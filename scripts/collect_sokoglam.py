#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Soko Glam(미국 K뷰티 편집숍) 판매 목록 실수집 (2026-09-28).

왜
  우리 사업은 다이소 K뷰티를 미국에서 파는 것이다. 미국 판매 채널 중
  K뷰티 전문 편집숍의 판매가·브랜드 목록이 없었다. Soko Glam 은 Shopify
  스토어라 컬렉션별 공개 상품 JSON(/collections/<handle>/products.json)을 준다.
  페이지를 렌더링하지 않고, 사람이 보는 목록과 같은 데이터를 받는다.

robots.txt (2026-09-28 확인)
  User-agent: * 에 Allow: / . /cart /checkout 등만 막는다. 컬렉션 경로는 허용.
  하루 두세 번, 요청 사이에 쉬고, 신분을 밝힌 UA 로 부른다.

원칙
  - 받은 값만 쓴다. 가격은 판매 중인 옵션의 최저가 그대로(USD).
  - 품절 옵션만 있는 상품은 뺀다.
  - 순위는 컬렉션 표시 순서다. 판매량 수치가 아니다.
  - 실패하면 이전 성공분을 물려받고 사유를 남긴다.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "sokoglam_products.json"
BASE = "https://sokoglam.com"
UA = "Mozilla/5.0 (compatible; JARVIS-LUNA/1.0; +https://github.com/coar0000-wq/jarvis-luna)"
COLLECTIONS = (("best-sellers", "Best Sellers"), ("skincare", "Skincare"))
DELAY = 3.0


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch(handle: str) -> list[dict]:
    url = f"{BASE}/collections/{handle}/products.json?limit=250"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8")).get("products") or []


def rows_of(products: list[dict], collection: str) -> list[dict]:
    rows = []
    for rank, p in enumerate(products, 1):
        live = [v for v in p.get("variants") or [] if v.get("available")]
        if not live:
            continue
        prices = [float(v["price"]) for v in live if str(v.get("price") or "").strip()]
        rows.append({
            "rank": rank,
            "name": str(p.get("title") or "").strip(),
            "brand": str(p.get("vendor") or "").strip(),
            "price_usd": min(prices) if prices else None,
            "category": str(p.get("product_type") or "").strip(),
            "collection": collection,
            "url": f"{BASE}/products/{p.get('handle')}",
            "tags": [t for t in (p.get("tags") or []) if isinstance(t, str)][:12],
        })
    return [r for r in rows if r["name"]]


def main() -> int:
    products, errors, per = [], [], {}
    seen = set()
    for i, (handle, label) in enumerate(COLLECTIONS):
        if i:
            time.sleep(DELAY)
        try:
            rows = rows_of(fetch(handle), label)
        except Exception as exc:  # 한 컬렉션이 실패해도 다른 것은 받는다
            errors.append({"collection": handle, "error": f"{type(exc).__name__}: {exc}"[:160]})
            continue
        new = [r for r in rows if r["url"] not in seen]
        seen.update(r["url"] for r in new)
        per[label] = len(new)
        products += new
        print(f"  {label:12s} {len(rows)}건 (새로 담은 것 {len(new)}건)")

    stale_from = ""
    if not products and OUT.exists():
        prev = json.loads(OUT.read_text(encoding="utf-8"))
        products = prev.get("products") or []
        stale_from = prev.get("collected_at") or ""
    prices = sorted(p["price_usd"] for p in products if p.get("price_usd"))
    payload = {
        "source": "sokoglam.com 컬렉션 공개 상품 JSON (실수집)",
        "generator": "scripts/collect_sokoglam.py",
        "robots_note": "User-agent: * Allow: / · /cart /checkout 만 차단 (2026-09-28 확인)",
        "collected_at": now() if not stale_from else stale_from,
        "is_stale": bool(stale_from),
        "count": len(products),
        "by_collection": per,
        "errors": errors,
        "rank_note": "순위는 컬렉션 표시 순서다. 판매량 수치가 아니다.",
        "price_stats": ({"n": len(prices), "min": prices[0], "median": prices[len(prices) // 2],
                         "max": prices[-1]} if prices else {}),
        "products": products,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Soko Glam {len(products)}건 저장 · 오류 {len(errors)}건")
    return 0 if products else 1


if __name__ == "__main__":
    sys.exit(main())
