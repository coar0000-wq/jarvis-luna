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
  - 2026-10-16: 근거 파일이 스스로 적은 시각(source_clock)을 함께 남긴다. 신선도는 이 시각으로 판정한다.
    측정 시각(measured_at)만 보면 2주 넘게 안 바뀐 산출물을 세도 '오늘 측정' 으로 보였다.
  - 2026-10-16: 소싱·디자인·그래프 3팀 지표 추가. 기준은 docs/team_improvement_criteria.md.

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


def clock(doc, *paths) -> str | None:
    """근거 파일이 스스로 적은 시각. 못 찾으면 None (측정 시각으로 대신하지 않는다)."""
    for path in paths or (("collected_at",), ("generated_at",), ("updated_at",), ("captured_at",)):
        cur = doc
        for key in path:
            cur = cur.get(key) if isinstance(cur, dict) else None
        if isinstance(cur, str) and len(cur) >= 10:
            return cur
    return None


def measure() -> dict:
    """팀 id -> (지표, 단위, 방향, 값, 분모, 근거 파일, 근거 시각)."""
    out = {}
    inst = load("data/institution_sources.json")
    if isinstance(inst, dict):
        out["institutions"] = ("collected_institution_items", "items", "increase", n(inst.get("total")),
                               (n(inst.get("organizations")) if isinstance(inst.get("organizations"), int)
                                else len(inst.get("by_org") or {})) or None,
                               "data/institution_sources.json", clock(inst))
    us = [load(p) for p in ("data/amazon_products.json", "data/walmart_products.json", "data/oliveyoung_us_products.json")]
    if any(isinstance(d, dict) for d in us):
        total = sum(n(d.get("count")) or len(d.get("products") or []) for d in us if isinstance(d, dict))
        # 세 파일 중 가장 오래된 시각. 하나라도 낡으면 합계도 낡은 것이다.
        clocks = [c for c in (clock(d) for d in us if isinstance(d, dict)) if c]
        out["market"] = ("us_market_products_observed", "products", "increase", total, None,
                         "data/amazon_products.json+walmart+oliveyoung", min(clocks) if clocks else None)
    copy = load("data/shopify_listing_copy.json")
    if isinstance(copy, dict):
        out["listing"] = ("listing_copies_ok", "copies", "increase", n(copy.get("ok")), n(copy.get("eligible")) or None,
                          "data/shopify_listing_copy.json", clock(copy))
    gate = load("data/listing_gate.json")
    if isinstance(gate, dict):
        items = [r for r in gate.get("items") or [] if isinstance(r, dict)]
        priced = sum(1 for r in items if "price" not in (r.get("public_blocked_by") or []))
        out["pricing"] = ("s_products_price_gate_passed", "products", "increase", priced, len(items) or None,
                          "data/listing_gate.json", clock(gate))
    legal = load("data/legal_full.json")
    if isinstance(legal, dict):
        out["legal"] = ("s_products_legal_complete", "products", "increase", n(legal.get("complete")),
                        n(legal.get("total")) or None, "data/legal_full.json", clock(legal))
    ai = load("data/robotics_sources.json")
    if isinstance(ai, dict):
        out["robotics"] = ("ai_items_collected", "items", "increase", n(ai.get("total")),
                           len(ai.get("sources") or {}) or None, "data/robotics_sources.json", clock(ai))
    ch = load("data/channel_candidates.json")
    if isinstance(ch, dict):
        out["channels"] = ("usable_channels", "channels", "increase", n(ch.get("usable")), n(ch.get("tested")) or None,
                           "data/channel_candidates.json", clock(ch))
    real = load("data/knowledge/real_sources.json")
    if isinstance(real, dict):
        total = sum(len((v or {}).get("items") or []) for v in (real.get("sources") or {}).values() if isinstance(v, dict))
        out["knowledge"] = ("real_knowledge_items", "items", "increase", total,
                            len(real.get("sources") or {}) or None, "data/knowledge/real_sources.json", clock(real))
    # 2026-10-16: 아래 세 팀은 기준선이 없어 '비교 자료 없음 · 근거 없음 또는 오래됨' 으로만 나왔다.
    # 예전 시험(pilot) 파일의 검토된 바이트에만 기대고 있었고, 그 파일이 바뀌거나 14일이 지나면 차단됐다.
    status = load("data/daiso_real/collection_status.json")
    if isinstance(status, dict) and isinstance(status.get("last_success"), dict):
        ok = status["last_success"]
        out["sourcing"] = ("useful_fetch_count", "fetches", "increase", n(ok.get("ok")), n(ok.get("requested")) or None,
                           "data/daiso_real/collection_status.json#last_success", clock(ok, ("finished_at",)))
    design = load("data/design_team.json")
    quality = ((design or {}).get("references") or {}).get("quality") if isinstance(design, dict) else None
    if isinstance(quality, dict):
        out["design"] = ("relevant_reference_count", "references", "increase", n(quality.get("relevant")),
                         n(quality.get("items")) or None, "data/design_team.json#references.quality",
                         clock(design, ("generated_at",)))
    loops = load("data/self_improve/status.json")
    topics = ((loops or {}).get("loops") or {}).get("topics") if isinstance(loops, dict) else None
    if isinstance(topics, dict) and "uncategorized_before" in topics:
        out["graph"] = ("uncategorized_records", "records", "decrease", n(topics.get("uncategorized_before")),
                        n(topics.get("records")) or None, "data/self_improve/status.json#loops.topics",
                        clock(loops, ("generated_at",)))
    return out


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    old = load("data/self_improve/team_baselines.json") or {}
    teams = dict(old.get("teams") or {})
    for tid, (metric, unit, direction, value, denom, src, source_clock) in measure().items():
        point = {"value": value, "denominator": denom, "measured_at": now, "source_path": src,
                 "source_clock": source_clock}
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
                     "신선도는 근거 파일 자신의 시각(source_clock)으로 본다. "
                     "내부 측정이며 매출·사업 성과 검증(verified_gain)이 아니다. 기준: docs/team_improvement_criteria.md",
           "teams": dict(sorted(teams.items()))}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("TEAM_BASELINES_OK " + " ".join(f"{k}={v['baseline']['value']}->{v['current']['value']}" for k, v in doc["teams"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
