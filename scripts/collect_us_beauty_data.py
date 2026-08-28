
import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(__file__))

SOURCE_FILE = os.path.join(BASE_DIR, "data", "data_sources.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "data", "us_beauty_market.json")

with open(SOURCE_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)

result = {
    "updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
    "country": "US",
    "category": "C245_BEAUTY",
    "sources": []
}

for s in config["sources"]:
    result["sources"].append({
        "name": s["name"],
        "url": s["url"],
        "type": s["type"],
        "status": "READY"
    })

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("US Beauty Market JSON 생성 완료")
