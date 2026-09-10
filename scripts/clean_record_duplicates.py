#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""옛 번호로 쌓인 레코드 중복본을 치운다.

왜 쌓였나
  expand_obsidian_graph.py 가 레코드 이름을 말뭉치 순번으로 지었다.

    record = f"Record {i:03d} · {slug(title)}"

  말뭉치는 회차마다 늘어난다. 그러면 같은 글이 회차마다 다른 번호를
  받고, 파일 이름에 번호가 들어가니 회차마다 새 파일이 하나 더 생긴다.

  같은 기사 하나가 이렇게 다섯 벌 있었다.

    Record-1199--J-beauty-pushes-overseas-as-Curél-and-Ci-Flavors-scale-gl.md
    Record-1205--...  Record-1216--...  Record-1221--...  Record-1224--...

  그런데 인덱스는 Record-1230 을 가리켰다. 디스크에 없는 번호다.
  다섯 벌은 아무도 안 가리키는 고아, 인덱스가 가리키는 한 벌은 없음.
  이것이 "끊어진 링크 107건" 의 정체다.

  노트가 3만에서 7만 6천으로 분 것도 같은 이유다. 새 자료가 그만큼
  들어온 게 아니라 같은 자료를 계속 다시 쓴 것이다.

무엇을 하나
  이름을 고정값으로 바꾼 뒤(expand_obsidian_graph.py) 이 스크립트를
  한 번 돌린다. 옛 번호 이름(Record-<숫자>--제목)을 가진 파일 중
  지금 아무 노트도 가리키지 않는 것을 지운다.

  가리키는 노트가 하나라도 있으면 지우지 않는다. 링크를 깨뜨리지
  않는 것이 먼저다.

  --apply 를 주지 않으면 세기만 하고 아무것도 안 지운다.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / "obsidian" / "JARVIS_LUNA"
RECORDS = VAULT / "Knowledge" / "Records"
REPORT = ROOT / "data" / "record_duplicates.json"

LINK = re.compile(r"\[\[([^\]|#]+)")
# 옛 이름: Record-1199--제목  (숫자 뒤에 대시 두 개)
OLD_NAME = re.compile(r"^Record-(\d+)--(.+)$")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="실제로 지운다. 안 주면 세기만 한다.")
    args = ap.parse_args()

    if not RECORDS.exists():
        print(f"레코드 폴더가 없다: {RECORDS}")
        return 1

    notes = list(VAULT.rglob("*.md"))
    print(f"볼트 노트 {len(notes):,}개")

    # 지금 어느 이름이 실제로 불리고 있나
    referenced: set[str] = set()
    for n in notes:
        try:
            text = n.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for raw in LINK.findall(text):
            t = nfc(raw.strip()).replace("\\", "/").rsplit("/", 1)[-1]
            if t.lower().endswith(".md"):
                t = t[:-3]
            referenced.add(t.casefold())

    # 옛 번호 이름을 제목별로 묶는다
    groups: dict[str, list[Path]] = defaultdict(list)
    old_files = 0
    for f in RECORDS.glob("*.md"):
        m = OLD_NAME.match(nfc(f.stem))
        if not m:
            continue
        old_files += 1
        groups[m.group(2).casefold()].append(f)

    orphan, kept = [], []
    for title, files in groups.items():
        for f in files:
            if nfc(f.stem).casefold() in referenced:
                kept.append(f.name)
            else:
                orphan.append(f)

    dup_titles = {t: len(fs) for t, fs in groups.items() if len(fs) > 1}
    print(f"옛 번호 파일 {old_files:,}개 · 서로 다른 제목 {len(groups):,}개")
    print(f"  같은 제목이 여러 벌인 것: {len(dup_titles):,}제목")
    if dup_titles:
        worst = sorted(dup_titles.items(), key=lambda x: -x[1])[:5]
        for t, c in worst:
            print(f"    {c}벌  {t[:60]}")
    print(f"  아무도 안 가리키는 것(지울 대상): {len(orphan):,}개")
    print(f"  아직 불리고 있어 두는 것: {len(kept):,}개")

    removed = 0
    if args.apply:
        for f in orphan:
            try:
                f.unlink()
                removed += 1
            except OSError as e:
                print(f"  못 지움 {f.name}: {type(e).__name__}")
        print(f"  지운 파일 {removed:,}개")
    else:
        print("  (--apply 없이 돌아 아무것도 지우지 않았다)")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "생성": datetime.now(timezone.utc).isoformat(),
        "만든이": "scripts/clean_record_duplicates.py",
        "왜": ("레코드 이름을 말뭉치 순번으로 지어서 같은 글이 회차마다 "
              "새 파일로 다시 써졌다. 인덱스는 새 번호를 가리키는데 "
              "디스크에는 옛 번호만 남아 링크가 끊어졌다."),
        "볼트_노트수": len(notes),
        "옛번호_파일수": old_files,
        "여러벌인_제목수": len(dup_titles),
        "고아_파일수": len(orphan),
        "아직_불리는_파일수": len(kept),
        "적용함": bool(args.apply),
        "지운_파일수": removed,
        "여러벌_상위": sorted(dup_titles.items(), key=lambda x: -x[1])[:50],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  보고서 -> {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
