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
import os
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

try:
    from .product_change_ledger import (offer_groups, best_from_rows, below_policy, thresholds,
        rows_index, archive_items, proof_record, append_changes, deletion_manifest, encode,
        LEDGER_PATH, MANIFEST_PATH, PRODUCT_PATH, ARCHIVE_PATH)
except ImportError:
    from product_change_ledger import (offer_groups, best_from_rows, below_policy, thresholds,
        rows_index, archive_items, proof_record, append_changes, deletion_manifest, encode,
        LEDGER_PATH, MANIFEST_PATH, PRODUCT_PATH, ARCHIVE_PATH)

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
    if not path.exists():
        return deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode(doc))


def rule() -> dict:
    if not RULE.exists():
        raise ValueError("profitability_rule.json missing: no exclusion without explicit policy")
    cfg = load(RULE, None)
    thresholds(cfg)
    return cfg


def best_offer(pricing: dict) -> dict[str, dict]:
    return {pd_no: best_from_rows(rows) for pd_no, rows in offer_groups(pricing).items()}


def judge(row: dict, cfg: dict) -> tuple[bool, str]:
    bad = below_policy(row, cfg)
    if not bad:
        return False, ""
    return True, (f"가장 나은 형태({row.get('form')} {row.get('qty')}개) "
                  f"마진 {row['margin_pct']}% · 순익 ${row['net_profit_usd']} · "
                  f"최저선 {cfg['min_margin_pct']}% / ${cfg['min_net_profit_usd']} 미달")


def products_rows(doc) -> list:
    rows_index(doc)
    return doc['products'] if isinstance(doc, dict) else doc


def main() -> int:
    apply_it = "--apply" in sys.argv
    restore = "--restore" in sys.argv
    cfg = rule()
    if not PRICING.exists():
        print("NO_CHANGE: pricing_model.json missing; no monetary evidence")
        return 0
    pricing_bytes = PRICING.read_bytes()
    pricing = json.loads(pricing_bytes)
    grouped = offer_groups(pricing)
    best = {pd_no: best_from_rows(offers) for pd_no, offers in grouped.items()}
    if not best:
        print("NO_CHANGE: no observed offers; no products changed")
        return 0
    if not PRODUCTS.exists():
        raise ValueError("operating products missing")
    before = PRODUCTS.read_bytes()
    prod_doc = json.loads(before)
    rows = products_rows(prod_doc)
    by_id = rows_index(prod_doc)
    ex_doc = load(EXCLUDED, {"items": {}, "count": 0})
    ex_items = archive_items(ex_doc)
    for pd_no, rec in ex_items.items():
        if rec.get('원본') and str(pd_no) in by_id:
            raise ValueError("operating/archive identity overlap: " + str(pd_no))
    ledger_file, manifest_file = ROOT / LEDGER_PATH, ROOT / MANIFEST_PATH
    ledger = load(ledger_file, None)
    manifest = load(manifest_file, None)
    changes = []
    new_doc, new_archive = deepcopy(prod_doc), deepcopy(ex_doc)
    new_items = new_archive['items']
    now = datetime.now(timezone.utc).isoformat()
    execution_id = os.environ.get('DAISO_EXECUTION_ID') or (
        os.environ['GITHUB_RUN_ID'] + ':' + os.environ.get('GITHUB_RUN_ATTEMPT','1')
        if os.environ.get('GITHUB_RUN_ID') else 'local:' + uuid.uuid4().hex)
    if restore:
        for pd_no, rec in sorted(ex_items.items()):
            if rec.get('뺀_규칙') != REASON_TAG or pd_no not in best:
                continue
            saved = rec.get('원본')
            if not isinstance(saved, dict) or str(saved.get('pd_no') or saved.get('product_id') or '') != str(pd_no):
                print("NO_RESTORE: verified archived original missing: " + str(pd_no))
                continue
            bad, why = judge(best[pd_no], cfg)
            if not bad:
                changes.append((str(pd_no), 'restore', deepcopy(saved)))
                rows.append(deepcopy(saved))
                del new_items[pd_no]
    else:
        for pd_no, original in sorted(by_id.items()):
            if pd_no not in best:
                continue
            bad, why = judge(best[pd_no], cfg)
            if bad:
                changes.append((pd_no, 'exclude', deepcopy(original)))
                offer = best[pd_no]
                new_items[pd_no] = {
                    'name': original.get('name'), '뺀_규칙': REASON_TAG, '왜': why,
                    '그때_숫자': deepcopy(offer), '기준': thresholds(cfg), '뺀_시각': now,
                    '되돌리는_법': 'scripts/daiso/exclude_unprofitable.py --restore --apply',
                    '원본': deepcopy(original),
                }
        drop = {pd_no for pd_no, action, _ in changes if action == 'exclude'}
        rows = [row for row in rows if str(row.get('pd_no') or row.get('product_id') or '') not in drop]
    if not changes:
        print("NO_CHANGE: no actual operating/archive identity changes")
        return 0
    print(f"{'RESTORE' if restore else 'EXCLUDE'}: actual changes={len(changes)}; operating products={len(rows)}")
    if not apply_it:
        print("DRY_RUN: product/archive/ledger/deletion manifest bytes unchanged")
        return 0
    if isinstance(new_doc, dict):
        new_doc['products'] = rows
        new_doc['count'] = len(rows)
    else:
        new_doc = rows
    rows_index(new_doc)
    new_archive['count'] = len(new_items)
    new_archive['generated_at'] = now
    new_archive.setdefault('generator', 'scripts/daiso/exclude_unprofitable.py')
    new_archive['손익_규칙_출처'] = 'data/daiso_real/profitability_rule.json'
    after = encode(new_doc)
    rule_bytes = RULE.read_bytes()
    records = [proof_record(pd_no, action, original, grouped[pd_no], cfg,
                           pricing_bytes, rule_bytes, before, after, execution_id, now)
               for pd_no, action, original in changes]
    ledger = append_changes(ledger, records, pricing_bytes)
    changed_path = ARCHIVE_PATH if restore else PRODUCT_PATH
    manifest = deletion_manifest(ROOT, manifest, changed_path,
                                 [pd_no for pd_no, _, _ in changes],
                                 'Verified deterministic profitability ' + ('restore' if restore else 'exclude') + ' with preserved original evidence')
    PRODUCTS.write_bytes(after)
    save(EXCLUDED, new_archive)
    save(ledger_file, ledger)
    if manifest is not None:
        save(manifest_file, manifest)
    print("CHANGE_PROOF_SAVED: exact product hashes, observed offers, thresholds and archived originals")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
