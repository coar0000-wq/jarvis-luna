#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""공개 RSS 트렌드 수집 (Hacker News + 이커머스/리테일 뉴스).

무료 · API 키 불필요. 실패 시 해당 피드만 비우고 전체는 저장.

출력 data/public_trend_rss.json
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "public_trend_rss.json"

UA = "JARVIS-LUNA/1.0 (trend research; github.com/coar0000-wq/jarvis-luna)"
TIMEOUT = 25
DELAY = 1.0

# 이름, URL, 카테고리
FEEDS = [
    ("hacker_news_frontpage", "https://hnrss.org/frontpage", "tech"),
    ("hacker_news_best", "https://hnrss.org/best", "tech"),
    ("hacker_news_ecommerce", "https://hnrss.org/newest?q=ecommerce+OR+shopify+OR+retail", "ecommerce"),
    ("google_news_kbeauty", "https://news.google.com/rss/search?q=Korean+beauty+OR+K-beauty&hl=en-US&gl=US&ceid=US:en", "beauty"),
    ("google_news_shopify", "https://news.google.com/rss/search?q=Shopify+beauty+OR+DTC+skincare&hl=en-US&gl=US&ceid=US:en", "ecommerce"),
]

RELEVANT = re.compile(
    r"shopify|ecommerce|e-commerce|retail|beauty|skincare|cosmetic|k-?beauty|"
    r"korean\s+beauty|sunscreen|dtc|dropship|fulfillment|amazon|tiktok\s*shop",
    re.I,
)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, */*"})
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
            pub = (e.findtext("a:updated", default="", namespaces=ns)
                   or e.findtext("a:published", default="", namespaces=ns) or "")
            if title:
                items.append({"title": title, "url": link, "published": pub})
        return items
    for e in root.findall("./channel/item"):
        title = (e.findtext("title") or "").strip()
        link = (e.findtext("link") or "").strip()
        pub = (e.findtext("pubDate") or "").strip()
        if title:
            items.append({"title": title, "url": link, "published": pub})
    return items


def main() -> int:
    feeds_out = []
    relevant = []
    for name, url, cat in FEEDS:
        block = {"name": name, "category": cat, "url": url, "items": [], "error": None}
        try:
            items = parse_rss(fetch(url))
            block["items"] = items[:25]
            for it in items:
                if RELEVANT.search(it["title"]) or cat in ("beauty", "ecommerce"):
                    relevant.append({**it, "feed": name, "category": cat})
            time.sleep(DELAY)
        except Exception as e:
            block["error"] = f"{type(e).__name__}: {e}"
            time.sleep(DELAY)
        feeds_out.append(block)

    # 중복 제거
    seen = set()
    uniq = []
    for it in relevant:
        k = it["title"].lower()[:100]
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)

    payload = {
        "source": "public RSS (hnrss + Google News RSS)",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok" if any(f["items"] for f in feeds_out) else "empty",
        "feed_summaries": [
            {"name": f["name"], "count": len(f["items"]), "error": f["error"]}
            for f in feeds_out
        ],
        "relevant_count": len(uniq),
        "relevant_items": uniq[:60],
        "feeds": feeds_out,
        "note": "이커머스·뷰티 관련 공개 헤드라인. 수요 순위가 아니라 트렌드 보조 시그널.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"public_trend_rss.json → relevant={len(uniq)}")
    for f in feeds_out:
        print(f"  {f['name']}: {len(f['items'])} err={f['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
