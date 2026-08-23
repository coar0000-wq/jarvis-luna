#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""전체 백업.

세 겹으로 남긴다.
  1) GitHub 원격 - 미커밋 변경을 커밋하고 푸시한 뒤 시점 태그를 붙인다.
  2) git bundle  - 전체 히스토리를 담은 단일 파일. 이것 하나로 저장소를 복원할 수 있다.
  3) ZIP         - .git 없이 현재 작업본 스냅샷. 깃 없이도 파일을 바로 꺼내 쓸 수 있다.

번들과 ZIP은 저장소 바깥(kms/_backups)에 둔다. 저장소를 부풀리지 않기 위해서다.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT.parent / "_backups"
KST = timezone(timedelta(hours=9))
STAMP = datetime.now(KST).strftime("%Y%m%d-%H%M")
TAG = "backup-%s-kst" % STAMP

EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", "_backups", "dist", "outputs"}
EXCLUDE_EXT = {".pyc"}

R: dict = {"stamp": STAMP, "tag": TAG, "steps": []}


def run(*args, cwd: Path = ROOT):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    R["steps"].append({"cmd": " ".join(args), "rc": p.returncode,
                       "out": (p.stdout or "")[-400:], "err": (p.stderr or "")[-400:]})
    return p


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)

    # 1) 원격 백업 --------------------------------------------------------
    run("git", "add", "-A")
    run("git", "commit", "-m", "JARVIS: 백업 시점 %s" % STAMP)
    run("git", "fetch", "origin", "main")
    run("git", "merge", "--no-edit", "origin/main")
    push = run("git", "push", "origin", "HEAD:main")
    head = run("git", "rev-parse", "HEAD").stdout.strip()

    run("git", "tag", "-f", "-a", TAG, "-m",
        "전체 백업 %s KST · 다이소 뷰티 수집 파이프라인 및 실데이터 대시보드까지" % STAMP)
    tag_push = run("git", "push", "-f", "origin", TAG)

    # 2) 번들 -------------------------------------------------------------
    bundle = DEST / ("jarvis-luna-%s.bundle" % STAMP)
    run("git", "bundle", "create", str(bundle), "--all")

    # 3) ZIP --------------------------------------------------------------
    zip_path = DEST / ("jarvis-luna-%s.zip" % STAMP)
    files = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for base, dirs, names in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for n in names:
                p = Path(base) / n
                if p.suffix in EXCLUDE_EXT:
                    continue
                try:
                    z.write(p, p.relative_to(ROOT).as_posix())
                    files += 1
                except OSError:
                    pass

    R["head"] = head
    R["push_rc"] = push.returncode
    R["tag_push_rc"] = tag_push.returncode
    R["artifacts"] = []
    for p in (bundle, zip_path):
        if p.exists():
            R["artifacts"].append({
                "path": str(p),
                "size_mb": round(p.stat().st_size / 1048576, 2),
                "sha256": sha256(p),
            })
    R["zip_file_count"] = files
    R["verified_bundle"] = run("git", "bundle", "verify", str(bundle)).returncode == 0
    R["remote_head"] = run("git", "rev-parse", "origin/main").stdout.strip()
    R["working_tree"] = run("git", "status", "--short", "-b").stdout[:400]
    R["SUCCESS"] = (R["push_rc"] == 0 and R["tag_push_rc"] == 0
                    and R["verified_bundle"] and len(R["artifacts"]) == 2
                    and R["head"] == R["remote_head"])

    (ROOT / "BACKUP_MANIFEST.json").write_text(
        json.dumps(R, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in R.items() if k != "steps"},
                     ensure_ascii=False, indent=2))
    return 0 if R["SUCCESS"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
