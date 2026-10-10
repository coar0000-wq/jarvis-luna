#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shop.com(Shopify 의 Shop 앱 마켓) 에서 같은 상품의 판매가를 읽어 USD 로 환산한다.

사용: python scripts/shop_price_compare.py "<검색어>"   ->  stdout 에 JSON 한 줄

지킨 것
  - 읽기 전용 검색 1회만 한다. 장바구니·결제·로그인 경로는 건드리지 않는다 (robots.txt 의 Disallow 와 정책 준수).
  - 하루 3회(상품 3개) 수준으로만 호출한다.
  - 실패하면 빈 결과를 돌려준다. 호출한 쪽이 가격 정책으로 되돌아간다.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36 JarvisLunaPriceCheck/1.0"
SYMBOLS = [("US$", "USD"), ("AU$", "AUD"), ("CA$", "CAD"), ("NZ$", "NZD"), ("HK$", "HKD"), ("SGD", "SGD"), ("USD", "USD"),
           ("EUR", "EUR"), ("GBP", "GBP"), ("AUD", "AUD"), ("CAD", "CAD"), ("€", "EUR"), ("£", "GBP"), ("₩", "KRW"),
           ("¥", "JPY"), ("$", "USD")]
PRICE_RE = re.compile(r"(US\$|AU\$|CA\$|NZ\$|HK\$|SGD|USD|EUR|GBP|AUD|CAD|€|£|₩|¥|\$)\s?([0-9][0-9,]*(?:\.[0-9]+)?)")


def rates():
    """USD 기준 환율 (무료 공개 API). 실패하면 빈 dict."""
    try:
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=20) as r:
            return json.loads(r.read().decode()).get("rates") or {}
    except Exception:  # noqa: BLE001
        return {}


def to_usd(text, fx):
    m = PRICE_RE.search(text or "")
    if not m:
        return None
    sym, num = m.group(1), float(m.group(2).replace(",", ""))
    cur = next((c for s, c in SYMBOLS if s == sym), None)
    if cur == "USD":
        return num
    rate = fx.get(cur)
    return round(num / rate, 2) if rate else None


def search(query, timeout_ms=45000):
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    out = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="en-US", viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        from urllib.parse import quote  # noqa: PLC0415

        page.goto("https://shop.com/search/results?query=" + quote(query), wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_selector("h3", timeout=timeout_ms)
        page.wait_for_timeout(2500)
        cards = page.evaluate(
            """() => [...document.querySelectorAll('h3')].map(h => {
                 const a = h.closest('a'); if (!a) return null;
                 const lines = a.innerText.split('\\n').map(s => s.trim()).filter(Boolean);
                 return {title: h.innerText.trim(), lines, href: a.getAttribute('href')};
               }).filter(Boolean)"""
        )
        browser.close()
    fx = rates()
    for c in cards[:40]:
        price_lines = [ln for ln in c["lines"] if PRICE_RE.search(ln) and not re.fullmatch(r"\(.*\)", ln)]
        usd = to_usd(price_lines[0], fx) if price_lines else None  # 첫 번째 가격이 현재 판매가 (뒤는 정가)
        store = c["lines"][0] if c["lines"] and c["lines"][0] != c["title"] else ""
        out.append({"title": c["title"], "store": store, "price_text": price_lines[0] if price_lines else "", "usd": usd,
                    "url": "https://shop.com" + (c["href"] or "")})
    return out


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]).strip()
    try:
        print(json.dumps({"query": q, "results": search(q)}, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"query": q, "results": [], "error": f"{type(exc).__name__}: {str(exc)[:200]}"}, ensure_ascii=False))
