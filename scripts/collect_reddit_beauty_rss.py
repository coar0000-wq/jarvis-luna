#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reddit 뷰티 서브레딧 RSS → 핫 키워드 시그널 (무료, API 키 불필요).

수집
  https://www.reddit.com/r/{sub}/hot.rss
  https://www.reddit.com/r/{sub}/top.rss?t=week

원칙
  - 실패 시 빈 목록 + reason. 가짜 포스트 생성 금지.
  - User-Agent 명시, 요청 간 대기.
  - 상업 API 없이 RSS 만 사용 (2026 기준 .rss 공개 유지).

출력 data/reddit_beauty_signals.json
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reddit_beauty_signals.json"

UA = "JARVIS-LUNA/1.0 (Shopify research; github.com/coar0000-wq/jarvis-luna)"
TIMEOUT = 25
DELAY = 1.5

SUBREDDITS = [
    "AsianBeauty",
    "KoreanBeauty",
    "SkincareAddiction",
    "AsianBeautyAdvice",
]

# 제목에서 뽑을 영문 토큰 (너무 짧은 것·불용어 제외)
STOP = {
    "the", "and", "for", "with", "from", "this", "that", "have", "has", "was",
    "are", "but", "not", "you", "your", "just", "about", "what", "when", "how",
    "can", "will", "all", "any", "out", "our", "into", "been", "more", "some",
    "help", "please", "thanks", "thank", "http", "https", "www", "com", "reddit",
}
# 뷰티 관련이면 가중
BOOST = {
    "sunscreen", "spf", "toner", "serum", "ampoule", "essence", "moisturizer",
    "cleanser", "retinol", "niacinamide", "hyaluronic", "ceramide", "centella",
    "heartleaf", "snail", "mucin", "collagen", "pdrn", "cushion", "sheet",
    "mask", "korean", "kbeauty", "k-beauty", "routine", "glass", "skin",
}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, */*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return res.read()


def parse_feed(xml_bytes: bytes) -> list[dict]:
    """Atom(Reddit) 또는 RSS item 파싱."""
    root = ET.fromstring(xml_bytes)
    items = []
    # Atom
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entries = root.findall("a:entry", ns)
    if entries:
        for e in entries:
            title = (e.findtext("a:title", default="", namespaces=ns) or "").strip()
            link = ""
            for l in e.findall("a:link", ns):
                href = l.attrib.get("href") or ""
                if href and not link:
                    link = href
            updated = (e.findtext("a:updated", default="", namespaces=ns)
                       or e.findtext("a:published", default="", namespaces=ns) or "")
            if title:
                items.append({"title": title, "url": link, "published": updated})
        return items
    # RSS 2.0
    for e in root.findall("./channel/item"):
        title = (e.findtext("title") or "").strip()
        link = (e.findtext("link") or "").strip()
        pub = (e.findtext("pubDate") or "").strip()
        if title:
            items.append({"title": title, "url": link, "published": pub})
    return items


def tokens_from_title(title: str) -> list[str]:
    t = title.lower()
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[^a-z0-9+\-\s]", " ", t)
    out = []
    for w in t.split():
        w = w.strip("-")
        if len(w) < 3 or w in STOP:
            continue
        out.append(w)
    return out


def collect_sub(sub: str) -> dict:
    feeds = {
        "hot": f"https://www.reddit.com/r/{sub}/hot.rss",
        "top_week": f"https://www.reddit.com/r/{sub}/top.rss?t=week",
    }
    posts = []
    errors = []
    for kind, url in feeds.items():
        try:
            raw = fetch(url)
            for p in parse_feed(raw):
                p["subreddit"] = sub
                p["feed"] = kind
                posts.append(p)
            time.sleep(DELAY)
        except Exception as e:
            errors.append(f"{kind}: {type(e).__name__}: {e}")
            time.sleep(DELAY)
    return {"subreddit": sub, "posts": posts, "errors": errors}


def main() -> int:
    all_posts = []
    per_sub = []
    counter: Counter = Counter()
    boost_hits: Counter = Counter()

    for sub in SUBREDDITS:
        block = collect_sub(sub)
        per_sub.append({
            "subreddit": sub,
            "post_count": len(block["posts"]),
            "errors": block["errors"],
        })
        for p in block["posts"]:
            all_posts.append(p)
            toks = tokens_from_title(p["title"])
            for w in toks:
                counter[w] += 1
                if w in BOOST or any(b in w for b in BOOST):
                    boost_hits[w] += 2
                    counter[w] += 1  # 가중

    # 상위 키워드
    top = [{"keyword": k, "score": v} for k, v in counter.most_common(40)]
    beauty_top = [{"keyword": k, "score": v} for k, v in boost_hits.most_common(25)]

    # 중복 제목 제거
    seen = set()
    unique_posts = []
    for p in all_posts:
        key = p["title"].lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        unique_posts.append(p)

    payload = {
        "source": "reddit.com public RSS",
        "method": "hot.rss + top.rss?t=week",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "subreddits": SUBREDDITS,
        "post_count": len(unique_posts),
        "per_subreddit": per_sub,
        "hot_keywords": top,
        "beauty_keywords": beauty_top,
        "posts": unique_posts[:80],
        "note": "커뮤니티 실수요 시그널. 광고 키워드·S등급 코칭 보강용. 판매 순위 아님.",
    }
    if len(unique_posts) == 0:
        payload["reason"] = "모든 피드 수집 실패 또는 빈 응답"
        payload["status"] = "empty"
    else:
        payload["status"] = "ok"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"reddit_beauty_signals.json → posts={len(unique_posts)} keywords={len(top)}")
    for row in beauty_top[:8]:
        print(f"  · {row['keyword']} ({row['score']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
