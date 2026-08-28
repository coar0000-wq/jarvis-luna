#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""다이소 상품 수집 + 실시간 환율(collection_status.fx) 갱신"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATUS = DATA / "daiso_real" / "collection_status.json"

URL = "https://www.daisomall.co.kr/ds/diy2/C245"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JarvisLunaBot/1.0)"}
KST = timezone(timedelta(hours=9))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def fetch_fx() -> dict:
    """여러 공개 API로 USD→KRW 환율을 가져온다. 실패 시 ok=False."""
    sources = [
        ("https://api.frankfurter.app/latest?from=USD&to=KRW", lambda d: float(d["rates"]["KRW"]), lambda d: d.get("date")),
        ("https://open.er-api.com/v6/latest/USD", lambda d: float(d["rates"]["KRW"]), lambda d: (d.get("time_last_update_utc") or "")[:10]),
        ("https://api.exchangerate-api.com/v4/latest/USD", lambda d: float(d["rates"]["KRW"]), lambda d: d.get("date")),
    ]
    for url, rate_fn, date_fn in sources:
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            krw = round(float(rate_fn(data)), 2)
            as_of = date_fn(data) or now_utc().astimezone(KST).strftime("%Y-%m-%d")
            result = {
                "usd_to_krw": krw,
                "krw_to_usd": round(1 / krw, 8),
                "as_of": as_of,
                "source": url.split("/v")[0] if "/v" in url else url,
                "api_url": url,
                "fetched_at": now_utc().isoformat(),
                "ok": True,
            }
            print(f"✅ 환율 갱신: 1 USD = {krw:,.2f} KRW (as_of={as_of})")
            return result
        except Exception as e:
            print(f"⚠️ 환율 API 실패 ({url}): {e}")
            continue
    return {
        "usd_to_krw": None,
        "krw_to_usd": None,
        "as_of": None,
        "source": None,
        "fetched_at": now_utc().isoformat(),
        "ok": False,
        "error": "all FX APIs failed",
    }


def update_collection_status_fx(fx: dict) -> None:
    """대시보드가 읽는 collection_status.json 의 fx 만 안전하게 갱신."""
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    if STATUS.exists():
        try:
            status = json.loads(STATUS.read_text(encoding="utf-8"))
        except Exception:
            status = {}
    else:
        status = {}
    status["fx"] = fx
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ {STATUS} fx 필드 갱신 완료")


def collect_products() -> list:
    products = []
    try:
        r = requests.get(URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup.find_all(["img", "strong", "span"]):
            title = tag.get("alt") or tag.get_text(strip=True)
            if not title or len(title) < 3:
                continue
            if title in [x["title"] for x in products]:
                continue
            products.append({
                "title": title,
                "category": "Beauty",
                "price": 0,
                "source": "Daiso Mall",
            })
            if len(products) >= 200:
                break
    except Exception as e:
        print(f"⚠️ 상품 수집 실패: {e}")
    return products


def main() -> None:
    DATA.mkdir(exist_ok=True)

    # 1) 환율 먼저 갱신 (대시보드 표시용)
    fx = fetch_fx()
    update_collection_status_fx(fx)

    # 2) 상품 수집
    products = collect_products()
    output = {
        "updated": now_utc().isoformat(),
        "products": products,
        "fx": fx,
    }
    out = DATA / "daiso_products.json"
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Daiso products: {len(products)}")


if __name__ == "__main__":
    main()
