#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gemini 영문 카피를 Shopify 상품 임포트 CSV 로 변환한다.

입력  data/shopify_listing_copy.json
      data/pricing_model.json                  (실배송 원가 모델)
      data/daiso_real/collection_status.json   (실시간 환율)
출력  data/shopify_import.csv

Shopify 규격 근거
  help.shopify.com/en/manual/products/import-export/using-csv
  - 신규 상품 임포트 시 필수 컬럼은 Title 뿐이다.
  - UTF-8, LF 개행으로 저장해야 한다.
  - Tags 는 쉼표로 구분한 한 셀에 담는다.
  - 단일 변형 상품은 Option1 name=Title, Option1 value=Default Title 을 쓴다.

가격 산정 (2026-08-31 개정)
  이전에는 원가 x 2.2 였는데 배송비·관세·결제수수료가 빠져 있어
  S등급 10건 전부 적자였다. 이제 pricing_model.json 을 쓴다.

  착지원가 = 다이소 원가 + 국제배송비(5개 묶음 분담) + 관세 15%
  판매가   = 미국 시장 벤치마크 하위 25% (올리브영 US 실조회)
  Compare-at = 시장 중앙값. 할인 대비 효과용.

  판매가가 손익분기 아래면 그 상품은 CSV 에서 제외하고 사유를 남긴다.
  원가 모델이 없으면 가격을 비운다. 임의의 배수를 쓰지 않는다.

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
PRICING = ROOT / "data" / "pricing_model.json"
STATUS = ROOT / "data" / "daiso_real" / "collection_status.json"
OUT = ROOT / "data" / "shopify_import.csv"
REPORT = ROOT / "data" / "shopify_import_report.json"

VENDOR = os.environ.get("SHOPIFY_VENDOR", "MD family")
# 몇 개 묶음 배송을 전제로 배송비를 분담할지. 기본 5개.
BUNDLE = os.environ.get("SHOPIFY_BUNDLE", "5개_묶음배송")

COLUMNS = [
    "Title", "URL handle", "Description", "Vendor", "Type", "Tags",
    "Published on online store", "Status", "SKU",
    "Option1 name", "Option1 value",
    "Price", "Cost per item", "Charge tax",
    "Inventory tracker", "Inventory quantity",
    "Continue selling when out of stock",
    "Compare-at price",
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

    # 실배송 원가 모델
    price_by_no, pm_note, market = {}, "원가 모델 없음 - 가격 비움", {}
    if PRICING.exists():
        try:
            pm = json.loads(PRICING.read_text(encoding="utf-8"))
            for r in (pm.get("scenarios") or {}).get(BUNDLE, []):
                price_by_no[str(r.get("pd_no"))] = r
            market = pm.get("market_benchmark") or {}
            pm_note = (f"{BUNDLE} 기준 · 관세 {pm.get('cost_basis',{}).get('tariff','')} · "
                       f"{pm.get('cost_basis',{}).get('shipping','')}")
        except (OSError, json.JSONDecodeError):
            pass

    sell_price = float(market.get("p25") or 0)
    compare_at = float(market.get("median") or 0)

    rate = 0.0
    fx_note = "환율 조회 실패"
    if STATUS.exists():
        try:
            fx = (json.loads(STATUS.read_text(encoding="utf-8")) or {}).get("fx") or {}
            rate = float(fx.get("usd_to_krw") or 0)
            if rate:
                fx_note = f"{rate} KRW/USD ({fx.get('as_of','')}) {fx.get('source','')}"
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    # 등록 게이트. 네 조건을 모두 통과한 상품만 CSV 에 넣는다.
    # 고시·실측·법률이 비어 있는 상품이 스토어에 올라가는 것을 막는 장치다.
    gate_path = ROOT / "data" / "listing_gate.json"
    gate = {}
    gate_note = "listing_gate.json 없음 - 게이트 미적용"
    try:
        g = json.loads(gate_path.read_text(encoding="utf-8-sig"))
        gate = {str(r.get("pd_no")): r for r in g.get("items") or []}
        gate_note = (f"listing_gate.json {g.get('generated_at','')[:19]} 기준 "
                     f"등록 가능 {g.get('ready',0)}/{g.get('total',0)}")
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass

    rows, skipped = [], []
    for it in doc.get("items", []):
        gr = gate.get(str(it.get("pd_no")))
        if gr and not gr.get("listing_ready"):
            LABEL = {"copy": "카피", "gosi": "고시", "price": "실측 무게", "legal": "법률 검토"}
            miss = ", ".join(LABEL.get(b, b) for b in gr.get("blocked_by") or [])
            skipped.append({"pd_no": it.get("pd_no"), "name_ko": it.get("name_ko"),
                            "reason": f"등록 게이트 미통과 - {miss} 미완료"})
            continue
        c = it.get("copy")
        if not c:
            skipped.append({"pd_no": it.get("pd_no"), "name_ko": it.get("name_ko"),
                            "reason": it.get("error") or "카피 없음"})
            continue

        pr = price_by_no.get(str(it.get("pd_no")))
        if pr and sell_price > 0:
            landed = float(pr["landed_cost_usd"])
            breakeven = float(pr["breakeven_usd"])
            if sell_price <= breakeven:
                skipped.append({
                    "pd_no": it.get("pd_no"), "name_ko": it.get("name_ko"),
                    "reason": (f"시장가 ${sell_price:.2f} 가 손익분기 "
                               f"${breakeven:.2f} 이하라 적자")})
                continue
            cost = round(landed, 2)          # Cost per item = 착지원가
            price = round(sell_price, 2)
            cmp_at = round(compare_at, 2) if compare_at > sell_price else ""
        else:
            skipped.append({"pd_no": it.get("pd_no"), "name_ko": it.get("name_ko"),
                            "reason": "원가 모델에 해당 상품이 없어 가격 산출 불가"})
            continue

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
            "Compare-at price": cmp_at,
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
        "listing_gate": gate_note,
        "skipped": skipped,
        "exchange_rate": fx_note,
        "pricing_model": pm_note,
        "bundle_assumption": BUNDLE,
        "sell_price_usd": sell_price,
        "compare_at_usd": compare_at,
        "market_benchmark": market,
        "vendor": VENDOR,
        "가격_근거": (
            "Cost per item 은 다이소 원가에 국제배송비와 관세 15% 를 더한 착지원가다. "
            f"배송비는 {BUNDLE} 을 전제로 분담한 값이라, 낱개로 팔리면 실제 원가가 더 높다. "
            f"판매가 ${sell_price:.2f} 는 미국 시장 하위 25% 값이며 "
            f"Compare-at ${compare_at:.2f} 는 시장 중앙값이다."),
        "게시전_확인사항": [
            f"판매가가 {BUNDLE} 전제다. 2개 이상 묶음 구매를 유도하지 못하면 "
            "배송비 분담이 깨져 적자가 난다. 무료배송 최소 주문금액을 걸어야 한다.",
            "광고비(CAC)가 계산에 없다. 뷰티 신규 스토어 CAC 를 감안하면 "
            "객단가를 올리지 못할 경우 마진이 남지 않는다.",
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
    print(f"원가 모델: {pm_note}")
    if rows:
        print(f"판매가 ${sell_price:.2f} (시장 하위25%) / Compare-at ${compare_at:.2f} (중앙값)")
    if skipped:
        print(f"제외 {len(skipped)}건:")
        for s in skipped:
            print(f"  - {s['name_ko']} :: {s['reason'][:60]}")
    if not rows and gate:
        # 게이트가 전부 막은 경우는 오류가 아니라 정상 판정이다.
        print("등록 가능한 상품이 없다. 고시·실측·법률을 채우면 열린다.")
        return 0
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
