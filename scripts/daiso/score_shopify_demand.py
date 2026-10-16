#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
다이소 상품 × 글로벌 실판매 채널 유사도 점수.

S등급 = Shopify 1차 등록 후보. 정본은 shopify_s_recommendations.json.

2026-09-06 필터 강화
- 펫/생활잡화/구강 하드 제외
- '논슬립' → lip 오매칭 차단
- 약한 단일 토큰(lip/pad/cream/mask/lotion/serum/cleanser)만으로는 S 불가
- 성분+제형 동시 매칭 또는 유사도 하한
- 카테고리 불일치·제형 불일치 강등
- google_trends_us 는 수요 매칭에서 제외 (뷰티 RSS는 별도 수집기)
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "data" / "daiso_real" / "products.json"
OUT = ROOT / "data" / "daiso_real" / "shopify_demand_score.json"
OUT_S = ROOT / "data" / "daiso_real" / "shopify_s_recommendations.json"
OUT_REJECT = ROOT / "data" / "daiso_real" / "shopify_s_rejected.json"
DASHBOARD = ROOT / "data" / "dashboard_runtime.json"
PRODUCT_MASTER = ROOT / "data" / "product_master.json"

CATEGORY_BASE = {
    "스킨케어": 42,
    "마스크팩": 38,
    "클렌징": 34,
    "메이크업": 32,
    "헤어케어": 30,
    "바디케어": 34,
    "맨즈케어": 28,
    "향수": 22,
    "뷰티소품": 14,
    "구강용품": 10,
}

CHANNEL_WEIGHT = {
    "tiktok_shop_us": 1.0,
    "oliveyoung_us": 0.98,
    "amazon_best_sellers": 0.95,
    "sephora": 0.9,
    "ulta_beauty": 0.85,
    "walmart_beauty": 0.8,
    # 2026-09-28 추가: 미국 K뷰티 편집숍, Amazon 급상승·신상품
    "sokoglam_us": 0.95,
    "amazon_movers_beauty": 0.85,
    "amazon_new_beauty": 0.75,
}

CORE_BUCKETS = {
    # 선케어(미국 OTC 의약품)와 네일(인화성 액체, 항공배송 제약)은 제외.
    "스킨케어", "마스크팩", "클렌징", "메이크업", "헤어케어", "바디케어",
}

# 상품이 실제로 미국에서 팔리는 목록만 매칭. Trends/기사/라벨 DB 제외.
MATCH_CHANNELS = (
    "oliveyoung_us", "tiktok_shop_us", "sephora", "ulta_beauty",
    "amazon_best_sellers", "walmart_beauty",
    "sokoglam_us", "amazon_movers_beauty", "amazon_new_beauty",
)

# 한·영 → 공통 정규 토큰. 짧은 '립'은 넣지 않는다 (논슬립 → lip 사고).
LEXICON: list[tuple[str, str]] = [
    ("어성초", "heartleaf"), ("heartleaf", "heartleaf"), ("houttuynia", "heartleaf"),
    ("병풀", "centella"), ("센텔라", "centella"), ("centella", "centella"),
    ("cica", "centella"), ("시카", "centella"),
    ("달팽이", "snail"), ("뮤신", "snail"), ("snail", "snail"), ("mucin", "snail"),
    ("히알루론", "hyaluronic"), ("히알루로닉", "hyaluronic"), ("hyaluronic", "hyaluronic"),
    ("세라마이드", "ceramide"), ("ceramide", "ceramide"),
    ("나이아신", "niacinamide"), ("니아신", "niacinamide"), ("niacinamide", "niacinamide"),
    ("레티놀", "retinol"), ("retinol", "retinol"),
    ("펩타이드", "peptide"), ("peptide", "peptide"),
    ("콜라겐", "collagen"), ("collagen", "collagen"),
    ("비타민c", "vitaminc"), ("비타민 c", "vitaminc"), ("비타씨", "vitaminc"),
    ("vita c", "vitaminc"), ("vitamin c", "vitaminc"),
    ("pdrn", "pdrn"),
    ("티트리", "teatree"), ("tea tree", "teatree"),
    ("토너", "toner"), ("toner", "toner"),
    ("세럼", "serum"), ("serum", "serum"),
    ("앰플", "ampoule"), ("ampoule", "ampoule"), ("ampule", "ampoule"),
    ("에센스", "essence"), ("essence", "essence"),
    ("크림", "cream"), ("cream", "cream"),
    ("로션", "lotion"), ("lotion", "lotion"),
    ("모이스처", "moisturizer"), ("moisturizer", "moisturizer"),
    ("moisturizing", "moisturizer"),
    ("클렌징", "cleanser"), ("클렌저", "cleanser"), ("cleanser", "cleanser"),
    ("마스크팩", "mask"), ("시트팩", "mask"), ("마스크", "mask"), ("mask", "mask"),
    ("선크림", "sunscreen"), ("선쿠션", "sunscreen"), ("sunscreen", "sunscreen"),
    ("spf", "sunscreen"), ("자외선", "sunscreen"), ("무기자차", "sunscreen"),
    # 2026-09-28: ROUND LAB "UVLOCK" 선크림이 클렌징 밀크와 매칭됐다. 선크림 표기를 더 잡는다.
    ("uvlock", "sunscreen"), ("uv lock", "sunscreen"), ("sun cream", "sunscreen"),
    ("sunblock", "sunscreen"), ("sun stick", "sunscreen"), ("sun serum", "sunscreen"),
    ("쿠션", "cushion"), ("cushion", "cushion"),
    ("프라이머", "primer"), ("primer", "primer"),
    ("블러쉬", "blush"), ("블러시", "blush"), ("blush", "blush"),
    ("립밤", "lip"), ("립틴트", "lip"), ("립글로스", "lip"), ("립스틱", "lip"),
    ("립 틴트", "lip"), ("lip tint", "lip"), ("lip balm", "lip"), ("lipstick", "lip"),
    ("샴푸", "shampoo"), ("shampoo", "shampoo"),
    ("트리트먼트", "treatment"), ("treatment", "treatment"),
    ("바디샴푸", "bodywash"), ("바디 샴푸", "bodywash"),
    ("바디워시", "bodywash"), ("바디 워시", "bodywash"),
    ("body wash", "bodywash"), ("bodywash", "bodywash"),
    ("body shampoo", "bodywash"), ("샤워젤", "bodywash"), ("shower gel", "bodywash"),
    ("바디로션", "bodylotion"), ("바디 로션", "bodylotion"),
    ("body lotion", "bodylotion"), ("bodylotion", "bodylotion"),
    ("바디크림", "bodylotion"), ("body cream", "bodylotion"),
    ("핸드크림", "handcream"), ("hand cream", "handcream"),
    ("수분", "hydrating"), ("보습", "hydrating"),
    ("hydrating", "hydrating"), ("hydration", "hydrating"),
    ("진정", "calming"), ("calming", "calming"), ("soothing", "calming"),
    ("미백", "brightening"), ("잡티", "brightening"), ("기미", "brightening"),
    ("brightening", "brightening"),
    ("모공", "pore"), ("pore", "pore"),
    ("탄력", "firming"), ("firming", "firming"),
    ("주름", "antiaging"), ("anti-aging", "antiaging"),
    ("repair", "repair"), ("리페어", "repair"),
    ("cosrx", "cosrx"), ("anua", "anua"), ("cerave", "cerave"),
    ("ordinary", "ordinary"), ("laneige", "laneige"),
    ("tirtir", "tirtir"), ("medicube", "medicube"),
]
_LEX_SORTED = sorted(LEXICON, key=lambda x: -len(x[0]))

INGREDIENT_TOKENS = {
    "heartleaf", "snail", "centella", "ceramide", "niacinamide",
    "retinol", "vitaminc", "sunscreen", "hyaluronic", "collagen",
    "peptide", "pdrn", "teatree",
}
FORM_TOKENS = {
    "toner", "serum", "ampoule", "essence", "sunscreen", "cushion",
    "bodywash", "bodylotion", "shampoo", "cleanser", "mask", "cream",
}
WEAK_SOLO = {
    "lip", "pad", "cream", "mask", "lotion", "serum", "cleanser",
    "essence", "treatment", "repair", "hydrating", "foam",
}

NON_CORE = (
    "면봉", "거울", "키링", "바지", "양말", "파자마", "걸이", "스탠드",
    "손톱깎이", "면도기", "칫솔", "치약", "테이프", "쌍꺼풀", "샤프너",
    "리필용기", "팬티", "속옷", "치실", "구두약", "저장 용기", "유리 저장",
    "기프트세트", "고체향수",
    "볼펜", "젤펜", "만년필", "샤프", "연필", "지우개", "노트", "메모지",
    "덴탈", "치간", "구강", "압축팩", "이불용", "밸브", "수납함", "정리함",
    "블리치", "탈색", "염색약", "헤어컬러",
    "마스크 컬러", "덴탈 마스크", "일회용 마스크", "KF94", "비말차단",
    "샌드크림", "초저점도", "3색",
    # 펫·생활잡화 — '논슬립' 은 lip 오매칭 원인이기도 함
    "[펫]", "펫]", "펫 ", "반려동물", "강아지", "고양이", "애견", "포포몽",
    "배변", "배변패드", "배변 패드", "논슬립", "대나무 배변",
    "용기", "공병", "펌프만",
)

STOP = {"the", "and", "for", "with", "from", "best", "ml", "oz", "by", "new"}

# 펫/구강은 마스크팩·클렌징으로 재분류하지 않는다.
BUCKET_RULES = [
    ("헤어케어", ("헤어", "샴푸", "린스", "트리트먼트", "두피", "hair", "shampoo")),
    ("바디케어", ("바디샴푸", "바디워시", "바디로션", "핸드크림", "body wash", "hand cream")),
    ("구강용품", ("치약", "칫솔", "구강", "가글")),
    ("향수", ("향수", "퍼퓸", "오드뚜왈렛", "perfume")),
    ("클렌징", ("클렌징", "클렌저", "리무버")),
    ("마스크팩", ("마스크팩", "시트팩", "마스크 시트")),
]

BUCKET_FAMILY = {
    "스킨케어": "skin", "마스크팩": "skin", "클렌징": "skin",
    "메이크업": "makeup",
    "헤어케어": "hair", "바디케어": "body", "구강용품": "oral",
    "향수": "fragrance", "뷰티소품": "tool", "맨즈케어": "skin",
}


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_cp_registry() -> dict[str, str]:
    """pd_no -> canonical_product_id (CP). product_master.json 정본."""
    doc = load_json(PRODUCT_MASTER, {}) or {}
    reg = doc.get("pd_no_to_cp") or {}
    return {str(k): str(v) for k, v in reg.items()}


def is_non_core(name: str) -> bool:
    return any(k in (name or "") for k in NON_CORE)


def rebucket(name: str, bucket: str) -> tuple[str, str]:
    if is_non_core(name):
        return bucket, ""
    low = (name or "").lower()
    for target, kws in BUCKET_RULES:
        if any(k in low for k in kws):
            if target != bucket:
                hit = next(k for k in kws if k in low)
                return target, f"이름의 '{hit}' 로 {bucket} -> {target} 재분류"
            return bucket, ""
    return bucket, ""


def to_canonical(text: str) -> set[str]:
    if not text:
        return set()
    t = text.lower()
    t = re.sub(r"\s+", " ", t)
    # 논슬립이 립으로 잘리지 않게 선치환
    t = t.replace("논슬립", " ")
    found: set[str] = set()
    for src, canon in _LEX_SORTED:
        if src in t:
            found.add(canon)
            t = t.replace(src, " ")
    for p in re.findall(r"[a-z]{4,}", t):
        if p not in STOP:
            found.add(p)
    return found


FORM_RULES = [
    ("wipe", ("티슈", "와이프", "wipe", "tissue", "물티슈")),
    ("pad", ("패드", "pad")),
    ("mist", ("미스트", "스프레이", "mist", "spray")),
    ("cushion", ("쿠션", "cushion")),
    ("stick", ("스틱", "stick")),
    ("mask", ("마스크팩", "시트팩", "mask sheet", "sheet mask")),
    ("ampoule", ("앰플", "ampoule", "ampule")),
    ("serum", ("세럼", "에센스", "serum", "essence")),
    ("toner", ("토너", "toner")),
    ("foam", ("폼클", "폼 클", "클렌저", "워시", "foam", "wash", "cleanser")),
    ("oil", ("오일", "oil")),
    ("gel", ("젤", "gel")),
    ("cream", ("크림", "밤", "cream", "balm")),
    ("lotion", ("로션", "에멀전", "lotion", "emulsion")),
    ("powder", ("파우더", "powder")),
]
FORM_EQUIV = [{"serum", "ampoule"}, {"cream", "lotion"}]


def form_of(name: str) -> str:
    low = (name or "").lower()
    if is_non_core(name):
        return "blocked"
    for form, kws in FORM_RULES:
        if any(k in low for k in kws):
            return form
    return ""


def form_compatible(a: str, b: str) -> bool:
    if a == "blocked" or b == "blocked":
        return False
    if not a or not b or a == b:
        return True
    return any(a in g and b in g for g in FORM_EQUIV)


def provenanced_channels(dashboard: dict) -> dict:
    """수집 시각이 있는 채널만 매칭 근거로 넘긴다.

    2026-10-16 실측: S등급 8개 중 4개가 tiktok_shop_us 행과 매칭돼 있었다.
    그 채널은 status=unverified · collected_at 없음 · 행마다 원본 URL 없음이고,
    data/tiktok_shop.json(2026-09-02) 의 조회수(2.4M·1.8M…)를 만든 수집기가 저장소에 없다.
    가중치는 1.0 으로 전 채널 최고였다. 출처를 확인할 수 없는 행이 등급을 올리고 있었다.
    build_daiso_candidate_comparison.py 는 이미 같은 채널을 'unverified_or_stale_source' 로
    빼고 있어서 두 경로의 판단이 달랐다. 여기서도 같은 기준으로 뺀다.
    낡았지만(stale) 수집 시각이 있는 실수집 채널은 그대로 쓴다. 오래된 것과 출처 없는 것은 다르다.
    """
    gc = dashboard.get("global_channels") or {}
    st = dashboard.get("global_channels_status") or {}
    if not isinstance(gc, dict):
        return {}
    if not st:
        # 상태표가 없는 구버전 런타임은 판정할 근거가 없다. 조용히 다 빼면 점수가 0 이 되고
        # 조용히 다 쓰면 위 문제가 그대로다. 그대로 쓰되 로그에 남긴다.
        print("  [경고] global_channels_status 없음 - 채널 출처 검사 생략")
        return gc
    kept = {}
    for channel, items in gc.items():
        meta = st.get(channel) or {}
        status = str(meta.get("status") or "").lower()
        if status in ("unverified", "disabled") or not meta.get("collected_at"):
            print(f"  [제외] {channel}: status={status or '-'} collected_at={meta.get('collected_at') or '없음'}")
            continue
        kept[channel] = items
    return kept


def extract_signals(global_channels: dict) -> list[dict]:
    signals = []
    if not isinstance(global_channels, dict):
        return signals
    for channel, items in global_channels.items():
        if not isinstance(items, list) or channel not in MATCH_CHANNELS:
            continue
        w = CHANNEL_WEIGHT.get(channel, 0.6)
        for rank, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            name = str(
                item.get("product") or item.get("keyword") or item.get("title")
                or item.get("name") or ""
            ).strip()
            if len(name) < 3:
                continue
            brand = str(item.get("brand") or "")
            blob = f"{name} {brand} {item.get('category') or ''} {item.get('sub') or ''}"
            sig_bucket, _ = rebucket(blob, "스킨케어")
            cans = to_canonical(blob)
            if not cans:
                continue
            # 선크림은 미국 OTC 의약품이라 우리가 팔지 않는다. 다른 상품의 매칭 근거로도
            # 쓰지 않는다 (보습 토큰 하나로 클렌저와 이어지는 일을 막는다).
            if "sunscreen" in cans:
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


def best_matches(daiso_name: str, signals: list[dict], top_n: int = 3,
                 daiso_bucket: str = "") -> list[dict]:
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
        j_d = len(inter) / len(d_can)
        j_s = len(inter) / max(1, len(sig["canonical"]))
        sim = 0.6 * j_d + 0.4 * j_s
        if inter & INGREDIENT_TOKENS:
            sim = min(1.0, sim + 0.12 * len(inter & INGREDIENT_TOKENS))
        if inter <= WEAK_SOLO and len(inter) == 1:
            sim *= 0.4
        if sim < 0.22:
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


KO_EN = {
    "선크림": ("sunscreen", "sun cream", "spf"), "무기자차": ("mineral", "physical"),
    "선쿠션": ("sun cushion", "sunscreen"), "쿠션": ("cushion",),
    "앰플": ("ampoule", "serum"), "세럼": ("serum",), "에센스": ("essence",),
    "토너": ("toner",), "크림": ("cream",), "로션": ("lotion",),
    "마스크팩": ("mask",), "시트팩": ("mask",),
    "클렌징": ("cleansing", "cleanser"), "클렌저": ("cleanser",),
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


def us_market_fit(name, market_listings=None):
    # Candidate comparisons may supply a verified fresh market universe.
    # Existing operational callers retain their current scoring inputs.
    us = us_listings() if market_listings is None else market_listings
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

    def overlap(u_name: str) -> float:
        got = sum(1 for t in terms if t in u_name)
        return got / max(1, len(terms))

    scored = sorted(((overlap(u["name"]), u) for u in hits), key=lambda x: -x[0])
    strong = [(o, u) for o, u in scored if o >= 0.33]
    weight = sum(o for o, _ in scored[:8])
    hit_pts = min(15.0, weight / 4 * 15)
    prices = sorted(u["price"] for _, u in (strong or scored))
    med = prices[len(prices) // 2]
    price_pts = min(10.0, med / 25 * 10)
    return round(hit_pts + price_pts, 1), len(strong), round(med, 2)


# 미국에서 그대로는 못 파는 것들. 소싱 단계에서 걸러야 한다.
# 뒤늦게 법률팀이 막으면 이미 카피·가격·고시 작업을 다 해버린 뒤다.
#
# SPF 표기 제품은 미국에서 화장품이 아니라 OTC 의약품이다.
# Drug Facts 라벨, 활성성분 표기, 시설 등록이 따로 필요하다.
US_OTC_SUN = ("spf", "선크림", "선스틱", "선쿠션", "선세럼", "자차", "선블록",
              "sunscreen", "sun cream", "pa+")

# 상품의 핵심 소구점이 미국에서 의약품 주장이 되는 경우.
# 미백은 OTC 의약품 주장이고, 주름개선·여드름 치료도 마찬가지다.
# 그 말을 못 쓰면 그 상품을 팔 이유 자체가 사라지므로 후보에서 뺀다.
KR_CLAIM_RISK = {
    "화이트닝": "미백 - 미국에서 OTC 의약품 주장",
    "미백": "미백 - 미국에서 OTC 의약품 주장",
    "주름개선": "주름개선 - 미국에서 의약품 주장",
    "링클": "주름개선 - 미국에서 의약품 주장",
    "안티에이징": "항노화 - 미국에서 의약품 주장",
    "여드름": "여드름 치료 - 미국에서 OTC 의약품",
    "아크네": "여드름 치료 - 미국에서 OTC 의약품",
    "기능성화장품": "한국 기능성 제도 표현 - 미국에 없는 범주",
    "아토피": "질병명 - 화장품에 쓸 수 없음",
}


def us_blockers(name: str) -> tuple[str, str]:
    """(구분, 사유). 문제 없으면 ("", "")."""
    low = (name or "").lower()
    for k in US_OTC_SUN:
        if k in low:
            return "otc_drug", f"'{k}' - 미국에서 OTC 의약품(Drug Facts 라벨 필요)"
    for k, why in KR_CLAIM_RISK.items():
        if k in name:
            return "claim_risk", why
    return "", ""


def qualify_s(name: str, bucket: str, total: int, matches: list,
              sold_out: bool = False) -> tuple[bool, str]:
    """S등급 단일 게이트. True면 등록 후보.

    품절은 여기서 막는다.

    09-09 에 S등급 1위 '드롭비 탄탄 광채 앰플' 이 품절 상태였다.
    품절이어도 og:title 에 가격이 있어 파싱은 성공한다. 수집기가 성공
    경로에서 품절을 안 읽었고 이 게이트도 재고를 보지 않았다.
    살 수 없는 물건을 미국에 등록할 뻔했다.

    품절은 되돌아오니 지우지 않는다. 등급만 내린다.
    """
    if sold_out:
        return False, "sold_out"
    if is_non_core(name):
        return False, "non_core"
    kind, _why = us_blockers(name)
    if kind:
        return False, kind
    if bucket not in CORE_BUCKETS:
        return False, "non_core_bucket"
    if total < 82:
        return False, "score_below_82"
    if not matches:
        return False, "no_global_match"
    m = matches[0]
    tokens = set(m.get("matched_tokens") or [])
    sim = float(m.get("similarity") or 0)
    if tokens <= WEAK_SOLO and len(tokens) <= 1:
        return False, "weak_solo_token"
    has_ing = bool(tokens & INGREDIENT_TOKENS)
    has_form = bool(tokens & FORM_TOKENS)
    if has_ing and has_form and sim >= 0.45:
        return True, "ingredient+form"
    if len(tokens) >= 2 and sim >= 0.55 and (has_ing or has_form):
        return True, "multi_token"
    if has_ing and sim >= 0.70:
        return True, "strong_ingredient"
    if has_form and sim >= 0.65:
        return True, "strong_form"
    return False, "match_too_weak"


def score_one(p: dict, signals: list[dict], *, market_listings=None) -> dict:
    name = p.get("name") or ""
    bucket = p.get("bucket") or p.get("site_category") or ""
    bucket, rebucket_note = rebucket(name, bucket)
    non_core = is_non_core(name)

    base_raw = CATEGORY_BASE.get(bucket, 12)
    cat_pts = round(base_raw / 42 * 25, 1)

    rating = float(p.get("rating") or 0)
    rating_pts = 0.0 if rating <= 0 else round(max(0.0, min(15.0, (rating - 4.0) / 0.9 * 15)), 1)

    reviews = int(p.get("review_count") or 0)
    review_pts = round(min(20.0, math.log10(reviews + 1) / math.log10(2001) * 20), 1) if reviews > 0 else 0.0

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

    kw_pts = 0
    low = name.lower()
    for kw, pts in (
        ("앰플", 5), ("세럼", 5), ("선크림", 4), ("spf", 4),
        ("바디샴푸", 5), ("바디워시", 5), ("샤워젤", 4), ("바디로션", 4),
        ("토너", 3), ("에센스", 3), ("마스크팩", 3), ("마스크 시트", 3),
        ("시카", 3), ("어성초", 3), ("pdrn", 3),
    ):
        if kw in low:
            kw_pts += pts
    kw_pts = min(5, kw_pts)

    us_pts, us_hits, us_price = (0.0, 0, 0.0) if non_core else us_market_fit(name, market_listings)

    penalty = 40 if non_core else 0
    matches = [] if non_core else best_matches(name, signals, daiso_bucket=bucket)
    sim_pts = 0
    if matches:
        best = matches[0]["match_score"]
        second = matches[1]["match_score"] if len(matches) > 1 else 0
        sim_pts = min(25, int(best * 24 + second * 4))

    total = max(5, min(100, round(
        cat_pts + rating_pts + review_pts + price_pts + kw_pts + us_pts - penalty)))

    ok_s, s_rule = qualify_s(name, bucket, total, matches, bool(p.get("sold_out")))
    if ok_s:
        grade = "S"
    elif not non_core and total >= 75:
        grade = "A"
    elif total >= 60:
        grade = "B"
    else:
        grade = "C"

    us_kind, us_why = us_blockers(name)
    if non_core:
        reason = "비핵심 상품 (펫·잡화·구강 등)"
    elif us_kind:
        reason = f"미국 판매 제약: {us_why}"
    elif matches:
        m = matches[0]
        reason = (
            f"글로벌 '{m['global_product']}' ({m['channel']}) 유사 "
            f"{m['similarity']:.0%} · 토큰 {', '.join(m.get('matched_tokens') or [])}"
        )
        if not ok_s:
            reason += f" · S제외:{s_rule}"
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
        "site_category": p.get("site_category"),
        "rebucketed": bool(rebucket_note),
        "price_krw": p.get("price_krw"),
        "rating": rating,
        "review_count": reviews,
        "url": p.get("url"),
        "image_url": p.get("image_url"),
        "shopify_score": total,
        "grade": grade,
        "s_rule": s_rule,
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
            "us_block_kind": us_kind,
            "us_block_reason": us_why,
            "max_possible": 100,
        },
        "scoring_basis": "다이소 실측 + 글로벌 실판매 유사도 + S게이트",
        "best_global_match": matches[0] if matches else None,
        "global_matches": matches[:3],
        "recommend_reason": reason,
    }


FORMS = ("선쿠션", "선크림", "쿠션", "앰플", "세럼", "에센스", "토너",
         "크림", "로션", "마스크팩", "시트팩", "클렌징", "클렌저", "미스트")


def _form(name):
    for f in FORMS:
        if f in name:
            return f
    return "기타"



# ---------------------------------------------------------------- 카테고리 전담팀 (2026-10-11)
# 사용자 지시: S등급을 스킨케어 / 메이크업 / 바디 3개 카테고리로 나눠 전담팀이 각자 작업한다.
# 예전에는 전체에서 점수 상위 10개만 S 로 남겨 10개 모두 스킨케어였다(메이크업 0, 바디 0).
# - 카테고리 구분은 config/daiso_commerce_strategy.json 의 score_buckets 를 그대로 쓴다.
# - 스킨케어는 기존 S 정원을 그대로 쓰고, 메이크업·바디 전담팀은 별도 정원(각 2)을 더 받는다.
# - 스킨케어 = 다이소 스킨케어 종류만. 선케어·마스크팩·클렌징 등 전담팀 범위 밖은 S 가 되지 않는다.
# - 메이크업·바디는 미국 실판매 목록 근거가 있는 상품만 전담팀 기준으로 S 를 준다.
#   법률·라벨·안전·가격 게이트는 그대로라 S 가 곧 공개를 뜻하지 않는다.
DESK_DEFAULT = {"skincare": ["스킨케어"],  # 다이소 스킨케어 종류만: 스킨/토너·에센스/세럼/앰플·크림·로션·미스트/픽서
                "makeup": ["메이크업"], "body": ["바디케어"]}
DESK_NAME = {"skincare": "스킨케어 전담팀", "makeup": "메이크업 전담팀", "body": "바디 전담팀"}
DESK_QUOTA = {"makeup": 2, "body": 2}          # 나머지 정원은 스킨케어
DESK_MIN_SCORE = {"makeup": 75, "body": 80}    # 전담팀 기준 최소 점수
DESK_MIN_US_HITS = 2                           # 미국 실판매 목록 유사 상품 수
DESK_EXCLUDE = ("핸드크림", "슬리퍼", "실내화", "풋크림")  # 사용자 지시로 제외해 온 품목


def _load_desks() -> dict:
    try:
        cfg = json.loads((Path(__file__).resolve().parents[2] / "config" / "daiso_commerce_strategy.json")
                         .read_text(encoding="utf-8"))
        out = {c["tag"]: [b for b in (c.get("score_buckets") or []) if b != "선케어"] for c in cfg.get("categories") or []
               if isinstance(c, dict) and c.get("tag") in DESK_NAME}
        return out if set(out) == set(DESK_NAME) else dict(DESK_DEFAULT)
    except (OSError, ValueError, KeyError, TypeError):
        return dict(DESK_DEFAULT)


CATEGORY_DESKS = _load_desks()


def _load_desk_scope() -> tuple[dict, dict]:
    """다이소몰 카테고리 목록(desk_catalog.json)과 config 의 전담팀 소분류 이름."""
    root = Path(__file__).resolve().parents[2]
    member, cats = {}, {}
    try:
        cfg = json.loads((root / "config" / "daiso_commerce_strategy.json").read_text(encoding="utf-8"))
        for tag, spec in (cfg.get("category_desks") or {}).items():
            if tag in DESK_NAME and isinstance(spec, dict):
                cats[tag] = {c.get("name") for c in spec.get("categories") or [] if isinstance(c, dict)}
    except (OSError, ValueError, TypeError):
        pass
    try:
        cat = json.loads((root / "data" / "daiso_real" / "desk_catalog.json").read_text(encoding="utf-8"))
        for tag, info in (cat.get("desks") or {}).items():
            if tag in DESK_NAME:
                for p in info.get("products") or []:
                    member.setdefault(str(p.get("pd_no")), tag)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return member, cats


DESK_MEMBER, DESK_SITE_CATEGORIES = _load_desk_scope()


def desk_of(bucket: str, pd_no: str | None = None, site_category: str | None = None) -> str | None:
    """전담팀 판정 (사용자 지시 2026-10-11: 다이소몰 카테고리 목록 그대로).

    1) 다이소몰 카테고리 목록(desk_catalog.json)에 있으면 그 전담팀
    2) 목록에 없으면 상품 상세의 소분류(site_category)가 전담팀 소분류인지
    3) 목록·소분류 정보가 아예 없을 때만 예전 버킷 기준
    """
    if pd_no and str(pd_no) in DESK_MEMBER:
        return DESK_MEMBER[str(pd_no)]
    if DESK_SITE_CATEGORIES:
        for tag, names in DESK_SITE_CATEGORIES.items():
            if site_category and site_category in names:
                return tag
        if DESK_MEMBER or site_category:
            return None
    for tag, buckets in CATEGORY_DESKS.items():
        if bucket in buckets:
            return tag
    return None


def desk_promote(rows) -> None:
    """메이크업·바디 전담팀 기준: 미국 실판매 근거 + 전담팀 최소 점수면 S 후보로 올린다."""
    for r in rows:
        desk = desk_of(r.get("bucket") or "", r.get("pd_no"), r.get("site_category"))
        r["desk"] = desk
        if desk not in DESK_MIN_SCORE or r.get("grade") == "S":
            continue
        name = r.get("name") or ""
        if (is_non_core(name) or us_blockers(name)[0] or any(k in name for k in DESK_EXCLUDE)
                or r.get("s_rule") in ("sold_out", "non_core", "non_core_bucket")):
            continue
        if (r.get("shopify_score") or 0) >= DESK_MIN_SCORE[desk] and (r.get("us_market_hits") or 0) >= DESK_MIN_US_HITS:
            r["grade"] = "S"
            r["s_rule"] = "category_desk_us_evidence"
            r["desk_note"] = (f"{DESK_NAME[desk]} 기준: 점수 {r.get('shopify_score')} ≥ {DESK_MIN_SCORE[desk]}, "
                              f"미국 실판매 유사 {r.get('us_market_hits')}건")


def desk_quotas(limit: int, kept) -> dict:
    counts = {d: sum(1 for r in kept if r.get("desk") == d) for d in DESK_NAME}
    quota = {d: min(DESK_QUOTA.get(d, 0), counts[d]) for d in DESK_QUOTA}
    quota["skincare"] = limit  # 스킨케어 정원은 줄이지 않는다
    return quota


def s_slot_limit(rows, s_ratio=0.06):
    """S 정원. assign_grades 와 같은 식을 한 군데서만 계산한다.

    대시보드가 "몇 자리 남았나"를 보여주려면 이 숫자가 필요한데,
    같은 식을 JS 에 또 적어두면 한쪽만 고친 날 조용히 엇갈린다.
    산출물에 실어서 내보낸다.
    """
    return max(4, min(10, round(len(rows) * s_ratio)))


def assign_grades(rows, s_ratio=0.06):
    desk_promote(rows)
    cands = [r for r in rows if r.get("grade") == "S"]
    if not cands:
        return
    cands.sort(key=lambda r: (-r["shopify_score"], -(r.get("us_market_hits") or 0)))
    seen, kept = {}, []
    for r in cands:
        # 동일 제형 상위 2개 제한은 전담팀 안에서만 센다(메이크업 크림 브라이트너가 스킨케어 크림에 밀리지 않게).
        f = (r.get("desk") or "", _form(r["name"]))
        if seen.get(f, 0) >= 2:
            r["grade"] = "A"
            r["downgrade_reason"] = "동일 제형(%s) 상위 2개에 밀림" % f[1]
            r["s_rule"] = "form_cap"
            continue
        # 글로벌 매칭이 이미 강하면 US 목록 0건이어도 유지
        # (OliveYoung 영문명에 한글 성분이 동시에 안 나오는 경우)
        strong_gate = r.get("s_rule") in {
            "ingredient+form", "multi_token", "strong_ingredient", "strong_form",
        }
        if not (r.get("us_market_hits") or 0) and not strong_gate:
            r["grade"] = "A"
            r["downgrade_reason"] = "미국 실판매 목록에서 유사 상품을 찾지 못함"
            r["s_rule"] = "no_us_listing"
            continue
        seen[f] = seen.get(f, 0) + 1
        kept.append(r)
    limit = s_slot_limit(rows, s_ratio)
    # 카테고리 전담팀별 정원 (2026-10-11). 전담팀 밖(헤어 등) 상품은 스킨케어 정원을 같이 쓴다.
    quota = desk_quotas(limit, kept)
    used = {d: 0 for d in quota}
    winners = []
    for r in kept:
        d = r.get("desk")
        if d not in quota:
            # 사용자 지시 2026-10-11: 전담팀(스킨케어·메이크업·바디) 범위 밖(마스크팩·클렌징·헤어 등)은 S 로 두지 않는다.
            r["grade"] = "A"
            r["downgrade_reason"] = "전담팀 범위 밖 카테고리"
            r["s_rule"] = "no_category_desk"
            continue
        if used[d] < quota[d]:
            used[d] += 1
            winners.append(r)
        else:
            r["grade"] = "A"
            r["downgrade_reason"] = "%s 정원 %d개 밖" % (DESK_NAME.get(d, d), quota[d])
            r["s_rule"] = "rank_cap"
    for i, r in enumerate(winners, 1):
        r["s_rank"] = i


def main() -> int:
    data = load_json(PRODUCTS, {}) or {}
    products = data.get("products") or []
    if not products:
        print(f"ERROR: no products in {PRODUCTS}")
        return 1

    cp_registry = load_cp_registry()
    if not cp_registry:
        print("WARN: product_master.json 없거나 비어 있음 — canonical_product_id 생략")

    # 이미지 URL 유실 방지: 이전 S추천·products 양쪽에서 보강
    prev_s = load_json(OUT_S, {}) or {}
    img_by_no, img_by_name = {}, {}
    for r in (prev_s.get("recommendations") or []):
        if r.get("pd_no") and r.get("image_url"):
            img_by_no[str(r["pd_no"])] = r["image_url"]
        if r.get("name") and r.get("image_url"):
            img_by_name[(r.get("name") or "").strip()] = r["image_url"]
    for p in products:
        if not isinstance(p, dict):
            continue
        if not p.get("image_url"):
            p["image_url"] = (
                img_by_no.get(str(p.get("pd_no") or ""))
                or img_by_name.get((p.get("name") or "").strip())
                or ""
            )
        elif p.get("pd_no"):
            img_by_no[str(p["pd_no"])] = p["image_url"]
        if p.get("name") and p.get("image_url"):
            img_by_name[(p.get("name") or "").strip()] = p["image_url"]

    dashboard = load_json(DASHBOARD, {}) or {}
    signals = extract_signals(provenanced_channels(dashboard))
    scored = [score_one(p, signals) for p in products]
    for s in scored:
        s["canonical_product_id"] = cp_registry.get(str(s.get("pd_no") or ""))
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
        # S 정원과 빈자리. 대시보드가 카탈로그 여유를 보여주는 데 쓴다.
        "s_slot_limit": s_slot_limit(scored),
        "s_slot_open": max(0, s_slot_limit(scored) - sum(1 for x in scored if x["grade"] == "S" and x.get("desk") not in DESK_QUOTA)),
        "category_desks": {d: {"name": DESK_NAME[d], "buckets": CATEGORY_DESKS.get(d, []),
                               "s_quota": DESK_QUOTA.get(d, s_slot_limit(scored)),
                               "s_count": sum(1 for x in scored if x["grade"] == "S" and x.get("desk") == d)}
                           for d in DESK_NAME},
        "category_avg_score": cat_avg,
        "global_channels_used": list(MATCH_CHANNELS),
        "global_demand_signals": len(signals),
        "products_with_global_match": matched,
        "canonical": "shopify_s_recommendations.json",
        "priority_note": "S등급만 Shopify 1차 등록. 펫/노이즈/약한 단일토큰 제외.",
        "scoring_model": {
            "logic": "s_gate_v2",
            "formula": "category+rating+reviews+price+keyword+us_fit − non_core; S=qualify_s()",
            "lexicon_size": len(LEXICON),
            "channel_weights": CHANNEL_WEIGHT,
            "s_rules": [
                "non_core 하드 제외 (펫·구강·잡화·논슬립)",
                "core 카테고리만",
                "점수 >= 82",
                "글로벌 매칭 필수",
                "약한 단일 토큰 S 불가",
                "성분+제형 또는 토큰 2개+유사도 0.55 또는 성분 유사도 0.70",
                "제형당 최대 2개, 전체 상한",
            ],
        },
        "top_recommendations": [x for x in recs if x["grade"] == "S"],
        "all_scored": scored,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    s_list = [x for x in recs if x["grade"] == "S"]
    s_payload = {
        "generated_at": result["generated_at"],
        "source": "score_shopify_demand.py",
        "canonical": True,
        "rule": "qualify_s v2 — core + ingredient/form match + no pet/noise",
        "count": len(s_list),
        "priority_note": "Shopify 1차 등록 후보. 이 파일만 정본으로 사용.",
        "recommendations": [
            {
                "rank": i,
                "canonical_product_id": cp_registry.get(str(x.get("pd_no") or "")),
                "pd_no": x.get("pd_no"),
                "name": x.get("name"),
                "bucket": x.get("bucket"),
                "desk": x.get("desk") or "skincare",
                "price_krw": x.get("price_krw"),
                "shopify_score": x.get("shopify_score"),
                "grade": "S",
                "s_rule": x.get("s_rule"),
                "url": x.get("url"),
                "image_url": (
                    x.get("image_url")
                    or img_by_no.get(str(x.get("pd_no") or ""))
                    or img_by_name.get((x.get("name") or "").strip())
                    or ""
                ),
                "recommend_reason": x.get("recommend_reason"),
                "matched_global": x.get("best_global_match"),
                # 등록 가능 여부는 뒤의 build_listing_gate.py만 판정한다.
                "registerable": None,
                "registerable_source": "pending_listing_gate",
            }
            for i, x in enumerate(s_list, 1)
        ],
    }
    OUT_S.write_text(json.dumps(s_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rejected = [
        {
            "canonical_product_id": cp_registry.get(str(x.get("pd_no") or "")),
            "pd_no": x.get("pd_no"),
            "name": x.get("name"),
            "bucket": x.get("bucket"),
            "shopify_score": x.get("shopify_score"),
            "s_rule": x.get("s_rule"),
            "downgrade_reason": x.get("downgrade_reason"),
            "recommend_reason": x.get("recommend_reason"),
        }
        for x in scored
        if x.get("s_rule") in {
            "non_core", "weak_solo_token", "match_too_weak", "non_core_bucket",
            "form_cap", "no_us_listing", "rank_cap", "no_global_match",
        } and x.get("shopify_score", 0) >= 70
    ]
    OUT_REJECT.write_text(json.dumps({
        "generated_at": result["generated_at"],
        "note": "점수는 높았으나 S에서 탈락한 후보. 등록하지 말 것.",
        "count": len(rejected),
        "items": rejected[:40],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Done {len(scored)} → {OUT}")
    print("Grades:", by_grade, "| matched:", matched, "| signals:", len(signals))
    # S JSON 이미지 커버리지 검증 (자동화 성공 조건)
    s_written = load_json(OUT_S, {}) or {}
    s_recs = s_written.get("recommendations") or []
    with_img = sum(1 for r in s_recs if (r.get("image_url") or "").strip())
    missing = [r.get("name") for r in s_recs if not (r.get("image_url") or "").strip()]
    print(f"S-list {len(s_list)} → {OUT_S} | image_url {with_img}/{len(s_recs)}")
    if missing:
        print("WARN image_url missing:", "; ".join((n or "")[:30] for n in missing[:8]))
    if s_recs and with_img == 0:
        print("ERROR: S recommendations have zero image_url — check products.json og:image")
        return 2
    for i, s in enumerate(s_list, 1):
        m = s.get("best_global_match") or {}
        print(f"  {i}. {s['shopify_score']:3d} {s['name'][:36]} | {m.get('global_product','-')[:28]} [{','.join((m.get('matched_tokens') or [])[:3])}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
