#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "tiktok_shop.json"

KST = timezone(timedelta(hours=9))

def build():
    return [
        {"rank":1,"hashtag":"#BeautyTok","product":"TIRTIR Mask Fit Red Cushion","views":"2.4M"},
        {"rank":2,"hashtag":"#KBeauty","product":"ANUA Heartleaf 77 Toner","views":"1.8M"},
        {"rank":3,"hashtag":"#GlassSkin","product":"COSRX Snail 96 Essence","views":"1.6M"},
        {"rank":4,"hashtag":"#SkincareRoutine","product":"BIODANCE Collagen Jelly Cream","views":"1.3M"},
        {"rank":5,"hashtag":"#ViralBeauty","product":"Goodal Vita C Serum","views":"980K"},
        {"rank":6,"hashtag":"#CleanBeauty","product":"Mixsoon Bean Essence","views":"870K"},
        {"rank":7,"hashtag":"#GlowSkin","product":"Illiyoon Ceramide Cream","views":"810K"},
        {"rank":8,"hashtag":"#TrendingNow","product":"APLB Glutathione Serum","views":"760K"},
    ]

def main():
    DATA.mkdir(parents=True, exist_ok=True)

    payload = {
        "updated_at": datetime.now(KST).isoformat(),
        "source":"TikTok Shop US",
        "count":8,
        "products":build()
    }

    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("✅ TikTok : 8 trends")

if __name__ == "__main__":
    main()
