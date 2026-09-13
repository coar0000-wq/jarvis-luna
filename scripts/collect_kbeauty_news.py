#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""미국 매체가 K뷰티를 어떻게 다루는지 모아 소싱 근거로 쓴다.

왜 만들었나
  "미국에서 한국 스킨·에센스가 인기다" 는 말은 맞지만, 그 말만으로
  상품을 고를 수는 없다. 어떤 성분과 어떤 제형이 실제로 기사화되는지
  세어보면 근거가 된다. 예를 들어 스네일 뮤신과 PDRN 이 Vogue 기사
  제목에 몇 번 나오는지는 검증 가능한 사실이다.

무엇이 아닌가
  이건 판매 데이터가 아니다. 매체 노출 신호다. 그래서 점수의 us_market_fit
  에는 넣지 않는다. 그건 미국 실판매 목록으로만 계산한다. 여기서 나온
  값은 어떤 상품군을 더 모을지 정하는 데 쓴다.

출처
  Google News RSS. 키가 필요 없고 robots.txt 가 /rss 를 막지 않는다.
  기사 제목만 읽는다. 본문은 가져오지 않는다.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "kbeauty_news.json"
UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"
TIMEOUT = 25
DELAY = 2.0

# 질의마다 용도를 적는다. 이유가 있다 (2026-09-13).
#
# 전에는 질의가 다섯 개였고 전부 상품 중심이었다. 그 결과로 나온
# 상품군 비중(스킨케어 85.9% 등)이 category_map.json 의 bucket_targets
# 근거가 된다. 스킨케어 150건이 그렇게 정해졌다.
#
# 여기에 구매자 질의를 그냥 더하면 그 기사들이 같은 풀에 섞인다.
# 그러면 상품 인기와 무관한 이유로 상품군 비중이 흔들리고,
# 수집 목표가 조용히 바뀐다. 그건 안 된다.
#
# 그래서 용도를 갈라 둔다. 상품군 비중은 '상품군' 질의에서만 센다.
# 구매자 신호는 따로 센다.
QUERIES = [
    {"q": '"K-beauty" skincare US sales', "용도": "상품군"},
    {"q": "Korean skincare essence serum trend United States", "용도": "상품군"},
    {"q": "K-beauty toner ampoule America popularity", "용도": "상품군"},
    {"q": "Korean beauty ingredient snail mucin PDRN centella", "용도": "상품군"},
    {"q": "K-beauty Amazon Ulta Sephora launch", "용도": "상품군"},

    # 구매자 축 (2026-09-13 추가)
    #
    # 왜 넣었나. 샘 리처드 교수가 올리브영 US 패서디나 매장에서 찍은
    # 영상을 검토하다 나왔다. 제목이 "라틴계, 선크림, 소비습관" 이다.
    #
    # 그런데 JARVIS 의 타겟팅 축은 상품군 하나뿐이었다.
    # 누가 사는가 하는 축이 없다. 기사 말뭉치를 뒤져 보니
    # latino / hispanic / gen z / millennial 이 0회였다.
    #
    # 0회는 없다는 증거가 아니다. 안 물어봤다는 증거다.
    # 위 다섯 질의가 전부 상품 이름이라 애초에 나올 자리가 없었다.
    # 그래서 물어보는 질의를 넣는다.
    #
    # 영상 자체는 수치로 쓰지 않는다. 올리브영 협조로 올리브영 매장에서
    # 찍은 것이라 중립적인 자리가 아니다. 물어볼 질문으로만 쓴다.
    # 답은 여기서 나오는 기사 수로 판단한다.
    {"q": "K-beauty Hispanic Latino consumers United States", "용도": "구매자"},
    {"q": "Korean skincare Gen Z spending America", "용도": "구매자"},
    {"q": "K-beauty shopper demographics US market growth", "용도": "구매자"},
]

# 구매자 축 낱말. BUCKET_TERMS 와 같은 방식으로 센다.
# 한 기사에서 같은 축은 한 번만 센다.
DEMO_TERMS = {
    "히스패닉·라틴": ["hispanic", "latino", "latina", "latinx"],
    "흑인": ["black consumer", "black shopper", "black women", "melanin-rich"],
    "아시아계": ["asian american", "aapi"],
    "Z세대": ["gen z", "gen-z", "generation z", "teen"],
    "밀레니얼": ["millennial"],
    "남성": ["men", "male", "guys"],
    "가격민감": ["affordable", "budget", "dupe", "drugstore", "value"],
}

# 다이소 버킷과 같은 이름을 쓴다. 그래야 수집 목표에 바로 반영된다.
BUCKET_TERMS = {
    "스킨케어": ["essence", "serum", "ampoule", "toner", "moisturizer", "cream",
              "lotion", "mist", "skincare", "skin care", "glass skin"],
    "마스크팩": ["sheet mask", "mask", "pad", "patch"],
    "클렌징": ["cleanser", "cleansing", "double cleanse", "makeup remover"],
    "메이크업": ["cushion", "foundation", "tint", "lip", "concealer", "makeup"],
    "헤어케어": ["shampoo", "hair", "scalp", "treatment"],
    "바디케어": ["body wash", "body lotion", "hand cream", "deodorant"],
    "향수": ["perfume", "fragrance"],
}

# 미국 기사에서 반복되는 성분. 우리가 다이소에서 찾아야 할 단서다.
INGREDIENTS = [
    "snail mucin", "pdrn", "centella", "cica", "heartleaf", "houttuynia",
    "niacinamide", "hyaluronic", "ceramide", "peptide", "retinol",
    "vitamin c", "collagen", "rice", "propolis", "azelaic", "mugwort",
    "panthenol", "tranexamic", "exosome",
]


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return res.read()


def google_news(query: str) -> list[dict]:
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    root = ET.fromstring(fetch(url))
    out = []
    for e in root.findall("./channel/item"):
        title = (e.findtext("title") or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "url": (e.findtext("link") or "").strip(),
            "published": (e.findtext("pubDate") or "").strip(),
            "source": (e.findtext("source") or "").strip(),
            "query": query,
        })
    return out


def tally(items: list[dict]) -> tuple[dict, dict]:
    """상품군과 성분을 센다. 한 기사에서 같은 말은 한 번만.

    상품군 질의로 받은 기사만 센다. 구매자 질의로 받은 기사를 섞으면
    상품 인기와 무관한 이유로 비중이 흔들리고, 그 비중이
    category_map.json 의 bucket_targets 근거라서 수집 목표가 바뀐다.
    """
    buckets, ings = Counter(), Counter()
    for it in items:
        if it.get("용도") != "상품군":
            continue
        low = it["title"].lower()
        for bucket, terms in BUCKET_TERMS.items():
            if any(t in low for t in terms):
                buckets[bucket] += 1
        for ing in INGREDIENTS:
            if ing in low:
                ings[ing] += 1
    return dict(buckets), dict(ings)


def tally_demo(items: list[dict]) -> tuple[dict, int]:
    """구매자 축을 센다. 기사 전부를 본다.

    상품군 질의로 받은 기사에 히스패닉 이야기가 나와도 그것은 신호다.
    여기서 세는 값은 상품군 비중을 건드리지 않으므로 섞여도 된다.
    """
    demo = Counter()
    hit_articles = 0
    for it in items:
        low = it["title"].lower()
        hit = False
        for axis, terms in DEMO_TERMS.items():
            if any(t in low for t in terms):
                demo[axis] += 1
                hit = True
        if hit:
            hit_articles += 1
    return dict(sorted(demo.items(), key=lambda x: -x[1])), hit_articles


def main() -> int:
    items, failed = [], []
    seen = set()
    for spec in QUERIES:
        q, use = spec["q"], spec["용도"]
        try:
            got = google_news(q)
        except (urllib.error.URLError, urllib.error.HTTPError, ET.ParseError, OSError) as e:
            failed.append({"query": q, "용도": use,
                           "error": f"{type(e).__name__}: {e}"[:120]})
            continue
        for it in got:
            key = re.sub(r"\W+", "", it["title"].lower())[:80]
            if key in seen:
                continue
            seen.add(key)
            it["용도"] = use
            items.append(it)
        time.sleep(DELAY)

    buckets, ings = tally(items)
    demo, demo_articles = tally_demo(items)
    by_use = Counter(it.get("용도") for it in items)
    total = sum(buckets.values()) or 1
    share = {k: round(v / total * 100, 1)
             for k, v in sorted(buckets.items(), key=lambda x: -x[1])}

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/collect_kbeauty_news.py",
        "출처": "Google News RSS (키 불필요). 기사 제목만 읽는다.",
        "성격": ("판매 데이터가 아니라 매체 노출 신호다. 점수의 us_market_fit 에는 "
               "넣지 않는다. 어떤 상품군을 더 모을지 정하는 데 쓴다."),
        "queries": QUERIES,
        "articles": len(items),
        "질의용도별_기사수": dict(by_use),
        "failed_queries": failed,
        "bucket_mentions": buckets,
        "bucket_share_pct": share,
        "_비중_계산_범위": (
            "상품군 질의로 받은 기사만 센다. 구매자 질의 기사를 섞으면 "
            "상품 인기와 무관한 이유로 비중이 흔들리고, 이 비중이 "
            "category_map.json 의 bucket_targets 근거라서 수집 목표가 바뀐다."
        ),
        "ingredient_mentions": dict(sorted(ings.items(), key=lambda x: -x[1])),
        "demo_mentions": demo,
        "demo_articles": demo_articles,
        "_구매자_축이란": (
            "누가 사는가. 2026-09-13 에 넣었다. 전에는 타겟팅 축이 상품군 "
            "하나뿐이었고 기사 말뭉치에 latino/hispanic/gen z 가 0회였다. "
            "그건 없다는 뜻이 아니라 질의가 전부 상품 이름이라 안 물어봤다는 "
            "뜻이었다. 이 값도 판매 데이터가 아니라 매체 노출 신호다. "
            "타겟팅을 바꾸기 전에 실판매나 광고 지표로 한 번 더 확인한다."
        ),
        # 용도별로 갈라 담는다.
        #
        # 전에는 items[:120] 으로 앞에서 잘랐다. 질의가 상품군 먼저 돌기
        # 때문에 120건이 전부 상품군 기사가 됐고, 구매자 기사는 한 건도
        # 안 남았다. 그러면 "히스패닉 16건" 이라고 적어 놓고 정작 그
        # 기사가 무엇이었는지 확인할 방법이 없다.
        # 세어 놓은 값의 근거를 못 보면 그 값은 못 믿는 값이 된다.
        "items": (
            [x for x in items if x.get("용도") == "상품군"][:120]
            + [x for x in items if x.get("용도") == "구매자"][:80]
        ),
        # 구매자 축에 실제로 걸린 기사만 따로 남긴다. 근거다.
        "demo_hit_samples": [
            {"title": x["title"], "source": x.get("source"),
             "url": x.get("url"), "용도": x.get("용도")}
            for x in items
            if any(t in x["title"].lower()
                   for terms in DEMO_TERMS.values() for t in terms)
        ][:40],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for _ in range(4):
        OUT.write_text(body, encoding="utf-8")
        try:
            if json.loads(OUT.read_text(encoding="utf-8-sig"))["articles"] == len(items):
                break
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, KeyError):
            pass
        time.sleep(0.5)
    else:
        print("기록 검증 실패", file=sys.stderr)
        return 1

    print(f"기사 {len(items)}건 · 질의 {len(QUERIES)}개 (실패 {len(failed)})")
    print("  질의 용도별:", ", ".join(f"{k} {v}건" for k, v in by_use.items()))
    print("상품군 언급 비중:", ", ".join(f"{k} {v}%" for k, v in list(share.items())[:6]))
    print("  (상품군 질의 기사만 센 값이다)")
    print("성분 언급:", ", ".join(f"{k} {v}" for k, v in
                              list(payload["ingredient_mentions"].items())[:8]))
    if demo:
        print(f"구매자 축 언급: {demo_articles}건 기사에서 — "
              + ", ".join(f"{k} {v}" for k, v in list(demo.items())[:7]))
    else:
        print("구매자 축 언급: 0건. 미국 매체가 기사 제목에서 "
              "구매자 집단을 말하지 않는다는 뜻이다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
