#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JARVIS YouTube 실수집 (가짜 데이터 금지)

- YouTube Atom RSS 만 사용 (API 키 불필요)
- 기본 채널: Learn With Shopify (UC7geKfz2-IH0rsgRBtHTm0g)
- 추가 채널: 환경변수 YOUTUBE_CHANNEL_IDS (쉼표 구분)
- RSS 실패·0건이면 exit 1 (빈 성공/하드코딩 목록 금지)

출력:
  data/youtube_real_videos.json
  data/shopify_learn_with_shopify.json  (Learn With Shopify 채널일 때)
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

LEARN_WITH_SHOPIFY = "UC7geKfz2-IH0rsgRBtHTm0g"
NOTEBOOKLM_URL = "https://notebook.google.com/notebook/88638802-cf08-47ca-a3ec-12453818438a"
NOTEBOOKLM_ID = "88638802-cf08-47ca-a3ec-12453818438a"
FEATURED_SHORT = "75DKB013fu4"
UA = "JARVIS-LUNA/1.0 (youtube-rss-real; no-fake-data)"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def clean(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip()


def channel_ids() -> list[str]:
    env = [
        c.strip()
        for c in (os.environ.get("YOUTUBE_CHANNEL_IDS") or "").replace("\n", ",").split(",")
        if c.strip()
    ]
    return list(dict.fromkeys(env + [LEARN_WITH_SHOPIFY]))


def collect_channel(cid: str) -> dict:
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
    raw = fetch(url)
    root = ET.fromstring(raw)
    ns = {
        "a": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }
    channel_title = clean(root.findtext("a:title", default="", namespaces=ns))
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
        if not title or not vid:
            continue
        item = {
            "video_id": vid,
            "title": title,
            "url": link,
            "published": published,
            "description_snip": desc,
            "channel_id": cid,
            "channel_title": channel_title,
            "source": "youtube_atom_rss",
            "collection_method": "live_rss",
            "analyze_with_notebook": NOTEBOOKLM_URL,
        }
        if vid == FEATURED_SHORT:
            item["priority"] = "critical"
            item["featured"] = True
            item["shorts_url"] = f"https://www.youtube.com/shorts/{vid}"
        videos.append(item)
    return {
        "channel_id": cid,
        "channel_title": channel_title,
        "rss_url": url,
        "count": len(videos),
        "videos": videos,
    }


def write_shopify_learn(videos: list[dict], channel_title: str) -> None:
    """Learn With Shopify 전용 산출물 (기존 경로 유지)."""
    # featured first
    featured = None
    ordered = []
    for v in videos:
        row = {
            "video_id": v["video_id"],
            "title": v["title"],
            "url": v["url"] if "shorts/" in (v.get("url") or "") or v["video_id"] != FEATURED_SHORT
            else f"https://www.youtube.com/shorts/{FEATURED_SHORT}",
            "published": v.get("published"),
            "description_snip": v.get("description_snip"),
            "channel": "Learn With Shopify",
            "channel_id": LEARN_WITH_SHOPIFY,
            "source": "youtube_rss_free",
            "analyze_with_notebook": NOTEBOOKLM_URL,
        }
        if v["video_id"] == FEATURED_SHORT:
            row["priority"] = "critical"
            row["featured"] = True
            row["jarvis_note"] = (
                "핵심: Shopify Product Network — 자사에 없는 상품도 타 브랜드 재고를 스토어에 노출해 "
                "검색·추천으로 놓친 매출을 회수. 다이소→Shopify 드롭십 확장 시 카탈로그 보완 전략으로 중요."
            )
            row["apply_to"] = [
                "shopify_catalog_strategy",
                "lost_sales_recovery",
                "cross_brand_product_network",
                "daiso_to_shopify_expansion",
            ]
            featured = row
        else:
            ordered.append(row)
    if featured:
        ordered = [featured] + ordered

    seed = [
        "shopify", "store", "entrepreneur", "ai", "claude", "checkout",
        "dropship", "marketing", "sell", "product", "browser", "cowork",
        "ecommerce", "sidekick", "build", "run", "network",
    ]
    kw: dict[str, int] = {}
    for v in ordered:
        low = (v.get("title") or "").lower()
        for w in seed:
            if w in low:
                kw[w] = kw.get(w, 0) + 1

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "channel": "Learn With Shopify",
        "channel_handle": "@learnwithshopify",
        "channel_id": LEARN_WITH_SHOPIFY,
        "channel_url": "https://www.youtube.com/@learnwithshopify",
        "collection_method": "YouTube Atom RSS (live, no fake data)",
        "rss_url": f"https://www.youtube.com/feeds/videos.xml?channel_id={LEARN_WITH_SHOPIFY}",
        "count": len(ordered),
        "title_keywords": dict(sorted(kw.items(), key=lambda x: -x[1])),
        "video_analysis": {
            "tool": "Google NotebookLM",
            "notebook_url": NOTEBOOKLM_URL,
            "notebook_id": NOTEBOOKLM_ID,
            "instruction": "YouTube/Shorts 분석 시 이 노트북 사용",
        },
        "videos": ordered,
        "jarvis_use": [
            "knowledge corpus / Obsidian notes",
            "Shopify operations education signals",
            "strategy keywords for dropshipping dashboard",
        ],
        "notes": (
            "featured_video 는 JARVIS 우선 학습·전략 반영 대상. "
            "가짜 하드코딩 목록 없음 — RSS 실응답만 저장."
        ),
    }
    if featured:
        payload["featured_video"] = {
            "video_id": featured["video_id"],
            "title": featured["title"],
            "url": featured["url"],
            "shorts_url": f"https://www.youtube.com/shorts/{featured['video_id']}",
            "priority": "critical",
            "why_important": featured.get("jarvis_note"),
            "apply_to": featured.get("apply_to"),
            "published": featured.get("published"),
            "notebooklm_url": NOTEBOOKLM_URL,
            "analyze_with": "NotebookLM (jarvis_video_analysis.json)",
        }
    out = DATA / "shopify_learn_with_shopify.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Learn With Shopify: {len(ordered)} → {out}")


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    ids = channel_ids()
    channels = []
    all_videos = []
    errors = []

    for cid in ids:
        try:
            ch = collect_channel(cid)
            if ch["count"] == 0:
                errors.append({"channel_id": cid, "error": "RSS returned 0 videos"})
                continue
            channels.append({
                "channel_id": ch["channel_id"],
                "channel_title": ch["channel_title"],
                "rss_url": ch["rss_url"],
                "count": ch["count"],
            })
            all_videos.extend(ch["videos"])
            print(f"OK {ch['channel_title'] or cid}: {ch['count']} videos")
            if cid == LEARN_WITH_SHOPIFY:
                write_shopify_learn(ch["videos"], ch["channel_title"])
        except Exception as e:
            errors.append({"channel_id": cid, "error": f"{type(e).__name__}: {e}"})
            print(f"FAIL {cid}: {e}", file=sys.stderr)

    if not all_videos:
        print("ERROR: no real YouTube videos collected — refusing fake fallback", file=sys.stderr)
        return 1

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "youtube_atom_rss",
        "truth_note": "Live RSS only. No hardcoded product/video lists.",
        "notebooklm_url": NOTEBOOKLM_URL,
        "channels": channels,
        "count": len(all_videos),
        "videos": all_videos,
        "errors": errors,
    }
    out = DATA / "youtube_real_videos.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"YouTube real: {len(all_videos)} videos from {len(channels)} channel(s) → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
