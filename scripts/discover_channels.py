#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""수집 가능한 새 채널을 찾아 실제로 시험한 뒤 제안한다.

왜 이렇게 만들었나
  "데이터는 많을수록 좋다"는 절반만 맞다. 2026-09-01 에 가짜 채널 6개를
  걷어냈다. 하드코딩 카탈로그와 폴백 샘플이 실측인 척 대시보드에 떠 있었다.
  그래서 이 스크립트는 후보를 자동으로 등록하지 않는다.
  robots.txt 를 확인하고 실제로 호출해 본 뒤,
  진짜 데이터가 나오는 것만 "제안" 한다. 연동은 사람이 승인한 뒤에 한다.

판정 기준 (하나라도 실패하면 제안하지 않는다)
  1. robots.txt 가 해당 경로를 막지 않는다
  2. 인증 없이 또는 이미 보유한 키로 200 응답이 온다
  3. 응답에서 구조화된 항목이 최소 3건 이상 파싱된다
  4. 항목에 실제 값이 있다 (전부 동일한 상수가 아니다)

출력 data/channel_candidates.json
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
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "channel_candidates.json"

UA = "JarvisLunaSourceProbe/1.0 (+https://github.com/coar0000-wq/jarvis-luna)"
TIMEOUT = 25
DELAY = 1.5
MIN_ITEMS = 3

# 후보 목록. 전부 공개 접근이거나 이미 키를 가진 것만 넣는다.
# 유료 API, 로그인 필요, robots.txt 금지 경로는 애초에 넣지 않는다.
CANDIDATES = [
    {
        "key": "openbeautyfacts_new",
        "label": "Open Beauty Facts 신규 등록순",
        "why": "오픈데이터. 미국 유통 신제품을 성분과 함께 얻는다.",
        "url": ("https://world.openbeautyfacts.org/api/v2/search"
                "?countries_tags_en=united-states&sort_by=created_t"
                "&fields=code,product_name,brands&page_size=20"),
        "kind": "json",
        "path": ["products"],
        "name_keys": ("product_name",),
    },
    {
        "key": "wikipedia_pageviews",
        "label": "Wikipedia 조회수 (브랜드 관심도)",
        "why": "무료 공식 API. K뷰티 브랜드 문서 조회수로 관심 추이를 본다.",
        "url": ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
                "/en.wikipedia/all-access/all-agents/K-beauty/daily"
                "/20260801/20260901"),
        "kind": "json",
        "path": ["items"],
        "name_keys": ("timestamp",),
    },
    {
        "key": "fda_cosmetic_enforcement",
        "label": "FDA 화장품 리콜·조치 이력",
        "why": "공식 오픈데이터. 취급하면 안 되는 성분·브랜드를 걸러낸다.",
        "url": ("https://api.fda.gov/food/enforcement.json"
                "?search=product_type:cosmetic&limit=20"),
        "kind": "json",
        "path": ["results"],
        "name_keys": ("product_description", "reason_for_recall"),
    },
    {
        "key": "allure_beauty_rss",
        "label": "Allure 뷰티 기사 RSS",
        "why": "미국 뷰티 매체. 어떤 제품이 기사화되는지로 트렌드를 본다.",
        "url": "https://www.allure.com/feed/rss",
        "kind": "rss",
    },
    {
        "key": "reddit_kbeauty_new",
        "label": "r/KoreanBeauty 신규글 RSS",
        "why": "기존 Reddit 수집의 서브레딧 확장. 실사용자 언급을 본다.",
        "url": "https://www.reddit.com/r/KoreanBeauty/top.rss?t=week",
        "kind": "rss",
    },
    {
        "key": "google_trends_daily_rss",
        "label": "Google Trends 미국 일간 급상승 RSS",
        "why": "공식 RSS. 승인제 alpha API 없이도 급상승 검색어를 얻는다.",
        "url": "https://trends.google.com/trending/rss?geo=US",
        "kind": "rss",
    },
    {
        "key": "openfda_drug_otc_sunscreen",
        "label": "openFDA 선케어 OTC 라벨",
        "why": "미국에서 선크림은 OTC 의약품이다. 라벨 요건 확인에 쓴다.",
        "url": ("https://api.fda.gov/drug/label.json"
                "?search=openfda.product_type:\"HUMAN+OTC+DRUG\"+AND+sunscreen&limit=10"),
        "kind": "json",
        "path": ["results"],
        "name_keys": ("id",),
    },
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

def get(url: str, headers: dict | None = None) -> tuple[bytes | None, str]:
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
         "Accept-Encoding": "identity"}
    if headers:
        h.update(headers)
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            if r.status != 200:
                return None, f"HTTP {r.status}"
            return r.read(), ""
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def robots_allows(url: str) -> tuple[bool, str]:
    """Unknown or unparseable robots policy is blocked, not assumed allowed."""
    u = urllib.parse.urlparse(url)
    robots_url = f"{u.scheme}://{u.netloc}/robots.txt"
    body, err = get(robots_url)
    if err or not body:
        return False, f"robots unknown: {err or 'empty response'}"
    txt = body.decode("utf-8", "replace")
    lines = txt.splitlines()
    if not any(re.match(r"^\s*user-agent\s*:", line, re.I) for line in lines):
        return False, "robots unknown: missing user-agent policy"
    parser = urllib.robotparser.RobotFileParser(robots_url)
    parser.parse(lines)
    if not parser.can_fetch(UA, url):
        return False, "robots denied"
    return True, "robots allowed"


# Fixed, reviewed documentation exceptions only. No generic robots bypass.
PUBLIC_API_DOCUMENTATION = {
    "wikipedia_pageviews": (
        "wikimedia.org",
        "/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/all-agents/K-beauty/daily/20260801/20260901",
        "https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/documentation/access-policy.html"),
    "fda_cosmetic_enforcement": (
        "api.fda.gov", "/food/enforcement.json",
        "https://open.fda.gov/apis/authentication"),
    "openfda_drug_otc_sunscreen": (
        "api.fda.gov", "/drug/label.json",
        "https://open.fda.gov/apis/authentication"),
}


def reviewed_public_api_documentation(candidate):
    """Only these three existing public GET routes may use the reviewed policy."""
    rule = PUBLIC_API_DOCUMENTATION.get(candidate.get("key"))
    if not rule or candidate.get("kind") != "json":
        return None
    url = urllib.parse.urlsplit(candidate.get("url", ""))
    host, endpoint, documentation = rule
    if (url.scheme != "https" or url.netloc != host or url.path != endpoint
            or url.fragment or url.username or url.password):
        return None
    query = urllib.parse.parse_qs(url.query, keep_blank_values=True)
    allowed_query = set() if host == "wikimedia.org" else {"search", "limit"}
    if set(query) - allowed_query:
        return None  # No keys, auth parameters, or unreviewed dispatch options.
    return documentation


def dig(d, path):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def probe(c: dict, previous=None) -> dict:
    res = {"key": c["key"], "label": c["label"], "why": c["why"],
           "url": c["url"], "kind": c["kind"]}

    res.update(evidence_scope="candidate_probe", connector_registered=False)

    def fail(reason, code, http_status=None, parse_status="not_attempted"):
        res.update(verdict="불가", reason=reason, probe_items=res.get("items", 0), items=0)
        if previous:
            for field in ("items", "samples", "provenance"):
                if field in previous:
                    res[field] = previous[field]
        attempt = source_attempt(c["url"], reason, code, http_status, parse_status)
        for field in ("access_basis", "public_api_documentation", "max_source_reads"):
            if field in res:
                attempt[field] = res[field]
        res.update(source_result(attempt, previous=previous))
        res["probe_status"] = "failed"
        return res

    ok, note = robots_allows(c["url"])
    res["robots"] = note
    documentation = None
    if not ok:
        # Explicit denial always wins. Auth/quota robots errors also stay blocked.
        unknown = note.startswith("robots unknown:")
        auth_or_quota = bool(re.search(r"HTTP (401|403|429)\b", note))
        documentation = reviewed_public_api_documentation(c) if unknown and not auth_or_quota else None
        if not documentation:
            return fail(note, "robots_unknown" if unknown else "robots_denied")
    res.update(access_basis="reviewed_public_api_read" if documentation else "robots_allowed",
               max_source_reads=1)
    if documentation:
        res["public_api_documentation"] = documentation

    # Exactly one sequential public source GET. No auth, quota, or rate retry.
    body, err = get(c["url"])
    if err or not body:
        return fail(err or "empty response", "http_error" if err.startswith("HTTP ") else "transport_error" if err else "empty_response")
    res["bytes"] = len(body)

    samples = []
    try:
        if c["kind"] == "rss":
            root = ET.fromstring(body)
            for t in root.iter():
                if t.tag.endswith("title") and (t.text or "").strip():
                    samples.append(t.text.strip())
            samples = samples[1:]           # 채널 제목 제외
        else:
            d = json.loads(body.decode("utf-8", "replace"))
            arr = dig(d, c["path"])
            if not isinstance(arr, list):
                raise ValueError("missing source array")
            for it in arr:
                if not isinstance(it, dict):
                    continue
                v = next((str(it[k]) for k in c["name_keys"]
                          if it.get(k) not in (None, "")), "")
                if v:
                    samples.append(v[:120])
    except Exception as e:
        return fail(f"parse failed: {type(e).__name__}", "parse_error", 200, "failed")

    res["items"] = len(samples)
    res["samples"] = samples[:3]

    if len(samples) < MIN_ITEMS:
        return fail(f"insufficient items: {len(samples)} (minimum {MIN_ITEMS})", "insufficient_items", 200, "ambiguous")
    elif len(set(samples)) == 1:
        return fail("all samples identical", "ambiguous_items", 200, "ambiguous")
    else:
        res.update(verdict="가능", reason=f"{len(samples)} items parsed with distinct values")
    captured = observation_time()
    res.update(source_result(source_attempt(c["url"], http_status=200, parse_status="ok"), captured))
    res.update(probe_status="ok", provenance={"source_key": c["key"], "source_url": c["url"], "http_status": 200, "parse_status": "ok",
                                             "access_basis": res["access_basis"], "max_source_reads": 1})
    if documentation:
        res["provenance"]["public_api_documentation"] = documentation
    for field in ("access_basis", "public_api_documentation", "max_source_reads"):
        if field in res:
            res["last_attempt"][field] = res[field]
    return res


def main() -> int:
    if '--cached-only' in sys.argv[1:]:
        # Offline publication validates existing observations; it never probes,
        # advances source clocks, releases stops or claims connector registration.
        if len(sys.argv) != 2:
            raise ValueError('cached channel validation accepts no other arguments')
        raw = OUT.read_bytes()
        if len(raw) > 8*1024*1024:
            raise ValueError('channel observation size bound')
        doc = json.loads(raw)
        rows = doc.get('candidates') if isinstance(doc,dict) else None
        keys = {c['key'] for c in CANDIDATES}
        if (not isinstance(rows,list) or not rows or len(rows) > len(keys)
                or any(not isinstance(r,dict) or r.get('key') not in keys for r in rows)
                or len({r['key'] for r in rows}) != len(rows)
                or type(doc.get('tested')) is not int or doc['tested'] != len(rows)):
            raise ValueError('cached channel observation scope invalid')
        print(f'CHANNELS_CACHED_ONLY {len(rows)} retained observations; no network/capture/registration')
        return 0
    only = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
    results = []
    previous = {r.get("key"): r for r in previous_payload(OUT).get("candidates", [])}
    for c in CANDIDATES:
        if only and c["key"] != only:
            continue
        r = probe(c, previous.get(c["key"]))
        mark = "가능" if r["verdict"] == "가능" else "불가"
        print(f"  [{mark}] {c['label'][:32]:34s} {r.get('items',0):3d}건  {r['reason'][:52]}")
        results.append(r)
        time.sleep(DELAY)

    # 이미 붙어 있는 소스도 매번 후보로 다시 올라온다. 그대로 두면
    # "미연동 4건" 처럼 보이는데 넷 다 이미 수집 중이었다.
    # dashboard_runtime.json 의 가동 채널과 대조해 표시한다.
    STOP = {"new", "daily", "rss", "us", "beauty", "drug", "otc", "api"}
    def words(k):
        return {w for w in str(k).lower().split("_") if w and w not in STOP}
    live = []
    try:
        rt = json.loads((ROOT / "data" / "dashboard_runtime.json")
                        .read_text(encoding="utf-8-sig"))
        live = [(k, words(k)) for k, v in (rt.get("global_channels_status") or {}).items()
                if (v or {}).get("status") == "ok"]
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    for r in results:
        hit = next((k for k, lw in live if words(r.get("key")) & lw), "")
        r["already_live"] = bool(hit)
        r["live_channel"] = hit

    usable = [r for r in results if r["verdict"] == "가능"]
    fresh = [r for r in usable if not r.get("already_live")]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/discover_channels.py",
        "정책": ("후보를 자동으로 등록하지 않는다. robots.txt 를 확인하고 실제로 "
               "호출해 본 뒤 진짜 데이터가 나오는 것만 제안한다. "
               "붙일지 말지는 대화로 지시하면 자비스가 수집기를 만들어 연동한다. "
               "이미 가동 중인 소스는 already_live 로 표시한다."),
        "판정기준": [
            "robots.txt 가 해당 경로를 막지 않을 것",
            "인증 없이 또는 보유한 키로 200 응답이 올 것",
            f"구조화된 항목이 최소 {MIN_ITEMS}건 파싱될 것",
            "항목 값이 전부 동일한 상수가 아닐 것",
        ],
        "tested": len(results),
        "usable": len(usable),
        "already_live": sum(1 for r in results if r.get("already_live")),
        "new_usable": len(fresh),
        "candidates": results,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n{len(results)}건 검사 · 사용 가능 {len(usable)} "
          f"(이미 가동 중 {len(usable) - len(fresh)}, 신규 {len(fresh)}) "
          f"-> {OUT.relative_to(ROOT)}")
    for r in fresh:
        print(f"  신규 후보: {r['label']}  {r['url'][:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
