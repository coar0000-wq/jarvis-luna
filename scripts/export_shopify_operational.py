#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""listing_gate ready 상품만 Shopify 운영용 4종 CSV로 내보낸다.

모든 상품은 draft, Published=false, 재고 0으로 내보낸다. 실제 재고·책임자·
라벨이 확인되기 전 공개 판매되지 않게 하는 안전 기본값이다.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data"
OUT = D / "shopify_exports"


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return re.sub(r"-{2,}", "-", text)[:80]


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    gate = load(D / "listing_gate.json", {}) or {}
    master = load(D / "product_master.json", {}) or {}
    legal = load(D / "legal_full.json", {}) or {}
    products = master.get("products") or [] if isinstance(master, dict) else []
    master_by = {str(x.get("pd_no")): x for x in products if isinstance(x, dict)}
    legal_by = legal.get("items") or {} if isinstance(legal, dict) else {}

    ready = [x for x in gate.get("items") or []
             if isinstance(x, dict) and x.get("ready")]
    if not ready:
        raise RuntimeError("listing_gate ready 상품이 없습니다")

    groups: dict[str, list[tuple[dict, dict]]] = {}
    for row in ready:
        pd_no = str(row.get("pd_no") or "")
        pm = master_by.get(pd_no)
        if not pm:
            raise RuntimeError(f"Product Master에 pd_no {pd_no}가 없습니다")
        variant = pm.get("variant") or {}
        groups.setdefault(str(variant.get("group_id") or f"VG-{pm['canonical_product_id']}"), []).append((row, pm))

    product_rows: list[dict] = []
    inventory_rows: list[dict] = []
    image_rows: list[dict] = []
    collection_rows: list[dict] = []

    for group_id, members in sorted(groups.items()):
        first_row, first_pm = members[0]
        first_copy = first_row.get("copy") or {}
        base_handle = "vt-reedle-shot" if group_id == "VG-VT-REEDLE-SHOT" else ""
        handle = base_handle or slug(first_copy.get("title") or first_pm.get("name_ko") or group_id)
        if not handle:
            handle = str(first_pm.get("canonical_product_id") or "product").lower()
        group_cps = "|".join(str(pm.get("canonical_product_id") or "")
                             for _, pm in members)

        for index, (row, pm) in enumerate(sorted(
                members, key=lambda pair: str((pair[1].get("variant") or {}).get("option_value") or ""))):
            variant = pm.get("variant") or {}
            copy = row.get("copy") or {}
            pd_no = str(row.get("pd_no") or "")
            legal_row = legal_by.get(pd_no, {}) if isinstance(legal_by, dict) else {}
            body = str(copy.get("description_html") or "")
            if legal_row.get("identity"):
                body += f"<p><strong>Identity:</strong> {legal_row['identity']}</p>"
            if legal_row.get("directions"):
                body += f"<p><strong>Directions:</strong> {legal_row['directions']}</p>"
            if legal_row.get("warnings"):
                body += f"<p><strong>Warnings:</strong> {legal_row['warnings']}</p>"
            if legal_row.get("ingredients"):
                body += "<p><strong>Ingredients:</strong> " + ", ".join(legal_row["ingredients"]) + "</p>"

            option_name = variant.get("option_name") or "Title"
            option_value = variant.get("option_value") or "Default Title"
            sku = variant.get("sku") or pm.get("canonical_product_id")
            image = pm.get("image_url") or ""
            tags = copy.get("tags") or []
            product_rows.append({
                "Handle": handle,
                "Title": copy.get("title") or pm.get("name_ko") or "",
                "Body (HTML)": body,
                "Vendor": pm.get("brand") or "MD family",
                "Type": copy.get("product_type") or pm.get("category") or "",
                "Tags": ", ".join(str(x) for x in tags),
                "Published": "FALSE",
                "Status": "draft",
                "Option1 Name": option_name,
                "Option1 Value": option_value,
                "Variant SKU": sku,
                "Variant Price": (row.get("price") or {}).get("price_usd") or "",
                "Variant Inventory Tracker": "shopify",
                "Variant Inventory Qty": 0,
                "Variant Inventory Policy": "deny",
                "Variant Requires Shipping": "TRUE",
                "Image Src": image,
                "Image Position": 1 if image else "",
                "Image Alt Text": copy.get("title") or pm.get("name_ko") or "",
                "SEO Title": copy.get("seo_title") or "",
                "SEO Description": copy.get("seo_description") or "",
                "Canonical Product ID": pm.get("canonical_product_id") or "",
                "pd_no": pd_no,
                "Legal Complete": "TRUE" if legal_row.get("complete") else "FALSE",
            })
            inventory_rows.append({
                "Handle": handle,
                "SKU": sku,
                "Canonical Product ID": pm.get("canonical_product_id") or "",
                "pd_no": pd_no,
                "Available": 0,
                "Inventory Policy": "deny",
                "Reason": "실재고 사람 입력 전 판매 차단",
            })
            if image:
                image_rows.append({
                    "Handle": handle,
                    "Canonical Product ID": pm.get("canonical_product_id") or "",
                    "pd_no": pd_no,
                    "Image Src": image,
                    "Image Position": 1,
                    "Image Alt Text": copy.get("title") or pm.get("name_ko") or "",
                })
            if index == 0:
                collection_rows.append({
                    "Collection Handle": "shopify-ready-s",
                    "Collection Title": "Shopify Ready S Grade",
                    "Product Handle": handle,
                    "Canonical Product IDs": group_cps,
                    "Published": "FALSE",
                })

    OUT.mkdir(parents=True, exist_ok=True)
    product_fields = [
        "Handle", "Title", "Body (HTML)", "Vendor", "Type", "Tags", "Published", "Status",
        "Option1 Name", "Option1 Value", "Variant SKU", "Variant Price",
        "Variant Inventory Tracker", "Variant Inventory Qty", "Variant Inventory Policy",
        "Variant Requires Shipping", "Image Src", "Image Position", "Image Alt Text",
        "SEO Title", "SEO Description", "Canonical Product ID", "pd_no", "Legal Complete",
    ]
    write_csv(OUT / "products.csv", product_fields, product_rows)
    write_csv(OUT / "inventory.csv", list(inventory_rows[0]), inventory_rows)
    write_csv(OUT / "images.csv", list(image_rows[0]) if image_rows else
              ["Handle", "Canonical Product ID", "pd_no", "Image Src", "Image Position", "Image Alt Text"], image_rows)
    write_csv(OUT / "collections.csv", list(collection_rows[0]), collection_rows)

    group_sizes = Counter((pm.get("variant") or {}).get("group_id") for _, pm in
                          [(r, master_by[str(r.get("pd_no"))]) for r in ready])
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_gate_generated_at": gate.get("generated_at"),
        "gate_total": gate.get("total"),
        "gate_ready": gate.get("ready"),
        "public_ready": gate.get("public_ready", 0),
        "legal_complete": legal.get("complete", 0) if isinstance(legal, dict) else 0,
        "products_rows": len(product_rows),
        "inventory_rows": len(inventory_rows),
        "images_rows": len(image_rows),
        "collections_rows": len(collection_rows),
        "variant_groups": {str(k): v for k, v in group_sizes.items() if v > 1},
        "safety": "draft + unpublished + inventory 0; 실재고와 법률 책임자 확인 전 공개 금지",
        "files": ["products.csv", "inventory.csv", "images.csv", "collections.csv"],
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Shopify 4종 Export: ready {len(ready)}건 · variant rows {len(product_rows)} · groups {len(groups)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
