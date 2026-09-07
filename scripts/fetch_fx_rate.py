#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""USD ↔ KRW 환율을 받아 collection_status.json 의 fx 에 쓴다.

왜 떼어냈나
  환율 코드가 collect_daiso.py 안에 있었다. 상품 수집기가 마지막에
  환율까지 받아서 같은 파일에 저장하는 구조였다.

  문제는 다이소 수집이 조용히 죽는 일이 실제로 있었다는 것이다.
  09-06 21:23 실행이 성공으로 보고됐는데 collection_status 는 09-05 것
  그대로였다. 그때 환율도 같이 멈춘다. 원가 계산은 환율에 걸려 있는데
  상품 수집이 막혔다고 환율까지 멈출 이유가 없다.

  값이 저장되는 자리는 그대로 둔다. collection_status.json 의 fx 다.
  pricing_model.py, build_shopify_import_csv.py, generate_dashboard_runtime.py
  세 곳이 이미 그 자리를 읽고 있어서 옮기면 셋 다 고쳐야 한다.

없는 값을 만들지 않는다
  세 곳 다 실패하면 usd_to_krw 를 None 으로 두고 ok=False 와 오류를
  남긴다. 예전 환율을 그대로 쓰지 않는다. 틀린 환율로 계산한 마진은
  아예 없느니만 못하다.

  다만 파일의 다른 부분(last_run, totals)은 건드리지 않는다.
  이 스크립트는 fx 칸만 쓴다.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "data" / "daiso_real" / "collection_status.json"
UA = "JarvisLunaResearchBot/1.0 (+contact: coar0000@naver.com)"
TIMEOUT = 20

# 세 곳을 모두 물어보고 기준일이 가장 최근인 것을 쓴다.
#
# 처음에는 순서대로 시도해 첫 성공을 썼다. 그런데 Frankfurter 는 ECB
# 고시라 주말과 휴일에 갱신되지 않는다. 월요일 오후에 물어보니 금요일
# 값(09-04)을 줬고, 그걸 쓰면 이미 있던 09-07 값보다 오래된 환율로
# 덮어쓰게 된다. 값이 뒤로 가는 것은 갱신이 아니다.
MONTHS = {m: f"{i:02d}" for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def as_date(raw) -> str:
    """어떤 형식으로 오든 YYYY-MM-DD 로 맞춘다.

    ExchangeRate-API 는 'Mon, 07 Sep 2026 00:02:31 +0000' 로 준다.
    앞 10글자만 잘랐더니 'Mon, 07 Se' 가 저장됐다. 날짜가 아니라
    문자열이라 최신 판별도 우연히 맞았을 뿐이다.
    """
    t = str(raw or "").strip()
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


ENDPOINTS = [
    ("https://api.frankfurter.app/latest?from=USD&to=KRW",
     lambda d: float(d["rates"]["KRW"]),
     lambda d: as_date(d.get("date")),
     "Frankfurter API"),
    ("https://open.er-api.com/v6/latest/USD",
     lambda d: float(d["rates"]["KRW"]),
     lambda d: as_date(d.get("time_last_update_utc")) or as_date(d.get("date")),
     "ExchangeRate-API"),
    ("https://api.exchangerate-api.com/v4/latest/USD",
     lambda d: float(d["rates"]["KRW"]),
     lambda d: as_date(d.get("date")),
     "exchangerate-api"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read(200000).decode("utf-8", "replace")


def fetch_fx() -> dict:
    """세 곳을 다 물어보고 기준일이 가장 최근인 값을 쓴다."""
    got, last_err = [], None
    for url, rate_fn, date_fn, label in ENDPOINTS:
        try:
            status, body = get(url)
            if status != 200:
                raise RuntimeError(f"HTTP {status}")
            data = json.loads(body)
            krw = round(float(rate_fn(data)), 2)
            as_of = date_fn(data) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            got.append({"usd_to_krw": krw, "as_of": as_of,
                        "source": label, "api_url": url})
            print(f"   {label}: 1 USD = {krw:,.2f} KRW (기준일 {as_of})")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                ValueError, KeyError, TypeError, RuntimeError) as e:
            last_err = e
            print(f"⚠️ 환율 API 실패 ({label}): {type(e).__name__}: {e}")
            continue

    if got:
        got.sort(key=lambda x: str(x.get("as_of") or ""), reverse=True)
        best = got[0]
        others = [f"{g['source']} {g['usd_to_krw']:,.2f}({g['as_of']})"
                  for g in got[1:]]
        print(f"✅ 환율 갱신 완료 : 1 USD = {best['usd_to_krw']:,.2f} KRW "
              f"({best['as_of']}, {best['source']})")
        if others:
            print(f"   다른 곳: {' · '.join(others)}")
        return {
            "usd_to_krw": best["usd_to_krw"],
            "krw_to_usd": round(1 / best["usd_to_krw"], 8),
            "as_of": best["as_of"],
            "source": best["source"],
            "api_url": best["api_url"],
            "fetched_at": now_iso(),
            "ok": True,
            "대조": others,
        }
    return {
        "usd_to_krw": None,
        "krw_to_usd": None,
        "as_of": None,
        "source": "all-failed",
        "api_url": None,
        "fetched_at": now_iso(),
        "ok": False,
        "error": f"{type(last_err).__name__}: {last_err}" if last_err else "unknown",
    }


def main() -> int:
    fx = fetch_fx()

    try:
        doc = json.loads(STATUS.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        doc = {}
    if not isinstance(doc, dict):
        doc = {}

    prev = doc.get("fx") or {}

    # 기준일이 뒤로 가면 덮어쓰지 않는다. 이미 09-07 값이 있는데
    # 09-04 값으로 바꾸면 그건 갱신이 아니라 후퇴다.
    if (fx.get("ok") and prev.get("ok") and prev.get("as_of")
            and str(fx.get("as_of") or "") < str(prev["as_of"])):
        print(f"::warning::받은 값의 기준일({fx['as_of']})이 이미 있는 것"
              f"({prev['as_of']})보다 오래됐다. 기존 값을 유지한다.")
        keep = dict(prev)
        keep["checked_at"] = fx["fetched_at"]
        keep["보류"] = (f"{fx['source']} 가 {fx['as_of']} 기준 "
                      f"{fx['usd_to_krw']:,.2f} 을 줬으나 더 오래되어 쓰지 않았다.")
        doc["fx"] = keep
        fx = keep
    else:
        doc["fx"] = fx

    STATUS.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    for _ in range(4):
        STATUS.write_text(body, encoding="utf-8")
        try:
            back = json.loads(STATUS.read_text(encoding="utf-8-sig"))
            if (back.get("fx") or {}) == fx:
                break
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass
        time.sleep(0.5)
    else:
        print("기록 검증 실패", file=sys.stderr)
        return 1

    # 다른 칸을 건드리지 않았는지 눈으로 확인할 수 있게 남긴다.
    keys = [k for k in doc if k != "fx"]
    print(f"   같은 파일의 다른 칸은 그대로: {', '.join(keys) or '없음'}")
    if prev.get("usd_to_krw") and fx.get("usd_to_krw"):
        diff = fx["usd_to_krw"] - prev["usd_to_krw"]
        if abs(diff) >= 0.01:
            print(f"   직전 {prev['usd_to_krw']:,.2f} → {fx['usd_to_krw']:,.2f} "
                  f"({diff:+.2f})")
        else:
            print(f"   직전과 같음 ({fx['usd_to_krw']:,.2f})")
    if not fx.get("ok"):
        print(f"::error::환율을 세 곳 모두에서 못 받았다. {fx.get('error')}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
