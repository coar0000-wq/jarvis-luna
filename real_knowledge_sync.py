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
# Organic / Clean Skincare (YouTube 대체)
# -----------------------------
# 2026-09-10: YouTube RSS 는 robots.txt Disallow → 수집 중단.
# 대신 미국·글로벌에서 유기농·클린·비건 스킨케어를 파는 브랜드 웹 상품을
# 카탈로그로 등록한다. (공격적 크롤 없이 공개 상품명·브랜드·가격대만 사용)
# 출력: data/knowledge/organic_skincare_products.json + real_sources.organic_skincare

ORGANIC_SKINCARE_SITES = [
    {"brand": "Tata Harper", "site": "tataharperskincare.com", "focus": "organic skincare"},
    {"brand": "Farmacy Beauty", "site": "farmacybeauty.com", "focus": "farm-to-face clean beauty"},
    {"brand": "Youth To The People", "site": "youthtothepeople.com", "focus": "superfood vegan skincare"},
    {"brand": "Biossance", "site": "biossance.com", "focus": "squalane clean beauty"},
    {"brand": "Herbivore Botanicals", "site": "herbivorebotanicals.com", "focus": "botanical clean skincare"},
    {"brand": "True Botanicals", "site": "truebotanicals.com", "focus": "organic certified skincare"},
    {"brand": "Juice Beauty", "site": "juicebeauty.com", "focus": "organic juice-based skincare"},
    {"brand": "Weleda", "site": "weleda.com", "focus": "natural organic body & face"},
    {"brand": "Burt's Bees", "site": "burtsbees.com", "focus": "natural skincare"},
    {"brand": "Acure", "site": "acure.com", "focus": "clean affordable organic"},
    {"brand": "Mad Hippie", "site": "madhippie.com", "focus": "clean active serums"},
    {"brand": "Pacifica Beauty", "site": "pacificabeauty.com", "focus": "vegan clean beauty"},
    {"brand": "Pai Skincare", "site": "paiskincare.com", "focus": "organic sensitive skin"},
    {"brand": "Kinship", "site": "lovekinship.com", "focus": "probiotic clean skincare"},
    {"brand": "Ilia Beauty", "site": "iliabeauty.com", "focus": "clean makeup + skin tints"},
]

ORGANIC_SKINCARE_CATALOG = [
    {"product_id": "ORG_TH_01", "title": "Regenerating Cleanser", "brand": "Tata Harper", "category": "Cleanser", "price_usd": 88.0, "tags": ["organic", "cleanser"], "site": "tataharperskincare.com", "url": "https://www.tataharperskincare.com/"},
    {"product_id": "ORG_TH_02", "title": "Resurfacing Mask", "brand": "Tata Harper", "category": "Mask", "price_usd": 105.0, "tags": ["organic", "exfoliating"], "site": "tataharperskincare.com", "url": "https://www.tataharperskincare.com/"},
    {"product_id": "ORG_FA_01", "title": "Green Clean Makeup Removing Cleansing Balm", "brand": "Farmacy Beauty", "category": "Cleanser", "price_usd": 36.0, "tags": ["clean", "balm cleanser"], "site": "farmacybeauty.com", "url": "https://www.farmacybeauty.com/"},
    {"product_id": "ORG_FA_02", "title": "Honey Potion Renewing Antioxidant Hydration Mask", "brand": "Farmacy Beauty", "category": "Mask", "price_usd": 60.0, "tags": ["honey", "hydrating"], "site": "farmacybeauty.com", "url": "https://www.farmacybeauty.com/"},
    {"product_id": "ORG_YTTP_01", "title": "Superfood Antioxidant Cleanser", "brand": "Youth To The People", "category": "Cleanser", "price_usd": 39.0, "tags": ["vegan", "superfood"], "site": "youthtothepeople.com", "url": "https://www.youthtothepeople.com/"},
    {"product_id": "ORG_YTTP_02", "title": "Adaptogen Deep Moisture Cream", "brand": "Youth To The People", "category": "Moisturizer", "price_usd": 58.0, "tags": ["vegan", "moisturizer"], "site": "youthtothepeople.com", "url": "https://www.youthtothepeople.com/"},
    {"product_id": "ORG_BIO_01", "title": "Squalane + Vitamin C Dark Spot Serum", "brand": "Biossance", "category": "Serum", "price_usd": 72.0, "tags": ["squalane", "vitamin c"], "site": "biossance.com", "url": "https://www.biossance.com/"},
    {"product_id": "ORG_BIO_02", "title": "Squalane + Omega Repair Cream", "brand": "Biossance", "category": "Moisturizer", "price_usd": 54.0, "tags": ["squalane", "barrier"], "site": "biossance.com", "url": "https://www.biossance.com/"},
    {"product_id": "ORG_HB_01", "title": "Blue Tansy Resurfacing Clarity Mask", "brand": "Herbivore Botanicals", "category": "Mask", "price_usd": 48.0, "tags": ["botanical", "clarity"], "site": "herbivorebotanicals.com", "url": "https://www.herbivorebotanicals.com/"},
    {"product_id": "ORG_HB_02", "title": "Coco Rose Body Polish", "brand": "Herbivore Botanicals", "category": "Body", "price_usd": 36.0, "tags": ["body", "exfoliating"], "site": "herbivorebotanicals.com", "url": "https://www.herbivorebotanicals.com/"},
    {"product_id": "ORG_TB_01", "title": "Pure Radiance Oil", "brand": "True Botanicals", "category": "Oil", "price_usd": 110.0, "tags": ["organic", "face oil"], "site": "truebotanicals.com", "url": "https://truebotanicals.com/"},
    {"product_id": "ORG_TB_02", "title": "Chebula Active Serum", "brand": "True Botanicals", "category": "Serum", "price_usd": 90.0, "tags": ["organic", "serum"], "site": "truebotanicals.com", "url": "https://truebotanicals.com/"},
    {"product_id": "ORG_JB_01", "title": "Stem Cellular Anti-Wrinkle Moisturizer", "brand": "Juice Beauty", "category": "Moisturizer", "price_usd": 68.0, "tags": ["organic", "anti-aging"], "site": "juicebeauty.com", "url": "https://juicebeauty.com/"},
    {"product_id": "ORG_JB_02", "title": "Green Apple Brightening Peel", "brand": "Juice Beauty", "category": "Treatment", "price_usd": 48.0, "tags": ["organic", "peel"], "site": "juicebeauty.com", "url": "https://juicebeauty.com/"},
    {"product_id": "ORG_WL_01", "title": "Skin Food Original Ultra-Rich Cream", "brand": "Weleda", "category": "Moisturizer", "price_usd": 18.0, "tags": ["organic", "skin food"], "site": "weleda.com", "url": "https://www.weleda.com/"},
    {"product_id": "ORG_WL_02", "title": "Calendula Face Cream", "brand": "Weleda", "category": "Moisturizer", "price_usd": 22.0, "tags": ["calendula", "sensitive"], "site": "weleda.com", "url": "https://www.weleda.com/"},
    {"product_id": "ORG_BB_01", "title": "Sensitive Facial Cleanser with Cotton Extract", "brand": "Burt's Bees", "category": "Cleanser", "price_usd": 10.0, "tags": ["natural", "sensitive"], "site": "burtsbees.com", "url": "https://www.burtsbees.com/"},
    {"product_id": "ORG_BB_02", "title": "Hydrating Facial Mask with Honey", "brand": "Burt's Bees", "category": "Mask", "price_usd": 14.0, "tags": ["honey", "hydrating"], "site": "burtsbees.com", "url": "https://www.burtsbees.com/"},
    {"product_id": "ORG_AC_01", "title": "Brightening Facial Scrub", "brand": "Acure", "category": "Exfoliator", "price_usd": 10.0, "tags": ["clean", "scrub"], "site": "acure.com", "url": "https://www.acure.com/"},
    {"product_id": "ORG_AC_02", "title": "Radically Rejuvenating Whipped Night Cream", "brand": "Acure", "category": "Moisturizer", "price_usd": 20.0, "tags": ["night cream", "clean"], "site": "acure.com", "url": "https://www.acure.com/"},
    {"product_id": "ORG_MH_01", "title": "Vitamin C Serum", "brand": "Mad Hippie", "category": "Serum", "price_usd": 34.0, "tags": ["vitamin c", "clean"], "site": "madhippie.com", "url": "https://www.madhippie.com/"},
    {"product_id": "ORG_MH_02", "title": "Antioxidant Facial Oil", "brand": "Mad Hippie", "category": "Oil", "price_usd": 25.0, "tags": ["facial oil", "antioxidant"], "site": "madhippie.com", "url": "https://www.madhippie.com/"},
    {"product_id": "ORG_PC_01", "title": "Vegan Collagen Barrier Face Cream", "brand": "Pacifica Beauty", "category": "Moisturizer", "price_usd": 22.0, "tags": ["vegan", "collagen"], "site": "pacificabeauty.com", "url": "https://www.pacificabeauty.com/"},
    {"product_id": "ORG_PC_02", "title": "Glow Baby Vitamin C Booster Serum", "brand": "Pacifica Beauty", "category": "Serum", "price_usd": 17.0, "tags": ["vitamin c", "vegan"], "site": "pacificabeauty.com", "url": "https://www.pacificabeauty.com/"},
    {"product_id": "ORG_PAI_01", "title": "Rosehip BioRegenerate Oil", "brand": "Pai Skincare", "category": "Oil", "price_usd": 52.0, "tags": ["organic", "rosehip"], "site": "paiskincare.com", "url": "https://www.paiskincare.com/"},
    {"product_id": "ORG_PAI_02", "title": "Camellia & Geranium Gentle Cream Cleanser", "brand": "Pai Skincare", "category": "Cleanser", "price_usd": 36.0, "tags": ["organic", "sensitive"], "site": "paiskincare.com", "url": "https://www.paiskincare.com/"},
    {"product_id": "ORG_KN_01", "title": "Self Reflect Probiotic Moisturizing Sunscreen SPF 32", "brand": "Kinship", "category": "Sunscreen", "price_usd": 36.0, "tags": ["spf", "probiotic"], "site": "lovekinship.com", "url": "https://www.lovekinship.com/"},
    {"product_id": "ORG_KN_02", "title": "Supermelts Cleanse Meltaway Cleansing Balm", "brand": "Kinship", "category": "Cleanser", "price_usd": 28.0, "tags": ["cleanse", "balm"], "site": "lovekinship.com", "url": "https://www.lovekinship.com/"},
    {"product_id": "ORG_IL_01", "title": "Super Serum Skin Tint SPF 40", "brand": "Ilia Beauty", "category": "Tint + SPF", "price_usd": 48.0, "tags": ["clean", "spf", "tint"], "site": "iliabeauty.com", "url": "https://www.iliabeauty.com/"},
    {"product_id": "ORG_IL_02", "title": "The Base Face Milk SPF 20", "brand": "Ilia Beauty", "category": "Moisturizer", "price_usd": 48.0, "tags": ["clean", "spf"], "site": "iliabeauty.com", "url": "https://www.iliabeauty.com/"},
]


def collect_organic_skincare():
    """유기농·클린 스킨케어 판매 웹 상품 등록 (YouTube 슬롯 대체).

    robots.txt 위반 크롤 없이 공개 브랜드 라인업 기준 실상품명을 등록한다.
    """
    now = datetime.now(timezone.utc).isoformat()
    items = []
    for row in ORGANIC_SKINCARE_CATALOG:
        title = row["title"]
        brand = row["brand"]
        bits = [title, brand]
        if row.get("category"):
            bits.append(row["category"])
        if row.get("price_usd") is not None:
            bits.append(f'${row["price_usd"]}')
        if row.get("tags"):
            bits.append(", ".join(row["tags"]))
        items.append({
            "product_id": row["product_id"],
            "title": title,
            "product": title,
            "brand": brand,
            "category": row.get("category") or "",
            "price_usd": row.get("price_usd"),
            "tags": row.get("tags") or [],
            "site": row.get("site") or "",
            "url": row.get("url") or "",
            "text": " · ".join(str(b) for b in bits),
            "collected_at": now,
            "source": "organic_skincare_catalog",
        })

    prod_path = DATA_DIR / "organic_skincare_products.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": now,
        "sites": ORGANIC_SKINCARE_SITES,
        "count": len(items),
        "items": items,
        "note": "YouTube 수집 대체 · 유기농/클린 스킨케어 브랜드 웹 상품 카탈로그",
    }
    prod_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "status": "ok" if items else "empty",
        "source": "Organic Skincare Web",
        "reason": "" if items else "카탈로그 비어 있음",
        "sites": len(ORGANIC_SKINCARE_SITES),
        "items": items,
        "product_file": "data/knowledge/organic_skincare_products.json",
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
    """미국 뷰티 시장 신호. 링크 목록이 아니라 실제 수집분을 쓴다.

    예전에는 아마존·세포라 같은 사이트 주소 8개를 그대로 돌려주고
    "US뷰티 8건" 이라고 셌다. 링크는 데이터가 아니다. 그 주소들에서
    무엇을 봤는지는 하나도 들어있지 않았다.

    실제 수집분은 dashboard_runtime.json 의 global_channels 에 있다.
    올리브영US·틱톡샵·세포라·울타·아마존·월마트 등 12개 채널이고
    각 항목에 상품명·가격·평점·리뷰수가 들어있다. 그걸 코퍼스에 넣는다.
    """
    path = Path(__file__).resolve().parent / "data" / "dashboard_runtime.json"
    try:
        d = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        return {"status": "failed", "source": "US Beauty Market",
                "reason": f"{type(e).__name__} - dashboard_runtime.json 을 읽지 못함",
                "items": []}
    channels = d.get("global_channels") or {}
    status = d.get("global_channels_status") or {}
    items = []
    for ch, rows in channels.items():
        if not isinstance(rows, list):
            continue
        meta = status.get(ch) or {}
        for r in rows:
            name = (r.get("product") or r.get("name") or "").strip()
            if not name:
                continue
            bits = [name]
            if r.get("brand"):
                bits.append(str(r["brand"]))
            if r.get("price") is not None:
                bits.append(f'${r["price"]}')
            if r.get("rating"):
                bits.append(f'평점 {r["rating"]}')
            if r.get("review_count"):
                bits.append(f'리뷰 {r["review_count"]:,}')
            items.append({
                "title": name,
                "text": " · ".join(bits),
                "url": r.get("url") or "",
                "channel": ch,
                "brand": r.get("brand"),
                "price_usd": r.get("price"),
                "rating": r.get("rating"),
                "review_count": r.get("review_count"),
                "trust": meta.get("trust"),
                "collected_at": meta.get("collected_at"),
            })
    return {
        "status": "ok" if items else "empty",
        "source": "US Beauty Market (global_channels 실수집분)",
        "reason": "" if items else "global_channels 가 비었다",
        "channels": len(channels),
        "items": items,
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
            "organic_skincare": collect_organic_skincare(),
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
