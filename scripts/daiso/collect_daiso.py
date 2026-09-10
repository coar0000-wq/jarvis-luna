#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
다이소몰 실제 상품 데이터 수집기.

원칙
----
* 측정한 값만 저장한다. 가격은 상품 페이지에 실제로 표시된 원화 금액이고,
  환율은 공개 API에서 받은 실시간 값이다. 배송비·관세·수수료처럼 아직
  확정되지 않은 값은 계산하지 않는다.
* 수집에 실패하면 실패했다고 기록한다. 추정치로 채우지 않는다.
* robots.txt를 지킨다. /pd/pdr/ 은 허용 경로이며 Crawl-delay 는 30초다.

환경변수
--------
DAISO_MAX_ITEMS  이번 실행에서 새로 가져올 상품 수 (기본 60)
DAISO_DELAY      요청 간 대기 초 (기본 30, robots.txt 준수)
DAISO_TIMEOUT    요청 타임아웃 초 (기본 20)
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "daiso_real"
PRODUCTS = OUT_DIR / "products.json"
STATE = OUT_DIR / "crawl_state.json"
QUEUE = OUT_DIR / "beauty_queue.json"
STATUS = OUT_DIR / "collection_status.json"
CATMAP = Path(__file__).with_name("category_map.json")

BASE = "https://www.daisomall.co.kr"
SITEMAP = BASE + "/sitemap.xml"
UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"

MAX_ITEMS = int(os.environ.get("DAISO_MAX_ITEMS", "60"))
DELAY = float(os.environ.get("DAISO_DELAY", "30"))
TIMEOUT = float(os.environ.get("DAISO_TIMEOUT", "20"))

now_iso = lambda: datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            charset = r.headers.get_content_charset() or "utf-8"
            return r.status, r.read().decode(charset, "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:                                    # noqa: BLE001
        return 0, str(e)


# ----------------------------------------------------------------- parsing
META = re.compile(
    r'<meta[^>]+(?:property|name)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']*)["\']',
    re.I)
META_REV = re.compile(
    r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']([^"\']+)["\']',
    re.I)
PRICE_RE = re.compile(r"가격\s*([\d,]+)\s*원")
REVIEW_RE = re.compile(r"리뷰\s*([\d.]+)\s*점\s*\(\s*([\d,]+)\s*건\s*\)")


def unescape(s: str) -> str:
    return (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&#39;", "'").strip())


def meta_tags(html: str) -> dict:
    tags = {}
    for k, v in META.findall(html):
        tags.setdefault(k.lower(), unescape(v))
    for v, k in META_REV.findall(html):
        tags.setdefault(k.lower(), unescape(v))
    return tags


# 실패 사유를 담을 곳. parse_product 는 dict|None 을 그대로 유지하고
# 왜 실패했는지는 여기에 적는다. 호출부를 바꾸지 않으려는 것이다.
LAST_FAIL: dict = {}

# og:description 끝에 "[가격 5,000원, 리뷰 4.8점(1198건), 품절]" 처럼 붙는다.
SOLDOUT_RE = re.compile(r"(일시품절|판매종료|품절)")


def parse_product(pd_no: str, url: str, html: str) -> dict | None:
    """상품 페이지에서 실제로 표시된 값만 추출한다.

    실패하면 LAST_FAIL 에 사유를 남긴다. 예전에는 실패 건수만 세고
    무엇이 왜 실패했는지 아무도 기록하지 않았다. 그래서 "35건 중 15건
    파싱 실패" 라고 보고만 하고 원인을 짚을 수가 없었다.
    """
    LAST_FAIL.clear()
    t = meta_tags(html)
    title = t.get("og:title") or t.get("title") or ""
    desc = t.get("og:description") or t.get("description") or ""

    # 구매할 수 없는 상품은 200 을 주면서 상품이 없는 껍데기를 돌려준다.
    #
    # "가격 없음 13건" 이 떠서 파서가 가격을 못 읽는 줄 알았다. 세 건을
    # 직접 열어봤다(1038044 / 1063854 / 77503). 셋 다 같았다.
    #   og:type   website   (살아 있는 상품은 product 다)
    #   og:title  "다이소몰" (상품명이 아니라 사이트 기본 제목)
    #   본문      상품 내용이 한 줄도 없음
    #
    # 다이소 API 에 물어보니 말로 답했다.
    #   POST fapi.daisomall.co.kr/pd/pdr/pdDtl/selPdDtlInfo  pdNo=1038044
    #   {"message":"현재 구매할 수 없는 상품입니다.","data":null,"success":false}
    #
    # 페이지에도 API 에도 가격이 없다. 파서를 고쳐서 읽어낼 값이 아니다.
    # 억지로 채우면 지어낸 값이다.
    #
    # 사이트맵에는 남아 있어 계속 시도하게 된다. 실패로 세지 말고
    # "구매 불가" 로 따로 센다. 고칠 것이 없는 항목을 고장 칸에 두면
    # 매번 파서를 의심하게 된다.
    if (t.get("og:type") or "").lower() != "product" or title.strip() == "다이소몰":
        LAST_FAIL.update(pd_no=pd_no, reason="구매 불가 (상품 페이지 없음)",
                         unavailable=True, og_type=t.get("og:type") or "",
                         og_title=title[:60],
                         근거=("다이소 selPdDtlInfo 가 '현재 구매할 수 없는 "
                             "상품입니다' 로 답한다. 페이지에 가격이 없다."))
        return None

    if not title:
        LAST_FAIL.update(pd_no=pd_no, reason="og:title 없음",
                         meta_count=len(t), html_len=len(html),
                         sold_out=("판매종료" in html or "품절" in html))
        return None

    # og:title 형식: "상품명 | 브랜드 | 카테고리 | 1,000원 - 다이소몰"
    head = title.rsplit(" - ", 1)[0]
    parts = [p.strip() for p in head.split("|")]
    name = parts[0] if parts else ""
    brand = parts[1] if len(parts) > 2 else None
    category = parts[2] if len(parts) > 3 else (parts[1] if len(parts) == 3 else None)

    price = None
    m = PRICE_RE.search(title) or PRICE_RE.search(desc)
    if m:
        price = int(m.group(1).replace(",", ""))
    else:                                    # 제목 끝의 "1,000원" 형태
        m2 = re.search(r"([\d,]+)\s*원", head)
        if m2:
            price = int(m2.group(1).replace(",", ""))

    if not name or price is None:
        LAST_FAIL.update(
            pd_no=pd_no,
            reason=("상품명 없음" if not name else "가격 없음"),
            og_title=title[:120],
            # 가격이 없는 건 대개 판매 종료·품절이다. 파싱이 깨진 게 아니다.
            sold_out=("판매종료" in html or "일시품절" in html or "품절" in html),
        )
        return None

    rating = review_count = None
    r = REVIEW_RE.search(desc) or REVIEW_RE.search(title)
    if r:
        rating = float(r.group(1))
        review_count = int(r.group(2).replace(",", ""))

    # 품절을 성공 경로에서 아무도 안 봤다.
    #
    # 품절이어도 og:title 에 가격이 그대로 있어서 파싱은 성공한다.
    # 그래서 품절 상품이 정상 상품으로 저장되고 S등급 등록 후보까지 갔다.
    # 09-09 기준 S등급 1위 '드롭비 탄탄 광채 앰플' 이 그 상태였다.
    #   og:description ... [가격 5,000원, 리뷰 4.8점(1198건), 품절]
    # 살 수 없는 물건을 미국에 등록할 뻔했다.
    #
    # 품절은 되돌아오니 지우지 않는다. 표시만 남기고 등록 후보를 고르는
    # 쪽(score_shopify_demand.py 의 qualify_s)이 거른다.
    sold_out = bool(SOLDOUT_RE.search(f"{title} {desc}"))
    return {
        "pd_no": pd_no,
        "name": name,
        "brand": brand,
        "site_category": category,
        "price_krw": price,
        "sold_out": sold_out,
        "stock_note": ("품절 표시 있음" if sold_out else "판매 중"),
        "stock_checked_at": now_iso(),
        "rating": rating,
        "review_count": review_count,
        "image_url": t.get("og:image"),
        "url": url,
        "collected_at": now_iso(),
        "source": "daisomall.co.kr 상품 상세 페이지",
    }


def excluded(item: dict, rules: dict) -> str:
    """수집 대상에서 뺄 상품이면 그 이유(버킷 이름)를 낸다.

    선케어와 네일은 아예 받지 않는다. 버킷 목록에서 빼기만 하면
    남은 버킷의 넓은 키워드(크림·로션·립 등)에 걸려 다른 이름으로
    들어오므로, 분류보다 먼저 검사한다.
    """
    hay = " ".join(filter(None, [item.get("site_category"), item.get("name")])).lower()
    if not hay:
        return ""
    for name, spec in rules.items():
        if name.startswith("_"):
            continue
        if any(str(k).lower() in hay for k in (spec.get("keywords") or [])):
            return name
    return ""


def classify(item: dict, buckets: dict) -> str | None:
    """뷰티관 카테고리 중 하나로 분류. 해당 없으면 None (수집 대상 아님)."""
    haystack = " ".join(filter(None, [item.get("site_category"), item.get("name")]))
    if not haystack:
        return None
    for bucket, keywords in buckets.items():
        if any(kw in haystack for kw in keywords):
            return bucket
    return None


# ----------------------------------------------------------------- fx rate
# 환율은 scripts/fetch_fx_rate.py 가 담당한다.
#
# 예전에는 이 파일 안에 있었다. 그런데 다이소 수집이 조용히 죽으면
# 환율까지 같이 멈췄다. 원가 계산이 환율에 걸려 있는데 상품 수집이
# 막혔다고 환율이 멈출 이유가 없다.
#
# 저장 자리는 그대로 collection_status.json 의 fx 다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fetch_fx_rate import fetch_fx  # noqa: E402


# ----------------------------------------------------------------- sitemap
def product_urls() -> list[str]:
    status, body = fetch(SITEMAP)
    if status != 200:
        return []
    urls = re.findall(r"<loc>\s*([^<\s]+/pd/pdr/[^<\s]+)\s*</loc>", body)
    if not urls:                                     # 중첩 sitemap 대응
        for sub in re.findall(r"<loc>\s*([^<\s]+\.xml)\s*</loc>", body):
            if sub == SITEMAP:
                continue
            time.sleep(min(DELAY, 5))
            s2, b2 = fetch(sub)
            if s2 == 200:
                urls += re.findall(r"<loc>\s*([^<\s]+/pd/pdr/[^<\s]+)\s*</loc>", b2)
    seen, out = set(), []
    for u in urls:
        u = unescape(u)
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def main() -> int:
    cfg = load_json(CATMAP, {})
    buckets = cfg.get("buckets", {})
    exclude_rules = cfg.get("exclude", {})

    store = load_json(PRODUCTS, {"products": []})
    products = store.get("products", [])

    # 이미 저장된 것도 매 회차 다시 거른다.
    # 수집 단계에서 새 상품만 막았더니, 워크플로가 예전 목록을 그대로 다시
    # 커밋해 선케어·네일 22건이 되살아났다. 규칙을 바꿨으면 가진 것도
    # 같이 정리해야 한다. 몇 건을 왜 뺐는지 남긴다.
    pruned = {}
    kept = []
    for it in products:
        why = excluded(it, exclude_rules)
        if why:
            pruned[why] = pruned.get(why, 0) + 1
        else:
            kept.append(it)
    if pruned:
        print(f"제외 규칙으로 기존 {sum(pruned.values())}건 정리: {pruned}")
    products = kept
    by_no = {p["pd_no"]: i for i, p in enumerate(products)}

    state = load_json(STATE, {"visited": [], "sitemap_cached_at": None, "urls": []})
    visited = set(state.get("visited", []))

    run = {
        "started_at": now_iso(),
        "requested": 0, "ok": 0, "parse_failed": 0, "http_error": 0,
        # 이 세 줄이 빠져 있었다. 아래에서 run["sold_out"] += 1 과
        # run["parse_fail_reasons"][why], run["parse_fail_samples"].append 을
        # 쓰는데 초기화가 없어 첫 품절 상품이나 첫 파싱 실패에서 KeyError 로
        # 죽었다. 죽으면 status 를 못 쓰니 last_run 이 09-05 에 멈춰 있었다.
        # 워크플로는 continue-on-error 라 초록으로 끝났고, 그래서 아무도
        # 몰랐다. 다이소는 품절 상품이 흔해서 사실상 매번 걸렸다.
        "sold_out": 0,
        # 구매할 수 없는 상품. 파싱 실패가 아니다. 사이트맵에는 남아 있지만
        # 다이소가 "현재 구매할 수 없는 상품입니다" 라고 답하는 것들이다.
        # 고칠 것이 없으므로 실패 칸과 갈라 센다.
        "unavailable": 0,
        "unavailable_samples": [],
        "parse_fail_reasons": {},
        "parse_fail_samples": [],
        "skipped_not_beauty": 0,
        "skipped_bucket_full": 0,
        "skipped_excluded": {},
        "pruned_existing": {},
        "queue_size": 0,
        "url_source": "",
        "scope": "다이소몰 뷰티관(C245) 10개 카테고리 (선케어·네일 제외)",
        "delay_seconds": DELAY, "max_items": MAX_ITEMS,
        "user_agent": UA,
        "robots_note": "robots.txt: User-agent * → Allow /pd/pdr/, Crawl-delay 30",
    }

    # 버킷 목표치. 스킨케어에 절반을 배정했다(근거: data/kbeauty_news.json).
    # 옛 형식(target_per_bucket 단일값)도 계속 읽는다.
    #
    # 원래 이 정의가 사이트맵 확인보다 아래에 있었다. 그런데 사이트맵이
    # 막혔을 때 도는 blocked 경로가 target_of 를 먼저 부른다. 즉 다이소가
    # 우리를 차단하면 "차단됐다" 고 기록하려다 NameError 로 죽는다.
    # 정작 기록이 필요한 순간에 기록을 못 남기는 구조였다.
    tmap = cfg.get("bucket_targets") or {}
    flat = int(cfg.get("target_per_bucket") or 25)

    def target_of(b: str) -> int:
        return int(tmap.get(b, flat))

    # 뷰티 URL 큐가 있으면 그걸 먼저 쓴다.
    #
    # 사이트맵을 훑으면 뷰티관 밖 상품을 받아본 뒤에야 버린다. 한 회차
    # 110건 중 82건이 그랬고 Crawl-delay 30 이라 41분이 버려졌다.
    # build_beauty_queue.py 가 뷰티관 페이지에서 상품 URL 만 모아 둔다.
    #
    # 큐가 없거나 비면 예전대로 사이트맵을 쓴다. 새 경로가 막혀도
    # 수집이 멈추지 않게 한다.
    queue = (load_json(QUEUE, {}) or {}).get("urls") or []
    queue = [u for u in queue if "/pd/pdr/" in u]
    run["queue_size"] = len(queue)
    run["url_source"] = "beauty_queue" if queue else "sitemap"

    urls = list(queue)
    if not urls:
        urls = state.get("urls") or []
    if not urls:
        urls = product_urls()
        if not urls:
            run.update(finished_at=now_iso(), status="blocked",
                       message="sitemap.xml에서 상품 URL을 가져오지 못했습니다. "
                               "차단 또는 사이트 구조 변경 가능성.")
            save_json(STATUS, {"last_run": run,
                               "totals": summarize(products, buckets,
                                                   {b: target_of(b) for b in buckets}),
                               "fx": load_json(STATUS, {}).get("fx")})
            print(json.dumps(run, ensure_ascii=False, indent=2))
            return 1
        # sitemap 순서는 카테고리와 무관하므로 섞어서 카탈로그 전체를 고르게 표본
        # 추출한다. 그래야 뷰티관 상품이 특정 구간에 몰려 있어도 빨리 만난다.
        random.seed(20260823)
        random.shuffle(urls)
        state["urls"] = urls
        state["sitemap_cached_at"] = now_iso()

    counts = tally(products)
    # 부족한 버킷을 먼저 채우려면 그 상품을 먼저 만나야 한다. sitemap 은
    # 무작위라 순서를 조정할 수 없으니, 대신 이번 회차에 남은 자리를
    # 로그에 남겨 어디가 비었는지 보이게 한다.
    # 버킷마다 목표가 다르다. 미국 기사에서 스킨케어 언급이 85.9% 라
    picked = 0
    for url in urls:
        if picked >= MAX_ITEMS:
            break
        m = re.search(r"pdNo=(\d+)", url)
        if not m:
            continue
        pd_no = m.group(1)
        if pd_no in visited:
            continue

        if not url.startswith("http"):
            url = BASE + url
        run["requested"] += 1
        picked += 1
        status, html = fetch(url)
        visited.add(pd_no)

        if status != 200:
            run["http_error"] += 1
        else:
            item = parse_product(pd_no, url, html)
            if item is None:
                info = dict(LAST_FAIL)
                # 품절·판매종료 상품은 가격이 표시되지 않는다. 파싱이 깨진
                # 게 아니라 살 수 없는 상품이다. 이걸 실패로 세면 실패율이
                # 부풀려진다. 따로 센다.
                if info.get("unavailable"):
                    run["unavailable"] += 1
                    if len(run["unavailable_samples"]) < 20:
                        run["unavailable_samples"].append(pd_no)
                elif info.get("sold_out"):
                    run["sold_out"] += 1
                else:
                    run["parse_failed"] += 1
                    why = info.get("reason", "?")
                    run["parse_fail_reasons"][why] = \
                        run["parse_fail_reasons"].get(why, 0) + 1
                    if len(run["parse_fail_samples"]) < 12:
                        run["parse_fail_samples"].append(info)
            else:
                drop = excluded(item, exclude_rules)
                if drop:
                    run["skipped_excluded"][drop] = \
                        run["skipped_excluded"].get(drop, 0) + 1
                    time.sleep(DELAY + random.uniform(0, 2))
                    continue
                bucket = classify(item, buckets)
                if bucket is None:
                    run["skipped_not_beauty"] += 1     # 뷰티관 밖 상품은 저장하지 않는다
                elif pd_no not in by_no and counts.get(bucket, 0) >= target_of(bucket):
                    # 버킷 상한. 예전에는 target_per_bucket 이 적혀만 있고
                    # 지켜지지 않아 메이크업 53개, 선케어 1개로 쏠렸다.
                    # 이미 가진 상품을 갱신하는 건 상한과 무관하게 허용한다.
                    run["skipped_bucket_full"] += 1
                else:
                    item["bucket"] = bucket
                    counts[bucket] = counts.get(bucket, 0) + 1
                    if pd_no in by_no:
                        products[by_no[pd_no]] = item
                    else:
                        by_no[pd_no] = len(products)
                        products.append(item)
                    run["ok"] += 1

        time.sleep(DELAY + random.uniform(0, 2))

    run["finished_at"] = now_iso()
    run["pruned_existing"] = pruned
    run["bucket_targets"] = {b: target_of(b) for b in buckets}
    run["buckets_short"] = {b: target_of(b) - counts.get(b, 0)
                            for b in buckets if counts.get(b, 0) < target_of(b)}
    reached = run["ok"] + run["skipped_not_beauty"]
    if run["requested"] == 0:
        run["status"] = "nothing_to_do"
    elif reached == 0:
        run["status"] = "blocked"
        run["message"] = ("모든 요청이 실패했습니다. GitHub Actions 러너의 해외 IP가 "
                          "차단되었을 수 있습니다. 로컬(한국 IP) 실행을 검토하세요.")
    elif reached < run["requested"] / 2:
        run["status"] = "degraded"
    else:
        run["status"] = "ok"

    state["visited"] = sorted(visited)
    save_json(STATE, state)
    save_json(PRODUCTS, {
        "updated_at": now_iso(),
        "source": "daisomall.co.kr (robots.txt 허용 경로 /pd/pdr/)",
        "truth_note": "가격은 상품 페이지에 표시된 실제 원화 금액입니다. "
                      "배송비·관세·수수료는 확정 견적이 없어 계산하지 않습니다.",
        "count": len(products),
        "products": products,
    })
    save_json(STATUS, {
        "last_run": run,
        "totals": summarize(products, buckets,
                            {b: target_of(b) for b in buckets}),
        # 여기서 다시 받지 않는다. 워크플로가 fetch_fx_rate.py 를 따로
        # 돌린다. 수집이 오래 걸려 그 사이 환율이 갱신됐을 수도 있으니
        # 지금 파일에 있는 값을 그대로 둔다.
        "fx": load_json(STATUS, {}).get("fx"),
        "sitemap_urls_known": len(urls),
        "visited": len(visited),
    })
    print(json.dumps(run, ensure_ascii=False, indent=2))
    return 0 if run["status"] in ("ok", "degraded", "nothing_to_do") else 1


def tally(products: list) -> dict:
    c: dict = {}
    for p in products:
        b = p.get("bucket")
        if b:
            c[b] = c.get(b, 0) + 1
    return c


def summarize(products: list, buckets: dict, target) -> dict:
    """target 은 이제 버킷별 dict 다. 단일값도 계속 받는다."""
    rows = {}
    for b in buckets:
        items = [p for p in products if p.get("bucket") == b]
        prices = [p["price_krw"] for p in items if isinstance(p.get("price_krw"), int)]
        rows[b] = {
            "count": len(items),
            "avg_price_krw": round(sum(prices) / len(prices)) if prices else None,
            "min_price_krw": min(prices) if prices else None,
            "max_price_krw": max(prices) if prices else None,
        }
    prices = [p["price_krw"] for p in products if isinstance(p.get("price_krw"), int)]
    return {
        "products": len(products),
        "bucket_targets": target,
        "by_bucket": {b: rows[b]["count"] for b in buckets},
        "categories": rows,
        "avg_price_krw": round(sum(prices) / len(prices)) if prices else None,
        "price_krw_min": min(prices) if prices else None,
        "price_krw_max": max(prices) if prices else None,
        "with_rating": sum(1 for p in products if p.get("rating") is not None),
    }


def record_crash(e: BaseException) -> None:
    """터졌다는 사실을 파일에 남긴다.

    워크플로의 수집 단계가 continue-on-error 라서, 스크립트가 죽어도
    워크플로는 초록으로 끝난다. 실제로 09-06 실행이 그랬다. 성공으로
    보고됐는데 collection_status 는 09-05 것 그대로였다.

    아무 기록도 없으면 다음 사람이 성공했다고 믿는다. 그게 제일 나쁘다.
    """
    prev = load_json(STATUS, {})
    run = dict(prev.get("last_run") or {})
    run.update(finished_at=now_iso(), status="crashed",
               error=f"{type(e).__name__}: {str(e)[:200]}",
               message="수집 도중 예외로 중단됐다. 이 기록은 실패를 남기려고 쓴 것이며 "
                       "totals 는 직전 성공분 그대로다.")
    save_json(STATUS, {"last_run": run,
                       "totals": prev.get("totals"),
                       "fx": prev.get("fx")})


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as _e:                                   # noqa: BLE001
        record_crash(_e)
        print(f"수집이 예외로 중단됐다: {type(_e).__name__}: {_e}", file=sys.stderr)
        raise SystemExit(1)
