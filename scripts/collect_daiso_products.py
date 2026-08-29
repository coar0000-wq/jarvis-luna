#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
JARVIS Agent 1 : DAISO Product Collector

출력:
    data/daiso_products.json

원칙:
- 실제 수집 데이터 우선
- 실패 시 기존 데이터 유지
- dashboard_runtime과 호환
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT = DATA_DIR / "daiso_products.json"

KST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/140 Safari/537.36"
    )
}

DAISO_URLS = [
    "https://shop.daiso.co.kr",
    "https://shop.daiso.co.kr/main",
]


def clean_price(text: str) -> int:
    nums = re.sub(r"[^0-9]", "", text or "")
    return int(nums) if nums else 0


def collect() -> list:
    products = []

    for url in DAISO_URLS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()

            soup = BeautifulSoup(r.text, "lxml")

            cards = soup.select(
                ".prd_item, .product-item, .goods-item, li[class*=product]"
            )

            for card in cards:

                name = (
                    card.get("data-name")
                    or (
                        card.select_one(".tit")
                        and card.select_one(".tit").get_text(" ", strip=True)
                    )
                    or (
                        card.select_one(".name")
                        and card.select_one(".name").get_text(" ", strip=True)
                    )
                    or (
                        card.select_one("img")
                        and card.select_one("img").get("alt", "")
                    )
                    or ""
                ).strip()

                if len(name) < 3:
                    continue

                price_txt = (
                    (
                        card.select_one(".price")
                        and card.select_one(".price").get_text(" ", strip=True)
                    )
                    or (
                        card.select_one(".num")
                        and card.select_one(".num").get_text(" ", strip=True)
                    )
                    or ""
                )

                price = clean_price(price_txt)

                category = (
                    card.get("data-category")
                    or (
                        card.select_one(".cate")
                        and card.select_one(".cate").get_text(" ", strip=True)
                    )
                    or "Lifestyle"
                )

                products.append(
                    {
                        "product": name,
                        "price_krw": price,
                        "category": category,
                        "brand": "Daiso",
                    }
                )

        except Exception:
            continue

    # 중복 제거
    seen = set()
    unique = []

    for p in products:
        key = p["product"].lower()

        if key in seen:
            continue

        seen.add(key)
        unique.append(p)

    return unique[:300]


def save(products: list):

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "updated_at": datetime.now(KST).isoformat(),
        "source": "Daiso Korea",
        "count": len(products),
        "products": products,
    }

    OUTPUT.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"✅ DAISO products: {len(products)} saved")


def main():

    products = collect()

    if not products and OUTPUT.exists():
        print("⚠️ Collection failed → keeping previous data")
        return

    save(products)


if __name__ == "__main__":
    main()
