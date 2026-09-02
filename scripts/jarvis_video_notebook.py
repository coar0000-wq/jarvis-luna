#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JARVIS 영상 분석 라우팅 — NotebookLM 노트북 고정.

YouTube/Shorts URL이 들어오면 분석 도구로 아래 노트북을 사용한다.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent if Path(__file__).resolve().parent.name == "scripts" else Path(__file__).resolve().parent
CFG = ROOT / "data" / "jarvis_video_analysis.json"

DEFAULT_NOTEBOOK = "https://notebook.google.com/notebook/88638802-cf08-47ca-a3ec-12453818438a"

def notebook_url() -> str:
    if CFG.exists():
        try:
            d = json.loads(CFG.read_text(encoding="utf-8"))
            return (d.get("primary_notebook") or {}).get("url") or DEFAULT_NOTEBOOK
        except Exception:
            pass
    return DEFAULT_NOTEBOOK

def analysis_plan(video_url: str) -> dict:
    """영상 URL에 대한 JARVIS 분석 지시."""
    return {
        "video_url": video_url,
        "tool": "Google NotebookLM",
        "notebook_url": notebook_url(),
        "steps": [
            "1. notebook_url 노트북을 연다",
            "2. video_url 을 소스로 추가(또는 기존 소스에서 선택)",
            "3. 요약·액션아이템·Shopify 적용 포인트를 추출한다",
            "4. 결과를 data/knowledge 또는 shopify_learn 노트에 반영한다",
        ],
    }

if __name__ == "__main__":
    print(json.dumps({"notebook_url": notebook_url()}, ensure_ascii=False, indent=2))
