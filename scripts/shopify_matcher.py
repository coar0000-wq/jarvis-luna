#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

DAISO_FILE = DATA / "daiso_products.json"
US_FILE = DATA / "us_beauty_products.json"
OUTPUT_FILE = DATA / "shopify_recommend.json"


def load_json(path):
    if not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


daiso = load_json(DAISO_FILE)
us = load_json(US_FILE)

daiso_products = daiso.get("products", [])
us_products = us.get("products", [])

recommend = []

for dp in daiso_products:

    title = dp.get("title", "")
    category = dp.get("category", "")
    price = dp.get("price", 0)

    best_score = 0
    matched = ""

    for up in us_products:

        us_title = up.get("title", "")

        score = 0

        for word in title.lower().split():
            if len(word) >= 3 and word in us_title.lower():
                score += 1

        if score > best_score:
            best_score = score
            matched = us_title

    recommend.append({
        "title": title,
        "category": category,
        "price_krw": price,
        "matched_product": matched,
        "match_score": best_score,
        "recommended": best_score >= 2
    })

output = {
    "updated": datetime.now(timezone.utc).isoformat(),
    "country": "US",
    "total_products": len(recommend),
    "recommended_count": len(
        [x for x in recommend if x["recommended"]]
    ),
    "products": recommend
}

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"추천 완료 : {len(recommend)}개 분석")
