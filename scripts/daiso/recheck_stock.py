#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""이미 모아둔 상품이 지금도 살 수 있는지 다시 본다.

왜 필요한가
  수집기는 한 번 본 상품을 다시 보지 않는다(crawl_state 의 visited).
  30초 간격을 지켜야 해서 그렇게 만든 것인데, 그러면 한 번 모은 상품은
  영영 그때 상태로 남는다.

  09-09 에 문제가 드러났다. S등급 1위 '드롭비 탄탄 광채 앰플' 을
  직접 열어보니 이렇게 적혀 있었다.

    og:description ... [가격 5,000원, 리뷰 4.8점(1198건), 품절]

  품절이어도 og:title 에 가격이 그대로 있어서 파싱은 성공한다. 그래서
  품절 상품이 정상 상품으로 저장됐고 미국 등록 후보 1위까지 올라갔다.
  살 수 없는 물건을 등록할 뻔했다.

  수집기는 고쳤다. 이제 성공 경로에서도 품절을 읽는다. 그런데 이미
  모아둔 202건은 그 표시가 없다. 그것들을 다시 봐야 한다.

무엇을 하나
  등록 후보(S·A등급)부터 다시 받는다. 그 상품들이 실제로 미국에
  올라갈 것들이라 틀리면 손해가 가장 크다.

  결과를 products.json 에 되쓴다.
    sold_out          품절 표시가 있으면 True
    gone              페이지에서 상품이 사라졌으면 True
    price_krw         값이 바뀌었으면 갱신하고 이전 값을 남긴다
    stock_checked_at  언제 확인했는지

  지우지는 않는다. 품절은 되돌아온다. 등급을 고르는 쪽
  (score_shopify_demand.py 의 qualify_s)이 표시를 보고 거른다.

robots.txt
  daisomall.co.kr 은 /pd/pdr/ 을 허용하고 Crawl-delay 30 을 요구한다.
  그래서 한 건에 30초다. S+A 가 40건이면 20분이다. 그 시간을 지킨다.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_daiso import (BASE, DELAY, fetch, parse_product,  # noqa: E402
                           LAST_FAIL)

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "data" / "daiso_real"
PRODUCTS = D / "products.json"
SCORE = D / "shopify_demand_score.json"
REPORT = D / "stock_recheck.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def items_of(doc):
    if isinstance(doc, list):
        return doc
    for k in ("products", "items"):
        if isinstance(doc.get(k), list):
            return doc[k]
    return []


def pick(grades: set, limit: int) -> list:
    """다시 볼 상품을 고른다. 등급이 높은 것부터, 확인이 오래된 것부터."""
    sc = load(SCORE, {}) or {}
    rows = sc.get("all_scored") or []
    order = {"S": 0, "A": 1, "B": 2, "C": 3}
    want = [r for r in rows if str(r.get("grade", "")).upper() in grades]
    want.sort(key=lambda r: (order.get(str(r.get("grade", "")).upper(), 9),
                             str(r.get("stock_checked_at") or "")))
    return [str(r["pd_no"]) for r in want if r.get("pd_no")][:limit]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grades", default="S,A")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    doc = load(PRODUCTS)
    if doc is None:
        print(f"::error::{PRODUCTS.name} 을 못 읽었다")
        return 1
    rows = items_of(doc)
    by_no = {str(x.get("pd_no")): x for x in rows}

    grades = {g.strip().upper() for g in args.grades.split(",") if g.strip()}
    targets = pick(grades, args.limit)
    if not targets:
        print("다시 볼 상품이 없다. 점수 파일이 비었을 수 있다.")
        return 0

    print(f"다시 볼 상품 {len(targets)}건 (등급 {','.join(sorted(grades))}) "
          f"· 한 건에 {DELAY:.0f}초 → 약 {len(targets) * DELAY / 60:.0f}분")

    changed, gone, soldout, errors = [], [], [], []
    for i, pd_no in enumerate(targets, 1):
        if i > 1:
            time.sleep(DELAY + random.uniform(0, 2))
        url = f"{BASE}/pd/pdr/SCR_PDR_0001?pdNo={pd_no}"
        status, html = fetch(url)
        row = by_no.get(pd_no)
        if row is None:
            continue
        row["stock_checked_at"] = now_iso()

        if status != 200:
            errors.append({"pd_no": pd_no, "status": status})
            print(f"  [{i}/{len(targets)}] {pd_no} HTTP {status}")
            continue

        item = parse_product(pd_no, url, html)
        if item is None:
            info = dict(LAST_FAIL)
            if info.get("gone"):
                row["gone"] = True
                row["stock_note"] = "페이지에서 상품이 사라졌다"
                gone.append(pd_no)
                print(f"  [{i}/{len(targets)}] {pd_no} 내려감")
            else:
                errors.append({"pd_no": pd_no, "reason": info.get("reason")})
                print(f"  [{i}/{len(targets)}] {pd_no} 읽기 실패 "
                      f"- {info.get('reason')}")
            continue

        row["gone"] = False
        was_price = row.get("price_krw")
        row["sold_out"] = bool(item.get("sold_out"))
        row["stock_note"] = item.get("stock_note")
        if item.get("price_krw") and item["price_krw"] != was_price:
            row["price_krw_before"] = was_price
            row["price_krw"] = item["price_krw"]
            changed.append({"pd_no": pd_no, "before": was_price,
                            "after": item["price_krw"]})
        if row["sold_out"]:
            soldout.append(pd_no)
        mark = "품절" if row["sold_out"] else "판매 중"
        print(f"  [{i}/{len(targets)}] {pd_no} {mark} "
              f"· {item.get('price_krw')}원 · {str(item.get('name'))[:24]}")

    for path, body in ((PRODUCTS, doc), (REPORT, {
            "생성": now_iso(),
            "만든이": "scripts/daiso/recheck_stock.py",
            "왜": ("한 번 모은 상품은 다시 보지 않아서 품절·단종을 놓쳤다. "
                  "09-09 에 S등급 1위가 품절 상태로 등록 후보에 올라 있었다."),
            "확인": len(targets),
            "품절": len(soldout),
            "내려감": len(gone),
            "가격변동": len(changed),
            "오류": len(errors),
            "품절_목록": soldout,
            "내려감_목록": gone,
            "가격변동_목록": changed,
            "오류_목록": errors,
        })):
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(body, ensure_ascii=False, indent=2) + "\n"
        for _ in range(4):
            path.write_text(text, encoding="utf-8")
            if load(path) is not None:
                break
            time.sleep(0.5)
        else:
            print(f"기록 검증 실패: {path.name}", file=sys.stderr)
            return 1

    print(f"\n확인 {len(targets)}건 · 품절 {len(soldout)} · 내려감 {len(gone)} "
          f"· 가격변동 {len(changed)} · 오류 {len(errors)}")
    if soldout or gone:
        print("::warning::등록 후보 중 지금 살 수 없는 상품이 있다. "
              "점수를 다시 계산하면 S등급에서 빠진다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
