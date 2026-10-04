#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""디자인팀 레퍼런스를 실제로 받아오는 곳에서만 모은다.

왜 이 목록인가
  사용자가 coolors.co, imweb.me, styles.refero.design 을 물었고 셋 다
  실제로 요청해본 뒤 제외했다.

    coolors.co        robots 허용. 그런데 팔레트 48개가 전부 브라우저에서
                      그려진다. 서버 HTML 559KB 에 palette-card 0개.
                      데이터는 /ajax/ 에서 오는데 그건 robots 가 막았다.
    imweb.me          robots 허용. HTML 183KB 에 '테마' 가 0번 나온다.
    refero.design     robots 가 ClaudeBot·Claude-Web·anthropic-ai 를
                      이름으로 지목해 Disallow: /.

  그래서 서버가 데이터를 그대로 주는 곳만 골랐다. 아래 넷은 2026-09-06 에
  직접 요청해 응답과 파싱을 확인했다.

    Google Fonts 메타   1,946개 폰트. 인기 순위·분류·웨이트·언어셋 포함
    Open Color          접근성 고려해 만든 오픈 팔레트. 13색 × 10단계
    Smashing Magazine   RSS. 실제 item 8건 확인
    A List Apart        RSS. 실제 entry 16건 확인

  전부 robots.txt 를 확인했고 와일드카드 그룹이 허용하는 경로만 쓴다.
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
OUT = ROOT / "data" / "design_sources.json"
UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"
TIMEOUT = 25
DELAY = 1.5

GOOGLE_FONTS = "https://fonts.google.com/metadata/fonts"
OPEN_COLOR = "https://raw.githubusercontent.com/yeun/open-color/master/open-color.json"
FEEDS = [
    ("Smashing Magazine", "https://www.smashingmagazine.com/feed/", "웹디자인·UX"),
    ("A List Apart", "https://alistapart.com/main/feed/", "웹표준·콘텐츠"),
]



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

def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        if res.status != 200:
            raise urllib.error.HTTPError(url, res.status, "unexpected HTTP status", res.headers, None)
        return res.read().decode("utf-8", "replace")


def collect_fonts() -> dict:
    """폰트 목록. 상점 글꼴을 고를 때 쓴다.

    한국어 지원 여부를 따로 표시한다. 브랜드명이 한글로 들어갈 수 있고,
    그때 fallback 이 깨지면 화면이 무너진다.
    """
    raw = fetch(GOOGLE_FONTS)
    doc = json.loads(raw[raw.index("{"):])
    fams = doc.get("familyMetadataList") or []
    if not isinstance(fams, list) or not fams or not all(isinstance(f, dict) and f.get("family") for f in fams):
        raise ValueError("no usable font metadata")

    def row(f: dict) -> dict:
        subs = f.get("subsets") or []
        return {
            "family": f.get("family"),
            "category": f.get("category"),
            "popularity": f.get("popularity"),
            "trending": f.get("trending"),
            "weights": sorted((f.get("fonts") or {}).keys()),
            "korean": "korean" in subs,
            "date_added": f.get("dateAdded"),
        }

    ranked = sorted((f for f in fams if f.get("popularity")),
                    key=lambda x: x["popularity"])
    trending = sorted((f for f in fams if f.get("trending")),
                      key=lambda x: x["trending"])
    korean = [f for f in fams if "korean" in (f.get("subsets") or [])]
    result = {
        "status": "ok",
        "source": "fonts.google.com/metadata/fonts (공개 메타데이터)",
        "robots": "허용 (2026-09-06 확인)",
        "total": len(fams),
        "korean_total": len(korean),
        "top_popular": [row(f) for f in ranked[:30]],
        "top_trending": [row(f) for f in trending[:20]],
        "korean_fonts": [row(f) for f in sorted(korean,
                                                key=lambda x: x.get("popularity") or 99999)],
    }

    rows = result["top_popular"] + result["top_trending"] + result["korean_fonts"]
    captured = captured_rows(rows, "fonts", GOOGLE_FONTS)
    result.update(source_result(source_attempt(GOOGLE_FONTS, http_status=200, parse_status="ok"), captured))
    return result


def collect_colors() -> dict:
    """팔레트. coolors 를 못 쓰는 대신 쓸 수 있는 오픈 팔레트다.

    Open Color 는 웹 UI 용으로 명도 단계를 맞춰 만든 색이라 그대로 써도
    대비가 크게 어긋나지 않는다. coolors 의 유행 팔레트와는 성격이 다르다.
    유행을 보려면 사람이 눈으로 보고 data/manual/ 에 넣는 편이 정직하다.
    """
    d = json.loads(fetch(OPEN_COLOR))
    scales = {k: v for k, v in d.items() if isinstance(v, list) and v}
    if not scales:
        raise ValueError("no usable color scales")
    result = {
        "status": "ok" if scales else "empty",
        "source": "github.com/yeun/open-color (MIT)",
        "note": ("웹 UI 용으로 명도 단계를 맞춘 오픈 팔레트. 유행 팔레트가 아니다. "
                 "유행은 coolors 가 브라우저에서만 그려서 자동 수집이 불가하다."),
        "hues": len(scales),
        "steps": len(next(iter(scales.values()))) if scales else 0,
        "palette": scales,
    }

    captured = observation_time()
    result.update(source_result(source_attempt(OPEN_COLOR, http_status=200, parse_status="ok"), captured))
    result["provenance"] = {"source_key": "colors", "source_url": OPEN_COLOR, "http_status": 200, "parse_status": "ok"}
    return result


def parse_feed(xml: str) -> list[dict]:
    root = ET.fromstring(xml)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in root.findall("./channel/item"):
        out.append({"title": (e.findtext("title") or "").strip(),
                    "url": (e.findtext("link") or "").strip(),
                    "published": (e.findtext("pubDate") or "").strip()})
    for e in root.findall("a:entry", ns):
        link = next((x.attrib.get("href") for x in e.findall("a:link", ns)), "")
        out.append({"title": (e.findtext("a:title", namespaces=ns) or "").strip(),
                    "url": link,
                    "published": (e.findtext("a:published", namespaces=ns) or "").strip()})
    return [x for x in out if x["title"]]


def collect_articles(previous=None) -> dict:
    previous = previous or {}
    items, failed, results = [], [], {}
    for name, url, topic in FEEDS:
        try:
            got = parse_feed(fetch(url))
            if not got:
                raise ValueError("no usable feed items")
            for x in got:
                x.update(feed=name, topic=topic)
            captured = captured_rows(got, name, url)
            results[name] = source_result(source_attempt(url, http_status=200, parse_status="ok"), captured)
        except Exception as exc:
            attempt = exception_attempt(url, exc)
            failed.append({"feed": name, "error": attempt["error"], "last_attempt": attempt})
            results[name] = source_result(attempt, previous=(previous.get("source_results") or {}).get(name))
            got = [dict(r) for r in previous.get("items", []) if r.get("feed") == name]
        items.extend(got)
        time.sleep(DELAY)
    result = pool_result(items, results, failed)
    result.update(feeds=len(FEEDS), failed=failed, count=len(result["items"]))
    return result


def exception_attempt(url, exc):
    is_parse = isinstance(exc, (ValueError, ET.ParseError, TypeError, AttributeError))
    code = "parse_error" if is_parse else "http_error" if isinstance(exc, urllib.error.HTTPError) else "transport_error"
    return source_attempt(url, f"{type(exc).__name__}: {exc}"[:160], code,
                          getattr(exc, "code", None) if not is_parse else 200,
                          "failed" if is_parse else "not_attempted")


# 실측해보고 뺀 곳. 왜 뺐는지 남긴다. 나중에 다시 묻지 않도록.
REJECTED = {
    "coolors.co /palettes/trending": (
        "robots 허용이나 팔레트가 브라우저에서만 그려진다. 서버 HTML 559KB 에 "
        "palette-card 0개·rgb() 0개. 데이터 출처로 보이는 /ajax/ 는 robots 가 막았다."),
    "imweb.me /theme": (
        "robots 는 Allow: / 지만 서버 HTML 183KB 에 '테마' 가 0번 나온다. "
        "목록이 전부 자바스크립트로 그려진다."),
    "styles.refero.design": (
        "robots 가 ClaudeBot·Claude-Web·anthropic-ai·GPTBot·CCBot 을 이름으로 "
        "지목해 Disallow: /. 와일드카드 그룹에도 Disallow: / 가 있다."),
    "themes.shopify.com/themes": (
        "robots 는 허용. HTTP 200 에 205KB 를 주지만 테마 목록이 JSON 으로 "
        "들어있지 않다. 추가 확인 전까지는 쓰지 않는다."),
    "YouTube /feeds/videos.xml": (
        "youtube.com/robots.txt 가 Disallow. Data API v3 로 가야 한다."),
}


def main() -> int:
    blocks, errors = {}, []
    previous = previous_payload(OUT)
    for key, fn in (("fonts", collect_fonts),
                    ("colors", collect_colors),
                    ("articles", collect_articles)):
        try:
            blocks[key] = fn(previous.get(key)) if key == "articles" else fn()
            if blocks[key]["status"] != "ok":
                errors.append(key)
        except Exception as e:                                   # noqa: BLE001
            attempt = exception_attempt({"fonts": GOOGLE_FONTS, "colors": OPEN_COLOR}.get(key, ""), e)
            blocks[key] = dict(previous.get(key) or {})
            blocks[key].update(source_result(attempt, previous=previous.get(key)))
            blocks[key]["reason"] = attempt["error"]
            errors.append(key)
        time.sleep(DELAY)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/collect_design_sources.py",
        "원칙": ("서버가 데이터를 그대로 주는 곳만 쓴다. 브라우저에서만 그려지는 "
               "사이트는 자동 수집 대상이 아니다. robots.txt 와일드카드 그룹이 "
               "허용하는 경로만 요청한다."),
        "robots_checked_at": "2026-09-06",
        "rejected": REJECTED,
        "failed_blocks": errors,
        **blocks,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for _ in range(4):
        OUT.write_text(body, encoding="utf-8")
        try:
            if json.loads(OUT.read_text(encoding="utf-8-sig"))["generated_at"]:
                break
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, KeyError):
            pass
        time.sleep(0.5)
    else:
        print("기록 검증 실패", file=sys.stderr)
        return 1

    f, c, a = blocks["fonts"], blocks["colors"], blocks["articles"]
    print(f"폰트 {f.get('total', 0)}개 (한국어 {f.get('korean_total', 0)}) · "
          f"팔레트 {c.get('hues', 0)}색조 × {c.get('steps', 0)}단계 · "
          f"기사 {a.get('count', 0)}건")
    if errors:
        print("실패한 블록:", ", ".join(errors))
    print(f"제외 {len(REJECTED)}곳 (사유 기록)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
