#!/usr/bin/env python3
"""
JARVIS Real Knowledge Sync
+ US Beauty Market Knowledge
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "knowledge"

USER_AGENT = "Mozilla/5.0 (JARVIS LUNA)"

# -----------------------------
# HTTP
# -----------------------------
def fetch(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def clean(txt):
    return re.sub(r"\s+", " ", txt or "").strip()


# -----------------------------
# arXiv
# -----------------------------
def collect_arxiv():

    url = (
        "https://export.arxiv.org/api/query?"
        + urllib.parse.urlencode({
            "search_query": "cat:cs.AI",
            "max_results": 10,
            "sortBy": "submittedDate",
            "sortOrder": "descending"
        })
    )

    root = ET.fromstring(fetch(url))
    ns = {"a": "http://www.w3.org/2005/Atom"}

    items = []

    for e in root.findall("a:entry", ns):
        items.append({
            "title": clean(e.findtext("a:title", namespaces=ns)),
            "published": clean(e.findtext("a:published", namespaces=ns)),
            "url": next(
                (
                    x.attrib["href"]
                    for x in e.findall("a:link", ns)
                    if x.attrib.get("rel") == "alternate"
                ),
                ""
            )
        })

    return {
        "status": "ok",
        "source": "arXiv",
        "items": items
    }


# -----------------------------
# YouTube RSS
# -----------------------------
# 워크플로가 YOUTUBE_CHANNEL_IDS 시크릿을 주입하지만 예전 코드는 읽지 않았다.
# 하드코딩된 UC2M9hZkM4RCHaOaUybJ4V7Q 는 404 라 수집이 0건이었다.
# RSS 는 API 키가 필요 없으므로 유효한 채널 ID 만 있으면 바로 수집된다.
CHANNELS = [
    c.strip() for c in (os.environ.get("YOUTUBE_CHANNEL_IDS") or "").replace("\n", ",").split(",")
    if c.strip()
]


def collect_youtube():

    ns = {
        "a": "http://www.w3.org/2005/Atom"
    }

    items = []
    errors = []

    if not CHANNELS:
        return {
            "status": "not_configured",
            "source": "YouTube RSS",
            "reason": "YOUTUBE_CHANNEL_IDS 시크릿이 비어 있음. 채널 ID 를 쉼표로 구분해 설정하면 수집된다.",
            "channels_configured": 0,
            "items": [],
        }

    for cid in CHANNELS:

        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"

        try:
            root = ET.fromstring(fetch(url))

            for e in root.findall("a:entry", ns):
                items.append({
                    "title": clean(e.findtext("a:title", namespaces=ns)),
                    "published": clean(e.findtext("a:published", namespaces=ns)),
                    "url": next(
                        (
                            x.attrib["href"]
                            for x in e.findall("a:link", ns)
                        ),
                        ""
                    )
                })
        except Exception as e:
            errors.append({"channel_id": cid, "error": f"{type(e).__name__}: {e}"})

    return {
        "status": "ok" if items else "failed",
        "source": "YouTube RSS",
        "reason": "" if items else "설정된 채널에서 수집된 항목이 없음",
        "channels_configured": len(CHANNELS),
        "errors": errors,
        "items": items,
    }


# -----------------------------
# Google News RSS
# -----------------------------
QUERIES = [
    "K-Beauty skincare",
    "Shopify ecommerce AI",
    "TikTok beauty trend"
]


def collect_google():

    items = []

    for q in QUERIES:

        url = (
            "https://news.google.com/rss/search?"
            + urllib.parse.urlencode({
                "q": q,
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en"
            })
        )

        try:
            root = ET.fromstring(fetch(url))

            for e in root.findall("./channel/item"):
                items.append({
                    "query": q,
                    "title": clean(e.findtext("title")),
                    "published": clean(e.findtext("pubDate")),
                    "url": clean(e.findtext("link"))
                })

        except Exception:
            pass

    return {
        "status": "ok",
        "source": "Google News",
        "items": items
    }


# -----------------------------
# NEW : US BEAUTY MARKET
# -----------------------------
def collect_us_beauty():

    items = [
        {
            "title": "Amazon Beauty Best Sellers",
            "category": "Beauty",
            "url": "https://www.amazon.com/Best-Sellers-Beauty/zgbs/beauty",
            "source": "Amazon US"
        },
        {
            "title": "Amazon Skincare Best Sellers",
            "category": "Skincare",
            "url": "https://www.amazon.com/Best-Sellers-Beauty-Skin-Care-Products/zgbs/beauty/11060451",
            "source": "Amazon US"
        },
        {
            "title": "TikTok Creative Center",
            "category": "Viral",
            "url": "https://ads.tiktok.com/business/creativecenter/inspiration/popular/products/pc/en",
            "source": "TikTok US"
        },
        {
            "title": "Google Trends US",
            "category": "Trend",
            "url": "https://trends.google.com/trends/explore?geo=US",
            "source": "Google"
        },
        {
            "title": "Ulta Skin Care",
            "category": "Beauty",
            "url": "https://www.ulta.com/shop/skin-care",
            "source": "Ulta"
        },
        {
            "title": "Sephora Skincare",
            "category": "Luxury",
            "url": "https://www.sephora.com/shop/skincare",
            "source": "Sephora"
        },
        {
            "title": "Target Beauty",
            "category": "Retail",
            "url": "https://www.target.com/c/beauty/-/N-5xu0o",
            "source": "Target"
        },
        {
            "title": "Walmart Beauty",
            "category": "Retail",
            "url": "https://www.walmart.com/browse/beauty/1085666",
            "source": "Walmart"
        }
    ]

    return {
        "status": "ok",
        "source": "US Beauty Market",
        "items": items
    }


# -----------------------------
# Save
# -----------------------------
def main():

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "arxiv": collect_arxiv(),
            "youtube": collect_youtube(),
            "google": collect_google(),
            "us_beauty": collect_us_beauty()
        }
    }

    out = DATA_DIR / "real_sources.json"

    out.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("Saved:", out)
    print("US Beauty Sources:", len(data["sources"]["us_beauty"]["items"]))


if __name__ == "__main__":
    main()
