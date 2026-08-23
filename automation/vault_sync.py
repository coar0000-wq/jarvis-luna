#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Obsidian 볼트 ↔ GitHub 양방향 동기화.

볼트가 곧 저장소이므로 별도의 복사 과정이 없다. 이 스크립트가 하는 일은
두 가지뿐이다.

  1) 내가 Obsidian에서 쓴 노트를 커밋해 올린다.
  2) GitHub Actions가 30분마다 만들어 올린 노트를 내려받는다.

--autostash 리베이스를 쓰므로 편집 중이던 내용이 있어도 충돌 없이 병합된다.
결과는 automation/vault_sync.log 에 남는다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAULT = "obsidian/JARVIS_LUNA"
LOG = ROOT / "automation" / "vault_sync.log"
KST = timezone(timedelta(hours=9))

steps: list[dict] = []


def run(*args) -> subprocess.CompletedProcess:
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    steps.append({"cmd": " ".join(args), "rc": p.returncode,
                  "out": (p.stdout or "").strip()[-300:],
                  "err": (p.stderr or "").strip()[-300:]})
    return p


def count_notes() -> int:
    d = ROOT / VAULT
    return sum(1 for _ in d.rglob("*.md")) if d.exists() else 0


def main() -> int:
    before = count_notes()

    # 1) 내가 볼트에서 편집한 내용 먼저 저장
    run("git", "add", "--", VAULT)
    staged = run("git", "diff", "--cached", "--quiet", "--", VAULT)
    pushed_local = False
    if staged.returncode != 0:
        stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        run("git", "commit", "-m", "Obsidian 볼트 편집 %s KST" % stamp)
        pushed_local = True

    # 2) 원격 반영분 내려받기 (편집 중이던 다른 파일은 autostash로 보존)
    run("git", "fetch", "origin", "main")
    rebase = run("git", "rebase", "--autostash", "origin/main")
    if rebase.returncode != 0:
        run("git", "rebase", "--abort")
        finish(before, False, "리베이스 충돌로 중단했습니다. 수동 확인이 필요합니다.")
        return 1

    # 3) 내 편집이 있으면 올리기
    push_ok = True
    if pushed_local:
        push_ok = run("git", "push", "origin", "HEAD:main").returncode == 0

    finish(before, push_ok, None)
    return 0 if push_ok else 1


def finish(before: int, ok: bool, message: str | None) -> None:
    after = count_notes()
    entry = {
        "at": datetime.now(KST).isoformat(),
        "notes_before": before,
        "notes_after": after,
        "notes_delta": after - before,
        "ok": ok,
        "message": message,
        "head": run("git", "rev-parse", "--short", "HEAD").stdout.strip(),
        "steps": steps,
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in entry.items() if k != "steps"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
