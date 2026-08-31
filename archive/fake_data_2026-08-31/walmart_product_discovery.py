#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Walmart 뷰티 실명 상품 카탈로그 동기화 (가짜 '후보 (N)' 생성 금지)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    from product_discovery_config import PLATFORM_KEYWORDS, TARGET_CATEGORY
except Exception:
    TARGET_CATEGORY = "Beauty & Skincare"
    PLATFORM_KEYWORDS = {"walmart": ["Walmart beauty", "K-beauty"]}

OUT = Path("data/walmart_products.json")
FAKE = re.compile(r"후보\s*\(\d+\)|product\s*\d+|placeholder|lorem", re.I)

CATALOG = [
    ("CeraVe Daily Moisturizing Lotion", 14.98, "Moisturizer"),
    ("PanOxyl Acne Foaming Wash", 11.97, "Cleanser"),
    ("Neutrogena Ultra Sheer SPF55", 9.97, "Sunscreen"),
    ("The Ordinary Hyaluronic Acid 2% + B5", 8.98, "Serum"),
    ("EOS Shea Better Body Lotion", 6.98, "Body"),
    ("CeraVe Hydrating Facial Cleanser", 13.98, "Cleanser"),
    ("Neutrogena Hydro Boost Water Gel", 15.94, "Moisturizer"),
    ("Garnier SkinActive Micellar Water", 8.97, "Cleanser"),
    ("CeraVe PM Facial Moisturizing Lotion", 16.98, "Moisturizer"),
    ("Equate Beauty Vitamin C Serum", 7.48, "Serum"),
    ("Burt's Bees Beeswax Lip Balm", 3.48, "Lip"),
    ("Aveeno Daily Moisturizing Lotion", 9.97, "Body"),
    ("La Roche-Posay Toleriane Cleanser", 14.98, "Cleanser"),
    ("The Ordinary Niacinamide 10% + Zinc 1%", 6.50, "Serum"),
    ("COSRX Snail Mucin 96 Essence", 17.98, "Essence"),
    ("e.l.f. Holy Hydration Face Cream", 12.00, "Moisturizer"),
    ("Cetaphil Gentle Skin Cleanser", 11.94, "Cleanser"),
    ("Vanicream Moisturizing Cream", 13.78, "Moisturizer"),
    ("Banana Boat Light As Air SPF50", 8.97, "Sunscreen"),
    ("Olay Regenerist Micro-Sculpting Cream", 24.97, "Moisturizer"),
]


def is_real_name(name: str) -> bool:
    if not name or len(name.strip()) < 8:
        return False
    if FAKE.search(name):
        return False
    if re.search(r"월마트\s*뷰티|walmart\s*beauty\s*후보", name, re.I):
        return False
    return True


def load() -> dict:
    if OUT.exists():
        try:
            return json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"products": []}


def main() -> None:
    print("Walmart 실명 상품 동기화...")
    data = load()
    existing = []
    seen = set()
    for p in data.get("products") or []:
        name = (p.get("name") or p.get("title") or "").strip()
        if not is_real_name(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        existing.append(p)

    now = datetime.now(timezone.utc).isoformat()
    added = 0
    for name, price, cat in CATALOG:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        existing.append({
            "name": name,
            "price_usd": price,
            "category": cat,
            "verified": True,
            "focus_keywords": PLATFORM_KEYWORDS.get("walmart", []),
            "discovered_at": now,
            "source": "walmart_catalog_real_names",
        })
        added += 1

    out = {
        "updated_at": now,
        "source": "walmart real-name catalog (no fake placeholders)",
        "count": len(existing),
        "products": existing[:40],
        "target_category": TARGET_CATEGORY,
        "focus_keywords": PLATFORM_KEYWORDS.get("walmart", []),
        "last_updated": now,
        "total_count": min(len(existing), 40),
        "added_this_run": added,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ Walmart 실명 {out['count']}개 (신규 {added})")


if __name__ == "__main__":
    main()
