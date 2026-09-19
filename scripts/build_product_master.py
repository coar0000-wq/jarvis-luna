#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""다이소 실상품의 운영 Product Master를 만든다.

정본은 data/daiso_real/products.json의 pd_no다. CP 번호는 한 번 발급하면
상품이 빠지거나 순서가 바뀌어도 재사용하지 않는다. 이전 레지스트리를 먼저
읽고 새 pd_no에만 다음 번호를 배정한다.

점수의 기존 100점제는 유지한다. match/demand/review/final_score는 실측
score_breakdown을 0~1로 정규화한 병행 지표이며 S 판정에는 아직 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PRODUCTS = DATA_DIR / "daiso_real" / "products.json"
SCORES = DATA_DIR / "daiso_real" / "shopify_demand_score.json"
GATE = DATA_DIR / "listing_gate.json"
OUT = DATA_DIR / "product_master.json"
CP_RE = re.compile(r"^CP(\d{6})$")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def _rows(doc: Any, key: str) -> list[dict]:
    if not isinstance(doc, dict):
        return []
    rows = doc.get(key) or []
    if isinstance(rows, dict):
        rows = list(rows.values())
    return [r for r in rows if isinstance(r, dict)]


def _brand(product: dict) -> str:
    value = str(product.get("brand") or "").strip()
    if value and value != "다이소":
        return value
    name = re.sub(r"^\[[^]]+\]", "", str(product.get("name") or "")).strip()
    token = re.split(r"[\s/]", name, maxsplit=1)[0]
    return token if 1 < len(token) <= 30 else ""


def _variant(name: str, cp: str) -> dict:
    reedle = re.search(r"(?:VT\s*)?리들샷\s*(50|100|300)\b", name, re.I)
    if reedle:
        value = reedle.group(1)
        return {
            "group_id": "VG-VT-REEDLE-SHOT",
            "option_name": "Strength",
            "option_value": value,
            "sku": f"{cp}-RS-{value}",
        }
    volume = re.search(r"(\d+(?:\.\d+)?\s*(?:ml|g))(?:\b|\*)", name, re.I)
    return {
        "group_id": f"VG-{cp}",
        "option_name": "Title",
        "option_value": volume.group(1).replace(" ", "") if volume else "Default Title",
        "sku": cp,
    }


def _parallel_scores(score: dict) -> dict:
    breakdown = score.get("score_breakdown") or {}
    best = score.get("best_global_match") or {}
    match = max(0.0, min(1.0, float(best.get("similarity") or 0)))
    demand_raw = sum(float(breakdown.get(k) or 0) for k in
                     ("category", "price", "keyword", "us_market_fit"))
    demand = max(0.0, min(1.0, demand_raw / 65.0))
    review_raw = float(breakdown.get("rating") or 0) + float(breakdown.get("reviews") or 0)
    review = max(0.0, min(1.0, review_raw / 35.0))
    final = 0.35 * match + 0.35 * demand + 0.30 * review
    return {
        "match_score": round(match, 4),
        "demand_score": round(demand, 4),
        "review_score": round(review, 4),
        "final_score": round(final, 4),
        "model": "parallel_v1_observational",
        "used_for_grade": False,
    }

def build_master(inject_scores: bool = True) -> dict:
    source_doc = load_json(PRODUCTS, {}) or {}
    source_rows = _rows(source_doc, "products")
    if not source_rows:
        raise RuntimeError(f"실상품이 없습니다: {PRODUCTS}")
    source_ids = [str(r.get("pd_no") or "") for r in source_rows]
    if any(not x for x in source_ids):
        raise RuntimeError("실상품에 빈 pd_no가 있습니다")
    if len(source_ids) != len(set(source_ids)):
        raise RuntimeError("실상품에 중복 pd_no가 있습니다")

    previous = load_json(OUT, {}) or {}
    registry: dict[str, str] = {}
    if isinstance(previous, dict):
        registry.update({str(k): str(v) for k, v in
                         (previous.get("pd_no_to_cp") or {}).items()})
        for row in previous.get("products") or []:
            if isinstance(row, dict) and row.get("pd_no") and row.get("canonical_product_id"):
                pd_no = str(row["pd_no"])
                cp = str(row["canonical_product_id"])
                if pd_no in registry and registry[pd_no] != cp:
                    raise RuntimeError(f"CP 충돌: {pd_no}={registry[pd_no]} / {cp}")
                registry.setdefault(pd_no, cp)

    invalid = {k: v for k, v in registry.items() if not CP_RE.match(v)}
    if invalid:
        raise RuntimeError(f"잘못된 CP 형식: {invalid}")
    if len(registry.values()) != len(set(registry.values())):
        raise RuntimeError("서로 다른 pd_no가 같은 CP를 사용합니다")

    used = [int(m.group(1)) for cp in registry.values() if (m := CP_RE.match(cp))]
    next_number = max(used, default=0) + 1
    for pd_no in sorted({str(r.get("pd_no") or "") for r in source_rows if r.get("pd_no")},
                        key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else x)):
        if pd_no not in registry:
            registry[pd_no] = f"CP{next_number:06d}"
            next_number += 1

    score_doc = load_json(SCORES, {}) if inject_scores else {}
    score_by = {str(r.get("pd_no")): r for r in _rows(score_doc, "all_scored")}
    gate_doc = load_json(GATE, {}) or {}
    gate_by = {str(r.get("pd_no") or r.get("product_id")): r
               for r in _rows(gate_doc, "items")}

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    products = []
    for src in sorted(source_rows, key=lambda r: str(r.get("pd_no") or "")):
        pd_no = str(src.get("pd_no") or "")
        if not pd_no:
            continue
        cp = registry[pd_no]
        score = score_by.get(pd_no, {})
        gate = gate_by.get(pd_no, {})
        name = str(src.get("name") or score.get("name") or "")
        products.append({
            "canonical_product_id": cp,
            "pd_no": pd_no,
            "name_ko": name,
            "brand": _brand(src),
            "category": score.get("bucket") or src.get("bucket") or src.get("site_category") or "",
            "source": {
                "system": "daisomall.co.kr",
                "url": src.get("url") or score.get("url") or "",
                "collected_at": src.get("collected_at") or source_doc.get("updated_at") or "",
            },
            "price_krw": src.get("price_krw"),
            "rating": src.get("rating"),
            "review_count": src.get("review_count"),
            "image_url": src.get("image_url") or score.get("image_url") or "",
            "shopify_score": score.get("shopify_score"),
            "grade": score.get("grade"),
            "s_rule": score.get("s_rule"),
            "score_breakdown": score.get("score_breakdown") or {},
            "component_scores": _parallel_scores(score) if score else {},
            "variant": _variant(name, cp),
            "listing": {
                "ready": gate.get("ready") if gate else None,
                "blocked_by": gate.get("blocked_by") or [],
                "gate_generated_at": gate_doc.get("generated_at") if gate else None,
            },
        })

    active_ids = [p["pd_no"] for p in products]
    active_cps = [p["canonical_product_id"] for p in products]
    if len(active_ids) != len(set(active_ids)) or len(active_cps) != len(set(active_cps)):
        raise RuntimeError("활성 Product Master에 중복 pd_no 또는 CP가 있습니다")
    if any(registry[p["pd_no"]] != p["canonical_product_id"] for p in products):
        raise RuntimeError("Product Master와 CP 레지스트리가 일치하지 않습니다")

    payload = {
        "schema_version": 2,
        "generated_at": now,
        "generator": "scripts/build_product_master.py",
        "source": "data/daiso_real/products.json",
        "id_policy": "pd_no에 최초 CP 발급 후 재사용·재번호 부여 금지",
        "active_product_count": len(products),
        "registry_count": len(registry),
        "pd_no_to_cp": dict(sorted(registry.items())),
        "products": products,
        "score_policy": {
            "grade_source": "shopify_score 0~100 + qualify_s/s_rule",
            "parallel_components": "match/demand/review/final 0~1, 관찰용이며 등급 미사용",
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    s_count = sum(1 for p in products if p.get("grade") == "S")
    print(f"Product Master {len(products)}개 · CP 레지스트리 {len(registry)}개 · S {s_count}개")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inject-s", action="store_true",
                        help="현재 점수·게이트를 Product Master에 주입")
    args = parser.parse_args()
    build_master(inject_scores=args.inject_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
