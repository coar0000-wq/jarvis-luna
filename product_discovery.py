import json
import datetime
from pathlib import Path

DATA_PATH = Path("data/products.json")
DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

def validate_evidence(item: dict) -> bool:
    ev = item.get("evidence", {})
    for k in ["source_url", "collected_at", "raw_snippet"]:
        if not ev.get(k):
            print(f"❌ 증거 없음 {k} - {item.get('name')} 제외")
            return False
    try:
        datetime.datetime.fromisoformat(ev["collected_at"].replace("Z", "+00:00"))
    except:
        return False
    return True

def collect_real_products():
    products = []
    valid = [p for p in products if validate_evidence(p)]
    
    if not valid:
        print("ℹ️ 유효한 데이터 없음 - 위젯 숨김")
        DATA_PATH.write_text(json.dumps({"products": [], "updated_at": datetime.datetime.utcnow().isoformat()+"Z", "note": "no valid evidence"}, indent=2), encoding="utf-8")
        return []

    DATA_PATH.write_text(json.dumps({"products": valid, "updated_at": datetime.datetime.utcnow().isoformat()+"Z"}, indent=2, ensure_ascii=False), encoding="utf-8")
    return valid

if __name__ == "__main__":
    collect_real_products()
