#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Google Trends / News — 뷰티 전용 수집기.

문제
----
기존 google_trends_us 는 geo=US 일간 RSS 전체를 넣어
야구·정치·TV 키워드가 수요 시그널로 섞였다.
S등급 채점에서는 이 채널을 쓰지 않는다 (MATCH_CHANNELS 제외).

이 스크립트는 뷰티 쿼리만 모아 data/google_trends_beauty.json 을 만든다.
대시보드 표시·키워드 보드용. 채점 본선에는 넣지 않는다.

피드
----
1) Google News RSS (뷰티 쿼리)
2) Google Trends daily RSS 를 뷰티 화이트리스트로 필터
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "google_trends_beauty.json"

UA = "JARVIS-LUNA/1.0 (beauty-trend research; github.com/coar0000-wq/jarvis-luna)"
TIMEOUT = 20
DELAY = 0.8

BEAUTY_QUERIES = [
    "K-beauty",
    "Korean sunscreen",
    "snail mucin",
    "heartleaf toner",
    "centella serum",
    "niacinamide serum",
    "retinol",
    "hyaluronic acid serum",
    "glass skin",
    "PDRN skincare",
    "collagen mask",
    "SPF 50 sunscreen",
]

BEAUTY_RE = re.compile(
    r"beauty|skincare|skin-?care|cosmetic|k-?beauty|korean\s+beauty|"
    r"sunscreen|spf|serum|toner|ampoule|essence|moisturizer|cleanser|"
    r"retinol|niacinamide|hyaluronic|ceramide|centella|cica|heartleaf|"
    r"snail\s*mucin|collagen|pdrn|glass\s*skin|makeup|lipstick|"
    r"sephora|ulta|olive\s*young|cosrx|anua|medicube",
    re.I,
)
NOISE_RE = re.compile(
    r"football|baseball|nba|nhl|soccer|election|trump|iran|schedule|"
    r"vs\s+\w+|announcer|cancelled|republican|democrat",
    re.I,
)

NEWS_TMPL = (
    "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
)
TRENDS_DAILY = "https://trends.google.com/trending/rss?geo=US"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "application/rss+xml,application/xml,*/*"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return res.read()


def parse_rss(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entries = root.findall("a:entry", ns)
    if entries:
        for e in entries:
            title = (e.findtext("a:title", default="", namespaces=ns) or "").strip()
            link = ""
            for l in e.findall("a:link", ns):
                if l.attrib.get("href") and not link:
                    link = l.attrib["href"]
            pub = (
                e.findtext("a:updated", default="", namespaces=ns)
                or e.findtext("a:published", default="", namespaces=ns)
                or ""
            )
            if title:
                items.append({"title": title, "url": link, "published": pub})
        return items
    for e in root.findall("./channel/item"):
        title = (e.findtext("title") or "").strip()
        link = (e.findtext("link") or "").strip()
        pub = (e.findtext("pubDate") or "").strip()
        approx = (e.findtext("{https://trends.google.com}approx_traffic") or "").strip()
        if title:
            row = {"title": title, "url": link, "published": pub}
            if approx:
                row["approx_traffic"] = approx
            items.append(row)
    return items


def keep(title: str) -> bool:
    if not title:
        return False
    if NOISE_RE.search(title) and not BEAUTY_RE.search(title):
        return False
    return bool(BEAUTY_RE.search(title))


def main() -> int:
    feeds = []
    kept = []

    for q in BEAUTY_QUERIES:
        url = NEWS_TMPL.format(q=urllib.parse.quote(q))
        block = {"name": f"news:{q}", "url": url, "items": [], "error": None}
        try:
            items = parse_rss(fetch(url))[:8]
            block["items"] = items
            for it in items:
                kept.append({**it, "feed": f"news:{q}", "query": q, "kind": "news"})
            time.sleep(DELAY)
        except Exception as e:
            block["error"] = f"{type(e).__name__}: {e}"
            time.sleep(DELAY)
        feeds.append(block)

    daily = {"name": "trends_daily_us", "url": TRENDS_DAILY, "items": [], "error": None}
    try:
        items = parse_rss(fetch(TRENDS_DAILY))
        daily["items"] = [it for it in items if keep(it["title"])][:15]
        daily["raw_count"] = len(items)
        daily["dropped_noise"] = len(items) - len(daily["items"])
        for it in daily["items"]:
            kept.append({**it, "feed": "trends_daily_us", "query": None, "kind": "trend"})
    except Exception as e:
        daily["error"] = f"{type(e).__name__}: {e}"
    feeds.append(daily)

    seen, uniq = set(), []
    for it in kept:
        k = it["title"].lower()[:90]
        if k in seen:
            continue
        seen.add(k)
        uniq.append({
            "keyword": it["title"],
            "product": it["title"],
            "sub": it.get("query") or it.get("feed"),
            "badge": it.get("approx_traffic") or "news",
            "url": it.get("url") or "",
            "kind": it.get("kind"),
            "beauty": True,
        })

    payload = {
        "source": "google news rss (beauty queries) + trends daily filtered",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok" if uniq else "empty",
        "note": "뷰티 키워드만. 채점 MATCH_CHANNELS 에는 넣지 않음. 대시보드 키워드 보드용.",
        "query_count": len(BEAUTY_QUERIES),
        "count": len(uniq),
        "items": uniq[:40],
        "feed_summaries": [
            {
                "name": f["name"],
                "count": len(f.get("items") or []),
                "error": f.get("error"),
                "dropped_noise": f.get("dropped_noise"),
            }
            for f in feeds
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"google_trends_beauty.json → {len(uniq)} items")
    for f in feeds:
        print(f"  {f['name']}: {len(f.get('items') or [])} err={f.get('error')}")
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
