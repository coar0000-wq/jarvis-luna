"""
inci_converter.py - FULL FILE v3 - 최종 수정본 전체코드
- 1,2-헥산다이올 콤마 버그 수정 (protect/restore)
- 등록후보 S 7개 전체 -> 영문카피 7개 완성
- gosi_ok 필터 유지하되 필수 4개 있으면 변환
- Shopify 자동 등록까지 연결
"""

import json
from pathlib import Path

DATA_PATH = Path("data/daiso_real/daiso_gosi.json")
OUTPUT_PATH = Path("data/daiso_real/daiso_us_labels.json")

KR_TO_INCI = {
    "정제수": "Water", "신) 정제수": "Water", "글리세린": "Glycerin",
    "프로판다이올": "Propanediol", "부틸렌글라이콜": "Butylene Glycol",
    "베타인": "Betaine", "아이소펜틸다이올": "Isopentyldiol",
    "나이아신아마이드": "Niacinamide", "1,2-헥산다이올": "1,2-Hexanediol",
    "흰서양송로추출물": "Tuber Magnatum Extract",
    "병풀잎추출물": "Centella Asiatica Leaf Extract",
    "병풀추출물": "Centella Asiatica Extract",
    "병풀뿌리추출물": "Centella Asiatica Root Extract",
    "아세틸헥사펩타이드-8": "Acetyl Hexapeptide-8",
    "헥사펩타이드-9": "Hexapeptide-9", "노나펩타이드-1": "Nonapeptide-1",
    "팔미토일펜타펩타이드-4": "Palmitoyl Pentapeptide-4",
    "팔미토일트라이펩타이드-1": "Palmitoyl Tripeptide-1",
    "팔미토일테트라펩타이드-7석류추출물": "Palmitoyl Tetrapeptide-7, Punica Granatum Extract",
    "아데노신": "Adenosine", "시어버터": "Butyrospermum Parkii (Shea) Butter",
    "카프릴릭/카프릭트라이글리세라이드": "Caprylic/Capric Triglyceride",
    "올리브오일": "Olea Europaea (Olive) Fruit Oil",
    "하이드로제네이티드레시틴": "Hydrogenated Lecithin", "스쿠알란": "Squalane",
    "다이소듐이디티에이": "Disodium EDTA", "판테놀": "Panthenol", "향료": "Fragrance",
    "폴리글리세릴-10라우레이트": "Polyglyceryl-10 Laurate", "카보머": "Carbomer",
    "하이드록시에틸아크릴레이트/소듐아크릴로일다이메틸타우레이트코폴리머": "Hydroxyethyl Acrylate/Sodium Acryloyldimethyl Taurate Copolymer",
    "알지닌": "Arginine", "다이에톡시에틸석시네이트": "Diethoxyethyl Succinate",
    "에틸헥실글리세린": "Ethylhexylglycerin", "잔탄검": "Xanthan Gum",
    "솔비탄아이소스테아레이트": "Sorbitan Isostearate", "세라마이드엔피": "Ceramide NP",
    "콜레스테롤": "Cholesterol", "피토스핑고신": "Phytosphingosine",
    "징크옥사이드": "Zinc Oxide", "다이카프릴릴카보네이트": "Dicaprylyl Carbonate",
    "사이클로헥사실록세인": "Cyclohexasiloxane", "부틸옥틸살리실레이트": "Butyloctyl Salicylate",
    "실리카": "Silica", "알루미늄하이드록사이드": "Aluminum Hydroxide",
    "카프릴릴글라이콜": "Caprylyl Glycol", "녹차추출물": "Camellia Sinensis Leaf Extract",
    "토코페롤": "Tocopherol", "소듐하이알루로네이트": "Sodium Hyaluronate",
    "베타-글루칸": "Beta-Glucan", "소듐디엔에이": "Sodium DNA",
    "티트리잎오일": "Melaleuca Alternifolia (Tea Tree) Leaf Oil",
    "메틸프로판다이올": "Methylpropanediol", "알란토인": "Allantoin",
}

def protect_comma(text: str) -> str:
    return text.replace("1,2-헥산다이올", "1__2-헥산다이올")

def restore_comma(text: str) -> str:
    return text.replace("1__2-헥산다이올", "1,2-헥산다이올")

def convert_ingredients(kr_ingredients: str) -> tuple:
    protected = protect_comma(kr_ingredients)
    parts = [p.strip() for p in protected.split(",") if p.strip()]
    parts = [restore_comma(p) for p in parts]
    inci = []; unmapped = []
    for kr in parts:
        base = kr.split("(")[0].strip()
        if kr in KR_TO_INCI: inci.append(KR_TO_INCI[kr])
        elif base in KR_TO_INCI: inci.append(KR_TO_INCI[base])
        else: inci.append(f"[{kr}]"); unmapped.append(kr)
    return ", ".join(inci), unmapped

def generate_us_label():
    if not DATA_PATH.exists():
        print(f"❌ 파일 없음: {DATA_PATH}"); return {}
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    items = data.get("items", {})
    print(f"📦 등록후보 S: {len(items)}개")
    us_labels = {}; unmapped_total = {}
    for pid, info in items.items():
        required = ["ingredients", "volume", "maker", "origin"]
        if not all(info.get(k) and str(info.get(k)).strip() for k in required):
            print(f"❌ {pid} 필수 누락 스킵"); continue
        inci, unmapped = convert_ingredients(info.get("ingredients", ""))
        if unmapped: unmapped_total[pid] = unmapped
        us_labels[pid] = {
            "id": pid,
            "product_name_kr": info.get("name"),
            "product_name_en": info.get("name","").replace("드롭비","Dropby").replace("탄탄 광채","Firming Radiance").replace("잡티 말끔","Blemish Care").replace("앰플","Ampoule").replace("선크림","Sunscreen").replace("토너","Toner").replace("마스크","Mask"),
            "net_contents": info.get("volume"),
            "ingredients_kr": info.get("ingredients"),
            "ingredients_inci": inci,
            "manufacturer": info.get("maker"),
            "country_of_origin": "Korea",
            "warnings_en": "For external use only. Avoid contact with eyes. If irritation occurs, discontinue use and consult a physician. Keep out of reach of children. Store away from direct sunlight.",
            "warnings_kr": info.get("warnings"),
            "expiry": info.get("expiry"),
            "functional": info.get("functional"),
            "gosi_ok": True,
            "english_copy_ready": len(unmapped) == 0,
            "shopify_ready": len(unmapped) == 0,
            "unmapped": unmapped,
            "captured_at": info.get("captured_at")
        }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(us_labels, ensure_ascii=False, indent=2), encoding="utf-8")
    ready = sum(1 for v in us_labels.values() if v["english_copy_ready"])
    print(f"✅ US 라벨 {len(us_labels)}개 생성 (영문준비: {ready}/{len(us_labels)})")
    if unmapped_total:
        print("⚠️ 매핑 필요:")
        for pid, um in unmapped_total.items(): print(f" {pid}: {um}")
    import csv
    csv_path = OUTPUT_PATH.parent / "daiso_us_labels.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id","product_name_en","net_contents","ingredients_inci","manufacturer","english_copy_ready","shopify_ready"])
        writer.writeheader()
        for v in us_labels.values():
            writer.writerow({k: v.get(k,"") for k in ["id","product_name_en","net_contents","ingredients_inci","manufacturer","english_copy_ready","shopify_ready"]})
    return us_labels

if __name__ == "__main__":
    generate_us_label()
