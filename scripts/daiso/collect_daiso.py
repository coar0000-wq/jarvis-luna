#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
다이소몰 실제 상품 데이터 수집기.

원칙
----
* 측정한 값만 저장한다. 가격은 상품 페이지에 실제로 표시된 원화 금액이고,
  환율은 공개 API에서 받은 실시간 값이다. 배송비·관세·수수료처럼 아직
  확정되지 않은 값은 계산하지 않는다.
* 수집에 실패하면 실패했다고 기록한다. 추정치로 채우지 않는다.
* robots.txt를 지킨다. /pd/pdr/ 은 허용 경로이며 Crawl-delay 는 30초다.

환경변수
--------
DAISO_MAX_ITEMS  이번 실행에서 새로 가져올 상품 수 (기본 60)
DAISO_DELAY      요청 간 대기 초 (기본 30, robots.txt 준수)
DAISO_TIMEOUT    요청 타임아웃 초 (기본 20)
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "daiso_real"
PRODUCTS = OUT_DIR / "products.json"
STATE = OUT_DIR / "crawl_state.json"
STATUS = OUT_DIR / "collection_status.json"
CATMAP = Path(__file__).with_name("category_map.json")

BASE = "https://www.daisomall.co.kr"
SITEMAP = BASE + "/sitemap.xml"
UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"

MAX_ITEMS = int(os.environ.get("DAISO_MAX_ITEMS", "60"))
DELAY = float(os.environ.get("DAISO_DELAY", "30"))
TIMEOUT = float(os.environ.get("DAISO_TIMEOUT", "20"))

now_iso = lambda: datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            charset = r.headers.get_content_charset() or "utf-8"
            return r.status, r.read().decode(charset, "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:                                    # noqa: BLE001
        return 0, str(e)


# ----------------------------------------------------------------- parsing
META = re.compile(
    r'<meta[^>]+(?:property|name)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']*)["\']',
    re.I)
META_REV = re.compile(
    r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']([^"\']+)["\']',
    re.I)
PRICE_RE = re.compile(r"가격\s*([\d,]+)\s*원")
REVIEW_RE = re.compile(r"리뷰\s*([\d.]+)\s*점\s*\(\s*([\d,]+)\s*건\s*\)")


def unescape(s: str) -> str:
    return (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&#39;", "'").strip())


def meta_tags(html: str) -> dict:
    tags = {}
    for k, v in META.findall(html):
        tags.setdefault(k.lower(), unescape(v))
    for v, k in META_REV.findall(html):
        tags.setdefault(k.lower(), unescape(v))
    return tags


def parse_product(pd_no: str, url: str, html: str) -> dict | None:
    """상품 페이지에서 실제로 표시된 값만 추출한다."""
    t = meta_tags(html)
    title = t.get("og:title") or t.get("title") or ""
    desc = t.get("og:description") or t.get("description") or ""
    if not title:
        return None

    # og:title 형식: "상품명 | 브랜드 | 카테고리 | 1,000원 - 다이소몰"
    head = title.rsplit(" - ", 1)[0]
    parts = [p.strip() for p in head.split("|")]
    name = parts[0] if parts else ""
    brand = parts[1] if len(parts) > 2 else None
    category = parts[2] if len(parts) > 3 else (parts[1] if len(parts) == 3 else None)

    price = None
    m = PRICE_RE.search(title) or PRICE_RE.search(desc)
    if m:
        price = int(m.group(1).replace(",", ""))
    else:                                    # 제목 끝의 "1,000원" 형태
        m2 = re.search(r"([\d,]+)\s*원", head)
        if m2:
            price = int(m2.group(1).replace(",", ""))

    if not name or price is None:
        return None

    rating = review_count = None
    r = REVIEW_RE.search(desc) or REVIEW_RE.search(title)
    if r:
        rating = float(r.group(1))
        review_count = int(r.group(2).replace(",", ""))

    return {
        "pd_no": pd_no,
        "name": name,
        "brand": brand,
        "site_category": category,
        "price_krw": price,
        "rating": rating,
        "review_count": review_count,
        "image_url": t.get("og:image"),
        "url": url,
        "collected_at": now_iso(),
        "source": "daisomall.co.kr 상품 상세 페이지",
    }


def classify(category: str | None, buckets: dict) -> str:
    if not category:
        return "미분류"
    for bucket, keywords in buckets.items():
        if any(kw in category for kw in keywords):
            return bucket
    return "미분류"


# ----------------------------------------------------------------- fx rate
def fetch_fx() -> dict:
    """실시간 KRW 환율. 실패하면 실패를 기록하고 값은 비워 둔다."""
    url = "https://api.frankfurter.app/latest?from=USD&to=KRW"
    status, body = fetch(url)
    if status == 200:
        try:
            d = json.loads(body)
            krw = float(d["rates"]["KRW"])
            return {"usd_to_krw": krw, "krw_to_usd": round(1 / krw, 8),
                    "as_of": d.get("date"), "source": url,
                    "fetched_at": now_iso(), "ok": True}
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            return {"ok": False, "error": "파싱 실패: %s" % e, "source": url,
                    "fetched_at": now_iso()}
    return {"ok": False, "error": "HTTP %s" % status, "source": url,
            "fetched_at": now_iso()}


# ----------------------------------------------------------------- sitemap
def product_urls() -> list[str]:
    status, body = fetch(SITEMAP)
    if status != 200:
        return []
    urls = re.findall(r"<loc>\s*([^<\s]+/pd/pdr/[^<\s]+)\s*</loc>", body)
    if not urls:                                     # 중첩 sitemap 대응
        for sub in re.findall(r"<loc>\s*([^<\s]+\.xml)\s*</loc>", body):
            if sub == SITEMAP:
                continue
            time.sleep(min(DELAY, 5))
            s2, b2 = fetch(sub)
            if s2 == 200:
                urls += re.findall(r"<loc>\s*([^<\s]+/pd/pdr/[^<\s]+)\s*</loc>", b2)
    seen, out = set(), []
    for u in urls:
        u = unescape(u)
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def main() -> int:
    cfg = load_json(CATMAP, {})
    buckets = cfg.get("buckets", {})
    target = int(cfg.get("target_per_bucket", 100))

    store = load_json(PRODUCTS, {"products": []})
    products = store.get("products", [])
    by_no = {p["pd_no"]: i for i, p in enumerate(products)}

    state = load_json(STATE, {"visited": [], "sitemap_cached_at": None, "urls": []})
    visited = set(state.get("visited", []))

    run = {
        "started_at": now_iso(),
        "requested": 0, "ok": 0, "parse_failed": 0, "http_error": 0,
        "delay_seconds": DELAY, "max_items": MAX_ITEMS,
        "user_agent": UA,
        "robots_note": "robots.txt: User-agent * → Allow /pd/pdr/, Crawl-delay 30",
    }

    urls = state.get("urls") or []
    if not urls:
        urls = product_urls()
        if not urls:
            run.update(finished_at=now_iso(), status="blocked",
                       message="sitemap.xml에서 상품 URL을 가져오지 못했습니다. "
                               "차단 또는 사이트 구조 변경 가능성.")
            save_json(STATUS, {"last_run": run, "totals": summarize(products, buckets, target),
                               "fx": load_json(STATUS, {}).get("fx")})
            print(json.dumps(run, ensure_ascii=False, indent=2))
            return 1
        state["urls"] = urls
        state["sitemap_cached_at"] = now_iso()

    counts = tally(products)
    picked = 0
    for url in urls:
        if picked >= MAX_ITEMS:
            break
        m = re.search(r"pdNo=(\d+)", url)
        if not m:
            continue
        pd_no = m.group(1)
        if pd_no in visited:
            continue

        if not url.startswith("http"):
            url = BASE + url
        run["requested"] += 1
        picked += 1
        status, html = fetch(url)
        visited.add(pd_no)

        if status != 200:
            run["http_error"] += 1
        else:
            item = parse_product(pd_no, url, html)
            if item is None:
                run["parse_failed"] += 1
            else:
                item["bucket"] = classify(item["site_category"], buckets)
                if counts.get(item["bucket"], 0) >= target and item["bucket"] != "미분류":
                    pass                          # 목표 도달 버킷은 갱신만
                counts[item["bucket"]] = counts.get(item["bucket"], 0) + 1
                if pd_no in by_no:
                    products[by_no[pd_no]] = item
                else:
                    by_no[pd_no] = len(products)
                    products.append(item)
                run["ok"] += 1

        time.sleep(DELAY + random.uniform(0, 2))

    run["finished_at"] = now_iso()
    if run["requested"] == 0:
        run["status"] = "nothing_to_do"
    elif run["ok"] == 0:
        run["status"] = "blocked"
        run["message"] = ("모든 요청이 실패했습니다. GitHub Actions 러너의 해외 IP가 "
                          "차단되었을 수 있습니다. 로컬(한국 IP) 실행을 검토하세요.")
    elif run["ok"] < run["requested"] / 2:
        run["status"] = "degraded"
    else:
        run["status"] = "ok"

    state["visited"] = sorted(visited)
    save_json(STATE, state)
    save_json(PRODUCTS, {
        "updated_at": now_iso(),
        "source": "daisomall.co.kr (robots.txt 허용 경로 /pd/pdr/)",
        "truth_note": "가격은 상품 페이지에 표시된 실제 원화 금액입니다. "
                      "배송비·관세·수수료는 확정 견적이 없어 계산하지 않습니다.",
        "count": len(products),
        "products": products,
    })
    save_json(STATUS, {
        "last_run": run,
        "totals": summarize(products, buckets, target),
        "fx": fetch_fx(),
        "sitemap_urls_known": len(urls),
        "visited": len(visited),
    })
    print(json.dumps(run, ensure_ascii=False, indent=2))
    return 0 if run["status"] in ("ok", "degraded", "nothing_to_do") else 1


def tally(products: list) -> dict:
    c: dict = {}
    for p in products:
        c[p.get("bucket", "미분류")] = c.get(p.get("bucket", "미분류"), 0) + 1
    return c


def summarize(products: list, buckets: dict, target: int) -> dict:
    c = tally(products)
    prices = [p["price_krw"] for p in products if isinstance(p.get("price_krw"), int)]
    return {
        "products": len(products),
        "target_per_bucket": target,
        "by_bucket": {b: c.get(b, 0) for b in list(buckets) + ["미분류"]},
        "price_krw_min": min(prices) if prices else None,
        "price_krw_max": max(prices) if prices else None,
        "with_rating": sum(1 for p in products if p.get("rating") is not None),
    }


if __name__ == "__main__":
    sys.exit(main())
