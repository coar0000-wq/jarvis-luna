#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""사람이 찾아낸 영상을 목록에 넣으면 받아온다.

왜 만들었나
  YouTube 수집이 두 갈래였다. 채널 RSS 와 SerpApi 검색어. 둘 다 "내가
  지금 본 이 영상" 은 못 받는다. 채널을 구독하지 않았거나 검색어에
  안 걸리면 그냥 빠진다.

  실제로 이런 일이 있었다. 사용자가 영상 두 개를 물었는데 하나는
  들어와 있고(gugo50_VbjE) 하나는 없었다(jUxSAGCaJIU). 없던 쪽은
  Learn With Shopify 의 "Shopify Just Changed How You Sell" 였다.
  구독 채널이었는데도 RSS 가 막히면서 빠진 것이다.

  좋은 영상을 봤을 때 넣을 데가 있어야 한다. 그게 이 스크립트다.

넣는 법
  data/manual/youtube_links.txt 에 URL 을 한 줄에 하나씩 적는다.
  # 로 시작하면 주석. 뒤에 | 를 쓰고 메모를 붙일 수 있다.

    https://www.youtube.com/watch?v=jUxSAGCaJIU | 쇼피파이 신기능
    https://youtu.be/gugo50_VbjE

robots.txt
  youtube.com/robots.txt 는 /feeds/videos.xml 을 막지만 /watch 는 막지
  않는다. 그래서 개별 영상 페이지는 받아도 된다. 2026-09-06 확인.
  목록을 긁는 게 아니라 사람이 지정한 것만 하나씩 받는다.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINKS = ROOT / "data" / "manual" / "youtube_links.txt"
OUT = ROOT / "data" / "youtube_manual.json"
# 사람이 브라우저로 보는 것과 같은 페이지를 받는다.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
TIMEOUT = 25
DELAY = 3.0

VID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")

# 어느 팀이 볼 자료인지. 제목과 설명으로 나눈다.
TEAM_TERMS = {
    "listing": ["shopify", "product page", "listing", "description", "seo",
                "conversion", "checkout"],
    "design": ["theme", "design", "layout", "branding", "logo", "template"],
    "market": ["k-beauty", "kbeauty", "korean skincare", "trend", "viral",
               "tiktok", "haul", "review"],
    "pricing": ["pricing", "margin", "profit", "shipping cost", "dropship"],
    "legal": ["fda", "compliance", "label", "regulation", "customs", "import"],
    "sourcing": ["daiso", "다이소", "sourcing", "supplier", "wholesale"],
}


def parse_links(text: str) -> list[dict]:
    out, seen = [], set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        url, _, note = line.partition("|")
        m = VID.search(url.strip())
        if not m:
            out.append({"raw": line[:80], "video_id": None,
                        "error": "URL 에서 영상 ID 를 못 찾았다"})
            continue
        vid = m.group(1)
        if vid in seen:
            continue
        seen.add(vid)
        out.append({"video_id": vid, "note": note.strip(),
                    "url": f"https://www.youtube.com/watch?v={vid}"})
    return out


def fetch_video(vid: str) -> dict:
    url = f"https://www.youtube.com/watch?v={vid}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            html = r.read(1200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    except (urllib.error.URLError, OSError) as e:
        return {"error": f"{type(e).__name__}"}

    def grab(pat, flags=0):
        m = re.search(pat, html, flags)
        return m.group(1) if m else ""

    title = grab(r'"videoDetails":\{.*?"title":"([^"]{2,200})"', re.S)
    if not title:
        title = grab(r"<title>([^<]{3,200})</title>").replace(" - YouTube", "")
    desc = grab(r'"shortDescription":"([^"]{0,1200})')
    # JSON 문자열 안이라 이스케이프가 남아 있다. 사람이 읽게 푼다.
    for a, b in (("\\u0026", "&"), ("\\n", " "), ('\\"', '"'), ("\\/", "/")):
        title = title.replace(a, b)
        desc = desc.replace(a, b)
    views = grab(r'"viewCount":"(\d+)"')
    return {
        "title": title.strip(),
        "channel": grab(r'"ownerChannelName":"([^"]{2,60})"'),
        "views": int(views) if views else None,
        "length_sec": int(grab(r'"lengthSeconds":"(\d+)"') or 0) or None,
        "published": grab(r'"uploadDate":"([\d-]{10})"') or grab(r'"publishDate":"([\d-]{10})"'),
        "description": desc.strip()[:600],
        "error": "" if title else "제목을 못 읽었다",
    }


def route(v: dict) -> list[str]:
    blob = f'{v.get("title", "")} {v.get("description", "")}'.lower()
    hit = [t for t, terms in TEAM_TERMS.items() if any(k in blob for k in terms)]
    return hit or ["knowledge"]


def main() -> int:
    if not LINKS.exists():
        LINKS.parent.mkdir(parents=True, exist_ok=True)
        LINKS.write_text(
            "# 좋은 영상을 보면 여기에 한 줄씩 붙여넣으세요.\n"
            "# '#' 으로 시작하면 주석, 뒤에 | 를 쓰면 메모를 남길 수 있습니다.\n"
            "#\n"
            "# https://www.youtube.com/watch?v=XXXXXXXXXXX | 왜 넣었는지\n",
            encoding="utf-8")
        print(f"{LINKS.relative_to(ROOT)} 를 만들었다. URL 을 넣으면 다음 실행에 받는다.")
        return 0

    links = parse_links(LINKS.read_text(encoding="utf-8-sig"))
    todo = [x for x in links if x.get("video_id")]
    bad = [x for x in links if not x.get("video_id")]

    prev = {}
    try:
        old = json.loads(OUT.read_text(encoding="utf-8-sig"))
        prev = {v["video_id"]: v for v in (old.get("videos") or [])}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass

    videos, fetched = [], 0
    for x in todo:
        vid = x["video_id"]
        was = prev.get(vid)
        # 이미 받은 것은 다시 받지 않는다. 제목이 바뀔 일은 드물다.
        if was and was.get("title") and not was.get("error"):
            was["note"] = x.get("note") or was.get("note", "")
            videos.append(was)
            continue
        got = fetch_video(vid)
        fetched += 1
        videos.append({
            "video_id": vid, "url": x["url"], "note": x.get("note", ""),
            **got,
            "teams": route(got),
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "source": "사람이 직접 지정 (data/manual/youtube_links.txt)",
        })
        time.sleep(DELAY)

    ok = [v for v in videos if v.get("title") and not v.get("error")]
    failed = [v for v in videos if v.get("error")]
    by_team: dict = {}
    for v in ok:
        for t in v.get("teams") or []:
            by_team[t] = by_team.get(t, 0) + 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/ingest_youtube_links.py",
        "입력": str(LINKS.relative_to(ROOT)),
        "robots": ("youtube.com/robots.txt 는 /feeds/videos.xml 을 막지만 /watch 는 "
                   "막지 않는다. 목록을 긁는 게 아니라 사람이 지정한 것만 받는다."),
        "total": len(videos),
        "ok": len(ok),
        "failed": len(failed),
        "fetched_this_run": fetched,
        "bad_lines": bad,
        "by_team": by_team,
        "videos": videos,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for _ in range(4):
        OUT.write_text(body, encoding="utf-8")
        try:
            json.loads(OUT.read_text(encoding="utf-8-sig"))
            break
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            time.sleep(0.5)
    else:
        print("기록 검증 실패", file=sys.stderr)
        return 1

    print(f"영상 {len(videos)}건 · 성공 {len(ok)} · 실패 {len(failed)} "
          f"· 이번에 새로 받은 것 {fetched}")
    for v in ok[-5:]:
        vw = f"{v['views']:,}회" if v.get("views") else "-"
        print(f"  [{','.join(v.get('teams') or [])}] {str(v.get('title'))[:52]} "
              f"· {v.get('channel')} · {vw}")
    for v in failed:
        print(f"  실패 {v['video_id']} — {v.get('error')}")
    for b in bad:
        print(f"  못 읽은 줄: {b.get('raw')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
