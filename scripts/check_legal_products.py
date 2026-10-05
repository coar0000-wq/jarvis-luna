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
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_gosi_to_us_labels import current_s_registry, rows_by_id, real, field_current

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "legal_products.json"
RECOMMENDATIONS = DATA / "daiso_real" / "shopify_s_recommendations.json"
SCORE = DATA / "daiso_real" / "shopify_demand_score.json"
LABELS = DATA / "daiso_real" / "daiso_us_labels.json"
COPIES = DATA / "shopify_listing_copy.json"
RULES = DATA / "us_claim_rules.json"
MASTER = DATA / "product_master.json"

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
    ids = current_s_registry(load(SCORE, {}), load(MASTER, {}))
    return set(ids), "canonical registry-bound score/master current S union"


ENGLISH_LABEL_FIELDS = LABEL_FIELDS + ("product_name_en", "directions_en", "warnings_en")


def english_text(value: Any) -> bool:
    return (real(value) and bool(re.search(r"[A-Za-z]", value))
            and not any(c.isalpha() and ord(c) > 127
                        and "LATIN" not in unicodedata.name(c, "") for c in value))


def human_evidence(evidence: Any, pd_no: str, allowed_sources: tuple[str, ...]) -> bool:
    """A parser's verified/model/alt flags are not a product approval."""
    return (isinstance(evidence, dict) and evidence.get("human_approved") is True
            and str(evidence.get("product_id") or evidence.get("pd_no") or "") == pd_no
            and evidence.get("source_type") in allowed_sources
            and all(real(evidence.get(f)) for f in ("evidence_ref", "reviewed_by", "reviewed_at")))


def us_requirements(label: dict, pd_no: str) -> dict:
    missing = [field for field in ENGLISH_LABEL_FIELDS
               if not english_text(label.get(field)) or not field_current(label, field)]
    actual = human_evidence(label.get("actual_label_evidence"), pd_no,
                            ("actual_packaging", "approved_us_label"))
    rp = label.get("responsible_person")
    # Manufacturer is not RP; never infer RP/address from maker or collector flags.
    rp_ok = (isinstance(rp, dict) and english_text(rp.get("name"))
             and english_text(rp.get("address"))
             and human_evidence(label.get("responsible_person_evidence"), pd_no,
                                ("responsible_person_confirmation",)))
    evidence = label.get("product_safety_evidence")
    safety_ok = human_evidence(evidence, pd_no, ("manufacturer_product_safety",))
    safety_ok = (safety_ok and real(evidence.get("manufacturer"))
                 and as_text(evidence.get("manufacturer")).casefold() ==
                     as_text(label.get("manufacturer")).casefold()
                 and real(evidence.get("product_specific_basis")))
    return {
        "label_fields": {"ok": not missing, "detail": "US English fields present" if not missing
                         else "Missing/placeholder/stale/non-English: " + ", ".join(missing)},
        "actual_label_review": {"ok": actual, "detail": "Product-specific human-approved actual label evidence required"},
        "responsible_person": {"ok": bool(rp_ok), "detail": "Explicit RP name/address and human approval required; manufacturer is not RP"},
        "manufacturer_product_safety": {"ok": bool(safety_ok), "detail": "Product-specific manufacturer safety evidence with human approval required"},
    }


def main() -> int:
    legal_doc = load(OUT, {})
    if not isinstance(legal_doc, dict):
        legal_doc = {}

    existing_items = legal_doc.get("items")
    if not isinstance(existing_items, dict):
        existing_items = {}

    s_ids, s_source = current_s_ids()
    cp_registry = current_s_registry(load(SCORE, {}), load(MASTER, {}))
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

    labels = rows_by_id(load(LABELS, {}))

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
    target_ids = set(existing_items) | s_ids
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

        row.setdefault("name", (
            recommendation.get("name")
            or label.get("product_name_kr")
            or row.get("name")
            or ""
        ))
        row.setdefault("canonical_product_id", cp_registry.get(pd_no))

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

        requirements = us_requirements(label, pd_no)
        label_ok = all(result["ok"] for result in requirements.values())

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
            **requirements,
            "human_legal_approval": {
                "ok": row.get("status") == "pass"
                and all(real(row.get(f)) for f in ("reviewer", "reviewed_at")),
                "detail": "Human legal approval required; automation never creates PASS",
            },
        }

        blockers = [
            name for name, result in checks.items() if not result["ok"]
        ]
        hard_block = bool(blockers)

        # Preserve human decisions/signatures as history; blockers govern eligibility.
        row.setdefault("status", "auto_checked")
        row["effective_legal_pass"] = not hard_block and row.get("status") == "pass"
        row["auto_checks"] = checks
        row["auto_blockers"] = blockers
        row["needs_attention"] = hard_block
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
            if isinstance(row, dict) and row.get("effective_legal_pass") is True
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
