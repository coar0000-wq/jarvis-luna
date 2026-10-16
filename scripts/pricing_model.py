#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""한국→미국 실배송 기준 단가 모델.

기존 대시보드의 "원가 x 2.2" 는 배송비·관세·결제수수료가 하나도 없는
껍데기 계산이었다. 이 스크립트는 알려진 비용만 넣어 추정 손익을 계산한다.
미확인 추가 수수료와 제외 비용이 있어 전체 검증 순이익이 아니다.

비용 근거 (각 항목의 출처 참고)
  배송  우체국 국제통상 소형포장물 미국행 요금표
        ems.epost.go.kr/front.EmsDeliveryDelivery072.postal
  관세  미국 화장품 HTS 3304 한국산 상호관세 15%
        de minimis($800 면세)는 2025-08-29 전 국가 폐지,
        2026-06-24 CBP 무기한 유예로 소액 소포도 과세 대상
  환율  data/daiso_real/collection_status.json 의 실시간 조회값
  수수료 판매 후 카드사 2% + $0 (user instruction2026-10-11)
         Shopify/Managed Markets 추가 수수료는 UNKNOWN, 계산에 더하지 않는다.

무게는 다이소 수집 데이터에 없다. 상품명의 용량(ml/g)으로 추정하되
추정임을 명시한다. 실제 배송 전 반드시 저울로 재야 한다.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from payment_fees import (PAYMENT_FEE_RATE, PAYMENT_FEE_FIXED_USD, PAYMENT_FEE_NOTE,
                          payment_cost_basis, profit_flags)

ROOT = Path(__file__).resolve().parents[1]
STRATEGY_PATH = ROOT / "config" / "daiso_commerce_strategy.json"
SCORE = ROOT / "data" / "daiso_real" / "shopify_demand_score.json"
SREC = ROOT / "data" / "daiso_real" / "shopify_s_recommendations.json"
STATUS = ROOT / "data" / "daiso_real" / "collection_status.json"
OUT = ROOT / "data" / "pricing_model.json"

# 우체국 국제통상 소형포장물 · 미국행 (원). 실제 요금표 그대로.
SMALL_PACKET_US = [
    (100, 8410), (200, 9420), (300, 10430), (400, 11440), (500, 13490),
    (600, 14440), (700, 15390), (800, 16340), (900, 17290), (1000, 18230),
    (1100, 20130), (1200, 21430), (1300, 22730), (1400, 24030), (1500, 24910),
    (1600, 26210), (1700, 28110), (1800, 30010), (1900, 31910), (2000, 33810),
]
SHIPPING_SOURCE = ("우체국 국제통상 소형포장물 미국행 요금표 "
                   "(ems.epost.go.kr, 2026-08-31 조회)")

TARIFF_RATE = 0.15          # 미국 화장품 HTS 3304 한국산 상호관세

# 관세를 누가 언제 내는가 — 두 방식이 있고 둘을 동시에 하면 고객이 두 번 낸다.
#
#   ddu  판매가에 관세를 녹인다. 우리가 배송사에 선납하는 계약(DDP 배송)이
#        있어야 성립한다. 없으면 고객이 물건 받을 때 관세 고지서를 또 받는다.
#   ddp  Shopify 가 결제 화면에서 고객에게 관세를 따로 받는다.
#        판매가에는 관세를 넣지 않는다.
#
# Shopify Managed Markets 는 2026-08-24 부터 DDU 지원을 폐지하고
# DDP 로 자동 전환했다. 즉 스토어를 열면 ddp 가 기본이 될 가능성이 높다.
# 다만 한국 발송 셀러 지원 여부는 개설 후 Markets 설정에서 확인해야 한다.
# 그래서 두 경우를 모두 산출해 두고 확인 후 고른다.
DUTY_MODES = ("ddu", "ddp")

# 판매 구성 (2026-09-04 결정)
#   광고를 하지 않기로 해서 CAC 가 0 이다. 그래서 단품도 흑자가 된다.
#   다만 2개 주문은 추가 배송비가 $1.30 뿐인데 매출은 두 배가 되므로
#   세트를 미는 편이 훨씬 유리하다.
#
#   할인율 15% 를 고른 이유
#     - 5~10% 는 미국 소비자에게 체감이 안 된다
#     - (처음 정할 때 기록) 20% 면 마진 36.7%, 15% 면 마진 40%·순익 2.2배였다.
#       원가·시장가가 바뀌어 지금 값은 다르다. 화면 문구는 offers.판단_근거 에서 매번 계산한다.
#   무료배송은 2개 주문 배송비가 이미 원가에 포함돼 있어 추가 부담이 없다.
BUNDLE_SIZE = 2
BUNDLE_DISCOUNT = 0.15
FREE_SHIP_MIN_QTY = 2

# 실제로 파는 구성. 단품과 1+1 뿐이다.
# 예전에는 3개·5개까지 계산해두고 화면이 5개짜리를 대표값으로 읽었다.
# 팔지도 않는 구성의 마진을 보여주면 판단이 어긋난다.
SELL_QTYS = (1, BUNDLE_SIZE)


def psych_price(v: float) -> float:
    """미국식 가격 표기. 0.99 로 올림."""
    import math
    return math.floor(v) + 0.99 if v >= 1 else round(v, 2)
# Explicit user card-processor component only; supplemental fees remain UNKNOWN.
PAY_RATE, PAY_FIXED = PAYMENT_FEE_RATE, PAYMENT_FEE_FIXED_USD
PAY_NOTE = PAYMENT_FEE_NOTE
PACKAGING_G = 40            # 완충재 + 봉투 실측 대신 보수적 추정

OLIVEYOUNG = ROOT / "data" / "oliveyoung_us_products.json"


SERP_PATH = ROOT / "data" / "serpapi_market.json"


def load_serp_prices() -> dict:
    """SerpApi google_shopping 으로 받은 상품별 미국 실판매가.

    전에는 올리브영 베스트셀러 100건의 중앙값 하나를 전 상품에 똑같이 썼다.
    앰플과 시트마스크의 시장가가 같을 리 없어 마진 계산이 어긋났다.
    상품번호별 중앙값이 있으면 그것을 쓰고, 없으면 종전 벤치마크로 돌아간다.
    """
    try:
        d = json.loads(SERP_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    out = {}
    for it in ((d.get("prices") or {}).get("items") or []):
        m = it.get("median_usd")
        n = it.get("n") or 0
        # 표본이 너무 적으면 중앙값을 믿지 않는다
        if isinstance(m, (int, float)) and m > 0 and n >= 5:
            out[str(it.get("pd_no"))] = {
                "median": float(m), "min": it.get("min_usd"),
                "max": it.get("max_usd"), "n": n, "query": it.get("query"),
            }
    return out


SERP = load_serp_prices()


def load_serp_collected_at() -> str | None:
    """SerpApi 수집 시각. 근거의 신선도 판단에 쓴다. 없으면 None (신선도 불명 = 근거 불인정)."""
    try:
        d = json.loads(SERP_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    value = d.get("generated_at") if isinstance(d, dict) else None
    return value if isinstance(value, str) and value.strip() else None


SERP_COLLECTED_AT = load_serp_collected_at()


# ---------------------------------------------------------------------------
# 판매 전략 정책 (config/daiso_commerce_strategy.json)
#
# 2026-10-11 사용자 승인: 가격/마진은 더 이상 등록을 막는 하드블록이 아니다.
# 목표 마진·손익분기 미달은 경고로 공개하고 등록은 진행한다.
# 막는 것은 "가격 근거가 없거나 잘못된 경우" 뿐이다. 이 요건은 설정 파일로
# 끌 수 없고, 끄려는 설정은 검증에서 거부된다.
# ---------------------------------------------------------------------------
STRATEGY_TAGS = ("skincare", "makeup", "body")


def canonical_daiso_image_path(path) -> bool:
    """허용 목록의 경로는 다이소 CDN 기준 절대경로('/...')만 된다. 호스트·스킴·쿼리·상위 경로는 거부."""
    return (isinstance(path, str) and re.fullmatch(r"/[A-Za-z0-9_\-./]+", path) is not None
            and "//" not in path and ".." not in path.split("/") and not path.endswith("/"))


def validate_strategy(doc: dict) -> dict:
    """정책 문서를 검증한다. 안전 요건을 풀어 주는 설정은 받아들이지 않는다(fail closed)."""
    def need(cond: bool, msg: str) -> None:
        if not cond:
            raise ValueError(f"invalid commerce strategy: {msg}")

    need(isinstance(doc, dict), "not an object")
    cats = doc.get("categories")
    need(isinstance(cats, list) and [c.get("tag") for c in cats if isinstance(c, dict)]
         == list(STRATEGY_TAGS), "categories must be exactly skincare, makeup, body")
    for c in cats:
        for key in ("daiso_name", "daiso_category_no", "product_type", "shopify_taxonomy"):
            need(isinstance(c.get(key), str) and c[key].strip(), f"{c.get('tag')}.{key} missing")
        need(isinstance(c.get("score_buckets"), list) and c["score_buckets"]
             and all(isinstance(b, str) and b for b in c["score_buckets"]), f"{c['tag']}.score_buckets")
        need(c.get("allowed_grades") == ["S"], f"{c['tag']} must be S-only")
    grades = doc.get("grade_policy") or {}
    need(grades.get("allowed_grades") == ["S"] and grades.get("lower_grade_fallback") is False,
         "grade_policy must be S-only without fallback")
    price = doc.get("price_policy") or {}
    need(price.get("mode") == "evidence_based_price", "price_policy.mode must be evidence_based_price")
    need(price.get("margin_hard_block") is False, "price_policy.margin_hard_block must be false")
    adv = price.get("margin_advisory") or {}
    for key in ("target_margin", "minimum_margin", "estimated_weight_extra_margin"):
        need(isinstance(adv.get(key), (int, float)) and not isinstance(adv.get(key), bool)
             and 0 <= adv[key] < 1, f"margin_advisory.{key}")
    ev = price.get("price_evidence") or {}
    need(ev.get("required") is True, "price_evidence.required cannot be disabled")
    need(ev.get("cost_plus_counts_as_evidence") is False, "cost-plus is not price evidence")
    sources = ev.get("sources")
    need(isinstance(sources, dict) and sources, "price_evidence.sources")
    for name, src in sources.items():
        need(isinstance(src, dict) and src.get("level") in {"product", "category"}
             and isinstance(src.get("allowed"), bool), f"sources.{name}")
        if src["allowed"]:
            need(src["level"] == "product", f"sources.{name}: only product-level evidence may be allowed")
            need(isinstance(src.get("min_sample"), int) and src["min_sample"] >= 1, f"sources.{name}.min_sample")
            need(isinstance(src.get("max_age_days"), (int, float)) and src["max_age_days"] > 0,
                 f"sources.{name}.max_age_days must be a positive freshness limit")
    serp_rule = sources.get("serpapi_google_shopping")
    need(serp_rule is None or serp_rule.get("price_claim") == "reference_price_basis_only",
         "SerpApi evidence is a reference price basis only, never a market-minimum claim")
    need(isinstance(ev.get("source_priority"), list)
         and all(s in sources and sources[s]["allowed"] for s in ev["source_priority"]),
         "price_evidence.source_priority must list allowed sources")
    safety = price.get("manufacturer_safety_record") or {}
    need(safety.get("required") is True and safety.get("deferred_plans_count_as_coverage") is False
         and safety.get("scope") == "per product, not global",
         "manufacturer_safety_record must stay required, per product, and not satisfied by deferred plans")
    vol = price.get("volume_comparison") or {}
    need(vol.get("required") is True, "volume_comparison.required cannot be disabled")
    need(isinstance(vol.get("tolerance"), (int, float)) and 0 <= vol["tolerance"] <= 0.10, "volume tolerance")
    need(vol.get("on_unknown_product_volume") == "reject_evidence"
         and vol.get("on_unknown_comparison_volume") == "reject_evidence", "unknown volume must reject evidence")
    img = doc.get("image_policy") or {}
    need(img.get("mode") == "reviewed_product_only_allowlist" and img.get("require_allowlist") is True
         and img.get("retain_face_verification") is True and img.get("human_faces_prohibited") is True,
         "image_policy must keep the reviewed allowlist and face verification")
    allow = img.get("reviewed_product_only_allowlist")
    need(isinstance(allow, dict), "image allowlist must be an object")
    for pd_no, entries in allow.items():
        need(isinstance(entries, list), f"allowlist[{pd_no}] must be a list")
        for entry in entries:
            need(isinstance(entry, dict) and canonical_daiso_image_path(entry.get("path"))
                 and re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256") or ""))
                 and str(entry.get("reviewed_by") or "").strip()
                 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(entry.get("reviewed_at") or "")),
                 f"allowlist[{pd_no}] entry needs path, sha256, reviewed_by, reviewed_at")
    # 2026-10-16 사용자 지시: 메이크업에 등록할 S 가 없으면 다이소 실시간 랭킹(메이크업)에서 하루 1개를 초안으로 올린다.
    # S 전용 등급 정책(grade_policy)은 그대로 둔다. 이 키는 등급을 내리는 것이 아니라 '별도 출처의 비공개 초안' 이다.
    # 안전 요건을 푸는 값(다른 카테고리, 하루 1개 초과, 공개 허용)은 받지 않는다.
    rank = doc.get("makeup_ranking_fallback")
    if rank is not None:
        need(isinstance(rank, dict), "makeup_ranking_fallback must be an object")
        need(rank.get("category") == "makeup", "ranking fallback is makeup-only")
        need(rank.get("status") == "DRAFT_ONLY" and rank.get("public_sale_authorized") is False,
             "ranking fallback creates non-public drafts only")
        need(rank.get("max_per_day") == 1, "ranking fallback is one product per day")
        need(rank.get("trigger") == "no_eligible_canonical_s", "ranking fallback only when no eligible S")
        need(rank.get("decided_by") == "owner_conversation" and isinstance(rank.get("decided_at"), str),
             "ranking fallback needs the owner decision record")
        need(isinstance(rank.get("enabled"), bool), "ranking fallback enabled flag")
        need(isinstance(rank.get("max_candidates_checked"), int) and not isinstance(rank["max_candidates_checked"], bool)
             and 1 <= rank["max_candidates_checked"] <= 30, "ranking fallback max_candidates_checked 1..30")
        need(str(rank.get("api_url") or "").startswith("https://www.daisomall.co.kr/ssn/search/GoodsBestSale"),
             "ranking fallback source must be Daiso realtime ranking")
        for key in ("spf_risk_forms", "uv_filter_ingredients"):
            need(isinstance(rank.get(key), list) and rank[key] and all(isinstance(x, str) and x for x in rank[key]),
                 f"ranking fallback {key}")
    return doc


def load_commerce_strategy(path: Path | None = None) -> dict:
    """config/daiso_commerce_strategy.json 을 읽어 검증한다. 없거나 깨졌으면 예외(대체값 없음)."""
    source = Path(path) if path else STRATEGY_PATH
    raw = source.read_bytes()
    doc = validate_strategy(json.loads(raw.decode("utf-8-sig")))
    doc = dict(doc)
    doc["_sha256"] = hashlib.sha256(raw).hexdigest()
    return doc


def parse_volume(text: str | None) -> dict | None:
    """'2ml*6개입', '2 ml x 6', '1.69 fl oz' -> 총량. 용량 표기가 없으면 None.
    daiso_daily_beauty_to_shopify.parse_size 와 같은 규칙이다(테스트가 둘의 일치를 확인한다)."""
    s = (text or "").lower().replace("fl. oz", "fl oz")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|ml|fl oz|oz|g|l)\b", s)
    if not m:
        return None
    v, u = float(m.group(1)), m.group(2)
    base, mult = {"ml": ("ml", 1), "l": ("ml", 1000), "fl oz": ("ml", 29.5735), "g": ("g", 1),
                  "kg": ("g", 1000), "oz": ("g", 28.3495)}[u]
    unit = v * mult
    c = (re.search(r"[x*\u00d7]\s*(\d+)\b", s[m.end():])
         or re.search(r"(\d+)\s*(?:ea|pcs|pc|\uac1c\uc785|\ub9e4\uc785|\uc785|ct|pack)\b", s[m.end():]))
    pre = re.search(r"(\d+)\s*[x*\u00d7]\s*$", s[: m.start()])
    count = int(c.group(1)) if c else (int(pre.group(1)) if pre else 1)
    return {"unit": round(unit, 2), "base": base, "count": count, "total": round(unit * count, 2)}


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def assess_price_evidence(evidence: dict | None, product_texts, now: datetime | None = None,
                          strategy: dict | None = None) -> dict:
    """가격 근거가 쓸 수 있는지 판정한다. 마진은 보지 않는다. 근거 자체만 본다.

    evidence: {source, median_usd, sample_n, query, collected_at}
      query 는 비교 대상의 이름이다 (용량 비교에 쓴다).
    product_texts: 우리 상품의 이름들 (한글명, 영문 제목). 이 중 용량이 읽히는 첫 번째를 쓴다.
    """
    strategy = strategy or load_commerce_strategy()
    price = strategy["price_policy"]
    vol = price["volume_comparison"]
    now = now or datetime.now(timezone.utc)
    out = {"ok": False, "reasons": [], "source": None, "level": None, "age_days": None,
           "volume_status": "not_checked"}
    if not isinstance(evidence, dict) or not evidence:
        out["reasons"].append("price_evidence_missing")
        return out
    source = str(evidence.get("source") or "")
    out["source"] = source or None
    rule = price["price_evidence"]["sources"].get(source)
    reasons = out["reasons"]
    if not rule or not rule["allowed"]:
        reasons.append(f"price_evidence_source_not_allowed:{source or 'unknown'}")
        out["level"] = rule["level"] if rule else None
        return out
    out["level"] = rule["level"]
    median = evidence.get("median_usd")
    if isinstance(median, bool) or not isinstance(median, (int, float)) or median != median or median <= 0:
        reasons.append("price_evidence_price_invalid")
    n = evidence.get("sample_n")
    if isinstance(n, bool) or not isinstance(n, int) or n < rule["min_sample"]:
        reasons.append(f"price_evidence_sample_too_small:{n}<{rule['min_sample']}")
    stamp = _parse_time(evidence.get("collected_at"))
    if stamp is None:
        reasons.append("price_evidence_collected_at_missing")
    else:
        age = (now - stamp).total_seconds() / 86400
        out["age_days"] = round(age, 2)
        if age < -1:
            reasons.append("price_evidence_dated_in_future")
        elif age > rule["max_age_days"]:
            reasons.append(f"price_evidence_stale:{age:.1f}d>{rule['max_age_days']}d")
    # 용량 비교: 총량(개당 용량 x 입수)이 같아야 같은 상품의 가격이다.
    ours = next((v for v in (parse_volume(t) for t in product_texts or []) if v), None)
    theirs = parse_volume(evidence.get("query"))
    if ours is None:
        out["volume_status"] = "unverified_product_volume"
        reasons.append("price_evidence_volume_unverified_product")
    elif theirs is None:
        out["volume_status"] = "unverified_comparison_volume"
        reasons.append("price_evidence_volume_unverified_comparison")
    elif ours["base"] != theirs["base"] or abs(ours["total"] - theirs["total"]) > vol["tolerance"] * max(
            ours["total"], theirs["total"]):
        out["volume_status"] = "mismatch"
        reasons.append(f"price_evidence_volume_mismatch:ours={ours['total']}{ours['base']},"
                       f"evidence={theirs['total']}{theirs['base']}")
    else:
        out["volume_status"] = "match"
    out["ok"] = not reasons
    return out


def profitability_advisory(price: float, landed_total: float, weight_estimated: bool = False,
                           strategy: dict | None = None) -> dict:
    """마진 경고. 등록을 막지 않는다 (blocks_registration 은 항상 False).
    price: 판매가, landed_total: 그 구성의 착지원가 합계(배송·관세 포함)."""
    adv = (strategy or load_commerce_strategy())["price_policy"]["margin_advisory"]
    fee = price * PAY_RATE + PAY_FIXED
    net = price - landed_total - fee
    margin = net / price if price else None
    breakeven = (landed_total + PAY_FIXED) / (1 - PAY_RATE)
    minimum = adv["minimum_margin"] + (adv["estimated_weight_extra_margin"] if weight_estimated else 0.0)
    warnings = []
    if price and price <= breakeven + 1e-9:
        warnings.append("price_at_or_below_breakeven")
    if margin is not None and margin + 0.0005 < minimum:
        warnings.append(f"margin_below_minimum:{margin * 100:.1f}%<{minimum * 100:.1f}%")
    if margin is not None and margin + 0.0005 < adv["target_margin"]:
        warnings.append(f"margin_below_target:{margin * 100:.1f}%<{adv['target_margin'] * 100:.1f}%")
    status = ("loss" if "price_at_or_below_breakeven" in warnings
              else "below_minimum" if any(w.startswith("margin_below_minimum") for w in warnings)
              else "below_target" if warnings else "ok")
    return {"status": status, "warnings": warnings, "blocks_registration": False, **profit_flags(),
            "net_profit_usd": round(net, 2), "margin_pct": round(margin * 100, 1) if margin is not None else None,
            "breakeven_usd": round(breakeven, 2), "minimum_margin_pct": round(minimum * 100, 1),
            "target_margin_pct": round(adv["target_margin"] * 100, 1),
            "target_price_usd": round(landed_total / (1 - PAY_RATE - adv["target_margin"]), 2)}


def product_market_evidence(pd_no) -> dict | None:
    """상품별 SerpApi 시장가 근거. 없으면 None (지어내지 않는다)."""
    hit = SERP.get(str(pd_no))
    if not hit:
        return None
    return {"source": "serpapi_google_shopping", "median_usd": round(hit["median"], 2),
            "sample_n": hit["n"], "query": hit.get("query"), "collected_at": SERP_COLLECTED_AT,
            # SerpApi 중앙값은 참고 가격 근거다. 같은 상품으로 검증한 비교 대상만 '최저가' 를 말할 수 있다.
            "price_claim": "reference_price_basis_only_not_market_minimum"}


def evidence_price(evidence: dict, qty: int = 1, discount: float = 0.0,
                   strategy: dict | None = None) -> float:
    """근거 가격에서 판매가를 만든다 (SerpApi 중앙값의 price_factor, 보통 95%)."""
    factor = ((strategy or load_commerce_strategy())["price_policy"]["price_evidence"]["sources"]
              .get(evidence.get("source")) or {}).get("price_factor", 1.0)
    return psych_price(float(evidence["median_usd"]) * factor * qty * (1 - discount))


def market_benchmark() -> dict:
    """OliveYoung US 베스트셀러 실수집 가격으로 시장 기준을 잡는다.

    수집 결과가 없으면 빈 dict 를 돌려주고, 호출부는 가격을 산출하지 않는다.
    이전 버전은 사람이 눈으로 본 수치를 상수로 박아 뒀는데 그건 검증이 안 된다.
    """
    if not OLIVEYOUNG.exists():
        return {}
    try:
        d = json.loads(OLIVEYOUNG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    st = d.get("price_stats") or {}
    if not st.get("n"):
        return {}
    return {
        "min": st["min"], "p25": st["p25"],
        "median": st["median"], "max": st["max"],
        "n": st["n"],
        "source": (f"us.oliveyoung.com/best-sellers 실수집 {st['n']}건 "
                   f"({(d.get('collected_at') or '')[:10]})"),
    }


def ship_krw(grams: int) -> int:
    for w, cost in SMALL_PACKET_US:
        if grams <= w:
            return cost
    return SMALL_PACKET_US[-1][1]


MEASURED_PATH = ROOT / "data" / "weights.json"


def load_measured() -> dict:
    """저울로 잰 실제 배송 무게. 있으면 추정값보다 항상 우선한다.

    형식은 data/weights.json 의 measured 아래에 상품번호를 키로 둔다.
      {"measured": {"1045146": {"gram": 128, "note": "포장 포함 실측"}}}
    값이 없으면 빈 dict 를 돌려주고 추정으로 넘어간다. 지어내지 않는다.
    """
    try:
        d = json.loads(MEASURED_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for pd_no, v in (d.get("measured") or {}).items():
        g = v.get("gram") if isinstance(v, dict) else v
        if isinstance(g, (int, float)) and g > 0:
            out[str(pd_no)] = (int(round(g)),
                               (v.get("note") if isinstance(v, dict) else "") or "실측")
    return out


MEASURED = load_measured()
STRATEGY = load_commerce_strategy()

GOSI_PATH = ROOT / "data" / "gosi.json"


def load_gosi_volume() -> dict:
    """고시 표의 '내용물의 용량 또는 중량'.

    상품명에서 뽑는 것보다 정확하다. 상품명에 용량이 없거나 세트 구성이라
    이름만으로는 틀리는 경우가 있다. 고시는 법정 표기라 신뢰도가 높다.

    다만 이것은 내용물 기준이다. 배송 무게는 여기에 용기와 포장이 붙는다.
    그래서 실측은 아니고 근거가 더 나은 추정이다.

    items 가 dict / list 둘 다 와도 동작하도록 처리한다.
    (list 인데 .items() 를 호출하면 AttributeError 가 난다.)
    """
    try:
        d = json.loads(GOSI_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    out = {}
    raw_items = d.get("items") if isinstance(d, dict) else None
    if isinstance(raw_items, dict):
        pairs = list(raw_items.items())
    elif isinstance(raw_items, list):
        pairs = []
        for i, v in enumerate(raw_items):
            if not isinstance(v, dict):
                continue
            pd_no = v.get("pd_no") or v.get("product_id") or v.get("id") or i
            pairs.append((str(pd_no), v))
    else:
        pairs = []

    for pd_no, v in pairs:
        if not isinstance(v, dict):
            continue
        raw = str(v.get("volume") or "").strip()
        if not raw:
            continue
        # "40 ml", "28g", "4ml x 4개입", "1매" 같은 표기를 다룬다
        nums = re.findall(r"(\d+(?:\.\d+)?)\s*(ml|mL|ML|g|G|kg|KG)", raw)
        if not nums:
            continue
        total = 0.0
        for val, unit in nums:
            v2 = float(val)
            if unit.lower() == "kg":
                v2 *= 1000
            total += v2
        # 개입 수가 적혀 있으면 곱한다 (예: 4ml 4개입)
        m = re.search(r"(\d+)\s*(?:개입|매|포|정)", raw)
        if m and len(nums) == 1:
            total *= int(m.group(1))
        if total > 0:
            out[str(pd_no)] = (total, raw)
    return out


GOSI_VOL = load_gosi_volume()


def est_weight(name: str) -> tuple[int, str]:
    """상품명의 용량 표기로 무게를 추정한다. 추정 근거를 함께 반환."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ml|g|mL|ML|G)\b", name)
    if not m:
        return 150 + PACKAGING_G, "용량 표기 없음 - 150g 가정"
    v = float(m.group(1))
    unit = m.group(2).lower()
    # 화장품 내용물 비중 약 1.0, 용기는 내용물의 60% 정도로 잡는다(보수적)
    content = v if unit in ("ml", "g") else v
    total = int(round(content * 1.6)) + PACKAGING_G
    return total, f"{int(v)}{unit} x 1.6(용기) + {PACKAGING_G}g(포장) 추정"


def analyze(p: dict, rate: float, per_order: int, MARKET: dict,
            duty_mode: str = "ddu") -> dict:
    name = p.get("name") or ""
    krw = int(p.get("price_krw") or 0)
    serp = SERP.get(str(p.get("pd_no")))
    pd_key = str(p.get("pd_no"))
    hit = MEASURED.get(pd_key)
    gv = GOSI_VOL.get(pd_key)
    if hit:
        grams, wnote = hit[0], hit[1]
        wsource = "measured"
    elif gv:
        # 고시 용량 기준. 이름 파싱보다 근거가 낫다.
        content, raw = gv
        grams = int(round(content * 1.6)) + PACKAGING_G
        wnote = f"고시 용량 {raw} x 1.6(용기) + {PACKAGING_G}g(포장)"
        wsource = "gosi_volume"
    else:
        grams, wnote = est_weight(name)
        wsource = "estimated"

    cost = krw / rate
    # 주문당 n개를 함께 보낸다고 가정하면 배송비가 n분의 1로 나뉜다
    order_g = grams * per_order
    ship_total = ship_krw(order_g) / rate
    ship_unit = ship_total / per_order

    tariff = cost * TARIFF_RATE

    # ddu: 관세를 우리가 부담하므로 착지원가에 포함
    # ddp: 관세를 고객이 결제 시 별도 납부하므로 우리 원가에서 제외
    landed_ddu = cost + ship_unit + tariff
    landed_ddp = cost + ship_unit
    landed = landed_ddu if duty_mode == "ddu" else landed_ddp

    def profit(sell: float) -> dict:
        fee = sell * PAY_RATE + (PAY_FIXED / per_order)
        net = sell - landed - fee
        return {"sell": round(sell, 2), "fee": round(fee, 2),
                "profit": round(net, 2),
                "margin_pct": round(net / sell * 100, 1) if sell else 0}

    # 손익분기 판매가: sell - landed - (sell*r + fixed/n) = 0
    breakeven = (landed + PAY_FIXED / per_order) / (1 - PAY_RATE)

    return {
        "pd_no": p.get("pd_no"), "name": name, "bucket": p.get("bucket"),
        "shopify_score": p.get("shopify_score"),
        "price_krw": krw,
        "weight_g_est": grams, "weight_note": wnote,
        "weight_source": wsource,
        # 우체국 요금은 100g 단위로 끊긴다. 경계 ±15g 이면 추정으로는 위험해
        # 실측이 필요하다. 그 외에는 고시 용량 추정으로 충분하다.
        "weigh_needed": (wsource != "measured"
                         and min(abs(grams % 100), 100 - (grams % 100)) <= 15),
        "unit_cost_usd": round(cost, 2),
        "shipping_unit_usd": round(ship_unit, 2),
        "shipping_order_usd": round(ship_total, 2),
        "tariff_usd": round(tariff, 2),
        "duty_mode": duty_mode,
        "landed_cost_usd": round(landed, 2),
        "landed_cost_ddu_usd": round(landed_ddu, 2),
        "landed_cost_ddp_usd": round(landed_ddp, 2),
        "customer_pays_duty_at_checkout": duty_mode == "ddp",
        "breakeven_usd": round(breakeven, 2),
        "at_2_2x": profit(cost * 2.2),          # 현재 대시보드 가정
        "at_market_p25": profit(MARKET["p25"]),
        "at_market_median": profit(MARKET["median"]),
        # 상품별 미국 실판매가. 있으면 이쪽이 정확하다.
        "market_price_source": ("serpapi_google_shopping" if serp
                                else "oliveyoung_us_benchmark"),
        "market_median_usd": (round(serp["median"], 2) if serp
                              else MARKET["median"]),
        "market_sample_n": (serp["n"] if serp else MARKET.get("n")),
        "at_product_market": (profit(serp["median"]) if serp else None),
    }


def main() -> int:
    if not SCORE.exists() or not SREC.exists():
        print("점수 파일이 없습니다.")
        return 1
    try:
        fx = (json.loads(STATUS.read_text(encoding="utf-8")) or {}).get("fx") or {}
        rate = float(fx.get("usd_to_krw") or 0)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        rate = 0
    if not rate:
        print("환율이 없습니다. 임의 환율을 쓰지 않고 중단합니다.")
        return 1

    detail = {str(x["pd_no"]): x for x in
              json.loads(SCORE.read_text(encoding="utf-8"))["all_scored"]}
    srec = json.loads(SREC.read_text(encoding="utf-8"))["recommendations"]
    for p in srec:
        p.update({k: v for k, v in (detail.get(str(p["pd_no"])) or {}).items()
                  if k not in p})

    MARKET = market_benchmark()
    if not MARKET:
        print("시장 벤치마크가 없습니다. scripts/collect_oliveyoung_us.py 를 먼저 실행하세요.")
        print("임의의 시장가를 쓰지 않고 중단합니다.")
        return 1

    # 기존 키(N개_묶음배송)는 ddu 기준으로 유지해 대시보드 호환을 지킨다.
    # duty_scenarios 에 두 방식을 모두 담아 비교 가능하게 한다.
    # 우리가 실제로 파는 구성만 만든다.
    # 단품 1개와 1+1(2개) 둘뿐이다. 3개·5개 묶음은 팔지 않는다.
    # 그런데 화면 대표 숫자가 5개 묶음을 읽고 있어서 마진이 부풀려 보였다.
    # 5개면 개당 배송비가 $2.14 인데 단품은 $6.98 이다. 3배 넘게 차이 난다.
    scenarios, duty_scenarios = {}, {}
    for mode in DUTY_MODES:
        for n in SELL_QTYS:
            rows = [analyze(p, rate, n, MARKET, mode) for p in srec]
            duty_scenarios[f"{mode}_{n}개_묶음배송"] = rows
            if mode == "ddu":
                scenarios[f"{n}개_묶음배송"] = rows

    # 상품별 권장가.
    # 전에는 전 상품에 시장 하위25% $18.7 하나를 똑같이 매겼다.
    # 실제 시장가는 마스크 $13, 앰플 $19 로 갈리는데 같은 값을 쓰면
    # 마스크는 44% 비싸게 붙어 안 팔리고 앰플은 남길 것을 못 남긴다.
    def offer_for(row, qty, disc):
        """상품 한 건의 권장가. 상품별 시장가가 있으면 그것을 기준으로 잡는다."""
        base = row.get("market_median_usd") or MARKET["p25"]
        src = row.get("market_price_source") or "oliveyoung_us_benchmark"
        evidence = (product_market_evidence(row.get("pd_no")) if src == "serpapi_google_shopping"
                    else None) or {"source": src, "median_usd": base, "sample_n": MARKET.get("n"),
                                   "query": None, "collected_at": None}
        if src == "serpapi_google_shopping":
            # 실판매 중앙값보다 살짝 아래로 들어간다. 신규 스토어의 진입 가격이다.
            # (비율은 config/daiso_commerce_strategy.json 의 price_factor)
            price = evidence_price(evidence, qty, disc, STRATEGY)
        else:
            price = psych_price(base * qty * (1 - disc))
        land = row["landed_cost_usd"]
        fee = price * PAY_RATE + PAY_FIXED
        net = price - land * qty - fee
        # 2026-10-11 사용자 승인: 손익분기·목표마진 미달은 등록을 막지 않고 경고로 공개한다.
        # register_blocked 는 이제 '가격 근거가 없거나 잘못된 경우' 만 뜻한다.
        assessment = assess_price_evidence(evidence, [row.get("name")], strategy=STRATEGY)
        price_ok = price > 0
        blocked = (not price_ok) or (not assessment["ok"])
        profit = profitability_advisory(price, land * qty, row.get("weight_source") == "estimated", STRATEGY)
        return {
            "pd_no": row.get("pd_no"), "name": row.get("name"),
            "qty": qty, "price_usd": round(price, 2),
            "unit_price_usd": round(price / qty, 2),
            "landed_cost_total_usd": round(land * qty, 2),
            "fee_usd": round(fee, 2),
            "net_profit_usd": round(net, 2),
            "margin_pct": round(net / price * 100, 1) if price else None,
            "market_median_usd": row.get("market_median_usd"),
            "market_price_source": src,
            "price_evidence": {**evidence, "assessment_at_generation": assessment},
            "profitability": profit,
            "profit_warnings": profit["warnings"],
            "register_blocked": blocked,
            "block_reason": ("가격 근거 미달: " + ",".join(assessment["reasons"] or ["price_invalid"])
                             if blocked else ""),
        }

    def per_product(qty, disc, mode="ddu"):
        rows = duty_scenarios[f"{mode}_{qty}개_묶음배송"]
        return [offer_for(r, qty, disc) for r in rows]

    # 전체 요약(대시보드 호환). 상품별 값의 중앙값을 쓴다.
    def offer(qty, disc, mode="ddu"):
        rows = duty_scenarios[f"{mode}_{qty}개_묶음배송"]
        each = per_product(qty, disc, mode)
        land = sum(r["landed_cost_usd"] for r in rows) / len(rows)
        ship = sum(r["shipping_order_usd"] for r in rows) / len(rows)
        prices = sorted(o["price_usd"] for o in each)
        price = prices[len(prices) // 2] if prices else psych_price(MARKET["p25"] * qty)
        fee = price * PAY_RATE + PAY_FIXED
        net = price - land * qty - fee
        return {
            "qty": qty,
            "discount_pct": round(disc * 100),
            "price_usd": round(price, 2),
            "unit_price_usd": round(price / qty, 2),
            "landed_cost_total_usd": round(land * qty, 2),
            "shipping_in_cost_usd": round(ship, 2),
            "fee_usd": round(fee, 2),
            "net_profit_usd": round(net, 2),
            "margin_pct": round(net / price * 100, 1),
            "free_shipping": qty >= FREE_SHIP_MIN_QTY,
            "orders_for_500usd": round(500 / net) if net > 0 else None,
            "price_basis": "상품별 권장가의 중앙값",
            "price_range_usd": [prices[0], prices[-1]] if prices else None,
        }

    single = offer(1, 0.0)
    bundle = offer(BUNDLE_SIZE, BUNDLE_DISCOUNT)
    # 2026-10-16: 판단_근거가 고정 문자열이었다("20%면 36.7%", "15%면 마진 40%·순익 2.2배").
    # 같은 카드에 계산값(세트 마진 59.1%, 순익 1.9배)이 나란히 떠서 서로 달랐다.
    # 비교용 20% 세트도 같은 offer() 로 계산해 문장에 넣는다.
    bundle_deeper = offer(BUNDLE_SIZE, BUNDLE_DISCOUNT + 0.05)
    bundle_ratio = (round(bundle["net_profit_usd"] / single["net_profit_usd"], 1)
                    if single["net_profit_usd"] > 0 else None)
    single_each = per_product(1, 0.0)
    bundle_each = per_product(BUNDLE_SIZE, BUNDLE_DISCOUNT)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "exchange_rate": {"usd_to_krw": rate, "as_of": fx.get("as_of"),
                          "source": fx.get("source")},
        "pricing_policy": {
            "mode": STRATEGY["price_policy"]["mode"],
            "strategy_file": "config/daiso_commerce_strategy.json",
            "strategy_sha256": STRATEGY["_sha256"],
            "margin_hard_block": False,
            "serp_collected_at": SERP_COLLECTED_AT,
            "note": ("register_blocked 는 가격 근거 미달(없음·오래됨·용량 불일치·입력 불가)일 때만 켜진다. "
                     "마진/손익분기 미달은 profit_warnings 로 공개할 뿐 등록을 막지 않는다."),
        },
        "cost_basis": {
            "shipping": SHIPPING_SOURCE,
            "tariff": f"{TARIFF_RATE:.0%} - 미국 화장품 HTS 3304 한국산 상호관세",
            "de_minimis": ("$800 면세 한도는 2025-08-29 전 국가 폐지, "
                           "2026-06-24 CBP 무기한 유예. 소액 소포도 과세 대상."),
            **payment_cost_basis(),
            "weight": (
                f"실측 {len(MEASURED)}건은 data/weights.json 값을 썼다. "
                "나머지는 다이소에 무게 정보가 없어 용량 표기로 추정한 값이라 실측이 필요하다."
            ),
            "not_included": ["광고비(CAC)", "반품/파손", "Shopify 월 구독료",
                             "포장 자재비", "미국 주 판매세", "환율 변동"],
        },
        "market_benchmark": MARKET,
        "offers_by_product": {
            "규칙": ("상품별 미국 실판매 중앙값의 95% 를 기준가로 잡는다. "
                   "신규 스토어라 시장 중앙값보다 살짝 아래로 들어간다. "
                   "상품별 시장가가 없으면 종전 하위25% 벤치마크를 쓴다."),
            "single": single_each,
            "bundle": bundle_each,
        },
        "product_market_prices": {
            "source": "SerpApi google_shopping (미국)",
            "matched": len(SERP),
            "note": ("상품별 실판매가가 있는 건은 그 값으로 마진을 계산한다. "
                     "없으면 올리브영 베스트셀러 벤치마크로 돌아간다."),
        },
        "duty_mode_note": {
            "선택_필요": True,
            "ddu": ("관세를 판매가에 녹인다. 배송사와 관세 선납(DDP 배송) 계약이 "
                    "있어야 성립한다. 없으면 고객이 수령 시 관세를 또 낸다."),
            "ddp": ("Shopify 가 결제 화면에서 고객에게 관세를 따로 받는다. "
                    "판매가에는 관세를 넣지 않는다."),
            "주의": "두 방식을 동시에 적용하면 고객이 관세를 두 번 낸다.",
            "shopify_현황": ("Managed Markets 는 2026-08-24 부터 DDU 지원을 폐지하고 "
                           "DDP 로 자동 전환. 스토어 개설 후 Markets 설정에서 "
                           "한국 발송 셀러 지원 여부를 확인할 것."),
            "기본값": "ddu (scenarios 키가 이 기준. 확인 후 변경)",
        },
        "offers": {
            "single": single,
            "bundle": bundle,
            "free_shipping_min_qty": FREE_SHIP_MIN_QTY,
            "bundle_vs_single": bundle_ratio,
            "판단_근거": (
                f"{BUNDLE_DISCOUNT:.0%} 할인을 고른 이유: 5~10%는 미국 소비자에게 체감이 작다는 판단이다. "
                f"계산값으로 {BUNDLE_DISCOUNT + 0.05:.0%}면 세트 마진 {bundle_deeper['margin_pct']}%, "
                f"{BUNDLE_DISCOUNT:.0%}면 {bundle['margin_pct']}%이고 "
                f"단품 대비 순익은 {bundle_ratio}배다. "
                f"무료배송은 {BUNDLE_SIZE}개 주문 배송비가 이미 원가에 포함돼 추가 부담이 없다."),
            "광고비": "0 (매출이 붙기 전까지 광고하지 않기로 결정)",
        },
        "scenarios": scenarios,
        "duty_scenarios": duty_scenarios,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    print(f"환율 {rate} KRW/USD | 관세 {TARIFF_RATE:.0%} | 수수료 {PAY_NOTE}")
    print("주의: 미확인 추가 수수료/제외 비용 전의 추정 손익이며 전체 검증 순이익이 아닙니다.")
    print(f"시장 벤치마크(올리브영 US): 하위25% ${MARKET['p25']} / 중앙값 ${MARKET['median']}\n")
    print(f"\n[권장 판매 구성]  광고비 0 기준")
    for lbl, o in (("단품", single), (f"{BUNDLE_SIZE}개 세트", bundle)):
        fs = " + 무료배송" if o["free_shipping"] else ""
        print(f"  {lbl:8s} ${o['price_usd']:6.2f}  개당 ${o['unit_price_usd']:5.2f}  "
              f"할인 {o['discount_pct']:2d}%{fs}")
        print(f"           원가 ${o['landed_cost_total_usd']:5.2f} + 수수료 ${o['fee_usd']:4.2f} "
              f"→ 순익 ${o['net_profit_usd']:+5.2f} (마진 {o['margin_pct']:.0f}%) "
              f"· 월$500에 {o['orders_for_500usd']}건")
    print()

    sell = MARKET.get("p25") or 0
    print(f"{'방식':6s} {'묶음':6s} {'착지원가':>9s} {'손익분기':>9s} "
          f"{'판매가':>8s} {'순익':>8s} {'마진':>7s}  고객 관세 부담")
    for mode in DUTY_MODES:
        for n in SELL_QTYS:
            rows = duty_scenarios[f"{mode}_{n}개_묶음배송"]
            land = sum(r["landed_cost_usd"] for r in rows) / len(rows)
            be = sum(r["breakeven_usd"] for r in rows) / len(rows)
            fee = sell * PAY_RATE + PAY_FIXED / n
            net = sell - land - fee
            duty = sum(r["tariff_usd"] for r in rows) / len(rows)
            who = f"결제 시 +${duty:.2f}" if mode == "ddp" else "없음 (판매가에 포함)"
            print(f"{mode:6s} {n}개    ${land:8.2f} ${be:8.2f} "
                  f"${sell:7.2f} ${net:7.2f} {net/sell*100:6.1f}%  {who}")
    print(f"\n저장 -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
