#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Agent6 출력 파일
INFILE = DATA / "daiso_real" / "shopify_demand_matching.json"

# Agent7 생성 파일
OUT_JSON = DATA / "shopify_products.json"
OUT_CSV = DATA / "shopify_products.csv"


def load():
    """Agent6 JSON 자동 인식"""
    if not INFILE.exists():
        raise FileNotFoundError(INFILE)

    data = json.loads(INFILE.read_text(encoding="utf-8"))

    if isinstance(data, dict):
        if "top_recommendations" in data:
            return data["top_recommendations"]
        if "recommendations" in data:
            return data["recommendations"]
        if "products" in data:
            return data["products"]

    if isinstance(data, list):
        return data

    raise KeyError("top_recommendations / recommendations / products not found")


def clean_product(name: str) -> bool:
    """메뉴/로그인 제거"""
    bad = [
        "Join", "Sign in", "Track", "Rewards", "Gift Card",
        "Find a Store", "Order", "Help", "Privacy", "Cookie"
    ]
    return not any(x.lower() in name.lower() for x in bad)


def build():
    rows = []

    for idx, p in enumerate(load(), start=1):

        product = p.get("product", "").strip()

        if not clean_product(product):
            continue

        price = round((p.get("margin", 55) / 100 * 35) + 18.90, 2)

        rows.append({
            "Handle": product.lower().replace(" ", "-").replace("%", ""),
            "Title": product,
            "Body (HTML)": f"<p>{p.get('keyword','K-Beauty')} trending K-Beauty product.</p>",
            "Vendor": "JARVIS K-Beauty",
            "Product Category": "Beauty & Personal Care",
            "Type": "Skincare",
            "Tags": ",".join(p.get("matched_sources", [])),
            "Published": "TRUE",
            "Variant Price": price,
            "Variant SKU": f"JB-{idx:03d}",
            "Demand Score": p.get("demand_score", 80),
            "ROAS": p.get("expected_roas", 4.0)
        })

    return rows


def main():
    products = build()

    OUT_JSON.write_text(
        json.dumps(
            {
                "count": len(products),
                "products": products
            },
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=products[0].keys())
        writer.writeheader()
        writer.writerows(products)

    print(f"✅ Shopify Catalog : {len(products)} products")
    print(f"JSON → {OUT_JSON}")
    print(f"CSV  → {OUT_CSV}")


if __name__ == "__main__":
    main()
