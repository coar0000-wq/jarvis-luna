"""
export_shopify_full.py - P0-3 Shopify Export 4개 계층
추천 파일: scripts/export_shopify_csv.py

출력 4개:
- products.csv (메인)
- inventory.csv (재고)
- images.csv (이미지)
- collections.csv (컬렉션)

+ Variant 구조: VT Reedle Shot -> 50,100,300 Handle 공유
"""

import json
import csv
from pathlib import Path
import datetime

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
EXPORT_DIR = ROOT / "export"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

def load_master():
    path = DATA_DIR / "product_master.json"
    if not path.exists():
        print("product_master.json 없음")
        return []
    return json.loads(path.read_text(encoding="utf-8"))

def load_legal():
    path = DATA_DIR / "legal_full.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def export_products(master, legal):
    fieldnames = [
        "Handle","Title","Body (HTML)","Vendor","Product Category","Type","Tags",
        "Published","Option1 Name","Option1 Value","Option2 Name","Option2 Value",
        "Variant SKU","Variant Grams","Variant Inventory Tracker","Variant Inventory Qty",
        "Variant Inventory Policy","Variant Fulfillment Service","Variant Price",
        "Variant Compare At Price","Variant Requires Shipping","Variant Taxable",
        "Image Src","Image Position","Image Alt Text","SEO Title","SEO Description","Status",
        "Canonical ID","Final Score","Grade"
    ]
    
    out_path = EXPORT_DIR / "products.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for p in master:
            # P2 Data Freshness
            parent_handle = p.get("parent_handle") or p["name"].lower().replace(" ","-")
            
            # MoCRA 풀 스키마로 Body 생성
            body = f"<h3>{p['brand']} {p['name']}</h3>"
            if legal:
                body += f"<p><strong>Identity:</strong> {legal.get('identity','')}</p>"
                body += f"<p><strong>Directions:</strong> {legal.get('directions','')}</p>"
                body += f"<p><strong>Warning:</strong> {legal.get('warning','')}</p>"
                body += f"<p><strong>Ingredients:</strong> {', '.join(legal.get('ingredients',[]))}</p>"
                body += f"<hr><p>Responsible Person: {legal.get('responsible_person',{}).get('name','')} / {legal.get('responsible_person',{}).get('email','')}</p>"
                body += f"<p>{legal.get('country','Made in Korea')}</p>"
            
            # Variant 그룹
            for var in p.get("variant_group", [{"variant":"standard","sku":p["canonical_id"],"price":29.0,"grams":120}]):
                row = {
                    "Handle": parent_handle,
                    "Title": f"{p['brand']} {p['name']}",
                    "Body (HTML)": body,
                    "Vendor": p["brand"],
                    "Product Category": f"Health & Beauty > Personal Care > Cosmetics > Skin Care > {p['category']}",
                    "Type": p["category"],
                    "Tags": f"{p['category']}, K-beauty, {p['grade']}-grade, {p.get('marketing',{}).get('keyword','')}",
                    "Published": "TRUE",
                    "Option1 Name": "Size" if len(p.get("variant_group",[]))>1 else "",
                    "Option1 Value": var["variant"],
                    "Option2 Name": "",
                    "Option2 Value": "",
                    "Variant SKU": var["sku"],
                    "Variant Grams": var.get("grams",120),
                    "Variant Inventory Tracker": "shopify",
                    "Variant Inventory Qty": "100",
                    "Variant Inventory Policy": "deny",
                    "Variant Fulfillment Service": "manual",
                    "Variant Price": var.get("price", p.get("pricing",{}).get("price_usd",29.0)),
                    "Variant Compare At Price": p.get("pricing",{}).get("compare_at_price",39.0),
                    "Variant Requires Shipping": "TRUE",
                    "Variant Taxable": "TRUE",
                    "Image Src": "",
                    "Image Position": "1",
                    "Image Alt Text": f"{p['name']} {var['variant']}",
                    "SEO Title": f"{p['brand']} {p['name']} {var['variant']} | JARVIS LUNA",
                    "SEO Description": f"{p['name']} {var['variant']} - {p.get('marketing',{}).get('keyword','K-beauty')} trend {p.get('marketing',{}).get('trend_growth','')}% growth",
                    "Status": "active",
                    "Canonical ID": p["canonical_id"],
                    "Final Score": p.get("final_score",0),
                    "Grade": p["grade"]
                }
                writer.writerow(row)
    
    print(f"✅ products.csv 생성: {out_path} ({len(master)} canonical)")
    return out_path

def export_inventory(master):
    fieldnames = ["Handle","Variant SKU","Location","Quantity","Inventory Policy"]
    out_path = EXPORT_DIR / "inventory.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in master:
            parent_handle = p.get("parent_handle") or p["name"].lower().replace(" ","-")
            for var in p.get("variant_group", []):
                writer.writerow({
                    "Handle": parent_handle,
                    "Variant SKU": var["sku"],
                    "Location": "US Warehouse",
                    "Quantity": 100,
                    "Inventory Policy": "deny"
                })
    print(f"✅ inventory.csv 생성: {out_path}")
    return out_path

def export_images(master):
    fieldnames = ["Handle","Image Src","Image Position","Image Alt Text","Variant SKU"]
    out_path = EXPORT_DIR / "images.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in master:
            parent_handle = p.get("parent_handle") or p["name"].lower().replace(" ","-")
            # 메인 이미지 + variant 이미지
            for idx, var in enumerate(p.get("variant_group", []), start=1):
                writer.writerow({
                    "Handle": parent_handle,
                    "Image Src": f"https://coar0000-wq.github.io/jarvis-luna/images/{p['canonical_id']}_{var['variant']}.jpg",
                    "Image Position": idx,
                    "Image Alt Text": f"{p['name']} {var['variant']}",
                    "Variant SKU": var["sku"]
                })
    print(f"✅ images.csv 생성: {out_path}")
    return out_path

def export_collections(master):
    fieldnames = ["Handle","Title","Body HTML","Collection Type","Rule Column","Rule Relation","Rule Condition"]
    out_path = EXPORT_DIR / "collections.csv"
    collections = [
        {"handle": "s-grade", "title": "S-Grade Trending", "body": "Top trending K-beauty with score >=0.85", "rule_col": "Tag", "rule_rel": "equals", "rule_cond": "S-grade"},
        {"handle": "vt-collection", "title": "VT Cosmetics", "body": "VT Reedle Shot series", "rule_col": "Vendor", "rule_rel": "equals", "rule_cond": "VT"},
        {"handle": "serum-collection", "title": "Serums & Ampoules", "body": "Best serums", "rule_col": "Type", "rule_rel": "equals", "rule_cond": "serum"},
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in collections:
            writer.writerow({
                "Handle": c["handle"],
                "Title": c["title"],
                "Body HTML": c["body"],
                "Collection Type": "auto",
                "Rule Column": c["rule_col"],
                "Rule Relation": c["rule_rel"],
                "Rule Condition": c["rule_cond"]
            })
    print(f"✅ collections.csv 생성: {out_path}")
    return out_path

def export_marketing_csv(master):
    """P1 마케팅 - Canonical ID 연결"""
    fieldnames = ["rank","canonical_id","keyword","ad_keyword_final","trend_volume","trend_growth","intent","season","final_score","grade","handle"]
    out_path = EXPORT_DIR / "marketing_priority.csv"
    sorted_master = sorted(master, key=lambda x: x.get("final_score",0), reverse=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for idx, p in enumerate(sorted_master, start=1):
            mkt = p.get("marketing",{})
            writer.writerow({
                "rank": idx,
                "canonical_id": p["canonical_id"],
                "keyword": mkt.get("keyword",""),
                "ad_keyword_final": mkt.get("ad_keyword_final",""),
                "trend_volume": mkt.get("trend_volume",0),
                "trend_growth": mkt.get("trend_growth",0),
                "intent": mkt.get("intent","purchase"),
                "season": mkt.get("season","all"),
                "final_score": p.get("final_score",0),
                "grade": p.get("grade",""),
                "handle": p.get("parent_handle","")
            })
    print(f"✅ marketing_priority.csv 생성: {out_path}")
    return out_path

def main():
    """호환 진입점. 운영 정본 exporter로 위임한다.

    예전 구현은 샘플 Product Master를 읽고 재고 100·Published TRUE를 만들어
    운영에 사용할 수 없었다. 기존 호출 경로는 유지하되 안전한 exporter만 쓴다.
    """
    from export_shopify_operational import main as operational_main
    return operational_main()

if __name__ == "__main__":
    main()
