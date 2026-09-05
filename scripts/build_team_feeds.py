#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""팀별로 볼 자료를 갈라 담는다.

지금까지 수집은 팀에 묶여 있지 않았다. 유튜브 180건이 '지식 수집'에
뭉뚱그려 들어가는데 그 안에 마케팅팀이 볼 K뷰티 리뷰와 디자인팀이 볼
Shopify 테마 영상이 섞여 있었다. 팀마다 자기 자료만 보게 나눈다.

두 가지를 한다.
  1) 이미 모은 자료를 키워드로 팀에 배정한다. 다시 수집하지 않는다.
  2) 법률팀은 볼 자료가 아예 없었다. FDA 소스를 새로 붙인다.

FDA 소스는 2026-09-05 실제 호출로 응답을 확인한 것만 넣었다.
  openFDA 화장품 이상사례      api.fda.gov/cosmetic/event.json
  openFDA 선케어 OTC 라벨      api.fda.gov/drug/label.json
  FDA 리콜 RSS                fda.gov .../recalls/rss.xml
응답이 없던 openFDA cosmetic/enforcement 와 FDA 화장품 전용 RSS 는
404 라서 넣지 않았다. 사유는 not_collected 에 남긴다.
"""
from __future__ import annotations
import json, re, time, urllib.request, html as H
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "team_feeds.json"
UA = "Mozilla/5.0 (compatible; JARVIS-LUNA/1.0; +https://github.com/coar0000-wq/jarvis-luna)"
TIMEOUT, RECENT_DAYS = 25, 14

# 팀별 배정 키워드. 제목과 본문에서 찾는다.
ROUTE = {
    "sourcing": ("다이소", "daiso", "소싱", "sourcing", "도매", "wholesale"),
    "market": ("k-beauty", "kbeauty", "korean skincare", "korean beauty", "뷰티", "화장품",
               "skincare", "serum", "sunscreen", "toner", "ampoule", "리뷰", "review",
               "trend", "트렌드"),
    "listing": ("listing", "product page", "copywriting", "카피", "상세페이지", "seo",
                "description"),
    "pricing": ("pricing", "price", "tariff", "duty", "shipping cost", "관세", "배송비",
                "가격", "환율"),
    "legal": ("fda", "mocra", "regulation", "compliance", "recall", "warning letter",
              "label", "규제", "리콜", "라벨", "성분 규제"),
    "design": ("shopify", "theme", "ui", "ux", "design system", "landing page", "테마",
               "디자인"),
    "robotics": ("robot", "로봇", "manipulation", "autonomous"),
}

FDA = [
    ("openFDA 화장품 이상사례", "json",
     "https://api.fda.gov/cosmetic/event.json?limit=40"),
    ("openFDA 선케어 OTC 라벨", "json",
     "https://api.fda.gov/drug/label.json?search=openfda.product_type:%22HUMAN+OTC+DRUG%22"
     "+AND+sunscreen&limit=20"),
    ("FDA 리콜 RSS", "rss",
     "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/recalls/rss.xml"),
]

NOT_COLLECTED = {
    "openFDA cosmetic/enforcement": "HTTP 404 - 해당 엔드포인트 없음",
    "FDA 화장품 전용 RSS": "HTTP 404 - 주소 없음. 리콜 RSS 로 대체",
    "FDA 수입경보 66-41 페이지": "HTTP 404",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(p: Path):
    for _ in range(3):
        try:
            return json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            time.sleep(0.4)
    return None


def get(url: str) -> str | None:
    try:
        return urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": UA}),
            timeout=TIMEOUT).read(2_000_000).decode("utf-8", "replace")
    except Exception:
        return None


def clean(t: str) -> str:
    t = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", t or "", flags=re.S)
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", t))).strip()


def collect_fda() -> tuple[list, list]:
    items, fails = [], []
    for name, kind, url in FDA:
        body = get(url)
        if not body:
            fails.append({"source": name, "reason": "응답 없음"})
            continue
        rows = []
        if kind == "json":
            try:
                for r in (json.loads(body).get("results") or []):
                    title = (r.get("products", [{}])[0].get("name_brand")
                             or (r.get("openfda") or {}).get("brand_name", [""])[0]
                             or r.get("report_number") or "")
                    date = (r.get("date_received") or r.get("effective_time") or "")
                    if isinstance(title, list):
                        title = title[0] if title else ""
                    if title:
                        rows.append({"title": str(title)[:200],
                                     "date": f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(str(date)) == 8 else "",
                                     "url": url.split("?")[0], "feed": name})
            except Exception:
                fails.append({"source": name, "reason": "JSON 파싱 실패"})
                continue
        else:
            for b in re.findall(r"<item[\s>].*?</item>", body, re.S | re.I)[:40]:
                t = clean(re.search(r"<title[^>]*>(.*?)</title>", b, re.S).group(1)) if re.search(r"<title", b) else ""
                l = clean(re.search(r"<link[^>]*>(.*?)</link>", b, re.S).group(1)) if re.search(r"<link", b) else ""
                d = clean(re.search(r"<pubDate[^>]*>(.*?)</pubDate>", b, re.S).group(1)) if re.search(r"<pubDate", b) else ""
                if t:
                    rows.append({"title": t[:200], "url": l, "date": d[:25], "feed": name})
        if not rows:
            fails.append({"source": name, "reason": "항목 0건"})
            continue
        items += rows
        print(f"  FDA {name:26s} {len(rows):3d}건")
        time.sleep(1.0)
    return items, fails


def route(text: str) -> list[str]:
    low = (text or "").lower()
    return [team for team, kws in ROUTE.items() if any(k in low for k in kws)]


def main() -> int:
    pools = []
    rs = load(DATA / "knowledge" / "real_sources.json")
    for key, blk in ((rs or {}).get("sources") or {}).items():
        for it in (blk.get("items") or []):
            pools.append({"title": it.get("title") or "", "url": it.get("url") or "",
                          "date": it.get("published") or it.get("date") or "",
                          "pool": key, "text": it.get("summary") or it.get("text") or ""})
    dt = load(DATA / "design_team.json")
    for it in ((dt or {}).get("references") or {}).get("items", []):
        pools.append({"title": it.get("title") or "", "url": it.get("url") or "",
                      "date": it.get("date") or "", "pool": "design_refs",
                      "text": it.get("summary") or ""})
    ps = load(DATA / "public_signals.json")
    for key, blk in ((ps or {}).get("sources") or {}).items():
        for it in (blk.get("items") or []):
            pools.append({"title": it.get("title") or it.get("term") or "", "url": it.get("url") or "",
                          "date": it.get("date") or "", "pool": f"signal:{key}", "text": ""})

    fda_items, fda_fails = collect_fda()
    for it in fda_items:
        pools.append({**it, "pool": "fda", "text": "fda regulation recall"})

    teams = {t: [] for t in ROUTE}
    unrouted = 0
    for it in pools:
        hits = route(f'{it.get("title","")} {it.get("text","")} {it.get("pool","")}')
        if it.get("pool") == "fda":
            hits = list(set(hits + ["legal"]))
        if not hits:
            unrouted += 1
            continue
        for t in hits:
            teams[t].append({k: it[k] for k in ("title", "url", "date", "pool") if k in it})

    cutoff = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    summary = {}
    for t, rows in teams.items():
        seen, uniq = set(), []
        for r in rows:
            k = (r.get("title"), r.get("url"))
            if k in seen:
                continue
            seen.add(k)
            uniq.append(r)
        uniq.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
        recent = [r for r in uniq if str(r.get("date") or "")[:10] >= cutoff]
        teams[t] = uniq[:60]
        summary[t] = {"total": len(uniq), "recent": len(recent)}

    payload = {
        "generated_at": now(),
        "generator": "scripts/build_team_feeds.py",
        "규칙": ("이미 모은 자료를 키워드로 팀에 배정한다. 다시 수집하지 않는다. "
               "법률팀만 FDA 소스를 새로 받는다."),
        "recent_days": RECENT_DAYS,
        "pool_size": len(pools),
        "unrouted": unrouted,
        "summary": summary,
        "fda_failures": fda_fails,
        "not_collected": NOT_COLLECTED,
        "teams": teams,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n전체 풀 {len(pools)}건 · 미배정 {unrouted}건")
    for t, s in summary.items():
        print(f"  {t:10s} 총 {s['total']:4d}  최근 {RECENT_DAYS}일 {s['recent']:3d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
