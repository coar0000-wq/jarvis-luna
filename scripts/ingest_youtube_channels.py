#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""사람이 지정한 채널의 최신 영상을 받는다.

왜 만들었나
  영상 하나씩 넣는 길(ingest_youtube_links.py)은 만들었는데 채널 단위로
  지켜보는 길이 없었다. 좋은 채널을 찾으면 그 채널이 새로 올리는 것도
  계속 받고 싶은 게 당연하다.

  원래 그 일은 채널 RSS 가 했는데 robots.txt 가 막았다.
  다행히 채널 페이지 자체는 막혀 있지 않다.

robots.txt 확인 (2026-09-06)
  youtube.com/robots.txt 의 Disallow 목록에 /@ 도 /channel/ 도 없다.
  막힌 것은 /feeds/videos.xml, /results, /youtubei/, /api/ 등이다.
  그래서 채널 페이지를 사람이 보는 것처럼 한 번 받아 목록만 읽는다.
  검색 결과를 긁는 게 아니라 지정된 채널만 하나씩 본다.

넣는 법
  data/manual/youtube_channels.txt 에 한 줄씩.
    https://www.youtube.com/@uxpeak | design | UX/UI 리디자인
  두 번째 칸은 팀(비우면 제목으로 자동 분류), 세 번째는 메모.
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
LIST = ROOT / "data" / "manual" / "youtube_channels.txt"
OUT = ROOT / "data" / "youtube_channels.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
TIMEOUT = 30
DELAY = 5.0          # 채널마다 넉넉히 쉰다. 목록을 훑는 게 아니다.
MAX_VIDEOS = 30

# 낱말표는 team_routing.py 한 곳에 있다. 예전에는 이 파일과
# ingest_youtube_links.py 가 각자 표를 들고 있었고, 한쪽에만 한글을
# 넣었다가 채널 영상 20건이 전부 knowledge 로 떨어졌다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from team_routing import TEAM_TERMS, KNOWN_TEAMS, route as route_teams  # noqa: E402

def load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(1600000).decode("utf-8", "replace")


def parse_channel(html: str) -> dict:
    """채널 페이지에서 채널 정보와 영상 목록을 읽는다.

    유튜브가 2026 년에 구조를 lockupViewModel 로 바꿨다. 예전 videoRenderer
    는 이제 안 나온다. 둘 다 훑도록 해서 다시 바뀌어도 한쪽은 걸리게 한다.
    """
    def find(pat, flags=0):
        m = re.search(pat, html, flags)
        return m.group(1) if m else ""

    info = {
        "channel_name": find(r'"channelMetadataRenderer":\{.*?"title":"([^"]{2,60})"', re.S),
        "channel_id": find(r'"externalId":"(UC[\w-]{20,24})"'),
        "subscribers": find(r'"subscriberCountText":\{"simpleText":"([^"]{2,20})"')
                       or find(r'([\d.]+[KM]?) subscribers'),
    }
    m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});</script>", html, re.S)
    if not m:
        return {**info, "videos": [], "error": "ytInitialData 를 못 찾았다"}
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {**info, "videos": [], "error": "ytInitialData 파싱 실패"}

    found: list[dict] = []

    def rows_of(meta: dict) -> list[str]:
        md = (meta.get("metadata") or {}).get("contentMetadataViewModel") or {}
        out = []
        for row in (md.get("metadataRows") or []):
            for part in (row.get("metadataParts") or []):
                txt = (part.get("text") or {}).get("content")
                if txt:
                    out.append(txt)
        return out

    def walk(o):
        if isinstance(o, dict):
            if "lockupViewModel" in o:                       # 2026 구조
                lv = o["lockupViewModel"]
                meta = (lv.get("metadata") or {}).get("lockupMetadataViewModel") or {}
                title = (meta.get("title") or {}).get("content") or ""
                vid = lv.get("contentId")
                if vid and title:
                    rows = rows_of(meta)
                    found.append({"video_id": vid, "title": title,
                                  "views_text": rows[0] if rows else "",
                                  "published_text": rows[1] if len(rows) > 1 else ""})
            elif "videoRenderer" in o:                        # 옛 구조
                vr = o["videoRenderer"]
                t = vr.get("title") or {}
                title = t.get("simpleText") or "".join(
                    x.get("text", "") for x in (t.get("runs") or []))
                vid = vr.get("videoId")
                if vid and title:
                    found.append({
                        "video_id": vid, "title": title,
                        "views_text": (vr.get("viewCountText") or {}).get("simpleText", ""),
                        "published_text": (vr.get("publishedTimeText") or {}).get("simpleText", ""),
                    })
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(data)
    seen, uniq = set(), []
    for v in found:
        if v["video_id"] in seen:
            continue
        seen.add(v["video_id"])
        uniq.append(v)
    return {**info, "videos": uniq[:MAX_VIDEOS], "error": ""}


def views_to_int(text: str) -> int | None:
    m = re.match(r"([\d,.]+)\s*([KMB])?", (text or "").strip(), re.I)
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return int(n * {"k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower(), 1))


def route(title: str, forced: str) -> list[str]:
    return route_teams(title, forced or None)


def prev_channels() -> dict:
    """지난 회차 채널 결과를 URL 로 꺼내온다."""
    old = load(OUT) or {}
    return {c.get("url"): c for c in (old.get("items") or []) if c.get("url")}


def prev_teams() -> dict:
    """지난 회차에 정한 팀을 영상 번호로 꺼내온다.

    유튜브가 제목을 A/B 로 돌린다. 같은 영상인데 회차마다 제목이 다르다.
    실제로 CSr4DYGUPOM 이 '브랜딩 잘하는 인스타 채널 큐레이션' 과
    '인스타그램 잘하고 싶다면 이 계정부터 보세요' 사이를 오갔고,
    그때마다 디자인팀에 들어왔다 빠졌다 했다.

    한 번 정한 팀은 그대로 둔다. 제목이 흔들린다고 자료가 옮겨
    다니면 팀에서 어제 본 것을 오늘 못 찾는다.
    """
    old = load(OUT) or {}
    out = {}
    for c in old.get("items") or []:
        for v in c.get("videos") or []:
            if v.get("video_id") and v.get("teams"):
                out[v["video_id"]] = {"teams": v["teams"],
                                      "title": v.get("title", "")}
    return out


def main() -> int:
    if not LIST.exists():
        LIST.parent.mkdir(parents=True, exist_ok=True)
        LIST.write_text(
            "# 지켜볼 유튜브 채널. 한 줄에 하나씩.\n"
            "# 형식: URL | 팀(선택) | 메모(선택)\n"
            "# 팀을 비우면 영상 제목으로 자동 분류합니다.\n"
            "#\n"
            "# https://www.youtube.com/@uxpeak | design | UX/UI 리디자인\n",
            encoding="utf-8")
        print(f"{LIST.relative_to(ROOT)} 를 만들었다. 채널을 넣으면 다음 실행에 받는다.")
        return 0

    entries = []
    for raw in LIST.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        url = parts[0]
        if "youtube.com" not in url:
            continue
        entries.append({"url": url.rstrip("/"),
                        "team": parts[1] if len(parts) > 1 else "",
                        "note": parts[2] if len(parts) > 2 else ""})

    pinned = prev_teams()
    before = prev_channels()
    retitled = []
    channels, all_videos = [], []
    for e in entries:
        base = e["url"].split("/videos")[0]
        try:
            html = fetch(base + "/videos")
            info = parse_channel(html)
        except urllib.error.HTTPError as ex:
            info = {"videos": [], "error": f"HTTP {ex.code}"}
        except (urllib.error.URLError, OSError) as ex:
            info = {"videos": [], "error": type(ex).__name__}

        vids = []
        for v in info.get("videos") or []:
            was = pinned.get(v["video_id"])
            if was and not e["team"]:
                teams = was["teams"]
                if was["title"] and was["title"] != v["title"]:
                    retitled.append({"video_id": v["video_id"],
                                     "before": was["title"],
                                     "after": v["title"],
                                     "kept_teams": teams})
            else:
                teams = route(v["title"], e["team"])
            vids.append({
                **v,
                "views": views_to_int(v.get("views_text", "")),
                "url": f"https://www.youtube.com/watch?v={v['video_id']}",
                "channel": info.get("channel_name") or base.rsplit("/", 1)[-1],
                "teams": teams,
            })
        # 받기에 실패했는데 지난 회차 것이 있으면 그걸 유지한다.
        # 예전에는 실패하면 그 채널 영상이 통째로 사라졌다. 한 번 끊긴
        # 것 때문에 20건이 날아가고 집계가 반토막 났다.
        # 지난 것임을 감추지 않으려고 stale 과 last_ok_at 을 함께 적는다.
        was = before.get(base)
        stale, last_ok = False, ""
        if not vids and was and (was.get("videos") or []):
            vids = was["videos"]
            all_videos.extend(vids)
            stale = True
            last_ok = was.get("last_ok_at") or was.get("checked_at", "")
            info = {**info, "channel_name": was.get("channel_name", ""),
                    "channel_id": was.get("channel_id", ""),
                    "subscribers": was.get("subscribers", ""),
                    "error": info.get("error", "") + " (지난 회차 결과 유지)"}
        else:
            all_videos.extend(vids)
            last_ok = datetime.now(timezone.utc).isoformat()
        channels.append({
            "stale": stale, "last_ok_at": last_ok,
            "url": base, "note": e["note"], "team_hint": e["team"],
            "channel_name": info.get("channel_name", ""),
            "channel_id": info.get("channel_id", ""),
            "subscribers": info.get("subscribers", ""),
            "video_count": len(vids),
            "error": info.get("error", ""),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "videos": vids,
        })
        time.sleep(DELAY)

    by_team: dict = {}
    for v in all_videos:
        for t in v["teams"]:
            by_team[t] = by_team.get(t, 0) + 1
    top = sorted((v for v in all_videos if v.get("views")),
                 key=lambda x: -x["views"])[:15]
    failed = [c for c in channels if c["error"] and not c.get("stale")]
    kept = [c for c in channels if c.get("stale")]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/ingest_youtube_channels.py",
        "입력": str(LIST.relative_to(ROOT)),
        "robots": ("youtube.com/robots.txt 의 Disallow 목록에 /@ 와 /channel/ 은 없다. "
                   "막힌 것은 /feeds/videos.xml, /results, /youtubei/ 등이다. "
                   "지정된 채널만 하나씩 본다. 2026-09-06 확인."),
        "channels": len(channels),
        "videos": len(all_videos),
        "failed": failed,
        "지난결과_유지": [{"url": c["url"], "last_ok_at": c["last_ok_at"],
                     "videos": c["video_count"]} for c in kept],
        "by_team": by_team,
        "팀_고정": ("한 번 정한 팀은 유지한다. 유튜브가 제목을 A/B 로 돌려서 "
                 "같은 영상이 회차마다 다른 팀으로 가는 일이 있었다."),
        "제목_바뀐_영상": retitled,
        "top_by_views": top,
        "items": channels,
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

    print(f"채널 {len(channels)}개 · 영상 {len(all_videos)}건 · 실패 {len(failed)}"
          + (f" · 제목 바뀜 {len(retitled)}건(팀 유지)" if retitled else "")
          + (f" · 지난 결과 유지 {len(kept)}개 채널" if kept else ""))
    for c in channels:
        if c["error"] and not c.get("stale"):
            print(f"  실패 {c['url']} — {c['error']}")
            continue
        if c.get("stale"):
            print(f"  유지 {c['channel_name']} · {c['video_count']}건 "
                  f"(마지막 성공 {c['last_ok_at'][:16]}) — {c['error']}")
            continue
        print(f"  {c['channel_name']} ({c['subscribers']}) · {c['video_count']}건"
              f"{' · ' + c['note'] if c['note'] else ''}")
    for v in top[:5]:
        print(f"    [{','.join(v['teams'])}] {v['title'][:52]} · {v['views']:,}회")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
