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
#
# 한글 낱말을 나중에 넣었다. 처음에는 영어만 봤는데 한국어 영상이 들어오니
# 하나도 안 걸렸다. 채널톡의 스퀘어129 창업 인터뷰가 그랬다. 역마진과 플랫폼
# 전략을 다루는데 제목도 설명도 전부 한글이라 knowledge 로 떨어졌다.
TEAM_TERMS = {
    "listing": ["shopify", "product page", "listing", "description", "seo",
                "conversion", "checkout",
                "쇼피파이", "상세페이지", "상품페이지", "전환율", "결제"],
    "design": ["theme", "design", "layout", "branding", "logo", "template",
               "디자인", "브랜딩", "로고", "레이아웃", "테마", "폰트"],
    "market": ["k-beauty", "kbeauty", "korean skincare", "trend", "viral",
               "tiktok", "haul", "review",
               "브랜드", "고객", "수요", "시장조사", "트렌드", "플랫폼",
               "입점", "해외진출", "일본", "매출"],
    "pricing": ["pricing", "margin", "profit", "shipping cost", "dropship",
                "가격", "마진", "원가", "역마진", "수익", "손익", "객단가",
                "경영", "전략", "창업", "재고"],
    "legal": ["fda", "compliance", "label", "regulation", "customs", "import",
              "규제", "인증", "통관", "라벨", "성분표시"],
    "sourcing": ["daiso", "다이소", "sourcing", "supplier", "wholesale",
                 "소싱", "도매", "공급처", "사입"],
}

# 사람이 팀을 직접 적을 수 있게 한다. 자동 분류는 어디까지나 추측이라
# 아는 사람이 정해주면 그게 맞다.
KNOWN_TEAMS = set(TEAM_TERMS) | {"knowledge"}


def parse_links(text: str) -> list[dict]:
    """한 줄을 읽는다. 칸은 | 로 나눈다.

    예전 형식은 'URL | 메모' 였다. 팀 칸을 넣으면서 형식이 바뀌었는데
    이미 적어둔 줄을 다시 고치게 하고 싶지 않았다. 그래서 두 번째 칸이
    아는 팀 이름이면 팀으로, 아니면 메모로 읽는다. 둘 다 그대로 돈다.

        https://... | 쇼피파이 2026 신기능        -> 메모  (예전 형식)
        https://... | pricing,market | 역마진      -> 팀 지정
    """
    out, seen = [], set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [x.strip() for x in line.split("|")]
        url = parts[0]
        teams, note = [], ""
        if len(parts) > 1:
            cand = [t.strip().lower() for t in parts[1].split(",") if t.strip()]
            if cand and all(t in KNOWN_TEAMS for t in cand):
                teams = cand
                note = parts[2] if len(parts) > 2 else ""
            else:
                note = " | ".join(parts[1:])
        m = VID.search(url)
        if not m:
            out.append({"raw": line[:80], "video_id": None,
                        "error": "URL 에서 영상 ID 를 못 찾았다"})
            continue
        vid = m.group(1)
        if vid in seen:
            continue
        seen.add(vid)
        out.append({"video_id": vid, "note": note, "teams": teams,
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

    def grab_json_str(field: str) -> str:
        """JSON 문자열 값을 이스케이프까지 제대로 읽는다.

        예전에는 "title":"([^"]+)" 로 잘라냈다. 그런데 제목에 큰따옴표가
        들어 있으면 거기서 끊긴다. 언어의 정원의 '천재들은 "어떻게"
        이미지로 요약하는 걸까?' 가 '천재들은 \\' 로 저장됐다.
        이스케이프된 따옴표는 넘기고, 값 전체를 json 으로 풀어야 한다.
        """
        m = re.search(r'"' + field + r'":"((?:[^"\\]|\\.)*)"', html)
        if not m:
            return ""
        try:
            return json.loads('"' + m.group(1) + '"')
        except json.JSONDecodeError:
            return m.group(1)

    title = grab_json_str("title")
    if not title:
        title = grab(r"<meta name=\"title\" content=\"([^\"]{3,200})\"")
    if not title:
        title = grab(r"<title>([^<]{3,200})</title>").replace(" - YouTube", "")
    desc = grab_json_str("shortDescription")[:600]
    views = grab(r'"viewCount":"(\d+)"')
    return {
        "title": title.strip(),
        "channel": grab_json_str("ownerChannelName"),
        "views": int(views) if views else None,
        "length_sec": int(grab(r'"lengthSeconds":"(\d+)"') or 0) or None,
        "published": grab(r'"uploadDate":"([\d-]{10})"') or grab(r'"publishDate":"([\d-]{10})"'),
        "description": desc.strip(),
        "error": "" if title else "제목을 못 읽었다",
    }


def route(v: dict, forced: list[str] | None = None) -> list[str]:
    """사람이 지정했으면 그걸 쓰고, 아니면 제목과 설명으로 추측한다."""
    if forced:
        return list(forced)
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
            "#\n"
            "# 팀을 직접 지정하려면 URL 뒤에 팀 이름을 적으세요.\n"
            "#   pricing market listing design legal sourcing knowledge\n"
            "#   여러 팀은 쉼표로. 안 적으면 제목과 설명으로 자동 분류합니다.\n"
            "#\n"
            "# https://www.youtube.com/watch?v=XXXXXXXXXXX | 왜 넣었는지\n"
            "# https://www.youtube.com/watch?v=XXXXXXXXXXX | pricing,market | 메모\n",
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
            # 팀 지정을 나중에 바꿀 수 있다. 다시 받지 않고 분류만 고친다.
            was["teams"] = route(was, x.get("teams"))
            was["team_source"] = "사람 지정" if x.get("teams") else "자동 분류"
            videos.append(was)
            continue
        got = fetch_video(vid)
        fetched += 1
        videos.append({
            "video_id": vid, "url": x["url"], "note": x.get("note", ""),
            **got,
            "teams": route(got, x.get("teams")),
            "team_source": "사람 지정" if x.get("teams") else "자동 분류",
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
