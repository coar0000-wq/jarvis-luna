#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""볼트 노트의 깨진 tags 프론트매터를 실제 값으로 고친다.

무엇이 잘못됐나
  expand_obsidian_graph.py:82 에서 f 접두사가 빠져 있었다.
      "tags: [{', '.join(tags)}]\\n"     <- 문자 그대로 기록됨
      f"tags: [{', '.join(tags)}]\\n"    <- 고친 것
  그래서 노트 18,174개 전부가 tags 자리에 파이썬 코드 문자열을 갖고 있다.
  Obsidian 에서 태그 검색과 그래프 그룹핑이 동작하지 않는다.

방침
  노트는 누적이 맞다. 지우지 않는다. 프론트매터만 제자리에서 고친다.
  본문에서 실제 정보를 읽어 태그를 다시 만든다. 추측하지 않는다.
    - 출처 도메인 (arxiv.org, youtube.com 등)
    - 폴더 종류 (records / topics / sources)
  근거를 못 찾으면 그 노트는 건드리지 않고 남긴다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / "obsidian" / "JARVIS_LUNA"
BROKEN = "tags: [{', '.join(tags)}]"

DOMAIN_TAG = {
    "arxiv.org": "arxiv",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "shopify.com": "shopify",
    "reddit.com": "reddit",
    "openbeautyfacts.org": "open-beauty-facts",
    "oliveyoung.com": "oliveyoung",
    "daisomall.co.kr": "daiso",
    "fda.gov": "fda",
    "wikipedia.org": "wikipedia",
    "allure.com": "allure",
}


def tags_for(path: Path, text: str) -> list[str]:
    tags = ["knowledge-graph"]
    parent = path.parent.name.lower()
    if parent in ("records", "topics", "sources"):
        tags.append(parent.rstrip("s"))

    for m in re.finditer(r"https?://([^/\s\)\]]+)", text):
        host = m.group(1).lower().lstrip("www.")
        for dom, tag in DOMAIN_TAG.items():
            if host.endswith(dom):
                if tag not in tags:
                    tags.append(tag)
                break
    return tags


def main() -> int:
    apply = "--apply" in sys.argv
    if not VAULT.exists():
        print(f"볼트 없음: {VAULT}")
        return 1

    fixed = skipped = untouched = 0
    for p in VAULT.rglob("*.md"):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            skipped += 1
            continue
        if BROKEN not in text:
            untouched += 1
            continue
        tags = tags_for(p, text)
        if len(tags) <= 1:
            skipped += 1        # 근거 부족. 건드리지 않는다.
            continue
        new = text.replace(BROKEN, f"tags: [{', '.join(tags)}]", 1)
        if apply:
            try:
                p.write_text(new, encoding="utf-8")
            except OSError:
                skipped += 1
                continue
        fixed += 1

    mode = "적용" if apply else "미리보기 (실제 수정하려면 --apply)"
    print(f"[{mode}]")
    print(f"  고칠 노트   {fixed}개")
    print(f"  이미 정상   {untouched}개")
    print(f"  근거 부족   {skipped}개 (건드리지 않음)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
