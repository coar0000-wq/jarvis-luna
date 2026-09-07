#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SerpApi 로 YouTube 검색 결과를 받는다.

왜 SerpApi 인가
  youtube.com/robots.txt 가 /feeds/videos.xml 을 Disallow 해서 RSS 수집을
  2026-09-06 에 멈췄다. SerpApi 는 우리가 아니라 그쪽이 가져온 결과를
  API 로 파는 서비스다. 우리는 그들의 문서화된 엔드포인트만 호출한다.

예산
  무료 250회/월. collect_serpapi_market.py 와 같은 원장을 쓴다.
  한 원장을 두 스크립트가 나눠 쓰므로 용도별 상한을 따로 둔다.
    market  : 상한 200 (실제 사용은 회당 22 회 안팎, 주 1회)
    youtube : 상한  30
  합쳐도 250 을 넘지 않고 20 회는 사람이 수동 확인할 몫으로 남긴다.
  상한을 넘으면 호출하지 않고 사유만 남긴다. 실패한 호출은 차감하지 않는다.

무엇을 찾나
  다이소 소싱과 붙는 질의만 쓴다. 조회수가 실제 관심의 크기를 보여준다.
  기사(collect_kbeauty_news.py)는 매체가 무엇을 다루는지 보여주고,
  이건 사람들이 무엇을 찾아보는지 보여준다. 둘은 다른 신호다.
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
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "youtube_serpapi.json"
LEDGER = DATA / "serpapi_usage.json"          # market 수집기와 공유
ENDPOINT = "https://serpapi.com/search.json"

# 월 상한. market 200 과 합쳐 245 로 무료 250 안쪽이다.
#
# 30 에서 45 로 올렸다. 스케줄을 주 1회에서 주 2회로 바꿨는데 회당 5회를
# 쓰므로 한 달 45회가 된다. 30 이면 달 중반에 막혀 나머지 회차는 헛돈다.
#
# 실측으로 계산했다. S등급이 5개인 지금 market 은 회당 13회(S 5 + 키워드 8),
# 주 2회면 117회다. 여기에 youtube 45 를 더해 162회. S가 14개로 늘어도
# market 198 + youtube 45 = 243 으로 250 안쪽이다.
# 주 3회는 youtube 65회가 되어 초과한다. 그래서 주 2회로 정했다.
YOUTUBE_CAP = 45
TIMEOUT = 30
DELAY = 2.0

QUERIES = [
    "korean skincare routine 2026",
    "k-beauty essence serum review",
    "daiso korea skincare haul",
    "PDRN skincare before after",
    "korean toner pad review",
]

# 기사 수집기와 같은 낱말을 쓴다. 두 신호를 나란히 볼 수 있어야 한다.
BUCKET_TERMS = {
    "스킨케어": ["essence", "serum", "ampoule", "toner", "moisturizer", "cream",
              "lotion", "mist", "skincare", "skin care", "glass skin"],
    "마스크팩": ["sheet mask", "mask", "pad", "patch"],
    "클렌징": ["cleanser", "cleansing", "double cleanse", "makeup remover"],
    "메이크업": ["cushion", "foundation", "tint", "lip", "concealer", "makeup"],
    "헤어케어": ["shampoo", "hair", "scalp", "treatment"],
}
INGREDIENTS = ["snail mucin", "pdrn", "centella", "cica", "heartleaf",
               "niacinamide", "hyaluronic", "ceramide", "peptide", "retinol",
               "vitamin c", "collagen", "rice", "propolis", "mugwort", "exosome"]


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def read_ledger() -> dict:
    d = load(LEDGER, None) or {}
    if d.get("month") != month_key():
        d = {"month": month_key(), "used": 0, "cap": 200, "runs": []}
    d.setdefault("runs", [])
    # 용도별 사용량. 없으면 0 부터.
    d.setdefault("by_purpose", {})
    d["by_purpose"].setdefault("youtube", 0)
    # setdefault 가 아니라 대입이다. 원장 파일에 이미 30 이 적혀 있으면
    # setdefault 는 코드에서 45 로 올려도 30 을 그대로 쓴다. 상한을 바꾼
    # 이유가 코드에 적혀 있으니 코드가 기준이다.
    d["youtube_cap"] = YOUTUBE_CAP
    return d


def call(params: dict, ledger: dict) -> tuple[dict | None, str]:
    """1회 호출. 용도별 상한과 전체 상한을 모두 본다."""
    used_yt = ledger["by_purpose"]["youtube"]
    if used_yt >= ledger["youtube_cap"]:
        return None, f"youtube 월 상한 {ledger['youtube_cap']}회 도달"
    if ledger["used"] >= 250:
        return None, "SerpApi 무료 250회 전체 소진"
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    try:
        raw = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "JARVIS-LUNA/1.0"}),
            timeout=TIMEOUT).read()
        d = json.loads(raw.decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}"[:120]   # 실패는 차감하지 않는다
    if d.get("error"):
        return None, str(d["error"])[:120]
    cached = str((d.get("search_metadata") or {}).get("status", "")).lower() == "cached"
    if not cached:
        ledger["used"] += 1
        ledger["by_purpose"]["youtube"] += 1
    return d, "cached" if cached else "ok"


VIEW_RE = re.compile(r"([\d,.]+)\s*([KMB])?", re.I)


def to_int(v) -> int | None:
    """views 가 숫자로 올 때도 있고 '1.2M' 로 올 때도 있다."""
    if isinstance(v, int):
        return v
    if not isinstance(v, str):
        return None
    m = VIEW_RE.match(v.strip())
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return int(n * {"k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower(), 1))


def main() -> int:
    key = (os.environ.get("SERPAPI_KEY") or "").strip()
    ledger = read_ledger()
    if not key:
        payload = {"generated_at": datetime.now(timezone.utc).isoformat(),
                   "status": "no_key",
                   "reason": "SERPAPI_KEY 가 없다. GitHub Secrets 에 넣어야 한다.",
                   "videos": []}
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print("SERPAPI_KEY 없음 - 건너뜀")
        return 0

    videos, notes = [], []
    seen = set()
    for q in QUERIES:
        d, note = call({"engine": "youtube", "search_query": q,
                        "gl": "us", "hl": "en", "api_key": key}, ledger)
        notes.append({"query": q, "note": note})
        if d is None:
            continue
        for v in (d.get("video_results") or []):
            vid = v.get("video_id")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            ch = v.get("channel") or {}
            videos.append({
                "video_id": vid,
                "title": (v.get("title") or "").strip(),
                "url": v.get("link"),
                "channel": ch.get("name"),
                "channel_url": ch.get("link"),
                "views": to_int(v.get("views")),
                "published": v.get("published_date"),
                "length": v.get("length"),
                "description": (v.get("description") or "")[:280],
                "query": q,
            })
        time.sleep(DELAY)

    buckets, ings = Counter(), Counter()
    view_by_bucket = Counter()
    for v in videos:
        blob = f"{v['title']} {v['description']}".lower()
        for b, terms in BUCKET_TERMS.items():
            if any(t in blob for t in terms):
                buckets[b] += 1
                view_by_bucket[b] += v.get("views") or 0
        for ing in INGREDIENTS:
            if ing in blob:
                ings[ing] += 1

    top = sorted((v for v in videos if v.get("views")),
                 key=lambda x: -x["views"])[:20]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/collect_serpapi_youtube.py",
        "출처": "SerpApi youtube 엔진 (그들이 가져온 결과를 API 로 받는다)",
        "왜_serpapi": ("youtube.com/robots.txt 가 /feeds/videos.xml 을 Disallow 해서 "
                      "직접 수집을 중단했다. SerpApi 는 문서화된 API 를 부르는 것이라 "
                      "우리가 막힌 경로를 치지 않는다."),
        "예산": {"youtube_cap": ledger["youtube_cap"],
               "youtube_used": ledger["by_purpose"]["youtube"],
               "전체_used": ledger["used"],
               "메모": "market 수집기와 같은 원장을 쓴다. 합쳐 250 을 넘지 않는다."},
        "queries": QUERIES,
        "calls": notes,
        "video_count": len(videos),
        "bucket_mentions": dict(buckets),
        "bucket_total_views": dict(view_by_bucket),
        "ingredient_mentions": dict(sorted(ings.items(), key=lambda x: -x[1])),
        "top_by_views": top,
        "videos": videos[:80],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for _ in range(4):
        OUT.write_text(body, encoding="utf-8")
        try:
            if json.loads(OUT.read_text(encoding="utf-8-sig"))["video_count"] == len(videos):
                break
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, KeyError):
            pass
        time.sleep(0.5)
    else:
        print("기록 검증 실패", file=sys.stderr)
        return 1

    ledger["runs"].append({"at": datetime.now(timezone.utc).isoformat(),
                           "purpose": "youtube",
                           "spent": len([n for n in notes if n["note"] == "ok"])})
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")

    print(f"영상 {len(videos)}건 · 질의 {len(QUERIES)}개")
    print(f"예산 youtube {ledger['by_purpose']['youtube']}/{ledger['youtube_cap']} · "
          f"전체 {ledger['used']}/250")
    if buckets:
        print("상품군:", ", ".join(f"{k} {v}건" for k, v in buckets.most_common(5)))
    if ings:
        print("성분:", ", ".join(f"{k} {v}" for k, v in list(ings.items())[:8]))
    bad = [n for n in notes if n["note"] not in ("ok", "cached")]
    if bad:
        print("호출 실패:", json.dumps(bad, ensure_ascii=False)[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
