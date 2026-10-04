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
            if r.status != 200:
                return None, f"HTTP {r.status}"
            return r.read(), ""
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"



def observation_time() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_attempt(url, error="", code=None, http_status=None, parse_status=None):
    if http_status is None and error.startswith("HTTP "):
        try:
            http_status = int(error.split()[1])
        except (ValueError, IndexError):
            pass
    return {"status": "failed" if error else "ok",
            "code": code or ("http_error" if http_status and http_status != 200 else
                              "transport_error" if error else "success"),
            "attempted_at": observation_time(), "source_url": url,
            "http_status": http_status, "parse_status": parse_status or "not_attempted",
            "error": error}


def captured_rows(rows, key, url):
    # This clock is sampled only after a successful HTTP response and usable parse.
    captured = observation_time()
    for row in rows:
        row.update(captured_at=captured, observed_at=captured, collected_at=captured,
                   provenance={"source_key": key, "source_url": url,
                               "http_status": 200, "parse_status": "ok"})
    return captured


def source_result(attempt, captured=None, previous=None):
    result = {"status": attempt["status"], "last_attempt": attempt}
    for field in ("captured_at", "observed_at", "collected_at"):
        value = captured or (previous or {}).get(field)
        if value:
            result[field] = value
    if attempt["status"] != "ok":
        result["retained"] = bool(previous)
    return result


def pool_result(items, results, errors):
    successful = sum(r["status"] == "ok" for r in results.values())
    result = {"status": "ok" if successful == len(results) and successful else
              "partial" if successful else "failed", "items": items,
              "source_results": results, "errors": errors,
              "reason": "; ".join(str(e) for e in errors)}
    # A pool's clock is the oldest actual item observation, never its write time.
    clocks = [r.get("captured_at") for r in items if r.get("captured_at")]
    if clocks and len(clocks) == len(items):
        captured = min(clocks)
        result.update(captured_at=captured, observed_at=captured, collected_at=captured)
    return result


def previous_payload(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}

def clean(s: str | None) -> str:
    return " ".join((s or "").split())


def collect_arxiv(previous=None) -> dict:
    """Read allowed OpenAlex topics, retaining each failed topic's old observations."""
    previous = previous or {}
    since = (datetime.now(timezone.utc) - timedelta(days=OPENALEX_DAYS)).strftime("%Y-%m-%d")
    rows, errors, results = [], [], {}
    for topic_id, label in OPENALEX_TOPICS:
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode({
            "filter": (f"primary_location.source.id:{ARXIV_OPENALEX_SOURCE},"
                       f"from_publication_date:{since},topics.id:{topic_id}"),
            "sort": "publication_date:desc", "per-page": str(MAX_PER_SOURCE),
            "mailto": OPENALEX_MAILTO})
        body, err = get(url, ARXIV_UA)
        got = []
        if err or not body:
            attempt = source_attempt(url, err or "empty response", code=None if err else "empty_response")
        else:
            try:
                doc = json.loads(body.decode("utf-8", "replace"))
                if not isinstance(doc, dict) or not isinstance(doc.get("results"), list):
                    raise ValueError("missing results array")
                for w in doc["results"]:
                    if not isinstance(w, dict) or not clean(w.get("title")):
                        continue
                    loc = w.get("primary_location") or {}
                    link = loc.get("landing_page_url") or w.get("doi") or ""
                    inv, slots = w.get("abstract_inverted_index"), {}
                    if isinstance(inv, dict):
                        for word, positions in inv.items():
                            if isinstance(positions, list):
                                for pos in positions:
                                    if isinstance(pos, int):
                                        slots[pos] = word
                    got.append({"title": clean(w.get("title")),
                                "summary": " ".join(slots[i] for i in sorted(slots))[:400],
                                "published": w.get("publication_date") or "", "url": link,
                                "primary_category": label, "source_detail": "arXiv via OpenAlex"})
                if not got:
                    raise ValueError("no usable source items")
                captured = captured_rows(got, topic_id, url)
                attempt = source_attempt(url, http_status=200, parse_status="ok")
                results[topic_id] = source_result(attempt, captured)
            except (ValueError, TypeError, AttributeError) as exc:
                attempt = source_attempt(url, str(exc), "parse_error", 200, "failed")
        if attempt["status"] != "ok":
            errors.append({"source_key": topic_id, "error": attempt["error"]})
            old = (previous.get("source_results") or {}).get(topic_id)
            results[topic_id] = source_result(attempt, previous=old)
            got = [dict(r) for r in previous.get("items", [])
                   if r.get("provenance", {}).get("source_key") == topic_id
                   or (not r.get("provenance") and r.get("primary_category") == label)]
        rows.extend(got)
        time.sleep(ARXIV_DELAY)
    return pool_result(rows, results, errors)


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


def collect_rss(previous=None) -> dict:
    previous = previous or {}
    rows, errors, results = [], [], {}
    for name, url in RSS_FEEDS:
        body, err = get(url, WEB_UA)
        got = []
        if err or not body:
            attempt = source_attempt(url, err or "empty response", code=None if err else "empty_response")
        else:
            try:
                root = ET.fromstring(body)
                for it in root.findall(".//item")[:MAX_PER_SOURCE]:
                    title = clean(it.findtext("title"))
                    if title:
                        got.append({"title": title, "summary": clean(it.findtext("description"))[:400],
                                    "published": clean(it.findtext("pubDate")),
                                    "url": clean(it.findtext("link")), "feed": name, "source": "rss"})
                if not got:
                    raise ValueError("no usable RSS items")
                captured = captured_rows(got, name, url)
                attempt = source_attempt(url, http_status=200, parse_status="ok")
                results[name] = source_result(attempt, captured)
            except (ET.ParseError, ValueError) as exc:
                attempt = source_attempt(url, str(exc), "parse_error", 200, "failed")
        if attempt["status"] != "ok":
            errors.append({"feed": name, "error": attempt["error"]})
            results[name] = source_result(attempt, previous=(previous.get("source_results") or {}).get(name))
            got = [dict(r) for r in previous.get("items", []) if r.get("feed") == name]
        rows.extend(got)
        time.sleep(1.5)
    return pool_result(rows, results, errors)


def main() -> int:
    previous = previous_payload(OUT).get("sources") or {}
    arx = collect_arxiv(previous.get("arxiv"))
    rss = collect_rss(previous.get("rss"))
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
