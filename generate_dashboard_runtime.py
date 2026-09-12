"""
generate_dashboard_runtime.py - FULL FILE 전체 덮어쓰기용
- gosi.json + products.json 증거 필수 검증
- 가짜 데이터 금지 (CLAUDE.md Rule 1)
"""

import json
import datetime
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
RUNTIME_PATH = ROOT / "dashboard_runtime.json"

def load_json_safe(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ {path} 로드 실패: {e}")
        return default

def validate_evidence(item: dict, name_field="title") -> bool:
    ev = item.get("evidence", {})
    for k in ["source_url", "collected_at", "raw_snippet"]:
        if not ev.get(k):
            print(f"❌ 증거 없음 {k} - {item.get(name_field, 'unknown')} 제외")
            return False
    if not ev["source_url"].startswith("http"):
        print(f"❌ source_url 형식 오류 - {item.get(name_field)}")
        return False
    try:
        datetime.datetime.fromisoformat(ev["collected_at"].replace("Z", "+00:00"))
    except:
        print(f"❌ collected_at 형식 오류 - {item.get(name_field)}")
        return False
    return True

def build_gosi():
    """gosi.json 검증 후 반환"""
    gosi_path = DATA_DIR / "gosi.json"
    data = load_json_safe(gosi_path, {"items": []})
    items = data.get("items", []) if isinstance(data, dict) else data
    if isinstance(items, dict):
        items = [items]

    valid = []
    for item in items:
        if validate_evidence(item, "title"):
            valid.append(item)

    if not valid:
        print("ℹ️ gosi 유효 데이터 없음 - 위젯 숨김")

    return {
        "items": valid,
        "updated_at": data.get("updated_at") if isinstance(data, dict) else datetime.datetime.utcnow().isoformat() + "Z",
        "count": len(valid),
        "source": "https://www.gosi.kr",
        "evidence_required": True
    }

def build_product_discovery():
    """products.json 검증 후 반환"""
    products_path = DATA_DIR / "products.json"
    data = load_json_safe(products_path, {"products": []})
    products = data.get("products", []) if isinstance(data, dict) else []

    valid = [p for p in products if validate_evidence(p, "name")]

    if not valid:
        print("ℹ️ Product Discovery 유효 데이터 없음 - 위젯 숨김")

    return {
        "products": valid,
        "updated_at": data.get("updated_at") if isinstance(data, dict) else datetime.datetime.utcnow().isoformat() + "Z",
        "count": len(valid),
        "evidence_required": True
    }

def build_daiso():
    daiso_path = DATA_DIR / "daiso_products.json"
    data = load_json_safe(daiso_path, {"products": []})
    return data

def generate_runtime():
    print("🚀 Dashboard Runtime 생성 시작 (gosi + product 증거 검증 포함)")

    runtime = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "version": "3.0-gosi-product-evidence-required",
        "gosi": build_gosi(),
        "product_discovery": build_product_discovery(),
        "daiso": build_daiso(),
        "meta": {
            "note": "CLAUDE.md Rule 1 준수 - gosi, product 모두 source_url + collected_at + raw_snippet 필수",
            "fake_data_allowed": False,
            "evidence_popup": True
        }
    }

    RUNTIME_PATH.write_text(json.dumps(runtime, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Runtime 생성 완료: {RUNTIME_PATH}")
    print(f" - gosi: {runtime['gosi']['count']}개")
    print(f" - Product Discovery: {runtime['product_discovery']['count']}개")
    return runtime

if __name__ == "__main__":
    generate_runtime()
