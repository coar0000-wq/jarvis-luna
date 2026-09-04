#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Google Programmable Search (CSE) 수집 — 시크릿이 있을 때만.

환경변수
  GOOGLE_CSE_API_KEY
  GOOGLE_CSE_ID
  KNOWLEDGE_QUERIES  (쉼표/줄바꿈 구분, 없으면 기본 뷰티 쿼리)

키 없으면 status=skipped 로 저장하고 exit 0 (워크플로 실패 안 함).

출력 data/google_cse_results.json
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "google_cse_results.json"

UA = "JARVIS-LUNA/1.0"
TIMEOUT = 30
DELAY = 1.0

DEFAULT_QUERIES = [
    "K-beauty US best seller",
    "Korean sunscreen SPF50",
    "heartleaf toner",
    "snail mucin essence",
    "Korean sheet mask",
    "Daiso beauty products",
]


def queries_from_env() -> list[str]:
    raw = os.environ.get("KNOWLEDGE_QUERIES") or ""
    parts = re_split(raw)
    return parts or list(DEFAULT_QUERIES)


def re_split(raw: str) -> list[str]:
    out = []
    for line in raw.replace("\n", ",").split(","):
        q = line.strip()
        if q:
            out.append(q)
    return out


def cse_search(api_key: str, cx: str, q: str, num: int = 5) -> list[dict]:
    params = urllib.parse.urlencode({
        "key": api_key,
        "cx": cx,
        "q": q,
        "num": num,
        "hl": "en",
        "gl": "us",
    })
    url = f"https://www.googleapis.com/customsearch/v1?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        data = json.loads(res.read().decode("utf-8"))
    items = []
    for it in data.get("items") or []:
        items.append({
            "title": it.get("title"),
            "link": it.get("link"),
            "snippet": it.get("snippet"),
            "displayLink": it.get("displayLink"),
        })
    return items


def main() -> int:
    key = (os.environ.get("GOOGLE_CSE_API_KEY") or "").strip()
    cx = (os.environ.get("GOOGLE_CSE_ID") or "").strip()
    qs = queries_from_env()

    if not key or not cx:
        payload = {
            "status": "skipped",
            "reason": "GOOGLE_CSE_API_KEY 또는 GOOGLE_CSE_ID 없음",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "queries": qs,
            "results": [],
            "note": "Secrets에 키를 넣으면 다음 실행부터 수집됩니다.",
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("google_cse: skipped (no secrets)")
        return 0

    results = []
    errors = []
    for q in qs[:10]:
        try:
            hits = cse_search(key, cx, q, num=5)
            results.append({"query": q, "count": len(hits), "items": hits})
            time.sleep(DELAY)
        except Exception as e:
            errors.append({"query": q, "error": f"{type(e).__name__}: {e}"})
            results.append({"query": q, "count": 0, "items": [], "error": str(e)})
            time.sleep(DELAY)

    payload = {
        "status": "ok" if any(r["count"] for r in results) else "empty",
        "source": "Google Programmable Search API",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "query_count": len(qs[:10]),
        "results": results,
        "errors": errors,
        "note": "검색 트렌드 보완. 유료 쿼터 주의 — 쿼리 수 상한 10.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"google_cse_results.json → queries={len(results)} hits={sum(r['count'] for r in results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
