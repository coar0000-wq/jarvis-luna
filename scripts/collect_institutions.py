#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""주요 금융·반도체·AI·데이터 기관의 공개 발표물과 학술 논문을 수집한다.

수집 경로는 세 가지이고, 모두 2026-09-04 에 실제 호출로 응답을 확인한 것만 등록했다.
응답이 없거나 robots.txt 가 전면 차단인 곳은 등록하지 않고 NOT_COLLECTED 에 사유를 남긴다.

  1) rss       공식 RSS/Atom 피드
  2) sitemap   robots.txt 가 허용하고 sitemap.xml 에 lastmod 가 있는 사이트
  3) openalex  OpenAlex API. 기관 ID 가 확인된 곳만 사용한다.

주의: 'Anthropic' 과 'xAI' 는 OpenAlex 소속 문자열 검색에서 일반 단어 및
'Anthropic (AI model)' 표기(= Claude 를 도구로 쓴 논문)와 섞인다. 기관 논문이
아니므로 두 곳은 OpenAlex 경로에서 제외하고 자사 사이트맵만 사용한다.
"""
from __future__ import annotations
import gzip, html, json, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "institution_sources.json"
MAILTO = "coar0000@naver.com"
UA = ("Mozilla/5.0 (compatible; JARVIS-LUNA/1.0; +https://github.com/coar0000-wq/jarvis-luna)")
TIMEOUT = 25
PER_RSS = 25
PER_SITEMAP = 20
PER_OPENALEX = 25
PAGE_META_LIMIT = 10      # 사이트맵 항목 중 본문 메타데이터를 실제로 받아올 상한
DELAY = 0.4

# ── 카테고리 ────────────────────────────────────────────────────────────────
IB, SEMI, AI, DATA = "투자은행", "반도체", "AI연구소", "데이터분석"

# ── 1) RSS: 실제 호출로 항목 수를 확인한 것만 ───────────────────────────────
RSS = [
    ("OpenAI",            AI,   "https://openai.com/news/rss.xml"),
    ("Google DeepMind",   AI,   "https://deepmind.google/blog/rss.xml"),
    ("Mistral AI",        AI,   "https://mistral.ai/rss.xml"),
    ("Microsoft Research", AI,  "https://www.microsoft.com/en-us/research/feed/"),
    ("AMD",               SEMI, "https://ir.amd.com/rss/news-releases.xml"),
    ("Broadcom",          SEMI, "https://investors.broadcom.com/rss/news-releases.xml"),
    ("Samsung Electronics", SEMI, "https://news.samsung.com/global/feed"),
    ("SK hynix",          SEMI, "https://news.skhynix.com/feed/"),
    ("Palantir",          DATA, "https://blog.palantir.com/feed"),
    ("C3 AI",             DATA, "https://ir.c3.ai/rss/news-releases.xml"),
    ("Snowflake",         DATA, "https://investors.snowflake.com/rss/pressrelease.aspx"),
    ("Databricks",        DATA, "https://www.databricks.com/feed"),
    ("Leidos",            DATA, "https://investors.leidos.com/rss/news-releases.xml"),
    ("Booz Allen Hamilton", DATA, "https://investors.boozallen.com/rss/news-releases.xml"),
    ("DataWalk",          DATA, "https://datawalk.com/feed/"),
]

# ── 2) 사이트맵: (기관, 분류, 사이트맵, URL 패턴, 본문 메타 수집 가능 여부) ──
SITEMAP = [
    ("Anthropic",      AI,  "https://www.anthropic.com/sitemap.xml",
     r"/(research|news|engineering)/", True),
    ("xAI",            AI,  "https://x.ai/sitemap.xml", r"/(news|blog)/", True),
    ("ASML",           SEMI, "https://www.asml.com/sitemap.xml", r"/news/", True),
    ("Barclays",       IB,  "https://home.barclays/sitemap.xml", r"/news/", True),
    ("Goldman Sachs",  IB,  "https://www.goldmansachs.com/sitemap.xml", r"/insights/", False),
    ("JPMorgan Chase", IB,  "https://www.jpmorgan.com/sitemap.xml", r"/insights/", False),
    ("Morgan Stanley", IB,  "https://www.morganstanley.com/sitemapindex.xml", r"ideas|insights", False),
]

# ── 3) OpenAlex 기관 ID (2026-09-04 조회로 works_count > 0 확인) ────────────
OPENALEX = [
    ("Goldman Sachs",   IB,   "I40713646"),
    ("JPMorgan Chase",  IB,   "I1305429384"),
    ("Morgan Stanley",  IB,   "I2802755631"),
    ("Bank of America", IB,   "I100621029"),
    ("Citigroup",       IB,   "I135458274"),
    ("UBS",             IB,   "I131328143"),
    ("Barclays",        IB,   "I4210104812"),
    ("Deutsche Bank",   IB,   "I158193983"),
    ("AMD",             SEMI, "I4210137977"),
    ("Intel",           SEMI, "I1343180700"),
    ("Qualcomm",        SEMI, "I4210087596"),
    ("Arm Holdings",    SEMI, "I2801109035"),
    ("Broadcom",        SEMI, "I4210127325"),
    ("Marvell Technology", SEMI, "I4210154351"),
    ("TSMC",            SEMI, "I4210120917"),
    ("Samsung Electronics", SEMI, "I2250650973"),
    ("ASML",            SEMI, "I927257375"),
    ("OpenAI",          AI,   "I4210161460"),
    ("Google DeepMind", AI,   "I4210090411"),
    ("Mistral AI",      AI,   "I4390039361"),
    ("Microsoft",       DATA, "I1290206253"),
    ("Booz Allen Hamilton", DATA, "I1322124587"),
    ("Leidos",          DATA, "I114662689"),
    ("CACI International", DATA, "I207766952"),
    ("Splunk",          DATA, "I4210160892"),
    ("Databricks",      DATA, "I4401726825"),
    ("Snowflake",       DATA, "I4400600931"),
]

# OpenAlex 에 기관 엔티티가 없어 소속 문자열로 찾는 곳.
# 토큰이 일반 단어와 겹치지 않는 경우에만 허용하고, 받은 뒤 다시 걸러낸다.
OPENALEX_AFFIL = [
    ("SK hynix",  SEMI, "SK Hynix", "hynix"),
    ("Palantir",  DATA, "Palantir Technologies", "palantir"),
    ("Dataiku",   DATA, "Dataiku", "dataiku"),
]

# 수집 경로를 찾지 못한 곳. 사유를 명시해 두고 데이터를 지어내지 않는다.
NOT_COLLECTED = {
    "Qualcomm 뉴스룸": "robots.txt 가 Disallow: / 로 전면 차단",
    "Palantir IR": "robots.txt 가 Disallow: / 로 전면 차단",
    "Intel 뉴스룸": "RSS 없음, 사이트맵 없음 (OpenAlex 논문만 수집)",
    "Citigroup 사이트": "robots.txt 응답 실패 (OpenAlex 논문만 수집)",
    "Bank of America 뉴스룸": "사이트맵에 lastmod 없어 최신순 판별 불가",
    "UBS 사이트": "사이트맵에 lastmod 없어 최신순 판별 불가",
    "Deutsche Bank 사이트": "사이트맵 하위 파일에 URL 0건",
    "Anthropic·xAI OpenAlex": "소속 문자열이 일반 단어 및 'Anthropic (AI model)' 표기와 혼재",
    "Dataiku 블로그 RSS": "피드 URL 없음 (OpenAlex 논문만 수집)",
    "TSMC 뉴스룸": "HTTP 403",
    "Marvell·Intel·Qualcomm·ASML IR RSS": "IR 피드 URL 없음",
    "SEC EDGAR 공시": "샌드박스에서 검증 불가하여 미등록",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch(url: str, limit: int = 3_000_000) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    raw = urllib.request.urlopen(req, timeout=TIMEOUT).read(limit)
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def clean(text: str) -> str:
    # CDATA 를 먼저 벗겨야 한다. <![CDATA[제목]]> 을 그대로 두면 태그 제거 정규식에
    # 통째로 걸려 제목이 빈 문자열이 된다. AMD·OpenAI·Samsung·Palantir 피드가 해당.
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text or "", flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def iso_date(raw: str) -> str:
    """RSS(RFC822) · 사이트맵(ISO) · OpenAlex(YYYY-MM-DD) 형식을 YYYY-MM-DD 로 맞춘다.

    형식이 섞이면 최신순 정렬과 날짜 비교가 조용히 어긋난다. 해석에 실패하면
    빈 문자열을 돌려주고 지어내지 않는다.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return m.group(0)
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(raw).date().isoformat()
    except Exception:
        return ""


def tag(block: str, name: str) -> str:
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", block, re.S | re.I)
    return clean(m.group(1)) if m else ""


# ── RSS ─────────────────────────────────────────────────────────────────────
def parse_rss(text: str, limit: int):
    blocks = re.findall(r"<item[\s>].*?</item>", text, re.S | re.I) or \
             re.findall(r"<entry[\s>].*?</entry>", text, re.S | re.I)
    rows = []
    for b in blocks[:limit]:
        title = tag(b, "title")
        link = tag(b, "link")
        if not link:
            m = re.search(r'<link[^>]+href=["\']([^"\']+)', b, re.I)
            link = m.group(1) if m else ""
        date = (tag(b, "pubDate") or tag(b, "published") or
                tag(b, "updated") or tag(b, "dc:date"))
        summary = tag(b, "description") or tag(b, "summary")
        if title and link:
            rows.append({"title": title[:300], "url": link,
                         "date": iso_date(date), "date_raw": date[:40],
                         "summary": summary[:400]})
    return rows


def collect_rss():
    items, fails = [], []
    for org, cat, url in RSS:
        try:
            rows = parse_rss(fetch(url), PER_RSS)
            if not rows:
                fails.append({"org": org, "url": url, "reason": "항목 0건"})
                continue
            for r in rows:
                r.update({"org": org, "category": cat, "kind": "발표물",
                          "source": "rss", "feed": url, "title_source": "feed"})
            items += rows
            print(f"  RSS      {org:22s} {len(rows):3d}건")
        except Exception as exc:
            fails.append({"org": org, "url": url, "reason": f"{type(exc).__name__}: {exc}"[:120]})
            print(f"  RSS      {org:22s} 실패 {type(exc).__name__}")
        time.sleep(DELAY)
    return items, fails


# ── 사이트맵 ────────────────────────────────────────────────────────────────
def slug_title(url: str) -> str:
    seg = [s for s in urllib.parse.urlparse(url).path.split("/") if s]
    if not seg:
        return ""
    last = re.sub(r"\.(html?|aspx|pdf)$", "", seg[-1])
    # transcript.pdf 처럼 파일명이 내용을 못 담는 경우 상위 경로를 제목으로 쓴다
    if len(last) <= 12 and len(seg) >= 2:
        last = f"{re.sub(r'[-_]+', ' ', seg[-2])} - {last}"
    return re.sub(r"[-_]+", " ", last).strip().title()[:300]


def page_meta(url: str):
    try:
        text = fetch(url, 250_000)
    except Exception:
        return "", ""

    def grab(key):
        pat = (rf'<meta[^>]+(?:property|name)=["\']{key}["\'][^>]*content=["\']([^"\']{{3,400}})',
               rf'<meta[^>]+content=["\']([^"\']{{3,400}})["\'][^>]*(?:property|name)=["\']{key}["\']')
        for p in pat:
            m = re.search(p, text, re.I)
            if m:
                return html.unescape(m.group(1)).strip()
        return ""

    title = grab("og:title")
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
        title = clean(m.group(1)) if m else ""
    return title[:300], (grab("og:description") or grab("description"))[:400]


def collect_sitemap():
    items, fails = [], []
    for org, cat, sm_url, pattern, want_meta in SITEMAP:
        try:
            text = fetch(sm_url)
            if "<sitemapindex" in text:
                kids = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", text)
                pick = [k for k in kids if re.search(pattern, k, re.I)] or kids
                text = fetch(pick[0])
            rows = []
            for blk in re.findall(r"<url>(.*?)</url>", text, re.S):
                loc = re.search(r"<loc>\s*([^<]+?)\s*</loc>", blk)
                lm = re.search(r"<lastmod>\s*([^<]+?)\s*</lastmod>", blk)
                if loc and lm and re.search(pattern, loc.group(1), re.I):
                    rows.append({"url": loc.group(1).strip(),
                                 "date": iso_date(lm.group(1).strip()),
                                 "date_raw": lm.group(1).strip()})
            rows.sort(key=lambda r: r["date"], reverse=True)
            rows = rows[:PER_SITEMAP]
            if not rows:
                fails.append({"org": org, "url": sm_url, "reason": "lastmod 있는 매칭 URL 0건"})
                continue
            got = 0
            for i, r in enumerate(rows):
                title, summary = ("", "")
                if want_meta and i < PAGE_META_LIMIT:
                    title, summary = page_meta(r["url"])
                    time.sleep(DELAY)
                r["title_source"] = "page" if title else "url-slug"
                r["title"] = title or slug_title(r["url"])
                r["summary"] = summary
                r.update({"org": org, "category": cat, "kind": "발표물",
                          "source": "sitemap", "feed": sm_url})
                got += 1
            items += rows
            print(f"  사이트맵  {org:22s} {got:3d}건")
        except Exception as exc:
            fails.append({"org": org, "url": sm_url, "reason": f"{type(exc).__name__}: {exc}"[:120]})
            print(f"  사이트맵  {org:22s} 실패 {type(exc).__name__}")
        time.sleep(DELAY)
    return items, fails


# ── OpenAlex ────────────────────────────────────────────────────────────────
def openalex(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": f"JARVIS-LUNA/1.0 (mailto:{MAILTO})"})
    return json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8"))


def work_rows(results, org, cat, token=None):
    rows = []
    for w in results:
        raws = [s for a in w.get("authorships", [])
                for s in a.get("raw_affiliation_strings", [])]
        if token and not any(token in s.lower() for s in raws):
            continue          # 소속 문자열 재확인에 실패하면 버린다
        title = (w.get("title") or "").strip()
        if not title:
            continue
        rows.append({
            "title": title[:300],
            "url": w.get("doi") or w.get("id", ""),
            "date": iso_date(w.get("publication_date", "")),
            "summary": "",
            "org": org, "category": cat, "kind": "논문",
            "source": "openalex", "title_source": "openalex",
            "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name", "") or "",
            "work_type": w.get("type", ""),
            "cited_by": w.get("cited_by_count", 0),
        })
    return rows


def collect_openalex():
    items, fails = [], []
    sel = "title,doi,id,publication_date,cited_by_count,primary_location,authorships,type"
    # 유형을 논문류로 좁힌다. 이 필터가 없으면 기여자가 소속을 적어 둔 Zenodo
    # 소프트웨어 릴리스(예: "EleutherAI/lm-evaluation-harness: v0.4.13")가 대량 섞인다.
    kind = "type:article|preprint|review"
    for org, cat, iid in OPENALEX:
        url = (f"https://api.openalex.org/works?per-page={PER_OPENALEX}&mailto={MAILTO}"
               f"&sort=publication_date:desc&select={sel}&filter=institutions.id:{iid},{kind}")
        try:
            rows = work_rows(openalex(url)["results"], org, cat)
            if not rows:
                fails.append({"org": org, "url": url, "reason": "논문 0건"})
                continue
            items += rows
            print(f"  OpenAlex {org:22s} {len(rows):3d}건")
        except Exception as exc:
            fails.append({"org": org, "url": url, "reason": f"{type(exc).__name__}: {exc}"[:120]})
            print(f"  OpenAlex {org:22s} 실패 {type(exc).__name__}")
        time.sleep(DELAY)

    for org, cat, query, token in OPENALEX_AFFIL:
        q = urllib.parse.quote(f'"{query}"')
        url = (f"https://api.openalex.org/works?per-page={PER_OPENALEX}&mailto={MAILTO}"
               f"&sort=publication_date:desc&select={sel}"
               f"&filter=raw_affiliation_strings.search:{q},{kind}")
        try:
            res = openalex(url)["results"]
            rows = work_rows(res, org, cat, token=token)
            if not rows:
                fails.append({"org": org, "url": url, "reason": "소속 재확인 통과 0건"})
                continue
            items += rows
            print(f"  OpenAlex {org:22s} {len(rows):3d}건 (소속검색 {len(res)}건 중)")
        except Exception as exc:
            fails.append({"org": org, "url": url, "reason": f"{type(exc).__name__}: {exc}"[:120]})
            print(f"  OpenAlex {org:22s} 실패 {type(exc).__name__}")
        time.sleep(DELAY)
    return items, fails


def main() -> int:
    only = None
    for a in sys.argv[1:]:
        if a.startswith("--only="):
            only = a.split("=", 1)[1]
    sources, items, fails = {}, [], []
    plan = [("rss", collect_rss), ("sitemap", collect_sitemap), ("openalex", collect_openalex)]
    for key, fn in plan:
        if only and only != key:
            continue
        got, bad = fn()
        items += got
        fails += bad
        sources[key] = {"status": "ok" if got else "empty", "count": len(got),
                        "failures": bad, "collected_at": now()}

    seen, uniq = set(), []
    for it in items:
        k = (it["org"], it["url"] or "", it["title"].lower())
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)

    final = uniq
    if only and OUT.exists():
        prev = json.loads(OUT.read_text(encoding="utf-8"))
        keep = [i for i in prev.get("items", []) if i.get("source") != only]
        final = keep + uniq
        for key, meta in prev.get("sources", {}).items():
            sources.setdefault(key, meta)

    # 집계는 반드시 병합이 끝난 뒤 계산한다. 부분 실행일 때 이번 회차 항목만으로
    # 계산하면 기관 수와 분류가 실제 파일 내용과 어긋난다.
    by_org, by_cat, by_kind = {}, {}, {}
    for it in final:
        by_org[it["org"]] = by_org.get(it["org"], 0) + 1
        by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
        by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1

    payload = {
        "collected_at": now(),
        "total": len(final),
        "organizations": len(by_org),
        "by_org": dict(sorted(by_org.items(), key=lambda x: -x[1])),
        "by_category": by_cat,
        "by_kind": by_kind,
        "sources": sources,
        "not_collected": NOT_COLLECTED,
        "items": final,
    }
    if only:
        payload["partial_run"] = only

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n총 {payload['total']}건 / 기관 {len(by_org)}곳 -> {OUT}")
    print(f"실패 {len(fails)}건")
    return 0 if uniq else 1


if __name__ == "__main__":
    raise SystemExit(main())
