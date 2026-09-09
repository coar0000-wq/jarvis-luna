#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Learn With Shopify 채널 수집 - 중단됨.

왜 멈췄나
  youtube.com/robots.txt 가 /feeds/videos.xml 을 Disallow 한다.
  이 스크립트는 그 경로를 부른다. 그래서 돌리지 않는다.

  지금 어느 워크플로도 이 파일을 부르지 않는다. 하지만 파일이 남아
  있으면 누군가 손으로 돌릴 수 있다. 그래서 실행 자체를 막았다.
  주석으로 "쓰지 마세요" 라고만 적어두면 언젠가 돌아간다.

대신 쓰는 길
  scripts/ingest_youtube_links.py    사람이 URL 을 넣으면 /watch 로 받는다.
  scripts/ingest_youtube_channels.py 채널 페이지를 받는다. /@ 는 막혀 있지 않다.
  scripts/collect_serpapi_youtube.py SerpApi 로 검색한다.

  robots.txt 가 막은 것은 /feeds/videos.xml, /results, /youtubei/, /api/ 다.
  /watch 와 /@ 와 /channel/ 은 막혀 있지 않다. 2026-09-06 확인.

  YouTube Data API v3 키가 생기면 그 경로로 되살릴 수 있다.

출력 (중단 전 기준)
  data/shopify_learn_with_shopify.json
"""
from __future__ import annotations

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent if (Path(__file__).resolve().parent.name == "scripts") else Path(__file__).resolve().parent
# 스크립트가 repo 루트 또는 scripts/ 에 있어도 동작
if (ROOT / "data").is_dir():
    DATA = ROOT / "data"
elif (ROOT.parent / "data").is_dir():
    DATA = ROOT.parent / "data"
    ROOT = ROOT.parent
else:
    DATA = ROOT / "data"

OUT = DATA / "shopify_learn_with_shopify.json"
CHANNEL_ID = "UC7geKfz2-IH0rsgRBtHTm0g"
NOTEBOOKLM_URL = "https://notebook.google.com/notebook/88638802-cf08-47ca-a3ec-12453818438a"
NOTEBOOKLM_ID = "88638802-cf08-47ca-a3ec-12453818438a"
CHANNEL_HANDLE = "@learnwithshopify"
RSS = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
UA = "JARVIS-LUNA/1.0 (knowledge-sync; free-rss)"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def clean(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip()


def collect() -> dict:
    raw = fetch(RSS)
    root = ET.fromstring(raw)
    ns = {
        "a": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }
    videos = []
    for e in root.findall("a:entry", ns):
        title = clean(e.findtext("a:title", default="", namespaces=ns))
        published = clean(e.findtext("a:published", default="", namespaces=ns))
        vid = clean(e.findtext("yt:videoId", default="", namespaces=ns))
        link = ""
        for l in e.findall("a:link", ns):
            href = l.attrib.get("href") or ""
            if "watch" in href or l.attrib.get("rel") == "alternate":
                link = href
                break
        if not link and vid:
            link = f"https://www.youtube.com/watch?v={vid}"
        desc = ""
        mg = e.find("media:group", ns)
        if mg is not None:
            desc = clean(mg.findtext("media:description", default="", namespaces=ns))[:400]
        videos.append({
            "video_id": vid,
            "title": title,
            "url": link,
            "published": published,
            "description_snip": desc,
            "channel": "Learn With Shopify",
            "channel_id": CHANNEL_ID,
            "source": "youtube_rss_free",
            "analyze_with_notebook": NOTEBOOKLM_URL,
        })

    # 제목 키워드 (전략·검색용)
    seed = [
        "shopify", "store", "entrepreneur", "ai", "claude", "checkout",
        "dropship", "marketing", "sell", "product", "browser", "cowork",
        "ecommerce", "sidekick", "build", "run",
    ]
    kw: dict[str, int] = {}
    for v in videos:
        low = v["title"].lower()
        for w in seed:
            if w in low:
                kw[w] = kw.get(w, 0) + 1

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "channel": "Learn With Shopify",
        "channel_handle": CHANNEL_HANDLE,
        "channel_id": CHANNEL_ID,
        "channel_url": f"https://www.youtube.com/{CHANNEL_HANDLE}",
        "collection_method": "YouTube Atom RSS (free, no API key)",
        "rss_url": RSS,
        "count": len(videos),
        "title_keywords": dict(sorted(kw.items(), key=lambda x: -x[1])),
        "videos": videos,
        "video_analysis": {
            "tool": "Google NotebookLM",
            "notebook_url": NOTEBOOKLM_URL,
            "notebook_id": NOTEBOOKLM_ID,
            "instruction": "YouTube/Shorts 분석 시 이 노트북 사용",
        },
        "jarvis_use": [
            "knowledge corpus / Obsidian notes",
            "Shopify operations education signals",
            "strategy keywords for dropshipping dashboard",
        ],
    }


# 2026-09-06 중단: youtube.com/robots.txt 가 "Disallow: /feeds/videos.xml".
# CSS-Tricks·Nielsen Norman·r/KoreanBeauty 를 같은 이유로 뺐으므로 예외 없음.
# 정식 경로는 YouTube Data API v3 (YOUTUBE_API_KEY 필요).
ROBOTS_BLOCKED = True

def main() -> int:
    if ROBOTS_BLOCKED:
        print("youtube.com/robots.txt 가 /feeds/videos.xml 을 막고 있어 수집하지 않는다. YouTube Data API v3 로 전환 필요.")
        return 0
    DATA.mkdir(parents=True, exist_ok=True)
    payload = collect()
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Learn With Shopify: {payload['count']} videos → {OUT}")
    for v in payload["videos"][:5]:
        print(f"  - {v['title'][:70]}")
    return 0


# 실행을 막는다. robots.txt 가 막은 경로를 부르는 코드다.
# 되살리려면 RSS 대신 Data API v3 로 바꾼 뒤 이 줄을 지운다.
DISABLED = "youtube.com/robots.txt 가 /feeds/videos.xml 을 Disallow 한다"


if __name__ == "__main__":
    import sys as _sys
    print(f"::error::이 수집기는 중단됐다. {DISABLED}", file=_sys.stderr)
    print("대신 ingest_youtube_links.py 나 ingest_youtube_channels.py 를 쓴다.",
          file=_sys.stderr)
    raise SystemExit(2)
