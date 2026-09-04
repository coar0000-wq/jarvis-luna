#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""마케팅 조사 분석팀 보드를 만든다.

무엇인가
  글로벌 수요 시그널 + 다이소 S등급 + 원가 모델을 묶어
  "다음에 무엇을 등록하고 무엇으로 광고할지"를 한 장에 정리한다.
  쇼핑몰 스크래핑 팀이 아니라 경영 의사결정용 요약이다.

입력 (전부 실수집 산출물)
  data/daiso_real/shopify_s_recommendations.json   S등급 (다이소 실크롤링)
  data/daiso_real/shopify_demand_score.json        전체 점수 · 평점 · 리뷰수
  data/pricing_model.json                          착지원가 · 손익분기 · 권장가
  data/shopify_listing_copy.json                   Gemini 영문 카피 · 태그
  data/oliveyoung_us_products.json                 미국 베스트셀러 실수집 (403 시 0건)
  data/open_beauty_facts.json                      오픈데이터 상품 정보
  data/dashboard_runtime.json                      채널 상태 · Sephora/Ulta 대체 경쟁군

출력 data/market_team.json

원칙 (CLAUDE.md: 거짓말 데이터 금지 / 가짜 데이터 금지)
  - 근거가 없는 필드는 채우지 않고 비운 채 사유를 적는다.
    특히 키워드의 검색 추세(trend)는 Google Trends 가 없으면 null 로 둔다.
    "up" 같은 값을 지어내지 않는다.
  - 각 항목에 source 를 달아 어디서 온 값인지 추적 가능하게 한다.
  - 이전 버전은 "competitor_analysis: 완료" 같은 의미 없는 문자열이었다.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data"
OUT = D / "market_team.json"
KST = timezone(timedelta(hours=9))

# 다이소 bucket 은 대부분 "스킨케어" 로 뭉뚱그려져 있어 변별력이 없다.
# 실제 상품명의 제형 단어로 시드를 잡는다.
FORM_SEED = {
    "선크림": "korean sunscreen",
    "무기자차": "mineral sunscreen",
    "앰플": "korean ampoule",
    "세럼": "korean serum",
    "에센스": "korean essence",
    "토너": "korean toner",
    "크림": "korean face cream",
    "로션": "korean lotion",
    "마스크": "korean sheet mask",
    "클렌징": "korean cleanser",
    "쿠션": "korean cushion foundation",
}
# 성분·소구점은 미국 검색어에서 그대로 쓰인다
INGREDIENT_SEED = {
    "어성초": "heartleaf",
    "병풀": "centella",
    "콜라겐": "collagen",
    "PDRN": "pdrn",
    "히알루론": "hyaluronic acid",
    "판테놀": "panthenol",
    "비타민": "vitamin c",
    "달팽이": "snail mucin",
    "세라마이드": "ceramide",
}


def load(p: Path, default=None):
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


# "korean face cream" 이 "MEDIHEAL Face Mask" 에 걸리면 안 된다.
# 아래 단어는 변별력이 없어 매칭에서 제외한다.
GENERIC = {"korean", "korea", "face", "skin", "beauty", "care", "the", "and",
           "for", "with", "type", "types", "set", "pack", "new", "best"}


def norm(s: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(w) > 2}


def keytokens(s: str) -> set[str]:
    return norm(s) - GENERIC


def build_s_priority(srec, detail, pricing, copies):
    """S등급 우선순위. 점수·가격·광고 키워드를 한 줄에 묶는다."""
    price5 = {str(r["pd_no"]): r for r in
              (pricing.get("scenarios") or {}).get("5개_묶음배송", [])}
    copy_by = {str(c["pd_no"]): c for c in (copies.get("items") or []) if c.get("copy")}
    market = pricing.get("market_benchmark") or {}
    sell = market.get("p25")

    rows = []
    for i, p in enumerate(srec.get("recommendations") or [], 1):
        pid = str(p.get("pd_no"))
        d = detail.get(pid) or {}
        pr = price5.get(pid)
        c = copy_by.get(pid)

        margin = None
        if pr and sell:
            net = sell - pr["landed_cost_usd"] - (sell * 0.029 + 0.06)
            margin = round(net / sell * 100, 1)

        rows.append({
            "rank": i,
            "pd_no": p.get("pd_no"),
            "name": p.get("name"),
            "name_en": (c or {}).get("copy", {}).get("title") if c else None,
            "bucket": p.get("bucket"),
            "score": p.get("shopify_score"),
            "rating": d.get("rating"),
            "review_count": d.get("review_count"),
            "cost_krw": p.get("price_krw"),
            "landed_cost_usd": pr["landed_cost_usd"] if pr else None,
            "breakeven_usd": pr["breakeven_usd"] if pr else None,
            "suggested_price_usd": sell,
            "margin_pct": margin,
            "shopify_action": ("1차 등록" if i <= 5 else "2차 검토"),
            "ad_keywords": ((c or {}).get("copy", {}).get("tags") or [])[:6] if c else [],
            "ad_keywords_source": ("Gemini 영문 카피 태그" if c else "카피 미생성"),
            "listing_ready": bool(c),
            "url": p.get("url"),
        })
    return rows


def build_keyword_board(s_rows, oy_products):
    """S등급 상품명에서 시드 키워드를 뽑고 미국 베스트셀러와 대조한다.

    검색량과 추세는 채우지 않는다. Google Trends 공식 API 가 승인제 alpha 라
    아직 연동이 안 됐고, "up" 같은 값을 지어내면 그건 가짜 데이터다.
    """
    seeds = {}
    for r in s_rows:
        name = r.get("name") or ""
        tags = [t.replace("-", " ") for t in (r.get("ad_keywords") or [])]
        for ko, en in {**FORM_SEED, **INGREDIENT_SEED}.items():
            if ko not in name:
                continue
            e = seeds.setdefault(en, {
                "seed": en, "matched_products": [], "from_terms": set(),
                "gemini_tags": set(),
            })
            e["matched_products"].append(r["name"])
            e["from_terms"].add(ko)
            for t in tags:
                if any(w in t for w in en.split()):
                    e["gemini_tags"].add(t)

    board = []
    for en, e in sorted(seeds.items(), key=lambda x: -len(x[1]["matched_products"])):
        sw = keytokens(en)
        examples = []
        if sw:
            for o in oy_products:
                # 시드의 변별 토큰이 전부 상품명에 있어야 인정한다
                if not sw <= norm(o.get("product", "")):
                    continue
                examples.append({
                    "product": o["product"], "brand": o.get("brand"),
                    "price_usd": o.get("price_usd"), "us_rank": o.get("rank")})
                if len(examples) >= 3:
                    break
        board.append({
            "seed": en,
            "s_product_count": len(e["matched_products"]),
            "from_terms": sorted(e["from_terms"]),
            "intent": "commercial",
            "intent_basis": "제형·성분 기반 구매 의도 키워드",
            "trend": None,
            "search_volume": None,
            "trend_unavailable_reason": (
                "Google Trends 공식 API 가 승인제 alpha 라 미연동. "
                "검색 추세를 추정하지 않는다."),
            "us_market_examples": examples,
            "us_example_count": len(examples),
            "gemini_tags": sorted(e["gemini_tags"])[:5],
            "linked_s_products": e["matched_products"][:5],
            "source": "다이소 S등급 상품명 + OliveYoung US 실수집 대조",
        })
    return board


def _normalize_us_item(item: dict, default_source: str) -> dict | None:
    """채널 아이템을 경쟁군 공통 스키마로 맞춘다."""
    if not isinstance(item, dict):
        return None
    name = (item.get("product") or item.get("title") or item.get("name") or "").strip()
    if len(name) < 3:
        return None
    price = item.get("price_usd")
    if price is None:
        price = item.get("price")
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None
    return {
        "product": name,
        "brand": item.get("brand") or item.get("sub") or "",
        "price_usd": price,
        "rating": item.get("rating"),
        "review_count": item.get("review_count"),
        "rank": item.get("rank"),
        "url": item.get("url") or item.get("product_url") or "",
        "source": item.get("source") or default_source,
    }


def collect_competitor_pool(oy_products, runtime) -> list[dict]:
    """경쟁군 후보 풀.

    우선순위:
      1) OliveYoung US 실수집 (있으면)
      2) dashboard global_channels 의 Sephora / Ulta / Amazon / Walmart
         (OY 가 Cloudflare 403 으로 비어도 대체 가능)
    """
    pool: list[dict] = []
    seen: set[str] = set()

    def add(items, src_label):
        for it in items or []:
            n = _normalize_us_item(it, src_label)
            if not n:
                continue
            key = n["product"].lower()
            if key in seen:
                continue
            seen.add(key)
            pool.append(n)

    add(oy_products, "us.oliveyoung.com/best-sellers 실수집")

    gc = (runtime or {}).get("global_channels") or {}
    # OY 채널 키가 런타임에 남아 있으면 같이 흡수
    add(gc.get("oliveyoung_us") or [], "oliveyoung_us (runtime)")
    add(gc.get("sephora") or [], "sephora 실수집/스냅샷")
    add(gc.get("ulta_beauty") or [], "ulta_beauty 실수집/스냅샷")
    add(gc.get("amazon_best_sellers") or [], "amazon_best_sellers")
    add(gc.get("walmart_beauty") or [], "walmart_beauty")
    return pool


def build_competitors(s_rows, us_pool):
    """미국 실판매(또는 스냅샷) 중 S등급과 같은 포지션인 상품을 경쟁군으로 잡는다.

    OliveYoung US 가 403 으로 비어도 Sephora/Ulta 등으로 채운다.
    """
    buckets = {r["bucket"] for r in s_rows if r.get("bucket")}
    # 바디케어 힌트 추가 (바디샴푸 등)
    hints = {
        "선케어": ("sun", "spf", "uv", "sunscreen"),
        "스킨케어": ("cream", "serum", "toner", "essence", "ampoule", "moistur",
                   "lotion", "collagen", "pdrn", "snail", "heartleaf"),
        "마스크팩": ("mask",),
        "클렌징": ("cleans", "foam", "wash"),
        "메이크업": ("cushion", "tint", "lip", "foundation"),
        "헤어케어": ("shampoo", "treatment", "hair"),
        "바디케어": ("body", "wash", "lotion", "shower"),
    }
    out = []
    for b in buckets:
        keys = hints.get(b)
        if not keys:
            continue
        for o in us_pool:
            low = (o.get("product") or "").lower()
            if not any(k in low for k in keys):
                continue
            # 가격 없어도 이름·포지션은 표시 (스냅샷에 가격 없는 경우)
            rank = o.get("rank")
            src = o.get("source") or "US channel"
            why = f"{src}"
            if rank:
                why += f" {rank}위"
            why += f" · {b} 동일 포지션"
            out.append({
                "name": o["product"],
                "brand": o.get("brand"),
                "price_usd": o.get("price_usd"),
                "rating": o.get("rating"),
                "review_count": o.get("review_count"),
                "us_rank": rank,
                "daiso_bucket": b,
                "why": why,
                "url": o.get("url") or "",
                "source": src,
            })
            if len([x for x in out if x["daiso_bucket"] == b]) >= 3:
                break
    return out


def build_actions(s_rows, status, pricing):
    """상태에서 실제로 도출되는 것만 액션으로 적는다."""
    acts = []
    unlisted = [r for r in s_rows if not r["listing_ready"]]
    ready = [r for r in s_rows if r["listing_ready"]]
    if ready:
        acts.append(f"영문 카피가 준비된 {len(ready)}건 중 상위 5건을 Shopify 초안으로 등록")
    if unlisted:
        acts.append(f"카피 미생성 {len(unlisted)}건에 대해 "
                    "shopify-listing-copy 워크플로 재실행")
    dead = [k for k, m in (status or {}).items()
            if m.get("count", 0) == 0 and m.get("status") != "disabled"]
    if dead:
        acts.append(f"수집 실패 채널 {len(dead)}개 점검: {', '.join(dead)}")
    if "oliveyoung_us" in (dead or []) or any(
            k == "oliveyoung_us" for k in (status or {})):
        oy_meta = (status or {}).get("oliveyoung_us") or {}
        if oy_meta.get("count", 0) == 0:
            acts.append(
                "OliveYoung US 는 Actions 에서 HTTP 403(Cloudflare). "
                "주 1회 로컬/브라우저 수집 또는 Sephora·Ulta 대체 경쟁군 사용")
    mkt = pricing.get("market_benchmark") or {}
    if mkt.get("n"):
        acts.append(f"시장 가격대 {mkt['n']}건 기준 중앙값 ${mkt.get('median')} 주 1회 확인")
    acts.append("묶음 구매 유도용 무료배송 최소 주문금액 설정 "
                "(낱개 배송 시 적자 구조라 필수)")
    return acts


def main() -> int:
    srec = load(D / "daiso_real" / "shopify_s_recommendations.json", {}) or {}
    score = load(D / "daiso_real" / "shopify_demand_score.json", {}) or {}
    pricing = load(D / "pricing_model.json", {}) or {}
    copies = load(D / "shopify_listing_copy.json", {}) or {}
    oy = load(D / "oliveyoung_us_products.json", {}) or {}
    obf = load(D / "open_beauty_facts.json", {}) or {}
    runtime = load(D / "dashboard_runtime.json", {}) or {}

    detail = {str(x["pd_no"]): x for x in (score.get("all_scored") or [])}
    oy_products = oy.get("products") or []
    status = runtime.get("global_channels_status") or {}
    us_pool = collect_competitor_pool(oy_products, runtime)

    s_rows = build_s_priority(srec, detail, pricing, copies)
    now = datetime.now(KST)

    live = [k for k, m in status.items() if m.get("count", 0) > 0]
    # 구버전 런타임은 데이터가 있는 채널의 trust 가 null 이다.
    # 그때는 신뢰 집계를 못 하므로 미판정으로 둔다.
    graded = [k for k in live if status[k].get("trust")]
    has_trust = bool(graded)
    verified = [k for k, m in status.items() if m.get("trust") == "verified"]

    oy_fail = (oy.get("count") == 0) or bool(oy.get("reason"))
    competitor_watch = build_competitors(s_rows, us_pool)

    payload = {
        "team": {
            "name": "마케팅 조사 분석팀",
            "scope": "US K-Beauty 수요 · 다이소→Shopify 우선순위",
            "status": "active" if s_rows else "waiting_data",
            "purpose": "경영 의사결정용 요약. 무엇을 등록하고 무엇으로 광고할지 정한다.",
            "updated_at": now.isoformat(),
            "generator": "scripts/build_market_team.py",
        },
        "target_market": {
            "primary": "United States",
            "segment": "Budget K-Beauty / Daiso-style",
            "channels": ["Shopify", "TikTok ads", "Google Shopping"],
            "price_band_usd": pricing.get("market_benchmark") or {},
            "price_band_source": (pricing.get("market_benchmark") or {}).get("source", ""),
        },
        "demand_signals": {
            "oliveyoung_us_top": [
                {"rank": p.get("rank"), "product": p.get("product"),
                 "brand": p.get("brand"), "price_usd": p.get("price_usd"),
                 "rating": p.get("rating"), "review_count": p.get("review_count")}
                for p in oy_products[:15]
            ],
            "open_beauty_facts_top": [
                {"product": p.get("product_name"), "brand": p.get("brands"),
                 "category": p.get("category"), "code": p.get("code")}
                for p in (obf.get("products") or [])[:15]
            ],
            "alt_us_channels_top": [
                {"product": p.get("product"), "brand": p.get("brand"),
                 "price_usd": p.get("price_usd"), "source": p.get("source")}
                for p in us_pool[:20]
            ],
            "manual_trends": [],
            "note": (
                "실수집 가능한 소스만 반영한다. "
                "OliveYoung US 가 Actions 403 이면 Sephora/Ulta 등으로 경쟁군을 채운다. "
                "OY 는 주 1회 로컬·브라우저 수집을 권장한다."
            ),
            "sources": {
                "oliveyoung_us": oy.get("reason") or oy.get("source", "미수집"),
                "open_beauty_facts": obf.get("source", "미수집"),
                "competitor_pool_size": len(us_pool),
                "competitor_fallback": (
                    "sephora+ulta+amazon+walmart" if oy_fail else "oliveyoung_us primary"
                ),
            },
        },
        "keyword_board": build_keyword_board(s_rows, oy_products),
        "s_grade_priority": s_rows,
        "competitor_watch": competitor_watch,
        "weekly_actions": build_actions(s_rows, status, pricing),
        "health": {
            "signals_live": len(live),
            "signals_total": len(status),
            "signals_verified": len(verified),
            "trust_graded": has_trust,
            "trust_note": ("" if has_trust else
                           "런타임 스냅샷이 구버전이라 신뢰 등급 미판정. "
                           "다음 Deep Analysis 실행 후 채워진다."),
            "live_channels": live,
            "s_count": len(s_rows),
            "listing_ready_count": sum(1 for r in s_rows if r["listing_ready"]),
            "last_score_run": (score.get("generated_at") or "")[:10],
            "last_pricing_run": (pricing.get("generated_at") or "")[:10],
            "exchange_rate": (pricing.get("exchange_rate") or {}).get("usd_to_krw"),
        },
        "data_integrity_note": (
            "모든 수치는 실수집 산출물에서 계산했다. "
            "근거가 없는 필드(키워드 추세·검색량)는 채우지 않고 사유를 적었다."),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    h = payload["health"]
    print(f"market_team.json 생성 -> {OUT.relative_to(ROOT)}")
    print(f"  S등급 {h['s_count']}건 (카피 준비 {h['listing_ready_count']}건)")
    print(f"  실데이터 채널 {h['signals_live']}/{h['signals_total']} (검증 {h['signals_verified']})")
    print(f"  키워드 {len(payload['keyword_board'])}개 · 경쟁군 {len(payload['competitor_watch'])}건")
    print(f"  주간 액션 {len(payload['weekly_actions'])}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
