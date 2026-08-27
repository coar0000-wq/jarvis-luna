#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
다이소 수집 상품을 Shopify 수요 기준으로 재평가하고
data/daiso_real/shopify_demand_score.json 을 생성한다.

사용:
  python scripts/daiso/score_shopify_demand.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "data" / "daiso_real" / "products.json"
OUT = ROOT / "data" / "daiso_real" / "shopify_demand_score.json"

# Shopify 수요 우선순위 (0~100)
SHOPIFY_DEMAND_PRIORITY = {
    "스킨케어": 95,
    "선케어": 90,
    "마스크팩": 85,
    "헤어케어": 80,
    "클렌징": 75,
    "맨즈케어": 70,
    "메이크업": 65,
    "바디케어": 60,
    "향수": 55,
    "네일": 40,
    "뷰티소품": 35,
    "구강용품": 30,
}

# 제품명 트렌드 키워드 보너스
TREND_KEYWORDS = {
    "세럼": 15,
    "앰플": 15,
    "히알루론": 12,
    "세라마이드": 12,
    "나이아신": 12,
    "펩타이드": 12,
    "spf": 14,
    "선크림": 14,
    "선쿠션": 12,
    "수분": 8,
    "보습": 8,
    "마스크": 7,
    "클렌징": 6,
    "레티놀": 10,
    "비타민c": 10,
    "비타씨": 10,
    "모공": 6,
    "잡티": 6,
    "미백": 5,
    "로션": 5,
    "크림": 5,
    "에센스": 10,
    "토너": 6,
    "필링": 5,
}

# 소모품/도구류 (실제 스킨케어 제품이 아님) — 점수 하향
NON_CORE_KEYWORDS = (
    "면봉", "스틱", "거울", "키링", "바지", "양말", "파자마",
    "걸이", "스탠드", "손톱깎이", "면도기", "칫솔", "치약",
    "테이프", "쌍꺼풀", "샤프너", "리필용기", "팬티", "속옷",
)


def score_product(p: dict) -> dict:
    name = (p.get("name") or "").lower()
    bucket = p.get("bucket") or ""
    base = SHOPIFY_DEMAND_PRIORITY.get(bucket, 20)

    kw_bonus = 0
    matched = []
    for kw, pts in TREND_KEYWORDS.items():
        if kw.lower() in name:
            kw_bonus += pts
            matched.append(kw)
    kw_bonus = min(kw_bonus, 30)

    penalty = 0
    for nk in NON_CORE_KEYWORDS:
        if nk in name:
            penalty = 35
            break

    rating = float(p.get("rating") or 0)
    reviews = int(p.get("review_count") or 0)
    social = 0
    if rating >= 4.5:
        social += 5
    if reviews >= 100:
        social += 5
    if reviews >= 300:
        social += 3

    total = max(5, min(100, base + kw_bonus + social - penalty))

    if total >= 85:
        grade = "S"
    elif total >= 70:
        grade = "A"
    elif total >= 55:
        grade = "B"
    else:
        grade = "C"

    return {
        "pd_no": p.get("pd_no"),
        "name": p.get("name"),
        "bucket": bucket,
        "price_krw": p.get("price_krw"),
        "rating": rating,
        "review_count": reviews,
        "url": p.get("url"),
        "image_url": p.get("image_url"),
        "shopify_score": total,
        "grade": grade,
        "matched_keywords": matched,
        "base_score": base,
        "keyword_bonus": kw_bonus,
        "penalty": penalty,
    }


def main():
    if not PRODUCTS.exists():
        print(f"ERROR: {PRODUCTS} not found")
        return 1

    data = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    products = data.get("products", [])
    if not products:
        print("No products to score")
        return 1

    scored = [score_product(p) for p in products]
    scored.sort(key=lambda x: (-x["shopify_score"], -x["review_count"]))

    by_grade = {"S": 0, "A": 0, "B": 0, "C": 0}
    for s in scored:
        by_grade[s["grade"]] += 1

    from collections import defaultdict
    cat_scores = defaultdict(list)
    for s in scored:
        cat_scores[s["bucket"]].append(s["shopify_score"])
    cat_avg = {
        k: round(sum(v) / len(v), 1)
        for k, v in sorted(cat_scores.items(), key=lambda x: -sum(x[1]) / len(x[1]))
    }

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_products": len(scored),
        "grade_summary": by_grade,
        "category_avg_score": cat_avg,
        "priority_note": "Shopify 수요 기준으로 재평가. S/A 등급을 우선 판매 후보로 사용하세요.",
        "top_recommendations": scored[:15],
        "all_scored": scored,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Done. {len(scored)} products scored → {OUT}")
    print("Grade summary:", by_grade)
    print("\nTop 8 recommendations:")
    for i, s in enumerate(scored[:8], 1):
        print(f"  {i}. [{s['grade']}] {s['shopify_score']:3d}점 | {s['bucket']:8s} | {s['name'][:42]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
