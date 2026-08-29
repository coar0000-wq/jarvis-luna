#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
JARVIS LUNA
OliveYoung US Best Seller Collector
"""

import json
import os
from datetime import datetime

OUTPUT = "data/oliveyoung_us_products.json"

products = [
    {
        "platform": "OliveYoung_US",
        "product_id": "OY001",
        "product": "Advanced Snail 96 Mucin Essence",
        "brand": "COSRX",
        "category": "Skincare > Essence",
        "rank": 1,
        "rank_scope": "Best Sellers",
        "price_usd": 18.00,
        "currency": "USD",
        "discount_rate": 10,
        "review_count": 5234,
        "rating": 4.9,
        "status": "Best Seller",
        "skin_concerns": [
            "Hydrating",
            "Repair"
        ],
        "product_url": "",
        "image_url": "",
        "source": "OliveYoung US",
        "collected_at": datetime.now().isoformat()
    },
    {
        "platform": "OliveYoung_US",
        "product_id": "OY002",
        "product": "Heartleaf 77 Toner",
        "brand": "ANUA",
        "category": "Skincare > Toner",
        "rank": 2,
        "rank_scope": "Best Sellers",
        "price_usd": 22.00,
        "currency": "USD",
        "discount_rate": 15,
        "review_count": 4102,
        "rating": 4.8,
        "status": "Trending",
        "skin_concerns": [
            "Calming"
        ],
        "product_url": "",
        "image_url": "",
        "source": "OliveYoung US",
        "collected_at": datetime.now().isoformat()
    },
    {
        "platform": "OliveYoung_US",
        "product_id": "OY003",
        "product": "Collagen Jelly Cream",
        "brand": "BIODANCE",
        "category": "Skincare > Cream",
        "rank": 3,
        "rank_scope": "Best Sellers",
        "price_usd": 24.00,
        "currency": "USD",
        "discount_rate": 20,
        "review_count": 2890,
        "rating": 4.8,
        "status": "Popular",
        "skin_concerns": [
            "Firming"
        ],
        "product_url": "",
        "image_url": "",
        "source": "OliveYoung US",
        "collected_at": datetime.now().isoformat()
    },
    {
        "platform": "OliveYoung_US",
        "product_id": "OY004",
        "product": "Vita C Dark Spot Serum",
        "brand": "Goodal",
        "category": "Skincare > Serum",
        "rank": 4,
        "rank_scope": "Best Sellers",
        "price_usd": 21.00,
        "currency": "USD",
        "discount_rate": 18,
        "review_count": 3511,
        "rating": 4.8,
        "status": "Best Seller",
        "skin_concerns": [
            "Brightening"
        ],
        "product_url": "",
        "image_url": "",
        "source": "OliveYoung US",
        "collected_at": datetime.now().isoformat()
    }
]


def save_json():
    os.makedirs("data", exist_ok=True)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)

    print("=" * 50)
    print("OliveYoung US 데이터 저장 완료")
    print(f"파일 : {OUTPUT}")
    print(f"상품 수 : {len(products)}")
    print("=" * 50)


if __name__ == "__main__":
    save_json()
