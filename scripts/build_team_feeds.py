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
    # 영문 기사 제목이 'Korean Skin-Care', 'Korean Makeup', 'K-Craze' 처럼
    # 조금씩 달라서 'korean skincare' 하나로는 절반이 빠졌다.
    # 국문 영상도 '선크림'·'피부'·'성분' 으로 말하지 '뷰티' 라고 안 한다.
    "market": ("k-beauty", "kbeauty", "k-craze", "korean skincare", "korean skin-care",
               "korean beauty", "korean makeup", "korean-beauty", "k-pop",
               "뷰티", "화장품", "skincare", "skin care", "serum", "sunscreen",
               "toner", "ampoule", "cosmetic", "makeup", "리뷰", "review",
               "trend", "트렌드", "선크림", "선스틱", "스킨케어", "피부",
               "클렌저", "앰플", "세럼", "토너", "크림", "올리브영", "성분",
               # 'k-beauty' 만 넣고 'beauty' 를 빼두었더니 TikTok 뷰티 기사
               # 30여 건이 미배정으로 남았다. 우리 사업 자체가 뷰티라
               # 넓게 잡아도 엉뚱한 것이 들어오지 않는다.
               "beauty", "tiktok", "ecommerce", "e-commerce", "이커머스"),
    "listing": ("listing", "product page", "copywriting", "카피", "상세페이지", "seo",
                "description"),
    "pricing": ("pricing", "price", "tariff", "duty", "shipping cost", "관세", "배송비",
                "가격", "환율"),
    # spf 를 넣었다. 미국에서 자외선차단제는 화장품이 아니라 OTC 의약품이라
    # Drug Facts 라벨이 필요하다. SPF 시험을 다루는 자료는 법률팀도 봐야 한다.
    "legal": ("fda", "mocra", "regulation", "compliance", "recall", "warning letter",
              "label", "spf", "규제", "리콜", "라벨", "성분 규제"),
    "design": ("shopify", "theme", "ui", "ux", "design system", "landing page", "테마",
               "디자인"),
    "robotics": ("robot", "로봇", "manipulation", "autonomous"),
    # 지식·기관 팀이 아예 빠져 있었다. 그래서 arxiv 논문과 기관 소식이
    # 갈 곳이 없어 미배정으로 쌓였다. 1,838건 중 1,107건이 그랬다.
    "knowledge": ("llm", "language model", "transformer", "diffusion", "agent",
                  "reinforcement", "benchmark", "fine-tun", "inference",
                  "논문", "모델", "학습"),
    "institutions": ("openai", "anthropic", "google deepmind", "nvidia", "meta ai",
                     "microsoft", "tsmc", "asml", "samsung", "sk hynix",
                     "실적", "발표", "출시"),
}

# 출처만 봐도 팀이 정해지는 것들. 제목에 낱말이 없어도 여기서 걸린다.
#
# 미배정 1,107건을 열어보니 대부분이 이런 것이었다.
#   us_beauty  'COSRX Advanced Snail 96 Mucin Essence' — 제품명뿐이라
#              '뷰티' 도 'skincare' 도 안 들어 있다.
#   institutions 'GPT-6 Astra: A new generation of intelligence'
#   design_refs 'Checkout now defaults to last used payment method'
# 제목은 낱말이 없지만 어디서 왔는지는 안다. 그걸 쓴다.
POOL_TEAMS = {
    "arxiv": ("knowledge",),
    "institutions": ("institutions",),
    "robotics": ("robotics",),
    "design_refs": ("design",),
    "us_beauty": ("market",),
    # 유튜브 풀 119건이 통째로 미배정이었다. 열어보니 선크림 정량,
    # 피부 장벽, 올리브영 특가 같은 것이라 전부 시장 자료다.
    "youtube": ("market",),
    # 논문은 사람이 팀을 지정해 넣는다. 지정한 팀은 ingest_papers.py 가
    # 들고 있으므로 여기서는 지식팀에만 기본으로 걸어둔다.
    # papers·youtube_manual·youtube_channel 은 항목마다 teams 를 들고 오므로
    # 출처 기본값을 두지 않는다. 사람이 정한 것을 덮어쓰면 안 된다.
    "daiso": ("sourcing",),
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


# 유니코드 붙임표. K‑Beauty 의 가운뎃줄이 보통 하이픈이 아니라서
# 'k-beauty' 키워드에 안 걸렸다. WWD·Allure 기사가 그렇게 빠졌다.
DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"


def norm(text: str) -> str:
    low = (text or "").lower()
    for d in DASHES:
        low = low.replace(d, "-")
    return low


MONTHS = {m: f"{i:02d}" for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), 1)}

# 사람이 골라 넣은 자료의 출처. 목록에서 위에 둔다.
BY_HAND = ("papers", "youtube_manual", "youtube_channel", "daiso")


def iso_date(raw: str) -> str:
    """날짜를 YYYY-MM-DD 로 맞춘다.

    풀마다 형식이 달랐다. 구글 뉴스 RSS 는 'Wed, 31 Dec 2025 08:00 GMT',
    다이소는 '2026-09-06', 논문은 '2026-08-24' 다. 이걸 문자열로 정렬하니
    'Wed' 가 '2026' 보다 커서 RSS 기사만 위로 올라왔다. 사람이 직접 넣은
    영상과 논문이 상위 60건 밖으로 밀려 팀 화면에서 아예 안 보였다.
    """
    t = (raw or "").strip()
    if not t:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return "-".join(m.groups())
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})", t)
    if m:
        day, mon, year = m.groups()
        mm = MONTHS.get(mon.lower())
        if mm:
            return f"{year}-{mm}-{int(day):02d}"
    return ""


def route(text: str) -> list[str]:
    low = norm(text)
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

    # 다이소 174건이 풀에 아예 없었다. 그래서 소싱팀이 0건이었다.
    # 우리가 실제로 팔 물건인데 팀 화면에서 안 보였다.
    dz = load(DATA / "daiso_real" / "products.json")
    for it in ((dz or {}).get("products") or []):
        pools.append({"title": it.get("name") or it.get("title") or "",
                      "url": it.get("url") or "",
                      "date": (dz or {}).get("updated_at", "")[:10],
                      "pool": "daiso",
                      # 우리가 파는 물건이다. 소싱팀 것으로 고정한다.
                      # 낱말로 돌리면 앰플·크림·마스크가 마케팅에도 걸려서
                      # 상품명 174개가 마케팅팀 상단을 덮어버린다.
                      "teams": ["sourcing"],
                      "text": " ".join(str(it.get(k) or "") for k in
                                       ("category", "bucket", "brand"))})

    # 사람이 넣은 논문과 영상.
    #
    # 이 셋이 풀에 없었다. 세션 내내 영상을 팀에 배정해 왔는데 그 결과가
    # 팀 피드에는 하나도 안 들어가고 있었다. 배정한 곳과 보는 곳이
    # 달랐던 것이다.
    #
    # teams 를 그대로 들고 온다. 사람이 정한 팀을 낱말로 다시 뒤집으면
    # 안 된다. 실제로 논문 하나가 초록의 'listing histories' 때문에
    # 마케팅이 아니라 리스팅팀으로 갔다.
    pm = load(DATA / "papers_manual.json")
    for it in ((pm or {}).get("papers") or []):
        if not it.get("title"):
            continue
        pools.append({"title": it["title"], "url": it.get("url") or "",
                      "date": it.get("date") or "", "pool": "papers",
                      "teams": it.get("teams") or [],
                      "text": (it.get("abstract") or "")[:600]})

    ym = load(DATA / "youtube_manual.json")
    for it in ((ym or {}).get("videos") or []):
        if not it.get("title") or it.get("error"):
            continue
        pools.append({"title": it["title"], "url": it.get("url") or "",
                      "date": (it.get("published") or it.get("collected_at") or "")[:10],
                      "pool": "youtube_manual", "teams": it.get("teams") or [],
                      "text": (it.get("description") or "")[:400]})

    yc = load(DATA / "youtube_channels.json")
    for c in ((yc or {}).get("items") or []):
        for it in (c.get("videos") or []):
            if not it.get("title"):
                continue
            pools.append({"title": it["title"], "url": it.get("url") or "",
                          "date": "", "pool": "youtube_channel",
                          "teams": it.get("teams") or [], "text": ""})

    fda_items, fda_fails = collect_fda()
    for it in fda_items:
        pools.append({**it, "pool": "fda", "text": "fda regulation recall"})

    # 제목 없는 항목은 버린다. openFDA 선케어 신호 하나가 제목 없이
    # 들어와 법률팀 화면에 빈 줄로 떴다. 사람이 보는 목록이라 URL 만
    # 있는 줄은 쓸모가 없다.
    dropped = len(pools)
    pools = [it for it in pools if str(it.get("title") or "").strip()]
    dropped -= len(pools)

    teams = {t: [] for t in ROUTE}
    for t in POOL_TEAMS.values():
        for x in t:
            teams.setdefault(x, [])
    unrouted = 0
    for it in pools:
        # 항목이 팀을 들고 왔으면 그것이 답이다. 낱말은 보지 않는다.
        given = [t for t in (it.get("teams") or []) if t != "knowledge" or True]
        if given:
            hits = list(given)
        else:
            hits = route(f'{it.get("title","")} {it.get("text","")} {it.get("pool","")}')
        # 제목에 낱말이 없어도 출처를 알면 팀은 정해진다.
        pool = str(it.get("pool") or "")
        by_pool = POOL_TEAMS.get(pool, ())
        if not by_pool and pool.startswith("signal:"):
            by_pool = ("market",)
        hits = list(dict.fromkeys(list(hits) + list(by_pool)))
        if pool == "fda":
            hits = list(dict.fromkeys(hits + ["legal"]))
        if not hits:
            unrouted += 1
            continue
        for t in hits:
            row = {k: it[k] for k in ("title", "url", "pool") if k in it}
            row["date"] = iso_date(it.get("date", ""))
            # 사람이 직접 넣은 것은 위에 둔다. 골라 넣은 자료가 자동
            # 수집분에 밀려 안 보이면 넣은 의미가 없다.
            row["by_hand"] = it.get("pool") in BY_HAND
            teams[t].append(row)

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
        uniq.sort(key=lambda r: (bool(r.get("by_hand")), str(r.get("date") or "")),
                  reverse=True)
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
        "제목없어_버림": dropped,
        "unrouted": unrouted,
        "summary": summary,
        "fda_failures": fda_fails,
        "not_collected": NOT_COLLECTED,
        "teams": teams,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n전체 풀 {len(pools)}건 · 미배정 {unrouted}건"
          + (f" · 제목 없어 버림 {dropped}건" if dropped else ""))
    for t, s in summary.items():
        print(f"  {t:10s} 총 {s['total']:4d}  최근 {RECENT_DAYS}일 {s['recent']:3d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
