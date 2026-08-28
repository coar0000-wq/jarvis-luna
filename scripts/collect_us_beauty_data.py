import json
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(__file__))

output = {
    "updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
    "country": "US",
    "market": "K-Beauty",
    "sources": [
        {
            "name": "Amazon Beauty",
            "url": "https://www.amazon.com/Best-Sellers-Beauty/zgbs/beauty",
            "category": "Beauty",
            "status": "ACTIVE"
        },
        {
            "name": "Amazon Skincare",
            "url": "https://www.amazon.com/Best-Sellers-Beauty-Skin-Care-Products/zgbs/beauty/11060451",
            "category": "Skincare",
            "status": "ACTIVE"
        },
        {
            "name": "TikTok Creative Center",
            "url": "https://ads.tiktok.com/business/creativecenter/inspiration/popular/products/pc/en",
            "category": "Viral",
            "status": "ACTIVE"
        },
        {
            "name": "Google Trends US",
            "url": "https://trends.google.com/trends/explore?geo=US",
            "category": "Trend",
            "status": "ACTIVE"
        },
        {
            "name": "Ulta Beauty",
            "url": "https://www.ulta.com/shop/skin-care",
            "category": "Skincare",
            "status": "ACTIVE"
        },
        {
            "name": "Sephora",
            "url": "https://www.sephora.com/shop/skincare",
            "category": "Luxury Beauty",
            "status": "ACTIVE"
        },
        {
            "name": "Target Beauty",
            "url": "https://www.target.com/c/beauty/-/N-5xu0o",
            "category": "Retail",
            "status": "ACTIVE"
        },
        {
            "name": "Walmart Beauty",
            "url": "https://www.walmart.com/browse/beauty/1085666",
            "category": "Retail",
            "status": "ACTIVE"
        }
    ]
}

os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)

with open(os.path.join(ROOT, "data", "us_beauty_market.json"), "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print("US Beauty Market database created successfully.")
