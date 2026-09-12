#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

PRODUCT = DATA / "daiso_products.json"
GOSI = DATA / "gosi.json"
OUTPUT = DATA / "listing_gate.json"


def load_json(path: Path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize_gosi(doc: dict) -> dict:
    items = doc.get("items", {})

    # list → dict 자동 변환 (충돌 방지)
    if isinstance(items, list):
        converted = {}
        for item in items:
            if isinstance(item, dict):
                pid = str(item.get("product_id", ""))
                if pid:
                    converted[pid] = item
        return converted

    if isinstance(items, dict):
        return items

    return {}


def main():
    product_doc = load_json(PRODUCT)
    gosi_doc = load_json(GOSI)

    products = product_doc.get("items", [])
    gosi_items = normalize_gosi(gosi_doc)

    results = []

    for row in products:
        pid = str(row.get("product_id", ""))
        g = gosi_items.get(pid, {})

        results.append({
            "product_id": pid,
            "name": row.get("name", ""),
            "price": row.get("price"),
            "category": row.get("category", ""),
            "volume": g.get("volume", ""),
            "maker": g.get("maker", ""),
            "origin": g.get("origin", ""),
            "ingredients": g.get("ingredients", ""),
            "warnings": g.get("warnings", ""),
            "ready": all([
                g.get("volume"),
                g.get("maker"),
                g.get("origin"),
                g.get("ingredients")
            ])
        })

    OUTPUT.write_text(
        json.dumps({
            "count": len(results),
            "items": results
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )

    print(f"listing_gate 생성 완료 : {len(results)}개")


if __name__ == "__main__":
    raise SystemExit(main())
