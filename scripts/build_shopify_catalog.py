#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import json, csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

INFILE = DATA / "shopify_demand_matching.json"
OUT_JSON = DATA / "shopify_products.json"
OUT_CSV = DATA / "shopify_products.csv"

def load():
    if not INFILE.exists():
        raise FileNotFoundError(INFILE)
    return json.loads(INFILE.read_text(encoding="utf-8"))["products"]

def build():
    rows = []
    for p in load():
        price = round((p["margin"] / 100 * 35) + 18.9, 2)
        rows.append({
            "Handle": p["product"].lower().replace(" ", "-").replace("%", ""),
            "Title": p["product"],
            "Body (HTML)": f"<p>{p['keyword']} trending K-Beauty product.</p>",
            "Vendor": "JARVIS K-Beauty",
            "Product Category": "Beauty & Personal Care",
            "Type": "Skincare",
            "Tags": ",".join(p["matched_sources"]),
            "Published": "TRUE",
            "Variant Price": price,
            "Variant SKU": f"JB-{p['rank']:03d}",
            "Demand Score": p["demand_score"],
            "ROAS": p["expected_roas"]
        })
    return rows

def main():
    products = build()

    OUT_JSON.write_text(
        json.dumps({"count": len(products), "products": products},
                   ensure_ascii=False, indent=2),
        encoding="utf-8"
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
