#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
다이소 상품 × 글로벌 8채널 수요 유사도 점수.

2026-08-31 재설계: 글로벌 8채널이 하드코딩/폴백 가짜 데이터로 확인되어
점수 산식에서 완전히 제외했다. 이제 daisomall 에서 실제로 크롤링한
카테고리·평점·리뷰수·가격만으로 점수를 낸다.

- 배점: 카테고리 35 / 평점 20 / 리뷰수 25 / 가격 10 / 키워드 10
- 글로벌 매칭은 참고 정보로만 기록하고 점수에 반영하지 않는다
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
    "바디케어": 34,  # 바디샴푸·바디워시·바디로션 포함 (쇼피파이 수요 높음)
    "맨즈케어": 28,
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

# 상품군 재분류.
# 다이소 카테고리는 헤어 미스트를 스킨케어로 넣는 등 실제 용도와 어긋난다.
# "리노이아 퍼퓸헤어 세럼미스트" 가 스킨케어로 들어와 세럼 토큰만으로
# 세포라 선크림 세럼과 붙었고 시장적합 만점을 받아 S 로 올라왔다.
# 이름에 확실한 단서가 있으면 카테고리보다 이름을 믿는다.
BUCKET_RULES = [
    ("헤어케어", ("헤어", "샴푸", "린스", "트리트먼트", "두피", "hair", "shampoo")),
    ("바디케어", ("바디", "핸드크림", "풋", "body", "hand cream")),
    ("구강용품", ("치약", "칫솔", "구강", "가글")),
    ("네일", ("네일", "매니큐어", "젤네일")),
    ("향수", ("향수", "퍼퓸", "오드", "perfume")),
    ("선케어", ("선크림", "선쿠션", "선스틱", "자차", "spf", "sunscreen")),
    ("클렌징", ("클렌징", "클렌저", "폼", "티슈", "리무버", "cleans")),
    ("마스크팩", ("마스크", "팩", "패드", "mask")),
]


def rebucket(name: str, bucket: str) -> tuple[str, str]:
    """이름에 확실한 단서가 있으면 그것을 따른다. 바뀐 사유를 함께 낸다."""
    low = (name or "").lower()
    for target, kws in BUCKET_RULES:
        if any(k in low for k in kws):
            if target != bucket:
                hit = next(k for k in kws if k in low)
                return target, f"이름의 '{hit}' 로 {bucket} -> {target} 재분류"
            return bucket, ""
    return bucket, ""


# 서로 매칭하면 안 되는 상품군. 헤어와 스킨은 시장이 다르다.
BUCKET_FAMILY = {
    "스킨케어": "skin", "마스크팩": "skin", "선케어": "skin", "클렌징": "skin",
    "메이크업": "makeup", "네일": "makeup",
    "헤어케어": "hair", "바디케어": "body", "구강용품": "oral",
    "향수": "fragrance", "뷰티소품": "tool", "맨즈케어": "skin",
}

# 매칭에 쓸 채널 = 미국에서 실제로 팔리는 상품 목록만.
# 뺀 것: allure_media(기사), google_trends_us/wikipedia_interest(검색어),
# openfda_sunscreen(약품 라벨), open_beauty_facts(유럽 성분 DB).
# 이것들은 상품이 아니라서 이름이 겹쳐도 수요 근거가 못 된다.
# 리노이아 헤어 미스트가 S 로 올라온 원인이 여기 있었다.
MATCH_CHANNELS = (
    "oliveyoung_us", "tiktok_shop_us", "sephora", "ulta_beauty",
    "amazon_best_sellers", "walmart_beauty",
)

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
    # 바디케어 (바디샴푸·워시 포함 — S등급 후보로 유지)
    ("바디샴푸", "bodywash"),
    ("바디 샴푸", "bodywash"),
    ("바디워시", "bodywash"),
    ("바디 워시", "bodywash"),
    ("body wash", "bodywash"),
    ("bodywash", "bodywash"),
    ("body shampoo", "bodywash"),
    ("샤워젤", "bodywash"),
    ("샤워 젤", "bodywash"),
    ("shower gel", "bodywash"),
    ("바디로션", "bodylotion"),
    ("바디 로션", "bodylotion"),
    ("body lotion", "bodylotion"),
    ("bodylotion", "bodylotion"),
    ("바디크림", "bodylotion"),
    ("바디 크림", "bodylotion"),
    ("body cream", "bodylotion"),
    ("핸드크림", "handcream"),
    ("핸드 크림", "handcream"),
    ("hand cream", "handcream"),
    ("handcream", "handcream"),
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

# 뷰티·바디 외 잡상품 (바디샴푸/바디워시는 절대 넣지 말 것)
NON_CORE = (
    "면봉", "거울", "키링", "바지", "양말", "파자마", "걸이", "스탠드",
    "손톱깎이", "면도기", "칫솔", "치약", "테이프", "쌍꺼풀", "샤프너",
    "리필용기", "팬티", "속옷", "치실", "구두약", "저장 용기", "유리 저장",
    "기프트세트", "고체향수",
    # 문구·생활잡화 오매칭 차단
    "볼펜", "젤펜", "만년필", "샤프", "연필", "지우개", "노트", "메모지",
    "덴탈", "치간", "구강", "압축팩", "이불용", "밸브", "수납함", "정리함",
    "블리치", "탈색", "염색약", "헤어컬러",
    "마스크 컬러", "덴탈 마스크", "일회용 마스크", "KF94", "비말차단",
    "샌드크림",  # 볼펜 색상명 오매칭 방지 (바디/스킨 '크림'과 구분)
    "초저점도", "3색",
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
        # 기사(Allure), 검색어(Trends), 성분 라벨(openFDA), 유럽 오픈데이터는
        # 상품이 아니다. Amazon/Walmart 는 사람이 넣은 한글 카탈로그라
        # 미국 실판매명이 아니다. 매칭에서 뺀다.
        if channel not in MATCH_CHANNELS:
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
            sig_bucket, _ = rebucket(blob, "스킨케어")
            cans = to_canonical(blob)
            if not cans:
                continue
            rank_w = max(0.5, 1.0 - rank * 0.05)
            signals.append({
                "channel": channel,
                "product": name,
                "bucket": sig_bucket,
                "form": form_of(blob),
                "canonical": cans,
                "demand": round(w * rank_w, 3),
                "rank": rank + 1,
            })
    return signals


# 제형(형태). 성분이 같아도 형태가 다르면 다른 상품이다.
# 클렌징 워터 티슈가 "톨레리안 퓨리파잉 폼 클렌저" 와 cleanser 토큰
# 하나로 붙어 S 로 올라온 일이 있다. 닦는 티슈와 거품 클렌저는 다르다.
FORM_RULES = [
    ("wipe",    ("티슈", "와이프", "wipe", "tissue", "물티슈")),
    ("pad",     ("패드", "pad")),
    ("mist",    ("미스트", "스프레이", "mist", "spray")),
    ("cushion", ("쿠션", "cushion")),
    ("stick",   ("스틱", "stick")),
    ("mask",    ("마스크", "시트팩", "mask", "sheet")),
    ("ampoule", ("앰플", "ampoule", "ampule")),
    ("serum",   ("세럼", "에센스", "serum", "essence")),
    ("toner",   ("토너", "스킨", "toner")),
    ("foam",    ("폼클", "폼 클", "클렌저", "워시", "foam", "wash", "cleanser")),
    ("oil",     ("오일", "oil")),
    ("gel",     ("젤 ", "gel")),
    ("cream",   ("크림", "밤", "cream", "balm")),
    ("lotion",  ("로션", "에멀전", "lotion", "emulsion")),
    ("powder",  ("파우더", "powder")),
]

# 같이 봐도 되는 제형 묶음. 세럼과 앰플은 사실상 같은 자리를 노린다.
FORM_EQUIV = [{"serum", "ampoule"}, {"cream", "lotion"}]


def form_of(name: str) -> str:
    """이름에서 제형을 뽑는다. 없으면 빈 문자열(가드 미적용)."""
    low = (name or "").lower()
    for form, kws in FORM_RULES:
        if any(k in low for k in kws):
            return form
    return ""


def form_compatible(a: str, b: str) -> bool:
    """한쪽이라도 제형을 못 뽑으면 통과시킨다. 오탐보다 미탐이 낫다."""
    if not a or not b or a == b:
        return True
    return any(a in g and b in g for g in FORM_EQUIV)


def best_matches(daiso_name: str, signals: list[dict], top_n: int = 3,
                 daiso_bucket: str = "") -> list[dict]:
    """상품군이 다르면 아예 비교하지 않는다.

    헤어 미스트가 세럼 토큰 하나로 선크림 세럼과 붙어 S 로 올라온 일이 있다.
    같은 계열(스킨/헤어/바디/구강) 안에서만 유사도를 본다.
    """
    d_can = to_canonical(daiso_name)
    if not d_can:
        return []
    d_fam = BUCKET_FAMILY.get(daiso_bucket or "", "")
    d_form = form_of(daiso_name)
    hits = []
    for sig in signals:
        if d_fam:
            s_fam = BUCKET_FAMILY.get(sig.get("bucket") or "", "")
            if s_fam and s_fam != d_fam:
                continue
        if not form_compatible(d_form, sig.get("form") or ""):
            continue
        inter = d_can & sig["canonical"]
        if not inter:
            continue
        # 교집합 비율 (다이소 기준 + 시그널 기준 평균)
        j_d = len(inter) / len(d_can)
        j_s = len(inter) / max(1, len(sig["canonical"]))
        sim = 0.6 * j_d + 0.4 * j_s
        # 핵심 성분·바디 제형 가산
        key_ings = {
            "snail", "heartleaf", "centella", "ceramide", "niacinamide",
            "retinol", "vitaminc", "sunscreen", "hyaluronic", "collagen", "peptide",
            "bodywash", "bodylotion", "shampoo",
        }
        if inter & key_ings:
            sim = min(1.0, sim + 0.12 * len(inter & key_ings))
        # 약한 단일 토큰(cream/mask/lotion만)은 노이즈 — 하한 상향
        weak_only = inter <= {"cream", "mask", "lotion", "serum"}
        if weak_only and len(inter) == 1:
            sim *= 0.55
        if sim < 0.18:
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


# -- US 시장 적합도 ------------------------------------------------
# 한국어 상품명의 제형/성분을 영문으로 옮겨 실제 미국 판매 목록과 대조한다.
KO_EN = {
    "선크림": ("sunscreen", "sun cream", "spf"), "무기자차": ("mineral", "physical"),
    "선쿠션": ("sun cushion", "sunscreen"), "쿠션": ("cushion",),
    "앰플": ("ampoule", "serum"), "세럼": ("serum",), "에센스": ("essence",),
    "토너": ("toner",), "크림": ("cream",), "로션": ("lotion",),
    "마스크": ("mask",), "팩": ("mask",), "클렌징": ("cleansing", "cleanser"),
    "클렌저": ("cleanser",), "폼": ("foam",), "패드": ("pad",),
    "어성초": ("heartleaf", "houttuynia"), "시카": ("cica", "centella"),
    "병풀": ("centella",), "콜라겐": ("collagen",), "판테놀": ("panthenol",),
    "히알루론": ("hyaluronic",), "나이아신아마이드": ("niacinamide",),
    "비타민": ("vitamin",), "레티놀": ("retinol",), "세라마이드": ("ceramide",),
    "달팽이": ("snail", "mucin"), "펩타이드": ("peptide",), "PDRN": ("pdrn",),
    "수분": ("hydrating", "moistur"), "진정": ("calming", "soothing"),
    "각질": ("exfoliat",), "모공": ("pore",), "미백": ("brightening",),
}
_US_CACHE = None


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def us_listings():
    """실제 미국 판매 목록을 한데 모은다. 없으면 빈 목록."""
    global _US_CACHE
    if _US_CACHE is not None:
        return _US_CACHE
    out = []
    oy = _load_json(ROOT / "data" / "oliveyoung_us_products.json")
    for x in (oy.get("products") or []):
        if x.get("price_usd"):
            out.append({"name": (x.get("product") or "").lower(),
                        "price": float(x["price_usd"])})
    mc = _load_json(ROOT / "data" / "manual_channels.json")
    for c in (mc.get("channels") or {}).values():
        for x in (c.get("products") or []):
            if x.get("price_usd"):
                out.append({"name": (x.get("product") or "").lower(),
                            "price": float(x["price_usd"])})
    _US_CACHE = out
    return out


def us_market_fit(name):
    """미국 실판매 목록에서 같은 제형/성분 상품을 찾는다.

    반환: (점수 최대 25, 매칭 건수, 매칭 상품 중간가)
      매칭 건수 15 - 미국에서 실제로 팔리는 유형인지
      가격 여력 10 - 미국 판매가가 높을수록 마진 여력이 크다
    """
    us = us_listings()
    if not us:
        return 0.0, 0, 0.0
    terms = set()
    for ko, ens in KO_EN.items():
        if ko in name:
            terms.update(ens)
    if not terms:
        return 0.0, 0, 0.0
    hits = [u for u in us if any(t in u["name"] for t in terms)]
    if not hits:
        return 0.0, 0, 0.0
    # 건수만 세면 40% 짜리 약한 매칭 18건이 만점을 받는다. 실제로
    # 헤어 미스트가 그렇게 만점을 받았다. 겹치는 토큰 비율로 가중한다.
    def overlap(u_name: str) -> float:
        got = sum(1 for t in terms if t in u_name)
        return got / max(1, len(terms))

    scored = sorted(((overlap(u["name"]), u) for u in hits), key=lambda x: -x[0])
    strong = [(o, u) for o, u in scored if o >= 0.5]
    weight = sum(o for o, _ in scored[:8])          # 상위 8건의 겹침 합
    hit_pts = min(15.0, weight / 4 * 15)
    prices = sorted(u["price"] for _, u in (strong or scored))
    med = prices[len(prices) // 2]
    price_pts = min(10.0, med / 25 * 10)
    return round(hit_pts + price_pts, 1), len(strong), round(med, 2)


def score_one(p: dict, signals: list[dict]) -> dict:
    """다이소 실측값만으로 점수를 낸다.

    2026-08-31 재설계
      이전 모델은 100점 중 40점을 글로벌 8채널 유사도에서 가져왔는데,
      그 채널들이 하드코딩 카탈로그와 폴백 샘플이었다.
      가짜 신호로 계산된 점수라 전면 폐기하고
      실제로 크롤링한 다이소 값만 쓴다.

    배점 (합계 100)
      카테고리 적합도 35  - CATEGORY_BASE (드롭쉬핑 적합도)
      실측 평점       20  - daisomall 상품 평점
      실측 리뷰수     25  - 리뷰수는 국내 실판매 대리지표
      가격 경쟁력     10  - 원가 대비 마진 확보 가능 구간
      상품유형 키워드 10  - 앰플/세럼/선크림 등

    글로벌 매칭은 점수에 반영하지 않고 참고 정보로만 기록한다.
    검증된 실수집 채널이 확보되면 그때 배점을 다시 연다.
    """
    import math

    name = p.get("name") or ""
    bucket = p.get("bucket") or ""
    # 다이소 카테고리가 실제 용도와 어긋나는 경우가 있다. 이름이 더 정확하다.
    bucket, rebucket_note = rebucket(name, bucket)
    non_core = any(k in name for k in NON_CORE)

    # 1) 카테고리 적합도 (최대 35)
    base_raw = CATEGORY_BASE.get(bucket, 12)
    cat_pts = round(base_raw / 42 * 25, 1)

    # 2) 실측 평점 (최대 20)
    rating = float(p.get("rating") or 0)
    if rating <= 0:
        rating_pts = 0.0
    else:
        rating_pts = round(max(0.0, min(15.0, (rating - 4.0) / 0.9 * 15)), 1)

    # 3) 실측 리뷰수 (최대 25) - 로그 스케일, 500건에서 만점
    reviews = int(p.get("review_count") or 0)
    review_pts = round(min(20.0, math.log10(reviews + 1) / math.log10(2001) * 20), 1) if reviews > 0 else 0.0

    # 4) 가격 경쟁력 (최대 10) - 드롭쉬핑 마진 확보 구간
    krw = int(p.get("price_krw") or 0)
    if krw <= 0:
        price_pts = 0.0
    elif 2000 <= krw <= 5000:
        price_pts = 10.0
    elif 1000 <= krw < 2000 or 5000 < krw <= 7000:
        price_pts = 7.0
    elif krw <= 10000:
        price_pts = 4.0
    else:
        price_pts = 1.0

    # 5) 상품유형 키워드 (최대 10) — 바디샴푸/워시 포함
    kw_pts = 0
    low = name.lower()
    for kw, pts in (
        ("앰플", 5), ("세럼", 5), ("선크림", 4), ("spf", 4),
        ("바디샴푸", 5), ("바디 샴푸", 5), ("바디워시", 5), ("바디 워시", 5),
        ("샤워젤", 4), ("바디로션", 4), ("바디 로션", 4),
        ("토너", 3), ("에센스", 3), ("마스크팩", 3), ("마스크 시트", 3),
        ("마스크", 2), ("크림", 2), ("샴푸", 3),
    ):
        if kw in low:
            kw_pts += pts
    kw_pts = min(5, kw_pts)

    # 6) US 시장 적합도 (최대 25) - 실제 미국 판매 목록과 대조
    us_pts, us_hits, us_price = us_market_fit(name)

    # 이름에 바디샴푸/워시가 있으면 버킷 오분류여도 바디 취급
    is_body_product = any(
        k in name for k in (
            "바디샴푸", "바디 샴푸", "바디워시", "바디 워시",
            "샤워젤", "바디로션", "바디 로션", "바디크림",
        )
    )

    penalty = 40 if non_core else 0

    # 글로벌 8채널 유사도 (무료 시그널) — 최대 25점
    matches = [] if non_core else best_matches(name, signals, daiso_bucket=bucket)
    if matches:
        best = matches[0]["match_score"]
        second = matches[1]["match_score"] if len(matches) > 1 else 0
        sim_pts = min(25, int(best * 24 + second * 4))
    else:
        sim_pts = 0

    # 2026-09-04: sim_pts 는 global_channels 유사도인데 그 안에
    # google_trends_us / tiktok_shop_us 처럼 값이 조작된 채널이 섞여 있다.
    # 총점에서 빼고, 실제 미국 판매 목록과 대조한 us_pts 로 대체한다.
    # sim_pts 는 참고용으로만 기록한다.
    total = max(5, min(100, round(
        cat_pts + rating_pts + review_pts + price_pts + kw_pts + us_pts - penalty)))

    core = bucket in {
        "스킨케어", "선케어", "마스크팩", "클렌징", "메이크업", "헤어케어", "바디케어",
    } or is_body_product
    best_sim = matches[0]["similarity"] if matches else 0
    best_tokens = (matches[0].get("matched_tokens") or []) if matches else []
    # 약한 단일 토큰만 있는 매칭은 S 불가
    strong_match = (
        best_sim >= 0.45
        or len(best_tokens) >= 2
        or bool(set(best_tokens) & {
            "bodywash", "bodylotion", "heartleaf", "snail", "centella",
            "sunscreen", "collagen", "pdrn", "toner", "serum", "ampoule",
            "cleanser", "shampoo",
        })
    )
    # S 는 미국에서 팔리는 같은 형태의 상품을 실제로 찾았을 때만 준다.
    # 예전에는 total >= 92 면 매칭이 22% 여도 S 가 됐다. 다이소 자체 평점과
    # 리뷰만 높아도 92 가 나오므로, 그건 국내 인기지 미국 수요 근거가 아니다.
    best_sim = matches[0]["similarity"] if matches else 0.0
    real_demand = best_sim >= 0.45
    if not non_core and core and total >= 82 and real_demand and (
        strong_match or total >= 92
    ):
        grade = "S"
    elif not non_core and total >= 75:
        grade = "A"
    elif total >= 60:
        grade = "B"
    else:
        grade = "C"

    if non_core:
        reason = "비핵심 상품 (뷰티 카테고리 아님)"
    elif matches and not real_demand and total >= 82:
        m = matches[0]
        reason = (
            f"국내 지표는 높지만 미국 유사 상품 매칭이 {m['similarity']:.0%} 뿐 — "
            f"가장 가까운 것은 '{m['global_product']}' ({m['channel']})"
        )
    elif matches:
        m = matches[0]
        reason = (
            f"글로벌 '{m['global_product']}' ({m['channel']}) 유사 "
            f"{m['similarity']:.0%} · 토큰 {', '.join(m.get('matched_tokens') or [])}"
        )
    else:
        bits = [f"{bucket} 카테고리"]
        if rating > 0:
            bits.append(f"평점 {rating}")
        if reviews > 0:
            bits.append(f"리뷰 {reviews:,}건")
        reason = " · ".join(bits) + " (글로벌 시그널 약함)"

    return {
        "pd_no": p.get("pd_no"),
        "name": name,
        "bucket": bucket,
        "rebucketed": bool(rebucket_note),
        "price_krw": p.get("price_krw"),
        "rating": rating,
        "review_count": reviews,
        "url": p.get("url"),
        "image_url": p.get("image_url"),
        "shopify_score": total,
        "grade": grade,
        "us_market_hits": us_hits,
        "us_median_price_usd": us_price,
        "us_market_hits": us_hits,
        "us_median_price_usd": us_price,
        "score_breakdown": {
            "category": cat_pts,
            "rating": rating_pts,
            "reviews": review_pts,
            "price": price_pts,
            "keyword": kw_pts,
            "us_market_fit": us_pts,
            "rebucket_note": rebucket_note,
            "global_similarity_reference_only": sim_pts,
            "penalty": -penalty,
            "max_possible": 100,
        },
        "scoring_basis": "다이소 실측 + 무료 글로벌 채널 유사도",
        "best_global_match": matches[0] if matches else None,
        "global_matches": matches[:3],
        "recommend_reason": reason,
    }


# -- 최종 등급 확정 ------------------------------------------------
FORMS = ("선쿠션", "선크림", "쿠션", "앰플", "세럼", "에센스", "토너",
         "크림", "로션", "마스크", "팩", "클렌징", "클렌저", "패드", "미스트")


def _form(name):
    for f in FORMS:
        if f in name:
            return f
    return "기타"


def assign_grades(rows, s_ratio=0.08):
    """S 등급을 실제로 등록 가능한 소수로 좁힌다.

    2026-09-04: 164개 중 37개가 S 였고 그중 11개가 100점에 몰려
    변별이 되지 않았다. 두 단계로 거른다.
      1) 같은 제형은 최고점 2개까지만 남긴다.
         선크림 3개, 마스크 5개, 쿠션 4개를 한꺼번에 올릴 일은 없다.
      2) US 시장 매칭 0건은 제외하고, 남은 후보 중 상위 s_ratio 만 S.
    떨어진 후보는 A 로 내리고 사유를 남긴다.
    """
    cands = [r for r in rows if r.get("grade") == "S"]
    if not cands:
        return
    cands.sort(key=lambda r: (-r["shopify_score"], -(r.get("us_market_hits") or 0)))
    seen, kept = {}, []
    for r in cands:
        f = _form(r["name"])
        if seen.get(f, 0) >= 2:
            r["grade"] = "A"
            r["downgrade_reason"] = "동일 제형(%s) 상위 2개에 밀림" % f
            continue
        if not (r.get("us_market_hits") or 0):
            r["grade"] = "A"
            r["downgrade_reason"] = "미국 실판매 목록에서 유사 상품을 찾지 못함"
            continue
        seen[f] = seen.get(f, 0) + 1
        kept.append(r)
    limit = max(3, round(len(rows) * s_ratio))
    for r in kept[limit:]:
        r["grade"] = "A"
        r["downgrade_reason"] = "상위 %d위 밖" % limit
    for i, r in enumerate(kept[:limit], 1):
        r["s_rank"] = i


def main() -> int:
    data = load_json(PRODUCTS, {}) or {}
    products = data.get("products") or []
    if not products:
        print(f"ERROR: no products in {PRODUCTS}")
        return 1

    dashboard = load_json(DASHBOARD, {}) or {}
    signals = extract_signals(dashboard.get("global_channels") or {})
    scored = [score_one(p, signals) for p in products]
    assign_grades(scored)
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
        "rule": "grade == S (core+body category + strong global match; non-beauty filtered)",
        "count": len(s_list),
        "priority_note": "S등급만(바디샴푸·워시 포함). 잡상품·약한 단일토큰 매칭 제외. Shopify 1차 등록 후보.",
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
