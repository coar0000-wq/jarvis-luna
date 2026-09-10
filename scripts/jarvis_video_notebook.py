#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""영상 분석에 쓸 NotebookLM 노트북을 주제별로 고른다.

왜 주제별인가
  전에는 노트북 하나를 상수로 박아뒀다. 그런데 NotebookLM 은 그 노트북에
  들어 있는 소스를 통째로 보고 답한다. 주제가 섞이면 답도 섞인다.

  실제로 겪었다. 2026-09-10 에 지식그래프 영상을 넣으려고 노트북을 열어
  보니 마케팅 엔지니어 영상이 소스로 들어 있었다. 거기에 그래프 영상을
  더하면 "네트워크 지표만 뽑아줘" 라고 물어도 마케팅 내용이 딸려 온다.
  그래서 그래프용 노트북을 따로 만들었다.

  이 파일은 그 판단을 코드로 옮긴 것이다.

낱말표를 새로 만들지 않는다
  영상을 팀에 배정할 때 쓰는 표가 이미 scripts/team_routing.py 에 있다.
  표를 두 벌 두면 서로 어긋난다. 실제로 그 일이 있었다. 낱말표가
  ingest_youtube_links.py 와 ingest_youtube_channels.py 에 하나씩 있었고,
  한쪽에만 한글을 넣었더니 채널 영상 20건이 전부 knowledge 로 떨어졌다.

  그래서 여기서는 노트북별 keywords 만 본다. 그것도 못 고르면 default 다.

설정 자리
  data/jarvis_video_analysis.json 의 notebooks.
  노트북을 늘리려면 그 파일에 항목을 더한다. 코드는 안 고쳐도 된다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "data" / "jarvis_video_analysis.json"

# 설정 파일을 못 읽어도 멈추지 않게 최소값을 둔다. 다만 이 값이 쓰였다는
# 것은 설정이 깨졌다는 뜻이므로 결과에 그렇게 적는다.
FALLBACK = {
    "name": "JARVIS 일반 영상 분석",
    "url": "https://notebook.google.com/notebook/88638802-cf08-47ca-a3ec-12453818438a",
    "notebook_id": "88638802-cf08-47ca-a3ec-12453818438a",
    "keywords": [],
}


def load_cfg() -> dict:
    try:
        return json.loads(CFG.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def notebooks() -> dict:
    nb = (load_cfg().get("notebooks") or {})
    return nb if isinstance(nb, dict) and nb else {"default": FALLBACK}


def _hit(text: str, kw: str) -> bool:
    """영어는 단어 경계를 본다. 한글은 조사가 붙어 다녀 포함으로 본다.

    'ui' 를 그냥 넣었다가 Liquid Death 가 디자인팀으로 간 적이 있다.
    liq'ui'd 안에 들어 있었다. team_routing.py 에 같은 설명이 있다.
    """
    if kw.isascii():
        return bool(re.search(r"\b" + re.escape(kw) + r"\b", text))
    return kw in text


def pick(title: str = "", desc: str = "", url: str = "") -> tuple[str, dict, str]:
    """주제 키, 노트북, 고른 근거를 돌려준다."""
    nb = notebooks()
    blob = f"{title} {desc} {url}".lower()
    best_key, best_hits = "", []
    for key, spec in nb.items():
        if key == "default":
            continue
        hits = [k for k in (spec.get("keywords") or []) if _hit(blob, str(k).lower())]
        if len(hits) > len(best_hits):
            best_key, best_hits = key, hits
    if best_key:
        return best_key, nb[best_key], "낱말 적중: " + ", ".join(best_hits[:4])
    d = nb.get("default") or FALLBACK
    return "default", d, "걸리는 주제 없음 → default"


def analysis_plan(video_url: str, title: str = "", desc: str = "") -> dict:
    """영상 하나에 대한 분석 지시."""
    key, spec, why = pick(title, desc, video_url)
    return {
        "video_url": video_url,
        "title": title,
        "tool": "Google NotebookLM",
        "topic": key,
        "notebook_name": spec.get("name"),
        "notebook_url": spec.get("url"),
        "고른_근거": why,
        "steps": [
            f"1. {spec.get('url')} 를 연다",
            "2. 소스 추가 → 웹사이트 → video_url 을 붙여넣는다",
            "3. 무엇을 뽑을지 좁혀서 묻는다. 없는 것은 없다고 답하게 한다",
            "4. 결과를 data/knowledge 에 넣고 'NotebookLM 요약' 이라고 적는다",
        ],
        "주의": ("요약은 LLM 이 옮겨 적은 값이다. 숫자를 실측값으로 쓰지 않는다. "
               "자막은 우리가 직접 받지 않는다. youtube.com/robots.txt 가 "
               "/api/timedtext 를 막는다."),
    }


def main() -> int:
    if len(sys.argv) > 1:
        print(json.dumps(analysis_plan(sys.argv[1], " ".join(sys.argv[2:])),
                         ensure_ascii=False, indent=2))
        return 0
    nb = notebooks()
    print(f"노트북 {len(nb)}개")
    for key, spec in nb.items():
        kws = ", ".join(str(k) for k in (spec.get("keywords") or [])[:6]) or "(없음)"
        print(f"  [{key}] {spec.get('name')}")
        print(f"      {spec.get('url')}")
        print(f"      낱말: {kws}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
