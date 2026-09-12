#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the Shopify listing gate from the canonical S-grade pipeline outputs.

정본:
  - data/daiso_real/shopify_s_recommendations.json  (S등급)
  - data/shopify_listing_copy.json                 (영문 카피)
  - data/pricing_model.json                        (판매가)
  - data/legal_products.json                       (법률 하드블록)
  - data/gosi.json                                 (한국 고시 표 — 용량·전성분·제조사·원산지)
  - data/daiso_real/daiso_us_labels.json           (미국 라벨 영문 번역본)

'gosi' 통과 조건:
  한국 고시(gosi.json) 필수 4항목이 채워져 있으면 통과.
  미국 라벨은 별도 us_label 로 표시하되, 플레이스홀더 문구는 미완료로 본다.
"""

from __future__ import annotations

import json
import re
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
GOSI = DATA / "gosi.json"
OUTPUT = DATA / "listing_gate.json"

# 사람이 아직 안 채운 가짜 값 — 있으면 미완료로 본다
_PLACEHOLDER_RE = re.compile(
    r"(실제\s*확인|실제\s*포장|placeholder|TODO|TBD|미입력|확인\s*필요|작성\s*필요)",
    re.I,
)

_GOSI_REQ = ("ingredients", "volume", "maker", "origin")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"JSON 읽기 실패: {path}: {exc}") from exc


def by_pd_no(rows: Any) -> dict[str, dict[str, Any]]:
    """list / dict 모두 pd_no 키 맵으로 정규화."""
    result: dict[str, dict[str, Any]] = {}
    if isinstance(rows, dict):
        for key, value in rows.items():
            if isinstance(value, dict):
                result[str(value.get("pd_no") or value.get("product_id") or key)] = value
    elif isinstance(rows, list):
        for value in rows:
            if isinstance(value, dict) and (
                value.get("pd_no") is not None or value.get("product_id") is not None
            ):
                result[str(value.get("pd_no") or value.get("product_id"))] = value
    return result


def _real(text: Any) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    if _PLACEHOLDER_RE.search(s):
        return False
    return True


def main() -> int:
    recommendation_doc = load_json(RECOMMENDATIONS, {})
    copy_doc = load_json(COPY, {})
    pricing_doc = load_json(PRICING, {})
    legal_doc = load_json(LEGAL, {})
    labels_doc = load_json(LABELS, {})
    gosi_doc = load_json(GOSI, {})

    recommendations = [
        row for row in recommendation_doc.get("recommendations", [])
        if isinstance(row, dict) and row.get("grade") == "S"
    ]
    if not recommendations:
        raise RuntimeError(
            "S등급 추천 상품이 없습니다: data/daiso_real/shopify_s_recommendations.json"
        )

    copy_by_id = by_pd_no(copy_doc.get("items", []))
    offers = (pricing_doc.get("offers_by_product") or {}).get("single", [])
    price_by_id = by_pd_no(offers)
    legal_by_id = by_pd_no(legal_doc.get("items", {}))
    # labels 파일이 { "1048583": {...} } 형태이거나 { "items": {...} } 둘 다 허용
    if isinstance(labels_doc, dict) and "items" in labels_doc:
        label_by_id = by_pd_no(labels_doc.get("items"))
    else:
        label_by_id = by_pd_no(labels_doc)
    gosi_by_id = by_pd_no((gosi_doc or {}).get("items") or {})

    results: list[dict[str, Any]] = []
    blocker_counts = {
        "copy": 0,
        "gosi": 0,
        "us_label": 0,
        "price": 0,
        "legal": 0,
    }

    for rank, product in enumerate(recommendations, start=1):
        pd_no = str(product.get("pd_no", ""))
        copy_row = copy_by_id.get(pd_no, {})
        copy_data = copy_row.get("copy") or {}
        label = label_by_id.get(pd_no, {})
        price = price_by_id.get(pd_no, {})
        legal = legal_by_id.get(pd_no, {})
        kr = gosi_by_id.get(pd_no, {})

        has_copy = (
            copy_row.get("copy_status") == "ok"
            and bool(copy_data.get("title"))
            and bool(copy_data.get("description_html"))
        )

        # 한국 고시 4항목 — Shopify 등록 전 원천 데이터
        has_gosi = all(_real(kr.get(f)) for f in _GOSI_REQ)

        # 미국 영문 라벨 — 플레이스홀더 거절
        has_us_label = bool(
            label.get("gosi_ok")
            and _real(label.get("net_contents"))
            and _real(label.get("ingredients_inci"))
            and _real(label.get("manufacturer"))
            and _real(label.get("country_of_origin"))
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
        if not has_us_label:
            blocked_by.append("us_label")
            blocker_counts["us_label"] += 1
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
                "volume": kr.get("volume", ""),
                "maker": kr.get("maker", ""),
                "origin": kr.get("origin", ""),
                "ingredients": (str(kr.get("ingredients") or "")[:120]),
                "gosi_ok": has_gosi,
            },
            "us_label": {
                "net_contents": label.get("net_contents", ""),
                "manufacturer": label.get("manufacturer", ""),
                "country_of_origin": label.get("country_of_origin", ""),
                "ingredients_inci": label.get("ingredients_inci", ""),
                "us_label_ok": has_us_label,
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
        "schema_version": 3,
        "generated_at": generated_at,
        "source": "data/daiso_real/shopify_s_recommendations.json",
        "total": total,
        "ready": ready,
        "counts": {
            "copy": total - blocker_counts["copy"],
            "gosi": total - blocker_counts["gosi"],
            "us_label": total - blocker_counts["us_label"],
            "price": total - blocker_counts["price"],
            "legal": total - blocker_counts["legal"],
        },
        "blockers": {key: value for key, value in blocker_counts.items() if value},
        "count": total,
        "note": (
            "gosi=한국 고시 4항목, us_label=영문 라벨(플레이스홀더 제외), "
            "legal=MoCRA 등 하드블록. ready는 5개 조건 모두 통과한 건수."
        ),
        "items": results,
    }

    OUTPUT.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"listing_gate 생성 완료: total={total}, ready={ready}, "
        f"blockers={output['blockers']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
