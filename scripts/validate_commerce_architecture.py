#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Product Master, gate, legal, marketing, Shopify exports의 조인 무결성 검사."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    source = load(D / "daiso_real" / "products.json")
    master = load(D / "product_master.json")
    score = load(D / "daiso_real" / "shopify_demand_score.json")
    srec = load(D / "daiso_real" / "shopify_s_recommendations.json")
    gate = load(D / "listing_gate.json")
    legal = load(D / "legal_full.json")
    market = load(D / "market_team.json")

    source_ids = {str(x["pd_no"]) for x in source.get("products") or []}
    registry = {str(k): str(v) for k, v in (master.get("pd_no_to_cp") or {}).items()}
    products = master.get("products") or []
    require(len(source_ids) == len(source.get("products") or []), "source pd_no 중복")
    require(len(registry) == len(set(registry.values())), "CP 중복")
    require({str(x["pd_no"]) for x in products} == source_ids, "Master 활성 상품 != source")
    require(all(registry[str(x["pd_no"])] == x.get("canonical_product_id") for x in products),
            "Master CP와 레지스트리 불일치")

    scored = score.get("all_scored") or []
    require(all(x.get("canonical_product_id") == registry.get(str(x.get("pd_no"))) for x in scored),
            "점수 산출물 CP 불일치")
    recs = srec.get("recommendations") or []
    gate_rows = gate.get("items") or []
    rec_by = {str(x["pd_no"]): x for x in recs}
    gate_by = {str(x["pd_no"]): x for x in gate_rows}
    require(set(rec_by) == set(gate_by), "S 추천과 gate 상품 집합 불일치")
    require(all(bool(rec_by[k].get("registerable")) == bool(gate_by[k].get("ready")) for k in rec_by),
            "S registerable과 gate ready 불일치")
    require(all(bool(rec_by[k].get("public_ready")) == bool(gate_by[k].get("public_ready")) for k in rec_by),
            "S public_ready와 gate public_ready 불일치")
    require(all(rec_by[k].get("canonical_product_id") == registry.get(k) for k in rec_by),
            "S 추천 CP 불일치")

    export_dir = D / "shopify_exports"
    with (export_dir / "products.csv").open(encoding="utf-8", newline="") as f:
        export_products = list(csv.DictReader(f))
    with (export_dir / "inventory.csv").open(encoding="utf-8", newline="") as f:
        inventory = list(csv.DictReader(f))
    export_ids = {x["pd_no"] for x in export_products}
    ready_ids = {k for k, x in gate_by.items() if x.get("ready")}
    require(export_ids == ready_ids, "Shopify products.csv가 gate ready 집합과 다름")
    require(all(x["Canonical Product ID"] == registry[x["pd_no"]] for x in export_products),
            "Shopify export CP 불일치")
    require(all(x["Status"] == "draft" and x["Published"] == "FALSE" for x in export_products),
            "Shopify export 공개 안전 기본값 위반")
    require(all(x["Available"] == "0" and x["Inventory Policy"] == "deny" for x in inventory),
            "Shopify inventory 안전 기본값 위반")

    require(legal.get("schema_version") == 3, "legal_full schema v3 필요")
    require(set((legal.get("items") or {}).keys()) == set(rec_by), "legal_full S 범위 불일치")
    expected_public = sum(1 for k, row in gate_by.items()
                          if row.get("ready") and (legal.get("items") or {}).get(k, {}).get("complete"))
    require(gate.get("public_ready") == expected_public, "gate public_ready와 legal_full 불일치")
    raw_ingredients = [x.get("ingredients_inci_raw", "") for x in (legal.get("items") or {}).values()]
    require(all("ingredients_inci_raw" in x for x in (legal.get("items") or {}).values()),
            "legal_full INCI 원문 누락")
    if any("1,2-Hexanediol" in raw for raw in raw_ingredients):
        require(any("1,2-Hexanediol" in item for row in legal["items"].values()
                    for item in row.get("ingredients") or []), "숫자 쉼표 INCI가 분리됨")

    market_rows = market.get("s_grade_priority") or []
    require(len(market_rows) == len(rec_by), "marketing priority S 범위 불일치")
    require(all(x.get("canonical_product_id") == registry.get(str(x.get("pd_no"))) for x in market_rows),
            "marketing priority CP 누락/불일치")
    with (D / "marketing_priority.csv").open(encoding="utf-8", newline="") as f:
        marketing_csv = list(csv.DictReader(f))
    require(len(marketing_csv) == len(market_rows), "marketing_priority.csv 행 수 불일치")
    require(all(x.get("canonical_product_id") for x in marketing_csv), "marketing_priority.csv CP 누락")

    for script in ("build_legal_full.py", "export_shopify_operational.py"):
        require((ROOT / "scripts" / script).exists(), f"workflow 참조 스크립트 없음: {script}")

    print("COMMERCE_ARCHITECTURE_OK")
    print(f"master={len(products)} S={len(recs)} gate_ready={len(ready_ids)} "
          f"legal_complete={legal.get('complete', 0)} exports={len(export_products)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
