#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shopify 1차 테스트 배치 (5~10 SKU) — 실데이터만, 가짜 금지.

입력: data/daiso_real/shopify_demand_score.json (또는 shopify_s_recommendations.json)
출력: data/daiso_real/shopify_test_batch.json

필터:
  - S등급
  - 핵심 카테고리(스킨케어/선케어/마스크/클렌징/토너)
  - 글로벌 매칭 강토큰(heartleaf, toner, sunscreen 등) 우선
  - 단일 weak 토큰(lotion/cream만) · 문구/베이비/핸드크림 제외
  - 토너·선케어 가산
  - 최대 10개, 선케어 최대 3개
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data" / "daiso_real"
SCORE = DATA / "shopify_demand_score.json"
SREC = DATA / "shopify_s_recommendations.json"
OUT = DATA / "shopify_test_batch.json"

CORE = {"스킨케어", "선케어", "마스크팩", "클렌징", "토너"}
STRONG = {
    "heartleaf", "snail", "centella", "ceramide", "niacinamide",
    "retinol", "peptide", "hyaluronic", "collagen", "pdrn",
    "sunscreen", "spf", "toner", "serum", "ampoule", "essence",
    "calming", "cica", "vitamin", "mucin",
}
WEAK_ONLY = {"lotion", "cream", "cleanser", "mask", "oil", "mist"}
NOISE = re.compile(
    r"볼펜|문구|샌드크림|베이비|baby|핸드크림|hand\s*cream|티슈|tissue",
    re.I,
)


def load_rows():
    if SCORE.exists():
        sc = json.loads(SCORE.read_text(encoding="utf-8"))
        rows = [x for x in (sc.get("all_scored") or []) if x.get("grade") == "S"]
        if rows:
            return rows
    if SREC.exists():
        return json.loads(SREC.read_text(encoding="utf-8")).get("recommendations") or []
    return []


def score_row(r: dict) -> dict | None:
    m = r.get("best_global_match") or r.get("matched_global") or {}
    if isinstance(m, str):
        m = {}
    toks = {t.lower() for t in (m.get("matched_tokens") or [])}
    strong_n = len(toks & STRONG)
    weak_only = bool(toks) and toks <= WEAK_ONLY
    name = r.get("name") or ""
    bucket = r.get("bucket") or ""
    if "토너" in name or "toner" in name.lower():
        bucket = "토너"
    rating = float(r.get("rating") or 0)
    reviews = int(r.get("review_count") or 0)
    sim = float(m.get("similarity") or 0)
    base = float(r.get("shopify_score") or r.get("score") or 0)

    if NOISE.search(name):
        return None
    if bucket not in CORE and "토너" not in name:
        if bucket not in {"스킨케어", "선케어", "마스크팩", "클렌징"}:
            return None
    if weak_only and strong_n == 0:
        return None
    if strong_n == 0 and sim < 0.5:
        return None

    quality = base + strong_n * 8 + sim * 10 + min(10, reviews / 200) + (3 if rating >= 4.5 else 0)
    if "토너" in name or "toner" in name.lower():
        quality += 12
    if any(x in name for x in ("선크림", "선쿠션", "SPF", "무기자차")):
        quality += 10
    if any(x in name for x in ("어성초", "시카", "달팽이", "세럼", "앰플")):
        quality += 8

    return {
        "pd_no": r.get("pd_no"),
        "name": name,
        "bucket": bucket,
        "price_krw": r.get("price_krw") or r.get("cost_krw"),
        "rating": rating or None,
        "review_count": reviews or None,
        "url": r.get("url"),
        "image_url": r.get("image_url"),
        "shopify_score": r.get("shopify_score") or r.get("score"),
        "grade": "S",
        "match_tokens": sorted(toks),
        "global_channel": m.get("channel"),
        "global_product": m.get("global_product"),
        "similarity": sim,
        "quality_rank_score": round(quality, 2),
        "test_reason": f"강토큰 {strong_n} · sim {sim:.0%}",
    }


def main() -> int:
    rows = load_rows()
    if not rows:
        print("ERROR: no S-grade rows")
        return 1
    picked = [x for x in (score_row(r) for r in rows) if x]
    picked.sort(key=lambda x: -x["quality_rank_score"])
    batch, sun, seen = [], 0, set()
    for p in picked:
        if len(batch) >= 10:
            break
        if p["name"] in seen:
            continue
        is_sun = any(x in p["name"] for x in ("선크림", "선쿠션", "SPF", "무기자차"))
        if is_sun:
            if sun >= 3:
                continue
            sun += 1
        seen.add(p["name"])
        batch.append(p)
    for i, b in enumerate(batch, 1):
        b["test_rank"] = i
    out = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Shopify 1차 테스트 등록 후보 (5~10개)",
        "rule": "S · 강토큰 · 토너/선케어 우선 · weak 단일매칭 제외 · 실데이터만",
        "count": len(batch),
        "organic_note": "광고비 없음 가정 — 유기 트래픽·콘텐츠·Product Network",
        "items": batch,
    }
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"test batch {len(batch)} → {OUT}")
    for b in batch:
        print(f"  {b['test_rank']}. {b['name'][:40]} [{b['bucket']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
