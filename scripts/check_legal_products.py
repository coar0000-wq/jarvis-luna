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
SCORE = DATA / "daiso_real" / "shopify_demand_score.json"
LABELS = DATA / "daiso_real" / "daiso_us_labels.json"
COPIES = DATA / "shopify_listing_copy.json"
RULES = DATA / "us_claim_rules.json"

# 예전에는 S등급 상품번호 일곱 개가 여기 박혀 있었다.
#
#   S_PRODUCT_IDS = {"1048583","1062781","1041749","1049271",
#                    "1041403","1045421","1059834"}
#
# 점수는 매 실행마다 다시 계산되는데 이 목록은 안 바뀌었다.
# 2026-09-13 에 대조해 보니 실제 S등급에 1053482 가 있는데 목록엔 없었다.
# 그 상품은 법률 점검을 아예 안 받고 있었다. 반대로 목록에만 있고
# 지금은 S등급이 아닌 것도 있었다.
#
# 박아 두면 반드시 어긋난다. 점수 파일에서 읽는다.

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


def current_s_ids() -> tuple[set[str], str]:
    """지금 S등급인 상품번호를 점수 파일에서 읽는다.

    점수 파일을 못 읽으면 추천 파일로 물러선다. 둘 다 없으면 빈 집합이다.
    빈 집합이면 아무것도 점검하지 않는다. 그게 맞다.
    없는 근거로 통과 판정을 내는 것보다 안 하는 것이 낫다.
    """
    doc = load(SCORE, {})
    rows = (doc.get("all_scored") or []) if isinstance(doc, dict) else []
    ids = {str(r.get("pd_no")) for r in rows
           if isinstance(r, dict) and r.get("grade") == "S" and r.get("pd_no")}
    if ids:
        return ids, "shopify_demand_score.json 의 all_scored 중 grade S"

    doc = load(RECOMMENDATIONS, {})
    rows = (doc.get("recommendations") or []) if isinstance(doc, dict) else []
    ids = {str(r.get("pd_no")) for r in rows
           if isinstance(r, dict) and r.get("grade") == "S" and r.get("pd_no")}
    if ids:
        return ids, "shopify_s_recommendations.json (점수 파일을 못 읽어 물러섬)"

    return set(), "S등급 목록을 못 읽었다"


def main() -> int:
    legal_doc = load(OUT, {})
    if not isinstance(legal_doc, dict):
        legal_doc = {}

    existing_items = legal_doc.get("items")
    if not isinstance(existing_items, dict):
        existing_items = {}

    s_ids, s_source = current_s_ids()
    print(f"S등급 {len(s_ids)}건 · 출처: {s_source}")

    recommendations_doc = load(RECOMMENDATIONS, {})
    recommendations = recommendations_doc.get("recommendations") or []
    recommendations_by_id = {
        str(row.get("pd_no")): row
        for row in recommendations
        if isinstance(row, dict)
        and str(row.get("pd_no", "")) in s_ids
    }

    # ------------------------------------------------------------
    # 점검 범위를 지금 S등급으로 좁힌다 (2026-09-13)
    #
    # 예전에는 이랬다.
    #   target_ids = set(existing_items) | set(recommendations_by_id)
    # 한 번 들어온 상품을 영원히 보존한다는 뜻이다.
    #
    # 그래서 S등급에서 빠진 상품이 목록에 계속 남았다. 그것들은 us_label
    # 이 없으니 label_fields 를 통과할 수 없고, 통과할 수 없으니 영원히
    # 차단으로 남는다. 화면에는 "등록 차단 7건" 이 계속 떴다.
    #
    # 2026-09-13 에 차단 7건을 추적해 보니 일곱 개 전부 지금 S등급이
    # 아니었다. 팔 생각이 없는 상품 때문에 고칠 수 없는 경고가 떠 있었다.
    # 고칠 수 없는 경고는 사람이 경고를 무시하게 만든다.
    #
    # 지우지는 않는다. 나중에 다시 S등급이 되면 그때까지의 판정을 살린다.
    # out_of_scope 로 옮겨 두고 점검과 집계에서만 뺀다.
    # ------------------------------------------------------------
    out_of_scope = legal_doc.get("out_of_scope")
    if not isinstance(out_of_scope, dict):
        out_of_scope = {}

    # 다시 S등급이 된 것은 도로 가져온다.
    for pd_no in list(out_of_scope):
        if pd_no in s_ids:
            existing_items[pd_no] = out_of_scope.pop(pd_no).get("row") or {}

    dropped = []
    for pd_no in list(existing_items):
        if pd_no not in s_ids:
            row = existing_items.pop(pd_no)
            out_of_scope[pd_no] = {
                "name": row.get("name", ""),
                "왜_뺐나": "지금 S등급이 아니다. 팔 계획이 없으므로 점검하지 않는다.",
                "뺀_시각": now(),
                "마지막_판정": row.get("hard_block_reason") or row.get("status"),
                "row": row,
            }
            dropped.append(pd_no)

    if dropped:
        print(f"범위 밖으로 옮김 {len(dropped)}건: {dropped[:8]}")

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
    legal_doc["out_of_scope"] = out_of_scope
    legal_doc["_범위"] = (
        f"지금 S등급 {len(s_ids)}건만 점검한다. 출처는 {s_source}. "
        "S등급에서 빠진 상품은 out_of_scope 로 옮기고 점검·집계에서 뺀다. "
        "지우지는 않으므로 다시 S등급이 되면 그때까지의 판정이 살아난다. "
        "예전에는 한 번 들어온 상품을 영원히 보존해서, 팔 계획도 없는 "
        "상품 때문에 고칠 수 없는 차단 경고가 계속 떴다."
    )
    legal_doc["auto_summary"] = {
        "checked": len(existing_items),
        "clean": clean,
        "needs_attention": flagged,
        "pass": sum(
            1 for row in existing_items.values()
            if isinstance(row, dict) and row.get("status") == "pass"
        ),
        "out_of_scope": len(out_of_scope),
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
