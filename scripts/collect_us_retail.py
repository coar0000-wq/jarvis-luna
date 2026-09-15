#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""미국 리테일 4곳 베스트셀러 실수집기 (Amazon / Walmart / Ulta / Sephora).

왜 만들었나
-----------
이 네 채널은 2026-09-15 까지 손입력 스냅샷이었다. `가동 7/12 · 낡음 4건`
의 그 4건이다. manual_channels.json 에 `source_url_given: false` 로 적혀
있었고 도메인 루트만 남아 있어 무엇을 보고 적었는지 되짚을 수 없었다.

더 나쁜 것이 둘 있었다.

  scripts/collect_amazon_products.py   이름만 수집기고 하드코딩 8건
  scripts/collect_walmart_products.py  같음

둘 다 build() 안에 상품명과 가격을 박아두고 "✅ Amazon : 8 products" 를
찍었다. archive/fake_data_2026-08-31/ 에 같은 성격의 스크립트가 이미
격리돼 있는데 이 둘은 남아 있었다. 이 파일이 그 둘을 대체한다.

sync_channels.py 의 from_us_beauty() 주석에도 이렇게 적혀 있었다.

    "지금 이 파일을 만드는 수집기는 없어서 이 경로는 항상 0건이다.
     지어낸 값을 채우느니 0건이 낫다."

그 수집기가 이 파일이다.

봇 차단 문제
------------
HTTP 요청으로는 네 곳 다 상품이 안 나온다. sync_channels.py 주석의
"Ulta/Sephora 는 봇 차단 때문에 카테고리 네비게이션 텍스트만 긁힌다" 가
그것이고, 실제로 data/us_beauty_products.json 첫 항목 title 이
"Join / Sign in" 이었다. 그래서 실제 브라우저(Playwright chromium)로 받는다.
scripts/daiso/collect_gosi_alt.py 가 쓰는 방식과 같다.

robots.txt (2026-09-15 확인)
---------------------------
  amazon.com    /gp/bestsellers/ 관련 Disallow 없음.
                (Disallow 인 /gp/aw/shoppingAids/ 는 건드리지 않는다)
  walmart.com   /browse/ 관련 Disallow 없음
  ulta.com      Disallow 는 /community/groups 둘뿐. /shop/ 허용
  sephora.com   /browse/ 는 Disallow 다. 그래서 /browse/ 를 쓰지 않고
                /beauty/beauty-best-sellers 만 받는다.

경로 메모 (실측해서 고른 것)
---------------------------
  ulta     /shop/bestsellers 는 warm session 으로도 "Our Apologies" 만
           돌아온다. /shop/skin-care 는 정상이라 그것을 쓴다.
  sephora  /beauty/bestsellers 는 홈으로 리다이렉트된다.
           실제 경로는 /beauty/beauty-best-sellers 다.

원칙 (CLAUDE.md: 거짓말 데이터 금지 / 가짜 데이터 금지)
  - 못 받으면 빈 목록과 사유를 남긴다. 지어내지 않는다.
  - 각 항목에 상세 URL 을 남겨 사람이 열어볼 수 있게 한다.
  - 스폰서 광고는 상품으로 세지 않는다. 베스트셀러 벤치마크가 아니다.
  - 실패 시 이전 성공분을 물려받되, 우리 수집기가 남긴 파일일 때만 한다.

사용
  pip install playwright && playwright install chromium
  python -u scripts/collect_us_retail.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

OUT_AMAZON = DATA / "amazon_products.json"
OUT_WALMART = DATA / "walmart_products.json"
OUT_US_BEAUTY = DATA / "us_beauty_products.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

NAV_TIMEOUT = 60000
SETTLE_MS = 6000          # 클라이언트 렌더링이 끝날 때까지
SCROLL_STEPS = 3          # 지연 로딩 유도
MAX_ITEMS = 60


# ----------------------------------------------------------------------
# 사이트별 추출기
#
# 브라우저 안에서 도는 JS 다. 파이썬에서 셀렉터를 추측하지 않고
# 각 사이트가 실제로 들고 있는 표식을 쓴다.
#
#   amazon   [id^=gridItemRoot] · a[href*="/dp/"]
#   walmart  [data-item-id] · [data-automation-id=product-title|product-price]
#   ulta     a[href*="/p/"] 의 카드 컨테이너 텍스트
#   sephora  a[href*="/product/"] · [data-at=review_count] · 별점은 부모 aria-label
# ----------------------------------------------------------------------

JS_AMAZON = r"""
() => {
  const rows = [];
  const seen = new Set();
  document.querySelectorAll('[id^="gridItemRoot"], .zg-grid-general-faceout').forEach(el => {
    const a = el.querySelector('a[href*="/dp/"]');
    if (!a) return;
    const url = a.href.split('?')[0];
    const asin = (url.match(/\/dp\/([A-Z0-9]{10})/) || [])[1] || '';
    if (!asin || seen.has(asin)) return;
    const lines = (el.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
    const rank = ((lines.find(s => /^#\d+$/.test(s)) || '').match(/\d+/) || [])[0];
    const priceTxt = lines.find(s => /^\$[\d,]+\.?\d*$/.test(s)) || '';
    const ratingTxt = lines.find(s => /out of 5 stars/i.test(s)) || '';
    const revTxt = lines.find(s => /^[\d,]+$/.test(s) && s.replace(/,/g,'').length > 1) || '';
    const name = lines.find(s => s.length > 12
      && !/^\$|out of 5|^#\d|^[\d,]+$/.test(s)) || '';
    if (!name) return;
    seen.add(asin);
    rows.push({
      rank: rank ? parseInt(rank, 10) : null,
      name: name,
      asin: asin,
      price_usd: priceTxt ? parseFloat(priceTxt.replace(/[$,]/g, '')) : null,
      rating: ratingTxt ? parseFloat((ratingTxt.match(/[\d.]+/) || [])[0]) : null,
      review_count: revTxt ? parseInt(revTxt.replace(/,/g, ''), 10) : null,
      url: url,
    });
  });
  return { rows, skipped_sponsored: 0 };
}
"""

# Walmart 가격 메모
#
#   여러 옵션이 있는 상품은 product-price 블록이 비어 있고 본문이 이렇다.
#     "$ | 7 | 97 | $61.31/oz | Options from $7.97 - $31.88"
#   그냥 첫 번째 $를 잡으면 $61.31 이 나온다. 그건 온스당 단가다.
#   립스틱 하나가 $61.31 로 박히면 손익분기 계산이 통째로 틀어진다.
#   단위당 단가($x/oz)를 먼저 지우고 판매가를 찾는다.
#
# URL 메모
#   슬러그가 상품명과 다를 때가 있다(classType=VARIANT).
#   Walmart 의 변형 상품 주소 방식이라 정본은 item_id 다.
JS_WALMART = r"""
() => {
  const rows = [];
  const seen = new Set();
  let sponsored = 0, noUrl = 0;
  const priceOf = (raw) => {
    // $61.31/oz 같은 단위당 단가를 먼저 지운다. 상품가가 아니다.
    const t = raw.replace(/\$[\d,]+\.?\d*\s*\/\s*[\w.]+/g, ' ');
    const m = t.match(/current price\s*\$([\d,]+\.\d{2})/i)
           || t.match(/Options from\s*\$([\d,]+\.\d{2})/i)
           || t.match(/Now\s*\$([\d,]+\.\d{2})/i)
           || t.match(/\$([\d,]+\.\d{2})/);
    return m ? parseFloat(m[1].replace(/,/g, '')) : null;
  };
  document.querySelectorAll('[data-item-id]').forEach(el => {
    const txt = el.innerText || '';
    // 스폰서 광고는 베스트셀러가 아니다. 세지 않는다.
    if (/\bSponsored\b/i.test(txt)) { sponsored++; return; }
    const titleEl = el.querySelector('[data-automation-id="product-title"]');
    const name = (titleEl?.innerText || '').replace(/\s+/g, ' ').trim();
    if (!name || name.length < 5) return;
    const id = el.getAttribute('data-item-id');
    if (!id || seen.has(id)) return;
    // /sp/track 은 광고 추적 링크다. 실제 상품 주소만 쓴다.
    const a = [...el.querySelectorAll('a[href*="/ip/"]')]
      .map(x => x.href.split('?')[0])
      .find(h => !/\/sp\/track/.test(h)) || '';
    if (!a) { noUrl++; return; }
    const rating = (txt.match(/([\d.]+)\s*out of 5/i) || [])[1];
    const rev = (txt.match(/([\d,]+)\s*reviews?/i) || [])[1];
    seen.add(id);
    rows.push({
      rank: rows.length + 1,
      name: name,
      item_id: id,
      price_usd: priceOf(txt),
      rating: rating ? parseFloat(rating) : null,
      review_count: rev ? parseInt(rev.replace(/,/g, ''), 10) : null,
      url: a,
    });
  });
  return { rows, skipped_sponsored: sponsored, skipped_no_url: noUrl };
}
"""

# Ulta 카드 텍스트는 이런 순서다.
#
#   브랜드+상품명(링크문구) | 3 colors | Sale | 브랜드 | 상품명 |
#   4.6 out of 5 stars ; 130 reviews | 4.6 | (130) | Sale price $16.80 | ...
#
# 처음에 parts[0] 을 브랜드로 읽었다. 그건 브랜드가 아니라 링크 전체
# 문구여서 상품명이 빈 문자열이 됐고 60건 중 1건만 살아남았다.
# 별점 칸을 기준점으로 잡으면 바로 앞 둘이 브랜드와 상품명이다.
JS_ULTA = r"""
() => {
  const rows = [];
  const seen = new Set();
  document.querySelectorAll('a[href*="/p/"]').forEach(a => {
    const url = a.href.split('?')[0];
    if (seen.has(url)) return;
    // 가격이 보이는 조상까지 올라간다. 카드 경계를 클래스명으로 찍지 않는다.
    let card = a;
    for (let i = 0; i < 5 && card.parentElement; i++) {
      if (/\$\d/.test(card.innerText || '')) break;
      card = card.parentElement;
    }
    const parts = (card.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
    if (!parts.length) return;
    const full = (a.innerText || '').replace(/\s+/g, ' ').trim();

    let brand = '', name = '';
    const starIdx = parts.findIndex(s => /out of 5 stars/i.test(s));
    if (starIdx >= 2) {
      brand = parts[starIdx - 2];
      name = parts[starIdx - 1];
    }
    // 리뷰가 없는 신규 상품은 별점 칸이 없다.
    // 전체 문구가 그것으로 시작하는 칸을 브랜드로 본다.
    if (!name) {
      const b = parts.slice(1).find(s =>
        s.length >= 2 && s.length < full.length && full.startsWith(s));
      if (b) { brand = b; name = full.slice(b.length).trim(); }
    }
    if (!name || name.length < 4) return;

    const joined = parts.join(' | ');
    // 판매가를 먼저 찾는다. List price 는 정가라 벤치마크가 아니다.
    const price = (joined.match(/Sale price\s*\$([\d,]+\.\d{2})/i)
                || joined.match(/\$([\d,]+\.\d{2})/) || [])[1];
    const rating = (joined.match(/([\d.]+)\s*out of 5/i) || [])[1];
    const rev = (joined.match(/;\s*([\d,]+)\s*reviews?/i)
              || joined.match(/\(([\d,]+)\)/) || [])[1];
    if (!price) return;
    seen.add(url);
    rows.push({
      rank: rows.length + 1,
      name: name,
      brand: brand,
      price_usd: parseFloat(price.replace(/,/g, '')),
      rating: rating ? parseFloat(rating) : null,
      review_count: rev ? parseInt(rev.replace(/,/g, ''), 10) : null,
      url: url,
    });
  });
  return { rows, skipped_sponsored: 0 };
}
"""

JS_SEPHORA = r"""
() => {
  const rows = [];
  const seen = new Set();
  document.querySelectorAll('a[href*="/product/"]').forEach(a => {
    let card = a;
    for (let i = 0; i < 5 && card.parentElement; i++) {
      if (/\$\d/.test(card.innerText || '')) break;
      card = card.parentElement;
    }
    const txt = card.innerText || '';
    if (!/\$\d/.test(txt)) return;
    const url = a.href.split('?')[0];
    const pid = (url.match(/-(P\d+)$/) || [])[1] || url;
    if (seen.has(pid)) return;
    // Quicklook | 브랜드 | 상품명 | 리뷰수 | $가격 | [배지]
    const parts = txt.split('\n').map(s => s.trim())
      .filter(s => s && !/^Quicklook$/i.test(s));
    const priceIdx = parts.findIndex(s => /^\$[\d,]+\.\d{2}$/.test(s));
    if (priceIdx < 2) return;
    const brand = parts[0];
    const name = parts[1];
    if (!name || name.length < 4) return;
    const price = parseFloat(parts[priceIdx].replace(/[$,]/g, ''));
    const revEl = card.querySelector('[data-at="review_count"]');
    let rev = (revEl?.innerText || '').trim();
    let revNum = null;
    if (/^[\d.]+K$/i.test(rev)) revNum = Math.round(parseFloat(rev) * 1000);
    else if (/^[\d,]+$/.test(rev)) revNum = parseInt(rev.replace(/,/g, ''), 10);
    const star = card.querySelector('[data-at="star_rating_style"]');
    const aria = star?.parentElement?.getAttribute('aria-label') || '';
    const rating = (aria.match(/([\d.]+)\s*stars?/i) || [])[1];
    seen.add(pid);
    rows.push({
      rank: rows.length + 1,
      name: name,
      brand: brand,
      product_id: pid,
      price_usd: price,
      rating: rating ? parseFloat(rating) : null,
      review_count: revNum,
      url: url,
    });
  });
  return { rows, skipped_sponsored: 0 };
}
"""

SITES = {
    "amazon": {
        "url": "https://www.amazon.com/gp/bestsellers/beauty/",
        "label": "amazon.com/gp/bestsellers/beauty",
        "js": JS_AMAZON,
        "robots": "/gp/bestsellers/ 관련 Disallow 없음 (2026-09-15 확인)",
    },
    "walmart": {
        "url": "https://www.walmart.com/browse/beauty/1085666",
        "label": "walmart.com/browse/beauty/1085666",
        "js": JS_WALMART,
        "robots": "/browse/ 관련 Disallow 없음 (2026-09-15 확인)",
    },
    "ulta": {
        "url": "https://www.ulta.com/shop/skin-care",
        "label": "ulta.com/shop/skin-care",
        "js": JS_ULTA,
        "robots": "Disallow 는 /community/groups 둘뿐. /shop/ 허용 (2026-09-15 확인)",
        "note": "/shop/bestsellers 는 차단 페이지만 돌아와 카테고리 경로를 쓴다",
    },
    "sephora": {
        "url": "https://www.sephora.com/beauty/beauty-best-sellers",
        "label": "sephora.com/beauty/beauty-best-sellers",
        "js": JS_SEPHORA,
        "robots": "/browse/ 는 Disallow 라 요청하지 않는다. 이 경로는 허용 (2026-09-15 확인)",
        "note": "/beauty/bestsellers 는 홈으로 리다이렉트된다",
    },
}

# 차단 페이지를 상품 0건과 구별한다. 둘은 원인이 달라 사유도 달라야 한다.
BLOCK_MARKS = (
    "our apologies", "be right back", "access denied", "pardon our interruption",
    "enter the characters", "automated access", "robot or human",
    "unusual traffic", "verify you are",
)


# 사람 브라우저에서 받아둔 보강 파일.
#
# Walmart 와 Sephora 는 CI 의 새 chromium 을 뒤로 돌린다.
#   walmart  "Robot or human?" HUMAN 챌린지 (headless/headful 둘 다)
#   sephora  "Access Denied"
# 사용 기록이 쌓인 실제 프로필의 Chrome 은 그냥 통과한다.
# 그래서 그 둘만 사람 세션에서 받아 이 파일에 넣고, 수집기가 빈
# 자리에만 썼다. 브라우저가 직접 받은 곳은 절대 이것으로 덮지 않는다.
ASSIST = DATA / "manual" / "us_retail_assist.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_assist() -> dict:
    if not ASSIST.exists():
        return {}
    try:
        d = json.loads(ASSIST.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"::warning::보강 파일을 읽지 못했다: {e}")
        return {}
    return d if isinstance(d, dict) else {}


def apply_assist(result: dict, assist: dict) -> None:
    """브라우저가 0건으로 끝난 곳에만 보강 행을 넣는다."""
    sites = (assist.get("sites") or {})
    at = assist.get("captured_at") or ""
    via = assist.get("via") or "사람 브라우저 세션"
    for key, blk in sites.items():
        if key not in result:
            continue
        if result[key]["rows"]:
            continue                      # 직접 받은 것이 이긴다
        rows = [r for r in (blk.get("rows") or [])
                if isinstance(r, dict) and r.get("name") and r.get("url")]
        if not rows:
            continue
        result[key]["rows"] = rows[:MAX_ITEMS]
        result[key]["assisted"] = True
        result[key]["assist_at"] = at
        result[key]["assist_via"] = via
        result[key]["skipped_sponsored"] = blk.get("skipped_sponsored") or 0
        result[key]["reason"] = (
            f"{result[key]['reason']} · 보강 파일로 채움 "
            f"({via}, {str(at)[:10]})")
        print(f"  [{key}] 브라우저 차단 → 보강 파일 {len(rows)}건 사용")


def collect_all() -> dict:
    """네 사이트를 한 브라우저로 돌면서 받는다."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("::error::playwright 가 없다.")
        print("  pip install playwright && playwright install chromium")
        return {}

    result = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=UA,
            viewport={"width": 1440, "height": 1000},
            locale="en-US",
            timezone_id="America/Los_Angeles",
        )
        page = ctx.new_page()

        for key, cfg in SITES.items():
            entry = {"rows": [], "reason": "", "url": cfg["url"],
                     "label": cfg["label"], "skipped_sponsored": 0}
            try:
                print(f"\n[{key}] {cfg['url']}")
                page.goto(cfg["url"], timeout=NAV_TIMEOUT,
                          wait_until="domcontentloaded")
                page.wait_for_timeout(SETTLE_MS)

                # 지연 로딩을 깨운다
                for i in range(SCROLL_STEPS):
                    page.evaluate(f"window.scrollTo(0, {(i + 1) * 1400})")
                    page.wait_for_timeout(1200)
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(600)

                body = (page.inner_text("body") or "").strip()
                low = body.lower()
                if len(body) < 400 or any(m in low for m in BLOCK_MARKS):
                    hit = next((m for m in BLOCK_MARKS if m in low), "본문이 비었다")
                    entry["reason"] = (f"차단/빈 페이지로 보인다 (근거: {hit}, "
                                       f"본문 {len(body)}자)")
                    print(f"  {entry['reason']}")
                    result[key] = entry
                    continue

                got = page.evaluate(cfg["js"]) or {}
                rows = [r for r in (got.get("rows") or [])
                        if r.get("name") and r.get("url")]
                entry["rows"] = rows[:MAX_ITEMS]
                entry["skipped_sponsored"] = got.get("skipped_sponsored") or 0
                if not rows:
                    entry["reason"] = ("페이지는 열렸으나 상품을 파싱하지 못했다. "
                                       "카드 구조가 바뀌었을 수 있다.")
                    print(f"  {entry['reason']}")
                else:
                    priced = sum(1 for r in rows if r.get("price_usd"))
                    print(f"  {len(entry['rows'])}건 (가격 있는 것 {priced}건"
                          + (f", 스폰서 제외 {entry['skipped_sponsored']}건"
                             if entry["skipped_sponsored"] else "") + ")")
            except Exception as e:                             # noqa: BLE001
                entry["reason"] = f"{type(e).__name__}: {e}"
                print(f"  실패: {entry['reason']}")
            result[key] = entry

        browser.close()
    return result


def price_stats(rows: list[dict]) -> dict:
    prices = sorted(r["price_usd"] for r in rows if r.get("price_usd"))
    if not prices:
        return {}
    return {
        "n": len(prices),
        "min": prices[0],
        "p25": prices[len(prices) // 4],
        "median": prices[len(prices) // 2],
        "max": prices[-1],
    }


GENERATOR = "scripts/collect_us_retail.py"
MARKER = "Playwright chromium"


def is_ours(prev, _marker: str = "") -> bool:
    """이 파일을 우리가 남긴 것인지 본다.

    collect_oliveyoung_us.py 가 같은 검사를 한다. 거기 주석에 왜 필요한지
    적혀 있다. 손입력 스크립트가 같은 경로에 먼저 쓰고 수집기가 0건으로
    끝나면, 남의 데이터를 우리 수집분으로 물려받게 된다.

    판별은 method 가 아니라 generator 로 한다. 같은 수집기가 때에 따라
    다른 경로로 받을 수 있기 때문이다. Walmart 와 Sephora 는 CI 의 새
    브라우저로는 봇 처리를 넘지 못해 사람 세션에서 받은 것을 넣는다.
    그것을 다음 CI 실행이 0건으로 덮으면 안 된다.
    """
    if not isinstance(prev, dict):
        return False
    if prev.get("generator") != GENERATOR:
        return False
    if not prev.get("collected_at"):
        return False
    return bool(prev.get("products"))


def write_catalog(out: Path, entry: dict, robots: str, note: str = "") -> int:
    """from_catalog_file() 이 읽는 모양으로 쓴다 (amazon / walmart)."""
    rows = entry["rows"]
    reason = entry["reason"]
    stale_from = ""

    prev_method = ""
    if not rows and out.exists():
        try:
            prev = json.loads(out.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            prev = {}
        if is_ours(prev):
            rows = prev["products"]
            stale_from = prev.get("collected_at") or prev.get("stale_from") or ""
            prev_method = str(prev.get("method") or "")
            reason = f"{reason} · 이전 수집분 유지({stale_from[:10]})"
            print(f"  이전 성공분 {len(rows)}건 유지")
        elif prev:
            print("::warning::기존 파일이 우리 수집기가 남긴 것이 아니라 "
                  "물려받지 않는다. 0건으로 기록한다.")
            reason = f"{reason} · 기존 파일 출처 불명이라 승계 안 함"

    if entry.get("assisted"):
        method = (f"{entry.get('assist_via')} · 베스트셀러 그리드 파싱 "
                  f"(CI 브라우저는 차단됨)")
    else:
        method = prev_method or f"{MARKER} · 베스트셀러 그리드 파싱"

    payload = {
        "source": f"{entry['label']} (실수집)",
        "generator": GENERATOR,
        "method": method,
        "assisted": bool(entry.get("assisted")),
        "assist_at": entry.get("assist_at", ""),
        "source_url": entry["url"],
        "robots_note": robots,
        "collected_at": now_iso(),
        "count": len(rows),
        "reason": reason,
        "is_stale": bool(stale_from),
        "stale_from": stale_from,
        "skipped_sponsored": entry.get("skipped_sponsored") or 0,
        "price_stats": price_stats(rows),
        "products": rows,
    }
    if note:
        payload["path_note"] = note
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"  저장 {len(rows)}건 -> {out.relative_to(ROOT)}")
    return len(rows)


def write_us_beauty(ulta: dict, seph: dict) -> int:
    """from_us_beauty() 가 읽는 모양으로 쓴다 (ulta / sephora).

    sync_channels.from_us_beauty(substr) 는 products[].source 에 "Ulta" 또는
    "Sephora" 가 들어 있는 것만 고른다. 그리고 브랜드나 가격 중 하나는
    있어야 상품으로 인정한다. 그래서 source 에 가게 이름을 박아둔다.
    """
    products, notes = [], {}
    for store, entry in (("Ulta", ulta), ("Sephora", seph)):
        for r in entry["rows"]:
            products.append({
                "source": f"{store} Bestsellers",
                "store": store,
                "title": r["name"],
                "brand": r.get("brand") or "",
                "price_usd": r.get("price_usd"),
                "rating": r.get("rating"),
                "review_count": r.get("review_count"),
                "category": "Beauty",
                "rank": r.get("rank"),
                "url": r.get("url") or "",
            })
        notes[store] = {
            "count": len(entry["rows"]),
            "source_url": entry["url"],
            "reason": entry["reason"],
        }

    stale_from = ""
    if not products and OUT_US_BEAUTY.exists():
        try:
            prev = json.loads(OUT_US_BEAUTY.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            prev = {}
        if is_ours(prev):
            products = prev["products"]
            stale_from = prev.get("collected_at") or prev.get("stale_from") or ""
            print(f"  이전 성공분 {len(products)}건 유지")
        elif prev:
            # 지금 파일에는 title 이 "Join / Sign in" 인 네비게이션 텍스트가
            # 들어 있다. 봇 차단으로 긁힌 것이라 물려받을 값이 아니다.
            print("::warning::기존 us_beauty_products.json 은 우리 수집기가 "
                  "남긴 것이 아니라 물려받지 않는다.")

    payload = {
        "generator": GENERATOR,
        "method": f"{MARKER} · Ulta/Sephora 카드 파싱",
        "collected_at": now_iso(),
        "country": "US",
        "market": "beauty",
        "count": len(products),
        "is_stale": bool(stale_from),
        "stale_from": stale_from,
        "by_store": notes,
        "price_stats": price_stats(
            [{"price_usd": p.get("price_usd")} for p in products]),
        "products": products,
    }
    OUT_US_BEAUTY.parent.mkdir(parents=True, exist_ok=True)
    OUT_US_BEAUTY.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"  저장 {len(products)}건 -> {OUT_US_BEAUTY.relative_to(ROOT)}")
    return len(products)


def main() -> int:
    got = collect_all()
    if not got:
        return 1

    assist = load_assist()
    if assist:
        print("\n" + "-" * 46)
        print(f"보강 파일 확인: {ASSIST.relative_to(ROOT)}")
        apply_assist(got, assist)

    print("\n" + "=" * 46)
    print("저장")
    print("=" * 46)

    n_am = write_catalog(OUT_AMAZON, got["amazon"],
                         SITES["amazon"]["robots"])
    n_wm = write_catalog(OUT_WALMART, got["walmart"],
                         SITES["walmart"]["robots"])
    n_ub = write_us_beauty(got["ulta"], got["sephora"])

    print("\n" + "=" * 46)
    print("결과")
    print("=" * 46)
    for key in SITES:
        e = got[key]
        if not e["rows"]:
            mark = "FAIL"
        elif e.get("assisted"):
            mark = "보강"
        else:
            mark = "OK  "
        print(f"  {mark} {key:8s} {len(e['rows']):3d}건  {e['label']}")
        if e["reason"]:
            print(f"       사유: {e['reason']}")

    live = sum(1 for k in SITES if got[k]["rows"])
    print(f"\n네 곳 중 {live}곳 수집 성공 · "
          f"amazon {n_am} · walmart {n_wm} · us_beauty {n_ub}")

    # 한 곳이라도 받았으면 진행한다. 전부 실패면 워크플로를 세운다.
    return 0 if live else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                                          # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("::error::미국 리테일 수집기가 예상 못한 예외로 멈췄다. "
              "위 traceback 을 본다.", file=sys.stderr)
        sys.exit(1)
