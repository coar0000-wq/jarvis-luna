#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SerpApi 로 미국 시장가와 검색 관심도를 채운다.

무료 플랜은 월 250회, 시간당 50회다 (2026-09-05 serpapi.com/pricing 확인).
성공한 호출만 차감되고 캐시·오류는 차감되지 않는다.

그래서 두 가지를 지킨다.
  1) 월 사용량을 파일로 기록하고 상한을 넘으면 아예 호출하지 않는다.
  2) 매일이 아니라 주 1회만 돈다. 하루 8회 예산으로는 매일 돌 수 없다.

메우는 공백
  가격: market_benchmark 가 올리브영 베스트셀러 100건의 중앙값 하나뿐이라
        상품별 미국 실판매가가 없었다. google_shopping 으로 상품마다 받는다.
  트렌드: 키워드보드의 trend 가 전부 null 이었다. 공식 Trends API 가
        승인제 알파라서다. google_trends 로 채운다.

키가 없거나 예산을 넘기면 status 를 skipped 로 두고 사유를 남긴다.
값을 지어내지 않는다.
"""
from __future__ import annotations
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "serpapi_market.json"
LEDGER = DATA / "serpapi_usage.json"

ENDPOINT = "https://serpapi.com/search.json"
MONTHLY_CAP = 200        # 무료 250 중 50 은 수동 확인용으로 남긴다
PRODUCT_LIMIT = 14       # S등급 전부
KEYWORD_LIMIT = 8
TIMEOUT = 30
DELAY = 2.0              # 시간당 50회 제한을 넉넉히 지킨다
RANKING_PRICE_LIMIT = 3  # 2026-10-16: 메이크업 실시간 랭킹 대체 후보 상위 3개 (월 상한 안에서)
DRAFT_PRICE_LIMIT = 4    # 2026-10-17: 이미 Shopify 초안인데 판매가 근거가 없는 상품 (월 상한 안에서)
REGISTRY = DATA / "shopify_daily_registry.json"
STRATEGY = ROOT / "config" / "daiso_commerce_strategy.json"


def load(path: Path, default=None):
    for _ in range(3):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            time.sleep(0.4)
    return default


def month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def read_ledger() -> dict:
    d = load(LEDGER, None) or {}
    if d.get("month") != month_key():
        return {"month": month_key(), "used": 0, "cap": MONTHLY_CAP, "runs": []}
    # 여기도 대입이다. 상한을 코드에서 바꿔도 원장에 적힌 옛 값이
    # 이기면 바꾼 의미가 없다.
    d["cap"] = MONTHLY_CAP
    d.setdefault("runs", [])
    return d


def call(params: dict, ledger: dict) -> tuple[dict | None, str]:
    """1회 호출. 예산을 넘으면 호출하지 않는다."""
    if ledger["used"] >= ledger["cap"]:
        return None, f"월 상한 {ledger['cap']}회 도달"
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    try:
        raw = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "JARVIS-LUNA/1.0"}),
            timeout=TIMEOUT).read()
        d = json.loads(raw.decode("utf-8"))
    except Exception as exc:                       # 실패는 차감되지 않는다
        return None, f"{type(exc).__name__}: {exc}"[:120]
    if d.get("error"):
        return None, str(d["error"])[:120]
    # 캐시 응답은 과금되지 않는다. 응답의 search_metadata 로 판별한다.
    cached = str((d.get("search_metadata") or {}).get("status", "")).lower() == "cached"
    if not cached:
        ledger["used"] += 1
    return d, "cached" if cached else "ok"


def to_usd(x) -> float | None:
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.replace("$", "").replace(",", "").strip()
        try:
            return float(s.split()[0])
        except (ValueError, IndexError):
            return None
    return None


def ranking_targets(skip: set[str]) -> list[dict]:
    """메이크업 실시간 랭킹 대체 후보 중 가격 근거가 필요한 상위 몇 개.

    2026-10-16: 일일 등록이 S 없는 날 랭킹 1위(메이크업 픽서)를 골랐지만 'price_evidence_missing' 으로
    제외됐다. 이 수집기는 S 만 시장가를 받아서 랭킹 상품은 가격 근거가 영영 없었다.
    가격 규칙은 그대로 두고(상품별 근거 필수), 근거를 받을 대상만 넓힌다.
    비비·쿠션·팩트 등은 일일 등록에서 고시 확인 없이는 어차피 빠지므로 여기서도 쓰지 않는다.
    """
    policy = (load(STRATEGY) or {}).get("makeup_ranking_fallback") or {}
    if not policy.get("enabled"):
        return []
    q = urllib.parse.urlencode({"pageNum": 1, "cntPerPage": 30, "largeExhCtgrNo": policy.get("large_ctgr"),
                                "middleExhCtgrNo": policy.get("middle_ctgr")})
    req = urllib.request.Request(policy["api_url"] + "?" + q, headers={
        "User-Agent": "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)",
        "Accept": "application/json", "Referer": policy.get("page_url", "")})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            rows = (json.loads(r.read().decode("utf-8", "replace")).get("resultSet") or {}).get("result") or []
    except Exception as exc:  # noqa: BLE001  랭킹을 못 읽으면 대상을 늘리지 않는다
        print(f"[serpapi] ranking fetch failed: {exc}")
        return []
    if rows and isinstance(rows[0], dict) and "resultDocuments" in rows[0]:
        rows = rows[0]["resultDocuments"]
    risk = [f.lower() for f in policy.get("spf_risk_forms") or []]
    out = []
    for i, x in enumerate(rows, 1):
        pd, name = str(x.get("pdNo") or ""), str(x.get("pdNm") or "")
        if not pd or pd in skip or x.get("soldOutYn") == "Y" or any(f in name.lower() for f in risk):
            continue
        out.append({"pd_no": pd, "name": name, "ranking_display_rank": i})
        if len(out) >= RANKING_PRICE_LIMIT:
            break
    return out


def registry_draft_targets(skip: set[str]) -> list[dict]:
    """일일 등록 장부의 DRAFT 중 판매가가 비어 있는 상품.

    2026-10-17: 수동 초안(1084687)·랭킹/바디 대체 초안은 S 가 아니라서 이 수집기의 대상이 아니었고,
    그래서 가격 근거가 영영 생기지 않았다('selling_price_evidence_pending' 에서 멈춤).
    가격 규칙(상품별 근거 필수, 용량 비교)은 그대로 두고 측정 대상만 넓힌다.
    판매 개시(공개·재고)는 여전히 등록 게이트와 사람 승인을 거친다.
    """
    reg = load(REGISTRY) or {}
    out = []
    for it in reg.get("items") or []:
        if not isinstance(it, dict) or str(it.get("status") or "").upper() != "DRAFT":
            continue
        pd, title = str(it.get("pd_no") or ""), str(it.get("title") or "")
        if not pd or pd in skip or it.get("single_usd") is not None:
            continue
        if not title or any("\uac00" <= ch <= "\ud7a3" for ch in title):
            continue  # 영문 상품명이 있어야 미국 쇼핑 검색이 같은 상품을 찾는다
        out.append({"pd_no": pd, "name": title, "query": title, "registry_draft": True})
        skip.add(pd)
        if len(out) >= DRAFT_PRICE_LIMIT:
            break
    return out


def collect_prices(key: str, ledger: dict) -> dict:
    score = load(DATA / "daiso_real" / "shopify_demand_score.json")
    copy = load(DATA / "shopify_listing_copy.json")
    if not score or not copy:
        return {"status": "failed", "reason": "점수 또는 카피 파일을 읽지 못함", "items": []}
    titles = {str(i.get("pd_no")): ((i.get("copy") or {}).get("title") or "")
              for i in copy.get("items", [])}
    targets = sorted([x for x in score.get("all_scored") or [] if x.get("grade") == "S"],
                     key=lambda x: -(x.get("shopify_score") or 0))[:PRODUCT_LIMIT]
    targets += ranking_targets({str(x.get("pd_no")) for x in targets})
    targets += registry_draft_targets({str(x.get("pd_no")) for x in targets})
    items, fails = [], []
    for x in targets:
        pd = str(x.get("pd_no"))
        q = titles.get(pd) or x.get("query") or x.get("name") or ""
        if not q:
            fails.append({"pd_no": pd, "reason": "질의어 없음"})
            continue
        d, note = call({"engine": "google_shopping", "q": q, "gl": "us", "hl": "en",
                        "num": 20, "api_key": key}, ledger)
        if d is None:
            fails.append({"pd_no": pd, "query": q, "reason": note})
            if "월 상한" in note:
                break
            time.sleep(DELAY)
            continue
        prices = []
        for r in (d.get("shopping_results") or [])[:20]:
            v = to_usd(r.get("extracted_price") if r.get("extracted_price") is not None
                       else r.get("price"))
            if v and 1 <= v <= 500:
                prices.append(v)
        items.append({
            "pd_no": pd, "name": x.get("name"), "query": q,
            "n": len(prices),
            "min_usd": round(min(prices), 2) if prices else None,
            "median_usd": round(median(prices), 2) if prices else None,
            "max_usd": round(max(prices), 2) if prices else None,
            "engine": "google_shopping", "cached": note == "cached",
            **({"source_scope": "makeup_ranking_fallback", "ranking_display_rank": x["ranking_display_rank"]}
               if x.get("ranking_display_rank") else {}),
            **({"source_scope": "registry_draft_missing_price"} if x.get("registry_draft") else {}),
        })
        time.sleep(DELAY)
    return {"status": "ok" if items else "failed",
            "reason": "" if items else "수집 0건",
            "count": len(items), "failures": fails, "items": items}


def collect_trends(key: str, ledger: dict) -> dict:
    mt = load(DATA / "market_team.json")
    if not mt:
        return {"status": "failed", "reason": "market_team.json 을 읽지 못함", "items": []}
    seeds = [k.get("seed") for k in (mt.get("keyword_board") or []) if k.get("seed")]
    seeds = seeds[:KEYWORD_LIMIT]
    items, fails = [], []
    for s in seeds:
        d, note = call({"engine": "google_trends", "q": s, "data_type": "TIMESERIES",
                        "geo": "US", "date": "today 12-m", "api_key": key}, ledger)
        if d is None:
            fails.append({"seed": s, "reason": note})
            if "월 상한" in note:
                break
            time.sleep(DELAY)
            continue
        pts = ((d.get("interest_over_time") or {}).get("timeline_data") or [])
        vals = []
        for p in pts:
            for v in p.get("values") or []:
                n = v.get("extracted_value")
                if isinstance(n, (int, float)):
                    vals.append(n)
        recent = vals[-8:] if len(vals) >= 8 else vals
        base = vals[:8] if len(vals) >= 16 else vals
        items.append({
            "seed": s, "points": len(vals),
            "avg_recent_8w": round(sum(recent) / len(recent), 1) if recent else None,
            "avg_base_8w": round(sum(base) / len(base), 1) if base else None,
            "peak": max(vals) if vals else None,
            "engine": "google_trends", "geo": "US", "window": "today 12-m",
            "cached": note == "cached",
        })
        time.sleep(DELAY)
    return {"status": "ok" if items else "failed",
            "reason": "" if items else "수집 0건",
            "count": len(items), "failures": fails, "items": items}


def main() -> int:
    key = os.environ.get("SERPAPI_KEY", "").strip()
    ledger = read_ledger()
    now = datetime.now(timezone.utc).isoformat()
    only = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--only=")), None)

    if not key:
        payload = {"generated_at": now, "status": "skipped",
                   "reason": "SERPAPI_KEY 가 없어 호출하지 않음. 값을 지어내지 않는다.",
                   "plan": "free 250/month", "usage": ledger}
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("SERPAPI_KEY 없음 - 건너뜀")
        return 0

    before = ledger["used"]
    previous = load(OUT, {}) or {}
    def block(name, collector):
        if only in (None, name):
            return {**collector(key, ledger), "collected_at": now}
        retained = dict(previous.get(name) or {"status": "skipped"})
        retained.setdefault("collected_at", previous.get("generated_at"))
        return retained
    prices = block("prices", collect_prices)
    trends = block("trends", collect_trends)
    spent = ledger["used"] - before
    ledger["runs"] = (ledger["runs"] + [{"at": now, "spent": spent}])[-20:]
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    payload = {
        "generated_at": now,
        "generator": "scripts/collect_serpapi_market.py",
        "plan": "SerpApi free 250 searches/month, 50/hour (2026-09-05 확인)",
        "정책": "월 상한 %d 회. 넘으면 호출하지 않고 사유만 남긴다. 주 1회만 실행한다." % MONTHLY_CAP,
        "usage": {"month": ledger["month"], "used": ledger["used"],
                  "cap": ledger["cap"], "spent_this_run": spent},
        "prices": prices,
        "trends": trends,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"이번 실행 {spent}회 사용 · 이번 달 누적 {ledger['used']}/{ledger['cap']}")
    print(f"  가격 {prices.get('count', 0)}건 / 트렌드 {trends.get('count', 0)}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
