#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""공개 소스 4종 수집기.

scripts/discover_channels.py 가 실제 호출로 검증해 "가능" 판정한 것만 구현했다.
   Google Trends 미국 급상승 RSS   승인제 alpha API 없이 실제 검색 급상승 확보
   Wikipedia 조회수 API            K뷰티 브랜드·주제 관심도 추이
   Allure 뷰티 RSS                 미국 뷰티 매체가 다루는 제품
   openFDA OTC 선케어 라벨          미국에서 선크림은 OTC 의약품. 라벨 요건 참조

원칙 (CLAUDE.md: 거짓말 데이터 금지 / 가짜 데이터 금지)
  - 소스별로 실패를 격리한다. 하나가 죽어도 나머지는 저장된다.
  - 실패하면 빈 배열과 사유를 남긴다. 이전 값으로 채우거나 지어내지 않는다.
  - 각 항목에 원본 링크를 남겨 검증 가능하게 한다.
  - 특히 google_trends_us 채널은 그동안 growth "+" momentum "High" 가
    모든 항목에 동일하게 박힌 가짜였다. 이 수집기가 그것을 대체한다.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "public_signals.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
TIMEOUT = 25
DELAY = 1.2

# Wikipedia 조회수를 볼 주제. S등급 상품의 성분·제형과 미국 시장 브랜드에서 골랐다.
WIKI_TOPICS = ["K-beauty", "Sunscreen", "Niacinamide", "Hyaluronic_acid",
               "Centella_asiatica", "Snail_slime", "Retinol", "Cosmetics"]


def get(url: str) -> tuple[bytes | None, str]:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read(), ""
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def txt(el, tag: str) -> str:
    for ch in el:
        if ch.tag.split("}")[-1] == tag:
            return (ch.text or "").strip()
    return ""


def collect_google_trends() -> dict:
    """미국 급상승 검색어. approx_traffic 은 구글이 준 실제 추정치다."""
    body, err = get("https://trends.google.com/trending/rss?geo=US")
    if body is None:
        return {"status": "failed", "reason": err, "items": []}
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        return {"status": "failed", "reason": f"XML 파싱 실패: {e}", "items": []}

    rows = []
    for it in root.findall(".//item"):
        kw = txt(it, "title")
        if not kw:
            continue
        traffic = txt(it, "approx_traffic")
        rows.append({
            "keyword": kw,
            "approx_traffic": traffic or None,
            "traffic_num": int(re.sub(r"[^\d]", "", traffic) or 0) if traffic else None,
            "published": txt(it, "pubDate"),
            "source_name": txt(it, "picture_source") or None,
            "url": f"https://trends.google.com/trending?geo=US&q={urllib.parse.quote(kw)}",
        })
    rows.sort(key=lambda x: -(x["traffic_num"] or 0))
    return {"status": "ok" if rows else "empty",
            "reason": "" if rows else "항목 없음",
            "source": "trends.google.com/trending/rss?geo=US (공식 RSS)",
            "note": "구글이 제공하는 실제 급상승 검색어와 추정 트래픽",
            "items": rows}


def collect_wikipedia() -> dict:
    """주제별 조회수 추이. 관심도의 대리지표."""
    end = datetime.now(timezone.utc).date() - timedelta(days=2)
    start = end - timedelta(days=29)
    rows, errs = [], []
    for topic in WIKI_TOPICS:
        u = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
             f"/en.wikipedia/all-access/all-agents/{urllib.parse.quote(topic)}"
             f"/daily/{start:%Y%m%d}/{end:%Y%m%d}")
        body, err = get(u)
        time.sleep(DELAY)
        if body is None:
            errs.append({"topic": topic, "error": err})
            continue
        try:
            items = json.loads(body.decode("utf-8")).get("items") or []
        except json.JSONDecodeError:
            errs.append({"topic": topic, "error": "JSON 파싱 실패"})
            continue
        if len(items) < 8:
            errs.append({"topic": topic, "error": f"데이터 {len(items)}일치뿐"})
            continue
        views = [int(x.get("views") or 0) for x in items]
        half = len(views) // 2
        prev = sum(views[:half]) / max(1, half)
        recent = sum(views[half:]) / max(1, len(views) - half)
        rows.append({
            "topic": topic.replace("_", " "),
            "days": len(views),
            "total_views": sum(views),
            "avg_daily": round(sum(views) / len(views)),
            "recent_avg": round(recent),
            "prev_avg": round(prev),
            # 추세는 실제 조회수 비교로만 계산한다. 임의 라벨을 붙이지 않는다.
            "change_pct": round((recent - prev) / prev * 100, 1) if prev else None,
            "url": f"https://en.wikipedia.org/wiki/{topic}",
        })
    rows.sort(key=lambda x: -(x["change_pct"] or -999))
    return {"status": "ok" if rows else "failed",
            "reason": "" if rows else "전 주제 수집 실패",
            "source": "wikimedia.org REST pageviews API (공식)",
            "note": f"{start} ~ {end} 일별 조회수. 후반 15일 대비 전반 15일 증감률",
            "errors": errs, "items": rows}


def collect_allure() -> dict:
    """미국 뷰티 매체가 지금 다루는 제품·주제."""
    body, err = get("https://www.allure.com/feed/rss")
    if body is None:
        return {"status": "failed", "reason": err, "items": []}
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        return {"status": "failed", "reason": f"XML 파싱 실패: {e}", "items": []}
    rows = []
    for it in root.findall(".//item"):
        t = txt(it, "title")
        if not t:
            continue
        rows.append({"title": t, "published": txt(it, "pubDate"),
                     "url": txt(it, "link")})
    return {"status": "ok" if rows else "empty",
            "reason": "" if rows else "항목 없음",
            "source": "allure.com/feed/rss",
            "note": "수요 신호가 아니라 매체 노출 신호. 참고용.",
            "items": rows[:30]}


def collect_openfda_sunscreen() -> dict:
    """미국에서 선크림은 OTC 의약품이다. 실제 라벨 문구를 참조한다."""
    u = ('https://api.fda.gov/drug/label.json?search=openfda.product_type:'
         '"HUMAN+OTC+DRUG"+AND+sunscreen&limit=20')
    body, err = get(u)
    if body is None:
        return {"status": "failed", "reason": err, "items": []}
    try:
        results = json.loads(body.decode("utf-8")).get("results") or []
    except json.JSONDecodeError as e:
        return {"status": "failed", "reason": f"JSON 파싱 실패: {e}", "items": []}
    rows = []
    for r in results:
        of = r.get("openfda") or {}
        first = lambda k: (of.get(k) or [None])[0]
        rows.append({
            "brand": first("brand_name"),
            "manufacturer": first("manufacturer_name"),
            "spl_id": r.get("id"),
            "active_ingredient": (r.get("active_ingredient") or [None])[0],
            "warnings_excerpt": ((r.get("warnings") or [""])[0] or "")[:220] or None,
            "url": f"https://api.fda.gov/drug/label.json?search=id:{r.get('id')}",
        })
    return {"status": "ok" if rows else "empty",
            "reason": "" if rows else "항목 없음",
            "source": "api.fda.gov/drug/label (openFDA 공식)",
            "note": ("미국 판매 선크림의 실제 라벨. 우리 선크림 3종의 "
                     "영문 라벨 작성 시 표현 참조용. 수요 신호가 아니다."),
            "items": rows}


SOURCES = {
    "google_trends_us": ("Google Trends 미국 급상승", collect_google_trends),
    "wikipedia_interest": ("Wikipedia 관심도", collect_wikipedia),
    "allure_media": ("Allure 뷰티 매체", collect_allure),
    "openfda_sunscreen": ("openFDA 선케어 라벨", collect_openfda_sunscreen),
}


def main() -> int:
    out, total = {}, 0
    for key, (label, fn) in SOURCES.items():
        try:
            r = fn()
        except Exception as e:
            r = {"status": "failed", "reason": f"{type(e).__name__}: {e}", "items": []}
        out[key] = r
        n = len(r.get("items") or [])
        total += n
        print(f"  [{r['status']:6s}] {label:22s} {n:3d}건  {r.get('reason','')[:44]}")
        time.sleep(DELAY)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/collect_public_signals.py",
        "선정_경위": ("scripts/discover_channels.py 가 robots.txt 확인과 실제 호출로 "
                  "'가능' 판정한 소스만 구현했다."),
        "total": total,
        "sources": out,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n총 {total}건 -> {OUT.relative_to(ROOT)}")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
