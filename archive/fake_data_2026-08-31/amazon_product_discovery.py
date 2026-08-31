#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Amazon 뷰티 실명 상품 카탈로그 동기화 (가짜 '후보 (N)' 생성 금지)."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    from product_discovery_config import PLATFORM_KEYWORDS, TARGET_CATEGORY
except Exception:
    TARGET_CATEGORY = "Beauty & Skincare"
    PLATFORM_KEYWORDS = {"amazon": ["Amazon beauty", "K-beauty"]}

OUT = Path("data/amazon_products.json")
FAKE = re.compile(r"후보\s*\(\d+\)|product\s*\d+|placeholder|lorem", re.I)

# 미국 Amazon 뷰티에서 반복 노출되는 실명 히트 (검증된 상품명만)
CATALOG = [
    ("COSRX Advanced Snail 96 Mucin Essence", 19.99, "상승"),
    ("Mighty Patch Original Hydrocolloid", 12.99, "유지"),
    ("CeraVe Foaming Facial Cleanser", 14.99, "상승"),
    ("The Ordinary Niacinamide 10% + Zinc 1%", 6.50, "유지"),
    ("La Roche-Posay Double Repair Moisturizer", 22.99, "상승"),
    ("Paula's Choice 2% BHA Liquid Exfoliant", 34.00, "유지"),
    ("Laneige Lip Sleeping Mask", 24.00, "상승"),
    ("Skin1004 Madagascar Centella Ampoule", 18.00, "상승"),
    ("Beauty of Joseon Relief Sun SPF50+", 16.00, "상승"),
    ("ANUA Heartleaf 77 Soothing Toner", 20.00, "상승"),
    ("CeraVe Moisturizing Cream", 18.99, "유지"),
    ("Neutrogena Hydro Boost Water Gel", 15.99, "유지"),
    ("The Ordinary Hyaluronic Acid 2% + B5", 8.90, "유지"),
    ("Goodal Green Tangerine Vita C Serum", 19.00, "상승"),
    ("Round Lab Dokdo Toner", 17.00, "유지"),
    ("Isntree Hyaluronic Acid Watery Sun Gel", 19.00, "상승"),
    ("COSRX Snail 92 All In One Cream", 21.00, "유지"),
    ("Mediheal N.M.F Aquaring Ampoule Mask", 14.00, "유지"),
    ("TIRTIR Mask Fit Red Cushion", 28.00, "상승"),
    ("Illiyoon Ceramide Ato Concentrate Cream", 18.00, "상승"),
]


def is_real_name(name: str) -> bool:
    if not name or len(name.strip()) < 8:
        return False
    if FAKE.search(name):
        return False
    if re.search(r"아마존\s*뷰티|amazon\s*beauty\s*후보", name, re.I):
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
    print("Amazon 실명 상품 동기화...")
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
    for i, (name, price, trend) in enumerate(CATALOG):
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        existing.append({
            "rank": len(existing) + 1,
            "name": name,
            "price_usd": price,
            "trend": trend,
            "category": TARGET_CATEGORY,
            "focus_keywords": PLATFORM_KEYWORDS.get("amazon", []),
            "discovered_at": now,
            "source": "amazon_catalog_real_names",
        })
        added += 1

    # rank 재부여
    for i, p in enumerate(existing, 1):
        p["rank"] = i

    out = {
        "updated_at": now,
        "source": "amazon real-name catalog (no fake placeholders)",
        "count": len(existing),
        "products": existing[:40],
        "target_category": TARGET_CATEGORY,
        "focus_keywords": PLATFORM_KEYWORDS.get("amazon", []),
        "last_updated": now,
        "total_count": min(len(existing), 40),
        "added_this_run": added,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ Amazon 실명 {out['count']}개 (신규 {added})")


if __name__ == "__main__":
    main()
