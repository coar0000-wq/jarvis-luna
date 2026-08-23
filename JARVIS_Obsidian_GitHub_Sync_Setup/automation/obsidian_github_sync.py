#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JARVIS LUNA의 Obsidian 전용 작업 폴더를 GitHub와 안전하게 동기화합니다.

이 스크립트는 Obsidian 볼트 전체가 아니라 `workspace_subfolder`로 지정한
전용 폴더만 관리합니다. 그 밖의 사용자 노트는 읽거나 수정하지 않습니다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG = SCRIPT_DIR / "obsidian_sync_config.json"
DEFAULT_EXAMPLE = SCRIPT_DIR / "obsidian_sync_config.example.json"
SYNC_STATUS_PATH = REPO_ROOT / "data" / "obsidian_sync_status.json"


class SyncError(RuntimeError):
    """사용자에게 안전하게 보여줄 수 있는 동기화 오류입니다."""


@dataclass(frozen=True)
class SyncConfig:
    vault_path: Path
    workspace_subfolder: str
    remote_name: str
    branch: str
    git_author_name: str
    git_author_email: str

    @property
    def vault_workspace(self) -> Path:
        return self.vault_path / self.workspace_subfolder

    @property
    def repository_workspace(self) -> Path:
        return REPO_ROOT / "obsidian" / self.workspace_subfolder

    @property
    def manifest_path(self) -> Path:
        return self.vault_workspace / ".jarvis_sync_manifest.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_config(path: Path) -> SyncConfig:
    if not path.exists():
        raise SyncError(
            f"설정 파일을 찾을 수 없습니다: {path}\n"
            f"{DEFAULT_EXAMPLE.name} 파일을 복사해 vault_path를 실제 Obsidian 볼트 경로로 바꾸세요."
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SyncError(f"설정 파일 JSON 형식 오류: {error}") from error

    vault_path = Path(str(raw.get("vault_path", "")).strip()).expanduser()
    workspace_subfolder = str(raw.get("workspace_subfolder", "JARVIS_LUNA")).strip().replace("\\", "/").strip("/")
    if not raw.get("vault_path"):
        raise SyncError("vault_path에 실제 Obsidian 볼트 전체 경로를 입력하세요.")
    if not workspace_subfolder or workspace_subfolder.startswith("..") or "/../" in workspace_subfolder:
        raise SyncError("workspace_subfolder에는 볼트 내부의 안전한 하위 폴더명만 입력하세요.")

    return SyncConfig(
        vault_path=vault_path,
        workspace_subfolder=workspace_subfolder,
        remote_name=str(raw.get("remote_name", "origin")).strip() or "origin",
        branch=str(raw.get("branch", "main")).strip() or "main",
        git_author_name=str(raw.get("git_author_name", "JARVIS Obsidian Sync")).strip() or "JARVIS Obsidian Sync",
        git_author_email=str(raw.get("git_author_email", "obsidian-sync@local")).strip() or "obsidian-sync@local",
    )


def run(command: list[str], *, cwd: Path = REPO_ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, encoding="utf-8", errors="replace")
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "알 수 없는 명령 실행 오류"
        raise SyncError(f"명령 실행 실패: {' '.join(command)}\n{message}")
    return result


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], check=check)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def iter_files(root: Path) -> dict[str, Path]:
    if not root.exists():
        return {}

    files: dict[str, Path] = {}
    for item in root.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        relative = item.relative_to(root).as_posix()
        if relative.startswith(".") or "/." in relative:
            continue
        files[relative] = item
    return files


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "files": {}}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and isinstance(loaded.get("files"), dict):
            return loaded
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": 1, "files": {}}


def load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def copy_file(source: Path, destination: Path, *, dry_run: bool) -> None:
    if dry_run:
        print(f"[DRY RUN] 복사: {source} -> {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def write_conflict_copy(source: Path, destination_root: Path, relative: str, label: str, *, dry_run: bool) -> Path:
    original = Path(relative)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    conflict_name = f"{original.stem}.{label}-conflict-{timestamp}{original.suffix}"
    destination = destination_root / original.parent / conflict_name
    copy_file(source, destination, dry_run=dry_run)
    return destination


def ensure_clean_for_managed_sync(config: SyncConfig) -> None:
    result = git("status", "--porcelain")
    managed_prefixes = {
        config.repository_workspace.relative_to(REPO_ROOT).as_posix() + "/",
        "data/obsidian_sync_status.json",
    }
    unmanaged: list[str] = []
    for line in result.stdout.splitlines():
        path = line[3:].strip().replace("\\", "/")
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[-1]
        if not any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in managed_prefixes):
            unmanaged.append(path)
    if unmanaged:
        joined = ", ".join(unmanaged[:5])
        suffix = " …" if len(unmanaged) > 5 else ""
        raise SyncError(
            "동기화 전에 저장소에 관리 대상 밖의 변경사항이 있습니다. "
            f"먼저 커밋 또는 정리한 뒤 다시 실행하세요: {joined}{suffix}"
        )


def pull_remote(config: SyncConfig, *, dry_run: bool) -> None:
    if dry_run:
        print(f"[DRY RUN] git pull --ff-only {config.remote_name} {config.branch}")
        return
    git("pull", "--ff-only", config.remote_name, config.branch)


def synchronize_workspace(config: SyncConfig, *, dry_run: bool) -> dict[str, int]:
    repository_root = config.repository_workspace
    vault_root = config.vault_workspace
    repository_root.mkdir(parents=True, exist_ok=True)
    vault_root.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(config.manifest_path)
    previous = manifest.get("files", {})
    repository_files = iter_files(repository_root)
    vault_files = iter_files(vault_root)
    results = {"repo_to_vault": 0, "vault_to_repo": 0, "conflicts": 0, "unchanged": 0}

    for relative in sorted(set(repository_files) | set(vault_files)):
        repository_file = repository_files.get(relative)
        vault_file = vault_files.get(relative)

        if repository_file is None and vault_file is not None:
            copy_file(vault_file, repository_root / relative, dry_run=dry_run)
            results["vault_to_repo"] += 1
            continue
        if vault_file is None and repository_file is not None:
            copy_file(repository_file, vault_root / relative, dry_run=dry_run)
            results["repo_to_vault"] += 1
            continue

        assert repository_file is not None and vault_file is not None
        repository_hash = sha256(repository_file)
        vault_hash = sha256(vault_file)
        if repository_hash == vault_hash:
            results["unchanged"] += 1
            continue

        previous_hash = str(previous.get(relative, {}).get("hash", ""))
        repository_changed = repository_hash != previous_hash
        vault_changed = vault_hash != previous_hash

        if vault_changed and not repository_changed:
            copy_file(vault_file, repository_file, dry_run=dry_run)
            results["vault_to_repo"] += 1
        elif repository_changed and not vault_changed:
            copy_file(repository_file, vault_file, dry_run=dry_run)
            results["repo_to_vault"] += 1
        else:
            # 첫 실행에서 양쪽 파일이 다를 때 또는 동시에 변경됐을 때는
            # 로컬 볼트 내용을 우선 보존하고 GitHub 버전은 충돌 사본으로 남깁니다.
            conflict = write_conflict_copy(repository_file, vault_root, relative, "github", dry_run=dry_run)
            copy_file(vault_file, repository_file, dry_run=dry_run)
            print(f"충돌 보존: {relative} (GitHub 사본: {conflict.name})")
            results["vault_to_repo"] += 1
            results["conflicts"] += 1

    if not dry_run:
        refreshed_repository_files = iter_files(repository_root)
        refreshed_vault_files = iter_files(vault_root)
        manifest_files: dict[str, dict[str, str]] = {}
        for relative in sorted(set(refreshed_repository_files) & set(refreshed_vault_files)):
            repository_hash = sha256(refreshed_repository_files[relative])
            vault_hash = sha256(refreshed_vault_files[relative])
            if repository_hash == vault_hash:
                manifest_files[relative] = {"hash": repository_hash}
        write_json(config.manifest_path, {"version": 1, "updated_at": utc_now(), "files": manifest_files})

    return results


def write_dashboard_note(config: SyncConfig, *, dry_run: bool) -> None:
    note_path = config.vault_workspace / "JARVIS Dashboard Sync.md"
    note = (
        "# JARVIS LUNA · GitHub 동기화\n\n"
        "- 동기화 대상: 이 `JARVIS_LUNA` 폴더와 GitHub 저장소의 `obsidian/JARVIS_LUNA` 폴더\n"
        "- 이 폴더 밖의 Obsidian 노트는 자동화가 수정하지 않습니다.\n"
        "- 충돌이 생기면 `github-conflict` 사본이 남으므로 내용을 비교한 뒤 수동으로 정리하세요.\n"
    )
    if dry_run:
        print(f"[DRY RUN] 대시보드 노트 작성: {note_path}")
        return
    if not note_path.exists() or note_path.read_text(encoding="utf-8") != note:
        note_path.write_text(note, encoding="utf-8")


def write_status(config: SyncConfig, results: dict[str, int], error: str | None = None, *, dry_run: bool) -> None:
    change_count = results["repo_to_vault"] + results["vault_to_repo"] + results["conflicts"]
    existing = load_json_object(SYNC_STATUS_PATH)
    if error is None and existing.get("state") == "connected" and change_count == 0:
        # 빈 동기화마다 커밋을 만들지 않습니다. 마지막 성공 상태는 그대로 유지합니다.
        return

    payload = {
        "service": "obsidian",
        "mode": "local_bidirectional_git_sync",
        "connected": error is None,
        "state": "connected" if error is None else "error",
        "last_checked_at": utc_now(),
        "last_successful_sync_at": utc_now() if error is None else None,
        "workspace": f"obsidian/{config.workspace_subfolder}",
        "summary": results,
        "error": error,
    }
    if dry_run:
        print("[DRY RUN] 대시보드 상태 파일 갱신")
        return
    write_json(SYNC_STATUS_PATH, payload)


def commit_and_push(config: SyncConfig, *, dry_run: bool) -> None:
    managed_paths = [
        config.repository_workspace.relative_to(REPO_ROOT).as_posix(),
        "data/obsidian_sync_status.json",
    ]
    if dry_run:
        print(f"[DRY RUN] git add {' '.join(managed_paths)}")
        print(f"[DRY RUN] git commit / push {config.remote_name} {config.branch}")
        return

    git("config", "user.name", config.git_author_name)
    git("config", "user.email", config.git_author_email)
    git("add", "--", *managed_paths)
    staged = git("diff", "--cached", "--quiet", check=False)
    if staged.returncode == 0:
        print("GitHub에 반영할 변경사항이 없습니다.")
        return
    git("commit", "-m", f"chore: sync Obsidian workspace ({utc_now()})")
    git("push", config.remote_name, config.branch)


def execute(config: SyncConfig, *, dry_run: bool) -> None:
    if not config.vault_path.exists():
        raise SyncError(f"Obsidian 볼트 경로를 찾을 수 없습니다: {config.vault_path}")
    ensure_clean_for_managed_sync(config)
    pull_remote(config, dry_run=dry_run)
    write_dashboard_note(config, dry_run=dry_run)
    results = synchronize_workspace(config, dry_run=dry_run)
    write_status(config, results, dry_run=dry_run)
    commit_and_push(config, dry_run=dry_run)
    print(json.dumps({"status": "connected", "summary": results}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="JARVIS LUNA Obsidian·GitHub 양방향 동기화")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="동기화 설정 JSON 경로")
    parser.add_argument("--dry-run", action="store_true", help="파일·Git 변경 없이 동작만 점검")
    args = parser.parse_args()

    try:
        execute(load_config(args.config), dry_run=args.dry_run)
        return 0
    except SyncError as error:
        print(f"동기화 실패: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
