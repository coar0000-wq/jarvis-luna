#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""미국 매체가 K뷰티를 어떻게 다루는지 모아 소싱 근거로 쓴다.

왜 만들었나
  "미국에서 한국 스킨·에센스가 인기다" 는 말은 맞지만, 그 말만으로
  상품을 고를 수는 없다. 어떤 성분과 어떤 제형이 실제로 기사화되는지
  세어보면 근거가 된다. 예를 들어 스네일 뮤신과 PDRN 이 Vogue 기사
  제목에 몇 번 나오는지는 검증 가능한 사실이다.

무엇이 아닌가
  이건 판매 데이터가 아니다. 매체 노출 신호다. 그래서 점수의 us_market_fit
  에는 넣지 않는다. 그건 미국 실판매 목록으로만 계산한다. 여기서 나온
  값은 어떤 상품군을 더 모을지 정하는 데 쓴다.

출처
  Google News RSS. 키가 필요 없고 robots.txt 가 /rss 를 막지 않는다.
  기사 제목만 읽는다. 본문은 가져오지 않는다.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "kbeauty_news.json"
UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"
TIMEOUT = 25
DELAY = 2.0

QUERIES = [
    '"K-beauty" skincare US sales',
    "Korean skincare essence serum trend United States",
    "K-beauty toner ampoule America popularity",
    "Korean beauty ingredient snail mucin PDRN centella",
    "K-beauty Amazon Ulta Sephora launch",
]

# 다이소 버킷과 같은 이름을 쓴다. 그래야 수집 목표에 바로 반영된다.
BUCKET_TERMS = {
    "스킨케어": ["essence", "serum", "ampoule", "toner", "moisturizer", "cream",
              "lotion", "mist", "skincare", "skin care", "glass skin"],
    "마스크팩": ["sheet mask", "mask", "pad", "patch"],
    "클렌징": ["cleanser", "cleansing", "double cleanse", "makeup remover"],
    "메이크업": ["cushion", "foundation", "tint", "lip", "concealer", "makeup"],
    "헤어케어": ["shampoo", "hair", "scalp", "treatment"],
    "바디케어": ["body wash", "body lotion", "hand cream", "deodorant"],
    "향수": ["perfume", "fragrance"],
}

# 미국 기사에서 반복되는 성분. 우리가 다이소에서 찾아야 할 단서다.
INGREDIENTS = [
    "snail mucin", "pdrn", "centella", "cica", "heartleaf", "houttuynia",
    "niacinamide", "hyaluronic", "ceramide", "peptide", "retinol",
    "vitamin c", "collagen", "rice", "propolis", "azelaic", "mugwort",
    "panthenol", "tranexamic", "exosome",
]


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return res.read()


def google_news(query: str) -> list[dict]:
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    root = ET.fromstring(fetch(url))
    out = []
    for e in root.findall("./channel/item"):
        title = (e.findtext("title") or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "url": (e.findtext("link") or "").strip(),
            "published": (e.findtext("pubDate") or "").strip(),
            "source": (e.findtext("source") or "").strip(),
            "query": query,
        })
    return out


def tally(items: list[dict]) -> tuple[dict, dict]:
    """기사 제목에서 상품군과 성분을 센다. 한 기사에서 같은 말은 한 번만."""
    buckets, ings = Counter(), Counter()
    for it in items:
        low = it["title"].lower()
        for bucket, terms in BUCKET_TERMS.items():
            if any(t in low for t in terms):
                buckets[bucket] += 1
        for ing in INGREDIENTS:
            if ing in low:
                ings[ing] += 1
    return dict(buckets), dict(ings)


def main() -> int:
    items, failed = [], []
    seen = set()
    for q in QUERIES:
        try:
            got = google_news(q)
        except (urllib.error.URLError, urllib.error.HTTPError, ET.ParseError, OSError) as e:
            failed.append({"query": q, "error": f"{type(e).__name__}: {e}"[:120]})
            continue
        for it in got:
            key = re.sub(r"\W+", "", it["title"].lower())[:80]
            if key in seen:
                continue
            seen.add(key)
            items.append(it)
        time.sleep(DELAY)

    buckets, ings = tally(items)
    total = sum(buckets.values()) or 1
    share = {k: round(v / total * 100, 1)
             for k, v in sorted(buckets.items(), key=lambda x: -x[1])}

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/collect_kbeauty_news.py",
        "출처": "Google News RSS (키 불필요). 기사 제목만 읽는다.",
        "성격": ("판매 데이터가 아니라 매체 노출 신호다. 점수의 us_market_fit 에는 "
               "넣지 않는다. 어떤 상품군을 더 모을지 정하는 데 쓴다."),
        "queries": QUERIES,
        "articles": len(items),
        "failed_queries": failed,
        "bucket_mentions": buckets,
        "bucket_share_pct": share,
        "ingredient_mentions": dict(sorted(ings.items(), key=lambda x: -x[1])),
        "items": items[:120],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for _ in range(4):
        OUT.write_text(body, encoding="utf-8")
        try:
            if json.loads(OUT.read_text(encoding="utf-8-sig"))["articles"] == len(items):
                break
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, KeyError):
            pass
        time.sleep(0.5)
    else:
        print("기록 검증 실패", file=sys.stderr)
        return 1

    print(f"기사 {len(items)}건 · 질의 {len(QUERIES)}개 (실패 {len(failed)})")
    print("상품군 언급 비중:", ", ".join(f"{k} {v}%" for k, v in list(share.items())[:6]))
    print("성분 언급:", ", ".join(f"{k} {v}" for k, v in
                              list(payload["ingredient_mentions"].items())[:8]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
