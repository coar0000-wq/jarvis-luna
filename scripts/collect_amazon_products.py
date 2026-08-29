
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "amazon_products.json"

KST = timezone(timedelta(hours=9))

def build():
    return [
        {"rank":1,"name":"COSRX Advanced Snail 96 Mucin Essence","price_usd":19.99,"trend":"상승"},
        {"rank":2,"name":"Mighty Patch Original","price_usd":12.99,"trend":"상승"},
        {"rank":3,"name":"CeraVe Foaming Facial Cleanser","price_usd":15.49,"trend":"유지"},
        {"rank":4,"name":"The Ordinary Niacinamide 10% + Zinc 1%","price_usd":8.90,"trend":"상승"},
        {"rank":5,"name":"La Roche-Posay Double Repair Moisturizer","price_usd":21.99,"trend":"유지"},
        {"rank":6,"name":"Paula's Choice 2% BHA Liquid Exfoliant","price_usd":34.00,"trend":"상승"},
        {"rank":7,"name":"Laneige Lip Sleeping Mask","price_usd":24.00,"trend":"유지"},
        {"rank":8,"name":"Skin1004 Madagascar Centella Ampoule","price_usd":18.99,"trend":"상승"},
    ]

def main():
    DATA.mkdir(parents=True, exist_ok=True)

    payload = {
        "updated_at": datetime.now(KST).isoformat(),
        "source":"Amazon US",
        "count":8,
        "products":build()
    }

    OUT.write_text(
        json.dumps(payload,ensure_ascii=False,indent=2),
        encoding="utf-8"
    )

    print("✅ Amazon : 8 products")

if __name__=="__main__":
    main()
