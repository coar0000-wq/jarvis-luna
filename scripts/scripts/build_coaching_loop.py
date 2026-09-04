#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S등급 Shopify 등록 전 코칭 루프.

역할 (영상 4C 중 Coaching)
  - 등록 전 체크리스트: 마진·카피·글로벌 매칭·가격대 등 실데이터로 pass/fail
  - 광고 카피 A/B: 키워드·후킹 각도만 다른 두 안 (사람은 고르고 수정)
  - 최종 등록/광고 실행은 사람 승인 (자동 발송·자동 등록 없음)

입력
  data/daiso_real/shopify_s_recommendations.json
  data/daiso_real/shopify_demand_score.json
  data/pricing_model.json
  data/shopify_listing_copy.json
  data/market_team.json  (경쟁군·가격밴드, 있으면)

출력
  data/coaching_loop.json
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data"
OUT = D / "coaching_loop.json"
KST = timezone(timedelta(hours=9))

# 버킷 → 영문 후킹 키워드 (광고 A/B용, 실상품명에서 파생 가능한 범위만)
BUCKET_HOOKS = {
    "선케어": ("SPF50+", "mineral sunscreen", "daily UV"),
    "스킨케어": ("K-beauty", "glass skin", "hydrating"),
    "마스크팩": ("sheet mask", "overnight mask", "collagen mask"),
    "클렌징": ("gentle cleanser", "double cleanse", "pH balanced"),
    "메이크업": ("cushion", "natural finish", "buildable"),
    "헤어케어": ("damage care", "silky hair", "treatment"),
    "바디케어": ("body wash", "moisturizing", "shower"),
}

FORM_EN = [
    ("선크림", "sunscreen"), ("선쿠션", "sun cushion"), ("무기자차", "mineral SPF"),
    ("토너", "toner"), ("세럼", "serum"), ("앰플", "ampoule"), ("에센스", "essence"),
    ("크림", "cream"), ("마스크", "mask"), ("클렌징", "cleanser"), ("쿠션", "cushion"),
    ("바디샴푸", "body wash"), ("바디워시", "body wash"), ("샴푸", "shampoo"),
    ("콜라겐", "collagen"), ("어성초", "heartleaf"), ("병풀", "centella"),
    ("PDRN", "PDRN"), ("달팽이", "snail mucin"),
]


def load(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def en_title_guess(name_ko: str, bucket: str) -> str:
    """Gemini 카피가 없을 때 쓸 짧은 영문 추정 (과장 없이 제형 중심)."""
    bits = []
    for ko, en in FORM_EN:
        if ko.lower() in name_ko.lower() or ko in name_ko:
            if en not in bits:
                bits.append(en)
    if not bits:
        bits = [BUCKET_HOOKS.get(bucket, ("K-beauty product",))[0]]
    return " ".join(bits[:3]).title() + " — Daiso Find"


def checklist_for(row: dict, detail: dict, copy_item: dict | None, pricing_row: dict | None, band: dict) -> list[dict]:
    """실수치로 pass/warn/fail. 지어내지 않는다."""
    items = []
    score = row.get("shopify_score") or row.get("score") or 0
    grade = row.get("grade") or "S"
    margin = row.get("margin_pct")
    if margin is None and pricing_row:
        margin = pricing_row.get("margin_pct")
    suggested = row.get("suggested_price_usd")
    if suggested is None and pricing_row:
        suggested = pricing_row.get("suggested_price_usd")
    landed = row.get("landed_cost_usd")
    if landed is None and pricing_row:
        landed = pricing_row.get("landed_cost_usd")
    listing_ready = bool(row.get("listing_ready"))
    has_copy = bool(copy_item and (copy_item.get("copy") or {}).get("title"))
    reason = row.get("recommend_reason") or (detail or {}).get("recommend_reason") or ""
    has_global = "글로벌" in reason or bool((detail or {}).get("best_global_match") or (detail or {}).get("matched_global"))

    def add(key, label, status, evidence, tip):
        items.append({
            "id": key,
            "label": label,
            "status": status,  # pass | warn | fail
            "evidence": evidence,
            "tip": tip,
        })

    add(
        "grade_s",
        "S등급 유지",
        "pass" if grade == "S" else "fail",
        f"grade={grade}, score={score}",
        "S가 아니면 1차 등록 보류",
    )
    if margin is not None:
        st = "pass" if margin >= 50 else ("warn" if margin >= 35 else "fail")
        add("margin", "마진 50%+", st, f"margin_pct={margin}", "착지·배송 반영 후 재계산")
    else:
        add("margin", "마진 확인", "warn", "pricing 미연결", "pricing_model 재실행")

    if suggested is not None:
        med = (band or {}).get("median")
        if med:
            # 시장 중앙값의 0.4~1.2배면 pass
            st = "pass" if 0.35 * med <= float(suggested) <= 1.3 * med else "warn"
            add(
                "price_band",
                "시장 가격대 정합",
                st,
                f"suggested=${suggested} · market median=${med}",
                "경쟁 대비 너무 싸면 저가 인식, 너무 비싸면 전환 저하",
            )
        else:
            add("price_band", "권장가 존재", "pass", f"suggested=${suggested}", "시장 벤치마크 추가 시 재검증")
    else:
        add("price_band", "권장가", "warn", "suggested_price 없음", "pricing_model 확인")

    add(
        "listing_copy",
        "영문 리스팅 카피",
        "pass" if has_copy else "fail",
        "Gemini 카피 있음" if has_copy else "카피 미생성",
        "shopify-listing-copy 워크플로 실행",
    )
    add(
        "listing_ready_flag",
        "등록 준비 플래그",
        "pass" if listing_ready else "warn",
        f"listing_ready={listing_ready}",
        "카피·이미지 준비되면 true",
    )
    add(
        "global_signal",
        "글로벌 수요 시그널",
        "pass" if has_global else "warn",
        reason[:120] if reason else "매칭 약함",
        "약한 단일 토큰 매칭이면 광고 키워드를 성분 중심으로",
    )
    reviews = row.get("review_count") or (detail or {}).get("review_count") or 0
    add(
        "social_proof",
        "국내 리뷰(대리지표)",
        "pass" if reviews >= 100 else ("warn" if reviews >= 20 else "fail"),
        f"review_count={reviews}",
        "리뷰 적으면 첫 광고 예산을 더 보수적으로",
    )
    return items


def ab_copy(row: dict, copy_item: dict | None, competitors: list[dict]) -> dict:
    """A/B 광고 카피. 기존 Gemini title 이 있으면 A의 기반으로 쓰고, B는 각도만 변경."""
    name = row.get("name") or ""
    bucket = row.get("bucket") or "스킨케어"
    hooks = BUCKET_HOOKS.get(bucket, ("K-beauty", "daily care", "value"))
    base_title = None
    base_body = None
    if copy_item and copy_item.get("copy"):
        c = copy_item["copy"]
        base_title = c.get("title")
        # description 은 html 일 수 있음 → 태그 제거 일부
        raw = c.get("description_html") or c.get("description") or ""
        base_body = re.sub(r"<[^>]+>", " ", raw)
        base_body = re.sub(r"\s+", " ", base_body).strip()[:220]

    title_a = base_title or en_title_guess(name, bucket)
    # A: 혜택·성분 후킹
    angle_a = f"{hooks[0]} · {hooks[1] if len(hooks) > 1 else 'K-beauty'}"
    primary_a = f"{title_a} — {angle_a}"
    body_a = base_body or (
        f"Daiso-sourced {hooks[0]}. Lightweight daily use. "
        f"Target US shoppers searching {hooks[1] if len(hooks) > 1 else 'K-beauty'}."
    )

    # B: 가격·가성비 / 경쟁 대비
    comp_name = None
    comp_price = None
    for c in competitors:
        if c.get("daiso_bucket") == bucket and c.get("price_usd"):
            comp_name = c.get("name")
            comp_price = c.get("price_usd")
            break
    sug = row.get("suggested_price_usd")
    if sug and comp_price:
        angle_b = f"Same vibe, smarter price (from ${sug} vs market ~${comp_price})"
    elif sug:
        angle_b = f"Budget K-beauty from ${sug}"
    else:
        angle_b = f"Affordable {hooks[-1]} pick"
    primary_b = f"{en_title_guess(name, bucket)} — {angle_b}"
    body_b = (
        f"Try this Daiso find before paying premium. "
        f"Hook: {angle_b}."
        + (f" Nearby US ref: {comp_name[:40]}." if comp_name else "")
    )

    keywords = []
    for ko, en in FORM_EN:
        if ko in name or ko.lower() in name.lower():
            keywords.append(en)
    for h in hooks:
        if h not in keywords:
            keywords.append(h)
    keywords = keywords[:8]

    return {
        "variant_a": {
            "label": "A · 성분/효능 후킹",
            "primary_text": primary_a[:150],
            "headline": title_a[:40],
            "description": body_a[:200],
            "cta": "Shop now",
        },
        "variant_b": {
            "label": "B · 가성비/가격 후킹",
            "primary_text": primary_b[:150],
            "headline": (en_title_guess(name, bucket))[:40],
            "description": body_b[:200],
            "cta": "See price",
        },
        "suggested_keywords": keywords,
        "test_plan": "각 안 3~5일 · CTR·ATC 비교 후 승자 유지. 예산은 소액부터.",
        "human_gate": "광고 계정에 올리기 전 문구·랜딩 링크 사람 확인 필수",
    }


def readiness(checks: list[dict]) -> str:
    fails = sum(1 for c in checks if c["status"] == "fail")
    warns = sum(1 for c in checks if c["status"] == "warn")
    if fails == 0 and warns <= 1:
        return "ready_to_list"
    if fails == 0:
        return "ready_with_notes"
    if fails <= 1:
        return "fix_then_list"
    return "hold"


def build() -> dict:
    srec = load(D / "daiso_real" / "shopify_s_recommendations.json", {}) or {}
    score = load(D / "daiso_real" / "shopify_demand_score.json", {}) or {}
    pricing = load(D / "pricing_model.json", {}) or {}
    copies = load(D / "shopify_listing_copy.json", {}) or {}
    market = load(D / "market_team.json", {}) or {}

    detail = {str(x.get("pd_no")): x for x in (score.get("all_scored") or [])}
    price_map = {}
    for x in (pricing.get("products") or pricing.get("items") or []):
        if isinstance(x, dict) and x.get("pd_no") is not None:
            price_map[str(x["pd_no"])] = x
    # market_team s_grade_priority 에 원가 필드가 이미 있을 수 있음
    copy_map = {}
    for it in (copies.get("items") or []):
        if it.get("pd_no") is not None:
            copy_map[str(it["pd_no"])] = it

    competitors = market.get("competitor_watch") or []
    band = (market.get("target_market") or {}).get("price_band_usd") or pricing.get("market_benchmark") or {}

    rows = srec.get("recommendations") or market.get("s_grade_priority") or []
    # 상위 15개만 코칭 (실행 가능 단위)
    rows = rows[:15]

    sessions = []
    for r in rows:
        pd = str(r.get("pd_no") or "")
        det = detail.get(pd) or {}
        # market_team row 우선 필드 병합
        merged = {**det, **r}
        checks = checklist_for(merged, det, copy_map.get(pd), price_map.get(pd), band)
        ab = ab_copy(merged, copy_map.get(pd), competitors)
        status = readiness(checks)
        sessions.append({
            "pd_no": pd,
            "name": merged.get("name") or r.get("name"),
            "bucket": merged.get("bucket"),
            "shopify_score": merged.get("shopify_score") or merged.get("score"),
            "url": merged.get("url") or r.get("url"),
            "readiness": status,
            "checklist": checks,
            "ad_copy_ab": ab,
            "coach_summary": {
                "pass": sum(1 for c in checks if c["status"] == "pass"),
                "warn": sum(1 for c in checks if c["status"] == "warn"),
                "fail": sum(1 for c in checks if c["status"] == "fail"),
                "next_action": (
                    "Shopify 초안 등록" if status == "ready_to_list" else
                    "경고 항목 보완 후 등록" if status == "ready_with_notes" else
                    "실패 항목 수정" if status == "fix_then_list" else
                    "보류 — 카피·마진부터"
                ),
            },
        })

    summary = {
        "ready_to_list": sum(1 for s in sessions if s["readiness"] == "ready_to_list"),
        "ready_with_notes": sum(1 for s in sessions if s["readiness"] == "ready_with_notes"),
        "fix_then_list": sum(1 for s in sessions if s["readiness"] == "fix_then_list"),
        "hold": sum(1 for s in sessions if s["readiness"] == "hold"),
    }

    return {
        "generated_at": datetime.now(KST).isoformat(),
        "role": "coaching",
        "principle": "AI는 체크리스트·A/B 초안만. 등록·광고 집행은 사람 승인.",
        "source": "scripts/build_coaching_loop.py",
        "scope": "S등급 상위 15개",
        "summary": summary,
        "sessions": sessions,
        "how_to_use": [
            "1) readiness=ready_to_list 부터 Shopify 초안 등록",
            "2) checklist fail 항목을 먼저 해소 (카피 워크플로 등)",
            "3) ad_copy_ab A/B 중 하나 골라 광고 — 3~5일 후 CTR 비교",
            "4) 자동 발송·자동 광고 ON 하지 말 것",
        ],
    }


def main() -> int:
    payload = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = payload["summary"]
    print(f"coaching_loop.json → {OUT.relative_to(ROOT)}")
    print(f"  sessions {len(payload['sessions'])} · ready {s['ready_to_list']} · notes {s['ready_with_notes']} · fix {s['fix_then_list']} · hold {s['hold']}")
    for sess in payload["sessions"][:5]:
        cs = sess["coach_summary"]
        print(f"  [{sess['readiness']}] {sess['name'][:36]} · P{cs['pass']}/W{cs['warn']}/F{cs['fail']} → {cs['next_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
