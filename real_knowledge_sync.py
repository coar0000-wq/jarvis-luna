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
# Learn With Shopify (@learnwithshopify) 기본 포함 — 무료 RSS
_DEFAULT_YT = ["UC7geKfz2-IH0rsgRBtHTm0g"]
_env_yt = [
    c.strip() for c in (os.environ.get("YOUTUBE_CHANNEL_IDS") or "").replace("\n", ",").split(",")
    if c.strip()
]
CHANNELS = list(dict.fromkeys(_env_yt + _DEFAULT_YT))


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
# Robotics
# -----------------------------
def collect_robotics():
    """scripts/collect_robotics.py 산출물을 코퍼스 소스로 합류시킨다.

    2026-09-04: 옵시디언 주제 로보틱스가 3건뿐이었다. 분류기는 정상이었고
    수집원에 로봇 자료가 없던 것이 원인이다. arXiv cs.RO / eess.SY 와
    로봇 매체 RSS 를 별도 수집기로 모으고 여기서 코퍼스에 넣는다.
    """
    path = Path(__file__).resolve().parent / "data" / "robotics_sources.json"
    try:
        d = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        return {"status": "failed", "source": "Robotics",
                "reason": f"{type(e).__name__} - scripts/collect_robotics.py 를 먼저 실행",
                "items": []}
    items = []
    for key in ("arxiv", "rss"):
        blk = (d.get("sources") or {}).get(key) or {}
        for x in blk.get("items") or []:
            t = (x.get("title") or "").strip()
            if not t:
                continue
            items.append({
                "title": t,
                "text": (x.get("summary") or "")[:400],
                "published": x.get("published") or "",
                "url": x.get("url") or "",
                "primary_category": x.get("primary_category"),
            })
    return {"status": "ok" if items else "empty",
            "source": "Robotics (arXiv cs.RO/eess.SY + IEEE Spectrum + Robot Report)",
            "reason": "" if items else "수집 항목 없음",
            "collected_at": d.get("generated_at", ""),
            "items": items}


# -----------------------------
# Institutions
# -----------------------------
def collect_institutions():
    """scripts/collect_institutions.py 산출물을 코퍼스 소스로 합류시킨다.

    투자은행·반도체·AI연구소·데이터분석 35개 기관의 공개 발표물(RSS·사이트맵)과
    학술 논문(OpenAlex)을 담는다. 항목마다 org·category·kind 를 그대로 넘겨
    옵시디언 분류가 기관과 분야를 함께 쓸 수 있게 한다.
    """
    path = Path(__file__).resolve().parent / "data" / "institution_sources.json"
    try:
        d = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        return {"status": "failed", "source": "Institutions",
                "reason": f"{type(e).__name__} - scripts/collect_institutions.py 를 먼저 실행",
                "items": []}
    items = []
    for x in d.get("items") or []:
        t = (x.get("title") or "").strip()
        if not t:
            continue
        items.append({
            "title": t,
            "text": (x.get("summary") or "")[:400],
            "published": x.get("date") or "",
            "url": x.get("url") or "",
            "org": x.get("org") or "",
            "category": x.get("category") or "",
            "kind": x.get("kind") or "",
            "venue": x.get("venue") or "",
        })
    return {"status": "ok" if items else "empty",
            "source": "Institutions (RSS + sitemap + OpenAlex, 35개 기관)",
            "reason": "" if items else "수집 항목 없음",
            "collected_at": d.get("collected_at", ""),
            "items": items}


# -----------------------------
# Save
# -----------------------------
def main():

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "arxiv": collect_arxiv(),
            "robotics": collect_robotics(),
            "institutions": collect_institutions(),
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
