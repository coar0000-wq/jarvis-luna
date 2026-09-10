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
      
