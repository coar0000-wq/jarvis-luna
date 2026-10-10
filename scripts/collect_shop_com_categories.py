#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shop.com 카테고리 페이지에서 뷰티 상품 노출 데이터를 읽어 data/shop_com_categories.json 에 저장한다.

수집 채널 현황의 "shop.com 카테고리" 채널 원천이다.

지킨 것
  - robots.txt 를 매번 먼저 읽고, 읽을 경로가 Disallow 에 걸리면 수집하지 않는다 (status=blocked_by_robots).
  - 읽기 전용. 카테고리 목록 페이지 2곳(/categories, /categories/5/beauty) 만 1회씩 연다.
    장바구니·결제·로그인·검색 경로는 건드리지 않는다.
  - 가격은 화면 표기를 그대로 두고, 환산값(USD)은 공개 환율로 따로 적는다. 환산 못 하면 null.
  - 실패하면 이전 파일을 지우지 않고 status=failed 로 사유만 남긴다. 빈 값을 그럴듯하게 채우지 않는다.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shop_price_compare as spc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "shop_com_categories.json"
BASE = "https://shop.com"
PAGES = [
    ("/categories", "Explore"),
    ("/categories/5/beauty", "Beauty"),
]
BEAUTY_SECTIONS = {"new in beauty"}
UA = spc.UA

JS_CARDS = """() => {
  const out = [];
  const links = [...document.querySelectorAll('main a[href]')].filter(a => a.querySelector('h3'));
  for (const a of links) {
    const h3 = a.querySelector('h3');
    const lines = a.innerText.split('\\n').map(s => s.trim()).filter(Boolean);
    const rEl = [...a.querySelectorAll('[aria-label],[alt]')]
      .map(e => e.getAttribute('aria-label') || e.getAttribute('alt')).find(s => /Average rating/.test(s || ''));
    let sec = ''; let el = a;
    for (let i = 0; i < 10 && el && !sec; i++) {
      el = el.parentElement; if (!el) break;
      let p = el.previousElementSibling;
      for (let j = 0; j < 4 && p && !sec; j++) {
        const t = (p.innerText || '').trim();
        if (t && t.length < 50 && !p.querySelector('h3')) sec = t;
        p = p.previousElementSibling;
      }
    }
    const wrap = (a.parentElement && a.parentElement.parentElement) ? a.parentElement.parentElement.innerText : '';
    out.push({title: h3.textContent.trim(), lines, rating_alt: rEl || '', section: sec,
              href: a.getAttribute('href'), off: (wrap.match(/(\\d+)% off/) || [])[1] || null});
  }
  return out;
}"""

JS_CATEGORIES = """() => [...document.querySelectorAll('main a[href^="/categories/"]')]
  .map(a => ({name: a.textContent.trim(), href: a.getAttribute('href')})).filter(c => c.name)"""


def launch_kwargs():
    """CI 에서는 playwright 가 설치한 chromium 을 쓴다. 로컬 점검용으로만 CHROME_PATH 로 실제 크롬을 지정할 수 있다."""
    import os  # noqa: PLC0415

    path = os.environ.get("CHROME_PATH")
    return {"executable_path": path} if path else {}


def norm(s):
    return (s or "").replace("\u2019", "'").strip().lower()


def robots_ok(paths):
    rp = RobotFileParser()
    req = urllib.request.Request(BASE + "/robots.txt", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        rp.parse(r.read().decode("utf-8", "replace").splitlines())
    return {p: rp.can_fetch("*", BASE + p) for p, _ in paths}


def parse_card(c, fx):
    prices = [ln for ln in c["lines"] if spc.PRICE_RE.search(ln) and not re.fullmatch(r"\(.*\)", ln)]
    cur_line = prices[0] if prices else ""
    # 가격 줄이 "US$54.00 US$60.00" 처럼 한 줄에 붙어 오기도 한다. 앞이 판매가, 뒤가 정가.
    found = [m.group(0) for m in spc.PRICE_RE.finditer(" ".join(prices))]
    sale = found[0] if found else ""
    orig = found[1] if len(found) > 1 else ""
    m = re.search(r"rating: ([\d.]+), based on (\d+) reviews", c.get("rating_alt") or "")
    brand = c["lines"][0] if c["lines"] and c["lines"][0] != c["title"] else ""
    return {
        "title": c["title"], "brand": brand, "section": c.get("section") or "",
        "price_text": sale, "list_price_text": orig,
        "price_usd": spc.to_usd(sale, fx) if sale else None,
        "discount_pct": int(c["off"]) if c.get("off") else None,
        "rating": float(m.group(1)) if m else None, "reviews": int(m.group(2)) if m else None,
        "url": urljoin(BASE, c["href"]).split("?")[0],
        "_line": cur_line,
    }


def collect():
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    allowed = robots_ok(PAGES)
    if not all(allowed.values()):
        return {"status": "blocked_by_robots", "reason": "robots.txt 가 읽을 경로를 허용하지 않음: " + ", ".join(p for p, ok in allowed.items() if not ok),
                "collected_at": now, "source_url": BASE + "/categories", "items": [], "categories": []}
    fx = spc.rates()
    items, categories, seen = [], [], set()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, **launch_kwargs())
        ctx = browser.new_context(user_agent=UA, locale="en-US", viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        for path, label in PAGES:
            page.goto(BASE + path, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_selector("h3", timeout=45000)
            page.wait_for_timeout(2500)
            if path == "/categories":
                categories = [c for c in page.evaluate(JS_CATEGORIES)
                              if re.match(r"^/categories/\d+/", c["href"]) and len(c["name"]) <= 30 and "\n" not in c["name"]]
            for raw in page.evaluate(JS_CARDS):
                card = parse_card(raw, fx)
                sec = norm(card["section"])
                # /categories 에서는 뷰티 섹션만 가져온다. 뷰티 페이지는 전부 뷰티.
                if path == "/categories" and sec not in BEAUTY_SECTIONS:
                    continue
                if not card["price_text"] or card["url"] in seen:
                    continue  # 가격이 없는 카드는 상품이 아니라 입점 스토어 소개 카드다
                seen.add(card["url"])
                card["page"] = label
                card.pop("_line", None)
                items.append(card)
        browser.close()
    seen_cat, cats = set(), []
    for c in categories:
        if c["href"] not in seen_cat:
            seen_cat.add(c["href"])
            cats.append({"name": c["name"], "url": urljoin(BASE, c["href"])})
    status = "ok" if items else "empty"
    return {"status": status, "reason": "" if items else "카드가 한 개도 읽히지 않음", "collected_at": now,
            "source_url": BASE + "/categories", "pages": [p for p, _ in PAGES],
            "robots_checked": True, "fx_source": "open.er-api.com" if fx else None,
            "categories": cats, "count": len(items), "items": items}


def main():
    try:
        data = collect()
    except Exception as exc:  # noqa: BLE001
        prev = {}
        try:
            prev = json.loads(OUT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        data = {**prev, "status": "failed", "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
                "last_attempt_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
        data.setdefault("items", [])
        data.setdefault("categories", [])
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": data.get("status"), "count": len(data.get("items", [])), "reason": data.get("reason", "")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
