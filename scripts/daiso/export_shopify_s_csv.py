#!/usr/bin/env python3
"""S등급 shopify_s_recommendations.json → Shopify Products CSV + commit_summary 조각."""
from __future__ import annotations
import csv, json, re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IN_S = ROOT / "data" / "daiso_real" / "shopify_s_recommendations.json"
OUT_CSV = ROOT / "data" / "daiso_real" / "shopify_s_products_import.csv"
RUNTIME = ROOT / "data" / "dashboard_runtime.json"

HEADERS = [
    "Handle","Title","Body (HTML)","Vendor","Product Category","Type","Tags","Published",
    "Option1 Name","Option1 Value","Variant SKU","Variant Grams","Variant Inventory Tracker",
    "Variant Inventory Qty","Variant Inventory Policy","Variant Fulfillment Service",
    "Variant Price","Variant Compare At Price","Variant Requires Shipping","Variant Taxable",
    "Variant Barcode","Image Src","Image Position","Image Alt Text","Gift Card",
    "SEO Title","SEO Description","Status","Cost per item","pd_no","name_ko","daiso_url","shopify_score",
]

def slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9가-힣\s-]+", "", s or "")
    s = re.sub(r"\s+", "-", s.strip().lower())
    return (s[:60] or "product")

def main() -> int:
    data = json.loads(IN_S.read_text(encoding="utf-8")) if IN_S.exists() else {}
    recs = data.get("recommendations") or []
    rows = []
    for r in recs:
        name = r.get("name") or ""
        tokens = ((r.get("matched_global") or {}).get("matched_tokens") or [])[:4]
        rows.append({
            "Handle": slug(name),
            "Title": name,
            "Body (HTML)": f"<p>{name}</p><p><em>{r.get('recommend_reason') or ''}</em></p>",
            "Vendor": "Daiso Korea",
            "Product Category": "",
            "Type": r.get("bucket") or "Beauty",
            "Tags": ",".join(["daiso","s-grade","k-beauty"] + list(tokens)),
            "Published": "false",
            "Option1 Name": "Title",
            "Option1 Value": "Default Title",
            "Variant SKU": f"DAISO-{r.get('pd_no')}",
            "Variant Grams": "0",
            "Variant Inventory Tracker": "",
            "Variant Inventory Qty": "",
            "Variant Inventory Policy": "deny",
            "Variant Fulfillment Service": "manual",
            "Variant Price": "",
            "Variant Compare At Price": "",
            "Variant Requires Shipping": "true",
            "Variant Taxable": "true",
            "Variant Barcode": "",
            "Image Src": r.get("image_url") or "",
            "Image Position": "1" if r.get("image_url") else "",
            "Image Alt Text": name,
            "Gift Card": "false",
            "SEO Title": name[:70],
            "SEO Description": (r.get("recommend_reason") or name)[:160],
            "Status": "draft",
            "Cost per item": str(int(r["price_krw"])) if r.get("price_krw") else "",
            "pd_no": str(r.get("pd_no") or ""),
            "name_ko": name,
            "daiso_url": r.get("url") or "",
            "shopify_score": str(r.get("shopify_score") or ""),
        })
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows → {OUT_CSV}")

    # commit_summary 한 줄 (runtime에 병합용)
    line = (
        f"S등급 {len(rows)}건 CSV 갱신 · "
        f"products/score 반영 · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}Z"
    )
    summary_path = ROOT / "data" / "daiso_real" / "last_commit_summary.json"
    summary_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "line": line,
        "s_count": len(rows),
        "csv": str(OUT_CSV.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("summary:", line)

    # runtime에 있으면 병합
    if RUNTIME.exists():
        try:
            rt = json.loads(RUNTIME.read_text(encoding="utf-8"))
            rt["commit_summary"] = {"line": line, "s_count": len(rows), "at": datetime.now(timezone.utc).isoformat()}
            RUNTIME.write_text(json.dumps(rt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print("dashboard_runtime.json commit_summary updated")
        except Exception as e:
            print("runtime merge skip:", e)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
