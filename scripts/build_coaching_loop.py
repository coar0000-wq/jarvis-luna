#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S등급 Shopify 등록 전 코칭 루프.

역할 (Coaching)
  - 등록 전 체크리스트: 마진·카피·글로벌 매칭·가격대·Reddit 키워드 등 실데이터
  - 광고 카피 A/B: 키워드·후킹 각도만 다른 두 안 (사람은 고르고 수정)
  - 최종 등록/광고 실행은 사람 승인

입력
  data/daiso_real/shopify_s_recommendations.json
  data/daiso_real/shopify_demand_score.json
  data/pricing_model.json
  data/shopify_listing_copy.json
  data/market_team.json
  data/reddit_beauty_signals.json   (선택 — 있으면 커뮤니티 키워드 매칭)

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
    ("PDRN", "PDRN"), ("달팽이", "snail mucin"), ("히알루론", "hyaluronic"),
]

KO_EN_BRIDGE = {
    "선크림": ["sunscreen", "spf"],
    "무기자차": ["mineral", "spf", "sunscreen"],
    "토너": ["toner"],
    "세럼": ["serum"],
    "앰플": ["ampoule", "ampule"],
    "에센스": ["essence"],
    "크림": ["cream", "moisturizer"],
    "마스크": ["mask", "sheet"],
    "클렌징": ["cleanser", "cleansing"],
    "쿠션": ["cushion"],
    "콜라겐": ["collagen"],
    "어성초": ["heartleaf"],
    "병풀": ["centella", "cica"],
    "달팽이": ["snail", "mucin"],
    "히알루론": ["hyaluronic"],
    "PDRN": ["pdrn"],
    "선쿠션": ["sunscreen", "cushion", "spf"],
    "바디샴푸": ["body", "wash", "shower"],
    "바디워시": ["body", "wash"],
}


def load(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_reddit_keywords():
    raw = load(D / "reddit_beauty_signals.json", {}) or {}
    keys = []
    for row in (raw.get("beauty_keywords") or []) + (raw.get("hot_keywords") or []):
        if isinstance(row, dict) and row.get("keyword"):
            keys.append(str(row["keyword"]).lower())
        elif isinstance(row, str):
            keys.append(row.lower())
    seen = set()
    uniq = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    meta = {
        "status": raw.get("status"),
        "post_count": raw.get("post_count") or 0,
        "collected_at": raw.get("collected_at"),
        "keyword_pool": len(uniq),
    }
    return uniq, meta


def product_search_terms(name: str, bucket: str) -> set:
    terms = set()
    for ko, ens in KO_EN_BRIDGE.items():
        if ko in name or ko.lower() in name.lower():
            terms.update(ens)
    for ko, en in FORM_EN:
        if ko in name:
            terms.add(en.lower().replace(" ", ""))
            for part in en.lower().split():
                terms.add(part)
    for h in BUCKET_HOOKS.get(bucket, ()):
        for part in h.lower().replace("-", " ").split():
            if len(part) >= 3:
                terms.add(part)
    for w in re.findall(r"[a-zA-Z]{3,}", name.lower()):
        terms.add(w)
    return terms


def match_reddit(name: str, bucket: str, reddit_keys: list) -> dict:
    if not reddit_keys:
        return {
            "matched": [],
            "score": 0,
            "status": "warn",
            "evidence": "Reddit 시그널 없음 (수집 전 또는 실패)",
            "tip": "Deep Analysis에서 collect_reddit_beauty_rss 실행",
        }
    terms = product_search_terms(name, bucket)
    matched = sorted({rk for rk in reddit_keys if rk in terms or any(rk in t or t in rk for t in terms)})
    extra = []
    for rk in reddit_keys[:40]:
        for t in terms:
            if len(rk) >= 4 and (rk in t or t in rk):
                extra.append(rk)
    matched = sorted(set(matched) | set(extra))[:8]
    if len(matched) >= 2:
        st = "pass"
        tip = "커뮤니티에서 회자되는 키워드와 겹침 — 광고 키워드로 우선 사용"
    elif len(matched) == 1:
        st = "pass"
        tip = "약한 매칭 1개 — 광고 문안에 해당 키워드 포함 권장"
    else:
        st = "warn"
        tip = "Reddit 핫 키워드와 직접 겹침 약함 — 성분 영문명으로 재검색"
    return {
        "matched": matched,
        "score": len(matched),
        "status": st,
        "evidence": (
            f"matched={matched}" if matched else f"terms={sorted(terms)[:8]} vs pool={len(reddit_keys)}"
        ),
        "tip": tip,
    }


def en_title_guess(name_ko: str, bucket: str) -> str:
    bits = []
    for ko, en in FORM_EN:
        if ko.lower() in name_ko.lower() or ko in name_ko:
            if en not in bits:
                bits.append(en)
    if not bits:
        bits = [BUCKET_HOOKS.get(bucket, ("K-beauty product",))[0]]
    return " ".join(bits[:3]).title() + " — Daiso Find"


def checklist_for(row, detail, copy_item, pricing_row, band, reddit_keys):
    items = []
    score = row.get("shopify_score") or row.get("score") or 0
    grade = row.get("grade") or "S"
    margin = row.get("margin_pct")
    if margin is None and pricing_row:
        margin = pricing_row.get("margin_pct")
    suggested = row.get("suggested_price_usd")
    if suggested is None and pricing_row:
        suggested = pricing_row.get("suggested_price_usd")
    listing_ready = bool(row.get("listing_ready"))
    has_copy = bool(copy_item and (copy_item.get("copy") or {}).get("title"))
    reason = row.get("recommend_reason") or (detail or {}).get("recommend_reason") or ""
    has_global = "글로벌" in reason or bool(
        (detail or {}).get("best_global_match") or (detail or {}).get("matched_global")
    )
    name = row.get("name") or ""
    bucket = row.get("bucket") or ""

    def add(key, label, status, evidence, tip):
        items.append({
            "id": key,
            "label": label,
            "status": status,
            "evidence": evidence,
            "tip": tip,
        })

    add("grade_s", "S등급 유지", "pass" if grade == "S" else "fail",
        f"grade={grade}, score={score}", "S가 아니면 1차 등록 보류")
    if margin is not None:
        st = "pass" if margin >= 50 else ("warn" if margin >= 35 else "fail")
        add("margin", "마진 50%+", st, f"margin_pct={margin}", "착지·배송 반영 후 재계산")
    else:
        add("margin", "마진 확인", "warn", "pricing 미연결", "pricing_model 재실행")

    if suggested is not None:
        med = (band or {}).get("median")
        if med:
            st = "pass" if 0.35 * med <= float(suggested) <= 1.3 * med else "warn"
            add("price_band", "시장 가격대 정합", st,
                f"suggested=${suggested} · market median=${med}",
                "경쟁 대비 너무 싸면 저가 인식, 너무 비싸면 전환 저하")
        else:
            add("price_band", "권장가 존재", "pass", f"suggested=${suggested}", "시장 벤치마크 추가 시 재검증")
    else:
        add("price_band", "권장가", "warn", "suggested_price 없음", "pricing_model 확인")

    add("listing_copy", "영문 리스팅 카피", "pass" if has_copy else "fail",
        "Gemini 카피 있음" if has_copy else "카피 미생성", "shopify-listing-copy 워크플로 실행")
    add("listing_ready_flag", "등록 준비 플래그", "pass" if listing_ready else "warn",
        f"listing_ready={listing_ready}", "카피·이미지 준비되면 true")
    add("global_signal", "글로벌 수요 시그널", "pass" if has_global else "warn",
        reason[:120] if reason else "매칭 약함", "약한 단일 토큰 매칭이면 광고 키워드를 성분 중심으로")
    reviews = row.get("review_count") or (detail or {}).get("review_count") or 0
    add("social_proof", "국내 리뷰(대리지표)",
        "pass" if reviews >= 100 else ("warn" if reviews >= 20 else "fail"),
        f"review_count={reviews}", "리뷰 적으면 첫 광고 예산을 더 보수적으로")

    rm = match_reddit(name, bucket, reddit_keys)
    add("reddit_community", "Reddit 뷰티 커뮤니티 키워드", rm["status"], rm["evidence"], rm["tip"])
    return items


def ab_copy(row, copy_item, competitors, reddit_matched):
    name = row.get("name") or ""
    bucket = row.get("bucket") or "스킨케어"
    hooks = BUCKET_HOOKS.get(bucket, ("K-beauty", "daily care", "value"))
    base_title = None
    base_body = None
    if copy_item and copy_item.get("copy"):
        c = copy_item["copy"]
        base_title = c.get("title")
        raw = c.get("description_html") or c.get("description") or ""
        base_body = re.sub(r"<[^>]+>", " ", raw)
        base_body = re.sub(r"\s+", " ", base_body).strip()[:220]

    title_a = base_title or en_title_guess(name, bucket)
    if reddit_matched:
        angle_a = f"{reddit_matched[0]} · {hooks[0]}"
    else:
        angle_a = f"{hooks[0]} · {hooks[1] if len(hooks) > 1 else 'K-beauty'}"
    primary_a = f"{title_a} — {angle_a}"
    body_a = base_body or (
        f"Daiso-sourced {hooks[0]}. Lightweight daily use. "
        f"Target US shoppers searching {hooks[1] if len(hooks) > 1 else 'K-beauty'}."
    )

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
        f"Try this Daiso find before paying premium. Hook: {angle_b}."
        + (f" Nearby US ref: {comp_name[:40]}." if comp_name else "")
    )

    keywords = []
    for ko, en in FORM_EN:
        if ko in name or ko.lower() in name.lower():
            keywords.append(en)
    for h in hooks:
        if h not in keywords:
            keywords.append(h)
    for rk in reddit_matched[:5]:
        if rk not in keywords:
            keywords.append(rk)
    keywords = keywords[:10]

    return {
        "variant_a": {
            "label": "A · 성분/커뮤니티 후킹",
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
        "reddit_keywords_used": reddit_matched[:5],
        "test_plan": "각 안 3~5일 · CTR·ATC 비교 후 승자 유지. 예산은 소액부터.",
        "human_gate": "광고 계정에 올리기 전 문구·랜딩 링크 사람 확인 필수",
    }


def readiness(checks):
    fails = sum(1 for c in checks if c["status"] == "fail")
    warns = sum(1 for c in checks if c["status"] == "warn")
    if fails == 0 and warns <= 1:
        return "ready_to_list"
    if fails == 0:
        return "ready_with_notes"
    if fails <= 1:
        return "fix_then_list"
    return "hold"


def build():
    srec = load(D / "daiso_real" / "shopify_s_recommendations.json", {}) or {}
    score = load(D / "daiso_real" / "shopify_demand_score.json", {}) or {}
    pricing = load(D / "pricing_model.json", {}) or {}
    copies = load(D / "shopify_listing_copy.json", {}) or {}
    market = load(D / "market_team.json", {}) or {}
    reddit_keys, reddit_meta = load_reddit_keywords()

    detail = {str(x.get("pd_no")): x for x in (score.get("all_scored") or [])}
    price_map = {}
    for x in (pricing.get("products") or pricing.get("items") or []):
        if isinstance(x, dict) and x.get("pd_no") is not None:
            price_map[str(x["pd_no"])] = x
    copy_map = {}
    for it in (copies.get("items") or []):
        if it.get("pd_no") is not None:
            copy_map[str(it["pd_no"])] = it

    competitors = market.get("competitor_watch") or []
    band = (market.get("target_market") or {}).get("price_band_usd") or pricing.get("market_benchmark") or {}

    rows = srec.get("recommendations") or market.get("s_grade_priority") or []
    rows = rows[:15]

    sessions = []
    for r in rows:
        pd = str(r.get("pd_no") or "")
        det = detail.get(pd) or {}
        merged = {**det, **r}
        checks = checklist_for(merged, det, copy_map.get(pd), price_map.get(pd), band, reddit_keys)
        rm = match_reddit(merged.get("name") or "", merged.get("bucket") or "", reddit_keys)
        ab = ab_copy(merged, copy_map.get(pd), competitors, rm.get("matched") or [])
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
            "reddit_match": rm,
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
        "reddit_signal": reddit_meta,
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
            "3) Reddit 매칭 키워드를 광고 키워드에 포함",
            "4) ad_copy_ab A/B 중 하나 골라 3~5일 CTR 비교",
            "5) 자동 발송·자동 광고 ON 하지 말 것",
        ],
    }


def main() -> int:
    payload = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = payload["summary"]
    print(f"coaching_loop.json → {OUT.relative_to(ROOT)}")
    print(f"  sessions {len(payload['sessions'])} · ready {s['ready_to_list']} · notes {s['ready_with_notes']} · fix {s['fix_then_list']} · hold {s['hold']}")
    print(f"  reddit pool={s.get('reddit_signal', {}).get('keyword_pool')} status={s.get('reddit_signal', {}).get('status')}")
    for sess in payload["sessions"][:5]:
        cs = sess["coach_summary"]
        rm = sess.get("reddit_match") or {}
        print(f"  [{sess['readiness']}] {sess['name'][:32]} · reddit={rm.get('matched')} → {cs['next_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
