"""
daiso_gosi_validator.py - FULL FILE
필수 4항목 검증 -> gosi_ok 자동 판정
"""
import json
from pathlib import Path

DATA_PATH = Path("data/daiso_real/daiso_gosi.json")
REQUIRED = ["ingredients", "volume", "maker", "origin"]

def validate_gosi_file():
    if not DATA_PATH.exists():
        print(f"❌ 파일 없음: {DATA_PATH}")
        return
    
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    items = data.get("items", {})
    
    ok_count = 0
    for pid, info in items.items():
        gosi_ok = all(info.get(k) and str(info.get(k)).strip() != "" for k in REQUIRED)
        info["gosi_ok"] = gosi_ok
        if gosi_ok:
            ok_count += 1
        else:
            missing = [k for k in REQUIRED if not info.get(k) or not str(info.get(k)).strip()]
            print(f"⚠️ {pid} {info.get('name')} - 누락: {missing}")
    
    data["gosi_ok_count"] = ok_count
    data["total_count"] = len(items)
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 검증 완료: {ok_count}/{len(items)} gosi_ok=true")
    return data

if __name__ == "__main__":
    validate_gosi_file()
