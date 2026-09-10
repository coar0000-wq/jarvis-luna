#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""대소문자만 다른 같은 경로가 저장소에 둘씩 등록된 것을 걷어낸다.

무엇이 문제인가
  저장소에 이런 짝이 있다.

    obsidian/.../Record-1889--ASML-reports-transactions-under-its-...md
    obsidian/.../Record-1889--Asml-Reports-Transactions-Under-Its-...md

  리눅스는 다른 파일로 보고 윈도우는 같은 파일로 본다. 그래서 윈도우에서
  체크아웃하면 나중 것이 앞 것을 덮어쓴다. 덮인 쪽은 언제나 "수정됨" 으로
  남는다. git checkout -- 로 되돌려도 즉시 다시 더러워진다.

  실측 72개 파일이 그 상태였다. 그 탓에 git rebase 가 아예 안 됐고,
  푸시할 때마다 reset -> 파일 복원 -> 커밋을 반복해야 했다.

왜 생겼나
  expand_obsidian_graph.py 가 레코드 이름을 말뭉치 순번으로 지었다.
  회차마다 같은 글이 다른 번호를 받았고, 제목 대소문자도 수집 시점에 따라
  달라졌다. 그래서 같은 기사가 여러 이름으로 쌓였다.

  이름은 URL 해시로 바꿨다(2026-09-10). 새로 생기는 것은 막혔다.
  이 스크립트는 이미 쌓인 것을 걷어낸다.

무엇을 하나
  git 이 추적하는 경로를 대소문자 무시하고 묶는다. 한 묶음에 둘 이상이면
  하나만 남기고 나머지를 색인에서 뺀다(git rm --cached).

  디스크의 파일은 지우지 않는다. 색인에서만 뺀다. 윈도우에서는 어차피
  한 파일이라 지울 것도 없다.

  남길 하나는 그 이름을 실제로 가리키는 노트가 더 많은 쪽으로 고른다.
  같으면 정렬해서 첫 번째를 남긴다. 아무 근거 없이 고르지 않는다.

  --apply 를 주지 않으면 세기만 한다.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / "obsidian" / "JARVIS_LUNA"
REPORT = ROOT / "data" / "record_case_collisions.json"
LINK = re.compile(r"\[\[([^\]|#]+)")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def tracked() -> list[str]:
    out = git("ls-files", "obsidian/")
    return [ln for ln in out.splitlines() if ln.strip().endswith(".md")]


def link_counts() -> dict[str, int]:
    """어느 이름이 몇 번 불리는지 센다. 남길 쪽을 고르는 근거다."""
    n: dict[str, int] = defaultdict(int)
    if not VAULT.exists():
        return n
    for note in VAULT.rglob("*.md"):
        try:
            text = note.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for raw in LINK.findall(text):
            t = unicodedata.normalize("NFC", raw.strip()).replace("\\", "/")
            t = t.rsplit("/", 1)[-1]
            if t.lower().endswith(".md"):
                t = t[:-3]
            n[t] += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="실제로 색인에서 뺀다. 안 주면 세기만 한다.")
    args = ap.parse_args()

    paths = tracked()
    print(f"추적 중인 볼트 노트 {len(paths):,}개")

    groups: dict[str, list[str]] = defaultdict(list)
    for p in paths:
        groups[unicodedata.normalize("NFC", p).casefold()].append(p)
    dup = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"대소문자만 다른 짝 {len(dup):,}묶음 "
          f"· 관련 경로 {sum(len(v) for v in dup.values()):,}개")
    if not dup:
        print("걷어낼 것 없음")
        return 0

    counts = link_counts()
    keep, drop, decided = [], [], []
    for _, variants in sorted(dup.items()):
        hits = {p: counts.get(Path(p).stem, 0) for p in variants}
        total = sum(hits.values())

        # 한 묶음 전체가 아무 데도 안 불리면 통째로 뺀다.
        #
        # 실측하니 77쌍이 전부 그랬다. 순번이 회차마다 밀려서 인덱스는 새
        # 번호를 가리키고 이것들은 버려진 것이다. 아무도 안 가리키는 노트는
        # 그래프에서 떠 있는 점일 뿐이라 링크를 깨뜨리지 않는다.
        #
        # 하나라도 불리는 묶음은 하나만 남긴다. 링크를 깨뜨리지 않는 것이
        # 먼저다. 남길 쪽은 더 많이 불리는 쪽으로 고른다.
        if total == 0:
            drop.extend(sorted(variants))
            decided.append({
                "판정": "통째로 뺌",
                "사유": "묶음 전체가 아무 노트에서도 안 불린다",
                "뺌": [{"경로": p, "불린_횟수": 0} for p in sorted(variants)],
            })
            continue

        scored = sorted(variants, key=lambda p: (-hits[p], p))
        k, rest = scored[0], scored[1:]
        keep.append(k)
        drop.extend(rest)
        decided.append({
            "판정": "하나만 남김",
            "남김": k,
            "남긴_이유": f"불린 횟수 {hits[k]} (묶음 최다)",
            "뺌": [{"경로": r, "불린_횟수": hits[r]} for r in rest],
        })

    whole = sum(1 for d in decided if d["판정"] == "통째로 뺌")
    print(f"  통째로 뺄 묶음 {whole:,} · 하나만 남길 묶음 {len(decided) - whole:,}")
    print(f"  남길 것 {len(keep):,}개 · 색인에서 뺄 것 {len(drop):,}개")
    for d in decided[:4]:
        print(f"    [{d['판정']}] {d.get('남김') and Path(d['남김']).name[:52] or ''}")
        for x in d["뺌"][:2]:
            print(f"      뺌  {Path(x['경로']).name[:52]} (불린 {x['불린_횟수']})")

    removed = 0
    if args.apply:
        # 한 번에 넘기면 명령줄 길이 한계에 걸린다. 나눠서 부른다.
        for i in range(0, len(drop), 40):
            chunk = drop[i:i + 40]
            git("rm", "--cached", "--quiet", "--ignore-unmatch", *chunk)
            removed += len(chunk)
        print(f"  색인에서 뺀 경로 {removed:,}개 (디스크 파일은 그대로)")
    else:
        print("  (--apply 없이 돌아 아무것도 바꾸지 않았다)")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "생성": datetime.now(timezone.utc).isoformat(),
        "만든이": "scripts/fix_case_collisions.py",
        "왜": ("대소문자만 다른 같은 경로가 저장소에 둘씩 등록돼 있었다. "
              "윈도우는 같은 파일로 보므로 하나가 다른 하나를 덮고, "
              "덮인 쪽이 영구히 수정됨으로 남아 rebase 가 안 됐다."),
        "추적_노트수": len(paths),
        "충돌_묶음": len(dup),
        "남긴_경로수": len(keep),
        "뺀_경로수": removed if args.apply else 0,
        "적용함": bool(args.apply),
        "판정": decided,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  보고서 -> {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
