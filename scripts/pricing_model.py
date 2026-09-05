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

# 관세를 누가 언제 내는가 — 두 방식이 있고 둘을 동시에 하면 고객이 두 번 낸다.
#
#   ddu  판매가에 관세를 녹인다. 우리가 배송사에 선납하는 계약(DDP 배송)이
#        있어야 성립한다. 없으면 고객이 물건 받을 때 관세 고지서를 또 받는다.
#   ddp  Shopify 가 결제 화면에서 고객에게 관세를 따로 받는다.
#        판매가에는 관세를 넣지 않는다.
#
# Shopify Managed Markets 는 2026-08-24 부터 DDU 지원을 폐지하고
# DDP 로 자동 전환했다. 즉 스토어를 열면 ddp 가 기본이 될 가능성이 높다.
# 다만 한국 발송 셀러 지원 여부는 개설 후 Markets 설정에서 확인해야 한다.
# 그래서 두 경우를 모두 산출해 두고 확인 후 고른다.
DUTY_MODES = ("ddu", "ddp")

# 판매 구성 (2026-09-04 결정)
#   광고를 하지 않기로 해서 CAC 가 0 이다. 그래서 단품도 흑자가 된다.
#   다만 2개 주문은 추가 배송비가 $1.30 뿐인데 매출은 두 배가 되므로
#   세트를 미는 편이 훨씬 유리하다.
#
#   할인율 15% 를 고른 이유
#     - 5~10% 는 미국 소비자에게 체감이 안 된다
#     - 20% 로 내리면 마진이 36.7% 로 떨어져 반품·파손 완충이 사라진다
#     - 15% 면 마진 40% 를 지키면서 단품 대비 순익 2.2배
#   무료배송은 2개 주문 배송비가 이미 원가에 포함돼 있어 추가 부담이 없다.
BUNDLE_SIZE = 2
BUNDLE_DISCOUNT = 0.15
FREE_SHIP_MIN_QTY = 2


def psych_price(v: float) -> float:
    """미국식 가격 표기. 0.99 로 올림."""
    import math
    return math.floor(v) + 0.99 if v >= 1 else round(v, 2)
# Shopify 국제 판매 실제 수수료 (2026-09-04 shopify.com/international/pricing 확인)
#   Shopify Payments 국제 blended  3.9%
#   Managed Markets                3.5%  (관세 계산·징수 무료 포함)
# 이전에는 국내 기준 2.9% + $0.30 을 쓰고 있었다. 국제는 2.5배다.
PAY_RATE, PAY_FIXED = 0.074, 0.0
PAY_NOTE = "Shopify Payments 국제 3.9% + Managed Markets 3.5% = 7.4%"
PACKAGING_G = 40            # 완충재 + 봉투 실측 대신 보수적 추정

OLIVEYOUNG = ROOT / "data" / "oliveyoung_us_products.json"


def market_benchmark() -> dict:
    """OliveYoung US 베스트셀러 실수집 가격으로 시장 기준을 잡는다.

    수집 결과가 없으면 빈 dict 를 돌려주고, 호출부는 가격을 산출하지 않는다.
    이전 버전은 사람이 눈으로 본 수치를 상수로 박아 뒀는데 그건 검증이 안 된다.
    """
    if not OLIVEYOUNG.exists():
        return {}
    try:
        d = json.loads(OLIVEYOUNG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    st = d.get("price_stats") or {}
    if not st.get("n"):
        return {}
    return {
        "min": st["min"], "p25": st["p25"],
        "median": st["median"], "max": st["max"],
        "n": st["n"],
        "source": (f"us.oliveyoung.com/best-sellers 실수집 {st['n']}건 "
                   f"({(d.get('collected_at') or '')[:10]})"),
    }


def ship_krw(grams: int) -> int:
    for w, cost in SMALL_PACKET_US:
        if grams <= w:
            return cost
    return SMALL_PACKET_US[-1][1]


MEASURED_PATH = ROOT / "data" / "weights.json"


def load_measured() -> dict:
    """저울로 잰 실제 배송 무게. 있으면 추정값보다 항상 우선한다.

    형식은 data/weights.json 의 measured 아래에 상품번호를 키로 둔다.
      {"measured": {"1045146": {"gram": 128, "note": "포장 포함 실측"}}}
    값이 없으면 빈 dict 를 돌려주고 추정으로 넘어간다. 지어내지 않는다.
    """
    try:
        d = json.loads(MEASURED_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for pd_no, v in (d.get("measured") or {}).items():
        g = v.get("gram") if isinstance(v, dict) else v
        if isinstance(g, (int, float)) and g > 0:
            out[str(pd_no)] = (int(round(g)),
                               (v.get("note") if isinstance(v, dict) else "") or "실측")
    return out


MEASURED = load_measured()


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


def analyze(p: dict, rate: float, per_order: int, MARKET: dict,
            duty_mode: str = "ddu") -> dict:
    name = p.get("name") or ""
    krw = int(p.get("price_krw") or 0)
    hit = MEASURED.get(str(p.get("pd_no")))
    if hit:
        grams, wnote = hit[0], hit[1]
        wsource = "measured"
    else:
        grams, wnote = est_weight(name)
        wsource = "estimated"

    cost = krw / rate
    # 주문당 n개를 함께 보낸다고 가정하면 배송비가 n분의 1로 나뉜다
    order_g = grams * per_order
    ship_total = ship_krw(order_g) / rate
    ship_unit = ship_total / per_order

    tariff = cost * TARIFF_RATE

    # ddu: 관세를 우리가 부담하므로 착지원가에 포함
    # ddp: 관세를 고객이 결제 시 별도 납부하므로 우리 원가에서 제외
    landed_ddu = cost + ship_unit + tariff
    landed_ddp = cost + ship_unit
    landed = landed_ddu if duty_mode == "ddu" else landed_ddp

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
        "weight_source": wsource,
        "unit_cost_usd": round(cost, 2),
        "shipping_unit_usd": round(ship_unit, 2),
        "shipping_order_usd": round(ship_total, 2),
        "tariff_usd": round(tariff, 2),
        "duty_mode": duty_mode,
        "landed_cost_usd": round(landed, 2),
        "landed_cost_ddu_usd": round(landed_ddu, 2),
        "landed_cost_ddp_usd": round(landed_ddp, 2),
        "customer_pays_duty_at_checkout": duty_mode == "ddp",
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

    MARKET = market_benchmark()
    if not MARKET:
        print("시장 벤치마크가 없습니다. scripts/collect_oliveyoung_us.py 를 먼저 실행하세요.")
        print("임의의 시장가를 쓰지 않고 중단합니다.")
        return 1

    # 기존 키(N개_묶음배송)는 ddu 기준으로 유지해 대시보드 호환을 지킨다.
    # duty_scenarios 에 두 방식을 모두 담아 비교 가능하게 한다.
    scenarios, duty_scenarios = {}, {}
    for mode in DUTY_MODES:
        for n in (1, 2, 3, 5):
            rows = [analyze(p, rate, n, MARKET, mode) for p in srec]
            duty_scenarios[f"{mode}_{n}개_묶음배송"] = rows
            if mode == "ddu":
                scenarios[f"{n}개_묶음배송"] = rows

    # 판매 구성별 권장가
    def offer(qty, disc, mode="ddu"):
        rows = duty_scenarios[f"{mode}_{qty}개_묶음배송"]
        land = sum(r["landed_cost_usd"] for r in rows) / len(rows)
        ship = sum(r["shipping_order_usd"] for r in rows) / len(rows)
        raw = MARKET["p25"] * qty * (1 - disc)
        price = psych_price(raw)
        fee = price * PAY_RATE + PAY_FIXED
        net = price - land * qty - fee
        return {
            "qty": qty,
            "discount_pct": round(disc * 100),
            "price_usd": round(price, 2),
            "unit_price_usd": round(price / qty, 2),
            "landed_cost_total_usd": round(land * qty, 2),
            "shipping_in_cost_usd": round(ship, 2),
            "fee_usd": round(fee, 2),
            "net_profit_usd": round(net, 2),
            "margin_pct": round(net / price * 100, 1),
            "free_shipping": qty >= FREE_SHIP_MIN_QTY,
            "orders_for_500usd": round(500 / net) if net > 0 else None,
        }

    single = offer(1, 0.0)
    bundle = offer(BUNDLE_SIZE, BUNDLE_DISCOUNT)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "exchange_rate": {"usd_to_krw": rate, "as_of": fx.get("as_of"),
                          "source": fx.get("source")},
        "cost_basis": {
            "shipping": SHIPPING_SOURCE,
            "tariff": f"{TARIFF_RATE:.0%} - 미국 화장품 HTS 3304 한국산 상호관세",
            "de_minimis": ("$800 면세 한도는 2025-08-29 전 국가 폐지, "
                           "2026-06-24 CBP 무기한 유예. 소액 소포도 과세 대상."),
            "payment_fee": PAY_NOTE,
            "weight": (
                f"실측 {len(MEASURED)}건은 data/weights.json 값을 썼다. "
                "나머지는 다이소에 무게 정보가 없어 용량 표기로 추정한 값이라 실측이 필요하다."
            ),
            "not_included": ["광고비(CAC)", "반품/파손", "Shopify 월 구독료",
                             "포장 자재비", "미국 주 판매세", "환율 변동"],
        },
        "market_benchmark": MARKET,
        "duty_mode_note": {
            "선택_필요": True,
            "ddu": ("관세를 판매가에 녹인다. 배송사와 관세 선납(DDP 배송) 계약이 "
                    "있어야 성립한다. 없으면 고객이 수령 시 관세를 또 낸다."),
            "ddp": ("Shopify 가 결제 화면에서 고객에게 관세를 따로 받는다. "
                    "판매가에는 관세를 넣지 않는다."),
            "주의": "두 방식을 동시에 적용하면 고객이 관세를 두 번 낸다.",
            "shopify_현황": ("Managed Markets 는 2026-08-24 부터 DDU 지원을 폐지하고 "
                           "DDP 로 자동 전환. 스토어 개설 후 Markets 설정에서 "
                           "한국 발송 셀러 지원 여부를 확인할 것."),
            "기본값": "ddu (scenarios 키가 이 기준. 확인 후 변경)",
        },
        "offers": {
            "single": single,
            "bundle": bundle,
            "free_shipping_min_qty": FREE_SHIP_MIN_QTY,
            "bundle_vs_single": (round(bundle["net_profit_usd"] / single["net_profit_usd"], 1)
                                 if single["net_profit_usd"] > 0 else None),
            "판단_근거": (
                f"{BUNDLE_DISCOUNT:.0%} 할인을 고른 이유: 5~10%는 미국 소비자에게 체감이 없고, "
                "20%면 마진이 36.7%로 떨어져 반품·파손 완충이 사라진다. "
                "15%면 마진 40%를 지키면서 단품 대비 순익 2.2배다. "
                "무료배송은 2개 주문 배송비가 이미 원가에 포함돼 추가 부담이 없다."),
            "광고비": "0 (매출이 붙기 전까지 광고하지 않기로 결정)",
        },
        "scenarios": scenarios,
        "duty_scenarios": duty_scenarios,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    print(f"환율 {rate} KRW/USD | 관세 {TARIFF_RATE:.0%} | 수수료 {PAY_NOTE}")
    print(f"시장 벤치마크(올리브영 US): 하위25% ${MARKET['p25']} / 중앙값 ${MARKET['median']}\n")
    print(f"\n[권장 판매 구성]  광고비 0 기준")
    for lbl, o in (("단품", single), (f"{BUNDLE_SIZE}개 세트", bundle)):
        fs = " + 무료배송" if o["free_shipping"] else ""
        print(f"  {lbl:8s} ${o['price_usd']:6.2f}  개당 ${o['unit_price_usd']:5.2f}  "
              f"할인 {o['discount_pct']:2d}%{fs}")
        print(f"           원가 ${o['landed_cost_total_usd']:5.2f} + 수수료 ${o['fee_usd']:4.2f} "
              f"→ 순익 ${o['net_profit_usd']:+5.2f} (마진 {o['margin_pct']:.0f}%) "
              f"· 월$500에 {o['orders_for_500usd']}건")
    print()

    sell = MARKET.get("p25") or 0
    print(f"{'방식':6s} {'묶음':6s} {'착지원가':>9s} {'손익분기':>9s} "
          f"{'판매가':>8s} {'순익':>8s} {'마진':>7s}  고객 관세 부담")
    for mode in DUTY_MODES:
        for n in (1, 2, 3, 5):
            rows = duty_scenarios[f"{mode}_{n}개_묶음배송"]
            land = sum(r["landed_cost_usd"] for r in rows) / len(rows)
            be = sum(r["breakeven_usd"] for r in rows) / len(rows)
            fee = sell * PAY_RATE + PAY_FIXED / n
            net = sell - land - fee
            duty = sum(r["tariff_usd"] for r in rows) / len(rows)
            who = f"결제 시 +${duty:.2f}" if mode == "ddp" else "없음 (판매가에 포함)"
            print(f"{mode:6s} {n}개    ${land:8.2f} ${be:8.2f} "
                  f"${sell:7.2f} ${net:7.2f} {net/sell*100:6.1f}%  {who}")
    print(f"\n저장 -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
