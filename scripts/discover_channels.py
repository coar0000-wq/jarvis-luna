#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""수집 가능한 새 채널을 찾아 실제로 시험한 뒤 제안한다.

왜 이렇게 만들었나
  "데이터는 많을수록 좋다"는 절반만 맞다. 2026-09-01 에 가짜 채널 6개를
  걷어냈다. 하드코딩 카탈로그와 폴백 샘플이 실측인 척 대시보드에 떠 있었다.
  그래서 이 스크립트는 후보를 자동으로 등록하지 않는다.
  robots.txt 를 확인하고 실제로 호출해 본 뒤,
  진짜 데이터가 나오는 것만 "제안" 한다. 연동은 사람이 승인한 뒤에 한다.

판정 기준 (하나라도 실패하면 제안하지 않는다)
  1. robots.txt 가 해당 경로를 막지 않는다
  2. 인증 없이 또는 이미 보유한 키로 200 응답이 온다
  3. 응답에서 구조화된 항목이 최소 3건 이상 파싱된다
  4. 항목에 실제 값이 있다 (전부 동일한 상수가 아니다)

출력 data/channel_candidates.json
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "channel_candidates.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
TIMEOUT = 25
DELAY = 1.5
MIN_ITEMS = 3

# 후보 목록. 전부 공개 접근이거나 이미 키를 가진 것만 넣는다.
# 유료 API, 로그인 필요, robots.txt 금지 경로는 애초에 넣지 않는다.
CANDIDATES = [
    {
        "key": "openbeautyfacts_new",
        "label": "Open Beauty Facts 신규 등록순",
        "why": "오픈데이터. 미국 유통 신제품을 성분과 함께 얻는다.",
        "url": ("https://world.openbeautyfacts.org/api/v2/search"
                "?countries_tags_en=united-states&sort_by=created_t"
                "&fields=code,product_name,brands&page_size=20"),
        "kind": "json",
        "path": ["products"],
        "name_keys": ("product_name",),
    },
    {
        "key": "wikipedia_pageviews",
        "label": "Wikipedia 조회수 (브랜드 관심도)",
        "why": "무료 공식 API. K뷰티 브랜드 문서 조회수로 관심 추이를 본다.",
        "url": ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
                "/en.wikipedia/all-access/all-agents/K-beauty/daily"
                "/20260801/20260901"),
        "kind": "json",
        "path": ["items"],
        "name_keys": ("timestamp",),
    },
    {
        "key": "fda_cosmetic_enforcement",
        "label": "FDA 화장품 리콜·조치 이력",
        "why": "공식 오픈데이터. 취급하면 안 되는 성분·브랜드를 걸러낸다.",
        "url": ("https://api.fda.gov/food/enforcement.json"
                "?search=product_type:cosmetic&limit=20"),
        "kind": "json",
        "path": ["results"],
        "name_keys": ("product_description", "reason_for_recall"),
    },
    {
        "key": "allure_beauty_rss",
        "label": "Allure 뷰티 기사 RSS",
        "why": "미국 뷰티 매체. 어떤 제품이 기사화되는지로 트렌드를 본다.",
        "url": "https://www.allure.com/feed/rss",
        "kind": "rss",
    },
    {
        "key": "reddit_kbeauty_new",
        "label": "r/KoreanBeauty 신규글 RSS",
        "why": "기존 Reddit 수집의 서브레딧 확장. 실사용자 언급을 본다.",
        "url": "https://www.reddit.com/r/KoreanBeauty/top.rss?t=week",
        "kind": "rss",
    },
    {
        "key": "google_trends_daily_rss",
        "label": "Google Trends 미국 일간 급상승 RSS",
        "why": "공식 RSS. 승인제 alpha API 없이도 급상승 검색어를 얻는다.",
        "url": "https://trends.google.com/trending/rss?geo=US",
        "kind": "rss",
    },
    {
        "key": "openfda_drug_otc_sunscreen",
        "label": "openFDA 선케어 OTC 라벨",
        "why": "미국에서 선크림은 OTC 의약품이다. 라벨 요건 확인에 쓴다.",
        "url": ("https://api.fda.gov/drug/label.json"
                "?search=openfda.product_type:\"HUMAN+OTC+DRUG\"+AND+sunscreen&limit=10"),
        "kind": "json",
        "path": ["results"],
        "name_keys": ("id",),
    },
]


def get(url: str, headers: dict | None = None) -> tuple[bytes | None, str]:
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
         "Accept-Encoding": "identity"}
    if headers:
        h.update(headers)
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read(), ""
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def robots_allows(url: str) -> tuple[bool, str]:
    """robots.txt 의 User-agent: * 블록만 보수적으로 해석한다."""
    u = urllib.parse.urlparse(url)
    body, err = get(f"{u.scheme}://{u.netloc}/robots.txt")
    if body is None:
        return True, f"robots.txt 확인 불가({err}) - 허용으로 간주"
    txt = body.decode("utf-8", "replace")
    star, rules = False, []
    for line in txt.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            star = (v == "*")
        elif star and k == "disallow" and v:
            rules.append(v)
    path = u.path or "/"
    for r in rules:
        if r == "/" or path.startswith(r.rstrip("*")):
            return False, f"robots.txt 금지 경로: {r}"
    return True, "robots.txt 허용"


def dig(d, path):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def probe(c: dict) -> dict:
    res = {"key": c["key"], "label": c["label"], "why": c["why"],
           "url": c["url"], "kind": c["kind"]}

    ok, note = robots_allows(c["url"])
    res["robots"] = note
    if not ok:
        res.update(verdict="불가", reason=note, items=0)
        return res

    body, err = get(c["url"])
    if body is None:
        res.update(verdict="불가", reason=f"요청 실패: {err}", items=0)
        return res
    res["bytes"] = len(body)

    samples = []
    try:
        if c["kind"] == "rss":
            root = ET.fromstring(body)
            for t in root.iter():
                if t.tag.endswith("title") and (t.text or "").strip():
                    samples.append(t.text.strip())
            samples = samples[1:]           # 채널 제목 제외
        else:
            d = json.loads(body.decode("utf-8", "replace"))
            arr = dig(d, c["path"]) or []
            for it in arr:
                if not isinstance(it, dict):
                    continue
                v = next((str(it[k]) for k in c["name_keys"]
                          if it.get(k) not in (None, "")), "")
                if v:
                    samples.append(v[:120])
    except Exception as e:
        res.update(verdict="불가", reason=f"파싱 실패: {type(e).__name__}", items=0)
        return res

    res["items"] = len(samples)
    res["samples"] = samples[:3]

    if len(samples) < MIN_ITEMS:
        res.update(verdict="불가", reason=f"항목 {len(samples)}건 (최소 {MIN_ITEMS})")
    elif len(set(samples)) == 1:
        res.update(verdict="불가", reason="모든 항목이 동일한 값 - 실측이 아닐 가능성")
    else:
        res.update(verdict="가능",
                   reason=f"{len(samples)}건 파싱 성공, 값이 서로 다름")
    return res


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
    results = []
    for c in CANDIDATES:
        if only and c["key"] != only:
            continue
        r = probe(c)
        mark = "가능" if r["verdict"] == "가능" else "불가"
        print(f"  [{mark}] {c['label'][:32]:34s} {r.get('items',0):3d}건  {r['reason'][:52]}")
        results.append(r)
        time.sleep(DELAY)

    usable = [r for r in results if r["verdict"] == "가능"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/discover_channels.py",
        "정책": ("후보를 자동으로 등록하지 않는다. robots.txt 를 확인하고 실제로 "
               "호출해 본 뒤 진짜 데이터가 나오는 것만 제안한다. "
               "연동은 사람이 승인한 뒤에 한다."),
        "판정기준": [
            "robots.txt 가 해당 경로를 막지 않을 것",
            "인증 없이 또는 보유한 키로 200 응답이 올 것",
            f"구조화된 항목이 최소 {MIN_ITEMS}건 파싱될 것",
            "항목 값이 전부 동일한 상수가 아닐 것",
        ],
        "tested": len(results),
        "usable": len(usable),
        "candidates": results,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n{len(usable)}/{len(results)}개 채널 추가 가능 -> {OUT.relative_to(ROOT)}")
    if usable:
        print("승인하시면 각각에 대해 수집기를 만들어 채널로 연동합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
