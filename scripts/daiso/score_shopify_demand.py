#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
다이소 상품 × 글로벌 8채널 수요 유사도 점수.

- 8채널(영어) ↔ 다이소(한글) 한영 매핑 사전으로 매칭
- 카테고리 기본점 낮춤 + 보너스 상한으로 100점 쏠림 방지
- 산출: shopify_demand_score.json + shopify_s_recommendations.json
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "data" / "daiso_real" / "products.json"
OUT = ROOT / "data" / "daiso_real" / "shopify_demand_score.json"
OUT_S = ROOT / "data" / "daiso_real" / "shopify_s_recommendations.json"
DASHBOARD = ROOT / "data" / "dashboard_runtime.json"

# 카테고리 기본점 (낮게 — 변별력)
CATEGORY_BASE = {
    "스킨케어": 42,
    "선케어": 40,
    "마스크팩": 38,
    "클렌징": 34,
    "메이크업": 32,
    "헤어케어": 30,
    "맨즈케어": 28,
    "바디케어": 26,
    "향수": 22,
    "네일": 16,
    "뷰티소품": 14,
    "구강용품": 10,
}

CHANNEL_WEIGHT = {
    "tiktok_shop_us": 1.0,
    "oliveyoung_us": 0.98,
    "amazon_best_sellers": 0.95,
    "sephora": 0.9,
    "ulta_beauty": 0.85,
    "shopify_demand_matching": 0.88,
    "shopify_recommended": 0.85,
    "walmart_beauty": 0.8,
    "google_trends_us": 0.7,
}

# 한·영 → 공통 정규 토큰 (매칭 핵심)
# 값: canonical token (영문 소문자)
LEXICON: list[tuple[str, str]] = [
    # 성분/효능
    ("어성초", "heartleaf"),
    ("heartleaf", "heartleaf"),
    ("병풀", "centella"),
    ("센텔라", "centella"),
    ("centella", "centella"),
    ("cica", "centella"),
    ("달팽이", "snail"),
    ("뮤신", "snail"),
    ("snail", "snail"),
    ("mucin", "snail"),
    ("히알루론", "hyaluronic"),
    ("히알루로닉", "hyaluronic"),
    ("hyaluronic", "hyaluronic"),
    ("세라마이드", "ceramide"),
    ("ceramide", "ceramide"),
    ("나이아신", "niacinamide"),
    ("니아신", "niacinamide"),
    ("niacinamide", "niacinamide"),
    ("레티놀", "retinol"),
    ("retinol", "retinol"),
    ("펩타이드", "peptide"),
    ("peptide", "peptide"),
    ("콜라겐", "collagen"),
    ("collagen", "collagen"),
    ("비타민c", "vitaminc"),
    ("비타민 c", "vitaminc"),
    ("비타씨", "vitaminc"),
    ("vita c", "vitaminc"),
    ("vitamin c", "vitaminc"),
    ("pdrn", "pdrn"),
    ("티트리", "teatree"),
    ("tea tree", "teatree"),
    # 제형
    ("토너", "toner"),
    ("toner", "toner"),
    ("세럼", "serum"),
    ("serum", "serum"),
    ("앰플", "ampoule"),
    ("ampoule", "ampoule"),
    ("ampule", "ampoule"),
    ("에센스", "essence"),
    ("essence", "essence"),
    ("크림", "cream"),
    ("cream", "cream"),
    ("로션", "lotion"),
    ("lotion", "lotion"),
    ("모이스처", "moisturizer"),
    ("moisturizer", "moisturizer"),
    ("moisturizing", "moisturizer"),
    ("클렌징", "cleanser"),
    ("클렌저", "cleanser"),
    ("cleanser", "cleanser"),
    ("폼", "cleanser"),
    ("마스크", "mask"),
    ("mask", "mask"),
    ("팩", "mask"),
    ("선크림", "sunscreen"),
    ("선쿠션", "sunscreen"),
    ("sunscreen", "sunscreen"),
    ("spf", "sunscreen"),
    ("자외선", "sunscreen"),
    ("쿠션", "cushion"),
    ("cushion", "cushion"),
    ("프라이머", "primer"),
    ("primer", "primer"),
    ("블러쉬", "blush"),
    ("블러시", "blush"),
    ("blush", "blush"),
    ("립", "lip"),
    ("lip", "lip"),
    ("샴푸", "shampoo"),
    ("shampoo", "shampoo"),
    ("트리트먼트", "treatment"),
    ("treatment", "treatment"),
    # 효능 키워드
    ("수분", "hydrating"),
    ("보습", "hydrating"),
    ("hydrating", "hydrating"),
    ("hydration", "hydrating"),
    ("진정", "calming"),
    ("calming", "calming"),
    ("soothing", "calming"),
    ("미백", "brightening"),
    ("잡티", "brightening"),
    ("기미", "brightening"),
    ("brightening", "brightening"),
    ("모공", "pore"),
    ("pore", "pore"),
    ("탄력", "firming"),
    ("firming", "firming"),
    ("주름", "antiaging"),
    ("anti-aging", "antiaging"),
    ("repair", "repair"),
    ("리페어", "repair"),
    # 브랜드 (글로벌↔다이소 공통 등장 시)
    ("cosrx", "cosrx"),
    ("anua", "anua"),
    ("cerave", "cerave"),
    ("ordinary", "ordinary"),
    ("laneige", "laneige"),
    ("tirtir", "tirtir"),
    ("medicube", "medicube"),
]

# 사전을 긴 키 우선 매칭용으로 정렬
_LEX_SORTED = sorted(LEXICON, key=lambda x: -len(x[0]))

NON_CORE = (
    "면봉", "거울", "키링", "바지", "양말", "파자마", "걸이", "스탠드",
    "손톱깎이", "면도기", "칫솔", "치약", "테이프", "쌍꺼풀", "샤프너",
    "리필용기", "팬티", "속옷", "치실", "구두약", "저장 용기", "유리 저장",
    "기프트세트", "고체향수",
)

STOP = {"the", "and", "for", "with", "from", "best", "ml", "oz", "by", "new"}


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def to_canonical(text: str) -> set[str]:
    """한글/영문 상품명 → 공통 canonical 토큰 집합"""
    if not text:
        return set()
    t = text.lower()
    t = re.sub(r"\s+", " ", t)
    found: set[str] = set()
    for src, canon in _LEX_SORTED:
        if src in t:
            found.add(canon)
            # 중복 매칭 줄이기 위해 치환
            t = t.replace(src, " ")
    # 남은 영문 토큰
    for p in re.findall(r"[a-z]{4,}", t):
        if p not in STOP:
            found.add(p)
    return found


def extract_signals(global_channels: dict) -> list[dict]:
    signals = []
    if not isinstance(global_channels, dict):
        return signals
    for channel, items in global_channels.items():
        if not isinstance(items, list):
            continue
        w = CHANNEL_WEIGHT.get(channel, 0.6)
        for rank, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            name = str(
                item.get("product")
                or item.get("keyword")
                or item.get("title")
                or item.get("name")
                or ""
            ).strip()
            if len(name) < 3:
                continue
            brand = str(item.get("brand") or "")
            blob = f"{name} {brand} {item.get('category') or ''} {item.get('sub') or ''}"
            cans = to_canonical(blob)
            if not cans:
                continue
            rank_w = max(0.5, 1.0 - rank * 0.05)
            signals.append({
                "channel": channel,
                "product": name,
                "canonical": cans,
                "demand": round(w * rank_w, 3),
                "rank": rank + 1,
            })
    return signals


def best_matches(daiso_name: str, signals: list[dict], top_n: int = 3) -> list[dict]:
    d_can = to_canonical(daiso_name)
    if not d_can:
        return []
    hits = []
    for sig in signals:
        inter = d_can & sig["canonical"]
        if not inter:
            continue
        # 교집합 비율 (다이소 기준 + 시그널 기준 평균)
        j_d = len(inter) / len(d_can)
        j_s = len(inter) / max(1, len(sig["canonical"]))
        sim = 0.6 * j_d + 0.4 * j_s
        # 핵심 성분 가산
        key_ings = {"snail", "heartleaf", "centella", "ceramide", "niacinamide",
                    "retinol", "vitaminc", "sunscreen", "hyaluronic", "collagen", "peptide"}
        if inter & key_ings:
            sim = min(1.0, sim + 0.12 * len(inter & key_ings))
        if sim < 0.12:
            continue
        hits.append({
            "channel": sig["channel"],
            "global_product": sig["product"],
            "similarity": round(sim, 3),
            "demand_weight": sig["demand"],
            "matched_tokens": sorted(inter),
            "match_score": round(sim * sig["demand"], 3),
        })
    hits.sort(key=lambda x: -x["match_score"])
    return hits[:top_n]


def score_one(p: dict, signals: list[dict]) -> dict:
    name = p.get("name") or ""
    bucket = p.get("bucket") or ""
    base = CATEGORY_BASE.get(bucket, 12)
    non_core = any(k in name for k in NON_CORE)

    matches = [] if non_core else best_matches(name, signals)
    if matches:
        best = matches[0]["match_score"]
        second = matches[1]["match_score"] if len(matches) > 1 else 0
        # 유사도 파트 최대 40점
        sim_pts = min(40, int(best * 38 + second * 6))
    else:
        sim_pts = 0

    # 한글 트렌드 키워드 소폭 (최대 12)
    kw_pts = 0
    low = name.lower()
    for kw, pts in (("앰플", 6), ("세럼", 6), ("선크림", 5), ("spf", 5),
                    ("토너", 4), ("에센스", 4), ("마스크", 3), ("크림", 2)):
        if kw in low:
            kw_pts += pts
    kw_pts = min(12, kw_pts)

    rating = float(p.get("rating") or 0)
    reviews = int(p.get("review_count") or 0)
    quality = 0
    if rating >= 4.5:
        quality += 4
    elif rating >= 4.0:
        quality += 2
    if reviews >= 100:
        quality += 3
    if reviews >= 300:
        quality += 2

    penalty = 40 if non_core else 0
    total = max(5, min(100, base + sim_pts + kw_pts + quality - penalty))

    best_sim = matches[0]["similarity"] if matches else 0
    core = bucket in {"스킨케어", "선케어", "마스크팩", "클렌징", "메이크업", "헤어케어"}
    specific = {"snail", "heartleaf", "centella", "ceramide", "niacinamide",
                "retinol", "vitaminc", "sunscreen", "hyaluronic", "collagen",
                "peptide", "toner", "serum", "ampoule", "essence", "cleanser",
                "cushion", "primer", "blush"}
    matched_toks = set((matches[0].get("matched_tokens") or [])) if matches else set()
    has_specific = bool(matched_toks & specific)

    if not non_core and core and matches and best_sim >= 0.25 and total >= 70 and has_specific:
        grade = "S"
    elif not non_core and total >= 50 and best_sim >= 0.12 and has_specific:
        grade = "A"
    elif total >= 40:
        grade = "B"
    else:
        grade = "C"

    reason = (
        f"글로벌 '{matches[0]['global_product']}' ({matches[0]['channel']}) "
        f"유사 {matches[0]['similarity']:.0%} · 토큰 {','.join(matches[0]['matched_tokens'][:5])}"
        if matches else
        ("비핵심 상품" if non_core else "글로벌 시그널 약함")
    )

    return {
        "pd_no": p.get("pd_no"),
        "name": name,
        "bucket": bucket,
        "price_krw": p.get("price_krw"),
        "rating": rating,
        "review_count": reviews,
        "url": p.get("url"),
        "image_url": p.get("image_url"),
        "shopify_score": total,
        "grade": grade,
        "base_score": base,
        "similarity_points": sim_pts,
        "keyword_points": kw_pts,
        "quality_bonus": quality,
        "penalty": penalty,
        "best_global_match": matches[0] if matches else None,
        "global_matches": matches,
        "recommend_reason": reason,
    }


def main() -> int:
    data = load_json(PRODUCTS, {}) or {}
    products = data.get("products") or []
    if not products:
        print(f"ERROR: no products in {PRODUCTS}")
        return 1

    dashboard = load_json(DASHBOARD, {}) or {}
    signals = extract_signals(dashboard.get("global_channels") or {})
    scored = [score_one(p, signals) for p in products]
    scored.sort(key=lambda x: (
        -x["shopify_score"],
        -(x.get("best_global_match") or {}).get("similarity", 0),
        -x["review_count"],
    ))

    by_grade = {"S": 0, "A": 0, "B": 0, "C": 0}
    for s in scored:
        by_grade[s["grade"]] += 1

    cat_scores: dict[str, list] = defaultdict(list)
    for s in scored:
        cat_scores[s["bucket"] or "기타"].append(s["shopify_score"])
    cat_avg = {
        k: round(sum(v) / len(v), 1)
        for k, v in sorted(cat_scores.items(), key=lambda x: -sum(x[1]) / len(x[1]))
    }

    matched = sum(1 for s in scored if s.get("global_matches"))
    recs = sorted(
        scored,
        key=lambda x: (
            0 if x["grade"] == "S" else 1 if x["grade"] == "A" else 2,
            0 if x.get("global_matches") else 1,
            -x["shopify_score"],
        ),
    )

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_products": len(scored),
        "grade_summary": by_grade,
        "category_avg_score": cat_avg,
        "global_channels_used": sorted((dashboard.get("global_channels") or {}).keys()),
        "global_demand_signals": len(signals),
        "products_with_global_match": matched,
        "priority_note": "한영 매핑 기반 글로벌 8채널 유사도 점수. S/A를 Shopify 우선 후보로 사용.",
        "scoring_model": {
            "logic": "kr_en_lexicon_similarity",
            "formula": "category_base + sim(max40) + keyword(max12) + quality - non_core",
            "lexicon_size": len(LEXICON),
            "channel_weights": CHANNEL_WEIGHT,
        },
        "top_recommendations": recs[:15],
        "all_scored": scored,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    s_list = [x for x in recs if x["grade"] == "S"]
    s_payload = {
        "generated_at": result["generated_at"],
        "source": "score_shopify_demand.py",
        "rule": "grade == S (core category + global match)",
        "count": len(s_list),
        "priority_note": "S등급만. Shopify 우선 등록·테스트 후보.",
        "recommendations": [
            {
                "rank": i,
                "pd_no": x.get("pd_no"),
                "name": x.get("name"),
                "bucket": x.get("bucket"),
                "price_krw": x.get("price_krw"),
                "shopify_score": x.get("shopify_score"),
                "grade": x.get("grade"),
                "url": x.get("url"),
                "recommend_reason": x.get("recommend_reason"),
                "matched_global": x.get("best_global_match"),
            }
            for i, x in enumerate(s_list, 1)
        ],
    }
    OUT_S.write_text(json.dumps(s_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Done {len(scored)} → {OUT}")
    print("Grades:", by_grade, "| matched:", matched, "| signals:", len(signals))
    print(f"S-list {len(s_list)} → {OUT_S}")
    for i, s in enumerate(recs[:8], 1):
        m = s.get("best_global_match")
        extra = f"≈{m['global_product'][:28]} [{','.join(m['matched_tokens'][:3])}]" if m else "-"
        print(f"  {i}. [{s['grade']}] {s['shopify_score']:3d} {s['name'][:30]} | {extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
