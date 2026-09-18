"""
build_product_master.py - P0-1 Product Master 계층 구축
- daiso_products.json / amazon_products.json / oliveyoung.json 독립 -> CP000XXX Canonical ID로 통합
- 중복 제거 + Variant 그룹화 (VT Reedle Shot 50/100/300)
"""
import json
from pathlib import Path
from collections import defaultdict
import datetime

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"

ALLOWED = {"serum","ampoule","essence","toner","cream","mask","cleanser","suncare","lotion","oil","mist","pad"}

def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except:
        return default

def normalize_name(name: str) -> str:
    return name.lower().replace(" ", "").replace("-", "").replace("_","")

def build_master():
    daiso = load_json(DATA_DIR / "daiso_products.json", {"items": {}})
    amazon = load_json(DATA_DIR / "amazon_products.json", {"products": []})
    olive = load_json(DATA_DIR / "oliveyoung.json", {"products": []})

    # 1. 모든 소스 수집
    raw = []
    if isinstance(daiso, dict):
        items = daiso.get("items", daiso)
        if isinstance(items, dict):
            for pid, v in items.items():
                if v.get("category","") not in ALLOWED and not any(t in str(v.get("tags",[])).lower() for t in ["beauty"]):
                    continue
                raw.append({"source": "daiso", "id": pid, "name": v.get("name",""), "brand": v.get("brand",""), "category": v.get("category","serum"), "evidence": v.get("evidence",{}), "price": v.get("price",0)})
        elif isinstance(items, list):
            raw.extend([{"source":"daiso","id":x.get("id"),"name":x.get("name"),"brand":x.get("brand",""),"category":x.get("category",""),"evidence":x.get("evidence",{})} for x in items])

    for src_name, src_data in [("amazon", amazon), ("oliveyoung", olive)]:
        prods = src_data.get("products", src_data) if isinstance(src_data, dict) else src_data
        if isinstance(prods, list):
            for p in prods:
                raw.append({"source": src_name, "id": p.get("id") or p.get("asin"), "name": p.get("name",""), "brand": p.get("brand",""), "category": p.get("category","serum"), "evidence": p.get("evidence",{}), "rating": p.get("rating",0)})

    # 2. 중복 제거 - brand+normalize_name 기준
    grouped = defaultdict(list)
    for r in raw:
        key = f"{r['brand'].lower()}|{normalize_name(r['name'][:20])}"
        grouped[key].append(r)

    master = []
    cp_counter = 231
    for key, items in grouped.items():
        if len(items) == 0:
            continue
        base = items[0]
        # Canonical ID 발급
        canonical_id = f"CP{cp_counter:06d}"
        cp_counter += 1

        # Variant 그룹화 - 같은 brand+base name에서 50/100/300 추출
        variants = []
        for it in items:
            # 간단히 variant 파싱
            name_low = it["name"].lower()
            if "50" in name_low: var = "50"
            elif "100" in name_low: var = "100"
            elif "300" in name_low: var = "300"
            else: var = it.get("variant","standard")
            variants.append({"variant": var, "sku": f"{base['brand'][:2].upper()}-{canonical_id[-3:]}-{var}", "price": it.get("price",29.0), "grams": 120})

        # S/A/B 정량화는 calculate_grade.py에서 계산, 여기서는 placeholder
        master.append({
            "canonical_id": canonical_id,
            "brand": base["brand"],
            "name": base["name"].split(" 50")[0].split(" 100")[0].split(" 300")[0],
            "category": base["category"],
            "parent_handle": base["name"].lower().replace(" ","-")[:50],
            "sources": {it["source"]: it["id"] for it in items},
            "variant_group": variants,
            "evidence": base["evidence"],
            "created_at": datetime.datetime.utcnow().isoformat()+"Z"
        })

    out_path = DATA_DIR / "product_master.json"
    out_path.write_text(json.dumps(master, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Product Master {len(master)}개 생성 -> {out_path}")
    return master

if __name__ == "__main__":
    build_master()
