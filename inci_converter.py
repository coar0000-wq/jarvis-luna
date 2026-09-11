"""
inci_converter.py - FULL FILE
한국어 전성분 -> INCI 영문 변환 + FDA 라벨 생성
"""
import json
from pathlib import Path

DATA_PATH = Path("data/daiso_real/daiso_gosi.json")
OUTPUT_PATH = Path("data/daiso_real/daiso_us_labels.json")

KR_TO_INCI = {
    "정제수": "Water",
    "글리세린": "Glycerin",
    "프로판다이올": "Propanediol",
    "부틸렌글라이콜": "Butylene Glycol",
    "베타인": "Betaine",
    "아이소펜틸다이올": "Isopentyldiol",
    "나이아신아마이드": "Niacinamide",
    "1,2-헥산다이올": "1,2-Hexanediol",
    "병풀잎추출물": "Centella Asiatica Leaf Extract",
    "병풀추출물": "Centella Asiatica Extract",
    "아데노신": "Adenosine",
    "시어버터": "Butyrospermum Parkii (Shea) Butter",
    "카프릴릭/카프릭트라이글리세라이드": "Caprylic/Capric Triglyceride",
    "스쿠알란": "Squalane",
    "다이소듐이디티에이": "Disodium EDTA",
    "판테놀": "Panthenol",
    "향료": "Fragrance",
    "카보머": "Carbomer",
    "잔탄검": "Xanthan Gum",
    "세라마이드엔피": "Ceramide NP",
    "징크옥사이드": "Zinc Oxide",
    "토코페롤": "Tocopherol",
    "알란토인": "Allantoin",
    "소듐하이알루로네이트": "Sodium Hyaluronate",
    "티트리잎오일": "Melaleuca Alternifolia (Tea Tree) Leaf Oil",
    "녹차추출물": "Camellia Sinensis Leaf Extract",
}

def convert_ingredients(kr_ingredients: str) -> str:
    parts = [p.strip() for p in kr_ingredients.split(",") if p.strip()]
    inci = []
    for kr in parts:
        base_kr = kr.split("(")[0].strip()
        inci_name = KR_TO_INCI.get(kr) or KR_TO_INCI.get(base_kr) or f"[{kr}]"
        inci.append(inci_name)
    return ", ".join(inci)

def generate_us_label():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    items = data.get("items", {})
    us_labels = {}
    for pid, info in items.items():
        if not info.get("gosi_ok"):
            continue
        us_labels[pid] = {
            "id": pid,
            "product_name_kr": info.get("name"),
            "product_name_en": f"Daiso {info.get('name')}",
            "net_contents": info.get("volume"),
            "ingredients_inci": convert_ingredients(info.get("ingredients","")),
            "ingredients_kr": info.get("ingredients"),
            "manufacturer": info.get("maker"),
            "country_of_origin": "Korea",
            "warnings_en": "For external use only. Avoid contact with eyes. If irritation occurs, discontinue use and consult a physician. Keep out of reach of children.",
            "gosi_ok": True
        }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(us_labels, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ US 라벨 {len(us_labels)}개 생성")
    return us_labels

if __name__ == "__main__":
    generate_us_label()
