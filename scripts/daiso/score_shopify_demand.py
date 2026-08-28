#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
다이소 수집 상품을 Shopify 수요 기준으로 재평가하고
data/daiso_real/shopify_demand_score.json 을 생성한다.

점수 구성
---------
1) 카테고리 기본점 (스킨케어 95 …)
2) 고정 트렌드 키워드 보너스 (세럼/앰플/SPF 등)
3) **글로벌 7대 채널 트렌드 매칭 보너스**
   - dashboard_runtime.json 의 global_channels
   - Amazon / TikTok / Walmart / Google Trends / Ulta / Sephora / Shopify 추천
4) 평점·리뷰 가점 / 비핵심 상품 감점

사용:
  python scripts/daiso/score_shopify_demand.py
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
DASHBOARD = ROOT / "data" / "dashboard_runtime.json"

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
    "쿠션": 8,
    "프라이머": 7,
    "블러쉬": 6,
    "선케어": 10,
}

# 글로벌 채널 상품명에서 뽑을 때 쓸 토큰 최소 길이
TOKEN_MIN = 3

# 채널별 매칭 보너스 가중치
CHANNEL_WEIGHT = {
    "amazon_best_sellers": 12,
    "tiktok_shop_us": 14,
    "walmart_beauty": 10,
    "google_trends_us": 11,
    "ulta_beauty": 10,
    "sephora": 12,
    "shopify_recommended": 13,
}

# 소모품/도구류 — 점수 하향
NON_CORE_KEYWORDS = (
    "면봉", "스틱", "거울", "키링", "바지", "양말", "파자마",
    "걸이", "스탠드", "손톱깎이", "면도기", "칫솔", "치약",
    "테이프", "쌍꺼풀", "샤프너", "리필용기", "팬티", "속옷",
)

# 글로벌 트렌드 토큰에서 제외할 잡음
STOP_TOKENS = {
    "the", "and", "for", "with", "from", "best", "seller", "trending",
    "hot", "new", "just", "dropped", "shop", "us", "beauty", "skin",
    "care", "makeup", "product", "original", "daily", "liquid", "mask",
    "cream", "lotion", "serum", "oil", "set", "kit", "pro", "ml", "oz",
}


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def tokenize(text: str) -> set[str]:
    if not text:
        return set()
    # 영문/숫자/한글 토큰
    parts = re.findall(r"[A-Za-z0-9]+|[가-힣]{2,}", text.lower())
    out = set()
    for p in parts:
        if len(p) < TOKEN_MIN:
            continue
        if p in STOP_TOKENS:
            continue
        out.add(p)
    return out


def build_global_trend_index(global_channels: dict) -> dict:
    """
    global_channels → {
      token: { "score": int, "channels": [..], "examples": [..] }
    }
    """
    index: dict[str, dict] = {}
    if not isinstance(global_channels, dict):
        return index

    for channel, items in global_channels.items():
        weight = CHANNEL_WEIGHT.get(channel, 8)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            texts = []
            for key in ("product", "keyword", "title", "name", "brand", "hashtag", "niche", "category"):
                val = item.get(key)
                if val:
                    texts.append(str(val))
            blob = " ".join(texts)
            tokens = tokenize(blob)
            example = item.get("product") or item.get("keyword") or item.get("title") or blob[:40]
            for tok in tokens:
                entry = index.setdefault(tok, {"score": 0, "channels": set(), "examples": []})
                entry["score"] += weight
                entry["channels"].add(channel)
                if example and example not in entry["examples"] and len(entry["examples"]) < 3:
                    entry["examples"].append(example)

    # set → list for JSON later
    for tok, entry in index.items():
        entry["channels"] = sorted(entry["channels"])
        # 토큰당 보너스 상한
        entry["score"] = min(entry["score"], 28)
    return index


def global_match_bonus(name: str, trend_index: dict) -> tuple[int, list]:
    """상품명과 글로벌 트렌드 토큰 교집합 보너스"""
    if not trend_index:
        return 0, []
    name_tokens = tokenize(name)
    hits = []
    total = 0
    for tok in name_tokens:
        if tok in trend_index:
            info = trend_index[tok]
            pts = info["score"]
            total += pts
            hits.append({
                "token": tok,
                "bonus": pts,
                "channels": info["channels"],
                "examples": info.get("examples", []),
            })
    # 글로벌 매칭 총 보너스 상한
    total = min(total, 35)
    hits.sort(key=lambda x: -x["bonus"])
    return total, hits[:8]


def score_product(p: dict, trend_index: dict) -> dict:
    name_raw = p.get("name") or ""
    name = name_raw.lower()
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
            penalty = 50  # 비핵심은 강하게 하향
            break

    # 비핵심 상품에는 글로벌 트렌드 보너스 미적용
    if penalty:
        global_bonus, global_hits = 0, []
    else:
        global_bonus, global_hits = global_match_bonus(name_raw, trend_index)

    rating = float(p.get("rating") or 0)
    reviews = int(p.get("review_count") or 0)
    social = 0
    if rating >= 4.5:
        social += 5
    if reviews >= 100:
        social += 5
    if reviews >= 300:
        social += 3

    total = max(5, min(100, base + kw_bonus + global_bonus + social - penalty))

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
        "global_trend_hits": global_hits,
        "global_trend_bonus": global_bonus,
        "base_score": base,
        "keyword_bonus": kw_bonus,
        "social_bonus": social,
        "penalty": penalty,
    }


def main():
    if not PRODUCTS.exists():
        print(f"ERROR: {PRODUCTS} not found")
        return 1

    data = load_json(PRODUCTS, {}) or {}
    products = data.get("products", [])
    if not products:
        print("No products to score")
        return 1

    dashboard = load_json(DASHBOARD, {}) or {}
    global_channels = dashboard.get("global_channels") or {}
    trend_index = build_global_trend_index(global_channels)

    scored = [score_product(p, trend_index) for p in products]
    scored.sort(key=lambda x: (-x["shopify_score"], -x["review_count"]))

    by_grade = {"S": 0, "A": 0, "B": 0, "C": 0}
    for s in scored:
        by_grade[s["grade"]] += 1

    cat_scores: dict[str, list] = defaultdict(list)
    for s in scored:
        cat_scores[s["bucket"]].append(s["shopify_score"])
    cat_avg = {
        k: round(sum(v) / len(v), 1)
        for k, v in sorted(cat_scores.items(), key=lambda x: -sum(x[1]) / len(x[1]))
    }

    with_global = sum(1 for s in scored if s.get("global_trend_bonus", 0) > 0)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_products": len(scored),
        "grade_summary": by_grade,
        "category_avg_score": cat_avg,
        "global_channels_used": sorted(global_channels.keys()) if global_channels else [],
        "global_trend_tokens": len(trend_index),
        "products_with_global_match": with_global,
        "priority_note": (
            "Shopify 수요 + 글로벌 7대 채널 트렌드 매칭으로 재평가. "
            "S/A 등급을 우선 판매 후보로 사용하세요."
        ),
        "scoring_model": {
            "base": "category priority",
            "keyword_bonus": "fixed beauty trend keywords (cap 30)",
            "global_bonus": "match vs global_channels tokens (cap 35)",
            "social": "rating/reviews",
            "penalty": "non-core product keywords",
            "channel_weights": CHANNEL_WEIGHT,
        },
        "top_recommendations": scored[:15],
        "all_scored": scored,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Done. {len(scored)} products scored → {OUT}")
    print("Grade summary:", by_grade)
    print(f"Global trend tokens: {len(trend_index)} | products matched: {with_global}")
    print("\nTop 8 recommendations:")
    for i, s in enumerate(scored[:8], 1):
        g = s.get("global_trend_bonus", 0)
        print(
            f"  {i}. [{s['grade']}] {s['shopify_score']:3d}점 "
            f"(global+{g}) | {s['bucket']:8s} | {s['name'][:40]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
