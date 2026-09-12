#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the Shopify listing gate from the canonical S-grade pipeline outputs.

The old version read data/daiso_products.json, which is a purged legacy file.
The live pipeline's source of truth is:
  - data/daiso_real/shopify_s_recommendations.json
  - data/shopify_listing_copy.json
  - data/pricing_model.json
  - data/legal_products.json
  - data/daiso_real/daiso_us_labels.json
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

RECOMMENDATIONS = DATA / "daiso_real" / "shopify_s_recommendations.json"
COPY = DATA / "shopify_listing_copy.json"
PRICING = DATA / "pricing_model.json"
LEGAL = DATA / "legal_products.json"
LABELS = DATA / "daiso_real" / "daiso_us_labels.json"
OUTPUT = DATA / "listing_gate.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"JSON 읽기 실패: {path}: {exc}") from exc


def by_pd_no(rows: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if isinstance(rows, dict):
        for key, value in rows.items():
            if isinstance(value, dict):
                result[str(value.get("pd_no", key))] = value
    elif isinstance(rows, list):
        for value in rows:
            if isinstance(value, dict) and value.get("pd_no") is not None:
                result[str(value["pd_no"])] = value
    return result


def main() -> int:
    recommendation_doc = load_json(RECOMMENDATIONS, {})
    copy_doc = load_json(COPY, {})
    pricing_doc = load_json(PRICING, {})
    legal_doc = load_json(LEGAL, {})
    labels_doc = load_json(LABELS, {})

    recommendations = [
        row for row in recommendation_doc.get("recommendations", [])
        if isinstance(row, dict) and row.get("grade") == "S"
    ]
    if not recommendations:
        raise RuntimeError("S등급 추천 상품이 없습니다: data/daiso_real/shopify_s_recommendations.json")

    copy_by_id = by_pd_no(copy_doc.get("items", []))
    offers = (pricing_doc.get("offers_by_product") or {}).get("single", [])
    price_by_id = by_pd_no(offers)
    legal_by_id = by_pd_no(legal_doc.get("items", {}))
    label_by_id = by_pd_no(labels_doc)

    results: list[dict[str, Any]] = []
    blocker_counts = {"copy": 0, "gosi": 0, "price": 0, "legal": 0}

    for rank, product in enumerate(recommendations, start=1):
        pd_no = str(product.get("pd_no", ""))
        copy_row = copy_by_id.get(pd_no, {})
        copy_data = copy_row.get("copy") or {}
        label = label_by_id.get(pd_no, {})
        price = price_by_id.get(pd_no, {})
        legal = legal_by_id.get(pd_no, {})

        has_copy = (
            copy_row.get("copy_status") == "ok"
            and bool(copy_data.get("title"))
            and bool(copy_data.get("description_html"))
        )
        has_gosi = bool(
            label.get("gosi_ok")
            and label.get("net_contents")
            and label.get("ingredients_inci")
            and label.get("manufacturer")
            and label.get("country_of_origin")
        )
        has_price = bool(
            price.get("price_usd")
            and float(price.get("price_usd", 0)) > 0
            and not price.get("register_blocked", False)
        )
        hard_legal_block = bool(legal.get("hard_block"))
        has_legal = bool(legal) and not hard_legal_block

        blocked_by: list[str] = []
        if not has_copy:
            blocked_by.append("copy")
            blocker_counts["copy"] += 1
        if not has_gosi:
            blocked_by.append("gosi")
            blocker_counts["gosi"] += 1
        if not has_price:
            blocked_by.append("price")
            blocker_counts["price"] += 1
        if not has_legal:
            blocked_by.append("legal")
            blocker_counts["legal"] += 1

        results.append({
            "rank": product.get("rank", rank),
            "pd_no": pd_no,
            "product_id": pd_no,
            "name": product.get("name", ""),
            "category": product.get("bucket", ""),
            "price_krw": product.get("price_krw"),
            "shopify_score": product.get("shopify_score"),
            "source_url": product.get("url", ""),
            "copy": copy_data,
            "copy_status": copy_row.get("copy_status", "missing"),
            "gosi": {
                "net_contents": label.get("net_contents", ""),
                "manufacturer": label.get("manufacturer", ""),
                "country_of_origin": label.get("country_of_origin", ""),
                "ingredients_inci": label.get("ingredients_inci", ""),
                "gosi_ok": bool(label.get("gosi_ok")),
            },
            "price": {
                "price_usd": price.get("price_usd"),
                "margin_pct": price.get("margin_pct"),
                "register_blocked": bool(price.get("register_blocked", False)),
            },
            "legal": {
                "status": legal.get("status", "missing"),
                "hard_block": hard_legal_block,
                "hard_block_reason": legal.get("hard_block_reason", ""),
            },
            "ready": not blocked_by,
            "blocked_by": blocked_by,
        })

    total = len(results)
    ready = sum(1 for row in results if row["ready"])
    generated_at = datetime.now(timezone.utc).isoformat()

    output = {
        "schema_version": 2,
        "generated_at": generated_at,
        "source": "data/daiso_real/shopify_s_recommendations.json",
        "total": total,
        "ready": ready,
        "counts": {
            "copy": total - blocker_counts["copy"],
            "gosi": total - blocker_counts["gosi"],
            "price": total - blocker_counts["price"],
            "legal": total - blocker_counts["legal"],
        },
        "blockers": {key: value for key, value in blocker_counts.items() if value},
        "count": total,
        "items": results,
    }

    OUTPUT.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"listing_gate 생성 완료: total={total}, ready={ready}, blockers={output['blockers']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
