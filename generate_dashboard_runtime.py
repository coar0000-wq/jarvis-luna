"""
generate_dashboard_runtime.py - FULL FILE v3.0
gosi + product 증거 필수 검증
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
    except:
        return default

def validate_evidence(item: dict, name_field="title") -> bool:
    ev = item.get("evidence", {})
    for k in ["source_url", "collected_at", "raw_snippet"]:
        if not ev.get(k):
            return False
    if not ev["source_url"].startswith("http"):
        return False
    try:
        datetime.datetime.fromisoformat(ev["collected_at"].replace("Z", "+00:00"))
    except:
        return False
    return True

def build_gosi():
    gosi_path = DATA_DIR / "gosi.json"
    data = load_json_safe(gosi_path, {"items": []})
    items = data.get("items", []) if isinstance(data, dict) else data
    valid = [item for item in items if validate_evidence(item, "title")]
    return {
        "items": valid,
        "updated_at": data.get("updated_at") if isinstance(data, dict) else datetime.datetime.utcnow().isoformat() + "Z",
        "count": len(valid),
        "source": "https://www.gosi.kr",
        "evidence_required": True
    }

def build_product_discovery():
    products_path = DATA_DIR / "products.json"
    data = load_json_safe(products_path, {"products": []})
    products = data.get("products", []) if isinstance(data, dict) else []
    valid = [p for p in products if validate_evidence(p, "name")]
    return {
        "products": valid,
        "updated_at": data.get("updated_at") if isinstance(data, dict) else datetime.datetime.utcnow().isoformat() + "Z",
        "count": len(valid),
        "evidence_required": True
    }

def build_daiso():
    return load_json_safe(DATA_DIR / "daiso_products.json", {"products": []})

def generate_runtime():
    runtime = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "version": "3.0-gosi-product-evidence-required",
        "gosi": build_gosi(),
        "product_discovery": build_product_discovery(),
        "daiso": build_daiso(),
        "meta": {"fake_data_allowed": False, "evidence_popup": True}
    }
    RUNTIME_PATH.write_text(json.dumps(runtime, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Runtime - gosi:{runtime['gosi']['count']} product:{runtime['product_discovery']['count']}")
    return runtime

if __name__ == "__main__":
    generate_runtime()
