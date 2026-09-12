#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S등급 상품의 미국 판매 전 자동 법률·라벨 점검.

중요:
- 이 스크립트는 법률 자문이나 사람의 최종 PASS 판정을 대신하지 않는다.
- 화장품 라벨 정보는 data/daiso_real/daiso_us_labels.json에서 읽는다.
- data/gosi.json은 국가고시 데이터이므로 화장품 라벨 판정에 사용하지 않는다.
- SPF/선스크린 상품은 OTC 의약품 검토 대상으로 계속 차단한다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "legal_products.json"
RECOMMENDATIONS = DATA / "daiso_real" / "shopify_s_recommendations.json"
LABELS = DATA / "daiso_real" / "daiso_us_labels.json"
COPIES = DATA / "shopify_listing_copy.json"
RULES = DATA / "us_claim_rules.json"

S_PRODUCT_IDS = {
    "1048583",
    "1062781",
    "1041749",
    "1049271",
    "1041403",
    "1045421",
    "1059834",
}

LABEL_FIELDS = (
    "ingredients_inci",
    "net_contents",
    "manufacturer",
    "country_of_origin",
)


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def as_text(value: Any) -> str:
    return str(value or "").strip()


def main() -> int:
    legal_doc = load(OUT, {})
    if not isinstance(legal_doc, dict):
        legal_doc = {}

    existing_items = legal_doc.get("items")
    if not isinstance(existing_items, dict):
        existing_items = {}

    recommendations_doc = load(RECOMMENDATIONS, {})
    recommendations = recommendations_doc.get("recommendations") or []
    recommendations_by_id = {
        str(row.get("pd_no")): row
        for row in recommendations
        if isinstance(row, dict)
        and str(row.get("pd_no", "")) in S_PRODUCT_IDS
        and row.get("grade") == "S"
    }

    labels = load(LABELS, {})
    if not isinstance(labels, dict):
        labels = {}

    copies_doc = load(COPIES, {})
    copies = {
        str(row.get("pd_no")): (row.get("copy") or {})
        for row in (copies_doc.get("items") or [])
        if isinstance(row, dict) and row.get("pd_no") is not None
    }

    rules_doc = load(RULES, {})
    banned = [
        as_text(term).lower()
        for group in (rules_doc.get("banned") or {}).values()
        if isinstance(group, list)
        for term in group
        if as_text(term)
    ]

    # 기존 상품을 보존하면서 현재 S등급 상품이 누락되어 있으면 자동 생성한다.
    target_ids = set(existing_items) | set(recommendations_by_id)
    flagged = 0
    clean = 0

    for pd_no in sorted(target_ids):
        row = existing_items.get(pd_no)
        if not isinstance(row, dict):
            row = {}
            existing_items[pd_no] = row

        recommendation = recommendations_by_id.get(pd_no, {})
        label = labels.get(pd_no) or {}
        copy = copies.get(pd_no) or {}

        row["name"] = (
            recommendation.get("name")
            or label.get("product_name_kr")
            or row.get("name")
            or ""
        )

        text_blob = " ".join(
            as_text(copy.get(field))
            for field in (
                "title",
                "description_html",
                "seo_title",
                "seo_description",
                "product_type",
            )
        )
        text_blob += " " + " ".join(
            as_text(tag) for tag in (copy.get("tags") or [])
        )

        claim_hits = sorted({term for term in banned if term in text_blob.lower()})
        product_blob = " ".join(
            as_text(value)
            for value in (
                recommendation.get("name"),
                label.get("product_name_kr"),
                row.get("name"),
            )
        )
        is_spf = bool(
            re.search(r"spf\s*\d+|선크림|선쿠션|sunscreen", product_blob, re.I)
        )

        label_ok = all(as_text(label.get(field)) for field in LABEL_FIELDS)
        label_missing = [
            field for field in LABEL_FIELDS if not as_text(label.get(field))
        ]

        checks = {
            "banned_claim": {
                "ok": not claim_hits,
                "detail": ", ".join(claim_hits[:5]) or "없음",
            },
            "otc_sunscreen": {
                "ok": not is_spf,
                "detail": (
                    "SPF/선스크린 제품 - 미국 OTC 의약품 검토 필요"
                    if is_spf else "해당 없음"
                ),
            },
            "label_fields": {
                "ok": label_ok,
                "detail": (
                    "4항목 확보"
                    if label_ok
                    else "미확보: " + ", ".join(label_missing)
                ),
            },
        }

        blockers = [
            name for name, result in checks.items() if not result["ok"]
        ]
        hard_block = bool(blockers)

        row["status"] = row.get("status") or "auto_checked"
        if row["status"] == "pass" and hard_block:
            # 새 자동 차단 사유가 생기면 사람 PASS를 유지하지 않는다.
            row["status"] = "pending"
        row["auto_checks"] = checks
        row["auto_blockers"] = blockers
        row["needs_attention"] = bool(claim_hits) or is_spf or not label_ok
        row["hard_block"] = hard_block
        row["hard_block_reason"] = (
            "자동 점검 미통과: " + ", ".join(blockers)
            if blockers else ""
        )
        row["auto_checked_at"] = now()

        if hard_block or row["status"] != "pass":
            flagged += 1
        else:
            clean += 1

    legal_doc["team"] = legal_doc.get("team", "법률·규제팀")
    legal_doc["items"] = existing_items
    legal_doc["auto_summary"] = {
        "checked": len(existing_items),
        "clean": clean,
        "needs_attention": flagged,
        "pass": sum(
            1 for row in existing_items.values()
            if isinstance(row, dict) and row.get("status") == "pass"
        ),
    }
    legal_doc["auto_checked_at"] = now()

    OUT.write_text(
        json.dumps(legal_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"법률 점검 완료: {len(existing_items)}건 · "
        f"자동 무차단 {clean} · 주의/차단 {flagged}"
    )
    for pd_no in sorted(recommendations_by_id):
        row = existing_items[pd_no]
        if row.get("hard_block"):
            print(
                f"  차단 {pd_no} {row.get('name', '')[:30]}: "
                f"{row.get('hard_block_reason', '')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
