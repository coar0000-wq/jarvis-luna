#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""수집원이 지금 살아 있는지 실제로 찔러본다.

왜 만들었나
  실패 기록을 메모로 남겨왔다. "TSMC 뉴스룸 HTTP 403", "ASML IR 피드 없음"
  같은 것들이다. 그런데 그 메모를 언제 어디서 확인했는지가 남아 있지 않다.

  실제로 이런 일이 있었다. FDA 리콜 RSS 를 "HTTP 404, 주소 없음" 이라고
  적어뒀는데, 브라우저로 열어보니 19KB 짜리 정상 RSS 가 나왔다. 확인했던
  환경이 차단당하고 있었을 뿐이다. 그 메모 하나 때문에 멀쩡한 소스를
  죽은 것으로 취급하고 있었다.

  그래서 메모 대신 결과를 남긴다. GitHub Actions 러너에서 직접 찔러보고
  언제 무엇이 몇 건 나왔는지 적는다. 판단은 그 기록으로 한다.

무엇을 보나
  HTTP 상태, 응답 크기, 파싱된 항목 수, 확인 시각.
  항목이 0건이면 200 이라도 실패로 본다. 껍데기를 받는 건 성공이 아니다.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "source_health.json"
UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"
TIMEOUT = 20
DELAY = 1.0

# (팀, 이름, 종류, URL). 실제로 수집기가 쓰는 주소만 넣는다.
SOURCES = [
    ("법률·규제팀", "openFDA 화장품 이상사례", "json",
     "https://api.fda.gov/cosmetic/event.json?limit=5"),
    ("법률·규제팀", "openFDA 선케어 OTC 라벨", "json",
     "https://api.fda.gov/drug/label.json?search=openfda.product_type:%22HUMAN+OTC+DRUG%22"
     "+AND+sunscreen&limit=5"),
    ("법률·규제팀", "FDA 리콜 RSS", "rss",
     "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/recalls/rss.xml"),
    ("법률·규제팀", "FDA MedWatch 안전경보 RSS", "rss",
     "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/medwatch/rss.xml"),
    ("법률·규제팀", "FDA 건강사기 RSS", "rss",
     "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/health-fraud/rss.xml"),

    ("디자인팀", "Google Fonts 메타", "json",
     "https://fonts.google.com/metadata/fonts"),
    ("디자인팀", "Open Color 팔레트", "json",
     "https://raw.githubusercontent.com/yeun/open-color/master/open-color.json"),
    ("디자인팀", "Smashing Magazine", "rss", "https://www.smashingmagazine.com/feed/"),
    ("디자인팀", "A List Apart", "rss", "https://alistapart.com/main/feed/"),

    ("지식 수집팀", "arXiv cs.AI", "rss",
     "https://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=5"),
    ("지식 수집팀", "Google News K-beauty", "rss",
     "https://news.google.com/rss/search?q=%22K-beauty%22+skincare&hl=en-US&gl=US&ceid=US:en"),

    ("채널 운영팀", "Google Trends 미국 RSS", "rss",
     "https://trends.google.com/trending/rss?geo=US"),
    ("채널 운영팀", "Allure RSS", "rss", "https://www.allure.com/feed/rss"),
    ("채널 운영팀", "Wikipedia 조회수 API", "json",
     "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/"
     "all-access/all-agents/K-beauty/daily/20260801/20260901"),
    ("채널 운영팀", "Open Beauty Facts", "json",
     "https://world.openbeautyfacts.org/api/v2/search?countries_tags_en=united-states"
     "&fields=code,product_name&page_size=5"),

    ("법률·규제팀", "미국 HTS 검색", "json",
     "https://hts.usitc.gov/reststop/search?keyword=shampoo"),

    ("기관 수집팀", "TSMC 뉴스룸", "html", "https://pr.tsmc.com/english/latest-news"),
    ("기관 수집팀", "ASML 뉴스", "html", "https://www.asml.com/en/news"),
    # 2026-09-09: /news/ 는 404 다. 공식 안내가 /media/news 를 가리킨다.
    ("기관 수집팀", "Deutsche Bank 미디어", "html",
     "https://www.db.com/media/news?language_id=1"),
    ("기관 수집팀", "Marvell 뉴스", "html", "https://www.marvell.com/company/newsroom.html"),
]


# 이 스크립트를 만든 이유가 위 설명에 적혀 있다. "FDA 리콜 RSS 를 404 라고
# 적어뒀는데 브라우저로 열어보니 멀쩡했다" 는 것이다.
#
# 그런데 이 스크립트가 같은 실수를 다시 했다. 09-09 보고서에 여섯 곳이
# 실패로 적혔다. 하나씩 브라우저로 열어봤다.
#
#   FDA 리콜/MedWatch/건강사기 RSS  404 -> 살아 있음. 최신 항목 09-06.
#   TSMC 뉴스룸                    403 -> 살아 있음. 최신 09-08.
#   Deutsche Bank                  404 -> 주소가 정말 바뀜(/media/news)
#
# 앞의 넷은 소스가 죽은 게 아니라 우리 User-Agent 가 막힌 것이다.
# CDN(Akamai 등)이 봇 UA 에 404·403 을 준다. 주소가 없어진 것과
# 우리가 거절당한 것은 다른 일인데 같은 칸에 적히고 있었다.
#
# 그래서 두 가지를 한다.
#   1. 봇 UA 가 거절당하면 브라우저 UA 로 한 번 더 찔러본다.
#      막힌 것인지 없어진 것인지 갈라야 판단할 수 있다.
#   2. 결과를 LIVE / BLOCKED / GONE / EMPTY / DOWN 으로 나눠 적는다.
#      BLOCKED 는 고칠 것이 없다. 그쪽이 우리를 안 받는 것이다.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
BLOCKISH = (401, 403, 404, 406, 409, 429)


# 응답을 400,000 바이트만 읽고 있었다. Google Fonts 메타는 그보다 커서
# 딱 400,000 에서 잘렸고, 잘린 JSON 이라 파싱에 실패했다. 보고서에는
# "JSON 파싱 실패" 로만 적혀서 형식이 바뀐 줄 알았다. 형식은 멀쩡했다.
# 상한을 올리고, 상한에 닿으면 잘렸다고 적는다.
READ_CAP = 4_000_000


def _get(url: str, ua: str) -> tuple[int, bytes, str]:
    req = urllib.request.Request(url, headers={
        "User-Agent": ua, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read(READ_CAP), ""
    except urllib.error.HTTPError as e:
        return e.code, b"", f"HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        return 0, b"", type(e).__name__


def probe(url: str, kind: str) -> dict:
    t0 = time.monotonic()
    status, body, err = _get(url, UA)
    ua_used, blocked = "bot", False

    # 봇 UA 가 거절당했으면 브라우저 UA 로 한 번 더 본다. 사이트가 죽은
    # 것인지 우리를 안 받는 것인지 갈라야 한다.
    if status in BLOCKISH:
        time.sleep(1.0)
        s2, b2, e2 = _get(url, BROWSER_UA)
        if s2 == 200:
            status, body, err = s2, b2, ""
            ua_used, blocked = "browser", True
        else:
            return {"status": status, "items": 0, "bytes": 0, "ok": False,
                    "판정": "GONE" if status == 404 else "BLOCKED",
                    "ua": "both-failed", "blocked_for_bot": True,
                    "note": f"{err} (브라우저 UA 로도 {s2})",
                    "ms": int((time.monotonic() - t0) * 1000)}
    elif status != 200:
        return {"status": status, "items": 0, "bytes": 0, "ok": False,
                "판정": "DOWN", "ua": ua_used, "blocked_for_bot": False,
                "note": err or f"HTTP {status}",
                "ms": int((time.monotonic() - t0) * 1000)}

    text = body.decode("utf-8", "replace")
    items, note = 0, ""
    if kind == "rss":
        try:
            root = ET.fromstring(text)
            items = len(root.findall("./channel/item")) + len(
                root.findall("{http://www.w3.org/2005/Atom}entry"))
        except ET.ParseError:
            items = len(re.findall(r"<item[ >]|<entry[ >]", text))
            note = "XML 파싱 실패, 태그 수로 셈"
    elif kind == "json":
        try:
            # Google Fonts 는 )]}' 로 시작하는 XSSI 방어 접두사를 붙인다.
            # 앞에서 여는 괄호를 찾아 잘라야 한다. 리스트로 오는 곳도 있다.
            st_body = text.lstrip()
            if st_body[:1] == "[":
                cut = text
            else:
                i = text.find("{")
                cut = text[i:] if i >= 0 else text
            d = json.loads(cut)
            if isinstance(d, list):
                items = len(d)
            else:
                for k in ("results", "items", "familyMetadataList", "products"):
                    if isinstance(d.get(k), list):
                        items = len(d[k]); break
                else:
                    items = len(d)
        except (json.JSONDecodeError, ValueError):
            note = ("응답이 상한(%d바이트)에서 잘려 파싱 못 함" % READ_CAP
                    if len(body) >= READ_CAP else "JSON 파싱 실패")
    else:
        items = 1 if len(text) > 2000 else 0
        note = "HTML 은 크기로만 판단"

    # 200 이어도 항목이 0 이면 실패로 본다. 껍데기는 성공이 아니다.
    ok = status == 200 and items > 0
    if blocked and ok:
        note = (note + " · " if note else "") + "봇 UA 는 거절당했고 브라우저 UA 로 받았다"
    return {"status": status, "items": items, "bytes": len(body),
            "ok": ok,
            "판정": ("BLOCKED" if (ok and blocked) else "LIVE" if ok else "EMPTY"),
            "ua": ua_used, "blocked_for_bot": blocked, "note": note,
            "ms": int((time.monotonic() - t0) * 1000)}


def main() -> int:
    prev = {}
    try:
        old = json.loads(OUT.read_text(encoding="utf-8-sig"))
        prev = {r["name"]: r for r in (old.get("sources") or [])}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for team, name, kind, url in SOURCES:
        r = probe(url, kind)
        was = prev.get(name) or {}
        rows.append({
            "team": team, "name": name, "kind": kind, "url": url,
            **r,
            "checked_at": now,
            # 마지막으로 성공한 때. 이번에 실패해도 지운다.
            "last_ok_at": now if r["ok"] else was.get("last_ok_at"),
            "fail_streak": 0 if r["ok"] else int(was.get("fail_streak") or 0) + 1,
        })
        time.sleep(DELAY)

    dead = [r for r in rows if not r["ok"]]
    alive = [r for r in rows if r["ok"]]
    # 세 번 연속 실패한 것만 진짜 고장으로 본다. 일시적 장애와 구분한다.
    broken = [r for r in dead if r["fail_streak"] >= 3]

    payload = {
        "generated_at": now,
        "generator": "scripts/check_source_health.py",
        "왜": ("메모 대신 결과를 남긴다. 예전에 FDA 리콜 RSS 를 '404, 주소 없음' 이라고 "
              "적어뒀는데 실제로는 멀쩡했다. 확인한 환경이 차단당하고 있었을 뿐이다."),
        "판정": ("HTTP 200 이면서 항목이 1건 이상일 때만 정상. 껍데기를 받는 건 "
               "성공이 아니다. 3회 연속 실패해야 고장으로 본다."),
        "판정이란": {
            "LIVE": "우리 봇 UA 로 받았다",
            "BLOCKED": "봇 UA 는 거절당했지만 살아 있다. 고칠 것이 없다",
            "GONE": "브라우저 UA 로도 404 다. 주소를 다시 찾아야 한다",
            "EMPTY": "200 인데 항목이 0건이다",
            "DOWN": "연결 자체가 안 된다",
        },
        "판정별": {k: sum(1 for r in rows if r.get("판정") == k)
                for k in ("LIVE", "BLOCKED", "GONE", "EMPTY", "DOWN")},
        "total": len(rows),
        "alive": len(alive),
        "dead": len(dead),
        "broken": len(broken),
        "고장": [{"team": r["team"], "name": r["name"], "note": r["note"],
                "status": r["status"], "fail_streak": r["fail_streak"],
                "last_ok_at": r["last_ok_at"]} for r in broken],
        "이번에_실패": [{"team": r["team"], "name": r["name"],
                    "status": r["status"], "note": r["note"],
                    "fail_streak": r["fail_streak"]} for r in dead],
        "sources": rows,
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

    print(f"수집원 {len(rows)}개 · 정상 {len(alive)} · 이번 실패 {len(dead)} · "
          f"3회 연속 실패 {len(broken)}")
    for r in dead:
        print(f"  [실패 {r['fail_streak']}회] {r['team']} · {r['name']} "
              f"— HTTP {r['status']} {r['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
