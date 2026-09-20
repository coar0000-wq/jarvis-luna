#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YouTube 자막 근거를 Shopify 실행 전략 데이터로 변환한다.

외부 API나 유료 모델을 호출하지 않는다. 사람이 검토해 넣은 타임스탬프 근거만
사용하며, listing/legal/pricing 게이트를 우회하지 않는다.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data"
SOURCE = D / "manual" / "shopify_youtube_insights.json"
OUT = D / "shopify_marketing_strategy.json"
KST = timezone(timedelta(hours=9))
REQUIRED_PILLARS = {"acquisition", "cro", "retention", "aov", "seo_geo", "creative"}
TIMESTAMP_RE = re.compile(r"^\d{2}:\d{2}(?::\d{2})?-\d{2}:\d{2}(?::\d{2})?$")


def load(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_source(doc: dict) -> dict:
    videos = doc.get("videos") or []
    insights = doc.get("insights") or []
    if doc.get("schema_version") != 1:
        raise RuntimeError("shopify_youtube_insights schema_version 1 필요")
    if not videos or not insights:
        raise RuntimeError("YouTube 영상 또는 인사이트가 비어 있음")

    video_ids = [str(v.get("video_id") or "") for v in videos]
    if len(video_ids) != len(set(video_ids)) or any(not x for x in video_ids):
        raise RuntimeError("YouTube video_id 누락 또는 중복")
    known = set(video_ids)
    insight_ids = [str(x.get("id") or "") for x in insights]
    if len(insight_ids) != len(set(insight_ids)) or any(not x for x in insight_ids):
        raise RuntimeError("마케팅 insight id 누락 또는 중복")

    bad = []
    cited = Counter()
    for x in insights:
        evidence = x.get("evidence") or {}
        vid = str(evidence.get("video_id") or "")
        cited[vid] += 1
        required = [x.get("pillar"), x.get("tactic"), x.get("action"),
                    evidence.get("summary"), x.get("prerequisites"),
                    x.get("kpis"), x.get("teams")]
        if vid not in known or not all(required):
            bad.append(str(x.get("id")))
            continue
        if not TIMESTAMP_RE.match(str(evidence.get("timestamp") or "")):
            bad.append(str(x.get("id")))
    if bad:
        raise RuntimeError("근거 또는 실행 필드 불완전: " + ", ".join(sorted(set(bad))))
    uncited = sorted(known - set(cited))
    if uncited:
        raise RuntimeError("인사이트가 없는 영상: " + ", ".join(uncited))
    pillars = {str(x.get("pillar")) for x in insights}
    missing = sorted(REQUIRED_PILLARS - pillars)
    if missing:
        raise RuntimeError("핵심 전략 축 누락: " + ", ".join(missing))
    return {
        "passed": True,
        "video_count": len(videos),
        "insight_count": len(insights),
        "timestamped_evidence_count": len(insights),
        "uncited_video_count": 0,
        "required_pillars_present": sorted(REQUIRED_PILLARS),
    }


def product_fit(row: dict) -> dict:
    name = str(row.get("name") or "")
    bucket = str(row.get("bucket") or row.get("category") or "")
    low = name.lower()
    if bucket in {"마스크팩"} or any(k in low for k in ("마스크", "패드", "립", "선크림", "리필")):
        aov = ["MKT-012", "MKT-014", "MKT-015"]
    elif bucket in {"스킨케어", "클렌징", "바디케어", "헤어케어"}:
        aov = ["MKT-013", "MKT-014", "MKT-015"]
    else:
        aov = ["MKT-014", "MKT-015"]

    if any(k in low for k in ("레티놀", "리들", "pdrn", "피디알엔", "니들")):
        guardrail = "사용 주의·제품 사실을 먼저 제시하고 자극·치료 효능을 단정하지 않음"
    elif any(k in low for k in ("모공", "탄력", "미백", "진정")):
        guardrail = "고민 키워드는 탐색 태그로만 사용하고 임상·치료 효과로 확대하지 않음"
    else:
        guardrail = "고시·영문 라벨·법률 게이트가 확인한 사실만 사용"

    return {
        "canonical_product_id": row.get("canonical_product_id"),
        "pd_no": str(row.get("pd_no") or ""),
        "product": name,
        "bucket": bucket,
        "grade": row.get("grade", "S"),
        "score": row.get("shopify_score"),
        "agent_ready": bool(row.get("agent_ready")),
        "public_ready": bool(row.get("public_ready")),
        "recommended_insight_ids": ["MKT-002", "MKT-003", "MKT-004", "MKT-016"] + aov,
        "organic_first_actions": [
            "구매 질문형 PDP/FAQ 초안",
            "제품 제형·사용 순서 숏폼 콘티",
            "무료배송 임계값을 고려한 루틴 또는 수량 세트 손익 계산",
        ],
        "paid_action_status": "blocked_until_explicit_cost_approval",
        "claim_guardrail": guardrail,
    }


def build_experiments() -> list[dict]:
    return [
        {
            "id": "EXP-001", "phase": "prelaunch", "priority": 1,
            "name": "S상품 PDP 질문·이미지 증거 패키지",
            "insight_ids": ["MKT-002", "MKT-003", "MKT-004", "MKT-016"],
            "owner_teams": ["listing", "design", "legal"],
            "action": "상위 S상품부터 FAQ, 제형, 사용 순서, 고시 근거를 한 PDP 패키지로 만든다.",
            "kpis": ["pdp_completion_rate", "claims_rejection_rate"],
            "cost_mode": "free_local", "status": "ready_for_draft"
        },
        {
            "id": "EXP-002", "phase": "prelaunch", "priority": 2,
            "name": "고민별 유기 랜딩페이지",
            "insight_ids": ["MKT-001", "MKT-018", "MKT-019"],
            "owner_teams": ["market", "listing", "design", "legal"],
            "action": "민감 피부·모공·탄력 중 근거가 충분한 한 가지 고민으로 랜딩 초안을 만들고 내부 트래픽에서 메시지를 검토한다.",
            "kpis": ["landing_completion_rate", "legal_pass_rate"],
            "cost_mode": "free_local", "status": "ready_for_draft"
        },
        {
            "id": "EXP-003", "phase": "prelaunch", "priority": 3,
            "name": "번들·무료배송 손익표",
            "insight_ids": ["MKT-008", "MKT-013", "MKT-014", "MKT-015"],
            "owner_teams": ["pricing", "sourcing", "market"],
            "action": "낱개·스타터·루틴 세트별 기여이익과 무료배송 기준을 계산해 적자 오퍼를 제거한다.",
            "kpis": ["contribution_margin_per_order", "bundle_margin"],
            "cost_mode": "free_local", "status": "ready_for_modeling"
        },
        {
            "id": "EXP-004", "phase": "launch", "priority": 4,
            "name": "검색형 숏폼 유기 테스트",
            "insight_ids": ["MKT-005", "MKT-020"],
            "owner_teams": ["market", "design", "listing"],
            "action": "광고비 없이 사용 장면·제형·루틴 순서 세 형식으로 게시해 클릭과 상품 페이지 유입을 비교한다.",
            "kpis": ["organic_video_sessions", "shortform_link_ctr", "pdp_sessions"],
            "cost_mode": "free_organic", "status": "ready_after_assets"
        },
        {
            "id": "EXP-005", "phase": "launch", "priority": 5,
            "name": "웰컴 이메일 5단계",
            "insight_ids": ["MKT-006"],
            "owner_teams": ["market", "listing", "legal"],
            "action": "동의 기반 구독자에게 피부 고민별 웰컴 플로우를 구성하고 자체 성과만 측정한다.",
            "kpis": ["first_purchase_rate", "welcome_flow_revenue", "unsubscribe_rate"],
            "cost_mode": "existing_stack_only", "status": "ready_after_store"
        },
        {
            "id": "EXP-006", "phase": "launch", "priority": 6,
            "name": "전환 추적 QA",
            "insight_ids": ["MKT-007"],
            "owner_teams": ["market", "legal"],
            "action": "실제 광고 집행 전 테스트 주문으로 Shopify와 광고 플랫폼의 구매 이벤트 차이를 확인한다.",
            "kpis": ["event_match_quality", "purchase_event_gap"],
            "cost_mode": "no_paid_media", "status": "blocked_until_store_and_consent"
        },
        {
            "id": "EXP-007", "phase": "postpurchase", "priority": 7,
            "name": "검증 구매 리뷰 수집",
            "insight_ids": ["MKT-017"],
            "owner_teams": ["market", "listing", "legal"],
            "action": "첫 주문부터 피부타입·제형·향·재구매 의향을 구조적으로 수집한다.",
            "kpis": ["review_capture_rate", "verified_reviews_per_sku"],
            "cost_mode": "existing_stack_only", "status": "ready_after_first_order"
        },
        {
            "id": "EXP-008", "phase": "postpurchase", "priority": 8,
            "name": "보상·재구매 이메일",
            "insight_ids": ["MKT-009", "MKT-010", "MKT-011"],
            "owner_teams": ["market", "pricing", "legal"],
            "action": "재구매 주기가 관찰된 후 포인트 가치, 보상 사용, 실제 만료 알림을 순서대로 검증한다.",
            "kpis": ["second_purchase_rate_90d", "reward_redemption_rate", "incremental_repeat_rate"],
            "cost_mode": "existing_stack_only", "status": "blocked_until_repeat_data"
        },
        {
            "id": "EXP-009", "phase": "paid_scale", "priority": 9,
            "name": "유료 크리에이티브 테스트",
            "insight_ids": ["MKT-001", "MKT-020"],
            "owner_teams": ["market", "design", "legal"],
            "action": "명시적 비용 승인 이후에만 훅·형식·증거별 소액 광고 실험을 실행한다.",
            "kpis": ["cost_per_acquisition", "mer", "concept_win_rate"],
            "cost_mode": "paid_requires_explicit_approval", "status": "blocked_by_cost_policy"
        }
    ]


def build_strategy(write: bool = True) -> dict:
    source = load(SOURCE, {}) or {}
    quality = validate_source(source)
    rec_doc = load(D / "daiso_real" / "shopify_s_recommendations.json", {}) or {}
    gate_doc = load(D / "listing_gate.json", {}) or {}
    gate_by = {str(x.get("pd_no")): x for x in (gate_doc.get("items") or [])}

    recs = []
    for row in rec_doc.get("recommendations") or []:
        merged = dict(row)
        gate = gate_by.get(str(row.get("pd_no")), {})
        merged["agent_ready"] = gate.get("agent_ready", row.get("agent_ready"))
        merged["public_ready"] = gate.get("public_ready", row.get("public_ready"))
        recs.append(merged)

    insights = source.get("insights") or []
    by_pillar: dict[str, list[str]] = defaultdict(list)
    for x in insights:
        by_pillar[str(x.get("pillar"))].append(str(x.get("id")))
    dates = sorted(str(v.get("published_at") or "") for v in source.get("videos") or [])

    experiments = build_experiments()
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(KST).isoformat(),
        "generator": "scripts/build_shopify_marketing_strategy.py",
        "status": "evidence_ready",
        "scope": "US K-Beauty Shopify launch marketing",
        "cost_policy": {
            "default": "free_local_or_existing_stack",
            "paid_media": "blocked_until_explicit_user_approval",
            "paid_api": "not_used",
        },
        "source_coverage": {
            "method": source.get("method"),
            "videos": len(source.get("videos") or []),
            "insights": len(insights),
            "pillars": {k: len(v) for k, v in sorted(by_pillar.items())},
            "oldest_video_date": dates[0] if dates else None,
            "newest_video_date": dates[-1] if dates else None,
            "source_file": "data/manual/shopify_youtube_insights.json",
        },
        "quality_gate": quality,
        "source_ledger": source.get("videos") or [],
        "evidence_insights": insights,
        "execution_experiments": experiments,
        "product_playbooks": [product_fit(x) for x in recs],
        "funnel": {
            "discover": ["MKT-005", "MKT-016", "MKT-020"],
            "consider": ["MKT-001", "MKT-002", "MKT-003", "MKT-004", "MKT-017"],
            "convert": ["MKT-008", "MKT-012", "MKT-013", "MKT-014", "MKT-015"],
            "retain": ["MKT-006", "MKT-009", "MKT-010", "MKT-011"],
            "measure": ["MKT-007"],
        },
        "launch_order": [x["id"] for x in experiments],
        "guardrails": [
            "listing_gate와 legal_full을 통과하지 않은 효능·성분 문구는 게시하지 않는다.",
            "영상 제작자의 매출·전환 수치를 자사 목표치로 복사하지 않는다.",
            "현재 비용 정책에 따라 유료 광고와 유료 API는 명시 승인 전 실행하지 않는다.",
            "AI 산출물은 초안이며 제품 사실·고객 언어·법률 검토를 거친다.",
            "성과는 Shopify 실제 주문·기여이익과 자체 UTM으로 판정한다.",
        ],
        "rejected_claims": source.get("rejected_claims") or [],
        "integrity": {
            "listing_gate_generated_at": gate_doc.get("generated_at"),
            "s_product_count": len(recs),
            "product_playbook_count": len(recs),
            "public_ready_count": sum(1 for x in recs if x.get("public_ready")),
            "agent_ready_count": sum(1 for x in recs if x.get("agent_ready")),
        },
    }
    if write:
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    payload = build_strategy(write=True)
    print(json.dumps({
        "ok": True,
        "videos": payload["source_coverage"]["videos"],
        "insights": payload["source_coverage"]["insights"],
        "experiments": len(payload["execution_experiments"]),
        "product_playbooks": len(payload["product_playbooks"]),
        "paid_status": payload["cost_policy"]["paid_media"],
        "out": str(OUT.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
