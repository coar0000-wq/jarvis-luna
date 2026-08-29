#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import json, csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

INFILE = DATA / "daiso_real" / "shopify_demand_matching.json"
OUT_JSON = DATA / "shopify_products.json"
OUT_CSV = DATA / "shopify_products.csv"


def load():
    if not INFILE.exists():
        raise FileNotFoundError(INFILE)

    data = json.loads(INFILE.read_text(encoding="utf-8"))

    if isinstance(data, dict):
        if "recommendations" in data:
            return data["recommendations"]
        if "products" in data:
            return data["products"]

    if isinstance(data, list):
        return data

    raise KeyError("recommendations/products not found")


def build():
    rows = []

    for i, p in enumerate(load(), start=1):
        price = round((p.get("margin", 50) / 100 * 35) + 18.9, 2)

        rows.append({
            "Handle": p["product"].lower().replace(" ", "-").replace("%", ""),
            "Title": p["product"],
            "Body (HTML)": f"<p>{p.get('keyword', 'K-Beauty')} trending K-Beauty product.</p>",
            "Vendor": "JARVIS K-Beauty",
            "Product Category": "Beauty & Personal Care",
            "Type": "Skincare",
            "Tags": ",".join(p.get("matched_sources", [])),
            "Published": "TRUE",
            "Variant Price": price,
            "Variant SKU": f"JB-{i:03d}",
            "Demand Score": p.get("demand_score", 80),
            "ROAS": p.get("expected_roas", 4.0),
        })

    return rows


def main():
    products = build()

    OUT_JSON.write_text(
        json.dumps(
            {"count": len(products), "products": products},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=products[0].keys())
        writer.writeheader()
        writer.writerows(products)

    print(f"✅ Shopify Catalog: {len(products)} products")
    print(f"JSON : {OUT_JSON}")
    print(f"CSV  : {OUT_CSV}")


if __name__ == "__main__":
    main()
