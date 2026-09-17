#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""손익이 안 나는 상품을 수집 대상에서 뺀다.

왜 만들었나 (2026-09-17)

  사용자가 말했다.  "손익분기 미달이면 수집하지마"

  category_map.json 의 exclude 에 이런 주석이 있다.

    "전에는 상세를 받은 뒤 법률팀이 걸렀다. 그러면 robots.txt
     Crawl-delay 30 때문에 한 건에 30초씩 버린다.
     어차피 못 파는 것은 처음부터 안 받는다."

  같은 이야기를 돈으로 하는 것이다. 다만 시점이 다르다.

    이름으로 거르는 것   받기 전에 된다   (이미 있다)
    돈으로 거르는 것     받아봐야 안다     (이 파일)

  무게와 용량과 시장가를 알아야 착지원가가 나온다. 그래서 한 번은
  받아야 한다. 대신 한 번 계산한 뒤로는 다시 받지 않는다.

무엇을 기준으로 빼나

  상품 하나에 판매 형태가 여럿이다. 단품과 2개 묶음이 있고 원가와
  수수료가 다르다. 그래서 형태 중 가장 나은 것으로 판단한다.
  단품이 손해라도 묶음으로 남으면 파는 방법이 있는 것이다.

  손익분기만 넘으면 되는 것이 아니다. VT 시카 카밍 토너 300 ml 이
  그랬다.

    단품 $14.99  마진 -5.7%  (손익분기 $15.92 미달)
    묶음 $24.99  마진  0.2%  순익 $0.04

  묶음은 형식상 손익분기를 넘는다. 그런데 $0.04 다. 반품 한 건,
  파손 한 건이면 사라진다. pricing_model.py 주석에도 같은 말이 있다.

    "20%면 마진이 36.7%로 떨어져 반품·파손 완충이 사라진다"

  그래서 최저 마진선을 둔다. 기본값은 data/daiso_real/profitability_rule.json
  에 있고 코드에 박지 않는다. 사업 판단이 바뀌면 그 파일만 고친다.

되돌릴 수 있게 남긴다

  환율·배송비·시장가가 바뀌면 같은 상품이 다시 팔릴 수 있다.
  그래서 지우지 않고 excluded_products.json 에 그때의 숫자와 함께
  남긴다. --restore 로 다시 계산해 살아나는 것을 되돌린다.

쓰는 법
  python -u scripts/daiso/exclude_unprofitable.py            보기만
  python -u scripts/daiso/exclude_unprofitable.py --apply    실제로 뺀다
  python -u scripts/daiso/exclude_unprofitable.py --restore  다시 계산해 복귀
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
DAISO = DATA / "daiso_real"

PRICING = DATA / "pricing_model.json"
PRODUCTS = DAISO / "products.json"
EXCLUDED = DAISO / "excluded_products.json"
RULE = DAISO / "profitability_rule.json"

REASON_TAG = "손익·마진 미달"

DEFAULT_RULE = {
    "생성": "2026-09-17",
    "왜": (
        "손익분기만 넘으면 되는 것이 아니다. 순익 $0.04 짜리는 반품 한 건이면 "
        "사라진다. 팔수록 일만 늘고 남는 것이 없다. 그래서 최저선을 둔다."
    ),
    "판단_방법": (
        "상품마다 판매 형태(단품·묶음)가 여럿이다. 그중 가장 나은 형태로 본다. "
        "단품이 손해라도 묶음으로 남으면 파는 방법이 있는 것이다."
    ),
    "min_margin_pct": 15.0,
    "min_net_profit_usd": 1.5,
    "기준_근거": (
        "pricing_model.py 는 마진 36.7% 를 '반품·파손 완충이 사라지는 선' 으로 "
        "적고 40% 를 지키는 쪽을 골랐다. 코칭 루프의 목표는 '마진 50%+' 다. "
        "여기 15% 는 그 목표가 아니라 '이 아래는 볼 것도 없다' 는 바닥이다. "
        "목표까지 올리면 지금 후보 대부분이 빠지므로 바닥만 막는다. "
        "숫자를 올리고 싶으면 이 파일만 고친다."
    ),
    "되돌리기": (
        "환율·배송비·시장가가 바뀌면 같은 상품이 다시 팔릴 수 있다. "
        "--restore 로 다시 계산해 기준을 넘긴 것을 products.json 으로 되돌린다."
    ),
}


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def save(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def rule() -> dict:
    r = load(RULE, None)
    if not isinstance(r, dict):
        save(RULE, DEFAULT_RULE)
        print(f"기준 파일을 만들었다 -> {RULE.relative_to(ROOT)}")
        return DEFAULT_RULE
    return r


def best_offer(pricing: dict) -> dict[str, dict]:
    """상품별로 가장 나은 판매 형태를 고른다.

    마진이 높은 쪽을 고르되, 마진이 같으면 순익이 큰 쪽을 고른다.
    """
    obp = pricing.get("offers_by_product") or {}
    best: dict[str, dict] = {}
    for form, rows in obp.items():
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                continue
            pd_no = str(r.get("pd_no") or "").strip()
            if not pd_no:
                continue
            m = r.get("margin_pct")
            n = r.get("net_profit_usd")
            if m is None or n is None:
                continue
            cur = best.get(pd_no)
            key = (float(m), float(n))
            if cur is None or key > (float(cur["margin_pct"]),
                                     float(cur["net_profit_usd"])):
                best[pd_no] = {**r, "form": form}
    return best


def judge(row: dict, cfg: dict) -> tuple[bool, str]:
    """기준 미달이면 (True, 사유)."""
    m = float(row.get("margin_pct") or 0)
    n = float(row.get("net_profit_usd") or 0)
    min_m = float(cfg.get("min_margin_pct", 15.0))
    min_n = float(cfg.get("min_net_profit_usd", 1.5))

    if row.get("register_blocked"):
        return True, (f"가장 나은 형태({row.get('form')} {row.get('qty')}개)도 "
                      f"손익분기 미달: {row.get('block_reason') or ''}".strip())
    if m < min_m or n < min_n:
        return True, (f"가장 나은 형태({row.get('form')} {row.get('qty')}개) "
                      f"마진 {m}% · 순익 ${n} — 최저선 마진 {min_m}% · "
                      f"순익 ${min_n} 미달")
    return False, ""


def products_rows(doc) -> list:
    if isinstance(doc, dict):
        return doc.get("products") or []
    return doc if isinstance(doc, list) else []


def main() -> int:
    apply_it = "--apply" in sys.argv
    restore = "--restore" in sys.argv

    cfg = rule()
    pricing = load(PRICING, {})
    if not pricing:
        print("pricing_model.json 이 없다. 가격 모델을 먼저 돌린다.")
        return 0

    best = best_offer(pricing)
    if not best:
        print("상품별 판매 형태가 없다. 뺄 근거가 없으므로 아무것도 하지 않는다.")
        return 0

    prod_doc = load(PRODUCTS, {})
    rows = products_rows(prod_doc)
    ex_doc = load(EXCLUDED, {})
    ex_items = ex_doc.get("items") or {}

    now = datetime.now(timezone.utc).isoformat()

    # ── 되돌리기 ────────────────────────────────────────────
    if restore:
        back = []
        for pd_no, rec in list(ex_items.items()):
            if rec.get("뺀_규칙") != REASON_TAG:
                continue
            row = best.get(str(pd_no))
            if not row:
                continue
            bad, _ = judge(row, cfg)
            if not bad:
                saved = rec.get("원본")
                if saved:
                    rows.append(saved)
                ex_items.pop(pd_no, None)
                back.append(f"{pd_no} {rec.get('name')}")
        if back:
            print(f"기준을 다시 넘긴 {len(back)}건을 되돌린다:")
            for b in back:
                print(f"  {b}")
            if apply_it:
                if isinstance(prod_doc, dict):
                    prod_doc["products"] = rows
                    prod_doc["count"] = len(rows)
                    save(PRODUCTS, prod_doc)
                ex_doc["items"] = ex_items
                ex_doc["count"] = len(ex_items)
                save(EXCLUDED, ex_doc)
                print("되돌렸다.")
            else:
                print("(--apply 를 붙여야 실제로 되돌린다)")
        else:
            print("되돌릴 것이 없다.")
        return 0

    # ── 미달 판정 ───────────────────────────────────────────
    by_id = {}
    for r in rows:
        if isinstance(r, dict):
            pid = str(r.get("pd_no") or r.get("product_id") or "").strip()
            if pid:
                by_id[pid] = r

    drop, keep = [], []
    for pd_no, row in sorted(best.items()):
        bad, why = judge(row, cfg)
        if bad:
            drop.append((pd_no, row, why))
        else:
            keep.append((pd_no, row))

    print(f"가격이 계산된 상품 {len(best)}건 · 기준 통과 {len(keep)} · 미달 {len(drop)}")
    print(f"기준: 마진 {cfg.get('min_margin_pct')}% 이상 "
          f"· 순익 ${cfg.get('min_net_profit_usd')} 이상 (가장 나은 판매 형태)")

    if not drop:
        print("미달 상품이 없다.")
        return 0

    print()
    for pd_no, row, why in drop:
        here = " (상품 목록에 있음)" if pd_no in by_id else " (이미 목록에 없음)"
        print(f"  {pd_no} {str(row.get('name'))[:40]}{here}")
        print(f"     {why}")

    if not apply_it:
        print("\n(--apply 를 붙여야 실제로 뺀다)")
        return 0

    removed = 0
    for pd_no, row, why in drop:
        original = by_id.get(pd_no)
        ex_items[pd_no] = {
            "name": row.get("name"),
            "뺀_규칙": REASON_TAG,
            "왜": why,
            "그때_숫자": {
                "form": row.get("form"),
                "qty": row.get("qty"),
                "price_usd": row.get("price_usd"),
                "landed_cost_total_usd": row.get("landed_cost_total_usd"),
                "fee_usd": row.get("fee_usd"),
                "net_profit_usd": row.get("net_profit_usd"),
                "margin_pct": row.get("margin_pct"),
                "market_median_usd": row.get("market_median_usd"),
            },
            "기준": {
                "min_margin_pct": cfg.get("min_margin_pct"),
                "min_net_profit_usd": cfg.get("min_net_profit_usd"),
            },
            "뺀_시각": now,
            "되돌리는_법": "scripts/daiso/exclude_unprofitable.py --restore --apply",
        }
        if original is not None:
            ex_items[pd_no]["원본"] = original
            removed += 1

    rows = [r for r in rows
            if str((r or {}).get("pd_no") or (r or {}).get("product_id") or "")
            not in {p for p, _, _ in drop}]

    if isinstance(prod_doc, dict):
        prod_doc["products"] = rows
        prod_doc["count"] = len(rows)
        save(PRODUCTS, prod_doc)

    ex_doc.setdefault("generator", "scripts/daiso/prune_excluded_products.py")
    ex_doc["generated_at"] = now
    ex_doc.setdefault(
        "왜_남기나",
        "규칙이 다시 바뀌어 되살려야 할 때 근거가 필요하다. 지우면 왜 뺐는지도 같이 사라진다.")
    ex_doc["손익_규칙_출처"] = str(RULE.relative_to(ROOT))
    ex_doc["items"] = ex_items
    ex_doc["count"] = len(ex_items)
    save(EXCLUDED, ex_doc)

    print(f"\n상품 목록에서 {removed}건을 뺐다. 남은 상품 {len(rows)}건.")
    print(f"사유와 그때 숫자는 {EXCLUDED.relative_to(ROOT)} 에 남겼다.")
    print("환율·배송비·시장가가 바뀌면 --restore 로 되돌릴 수 있다.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                                          # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("::error::손익 제외기가 예상 못한 예외로 멈췄다.", file=sys.stderr)
        sys.exit(1)
