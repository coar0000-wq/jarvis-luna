#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

URL = "https://www.daisomall.co.kr/ds/diy2/C245"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

def main():

    DATA.mkdir(exist_ok=True)

    products = []

    r = requests.get(URL, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")

    for tag in soup.find_all(["img", "strong", "span"]):

        title = tag.get("alt") or tag.get_text(strip=True)

        if len(title) < 3:
            continue

        if title in [x["title"] for x in products]:
            continue

        products.append({
            "title": title,
            "category": "Beauty",
            "price": 0,
            "source": "Daiso Mall"
        })

        if len(products) >= 200:
            break

    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "products": products
    }

    with open(DATA / "daiso_products.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Daiso products: {len(products)}")

if __name__ == "__main__":
    main()
