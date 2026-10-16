#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""카테고리 전담팀 목록 수집 (다이소몰 공개 카테고리 목록).

왜 (2026-10-11 사용자 지시)
  "스킨케어 = 다이소 스킨케어 종류(스킨/토너·에센스/세럼/앰플·크림·로션·미스트/픽서)",
  "바디 = https://www.daisomall.co.kr/ds/exhCtgr/C208/CTGR_01050/CTGR_01061/CTGR_01113 목록".
  전담팀 범위를 이름 추정이 아니라 다이소몰이 실제로 분류한 카테고리 목록으로 정한다.

어떻게
  다이소몰 카테고리 화면이 쓰는 공개 목록 호출(/ssn/search/SearchGoods, isCategory=1)을
  config/daiso_commerce_strategy.json 의 category_desks 카테고리마다 부른다.
  로그인·키가 필요 없고, 화면에 보이는 값(이름·가격·리뷰·누적주문·소분류)만 담는다.
  호출 사이에 쉰다. 실패하면 이전 파일을 지우지 않고 오류만 남긴다(빈 목록으로 덮지 않는다).

출력  data/daiso_real/desk_catalog.json
  desks.<desk>.products[] = {pd_no, name, price_krw, rating, review_count, total_orders,
                             small_category, small_category_code, sold_out, url, image_url}
  build_beauty_queue.py 는 이 목록을 수집 큐 앞쪽에 넣고,
  score_shopify_demand.py 는 이 목록으로 상품의 전담팀을 정한다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "daiso_commerce_strategy.json"
OUT = ROOT / "data" / "daiso_real" / "desk_catalog.json"
API = "https://www.daisomall.co.kr/ssn/search/SearchGoods"
PRODUCT = "https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo={}"
CDN = "https://cdn.daisomall.co.kr"
PER_PAGE = 100
MAX_PAGES = int(os.environ.get("DESK_CATALOG_MAX_PAGES", "5"))
DELAY = float(os.environ.get("DESK_CATALOG_DELAY", "2"))
UA = "Mozilla/5.0 (JARVIS desk catalog; +https://github.com/coar0000-wq/jarvis-luna)"


def to_int(v) -> int:
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def to_float(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def fetch(code: str, page: int) -> dict:
    q = {"searchTerm": "", "searchQuery": "", "pageNum": page, "brndCd": "", "cntPerPage": PER_PAGE,
         "userId": "", "newPdYn": "", "massOrPsblYn": "", "pkupOrPsblYn": "", "fdrmOrPsblYn": "",
         "quickOrPsblYn": "", "searchSort": "", "isCategory": 1, "exhCtgrNo": code,
         "largeExhCtgrNo": "CTGR_01050", "mallId": "MALL_MAIN"}
    req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(q)}",
                                 headers={"User-Agent": UA, "Referer": "https://www.daisomall.co.kr/"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def documents(payload: dict) -> tuple[int, list[dict]]:
    total, docs = 0, []
    for block in ((payload or {}).get("resultSet") or {}).get("result") or []:
        if isinstance(block, dict) and block.get("resultDocuments") is not None:
            total = to_int(block.get("totalSize"))
            docs = [d for d in block.get("resultDocuments") or [] if isinstance(d, dict)]
    return total, docs


def row(doc: dict) -> dict | None:
    pd_no = str(doc.get("pdNo") or "").strip()
    if not pd_no:
        return None
    img = str(doc.get("pdImgUrl") or "").strip()
    return {"pd_no": pd_no, "name": str(doc.get("pdNm") or doc.get("exhPdNm") or "").strip(),
            "price_krw": to_int(doc.get("pdPrc")), "rating": to_float(doc.get("avgStscVal")),
            "review_count": to_int(doc.get("revwCnt")), "total_orders": to_int(doc.get("totOrQy")),
            "small_category": str(doc.get("exhSmallCtgrNm") or "").strip(),
            "small_category_code": str(doc.get("exhSmallCtgrNo") or doc.get("exhCtgrNo") or "").strip(),
            "sold_out": str(doc.get("soldOutYn") or "").upper() == "Y",
            "url": PRODUCT.format(pd_no), "image_url": (CDN + img) if img.startswith("/") else img}


def valid_category_page(payload: dict, total: int, docs: list[dict]) -> bool:
    """Validate the same final document block that documents() selects.

    Missing/malformed envelopes must not look like an explicitly empty category.
    Keep validation separate from extraction so legacy products/errors are retained.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("resultSet"), dict):
        return False
    blocks = payload["resultSet"].get("result")
    if not isinstance(blocks, list):
        return False
    block = next((b for b in reversed(blocks)
                  if isinstance(b, dict) and b.get("resultDocuments") is not None), None)
    if block is None:
        return False
    raw_total = block.get("totalSize")
    total_text = str(raw_total).strip().replace(",", "")
    raw_docs = block.get("resultDocuments")
    if not total_text.isdecimal() or not isinstance(raw_docs, list):
        return False
    if len(docs) != len(raw_docs) or any(not str(d.get("pdNo") or "").strip() for d in docs):
        return False
    return (total == 0 and not docs) or (total > 0 and bool(docs))


def collect(cfg: dict) -> dict:
    desks, errors, calls = {}, [], 0
    for desk, spec in cfg.items():
        if desk.startswith("_") or not isinstance(spec, dict):
            continue
        seen, cats = {}, []
        for cat in spec.get("categories") or []:
            code, got, total = cat.get("code"), 0, 0
            listing, totals = {}, []
            fetch_status, valid_pages = "ok", True
            reached_end = False
            for page in range(1, MAX_PAGES + 1):
                if calls:
                    time.sleep(DELAY)
                calls += 1
                try:
                    payload = fetch(code, page)
                    total, docs = documents(payload)
                except Exception as e:  # noqa: BLE001 - 네트워크 오류는 기록만 하고 다음 카테고리로
                    errors.append({"desk": desk, "category": cat.get("name"), "code": code, "page": page,
                                   "error": f"{type(e).__name__}: {e}"[:200]})
                    fetch_status = "error"
                    break
                valid_pages = valid_category_page(payload, total, docs) and valid_pages
                totals.append(total)
                for d in docs:
                    r = row(d)
                    if r and r["pd_no"] not in listing:
                        listing[r["pd_no"]] = r
                    if r and r["pd_no"] not in seen:
                        seen[r["pd_no"]] = r
                        got += 1
                if not docs or page * PER_PAGE >= total:
                    reached_end = True
                    break
            if fetch_status == "ok":
                if not valid_pages or len(set(totals)) != 1:
                    fetch_status = "invalid_response"
                elif not reached_end:
                    fetch_status = "truncated"
                elif len(listing) != total:
                    fetch_status = "incomplete"
            cats.append({**cat, "site_total": total, "collected": got,
                         "fetched_at": datetime.now(timezone.utc).isoformat(),
                         "fetch_status": fetch_status, "complete": fetch_status == "ok",
                         "listing_products": list(listing.values())})
        products = sorted(seen.values(), key=lambda r: (-r["total_orders"], -r["review_count"], r["pd_no"]))
        desks[desk] = {"name": spec.get("name"), "source": spec.get("source"), "categories": cats,
                       "product_count": len(products), "products": products}
    return {"desks": desks, "errors": errors, "calls": calls}


def main(argv=()) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desk', choices=('skincare', 'makeup', 'body'))
    parser.add_argument('--output', help='Repository-relative output, e.g. out/body_shower_catalog.json')
    args = parser.parse_args(argv)
    out = OUT
    if args.output:
        supplied = Path(args.output)
        out = (ROOT / supplied).resolve()
        if supplied.is_absolute() or not out.is_relative_to(ROOT.resolve()) or out == ROOT.resolve():
            print('DESK_CATALOG_FAIL output must be a repository-relative file')
            return 2
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8")).get("category_desks") or {}
    except (OSError, ValueError) as e:
        print(f"DESK_CATALOG_SKIP config unreadable: {e}")
        return 0
    if not cfg:
        print("DESK_CATALOG_SKIP no category_desks in config")
        return 0
    if args.desk:
        if args.desk not in cfg:
            print(f'DESK_CATALOG_FAIL configured desk missing: {args.desk}')
            return 2
        cfg = {args.desk: cfg[args.desk]}
    got = collect(cfg)
    old = {}
    if out.exists():
        try:
            old = json.loads(out.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
    desks = got["desks"]
    # 한 전담팀이 0건이면(네트워크 실패 등) 이전 목록을 그대로 둔다. 빈 목록으로 덮지 않는다.
    kept_previous = []
    for desk, info in desks.items():
        prev = (old.get("desks") or {}).get(desk)
        if not info["products"] and prev and prev.get("products"):
            desks[desk] = {**prev, "kept_previous_because": "이번 수집 0건"}
            kept_previous.append(desk)
    doc = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
           "generator": "scripts/daiso/collect_desk_catalog.py",
           "source": "daisomall.co.kr 카테고리 화면 공개 목록 (/ssn/search/SearchGoods, isCategory=1)",
           "why": "사용자 지시 2026-10-11: 전담팀 범위 = 다이소몰 카테고리 목록 그대로",
           "calls": got["calls"], "errors": got["errors"], "kept_previous": kept_previous,
           "desks": desks}
    if not any(d.get("products") for d in desks.values()):
        print(f"DESK_CATALOG_FAIL no products; errors={got['errors'][:3]}")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("DESK_CATALOG_OK " + " ".join(f"{k}={v['product_count']}" for k, v in desks.items())
          + f" calls={got['calls']} errors={len(got['errors'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
