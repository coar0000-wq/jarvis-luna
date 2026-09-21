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

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_signature  # noqa: E402
import typesafe_decision_support  # noqa: E402

RECOMMENDATIONS = DATA / "daiso_real" / "shopify_s_recommendations.json"
COPY = DATA / "shopify_listing_copy.json"
PRICING = DATA / "pricing_model.json"
LEGAL = DATA / "legal_products.json"
LEGAL_FULL = DATA / "legal_full.json"
LABELS = DATA / "daiso_real" / "daiso_us_labels.json"
GOSI = DATA / "gosi.json"
PRODUCT_MASTER = DATA / "product_master.json"
OUTPUT = DATA / "listing_gate.json"

# 사람이 아직 안 채운 가짜 값 — 있으면 미완료로 본다
_PLACEHOLDER_RE = re.compile(
    r"(실제\s*확인|실제\s*포장|placeholder|TODO|TBD|미입력|확인\s*필요|작성\s*필요)",
    re.I,
)

_GOSI_REQ = ("ingredients", "volume", "maker", "origin")
_CP_RE = re.compile(r"^CP\d{6}$")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _recommendation_signature(rows: list[dict]) -> str:
    semantic = [{
        "pd_no": str(x.get("pd_no") or x.get("product_id") or ""),
        "grade": x.get("grade"),
        "rank": x.get("rank"),
        "name": x.get("name"),
        "shopify_score": x.get("shopify_score"),
    } for x in rows]
    raw = json.dumps(semantic, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(raw)


def _agent_input_signature(recommendations: list[dict]) -> dict[str, Any]:
    # 계산은 scripts/gate_signature.py 한 곳에만 둔다. 생성자와 검사자가
    # 각자 같은 식을 들고 있으면 언젠가 갈라져 거짓 통과가 난다.
    return gate_signature.agent_input_signature(recommendations)


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
    legal_full_doc = load_json(LEGAL_FULL, {})
    labels_doc = load_json(LABELS, {})
    gosi_doc = load_json(GOSI, {})
    master_doc = load_json(PRODUCT_MASTER, {})
    cp_registry = {
        str(k): str(v) for k, v in
        ((master_doc.get("pd_no_to_cp") or {}).items()
         if isinstance(master_doc, dict) else [])
    }

    recommendations = [
        row for row in recommendation_doc.get("recommendations", [])
        if isinstance(row, dict) and row.get("grade") == "S"
    ]
    agent_input_signature = _agent_input_signature(recommendations)

    # 팔지 않기로 한 것은 게이트에 올리지 않는다. (2026-09-13)
    # products.json 에서 빼도 추천 파일은 그대로라서, 뺀 상품이 계속
    # "막힘" 으로 남아 있었다. 1045421 태그 듀이 쿠션이 그랬다.
    # SPF50+ 자외선 차단 기능성이라 미국에선 OTC 의약품이고 애초에 팔 물건이 아닌데,
    # 고시가 없다고 게이트가 붙들고 있었다. 막힌 게 아니라 뺀 것이다.
    # items 는 pdNo 를 키로 하는 dict 다. 리스트로 알고 짰다가 한 번 헛돌았다.
    parked = load_json(DATA / "daiso_real" / "excluded_products.json", {})
    parked_items = parked.get("items") or {}
    if isinstance(parked_items, dict):
        parked_ids = {str(k) for k in parked_items}
    else:
        parked_ids = {
            str(r.get("pdNo") or r.get("pd_no"))
            for r in parked_items if isinstance(r, dict)
        }
    if parked_ids:
        kept = [r for r in recommendations
                if str(r.get("pdNo") or r.get("pd_no")) not in parked_ids]
        if len(kept) != len(recommendations):
            dropped = [str(r.get("pdNo") or r.get("pd_no"))
                       for r in recommendations if r not in kept]
            print(f"제외 목록에 있어 게이트에서 뺌 {len(dropped)}건: "
                  f"{', '.join(dropped)}")
        recommendations = kept

    if not recommendations:
        raise RuntimeError(
            "S등급 추천 상품이 없습니다: data/daiso_real/shopify_s_recommendations.json"
        )

    copy_by_id = by_pd_no(copy_doc.get("items", []))
    offers = (pricing_doc.get("offers_by_product") or {}).get("single", [])
    price_by_id = by_pd_no(offers)
    legal_by_id = by_pd_no(legal_doc.get("items", {}))
    legal_full_by_id = by_pd_no(legal_full_doc.get("items", {}))
    # labels 파일이 { "1048583": {...} } 형태이거나 { "items": {...} } 둘 다 허용
    if isinstance(labels_doc, dict) and "items" in labels_doc:
        label_by_id = by_pd_no(labels_doc.get("items"))
    else:
        label_by_id = by_pd_no(labels_doc)
    gosi_by_id = by_pd_no((gosi_doc or {}).get("items") or {})

    results: list[dict[str, Any]] = []
    blocker_counts = {
        "ontology": 0,
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
        legal_full = legal_full_by_id.get(pd_no, {})
        kr = gosi_by_id.get(pd_no, {})
        canonical_product_id = (
            product.get("canonical_product_id") or cp_registry.get(pd_no)
        )
        has_ontology = bool(
            canonical_product_id
            and _CP_RE.fullmatch(str(canonical_product_id))
            and cp_registry.get(pd_no) == str(canonical_product_id)
        )

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

        agent_blocked_by: list[str] = []
        if not has_ontology:
            agent_blocked_by.append("ontology")
        if not has_gosi:
            agent_blocked_by.append("gosi")
        if not has_us_label:
            agent_blocked_by.append("us_label")
        if not has_price:
            agent_blocked_by.append("price")
        if not has_legal:
            agent_blocked_by.append("legal")

        blocked_by: list[str] = []
        if not has_ontology:
            blocked_by.append("ontology")
            blocker_counts["ontology"] += 1
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

        public_blocked_by = list(blocked_by)
        if not legal_full.get("complete"):
            public_blocked_by.append("legal_full")

        # TypeSafe System One 방식의 보조 판단. 기본은 로컬 규칙만 쓰므로
        # 네트워크 호출도 비용도 없다. 실제 TypeSafe 호출은
        # TYPESAFE_ENABLED=1 + TYPESAFE_ALLOW_PAID=1 이 둘 다 있어야 한다.
        # 기존 점수·법률·게이트가 정본이며, 보조 판단은 이를 덮지 않는다.
        typesafe = typesafe_decision_support.evaluate({
            "canonical_product_id": canonical_product_id,
            "pd_no": pd_no,
            "name": product.get("name", ""),
            "grade": product.get("grade"),
            "shopify_score": product.get("shopify_score"),
            "blocked_by": blocked_by,
            "public_blocked_by": public_blocked_by,
            "gosi": {"gosi_ok": has_gosi},
            "us_label": {"us_label_ok": has_us_label},
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
            "legal_full_complete": bool(legal_full.get("complete")),
        })
        results.append({
            "rank": product.get("rank", rank),
            "canonical_product_id": canonical_product_id,
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
            "agent_ready": not agent_blocked_by,
            "agent_blocked_by": agent_blocked_by,
            "ready": not blocked_by,
            "blocked_by": blocked_by,
            "public_ready": not public_blocked_by,
            "public_blocked_by": public_blocked_by,
            "legal_full_complete": bool(legal_full.get("complete")),
            "typesafe": typesafe,
        })

    total = len(results)
    agent_ready = sum(1 for row in results if row["agent_ready"])
    ready = sum(1 for row in results if row["ready"])
    public_ready = sum(1 for row in results if row["public_ready"])
    generated_at = datetime.now(timezone.utc).isoformat()
    typesafe_modes: dict[str, int] = {}
    for row in results:
        mode = str((row.get("typesafe") or {}).get("mode") or "missing")
        typesafe_modes[mode] = typesafe_modes.get(mode, 0) + 1
    usage_ledger = typesafe_decision_support.ledger()
    typesafe_summary = {
        "framework": "typesafe_system_one_compatible",
        "mode_counts": typesafe_modes,
        "typesafe_calls": usage_ledger["calls"],
        "free_credits_only": sum(
            1 for row in results if (row.get("typesafe") or {}).get("free_credits_only")
        ),
        "paid_api_calls": sum(
            1 for row in results if (row.get("typesafe") or {}).get("paid_api_called")
        ),
        "enforced": sum(
            1 for row in results if (row.get("typesafe") or {}).get("enforced")
        ),
        "usage": usage_ledger,
        "note": (
            "기본은 비용 없는 로컬 advisory. 실제 호출은 TYPESAFE_ENABLED=1 과 "
            "TYPESAFE_FREE_CREDITS_ONLY=1(무료 크레딧 한도 내) 또는 "
            "TYPESAFE_ALLOW_PAID=1(유료 승인) 일 때만 한다. 크레딧 구매는 하지 않는다."
        ),
    }

    output = {
        "schema_version": 4,
        "generated_at": generated_at,
        "source": "data/daiso_real/shopify_s_recommendations.json",
        "agent_input_signature": agent_input_signature,
        "total": total,
        "agent_ready": agent_ready,
        "ready": ready,
        "draft_ready": ready,
        "public_ready": public_ready,
        "counts": {
            "ontology": total - blocker_counts["ontology"],
            "copy": total - blocker_counts["copy"],
            "gosi": total - blocker_counts["gosi"],
            "us_label": total - blocker_counts["us_label"],
            "price": total - blocker_counts["price"],
            "legal": total - blocker_counts["legal"],
            "legal_full": sum(1 for row in results if row["legal_full_complete"]),
        },
        "blockers": {key: value for key, value in blocker_counts.items() if value},
        "typesafe_summary": typesafe_summary,
        "count": total,
        "note": (
            "ontology=CP 정본 조인, gosi=한국 고시 4항목, "
            "us_label=영문 라벨(플레이스홀더 제외), legal=자동 하드블록, "
            "legal_full=MoCRA/FPLA 공개 필드. agent_ready는 LLM 입력 자격, "
            "ready는 Shopify 초안 준비, public_ready는 공개 판매 준비 건수."
        ),
        "items": results,
    }

    OUTPUT.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # S 추천의 registerable은 게이트만 정한다. 점수 단계에서 임의로 True를
    # 넣으면 10/10처럼 보이면서 실제 게이트는 7/10인 모순이 생긴다.
    gate_by_id = {str(row["pd_no"]): row for row in results}
    changed = False
    for row in recommendation_doc.get("recommendations") or []:
        if not isinstance(row, dict):
            continue
        pd_no = str(row.get("pd_no") or "")
        gate_row = gate_by_id.get(pd_no)
        if not gate_row:
            continue
        row["canonical_product_id"] = (
            row.get("canonical_product_id") or cp_registry.get(pd_no)
        )
        row["agent_ready"] = bool(gate_row["agent_ready"])
        row["agent_blocked_by"] = list(gate_row["agent_blocked_by"])
        row["registerable"] = bool(gate_row["ready"])
        row["blocked_by"] = list(gate_row["blocked_by"])
        row["public_ready"] = bool(gate_row["public_ready"])
        row["public_blocked_by"] = list(gate_row["public_blocked_by"])
        row["typesafe"] = gate_row.get("typesafe") or {}
        row["registerable_source"] = "data/listing_gate.json"
        row["gate_generated_at"] = generated_at
        changed = True
    if changed:
        recommendation_doc["agent_ready_count"] = agent_ready
        recommendation_doc["registerable_count"] = ready
        recommendation_doc["registerable_source"] = "data/listing_gate.json"
        RECOMMENDATIONS.write_text(
            json.dumps(recommendation_doc, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(
        f"listing_gate 생성 완료: total={total}, agent_ready={agent_ready}, "
        f"draft_ready={ready}, public_ready={public_ready}, "
        f"blockers={output['blockers']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
