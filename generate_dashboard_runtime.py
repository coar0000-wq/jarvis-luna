"""
generate_dashboard_runtime.py - FULL FILE
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

def validate_product_evidence(item: dict) -> bool:
    ev = item.get("evidence", {})
    for k in ["source_url", "collected_at", "raw_snippet"]:
        if not ev.get(k):
            return False
    try:
        datetime.datetime.fromisoformat(ev["collected_at"].replace("Z", "+00:00"))
    except:
        return False
    return True

def build_product_discovery():
    data = load_json_safe(DATA_DIR / "products.json", {"products": []})
    valid = [p for p in data.get("products", []) if validate_product_evidence(p)]
    return {
        "products": valid,
        "updated_at": data.get("updated_at") or datetime.datetime.utcnow().isoformat() + "Z",
        "count": len(valid)
    }

def build_gosi():
    return load_json_safe(DATA_DIR / "gosi.json", {"items": []})

def build_daiso():
    return load_json_safe(DATA_DIR / "daiso_products.json", {"products": []})

def generate_runtime():
    runtime = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "version": "2.0-evidence-required",
        "gosi": build_gosi(),
        "daiso": build_daiso(),
        "product_discovery": build_product_discovery(),
        "meta": {"fake_data_allowed": False}
    }
    RUNTIME_PATH.write_text(json.dumps(runtime, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Runtime {len(runtime['product_discovery']['products'])}개")
    return runtime

if __name__ == "__main__":
    generate_runtime()
