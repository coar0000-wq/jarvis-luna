#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""한국→미국 실배송 기준 단가 모델.

기존 대시보드의 "원가 x 2.2" 는 배송비·관세·결제수수료가 하나도 없는
껍데기 계산이었다. 이 스크립트는 실제 비용을 전부 넣어 손익을 계산한다.

비용 근거 (전부 2026-08-31 실조회)
  배송  우체국 국제통상 소형포장물 미국행 요금표
        ems.epost.go.kr/front.EmsDeliveryDelivery072.postal
  관세  미국 화장품 HTS 3304 한국산 상호관세 15%
        de minimis($800 면세)는 2025-08-29 전 국가 폐지,
        2026-06-24 CBP 무기한 유예로 소액 소포도 과세 대상
  환율  data/daiso_real/collection_status.json 의 실시간 조회값
  수수료 Shopify 표준 온라인 결제 2.9% + $0.30

무게는 다이소 수집 데이터에 없다. 상품명의 용량(ml/g)으로 추정하되
추정임을 명시한다. 실제 배송 전 반드시 저울로 재야 한다.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCORE = ROOT / "data" / "daiso_real" / "shopify_demand_score.json"
SREC = ROOT / "data" / "daiso_real" / "shopify_s_recommendations.json"
STATUS = ROOT / "data" / "daiso_real" / "collection_status.json"
OUT = ROOT / "data" / "pricing_model.json"

# 우체국 국제통상 소형포장물 · 미국행 (원). 실제 요금표 그대로.
SMALL_PACKET_US = [
    (100, 8410), (200, 9420), (300, 10430), (400, 11440), (500, 13490),
    (600, 14440), (700, 15390), (800, 16340), (900, 17290), (1000, 18230),
    (1100, 20130), (1200, 21430), (1300, 22730), (1400, 24030), (1500, 24910),
    (1600, 26210), (1700, 28110), (1800, 30010), (1900, 31910), (2000, 33810),
]
SHIPPING_SOURCE = ("우체국 국제통상 소형포장물 미국행 요금표 "
                   "(ems.epost.go.kr, 2026-08-31 조회)")

TARIFF_RATE = 0.15          # 미국 화장품 HTS 3304 한국산 상호관세
PAY_RATE, PAY_FIXED = 0.029, 0.30   # Shopify 결제수수료
PACKAGING_G = 40            # 완충재 + 봉투 실측 대신 보수적 추정

# 올리브영 미국 홈 노출 상품 실가격 (2026-08-31 조회, n=69)
MARKET = {"min": 5.99, "p25": 20.0, "median": 26.0, "max": 299.0,
          "source": "us.oliveyoung.com 노출 상품 69건 실조회 2026-08-31"}


def ship_krw(grams: int) -> int:
    for w, cost in SMALL_PACKET_US:
        if grams <= w:
            return cost
    return SMALL_PACKET_US[-1][1]


def est_weight(name: str) -> tuple[int, str]:
    """상품명의 용량 표기로 무게를 추정한다. 추정 근거를 함께 반환."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ml|g|mL|ML|G)\b", name)
    if not m:
        return 150 + PACKAGING_G, "용량 표기 없음 - 150g 가정"
    v = float(m.group(1))
    unit = m.group(2).lower()
    # 화장품 내용물 비중 약 1.0, 용기는 내용물의 60% 정도로 잡는다(보수적)
    content = v if unit in ("ml", "g") else v
    total = int(round(content * 1.6)) + PACKAGING_G
    return total, f"{int(v)}{unit} x 1.6(용기) + {PACKAGING_G}g(포장) 추정"


def analyze(p: dict, rate: float, per_order: int) -> dict:
    name = p.get("name") or ""
    krw = int(p.get("price_krw") or 0)
    grams, wnote = est_weight(name)

    cost = krw / rate
    # 주문당 n개를 함께 보낸다고 가정하면 배송비가 n분의 1로 나뉜다
    order_g = grams * per_order
    ship_total = ship_krw(order_g) / rate
    ship_unit = ship_total / per_order

    tariff = cost * TARIFF_RATE
    landed = cost + ship_unit + tariff        # 결제수수료 전 원가

    def profit(sell: float) -> dict:
        fee = sell * PAY_RATE + (PAY_FIXED / per_order)
        net = sell - landed - fee
        return {"sell": round(sell, 2), "fee": round(fee, 2),
                "profit": round(net, 2),
                "margin_pct": round(net / sell * 100, 1) if sell else 0}

    # 손익분기 판매가: sell - landed - (sell*r + fixed/n) = 0
    breakeven = (landed + PAY_FIXED / per_order) / (1 - PAY_RATE)

    return {
        "pd_no": p.get("pd_no"), "name": name, "bucket": p.get("bucket"),
        "shopify_score": p.get("shopify_score"),
        "price_krw": krw,
        "weight_g_est": grams, "weight_note": wnote,
        "unit_cost_usd": round(cost, 2),
        "shipping_unit_usd": round(ship_unit, 2),
        "shipping_order_usd": round(ship_total, 2),
        "tariff_usd": round(tariff, 2),
        "landed_cost_usd": round(landed, 2),
        "breakeven_usd": round(breakeven, 2),
        "at_2_2x": profit(cost * 2.2),          # 현재 대시보드 가정
        "at_market_p25": profit(MARKET["p25"]),
        "at_market_median": profit(MARKET["median"]),
    }


def main() -> int:
    if not SCORE.exists() or not SREC.exists():
        print("점수 파일이 없습니다.")
        return 1
    try:
        fx = (json.loads(STATUS.read_text(encoding="utf-8")) or {}).get("fx") or {}
        rate = float(fx.get("usd_to_krw") or 0)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        rate = 0
    if not rate:
        print("환율이 없습니다. 임의 환율을 쓰지 않고 중단합니다.")
        return 1

    detail = {str(x["pd_no"]): x for x in
              json.loads(SCORE.read_text(encoding="utf-8"))["all_scored"]}
    srec = json.loads(SREC.read_text(encoding="utf-8"))["recommendations"]
    for p in srec:
        p.update({k: v for k, v in (detail.get(str(p["pd_no"])) or {}).items()
                  if k not in p})

    scenarios = {}
    for n in (1, 3, 5):
        scenarios[f"{n}개_묶음배송"] = [analyze(p, rate, n) for p in srec]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "exchange_rate": {"usd_to_krw": rate, "as_of": fx.get("as_of"),
                          "source": fx.get("source")},
        "cost_basis": {
            "shipping": SHIPPING_SOURCE,
            "tariff": f"{TARIFF_RATE:.0%} - 미국 화장품 HTS 3304 한국산 상호관세",
            "de_minimis": ("$800 면세 한도는 2025-08-29 전 국가 폐지, "
                           "2026-06-24 CBP 무기한 유예. 소액 소포도 과세 대상."),
            "payment_fee": f"{PAY_RATE:.1%} + ${PAY_FIXED} (Shopify 표준)",
            "weight": "다이소 데이터에 무게 없음. 용량 표기로 추정한 값이므로 실측 필요.",
            "not_included": ["광고비(CAC)", "반품/파손", "Shopify 월 구독료",
                             "포장 자재비", "미국 주 판매세", "환율 변동"],
        },
        "market_benchmark": MARKET,
        "scenarios": scenarios,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    print(f"환율 {rate} KRW/USD | 관세 {TARIFF_RATE:.0%} | 결제 {PAY_RATE:.1%}+${PAY_FIXED}")
    print(f"시장 벤치마크(올리브영 US): 하위25% ${MARKET['p25']} / 중앙값 ${MARKET['median']}\n")
    for label, rows in scenarios.items():
        loss = sum(1 for r in rows if r["at_2_2x"]["profit"] < 0)
        avg_be = sum(r["breakeven_usd"] for r in rows) / len(rows)
        avg_land = sum(r["landed_cost_usd"] for r in rows) / len(rows)
        print(f"[{label}] 평균 착지원가 ${avg_land:.2f} | 손익분기 ${avg_be:.2f} | "
              f"2.2배 가격에서 적자 {loss}/{len(rows)}건")
    print(f"\n저장 -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
