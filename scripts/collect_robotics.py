#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""로보틱스 자료 수집기.

왜 만들었나
  2026-09-04 옵시디언 주제를 20개로 세분화했더니 "로보틱스" 가 3건뿐이었다.
  분류기는 정상이었고(테스트 통과), 수집원 자체에 로봇 자료가 없었다.
  기존 arXiv 수집기가 cat:cs.AI 하나만 조회하고 있었기 때문이다.

수집원 (전부 공개, 2026-09-04 실호출 검증)
  arXiv cs.RO     로보틱스 논문        export.arxiv.org
  arXiv eess.SY   시스템·제어 논문      export.arxiv.org
  IEEE Spectrum   로보틱스 기사 RSS     spectrum.ieee.org
  The Robot Report 산업 로봇 뉴스 RSS   therobotreport.com

접근 정책
  arXiv 은 robots.txt 가 / 를 막지만, 프로그램 접근용으로
  export.arxiv.org 를 따로 제공하며 이 주소를 쓰라고 안내한다.
  (info.arxiv.org/help/robots.html, /help/api/tou.html)
  우리는 그 전용 주소만 쓰고 요청 간 3초를 둔다.
  IEEE Spectrum 과 The Robot Report 는 robots.txt 허용 확인.

원칙 (CLAUDE.md: 거짓말 데이터 금지 / 가짜 데이터 금지)
  소스별 실패를 격리한다. 실패하면 빈 배열과 사유를 남기고 지어내지 않는다.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "robotics_sources.json"

ARXIV_UA = "JARVIS-LUNA/1.0 (https://github.com/coar0000-wq/jarvis-luna)"
WEB_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
TIMEOUT = 30
ARXIV_DELAY = 3.0        # arXiv 권장. 부하를 주지 않는다.
NS = {"a": "http://www.w3.org/2005/Atom",
      "ar": "http://arxiv.org/schemas/atom"}

ARXIV_CATS = [("cs.RO", "로보틱스"), ("eess.SY", "시스템·제어")]

# OpenAlex 로 받는다. 이유는 collect_arxiv() 주석에 적어 두었다.
ARXIV_OPENALEX_SOURCE = "S4306400194"          # arXiv (Cornell University)
OPENALEX_MAILTO = os.environ.get(
    "OPENALEX_MAILTO", "jarvis-luna@users.noreply.github.com")
OPENALEX_DAYS = 21
OPENALEX_TOPICS = [
    ("T10715", "로보틱스"),
    ("T11209", "제어·자율주행"),
]
RSS_FEEDS = [
    ("IEEE Spectrum Robotics", "https://spectrum.ieee.org/feeds/topic/robotics.rss"),
    ("The Robot Report", "https://www.therobotreport.com/feed/"),
]
MAX_PER_SOURCE = 25


def get(url: str, ua: str) -> tuple[bytes | None, str]:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": ua, "Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read(), ""
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def clean(s: str | None) -> str:
    return " ".join((s or "").split())


def collect_arxiv() -> dict:
    """2026-09-14 부터 받지 않는다.

    이 파일 18행에 "arXiv 은 프로그램 접근용 export.arxiv.org 를 제공하며
    이 주소를 쓰라고 안내한다" 고 적어 두고 받아 왔다. 안내는 사실이다.
    그런데 그 호스트의 robots.txt 는 User-agent: * 에 Disallow: / 다.
    안내 문서와 robots 가 어긋날 때 우리는 robots 를 따르기로 했다.

    RSS 쪽(IEEE Spectrum, Robot Report)은 그대로 받는다. 거기는 막지 않는다.
    로보틱스 수집이 통째로 죽는 것이 아니라 arXiv 몫만 빈다.
    2026-09-17 추가

    막힌 것은 한 호스트지 논문이 아니었다. 지식 수집팀에 같은 일을 하고
    여기만 비워두면 같은 자리를 다시 파게 된다. OpenAlex 로 받는다.

      export.arxiv.org   Disallow: /        안 된다
      api.openalex.org   Allow: /           이걸 쓴다

    real_knowledge_sync.py 와 같은 방식이고 주제만 로보틱스다.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=OPENALEX_DAYS)
             ).strftime("%Y-%m-%d")
    rows, errs = [], []
    seen = set()

    for topic_id, label in OPENALEX_TOPICS:
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode({
            "filter": (f"primary_location.source.id:{ARXIV_OPENALEX_SOURCE},"
                       f"from_publication_date:{since},"
                       f"topics.id:{topic_id}"),
            "sort": "publication_date:desc",
            "per-page": str(MAX_PER_SOURCE),
            "mailto": OPENALEX_MAILTO,
        })
        body, err = get(url, ARXIV_UA)
        if err or not body:
            errs.append(f"{label}: {err or 'empty'}")
            continue
        try:
            doc = json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError as e:
            errs.append(f"{label}: JSON {e}")
            continue

        for w in doc.get("results") or []:
            title = clean(w.get("title"))
            if not title:
                continue
            loc = w.get("primary_location") or {}
            link = loc.get("landing_page_url") or w.get("doi") or ""
            key = link or title.lower()
            if key in seen:
                continue
            seen.add(key)

            inv = w.get("abstract_inverted_index")
            summary = ""
            if isinstance(inv, dict) and inv:
                slots = {}
                for word, pos in inv.items():
                    if isinstance(pos, list):
                        for p in pos:
                            if isinstance(p, int):
                                slots[p] = word
                summary = " ".join(slots[i] for i in sorted(slots))

            rows.append({
                "title": title,
                "summary": summary[:400],
                "published": w.get("publication_date") or "",
                "url": link,
                "primary_category": label,
                "source_detail": "arXiv via OpenAlex",
            })
        time.sleep(ARXIV_DELAY)

    if not rows:
        return {
            "status": "failed",
            "reason": ("OpenAlex 에서 로보틱스 논문을 받지 못했다. "
                       + ("; ".join(errs) if errs else "결과 0건")),
            "items": [],
            "errors": errs,
        }

    return {
        "status": "ok",
        "reason": "; ".join(errs),
        "경로": ("api.openalex.org (robots Allow: /) · "
                "export.arxiv.org 에는 요청하지 않는다"),
        "items": rows,
        "errors": errs,
    }


def _collect_arxiv_disabled() -> dict:
    rows, errs = [], []
    for cat, label in ARXIV_CATS:
        url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode({
            "search_query": f"cat:{cat}", "max_results": MAX_PER_SOURCE,
            "sortBy": "submittedDate", "sortOrder": "descending"})
        body, err = get(url, ARXIV_UA)
        time.sleep(ARXIV_DELAY)
        if body is None:
            errs.append({"category": cat, "error": err})
            continue
        try:
            root = ET.fromstring(body)
        except ET.ParseError as e:
            errs.append({"category": cat, "error": f"XML 파싱 실패: {e}"})
            continue
        for e in root.findall("a:entry", NS):
            title = clean(e.findtext("a:title", namespaces=NS))
            if not title:
                continue
            pc = e.find("ar:primary_category", NS)
            rows.append({
                "title": title,
                "summary": clean(e.findtext("a:summary", namespaces=NS))[:400],
                "published": clean(e.findtext("a:published", namespaces=NS)),
                "primary_category": pc.get("term") if pc is not None else None,
                "query_category": cat,
                "category_label": label,
                "url": next((x.attrib["href"] for x in e.findall("a:link", NS)
                             if x.attrib.get("rel") == "alternate"), ""),
                "source": "arxiv",
            })
    # 같은 논문이 두 카테고리에 걸릴 수 있다
    seen, uniq = set(), []
    for r in rows:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        uniq.append(r)
    return {"status": "ok" if uniq else "failed",
            "reason": "" if uniq else "전 카테고리 수집 실패",
            "source": "export.arxiv.org (프로그램 접근 전용 주소)",
            "categories": [c for c, _ in ARXIV_CATS],
            "errors": errs, "items": uniq}


def collect_rss() -> dict:
    rows, errs = [], []
    for name, url in RSS_FEEDS:
        body, err = get(url, WEB_UA)
        time.sleep(1.5)
        if body is None:
            errs.append({"feed": name, "error": err})
            continue
        try:
            root = ET.fromstring(body)
        except ET.ParseError as e:
            errs.append({"feed": name, "error": f"XML 파싱 실패: {e}"})
            continue
        for it in root.findall(".//item")[:MAX_PER_SOURCE]:
            title = clean(it.findtext("title"))
            if not title:
                continue
            rows.append({
                "title": title,
                "summary": clean(it.findtext("description"))[:400],
                "published": clean(it.findtext("pubDate")),
                "url": clean(it.findtext("link")),
                "feed": name,
                "source": "rss",
            })
    return {"status": "ok" if rows else "failed",
            "reason": "" if rows else "전 피드 수집 실패",
            "source": ", ".join(n for n, _ in RSS_FEEDS),
            "errors": errs, "items": rows}


def main() -> int:
    arx = collect_arxiv()
    rss = collect_rss()
    total = len(arx["items"]) + len(rss["items"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/collect_robotics.py",
        "목적": ("옵시디언 주제 '로보틱스' 가 3건뿐이던 문제를 해결한다. "
               "분류기는 정상이었고 수집원에 로봇 자료가 없었던 것이 원인이다."),
        "접근_정책": ("arXiv 은 프로그램 접근용 export.arxiv.org 를 제공하며 "
                  "그 주소만 사용하고 요청 간 3초를 둔다. "
                  "RSS 두 곳은 robots.txt 허용을 확인했다."),
        "total": total,
        "sources": {"arxiv": arx, "rss": rss},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"  arXiv  {len(arx['items']):3d}건  {arx['reason'] or 'OK'}")
    print(f"  RSS    {len(rss['items']):3d}건  {rss['reason'] or 'OK'}")
    print(f"\n총 {total}건 -> {OUT.relative_to(ROOT)}")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
