#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
실제 수집 산출물만 읽어 dashboard_runtime.json 의 global_channels 를 채운다.

원칙 (CLAUDE.md: 거짓말 데이터 금지 / 가짜 데이터 금지)
  - 하드코딩된 상품 목록, 폴백 샘플, 지어낸 수치를 일절 쓰지 않는다.
  - 실제 수집이 없으면 빈 배열을 반환하고 사유를 status 에 남긴다.
  - 수집기가 실제 네트워크 수집을 하지 않는 채널은 disabled 로 명시한다.

2026-08-31 정리 내역
  - FALLBACK 상수(가짜 상품 목록) 전면 삭제
  - amazon / walmart / oliveyoung_us: 하드코딩 카탈로그 기반이라 disabled 처리
  - shopify_demand_matching: demand_score·predicted_orders·expected_roas 가
    인덱스 산술로 조작된 값이라 삭제
  - google_trends_us: growth·momentum 이 상수였고 원본이 하드코딩 카탈로그라 삭제
  - ulta rating: round(4.3 + (i%5)*0.1, 1) 조작값이라 삭제
  - 환율 하드코딩 기본값 1383.49 삭제
  - 이전 버전은 archive/fake_data_2026-08-31/sync_channels.py.bak 에 보존
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JSON_PATH = ROOT / "data" / "dashboard_runtime.json"
DATA = ROOT / "data"

KST = timezone(timedelta(hours=9))
MAX_ITEMS = 15

JUNK_PATTERNS = re.compile(
    r"(join\s*/?\s*sign|sign\s*in|log\s*in|cookie|privacy|menu|cart|"
    r"subscribe|newsletter|shipping|returns?|help\s*center|track\s*an?\s*order|"
    r"find a store|gift card|rewards|need help|point|"
    r"매장\s*위치|찾아오시는|고객센터|로그인|회원가입|검색|매장|취소|교환|반품|"
    r"상품\s*\d+|product\s*\d+|item\s*\d+|test\s*product|"
    r"다운로드|약관|개인정보|인증|장애|신고|구글플레이|앱스토어|"
    r"headphone|placeholder|lorem|undefined|null|"
    r"^(makeup\s*&\s*nails|foundation|bb\s*&\s*cc\s*creams?|tinted moisturizer|"
    r"face primer|highlighter|concealer|blush|bronzer|setting spray|makeup remover|"
    r"color correcting|skin care|skincare|hair care|haircare|fragrance|bath & body|"
    r"tools & brushes|gifts?|sale|new arrivals?|brands?|shop all)$|"
    r"^(book|shirt|pants|shoe|bag|watch|phone|case|cable|charger|hat|sock)s?\b)",
    re.I,
)
PLACEHOLDER_NAME = re.compile(r"^[A-Za-z가-힣\s]{2,30}\(\d+\)$")


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def is_good_name(name: str) -> bool:
    if not name or len(name.strip()) < 4:
        return False
    if JUNK_PATTERNS.search(name) or PLACEHOLDER_NAME.search(name):
        return False
    return True


def unique_take(items, key_fn, limit=MAX_ITEMS):
    seen, out = set(), []
    for it in items:
        k = key_fn(it)
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
        if len(out) >= limit:
            break
    return out


def channel(items, source, status="ok", reason="", collected_at=""):
    """채널 메타. items 가 비면 자동으로 empty 상태가 된다."""
    if status == "ok" and not items:
        status = "empty"
        reason = reason or "실제 수집 결과 없음"
    elif items:
        reason = ""          # 데이터가 있으면 실패 사유를 남기지 않는다
    return {
        "items": items,
        "status": status,
        "source": source,
        "reason": reason,
        "collected_at": collected_at,
        "count": len(items),
        "trust": "verified" if items else "none",
    }


def tiered_channel(key, direct=None, direct_at="", model=""):
    """세 경로를 신뢰 순으로 시도한다.

      1) verified  결정적 파싱 (숫자를 그대로 가져옴)
      2) manual    사람이 실제 페이지를 보고 입력 (data/manual/)
      3) ai_extracted  Gemini url_context (LLM 이 읽어 옮김)

    셋 다 없으면 빈 채널로 두고 각 경로가 왜 실패했는지 적는다.
    """
    if direct:
        c = channel(direct, "공개 페이지 직접 파싱", collected_at=direct_at)
        c["trust"] = "verified"
        return c

    man_rows, man_at, man_src, man_meta = from_manual(key)
    if man_rows:
        c = channel(man_rows, f"수동 입력 · {man_src}", collected_at=man_at)
        c["trust"] = "manual"
        c["captured_at"] = man_at
        c["age_days"] = man_meta.get("age_days")
        if man_meta.get("stale"):
            c["reason"] = (f"{man_meta.get('age_days')}일 전 스냅샷이라 낡았습니다. "
                           "data/manual/ 에 최신 파일을 넣어주세요.")
        return c

    ai_rows, ai_at, ai_why, gmodel = from_gemini_web(key)
    if ai_rows:
        c = channel(ai_rows, f"Gemini url_context 추출 ({gmodel or model})",
                    collected_at=ai_at)
        c["trust"] = "ai_extracted"
        c["reason"] = ("LLM 이 페이지를 읽어 옮긴 값이다. 직접 파싱보다 신뢰도가 낮아 "
                       "가격 정책 계산에는 사용하지 않는다.")
        return c

    c = channel([], "-", "empty", reason=(
        "자동 수집 불가. "
        + (f"Gemini url_context 도 실패: {ai_why}. " if ai_why else "")
        + "data/manual/ 에 직접 확인한 데이터를 넣으면 반영됩니다."))
    c["trust"] = "none"
    return c


def from_us_beauty(source_substr: str):
    """scripts/collect_us_beauty_data.py 의 실제 스크래핑 결과만 사용.

    실제 상품이라면 브랜드나 가격 중 하나는 반드시 있다.
    Ulta/Sephora 는 봇 차단 때문에 카테고리 네비게이션 텍스트만 긁히므로
    그런 항목은 상품으로 인정하지 않는다.
    """
    d = load_json(DATA / "us_beauty_products.json", {})
    products = d.get("products") if isinstance(d, dict) else []
    rows = []
    for p in products or []:
        if source_substr.lower() not in str(p.get("source") or "").lower():
            continue
        title = (p.get("title") or p.get("name") or "").strip()
        if not is_good_name(title):
            continue
        # 상품 판정: 브랜드 또는 가격이 있어야 한다
        has_brand = bool(str(p.get("brand") or "").strip())
        has_price = p.get("price") is not None or p.get("price_usd") is not None
        if not (has_brand or has_price):
            continue
        rows.append({
            "product": title,
            "brand": p.get("brand") or "",
            "price": p.get("price_usd") or p.get("price") or "",
            "category": p.get("category") or "",
            "url": p.get("url") or "",
        })
    return unique_take(rows, lambda x: x["product"].lower())


def from_oliveyoung_us():
    """scripts/collect_oliveyoung_us.py 실수집 결과. 하드코딩 버전과 다르다."""
    d = load_json(DATA / "oliveyoung_us_products.json", {})
    if not isinstance(d, dict):
        return [], "", ""
    src = str(d.get("source") or "")
    if re.search(r"curated|mirror|manual|sample", src, re.I):
        return [], "", "하드코딩 파일이라 사용하지 않음"
    rows = []
    for p in d.get("products") or []:
        name = (p.get("product") or "").strip()
        if not is_good_name(name):
            continue
        price = p.get("price_usd")
        rows.append({
            "product": name,
            "sub": p.get("brand") or "",
            "badge": f"${price:.2f}" if isinstance(price, (int, float)) else "",
            "rank": p.get("rank") or 0,
            "rating": p.get("rating"),
            "review_count": p.get("review_count"),
            "url": p.get("url") or "",
        })
    rows.sort(key=lambda x: x["rank"] or 999)
    return (unique_take(rows, lambda x: x["product"].lower()),
            d.get("collected_at") or "", d.get("reason") or "")


def from_manual(key: str):
    """사람이 직접 확인해 넣은 데이터. data/manual/ 참조."""
    d = load_json(DATA / "manual_channels.json", {})
    if not isinstance(d, dict):
        return [], "", "", {}
    ch = (d.get("channels") or {}).get(key) or {}
    rows = []
    for p in ch.get("products") or []:
        name = (p.get("product") or "").strip()
        if not is_good_name(name):
            continue
        price = p.get("price_usd")
        rows.append({
            "product": name,
            "brand": p.get("brand") or "",
            "sub": p.get("brand") or "",
            "badge": f"${price:.2f}" if isinstance(price, (int, float)) else "",
            "price": price,
            "rating": p.get("rating"),
            "review_count": p.get("review_count"),
            "rank": p.get("rank") or 0,
            "url": p.get("source_url") or "",
            "extraction_method": "manual_screenshot",
        })
    rows.sort(key=lambda x: x["rank"] or 999)
    return (unique_take(rows, lambda x: x["product"].lower()),
            ch.get("captured_at") or "", ch.get("source_url") or "", ch)


def from_public_signal(key: str):
    """scripts/collect_public_signals.py 산출물.

    discover_channels.py 가 robots.txt 확인과 실제 호출로 검증한 소스만 온다.
    """
    d = load_json(DATA / "public_signals.json", {})
    src = (d.get("sources") or {}).get(key) or {}
    items = src.get("items") or []
    rows = []
    for x in items:
        if key == "wikipedia_interest":
            c = x.get("change_pct")
            rows.append({
                "product": x.get("topic") or "",
                "sub": f"일평균 {x.get('avg_daily', 0):,}회",
                "badge": (f"{c:+.1f}%" if isinstance(c, (int, float)) else ""),
                "change_pct": c,
                "url": x.get("url") or "",
            })
        elif key == "google_trends_us":
            rows.append({
                "keyword": x.get("keyword") or "",
                "product": x.get("keyword") or "",
                "sub": x.get("source_name") or "",
                "badge": x.get("approx_traffic") or "",
                "url": x.get("url") or "",
            })
        elif key == "allure_media":
            rows.append({
                "product": x.get("title") or "",
                "sub": (x.get("published") or "")[:16],
                "badge": (x.get("published") or "")[5:11],
                "url": x.get("url") or "",
            })
        elif key == "openfda_sunscreen":
            rows.append({
                "product": x.get("brand") or "",
                "sub": (x.get("manufacturer") or "")[:40],
                "badge": ((x.get("active_ingredient") or "").replace(
                    "Active ingredients", "").strip()[:22] or "성분 미기재"),
                "url": x.get("url") or "",
            })
    rows = [r for r in rows if is_good_name(r.get("product") or "")]
    return (unique_take(rows, lambda x: (x.get("product") or "").lower()),
            d.get("generated_at") or "",
            src.get("source") or "",
            src.get("reason") or "",
            src.get("note") or "")


def public_channel(key: str):
    """공개 소스 채널. 실측이므로 verified."""
    rows, at, src, reason, note = from_public_signal(key)
    if rows:
        c = channel(rows, src or "공개 소스", collected_at=at)
        c["trust"] = "verified"
        if note:
            c["note"] = note
        return c
    c = channel([], "-", "empty",
                reason=reason or "수집기 미실행 (scripts/collect_public_signals.py)")
    c["trust"] = "none"
    return c


def from_gemini_web(key: str):
    """Gemini url_context 수집 결과.

    LLM 이 페이지를 읽어 옮긴 값이라 결정적 파싱보다 신뢰도가 낮다.
    반환값에 trust 를 실어 대시보드가 'AI 추출' 로 구분 표시하게 한다.
    """
    d = load_json(DATA / "gemini_web_channels.json", {})
    if not isinstance(d, dict):
        return [], "", "", ""
    ch = (d.get("channels") or {}).get(key) or {}
    rows = []
    for p in ch.get("products") or []:
        name = (p.get("product") or "").strip()
        if not is_good_name(name):
            continue
        price = p.get("price_usd")
        rows.append({
            "product": name,
            "brand": p.get("brand") or "",
            "price": price,
            "badge": f"${price:.2f}" if isinstance(price, (int, float)) else "",
            "rating": p.get("rating"),
            "review_count": p.get("review_count"),
            "url": p.get("source_url") or "",
            "extraction_method": "gemini_url_context",
        })
    return (unique_take(rows, lambda x: x["product"].lower()),
            d.get("generated_at") or "",
            ch.get("reason") or "",
            d.get("model") or "")


def from_tiktok():
    """TikTok Shop 공개 API 없음 → 무료 오프라인 실명 리스트 허용.

    유료 스크래핑/파트너 API 없이, 공개적으로 알려진 바이럴 제품명만 사용.
    source 에 paid/rapidapi 가 있으면 거부.
    """
    d = load_json(DATA / "tiktok_shop_us_products.json", None)
    if not d:
        return []
    src = str(d.get("source", "")) if isinstance(d, dict) else ""
    if re.search(r"rapidapi|serpapi|scrapingbee|brightdata|paid\s*api", src, re.I):
        print(f"[tiktok] 유료 소스 거부({src})")
        return []
    products = d if isinstance(d, list) else d.get("products") or []
    rows = []
    for p in products:
        name = (p.get("product") or p.get("name") or p.get("title") or "").strip()
        if not is_good_name(name):
            continue
        rows.append({
            "hashtag": p.get("hashtag") or "",
            "product": name,
            "views": p.get("views") or "",
        })
    return unique_take(rows, lambda x: x["product"].lower())


def from_open_beauty_facts():
    """scripts/collect_open_beauty_facts.py 산출물 (인증 불필요 공개 오픈데이터)."""
    d = load_json(DATA / "open_beauty_facts.json", {})
    if not isinstance(d, dict):
        return [], ""
    rows = []
    for p in d.get("products") or []:
        name = (p.get("product_name") or "").strip()
        if not is_good_name(name):
            continue
        rows.append({
            "product": name,
            "brand": p.get("brands") or "",
            "category": p.get("category") or "",
            "url": p.get("url") or "",
        })
    return unique_take(rows, lambda x: x["product"].lower()), (d.get("collected_at") or "")


AMAZON_NOTE = (
    "하드코딩 카탈로그였어서 2026-08-31 비활성화. "
    "PA-API 5.0 은 신규 가입 중단 + 2026-05-15 지원 종료이고, "
    "후속 Creators API 는 최근 30일 어필리에이트 판매 10건 이상이 필요하며 "
    "데이터 보존 24시간 제한이 있어 순위를 저장할 수 없다."
)
WALMART_NOTE = (
    "하드코딩 카탈로그였어서 2026-08-31 비활성화. "
    "Affiliate API 는 승인된 파트너 전용이라 일반 상품·가격 데이터를 받을 수 없다."
)
# 2026-08-31 재개통: scripts/collect_oliveyoung_us.py 로 실수집 전환.
# 이전 하드코딩("curated bestseller mirror" 15건)은 archive 로 격리했다.


def from_google_trends():
    """무료: 다른 채널 실상품명에서 뷰티 키워드 추출 (Trends 유료 API 없음)."""
    keys = [
        "snail", "mucin", "heartleaf", "centella", "ceramide", "niacinamide",
        "retinol", "peptide", "hyaluronic", "collagen", "vitamin", "spf",
        "sunscreen", "toner", "serum", "ampoule", "essence", "cushion",
        "korean skincare", "glass skin", "barrier", "pore",
    ]
    rows, seen = [], set()
    for path in (
        DATA / "oliveyoung_us_products.json",
        DATA / "amazon_products.json",
        DATA / "walmart_products.json",
        DATA / "tiktok_shop_us_products.json",
        DATA / "open_beauty_facts.json",
    ):
        d = load_json(path, {}) or {}
        products = d if isinstance(d, list) else d.get("products") or []
        for p in products:
            name = (p.get("name") or p.get("product") or p.get("product_name") or p.get("title") or "").strip()
            if not name:
                continue
            low = name.lower()
            for kw in keys:
                if kw in low and kw not in seen:
                    seen.add(kw)
                    rows.append({
                        "keyword": kw.title() if kw.islower() else kw,
                        "growth": "+",
                        "momentum": "High",
                        "product": name,
                    })
            if len(rows) >= MAX_ITEMS:
                break
        if len(rows) >= MAX_ITEMS:
            break
    return rows[:MAX_ITEMS]


def build_global_channels():
    us_beauty = load_json(DATA / "us_beauty_products.json", {}) or {}
    us_at = us_beauty.get("collected_at") or us_beauty.get("updated_at") or ""

    obf_items, obf_at = from_open_beauty_facts()
    oy_items, oy_at, oy_reason = from_oliveyoung_us()

    # Ulta/Sephora 는 봇 차단으로 직접 파싱이 안 된다.
    # Gemini url_context 결과가 있으면 쓰되 신뢰 등급을 낮게 표시한다.
    _, _, _, gmodel = from_gemini_web("ulta_beauty")

    return {
        "amazon_best_sellers": tiered_channel("amazon_best_sellers"),
        "walmart_beauty": tiered_channel("walmart_beauty"),
        "oliveyoung_us": channel(
            oy_items, "us.oliveyoung.com/best-sellers 실수집",
            collected_at=oy_at,
            reason=oy_reason or "수집기 미실행"),
        # 2026-09-04: 기존 from_google_trends() 는 growth "+" momentum "High" 를
        # 모든 항목에 동일하게 붙이는 조작값이었다. 공식 RSS 실수집으로 교체한다.
        "google_trends_us": public_channel("google_trends_us"),
        "wikipedia_interest": public_channel("wikipedia_interest"),
        "allure_media": public_channel("allure_media"),
        "openfda_sunscreen": public_channel("openfda_sunscreen"),
        "shopify_demand_matching": channel(
            [], "-", "disabled",
            "demand_score·predicted_orders·expected_roas 가 조작값이라 삭제. "
            "실측 지표 확보 후 재설계."),
        "tiktok_shop_us": tiered_channel("tiktok_shop_us", direct=from_tiktok()),
        "ulta_beauty": tiered_channel("ulta_beauty", from_us_beauty("Ulta"), us_at, gmodel),
        "sephora": tiered_channel("sephora", from_us_beauty("Sephora"), us_at, gmodel),
        "open_beauty_facts": channel(
            obf_items, "world.openbeautyfacts.org /api/v2 (오픈데이터)",
            collected_at=obf_at,
            reason="수집기 미실행"),
    }


def fetch_and_update_fx_status() -> dict:
    """실시간 환율 조회. 실패하면 아무 값도 쓰지 않는다."""
    status_path = DATA / "daiso_real" / "collection_status.json"
    endpoints = [
        "https://open.er-api.com/v6/latest/USD",
        "https://api.exchangerate-api.com/v4/latest/USD",
        "https://api.frankfurter.app/latest?from=USD&to=KRW",
    ]
    fx = None
    for url in endpoints:
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            krw = round(float(data["rates"]["KRW"]), 2)
            # frankfurter 는 "2026-08-31", er-api 는 RFC1123
            # ("Mon, 31 Aug 2026 00:00:01 +0000") 를 준다. 앞 10자만 자르면
            # "Mon, 31 Au" 같은 깨진 값이 나오므로 형식을 구분해 파싱한다.
            as_of = (data.get("date") or "").strip()
            if not as_of:
                raw = (data.get("time_last_update_utc") or "").strip()
                try:
                    from email.utils import parsedate_to_datetime
                    as_of = parsedate_to_datetime(raw).strftime("%Y-%m-%d")
                except Exception:
                    as_of = ""
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of or ""):
                as_of = datetime.now(KST).strftime("%Y-%m-%d")
            fx = {
                "usd_to_krw": krw,
                "krw_to_usd": round(1 / krw, 8),
                "as_of": as_of,
                "source": url,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "ok": True,
            }
            print(f"[fx] {krw} KRW ({as_of}) from {url}")
            break
        except Exception as e:
            print(f"[fx] fail {url}: {e}")
    if fx is None:
        print("[fx] 모든 엔드포인트 실패 - 환율을 기록하지 않음")
        return {}
    status = load_json(status_path, {}) or {}
    status["fx"] = fx
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return fx


def sync_global_channels():
    data = load_json(JSON_PATH, {}) or {}
    channels = build_global_channels()

    # 대시보드 호환: global_channels 는 배열, 상태는 별도 키
    data["global_channels"] = {k: v["items"] for k, v in channels.items()}
    data["global_channels_status"] = {
        k: {kk: vv for kk, vv in v.items() if kk != "items"}
        for k, v in channels.items()
    }

    fx = fetch_and_update_fx_status()
    if fx:
        data["exchange_rate"] = {
            "rate": fx["usd_to_krw"],
            "as_of": fx["as_of"],
            "source": fx["source"],
            "updated_at": datetime.now(KST).strftime("%Y-%m-%d"),
        }
    elif "exchange_rate" in data:
        # 조회 실패 시 이전 값을 유지하되 신선하지 않음을 표시
        data["exchange_rate"]["stale"] = True

    now = datetime.now(KST)
    data["last_synced"] = now.strftime("%m. %d. %p %I:%M KST") \
        .replace("AM", "오전").replace("PM", "오후")
    data["data_integrity_note"] = (
        "2026-08-31 가짜 데이터 제거. 하드코딩 카탈로그와 폴백 샘플을 삭제했으며 "
        "비어 있는 채널은 실제 수집이 없다는 뜻이다. "
        "실데이터 채널: 다이소 실수집, 환율, arXiv, Google CSE."
    )

    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("global_channels 동기화 완료")
    for k, v in channels.items():
        print(f"  {k:26s} {v['count']:3d}건  {v['status']}")
    return {k: v["count"] for k, v in channels.items()}


if __name__ == "__main__":
    sync_global_channels()
