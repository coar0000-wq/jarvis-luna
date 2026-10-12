#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""11팀 자기개선 기준선(baseline) 만들기.

왜 (2026-10-11 사용자 지시)
  "자기개선에서 비교자료 없음 이러는데 기준을 만들어놓고 시작해. 그래야 차후 자비스 능력이 좋아지지"
  team_improvement_evidence 는 비교할 이전 측정이 없으면 '비교 자료 없음'으로 둔다.
  그래서 팀마다 실제 산출물에서 셀 수 있는 지표 하나를 정하고, 처음 잰 값을 기준선으로 고정한다.
  이후 실행은 current 만 갱신한다. 기준선은 덮어쓰지 않는다(사람이 지우기 전까지 고정).

원칙
  - 값은 data/ 의 실제 산출물에서 센다. 추정하지 않는다. 파일이 없으면 그 팀은 건너뛴다.
  - 기준선 대비 변화는 '내부 측정'일 뿐 매출·사업 성과 검증이 아니다(verified_gain 아님).

출력  data/self_improve/team_baselines.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "self_improve" / "team_baselines.json"


def load(rel: str):
    try:
        return json.loads((ROOT / rel).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def n(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def measure() -> dict:
    """팀 id -> (지표, 단위, 방향, 값, 분모, 근거 파일)."""
    out = {}
    inst = load("data/institution_sources.json")
    if isinstance(inst, dict):
        out["institutions"] = ("collected_institution_items", "items", "increase", n(inst.get("total")),
                               (n(inst.get("organizations")) if isinstance(inst.get("organizations"), int)
                                else len(inst.get("by_org") or {})) or None,
                               "data/institution_sources.json")
    us = [load(p) for p in ("data/amazon_products.json", "data/walmart_products.json", "data/oliveyoung_us_products.json")]
    if any(isinstance(d, dict) for d in us):
        total = sum(n(d.get("count")) or len(d.get("products") or []) for d in us if isinstance(d, dict))
        out["market"] = ("us_market_products_observed", "products", "increase", total, None,
                         "data/amazon_products.json+walmart+oliveyoung")
    copy = load("data/shopify_listing_copy.json")
    if isinstance(copy, dict):
        out["listing"] = ("listing_copies_ok", "copies", "increase", n(copy.get("ok")), n(copy.get("eligible")) or None,
                          "data/shopify_listing_copy.json")
    gate = load("data/listing_gate.json")
    if isinstance(gate, dict):
        items = [r for r in gate.get("items") or [] if isinstance(r, dict)]
        priced = sum(1 for r in items if "price" not in (r.get("public_blocked_by") or []))
        out["pricing"] = ("s_products_price_gate_passed", "products", "increase", priced, len(items) or None,
                          "data/listing_gate.json")
    legal = load("data/legal_full.json")
    if isinstance(legal, dict):
        out["legal"] = ("s_products_legal_complete", "products", "increase", n(legal.get("complete")),
                        n(legal.get("total")) or None, "data/legal_full.json")
    ai = load("data/robotics_sources.json")
    if isinstance(ai, dict):
        out["robotics"] = ("ai_items_collected", "items", "increase", n(ai.get("total")),
                           len(ai.get("sources") or {}) or None, "data/robotics_sources.json")
    ch = load("data/channel_candidates.json")
    if isinstance(ch, dict):
        out["channels"] = ("usable_channels", "channels", "increase", n(ch.get("usable")), n(ch.get("tested")) or None,
                           "data/channel_candidates.json")
    real = load("data/knowledge/real_sources.json")
    if isinstance(real, dict):
        total = sum(len((v or {}).get("items") or []) for v in (real.get("sources") or {}).values() if isinstance(v, dict))
        out["knowledge"] = ("real_knowledge_items", "items", "increase", total,
                            len(real.get("sources") or {}) or None, "data/knowledge/real_sources.json")
    return out


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    old = load("data/self_improve/team_baselines.json") or {}
    teams = dict(old.get("teams") or {})
    for tid, (metric, unit, direction, value, denom, src) in measure().items():
        point = {"value": value, "denominator": denom, "measured_at": now, "source_path": src}
        prev = teams.get(tid) or {}
        if prev.get("metric") != metric or not isinstance(prev.get("baseline"), dict):
            teams[tid] = {"metric": metric, "unit": unit, "direction": direction, "baseline": point, "current": point,
                          "baseline_note": "첫 측정값을 기준선으로 고정 (2026-10-11 사용자 지시)"}
        else:
            prev["current"] = point
            b = prev["baseline"].get("value")
            prev["change"] = (value - b) if isinstance(b, int) else None
            teams[tid] = prev
    doc = {"schema_version": 1, "generated_at": now, "generator": "scripts/build_team_baselines.py",
           "policy": "팀마다 실제 산출물에서 센 지표 1개. 첫 측정값을 기준선으로 고정하고 매 실행 current 만 갱신한다. "
                     "내부 측정이며 매출·사업 성과 검증(verified_gain)이 아니다.",
           "teams": dict(sorted(teams.items()))}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("TEAM_BASELINES_OK " + " ".join(f"{k}={v['baseline']['value']}->{v['current']['value']}" for k, v in doc["teams"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
