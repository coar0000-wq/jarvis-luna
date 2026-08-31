#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gemini 영문 카피를 Shopify 상품 임포트 CSV 로 변환한다.

입력  data/shopify_listing_copy.json
      data/daiso_real/collection_status.json  (실시간 환율)
출력  data/shopify_import.csv

Shopify 규격 근거
  help.shopify.com/en/manual/products/import-export/using-csv
  - 신규 상품 임포트 시 필수 컬럼은 Title 뿐이다.
  - UTF-8, LF 개행으로 저장해야 한다.
  - Tags 는 쉼표로 구분한 한 셀에 담는다.
  - 단일 변형 상품은 Option1 name=Title, Option1 value=Default Title 을 쓴다.

가격 산정
  원가(USD) = 다이소 실측 원화가 / 실시간 환율
  판매가     = 원가 x MARKUP (기본 2.2)
  MARKUP 은 가정이지 실측이 아니다. CSV 와 리포트에 그렇게 명시한다.
  환율 조회에 실패하면 가격을 비운다. 임의의 환율을 쓰지 않는다.

주의
  Weight 는 다이소 수집 데이터에 없어서 0 으로 둔다.
  배송비 계산 전에 반드시 실제 무게를 채워야 한다.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPY = ROOT / "data" / "shopify_listing_copy.json"
STATUS = ROOT / "data" / "daiso_real" / "collection_status.json"
OUT = ROOT / "data" / "shopify_import.csv"
REPORT = ROOT / "data" / "shopify_import_report.json"

MARKUP = float(os.environ.get("SHOPIFY_MARKUP", "2.2"))
VENDOR = os.environ.get("SHOPIFY_VENDOR", "MD family")

COLUMNS = [
    "Title", "URL handle", "Description", "Vendor", "Type", "Tags",
    "Published on online store", "Status", "SKU",
    "Option1 name", "Option1 value",
    "Price", "Cost per item", "Charge tax",
    "Inventory tracker", "Inventory quantity",
    "Continue selling when out of stock",
    "Weight value (grams)", "Weight unit for display", "Requires shipping",
    "Fulfillment service",
    "Product image URL", "Image position", "Image alt text",
    "SEO title", "SEO description",
]


def handle_of(title: str, pd_no: str) -> str:
    h = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    h = re.sub(r"-{2,}", "-", h)[:80].strip("-")
    return f"{h}-{pd_no}" if h else f"daiso-{pd_no}"


def clean_tag(t: str) -> str:
    t = re.sub(r"[^a-z0-9\- ]+", "", str(t).lower()).strip()
    return re.sub(r"\s+", "-", t)[:40]


def main() -> int:
    if not COPY.exists():
        print(f"입력 없음: {COPY}. 먼저 scripts/gemini_listing_copy.py 를 실행하세요.")
        return 1
    doc = json.loads(COPY.read_text(encoding="utf-8"))

    rate = 0.0
    fx_note = "환율 조회 실패 - 가격 비움"
    if STATUS.exists():
        try:
            fx = (json.loads(STATUS.read_text(encoding="utf-8")) or {}).get("fx") or {}
            rate = float(fx.get("usd_to_krw") or 0)
            if rate:
                fx_note = f"{rate} KRW/USD ({fx.get('as_of','')}) {fx.get('source','')}"
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    rows, skipped = [], []
    for it in doc.get("items", []):
        c = it.get("copy")
        if not c:
            skipped.append({"pd_no": it.get("pd_no"), "name_ko": it.get("name_ko"),
                            "reason": it.get("error") or "카피 없음"})
            continue

        krw = int(it.get("price_krw") or 0)
        if rate > 0 and krw > 0:
            cost = round(krw / rate, 2)
            price = round(cost * MARKUP, 2)
        else:
            cost = price = ""

        tags = [clean_tag(t) for t in (c.get("tags") or [])]
        tags = [t for t in tags if t][:15]

        rows.append({
            "Title": c["title"][:255],
            "URL handle": handle_of(c["title"], str(it.get("pd_no") or "")),
            "Description": c["description_html"],
            "Vendor": VENDOR,
            "Type": c.get("product_type", ""),
            "Tags": ", ".join(tags),
            "Published on online store": "false",   # 검수 전 비공개
            "Status": "draft",                      # 사람이 확인 후 active 로
            "SKU": f"DAISO-{it.get('pd_no')}",
            "Option1 name": "Title",
            "Option1 value": "Default Title",
            "Price": price,
            "Cost per item": cost,
            "Charge tax": "true",
            "Inventory tracker": "shopify",
            "Inventory quantity": 0,
            "Continue selling when out of stock": "deny",
            "Weight value (grams)": 0,      # 실측 무게 없음 - 배송 설정 전 필수 입력
            "Weight unit for display": "g",
            "Requires shipping": "true",
            "Fulfillment service": "manual",
            "Product image URL": it.get("image_url") or "",
            "Image position": 1 if it.get("image_url") else "",
            "Image alt text": c["title"][:125],
            "SEO title": c["seo_title"][:70],
            "SEO description": c["seo_description"][:320],
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Shopify 요구: UTF-8, LF 개행
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "csv": "data/shopify_import.csv",
        "rows": len(rows),
        "skipped": skipped,
        "exchange_rate": fx_note,
        "markup": MARKUP,
        "vendor": VENDOR,
        "가격_근거": ("원가는 다이소 실측 원화가를 실시간 환율로 나눈 값이다. "
                   f"판매가는 원가 x {MARKUP} 로, 이 배수는 검증된 수치가 아니라 가정이다."),
        "게시전_확인사항": [
            "Status 를 draft 로, 공개를 false 로 두었다. 검수 후 직접 active 로 바꿔야 한다.",
            "Weight value (grams) 가 0 이다. 다이소 수집 데이터에 무게가 없어 비워 두었으므로 "
            "배송비를 계산하려면 실제 무게를 채워야 한다.",
            "Inventory quantity 가 0 이다. 실제 확보 수량을 입력해야 판매가 된다.",
            "Product image URL 은 다이소 CDN 주소다. 저작권 확인 후 자체 촬영본으로 교체하는 것이 안전하다.",
            "영문 카피는 Gemini 생성물이므로 효능 표현과 성분 표기를 사람이 확인해야 한다.",
        ],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")

    print(f"CSV {len(rows)}건 -> {OUT.relative_to(ROOT)}")
    print(f"환율: {fx_note}")
    if skipped:
        print(f"제외 {len(skipped)}건:")
        for s in skipped:
            print(f"  - {s['name_ko']} :: {s['reason'][:60]}")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
