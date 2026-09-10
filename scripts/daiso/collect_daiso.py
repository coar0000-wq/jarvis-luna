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
* 가격은 단일 meta 태그에 의존하지 않고 JSON-LD, meta, data-* 속성,
  본문 표시 가격, 임베디드 상태 데이터 순서로 여러 경로에서 확인한다.
* 이전 실행에서 파싱 실패한 상품은 다음 실행에서 자동 재시도한다.
* robots.txt를 지킨다. /pd/pdr/ 은 허용 경로이며 Crawl-delay 는 30초다.

환경변수
--------
DAISO_MAX_ITEMS       이번 실행에서 가져올 상품 수 (기본 60)
DAISO_DELAY           요청 간 대기 초 (기본 30, robots.txt 준수)
DAISO_TIMEOUT         요청 타임아웃 초 (기본 20)
DAISO_RETRY_FAILED    이전 실패 상품 재시도 여부 (기본 1)
DAISO_RETRY_UNAVAILABLE 이전 구매불가 상품도 재시도 여부 (기본 1)
"""
from __future__ import annotations

import html as html_lib
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
QUEUE = OUT_DIR / "beauty_queue.json"
STATUS = OUT_DIR / "collection_status.json"
CATMAP = Path(__file__).with_name("category_map.json")

BASE = "https://www.daisomall.co.kr"
SITEMAP = BASE + "/sitemap.xml"
UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"

MAX_ITEMS = int(os.environ.get("DAISO_MAX_ITEMS", "60"))
DELAY = float(os.environ.get("DAISO_DELAY", "30"))
TIMEOUT = float(os.environ.get("DAISO_TIMEOUT", "20"))
RETRY_FAILED = os.environ.get("DAISO_RETRY_FAILED", "1").strip().lower() not in {"0", "false", "no"}
RETRY_UNAVAILABLE = os.environ.get("DAISO_RETRY_UNAVAILABLE", "1").strip().lower() not in {"0", "false", "no"}

now_iso = lambda: datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fetch(url: str) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            charset = r.headers.get_content_charset() or "utf-8"
            return r.status, r.read().decode(charset, "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


# ----------------------------------------------------------------- parsing
META = re.compile(
    r'<meta[^>]+(?:property|name)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']*)["\']',
    re.I,
)
META_REV = re.compile(
    r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']([^"\']+)["\']',
    re.I,
)

PRICE_WON_RE = re.compile(r"(?<!\d)([\d]{1,3}(?:,\d{3})+|\d{2,6})\s*원(?!\d)")
PRICE_LABEL_RE = re.compile(
    r"(?:판매가|판매가격|가격|정가|할인가|최저가|할인판매가|salePrice|sellingPrice|sellPrice|price)"
    r"\s*[:=]?\s*[\"']?\s*([\d]{1,3}(?:,\d{3})+|\d{2,6})(?:\.\d+)?\s*(?:원|KRW)?",
    re.I,
)
REVIEW_RE = re.compile(r"리뷰\s*([\d.]+)\s*점\s*\(\s*([\d,]+)\s*건\s*\)")
SOLDOUT_RE = re.compile(r"(일시품절|판매종료|품절)")


def unescape(s: str) -> str:
    return html_lib.unescape(str(s)).strip()


def meta_tags(html: str) -> dict:
    tags = {}
    for k, v in META.findall(html):
        tags.setdefault(k.lower(), unescape(v))
    for v, k in META_REV.findall(html):
        tags.setdefault(k.lower(), unescape(v))
    return tags


def visible_text(html: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<noscript\b[^>]*>.*?</noscript>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text))


def iter_json_values(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield str(k), v
            yield from iter_json_values(v)
    elif isinstance(value, list):
        for item in value:
            yield from iter_json_values(item)


def json_ld_objects(html: str) -> list:
    out = []
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.I | re.S,
    )
    for block in blocks:
        raw = html_lib.unescape(block).strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
            continue
        except json.JSONDecodeError:
            pass

        try:
            cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", raw)
            out.append(json.loads(cleaned))
        except json.JSONDecodeError:
            continue
    return out


def numeric_price(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    s = unescape(str(value))
    s = s.replace("₩", "").replace("KRW", "").strip()
    m = re.search(r"(\d{1,3}(?:,\d{3})+|\d{2,6})(?:\.\d+)?", s)
    if not m:
        return None
    try:
        price = int(m.group(1).replace(",", ""))
    except ValueError:
        return None
    if price <= 0 or price > 1000000:
        return None
    return price


def extract_price(html: str, tags: dict, title: str, desc: str) -> tuple[int | None, str | None]:
    for obj in json_ld_objects(html):
        for key_name, value in iter_json_values(obj):
            lk = key_name.casefold()
            if lk in {"price", "lowprice", "highprice"} or lk.endswith("price"):
                price = numeric_price(value)
                if price is not None:
                    return price, f"jsonld:{key_name}"

    meta_keys = (
        "product:price:amount",
        "og:price:amount",
        "price",
        "saleprice",
        "sale_price",
        "sellingprice",
        "selling_price",
        "sellprice",
        "pricevalue",
    )
    for candidate_key in meta_keys:
        value = tags.get(candidate_key.casefold())
        price = numeric_price(value)
        if price is not None:
            return price, f"meta:{candidate_key}"

    attr_patterns = [
        re.compile(r'<[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)["\'][^>]*>', re.I),
        re.compile(r'<[^>]+content=["\']([^"\']+)["\'][^>]+itemprop=["\']price["\'][^>]*>', re.I),
        re.compile(r'<[^>]+(?:data-price|data-sale-price|data-selling-price|data-sell-price)=["\']([^"\']+)["\'][^>]*>', re.I),
        re.compile(r'<[^>]+(?:data-price|data-sale-price|data-selling-price|data-sell-price)=([0-9,]+)[^>]*>', re.I),
    ]
    for pattern in attr_patterns:
        for raw in pattern.findall(html):
            price = numeric_price(raw)
            if price is not None:
                return price, "html-attribute"

    script_text = " ".join(
        re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.I | re.S)
    )
    for source_name, text in (("script", script_text), ("html", html)):
        for match in PRICE_LABEL_RE.finditer(text):
            price = numeric_price(match.group(1))
            if price is not None:
                return price, f"{source_name}:label"

    for source_name, text in (
        ("title", title),
        ("description", desc),
        ("body", visible_text(html)),
    ):
        match = PRICE_WON_RE.search(text)
        if match:
            price = numeric_price(match.group(1))
            if price is not None:
                return price, f"{source_name}:won"

    return None, None


LAST_FAIL: dict = {}


def parse_product(pd_no: str, url: str, html: str) -> dict | None:
    LAST_FAIL.clear()
    t = meta_tags(html)
    title = t.get("og:title") or t.get("title") or ""
    desc = t.get("og:description") or t.get("description") or ""

    normalized_title = unescape(title).strip()
    normalized_desc = unescape(desc).strip()
    body_text = visible_text(html)

    if normalized_title == "다이소몰" or (
        (t.get("og:type") or "").lower() != "product"
        and not normalized_title
    ):
        LAST_FAIL.update(
            pd_no=pd_no,
            reason="구매 불가 (상품 페이지 없음)",
            unavailable=True,
            og_type=t.get("og:type") or "",
            og_title=normalized_title[:120],
            html_len=len(html),
            근거="상품 상세 메타가 사이트 기본 페이지로 반환되어 실제 상품 정보가 없습니다.",
        )
        return None

    if not normalized_title:
        LAST_FAIL.update(
            pd_no=pd_no,
            reason="og:title 없음",
            meta_count=len(t),
            html_len=len(html),
            sold_out=bool(SOLDOUT_RE.search(body_text)),
        )
        return None

    head = normalized_title.rsplit(" - ", 1)[0]
    parts = [p.strip() for p in head.split("|")]
    name = parts[0] if parts else ""
    brand = parts[1] if len(parts) > 2 else None
    category = parts[2] if len(parts) > 3 else (parts[1] if len(parts) == 3 else None)

    price, price_source = extract_price(
        html,
        t,
        normalized_title,
        normalized_desc,
    )

    if not name or price is None:
        sold_out = bool(SOLDOUT_RE.search(f"{normalized_title} {normalized_desc} {body_text}"))
        LAST_FAIL.update(
            pd_no=pd_no,
            reason="상품명 없음" if not name else "가격 없음",
            og_title=normalized_title[:160],
            og_type=t.get("og:type") or "",
            price_source=price_source,
            sold_out=sold_out,
            html_len=len(html),
        )
        return None

    rating = review_count = None
    r = REVIEW_RE.search(normalized_desc) or REVIEW_RE.search(normalized_title)
    if r:
        rating = float(r.group(1))
        review_count = int(r.group(2).replace(",", ""))

    sold_out = bool(SOLDOUT_RE.search(f"{normalized_title} {normalized_desc} {body_text}"))

    return {
        "pd_no": pd_no,
        "name": name,
        "brand": brand,
        "site_category": category,
        "price_krw": price,
        "price_source": price_source,
        "sold_out": sold_out,
        "stock_note": "품절 표시 있음" if sold_out else "판매 중",
        "stock_checked_at": now_iso(),
        "rating": rating,
        "review_count": review_count,
        "image_url": t.get("og:image"),
        "url": url,
        "collected_at": now_iso(),
        "source": "daisomall.co.kr 상품 상세 페이지",
    }


def excluded(item: dict, rules: dict) -> str:
    hay = " ".join(filter(None, [item.get("site_category"), item.get("name")])).lower()
    if not hay:
        return ""
    for name, spec in rules.items():
        if name.startswith("_"):
            continue
        if any(str(k).lower() in hay for k in (spec.get("keywords") or [])):
            return name
    return ""


def classify(item: dict, buckets: dict) -> str | None:
    haystack = " ".join(filter(None, [item.get("site_category"), item.get("name")]))
    if not haystack:
        return None
    for bucket, keywords in buckets.items():
        if any(kw in haystack for kw in keywords):
            return bucket
    return None


# ----------------------------------------------------------------- fx rate
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fetch_fx_rate import fetch_fx  # noqa: E402, F401


# ----------------------------------------------------------------- sitemap
def product_urls() -> list[str]:
    status, body = fetch(SITEMAP)
    if status != 200:
        return []
    urls = re.findall(r"<loc>\s*([^<\s]+/pd/pdr/[^<\s]+)\s*</loc>", body)
    if not urls:
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


def collect_retry_ids(previous_run: dict) -> set[str]:
    ids: set[str] = set()
    if RETRY_FAILED:
        for row in previous_run.get("parse_fail_samples") or []:
            if isinstance(row, dict) and row.get("pd_no"):
                ids.add(str(row["pd_no"]))
        for row in previous_run.get("failed_samples") or []:
            if isinstance(row, dict) and row.get("pd_no"):
                ids.add(str(row["pd_no"]))
    if RETRY_UNAVAILABLE:
        for pd_no in previous_run.get("unavailable_samples") or []:
            ids.add(str(pd_no))
    return ids


def main() -> int:
    cfg = load_json(CATMAP, {})
    buckets = cfg.get("buckets", {})
    exclude_rules = cfg.get("exclude", {})

    status_before = load_json(STATUS, {})
    previous_run = status_before.get("last_run") or {}

    store = load_json(PRODUCTS, {"products": []})
    products = store.get("products", [])

    pruned = {}
    kept = []
    for it in products:
        why = excluded(it, exclude_rules)
        if why:
            pruned[why] = pruned.get(why, 0) + 1
        else:
            kept.append(it)
    if pruned:
        print(f"제외 규칙으로 기존 {sum(pruned.values())}건 정리: {pruned}")
    products = kept
    by_no = {str(p.get("pd_no")): i for i, p in enumerate(products) if p.get("pd_no")}

    state = load_json(STATE, {"visited": [], "sitemap_cached_at": None, "urls": []})
    visited = set(str(x) for x in state.get("visited", []))

    retry_ids = collect_retry_ids(previous_run)
    if retry_ids:
        before = len(visited)
        visited.difference_update(retry_ids)
        print(f"이전 실패/구매불가 상품 재시도: {len(retry_ids)}건 (visited 해제 {before - len(visited)}건)")

    run = {
        "started_at": now_iso(),
        "requested": 0,
        "ok": 0,
        "parse_failed": 0,
        "http_error": 0,
        "sold_out": 0,
        "unavailable": 0,
        "unavailable_samples": [],
        "parse_fail_reasons": {},
        "parse_fail_samples": [],
        "skipped_not_beauty": 0,
        "skipped_bucket_full": 0,
        "skipped_excluded": {},
        "pruned_existing": {},
        "retry_ids": sorted(retry_ids),
        "queue_size": 0,
        "url_source": "",
        "scope": "다이소몰 뷰티관(C245) 10개 카테고리 (선케어·네일 제외)",
        "delay_seconds": DELAY,
        "max_items": MAX_ITEMS,
        "retry_failed": RETRY_FAILED,
        "retry_unavailable": RETRY_UNAVAILABLE,
        "user_agent": UA,
        "robots_note": "robots.txt: User-agent * → Allow /pd/pdr/, Crawl-delay 30",
    }

    tmap = cfg.get("bucket_targets") or {}
    flat = int(cfg.get("target_per_bucket") or 25)

    def target_of(b: str) -> int:
        return int(tmap.get(b, flat))

    queue = (load_json(QUEUE, {}) or {}).get("urls") or []
    queue = [u for u in queue if "/pd/pdr/" in u]
    run["queue_size"] = len(queue)
    run["url_source"] = "beauty_queue" if queue else "sitemap"

    urls = list(queue)
    if not urls:
        urls = state.get("urls") or []
    if not urls:
        urls = product_urls()
        if not urls:
            run.update(
                finished_at=now_iso(),
                status="blocked",
                message="sitemap.xml에서 상품 URL을 가져오지 못했습니다. 차단 또는 사이트 구조 변경 가능성.",
            )
            save_json(
                STATUS,
                {
                    "last_run": run,
                    "totals": summarize(products, buckets, {b: target_of(b) for b in buckets}),
                    "fx": status_before.get("fx"),
                },
            )
            print(json.dumps(run, ensure_ascii=False, indent=2))
            return 1
        random.seed(20260823)
        random.shuffle(urls)
        state["urls"] = urls
        state["sitemap_cached_at"] = now_iso()

    retry_urls = []
    retry_id_set = set(retry_ids)
    normal_urls = []
    for url in urls:
        m = re.search(r"pdNo=(\d+)", url)
        if m and m.group(1) in retry_id_set:
            retry_urls.append(url)
        else:
            normal_urls.append(url)
    urls = retry_urls + normal_urls
    if retry_urls:
        print(f"재시도 우선 URL: {len(retry_urls)}건")

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

        if status != 200:
            run["http_error"] += 1
            visited.add(pd_no)
        else:
            item = parse_product(pd_no, url, html)
            if item is None:
                info = dict(LAST_FAIL)
                if info.get("unavailable"):
                    run["unavailable"] += 1
                    if len(run["unavailable_samples"]) < 20:
                        run["unavailable_samples"].append(pd_no)
                    visited.discard(pd_no)
                elif info.get("sold_out"):
                    run["sold_out"] += 1
                    visited.discard(pd_no)
                else:
                    run["parse_failed"] += 1
                    why = info.get("reason", "?")
                    run["parse_fail_reasons"][why] = run["parse_fail_reasons"].get(why, 0) + 1
                    if len(run["parse_fail_samples"]) < 20:
                        run["parse_fail_samples"].append(info)
                    visited.discard(pd_no)
            else:
                visited.add(pd_no)
                drop = excluded(item, exclude_rules)
                if drop:
                    run["skipped_excluded"][drop] = run["skipped_excluded"].get(drop, 0) + 1
                    time.sleep(DELAY + random.uniform(0, 2))
                    continue
                bucket = classify(item, buckets)
                if bucket is None:
                    run["skipped_not_beauty"] += 1
                elif pd_no not in by_no and counts.get(bucket, 0) >= target_of(bucket):
                    run["skipped_bucket_full"] += 1
                else:
                    item["bucket"] = bucket
                    counts[bucket] = counts.get(bucket, 0) + 1
                    if pd_no in by_no:
                        products[by_no[pd_no]] = item
                    else:
                        by_no[pd_no] = len(products)
                        products.append(item)
                    run["ok"] += 1

        time.sleep(DELAY + random.uniform(0, 2))

    run["finished_at"] = now_iso()
    run["pruned_existing"] = pruned
    run["bucket_targets"] = {b: target_of(b) for b in buckets}
    run["buckets_short"] = {
        b: target_of(b) - counts.get(b, 0)
        for b in buckets
        if counts.get(b, 0) < target_of(b)
    }

    reached = run["ok"] + run["skipped_not_beauty"]
    if run["requested"] == 0:
        run["status"] = "nothing_to_do"
    elif reached == 0 and run["http_error"] == run["requested"]:
        run["status"] = "blocked"
        run["message"] = (
            "모든 요청이 HTTP 오류로 실패했습니다. "
            "GitHub Actions 러너의 해외 IP가 차단되었을 수 있습니다."
        )
    elif reached < run["requested"] / 2:
        run["status"] = "degraded"
    else:
        run["status"] = "ok"

    state["visited"] = sorted(visited)
    save_json(STATE, state)
    save_json(
        PRODUCTS,
        {
            "updated_at": now_iso(),
            "source": "daisomall.co.kr (robots.txt 허용 경로 /pd/pdr/)",
            "truth_note": "가격은 상품 페이지에 표시된 실제 원화 금액입니다. 배송비·관세·수수료는 확정 견적이 없어 계산하지 않습니다.",
            "count": len(products),
            "products": products,
        },
    )
    save_json(
        STATUS,
        {
            "last_run": run,
            "totals": summarize(products, buckets, {b: target_of(b) for b in buckets}),
            "fx": status_before.get("fx"),
            "sitemap_urls_known": len(urls),
            "visited": len(visited),
        },
    )
    print(json.dumps(run, ensure_ascii=False, indent=2))
    return 0 if run["status"] in ("ok", "degraded", "nothing_to_do") else 1


def tally(products: list) -> dict:
    c: dict = {}
    for p in products:
        b = p.get("bucket")
        if b:
            c[b] = c.get(b, 0) + 1
    return c


def summarize(products: list, buckets: dict, target) -> dict:
    """target 은 버킷별 dict 다. 단일값도 계속 받는다."""
    rows = {}
    for b in buckets:
        items = [p for p in products if p.get("bucket") == b]
        prices = [p["price_krw"] for p in items if isinstance(p.get("price_krw"), int)]
        rows[b] = {
            "count": len(items),
            "avg_price_krw": round(sum(prices) / len(prices)) if prices else None,
            "min_price_krw": min(prices) if prices else None,
            "max_price_krw": max(prices) if prices else None,
        }
    prices = [p["price_krw"] for p in products if isinstance(p.get("price_krw"), int)]
    return {
        "products": len(products),
        "bucket_targets": target,
        "by_bucket": {b: rows[b]["count"] for b in buckets},
        "categories": rows,
        "avg_price_krw": round(sum(prices) / len(prices)) if prices else None,
        "price_krw_min": min(prices) if prices else None,
        "price_krw_max": max(prices) if prices else None,
        "with_rating": sum(1 for p in products if p.get("rating") is not None),
    }


def record_crash(e: BaseException) -> None:
    """터졌다는 사실을 파일에 남긴다."""
    prev = load_json(STATUS, {})
    run = dict(prev.get("last_run") or {})
    run.update(
        finished_at=now_iso(),
        status="crashed",
        error=f"{type(e).__name__}: {str(e)[:200]}",
        message="수집 도중 예외로 중단됐다. 이 기록은 실패를 남기려고 쓴 것이며 totals 는 직전 성공분 그대로다.",
    )
    save_json(
        STATUS,
        {
            "last_run": run,
            "totals": prev.get("totals"),
            "fx": prev.get("fx"),
        },
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as _e:  # noqa: BLE001
        record_crash(_e)
        print(
            f"수집이 예외로 중단됐다: {type(_e).__name__}: {_e}",
            file=sys.stderr,
        )
        raise SystemExit(1)
