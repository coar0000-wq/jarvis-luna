#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""listing_gate.json 이 현재 입력으로 만들어진 것인지 판정하는 한 곳.

왜 필요했나 (2026-09-19)

  게이트에는 이미 agent_input_signature 가 있었다. 그런데 그것을 검사하는
  곳은 scripts/gemini_listing_copy.py 하나뿐이었다.

  그래서 이런 구멍이 있었다.

    build_listing_gate.py 로 게이트를 만든다            ready 8건
    이후 legal_products.json 에 hard_block 이 붙는다
    build_listing_gate.py 를 다시 돌리지 않는다
    export_shopify_operational.py 와
    build_shopify_action_queue.py 는 옛 ready 를 그대로 쓴다
    validate_commerce_architecture.py 는 OK 를 찍는다

  즉 사람에게 "승인해 달라"고 올라가는 Action 이 낡은 판정 위에서 만들어질 수
  있었다. Shopify 실행기를 붙이는 순간 그대로 바깥으로 나간다.

  서명 계산이 세 파일에 흩어져 있으면 또 갈라진다. 여기 한 곳에 둔다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

RECOMMENDATIONS = DATA / "daiso_real" / "shopify_s_recommendations.json"
PRICING = DATA / "pricing_model.json"
LEGAL = DATA / "legal_products.json"
LABELS = DATA / "daiso_real" / "daiso_us_labels.json"
GOSI = DATA / "gosi.json"
PRODUCT_MASTER = DATA / "product_master.json"
GATE = DATA / "listing_gate.json"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _doc(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def recommendation_signature(rows: list[dict]) -> str:
    semantic = [{
        "pd_no": str(x.get("pd_no") or x.get("product_id") or ""),
        "grade": x.get("grade"),
        "rank": x.get("rank"),
        "name": x.get("name"),
        "shopify_score": x.get("shopify_score"),
    } for x in rows]
    return sha256_bytes(_canonical(semantic))


def agent_input_signature(recommendations: list[dict]) -> dict[str, Any]:
    master = _doc(PRODUCT_MASTER)
    gosi = _doc(GOSI)
    labels = _doc(LABELS)
    pricing = _doc(PRICING)
    legal = _doc(LEGAL)
    semantic = {
        "data/product_master.json": master.get("pd_no_to_cp") or {},
        "data/gosi.json": gosi.get("items") or {},
        "data/daiso_real/daiso_us_labels.json": labels.get("items") or labels,
        "data/pricing_model.json": (pricing.get("offers_by_product") or {}).get("single") or [],
        "data/legal_products.json": legal.get("items") or {},
    }
    hashes = {path: sha256_bytes(_canonical(value)) for path, value in semantic.items()}
    return {
        "semantic_sources": hashes,
        "recommendations_sha256": recommendation_signature(recommendations),
    }


def current_recommendations() -> list[dict]:
    doc = _doc(RECOMMENDATIONS)
    rows = doc.get("recommendations") or []
    return [x for x in rows if isinstance(x, dict)]


def stale_reason(gate: dict | None = None) -> str:
    """게이트가 낡았으면 사람이 읽을 사유, 최신이면 빈 문자열."""
    doc = gate if isinstance(gate, dict) else _doc(GATE)
    if not doc:
        return "data/listing_gate.json 이 없거나 읽을 수 없습니다"

    recorded = doc.get("agent_input_signature") or {}
    if not recorded:
        return "listing_gate.json 에 agent_input_signature 가 없습니다"

    current = agent_input_signature(current_recommendations())
    if recorded == current:
        return ""

    changed = []
    recorded_sources = (recorded.get("semantic_sources") or {})
    current_sources = (current.get("semantic_sources") or {})
    for path in sorted(set(recorded_sources) | set(current_sources)):
        if recorded_sources.get(path) != current_sources.get(path):
            changed.append(path)
    if recorded.get("recommendations_sha256") != current.get("recommendations_sha256"):
        changed.append("data/daiso_real/shopify_s_recommendations.json")

    return ("listing_gate.json 이 현재 입력보다 오래됐습니다. 바뀐 입력: "
            + (", ".join(changed) or "알 수 없음")
            + " · scripts/build_listing_gate.py 를 다시 실행하세요")


def require_current(gate: dict | None = None) -> None:
    reason = stale_reason(gate)
    if reason:
        raise RuntimeError(reason)
