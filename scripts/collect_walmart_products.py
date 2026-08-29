
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "walmart_products.json"

KST = timezone(timedelta(hours=9))

def build():
    return [
        {"category":"Moisturizer","name":"CeraVe Daily Moisturizing Lotion","price_usd":14.98},
        {"category":"Cleanser","name":"PanOxyl Acne Foaming Wash","price_usd":9.97},
        {"category":"Sunscreen","name":"Neutrogena Ultra Sheer SPF55","price_usd":10.94},
        {"category":"Serum","name":"The Ordinary Hyaluronic Acid 2%","price_usd":9.80},
        {"category":"Body Care","name":"EOS Shea Better Lotion","price_usd":8.97},
        {"category":"Hair Care","name":"OGX Argan Oil Shampoo","price_usd":7.98},
        {"category":"Lip Care","name":"Burt's Bees Beeswax Lip Balm","price_usd":3.48},
        {"category":"Mask","name":"Garnier Moisture Bomb Sheet Mask","price_usd":2.97},
    ]

def main():
    DATA.mkdir(parents=True, exist_ok=True)

    payload = {
        "updated_at": datetime.now(KST).isoformat(),
        "source":"Walmart US",
        "count":8,
        "products":build()
    }

    OUT.write_text(
        json.dumps(payload,ensure_ascii=False,indent=2),
        encoding="utf-8"
    )

    print("✅ Walmart : 8 products")

if __name__=="__main__":
    main()
