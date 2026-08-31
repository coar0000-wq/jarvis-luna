#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OliveYoung US 베스트셀러 실수집기.

수집원  https://us.oliveyoung.com/best-sellers.data
        페이지가 클라이언트 렌더링이라 HTML 에는 상품이 없다.
        React Router 의 turbo-stream 데이터 응답을 직접 파싱한다.

robots.txt 준수 (2026-08-31 확인)
  Allow: /            -> /best-sellers 허용
  Disallow: /search   -> 검색 경로는 절대 요청하지 않는다
  Crawl-delay 명시 없음. 그래도 요청 간 대기를 둔다.

원칙 (CLAUDE.md: 거짓말 데이터 금지 / 가짜 데이터 금지)
  - 이전 oliveyoung_us_discovery.py 는 "curated bestseller mirror" 라는 이름의
    하드코딩 15건이었다. 그것을 대체하는 실수집기다.
  - 파싱에 실패하면 빈 목록을 저장하고 사유를 남긴다. 지어내지 않는다.
  - 각 항목에 product_id 와 상세 URL 을 남겨 검증 가능하게 한다.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "oliveyoung_us_products.json"

BASE = "https://us.oliveyoung.com"
DATA_URL = f"{BASE}/best-sellers.data"
TIMEOUT = 40
RETRIES = 3
DELAY = 3.0

# Cloudflare 가 비브라우저 요청을 403 으로 막는다. 실제 브라우저 헤더를 맞춘다.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
    "Referer": f"{BASE}/best-sellers",
    "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Connection": "keep-alive",
}

# turbo-stream 형식
#   전체가 하나의 JSON 배열이고, 객체는 {"_<키인덱스>": <값인덱스>} 로 표현된다.
#   즉 {"_66":475} 는 "키 = arr[66], 값 = arr[475]" 를 뜻한다.
#   문자열 키가 중복 저장되지 않아 "product_name" 이 파일 전체에 한 번만 나온다.
#   따라서 정규식으로는 첫 상품밖에 못 잡는다. 반드시 인덱스를 해석해야 한다.

MAX_DEPTH = 30


def resolve(arr: list, node, depth: int = 0):
    """turbo-stream 노드를 일반 파이썬 값으로 되돌린다."""
    if depth > MAX_DEPTH:
        return None
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if not (isinstance(k, str) and k.startswith("_")):
                continue
            try:
                key = arr[int(k[1:])]
            except (ValueError, IndexError):
                continue
            if not isinstance(key, str):
                continue
            try:
                val = arr[v] if isinstance(v, int) and 0 <= v < len(arr) else v
            except IndexError:
                val = None
            out[key] = resolve(arr, val, depth + 1)
        return out
    if isinstance(node, list):
        return [resolve(arr, arr[x] if isinstance(x, int) and 0 <= x < len(arr) else x,
                        depth + 1) for x in node]
    return node


def walk_products(arr: list):
    """product_id 와 product_name 을 동시에 가진 객체만 상품으로 인정한다."""
    found, seen = [], set()
    for node in arr:
        if not isinstance(node, dict):
            continue
        obj = resolve(arr, node)
        if not isinstance(obj, dict):
            continue
        pid = obj.get("product_id")
        name = obj.get("product_name")
        if not (isinstance(pid, str) and pid.startswith("UA") and isinstance(name, str) and name):
            continue
        if pid in seen:
            continue
        seen.add(pid)
        found.append(obj)
    return found


def dig(obj, *path):
    cur = obj
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def fetch(url: str) -> tuple[str, str]:
    last = ""
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read().decode("utf-8", "replace"), ""
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (403, 429, 500, 502, 503):
                time.sleep(DELAY * attempt)
                continue
            return "", last
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(DELAY * attempt)
    return "", last


def parse(body: str) -> list[dict]:
    try:
        arr = json.loads(body.strip().split("\n")[0])
    except json.JSONDecodeError as e:
        print(f"turbo-stream JSON 파싱 실패: {e}")
        return []
    if not isinstance(arr, list):
        print("최상위가 배열이 아님")
        return []

    rows = []
    for obj in walk_products(arr):
        pid = obj["product_id"]
        price = dig(obj, "price", "sale", "min", "amount")
        if price is None:
            price = dig(obj, "price", "original", "min", "amount")
        orig = dig(obj, "price", "original", "min", "amount")
        rows.append({
            "rank": len(rows) + 1,
            "product_id": pid,
            "product": obj["product_name"].strip(),
            "brand": (obj.get("brand_name") or "").strip(),
            "price_usd": float(price) if isinstance(price, (int, float)) else None,
            "original_price_usd": float(orig) if isinstance(orig, (int, float)) else None,
            "currency": dig(obj, "price", "currency") or "USD",
            "rating": obj.get("rating") if isinstance(obj.get("rating"), (int, float)) else None,
            "review_count": obj.get("review_count") if isinstance(obj.get("review_count"), int) else None,
            "is_soldout": bool(obj.get("is_soldout")),
            "image_url": obj.get("image_url") or "",
            "url": f"{BASE}/products/{pid}",
        })
    return rows


def main() -> int:
    body, err = fetch(DATA_URL)
    products, reason = [], ""
    if err:
        reason = f"수집 실패: {err}"
        print(reason)
    else:
        products = parse(body)
        if not products:
            reason = ("응답은 받았으나 상품을 파싱하지 못함. "
                      "turbo-stream 필드 구조가 바뀌었을 수 있음.")
            print(reason)

    priced = [p for p in products if p["price_usd"]]
    prices = sorted(p["price_usd"] for p in priced)

    payload = {
        "source": "us.oliveyoung.com/best-sellers (실수집)",
        "method": "React Router turbo-stream 데이터 응답 파싱",
        "robots_note": ("robots.txt 확인: Allow / 이며 /best-sellers 는 허용 경로. "
                        "Disallow 인 /search 는 요청하지 않음."),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "count": len(products),
        "reason": reason,
        "price_stats": ({
            "n": len(prices),
            "min": prices[0],
            "p25": prices[len(prices) // 4],
            "median": prices[len(prices) // 2],
            "max": prices[-1],
        } if prices else {}),
        "products": products,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    print(f"{len(products)}건 수집 -> {OUT.relative_to(ROOT)}")
    if prices:
        s = payload["price_stats"]
        print(f"가격대: ${s['min']} ~ ${s['max']} | 하위25% ${s['p25']} | 중앙값 ${s['median']}")
    return 0 if products else 1


if __name__ == "__main__":
    sys.exit(main())
