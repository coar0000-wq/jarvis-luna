
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/138 Safari/537.36"
    )
}

SOURCES = [
    {
        "name": "Ulta Skincare",
        "url": "https://www.ulta.com/shop/skin-care",
        "category": "Skincare",
    },
    {
        "name": "Ulta Makeup",
        "url": "https://www.ulta.com/shop/makeup",
        "category": "Makeup",
    },
    {
        "name": "Sephora Skincare",
        "url": "https://www.sephora.com/shop/skincare",
        "category": "Skincare",
    },
    {
        "name": "Target Beauty",
        "url": "https://www.target.com/c/beauty/-/N-5xu0o",
        "category": "Beauty",
    },
    {
        "name": "Walmart Beauty",
        "url": "https://www.walmart.com/browse/beauty/1085666",
        "category": "Beauty",
    },
]

def scrape(source):
    results = []

    try:
        r = requests.get(source["url"], headers=HEADERS, timeout=30)
        soup = BeautifulSoup(r.text, "html.parser")

        titles = []

        for tag in soup.find_all(["h2", "h3", "span"]):
            t = tag.get_text(" ", strip=True)
            if 10 <= len(t) <= 120:
                titles.append(t)

        seen = set()

        for title in titles:
            if title in seen:
                continue
            seen.add(title)

            results.append(
                {
                    "title": title,
                    "category": source["category"],
                    "source": source["name"],
                    "url": source["url"],
                }
            )

            if len(results) >= 25:
                break

    except Exception as e:
        results.append(
            {
                "error": str(e),
                "source": source["name"],
            }
        )

    return results

def main():
    DATA.mkdir(exist_ok=True)

    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "country": "US",
        "market": "K-Beauty",
        "products": [],
    }

    for src in SOURCES:
        output["products"].extend(scrape(src))

    out = DATA / "us_beauty_products.json"

    out.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Saved {len(output['products'])} products")

if __name__ == "__main__":
    main()
