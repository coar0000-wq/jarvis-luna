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
        "recommended_insight_ids": ["MKT-002", "MKT-003", "MKT-004", "MKT-016",
                                    "MKT-023", "MKT-025", "MKT-026", "MKT-032",
                                    "MKT-034", "MKT-035", "MKT-047", "MKT-049", "MKT-051"] + aov,
        "organic_first_actions": [
            "구매 질문형 PDP/FAQ 초안",
            "제품 제형·사용 순서 숏폼 콘티",
            "무료배송 임계값을 고려한 루틴 또는 수량 세트 손익 계산",
        ],
        "paid_action_status": "blocked_until_explicit_user_approval",
        "claim_guardrail": guardrail,
    }


def build_experiments() -> list[dict]:
    return [
        {
            "id": "EXP-001", "phase": "prelaunch", "priority": 1,
            "name": "S상품 PDP 질문·이미지 증거 패키지",
            "insight_ids": ["MKT-002", "MKT-003", "MKT-004", "MKT-016", "MKT-026"],
            "owner_teams": ["listing", "design", "legal"],
            "action": "상위 S상품부터 FAQ, 제형, 사용 순서, 고시 근거와 유효한 구조화 데이터를 한 PDP 패키지로 만든다.",
            "kpis": ["pdp_completion_rate", "structured_data_valid_rate", "claims_rejection_rate"],
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
            "name": "번들·할인·무료배송 손익표",
            "insight_ids": ["MKT-008", "MKT-013", "MKT-014", "MKT-015", "MKT-021", "MKT-022"],
            "owner_teams": ["pricing", "sourcing", "market"],
            "action": "낱개·스타터·루틴 세트와 할인 중첩·무료배송 시나리오별 기여이익을 계산해 적자 오퍼를 제거한다.",
            "kpis": ["contribution_margin_per_order", "bundle_margin", "discount_cost_rate"],
            "cost_mode": "free_local", "status": "ready_for_modeling"
        },
        {
            "id": "EXP-004", "phase": "launch", "priority": 4,
            "name": "검색형 숏폼 유기 테스트",
            "insight_ids": ["MKT-005", "MKT-020", "MKT-027"],
            "owner_teams": ["market", "design", "listing"],
            "action": "광고비 없이 훅-발견-혜택-소프트 CTA와 문장별 B-roll을 사용 장면·제형·루틴 순서 형식으로 게시해 반응을 비교한다.",
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
            "cost_mode": "paid_requires_explicit_approval", "status": "blocked_until_explicit_user_approval"
        },
        {
            "id": "EXP-010", "phase": "prelaunch", "priority": 10,
            "name": "AI 카탈로그·구조화 데이터 QA",
            "insight_ids": ["MKT-023", "MKT-026"],
            "owner_teams": ["market", "listing", "legal"],
            "action": "공개 준비 상품의 가격·재고·정책·스키마를 검증하고 대표 구매 질문에서 상품 노출 누락을 기록한다.",
            "kpis": ["catalog_eligible_sku_rate", "structured_data_valid_rate", "ai_query_product_coverage"],
            "cost_mode": "free_local", "status": "ready_after_store"
        },
        {
            "id": "EXP-011", "phase": "postpurchase", "priority": 11,
            "name": "운영 이벤트 기반 리텐션",
            "insight_ids": ["MKT-028", "MKT-029"],
            "owner_teams": ["market", "legal"],
            "action": "실제 배송 지연에는 선제 안내를 보내고 저참여 구독자는 재참여 후 선셋 처리해 고객 경험과 목록 품질을 함께 관리한다.",
            "kpis": ["where_is_my_order_rate", "pre_fulfillment_cancel_rate", "reactivation_rate", "deliverability_rate"],
            "cost_mode": "existing_stack_only", "status": "ready_after_store"
        },
        {
            "id": "EXP-012", "phase": "paid_scale", "priority": 12,
            "name": "AI 캠페인 승인 큐",
            "insight_ids": ["MKT-024"],
            "owner_teams": ["market", "design", "listing", "legal"],
            "action": "AI 캠페인 제안의 대상·클레임·예산·일정을 승인 큐에서 검토하며 유료 집행은 명시적 사용자 승인 전까지 차단한다.",
            "kpis": ["campaign_approval_rate", "claims_rejection_rate", "unapproved_spend"],
            "cost_mode": "paid_requires_explicit_approval", "status": "blocked_until_explicit_user_approval"
        },
        {
            "id": "EXP-013", "phase": "launch", "priority": 13,
            "name": "장바구니 회수 중복·동의·종료 QA",
            "insight_ids": ["MKT-030", "MKT-031"],
            "owner_teams": ["market", "pricing", "legal"],
            "action": "Shopify 기본 기능 또는 이미 승인된 발송 스택에서 중복 알림을 제거하고 동의 필터, 구매 종료 조건, 할인 지연, 승인 테스트 계정을 점검한 뒤에만 플로우를 활성화한다.",
            "kpis": ["duplicate_recovery_message_rate", "purchase_exit_success_rate", "cart_recovery_rate", "discount_used_order_rate"],
            "cost_mode": "native_or_existing_stack_only", "status": "blocked_until_store_and_consent"
        },
        {
            "id": "EXP-014", "phase": "launch", "priority": 14,
            "name": "상품피드 GEO 진실원장",
            "insight_ids": ["MKT-032", "MKT-033"],
            "owner_teams": ["market", "listing", "sourcing", "legal"],
            "action": "상품 사실·구조화 데이터·Merchant Center 피드를 한 원장으로 대조하고 누락 속성과 가격·재고 불일치를 오류 큐로 보낸다.",
            "kpis": ["product_data_completeness", "merchant_center_eligible_rate", "price_inventory_mismatch_rate", "product_query_coverage"],
            "cost_mode": "free_native", "status": "blocked_until_store_and_feed"
        },
        {
            "id": "EXP-015", "phase": "prelaunch", "priority": 15,
            "name": "브랜드 선호·고객 여정 지도",
            "insight_ids": ["MKT-036", "MKT-038"],
            "owner_teams": ["market", "listing", "design", "knowledge", "legal"],
            "action": "고객 인터뷰로 실제 정보 접점을 확인하고 세그먼트별 최초 접점, 랜딩 질문, 이메일 또는 구매 전환, 재구매까지의 메시지 지도를 작성한다.",
            "kpis": ["customer_interview_count", "journey_step_coverage", "landing_message_match_rate", "third_party_brand_mentions"],
            "cost_mode": "free_organic", "status": "ready_for_research"
        },
        {
            "id": "EXP-016", "phase": "launch", "priority": 16,
            "name": "연관상품 유기 획득-이메일 교차판매",
            "insight_ids": ["MKT-037", "MKT-039", "MKT-040"],
            "owner_teams": ["sourcing", "pricing", "market", "design", "listing", "legal"],
            "action": "기존에 보유하고 품질·마진 검증이 끝난 연관 상품만 유기 콘텐츠로 소개하고, 관심 행동별 이메일에서 보완 상품과 핵심 소모품을 과도한 할인 없이 연결한다.",
            "kpis": ["validated_adjacent_sku_count", "organic_content_sessions", "cross_sell_attach_rate", "discount_campaign_share"],
            "cost_mode": "existing_assets_only", "status": "ready_after_existing_assortment_review"
        },
        {
            "id": "EXP-017", "phase": "postpurchase", "priority": 17,
            "name": "검증 리뷰 언어·크롤 QA",
            "insight_ids": ["MKT-034", "MKT-035"],
            "owner_teams": ["market", "listing", "legal"],
            "action": "검증 구매 리뷰가 쌓인 뒤 고객 언어를 제품 사실과 대조해 PDP·피드에 반영하고 리뷰 구조화 데이터와 서버 렌더링 노출을 검사한다.",
            "kpis": ["review_language_coverage", "review_markup_valid_rate", "server_rendered_review_rate", "claims_rejection_rate"],
            "cost_mode": "free_local_or_existing_stack", "status": "blocked_until_verified_reviews"
        },
        {
            "id": "EXP-018", "phase": "retention", "priority": 18,
            "name": "이메일 행동·주문 진단 원장",
            "insight_ids": ["MKT-041", "MKT-042", "MKT-043"],
            "owner_teams": ["market", "listing", "design", "pricing", "knowledge", "legal"],
            "action": "동의 기반 캠페인을 클릭·주문·수신자당 매출로 정렬하고 이메일 문제와 랜딩·오퍼 문제를 분리하며 비할인 승자 요인을 재사용 가능한 원장으로 만든다.",
            "kpis": ["revenue_per_recipient", "click_to_order_rate", "nonpromo_revenue_per_recipient", "campaign_learning_coverage"],
            "cost_mode": "existing_stack_only", "status": "blocked_until_store_and_consent"
        },
        {
            "id": "EXP-019", "phase": "measurement", "priority": 19,
            "name": "플랫폼 귀속-Shopify 실매출 대조",
            "insight_ids": ["MKT-044"],
            "owner_teams": ["market", "pricing", "knowledge"],
            "action": "승인된 광고 데이터가 존재할 때만 동일 기간의 Shopify 순매출·총 광고비·플랫폼 귀속 매출을 대조해 채널 보고와 실제 사업 성과의 차이를 기록한다.",
            "kpis": ["platform_revenue_gap", "marketing_efficiency_ratio", "contribution_margin_after_marketing"],
            "cost_mode": "free_local", "status": "blocked_until_approved_ad_data"
        },
        {
            "id": "EXP-020", "phase": "prelaunch", "priority": 20,
            "name": "실구매자-가치제안 크리에이티브 매트릭스",
            "insight_ids": ["MKT-045", "MKT-046"],
            "owner_teams": ["market", "design", "listing", "pricing", "legal"],
            "action": "개인정보를 집계한 실제 구매자 특성과 검증된 가치제안을 연결해 유기 콘텐츠용 메시지·장면 초안을 만들고 유료 배포는 명시 승인 전 차단한다.",
            "kpis": ["audience_message_match_rate", "value_prop_comprehension_rate", "organic_engagement_rate", "discount_dependency_rate"],
            "cost_mode": "free_organic", "status": "ready_for_draft"
        },
        {
            "id": "EXP-021", "phase": "prelaunch", "priority": 21,
            "name": "구매 질문 fan-out SEO·GEO 갭 감사",
            "insight_ids": ["MKT-047", "MKT-048"],
            "owner_teams": ["market", "listing", "knowledge", "legal"],
            "action": "대표 구매 질문을 속성·비교·사용 상황·인용 하위 질문으로 분해하고 상품·컬렉션·FAQ의 크롤·색인·내부 링크·제품 데이터 누락을 오류 큐로 보낸다.",
            "kpis": ["theme_question_coverage", "product_data_completeness", "internal_link_coverage", "retrieval_gap_count"],
            "cost_mode": "free_local", "status": "ready_after_store"
        },
        {
            "id": "EXP-022", "phase": "prelaunch", "priority": 22,
            "name": "PDP·카트 의사결정 장벽 감사",
            "insight_ids": ["MKT-049", "MKT-050", "MKT-051"],
            "owner_teams": ["market", "listing", "design", "pricing", "legal"],
            "action": "상위 상품의 명확성·신뢰·가치·비교·마찰·확신 장벽을 하나씩 분류하고 해당 지점에만 검증 증거·정책·비교·관련상품을 배치한 초안을 만든다.",
            "kpis": ["diagnosed_decision_point_rate", "proof_proximity_coverage", "cart_to_checkout_rate", "cross_sell_attach_rate"],
            "cost_mode": "free_local", "status": "ready_for_draft"
        },
        {
            "id": "EXP-023", "phase": "measurement", "priority": 23,
            "name": "모바일 성능 코호트·체크아웃 신뢰 감사",
            "insight_ids": ["MKT-052", "MKT-053"],
            "owner_teams": ["market", "listing", "design", "knowledge", "legal"],
            "action": "기기·브라우저·네트워크 코호트별 모바일 이탈을 비교하고 체크아웃에서 배송·반품·신뢰 정보를 찾으러 되돌아가는 구간을 우선 수정한다.",
            "kpis": ["mobile_cohort_conversion_gap", "journey_error_rate", "checkout_exit_to_storefront_rate", "mobile_checkout_completion_rate"],
            "cost_mode": "free_local", "status": "blocked_until_store_analytics"
        },
        {
            "id": "EXP-024", "phase": "retention", "priority": 24,
            "name": "리텐션 플로우 제외·중복 제거 감사",
            "insight_ids": ["MKT-054", "MKT-055", "MKT-056"],
            "owner_teams": ["market", "knowledge", "legal"],
            "action": "핵심 라이프사이클 플로우의 스킵·제외 규칙과 이메일·SMS 중복을 감사하고 분기별 kill list로 목적 없는 자동화를 승인·백업 후 제거한다.",
            "kpis": ["eligible_contact_skip_rate", "unexplained_exclusion_count", "cross_channel_overlap_rate", "stale_automation_count"],
            "cost_mode": "existing_stack_only", "status": "blocked_until_store_and_consent"
        },
        {
            "id": "EXP-025", "phase": "prelaunch", "priority": 25,
            "name": "고객 선택형 번들·사은품 손익 모델",
            "insight_ids": ["MKT-057", "MKT-058"],
            "owner_teams": ["pricing", "sourcing", "market", "listing", "design", "legal"],
            "action": "고정·믹스앤매치 번들을 고객 선택 필요도로 나누고 사은품 임계값별 원가·배송·반품을 계산해 기여이익이 남는 조합만 초안에 둔다.",
            "kpis": ["bundle_completion_rate", "bundle_margin", "gift_threshold_attach_rate", "contribution_margin_per_order"],
            "cost_mode": "free_local", "status": "ready_for_modeling"
        },
        {
            "id": "EXP-026", "phase": "prelaunch", "priority": 26,
            "name": "톤·감정·가치 포지셔닝 지도",
            "insight_ids": ["MKT-059"],
            "owner_teams": ["market", "design", "listing", "pricing"],
            "action": "현재 브랜드와 경쟁 대안을 톤·감정·가치 축에 표시하고 목표 위치를 정한 뒤 PDP·이메일·유기 콘텐츠의 보이스 편차를 점검한다.",
            "kpis": ["positioning_consistency_rate", "competitor_overlap_score", "value_signal_comprehension", "channel_voice_deviation"],
            "cost_mode": "free_local", "status": "ready_for_research"
        },
        {
            "id": "EXP-027", "phase": "prelaunch", "priority": 27,
            "name": "Search Console 컬렉션 기회 큐",
            "insight_ids": ["MKT-060", "MKT-061"],
            "owner_teams": ["market", "listing", "design", "knowledge", "legal"],
            "action": "비브랜드 쿼리를 랜딩페이지와 의도 클러스터로 연결하고 이미 노출되는 컬렉션부터 비교·선택 기준·FAQ·내부 링크 초안을 보강한다.",
            "kpis": ["query_page_mapping_coverage", "collection_nonbrand_clicks", "internal_link_coverage", "collection_to_pdp_rate"],
            "cost_mode": "free_local", "status": "blocked_until_search_console_data"
        },
        {
            "id": "EXP-028", "phase": "launch", "priority": 28,
            "name": "시각 예시형 유기 크리에이터 브리프",
            "insight_ids": ["MKT-062"],
            "owner_teams": ["market", "design", "listing", "legal"],
            "action": "검증된 제품 사실·목표 고객·금지 클레임·참고 장면을 한 브리프에 묶어 기존 보유자산으로 유기 초안을 만들며 유료 제작·배포는 명시 승인 전 실행하지 않는다.",
            "kpis": ["brief_requirement_coverage", "creator_revision_rate", "organic_asset_acceptance_rate", "creative_angle_coverage"],
            "cost_mode": "free_organic", "status": "ready_after_assets"
        },
        {
            "id": "EXP-029", "phase": "prelaunch", "priority": 29,
            "name": "프로모션 깊이·기간 기여이익 게이트",
            "insight_ids": ["MKT-063"],
            "owner_teams": ["pricing", "market", "knowledge"],
            "action": "프로모션별 할인율·기간·매출·총이익·기여이익·운영비를 한 표에서 비교하고 이익이 악화되는 연장·심화 시나리오는 승인 큐에서 차단한다.",
            "kpis": ["promotion_contribution_margin", "gross_margin_rate", "discount_duration_days", "profit_after_promotion"],
            "cost_mode": "free_local", "status": "ready_for_modeling"
        },
        {
            "id": "EXP-030", "phase": "research", "priority": 30,
            "name": "반복 불만·가격 거부선 포지셔닝 검증",
            "insight_ids": ["MKT-064"],
            "owner_teams": ["market", "sourcing", "pricing", "listing", "knowledge"],
            "action": "경쟁 상품·브랜드 리뷰에서 반복 불만을 묶고 실제 가격과 가격 거부 표현을 연결해 비용 집행 전 해결 문제·가치제안·가격 가설을 승인한다.",
            "kpis": ["repeated_complaint_cluster_count", "cross_brand_complaint_rate", "price_resistance_evidence_count", "validated_problem_hypothesis_count"],
            "cost_mode": "free_local", "status": "ready_for_research"
        },
        {
            "id": "EXP-031", "phase": "launch", "priority": 31,
            "name": "문제 훅 다각도 유기 크리에이티브",
            "insight_ids": ["MKT-065"],
            "owner_teams": ["market", "design", "listing", "legal"],
            "action": "반복 고객 문제 하나를 문제 시연·전후 비교·실사용 검증의 서로 다른 각도로 제작해 보유 자산에서 유기 반응을 비교하며 유료 제작·배포는 명시 승인 전 차단한다.",
            "kpis": ["organic_hook_hold_rate", "creative_angle_coverage", "organic_link_ctr", "claim_violation_count"],
            "cost_mode": "free_organic", "status": "ready_after_assets"
        },
        {
            "id": "EXP-032", "phase": "retention", "priority": 32,
            "name": "고객 상태·사용주기 이메일 QA",
            "insight_ids": ["MKT-066", "MKT-067"],
            "owner_teams": ["market", "listing", "legal", "knowledge"],
            "action": "가입·이탈·구매·비활성 상태별 진입·종료·제외 규칙을 작성하고 SKU 사용주기에 맞춘 리뷰 요청과 부정 리뷰 서비스 회복 큐를 연결한다.",
            "kpis": ["lifecycle_state_coverage", "flow_overlap_rate", "review_request_timing_accuracy", "service_recovery_resolution_rate"],
            "cost_mode": "existing_stack_only", "status": "blocked_until_store_and_consent"
        },
        {
            "id": "EXP-033", "phase": "measurement", "priority": 33,
            "name": "기기·결제 코호트 세션가치 CRO",
            "insight_ids": ["MKT-068", "MKT-069", "MKT-073"],
            "owner_teams": ["market", "listing", "design", "pricing", "knowledge"],
            "action": "기기별 행동 혼란과 결제수단·구매유형 차이를 한 가설씩 테스트하고 자사 기준선 대비 전환율·AOV·세션당 매출·기여이익을 함께 판정한다.",
            "kpis": ["mobile_desktop_conversion_gap", "payment_method_aov", "revenue_per_session", "contribution_margin_per_session"],
            "cost_mode": "free_local", "status": "blocked_until_store_analytics"
        },
        {
            "id": "EXP-034", "phase": "prelaunch", "priority": 34,
            "name": "AI 상품 데이터·추천 가시성 운영",
            "insight_ids": ["MKT-070", "MKT-071"],
            "owner_teams": ["market", "listing", "knowledge", "legal"],
            "action": "상품 속성·변형·가격·재고의 누락과 충돌을 차단하고 핵심 구매질문의 AI 노출 브랜드·인용·추천 이유를 반복 기록해 정보 공백을 개선 큐로 보낸다.",
            "kpis": ["catalog_attribute_completeness", "cross_channel_attribute_consistency", "ai_question_visibility_rate", "citation_source_coverage"],
            "cost_mode": "free_local", "status": "blocked_until_verified_channel_support"
        },
        {
            "id": "EXP-035", "phase": "prelaunch", "priority": 35,
            "name": "CRO 단위경제 선행 게이트",
            "insight_ids": ["MKT-072", "MKT-073"],
            "owner_teams": ["pricing", "sourcing", "market", "knowledge"],
            "action": "가격·원가·배송·재고·결제비·운영비가 성립하지 않는 경로는 CRO 백로그에서 분리하고 손익이 성립하는 경로만 자사 기준선·AOV·마진과 함께 테스트 승인한다.",
            "kpis": ["unit_economics_pass_rate", "structural_loss_scenario_count", "cro_eligible_path_count", "contribution_margin_per_order"],
            "cost_mode": "free_local", "status": "ready_for_modeling"
        }
    ]


def validate_strategy_references(payload: dict) -> None:
    insights = payload.get("evidence_insights") or []
    known = {str(x.get("id") or "") for x in insights}
    errors = []

    experiments = payload.get("execution_experiments") or []
    experiment_ids = [str(x.get("id") or "") for x in experiments]
    if len(experiment_ids) != len(set(experiment_ids)) or any(not x for x in experiment_ids):
        errors.append("experiment id 누락 또는 중복")
    for experiment in experiments:
        exp_id = str(experiment.get("id") or "")
        unknown = sorted(set(experiment.get("insight_ids") or []) - known)
        if unknown:
            errors.append(f"{exp_id} 알 수 없는 insight: {', '.join(unknown)}")
        if experiment.get("cost_mode") == "paid_requires_explicit_approval" and \
                experiment.get("status") != "blocked_until_explicit_user_approval":
            errors.append(f"{exp_id} 유료 실행 차단 상태 누락")

    funnel_seen = set()
    for stage, ids in (payload.get("funnel") or {}).items():
        unknown = sorted(set(ids or []) - known)
        if unknown:
            errors.append(f"funnel {stage} 알 수 없는 insight: {', '.join(unknown)}")
        repeated = sorted(set(ids or []) & funnel_seen)
        if repeated:
            errors.append(f"funnel 중복 insight: {', '.join(repeated)}")
        funnel_seen.update(ids or [])

    for row in payload.get("product_playbooks") or []:
        unknown = sorted(set(row.get("recommended_insight_ids") or []) - known)
        if unknown:
            errors.append(f"product_playbook 알 수 없는 insight: {', '.join(unknown)}")

    launch_order = payload.get("launch_order") or []
    if launch_order != experiment_ids:
        errors.append("launch_order와 experiment 순서 불일치")
    if errors:
        raise RuntimeError("전략 참조 검증 실패: " + " | ".join(errors))


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
            "discover": ["MKT-005", "MKT-016", "MKT-020", "MKT-023", "MKT-027", "MKT-032", "MKT-036", "MKT-040", "MKT-047", "MKT-048", "MKT-060", "MKT-061", "MKT-062"],
            "consider": ["MKT-001", "MKT-002", "MKT-003", "MKT-004", "MKT-017", "MKT-025", "MKT-026", "MKT-034", "MKT-035", "MKT-038", "MKT-045", "MKT-046", "MKT-049", "MKT-051", "MKT-052", "MKT-053", "MKT-059"],
            "convert": ["MKT-008", "MKT-012", "MKT-013", "MKT-014", "MKT-015", "MKT-021", "MKT-022", "MKT-037", "MKT-050", "MKT-057", "MKT-058", "MKT-063"],
            "retain": ["MKT-006", "MKT-009", "MKT-010", "MKT-011", "MKT-028", "MKT-029", "MKT-030", "MKT-031", "MKT-039", "MKT-041", "MKT-042", "MKT-043", "MKT-054", "MKT-055", "MKT-056"],
            "measure": ["MKT-007", "MKT-024", "MKT-033", "MKT-044"],
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
    validate_strategy_references(payload)
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
