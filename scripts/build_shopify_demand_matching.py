#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "daiso_real" / "shopify_demand_matching.json"


def load(path):
    if not path.exists():
        return []

    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, dict) and "products" in obj:
            return obj["products"]
        return obj if isinstance(obj, list) else []
    except:
        return []


amazon = load(DATA / "amazon_products.json")
olive = load(DATA / "oliveyoung_us_products.json")
walmart = load(DATA / "walmart_products.json")
beauty = load(DATA / "us_beauty_products.json")

pool = {}


def add(name, source):
    if not name:
        return

    key = name.lower().strip()

    if key not in pool:
        pool[key] = {
            "product": name,
            "matched_sources": []
        }

    if source not in pool[key]["matched_sources"]:
        pool[key]["matched_sources"].append(source)


for p in amazon:
    add(p.get("name") or p.get("title"), "Amazon")

for p in olive:
    add(p.get("product") or p.get("title"), "OliveYoung US")

for p in walmart:
    add(p.get("name") or p.get("title"), "Walmart Beauty")

for p in beauty:
    add(p.get("title") or p.get("name"), p.get("source", "Beauty"))


result = []

for item in pool.values():

    matched = len(item["matched_sources"])

    demand_score = min(98, 55 + matched * 12)
    predicted_orders = 35 + matched * 28
    expected_roas = round(2.8 + matched * 0.45, 1)

    if matched >= 4:
        competition = "Low"
    elif matched >= 2:
        competition = "Medium"
    else:
        competition = "High"

    result.append({
        "keyword": item["product"].split()[0],
        "product": item["product"],
        "demand_score": demand_score,
        "competition": competition,
        "predicted_orders": predicted_orders,
        "expected_roas": expected_roas,
        "matched_sources": item["matched_sources"]
    })

result = sorted(
    result,
    key=lambda x: x["demand_score"],
    reverse=True
)[:20]

OUT.parent.mkdir(parents=True, exist_ok=True)

OUT.write_text(
    json.dumps(
        {
            "updated_at": "AUTO",
            "top_recommendations": result
        },
        ensure_ascii=False,
        indent=2
    ),
    encoding="utf-8"
)

print(f"✅ Generated {len(result)} Shopify demand products")
