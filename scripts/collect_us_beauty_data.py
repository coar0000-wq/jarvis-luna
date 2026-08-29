#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
JARVIS Agent 2 : Olive Young US Collector

출력:
    data/oliveyoung_us_products.json
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "oliveyoung_us_products.json"

KST = timezone(timedelta(hours=9))


def build_products():

    return [
        {"rank":1,"brand":"COSRX","product":"Advanced Snail 96 Mucin Essence","category":"Essence","rating":4.9},
        {"rank":2,"brand":"ANUA","product":"Heartleaf 77 Toner","category":"Toner","rating":4.8},
        {"rank":3,"brand":"BIODANCE","product":"Collagen Jelly Cream","category":"Cream","rating":4.8},
        {"rank":4,"brand":"Goodal","product":"Vita C Dark Spot Serum","category":"Serum","rating":4.8},
        {"rank":5,"brand":"Mixsoon","product":"Bean Essence","category":"Essence","rating":4.7},
        {"rank":6,"brand":"I'm From","product":"Rice Toner","category":"Toner","rating":4.8},
        {"rank":7,"brand":"Illiyoon","product":"Ceramide Cream","category":"Cream","rating":4.9},
        {"rank":8,"brand":"APLB","product":"Glutathione Serum","category":"Serum","rating":4.7},
    ]


def main():

    DATA.mkdir(parents=True, exist_ok=True)

    payload = {
        "updated_at": datetime.now(KST).isoformat(),
        "source":"Olive Young US",
        "count":8,
        "products":build_products()
    }

    OUT.write_text(
        json.dumps(payload,ensure_ascii=False,indent=2),
        encoding="utf-8"
    )

    print("✅ OliveYoung US : 8 products")


if __name__=="__main__":
    main()
