#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""사람이 찾은 논문을 넣으면 받아서 팀에 나눈다.

왜 만들었나
  영상은 넣을 데가 있었는데(ingest_youtube_links.py) 논문은 없었다.
  arXiv 자동 수집은 로보틱스와 MoE 검색어로만 돌고 있어서, 그 밖의
  논문을 발견해도 넣을 자리가 없었다.

  실제로 쇼피파이 앱 생태계를 7년치로 분석한 논문을 받았는데
  기존 경로 어디에도 안 들어갔다.

robots.txt (2026-09-06 확인)
  arxiv.org 는 /abs, /pdf, /html, /list 를 허용하고 Crawl-delay 15 를 건다.
  그래서 /abs 를 15초 간격으로 하나씩 받는다.

  export.arxiv.org 는 쓰지 않는다. 그쪽 robots.txt 는
  'User-agent: *  Disallow: /' 로 전면 차단이다. 기존 수집기 두 개가
  거기를 쓰고 있어서 따로 손봐야 한다.

넣는 법
  data/manual/papers.txt 에 한 줄씩.
    https://arxiv.org/abs/2608.23771 | market,listing | 왜 넣었는지
  팀을 비우면 제목과 초록으로 자동 분류한다.
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from team_routing import KNOWN_TEAMS, route as route_teams  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LIST = ROOT / "data" / "manual" / "papers.txt"
OUT = ROOT / "data" / "papers_manual.json"
UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"
TIMEOUT = 30
CRAWL_DELAY = 15.0          # arxiv.org robots.txt 가 요구하는 값

ARXIV_ID = re.compile(r"arxiv\.org/(?:abs|pdf|html)/([0-9]{4}\.[0-9]{4,5})")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(900000).decode("utf-8", "replace")


def clean(t: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", t)).strip()


def parse_abs(page: str) -> dict:
    def meta(name: str) -> str:
        m = re.search(rf'<meta name="{name}" content="([^"]*)"', page)
        return clean(m.group(1)) if m else ""

    m = re.search(r'<blockquote class="abstract[^"]*">(.*?)</blockquote>',
                  page, re.S)
    abstract = clean(re.sub(r"<[^>]+>", " ", m.group(1))) if m else ""
    abstract = re.sub(r"^Abstract:\s*", "", abstract)
    subj = re.search(r'<td class="tablecell subjects">(.*?)</td>', page, re.S)
    return {
        "title": meta("citation_title"),
        "authors": re.findall(r'<meta name="citation_author" content="([^"]+)"', page),
        "date": meta("citation_date").replace("/", "-"),
        "pdf_url": meta("citation_pdf_url"),
        "subjects": clean(re.sub(r"<[^>]+>", " ", subj.group(1))) if subj else "",
        "abstract": abstract,
    }


def parse_line(line: str) -> dict | None:
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
    m = ARXIV_ID.search(url)
    if not m:
        return {"raw": line[:80], "arxiv_id": None,
                "error": "arXiv 번호를 못 찾았다"}
    return {"arxiv_id": m.group(1), "teams": teams, "note": note,
            "url": f"https://arxiv.org/abs/{m.group(1)}"}


def main() -> int:
    if not LIST.exists():
        LIST.parent.mkdir(parents=True, exist_ok=True)
        LIST.write_text(
            "# 읽을 만한 논문을 여기에 한 줄씩 붙여넣으세요.\n"
            "# '#' 으로 시작하면 주석입니다.\n"
            "#\n"
            "# 형식 1  URL | 메모\n"
            "# 형식 2  URL | 팀 | 메모\n"
            "#\n"
            "# 팀 이름: market listing design pricing legal sourcing knowledge\n"
            "# 팀을 안 적으면 제목과 초록을 보고 자동으로 나눕니다.\n"
            "#\n"
            "# https://arxiv.org/abs/0000.00000 | market | 왜 넣었는지\n",
            encoding="utf-8")
        print(f"{LIST.relative_to(ROOT)} 를 만들었다. 논문을 넣으면 다음 실행에 받는다.")
        return 0

    lines = [parse_line(x.strip()) for x in
             LIST.read_text(encoding="utf-8-sig").splitlines()
             if x.strip() and not x.strip().startswith("#")]
    todo = [x for x in lines if x and x.get("arxiv_id")]
    bad = [x for x in lines if x and not x.get("arxiv_id")]

    prev = {}
    try:
        old = json.loads(OUT.read_text(encoding="utf-8-sig"))
        prev = {p["arxiv_id"]: p for p in (old.get("papers") or [])}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass

    papers, fetched = [], 0
    for x in todo:
        aid = x["arxiv_id"]
        was = prev.get(aid)
        # 이미 받은 것은 다시 받지 않는다. 15초씩 기다려야 해서 더 그렇다.
        if was and was.get("title") and not was.get("error"):
            was["note"] = x.get("note") or was.get("note", "")
            was["teams"] = route_teams(
                f'{was.get("title","")} {was.get("abstract","")}', x.get("teams"))
            was["team_source"] = "사람 지정" if x.get("teams") else "자동 분류"
            papers.append(was)
            continue
        if fetched:
            time.sleep(CRAWL_DELAY)
        try:
            got = parse_abs(fetch(x["url"]))
            err = "" if got.get("title") else "제목을 못 읽었다"
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
            got, err = {}, f"{type(e).__name__}"
        fetched += 1
        papers.append({
            "arxiv_id": aid, "url": x["url"], "note": x.get("note", ""),
            **got, "error": err,
            "teams": route_teams(f'{got.get("title","")} {got.get("abstract","")}',
                                 x.get("teams")),
            "team_source": "사람 지정" if x.get("teams") else "자동 분류",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "source": "사람이 직접 지정 (data/manual/papers.txt)",
        })

    ok = [p for p in papers if p.get("title") and not p.get("error")]
    by_team: dict = {}
    for p in ok:
        for t in p.get("teams") or []:
            by_team[t] = by_team.get(t, 0) + 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/ingest_papers.py",
        "입력": str(LIST.relative_to(ROOT)),
        "robots": ("arxiv.org 는 /abs 를 허용하고 Crawl-delay 15 를 요구한다. "
                   "15초 간격으로 하나씩 받는다. export.arxiv.org 는 "
                   "robots.txt 가 전면 차단이라 쓰지 않는다. 2026-09-06 확인."),
        "total": len(papers),
        "ok": len(ok),
        "failed": len(papers) - len(ok),
        "fetched_this_run": fetched,
        "bad_lines": bad,
        "by_team": by_team,
        "papers": papers,
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

    print(f"논문 {len(papers)}건 · 성공 {len(ok)} · 이번에 새로 받은 것 {fetched}")
    for p in ok[-5:]:
        print(f"  [{','.join(p.get('teams') or [])}] {str(p.get('title'))[:58]}")
        print(f"      {p.get('date','')} · {p.get('subjects','')[:40]}")
    for p in papers:
        if p.get("error"):
            print(f"  실패 {p.get('arxiv_id')} — {p['error']}")
    for b in bad:
        print(f"  못 읽은 줄: {b.get('raw')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
