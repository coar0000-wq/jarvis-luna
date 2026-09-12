#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""상품 수요 신호 수집기 — data/products.json.

박혀 있던 예시 데이터를 뺐다 (2026-09-12).

  파일 첫 줄에 '진짜 데이터만 수집, 증거 없으면 저장 안 함' 이라고 적혀 있었는데
  정작 collect_real_products() 안에는 이런 값이 파이썬 소스에 그대로 있었다.

    "name": "Hydrating Serum"
    "demand_change": 24
    "raw_snippet": "Interest: 68 -> 84 (past 7 days), +24% WoW"
    "collected_at": datetime.utcnow()

  68 -> 84 도 +24% 도 Google Trends 에서 받아온 값이 아니다. 사람이 적은 값이다.
  collected_at 은 수집 시각이 아니라 실행 시각이었다.
  그런데 validate_evidence 는 형식만 보므로 전부 통과했다.
  형식이 맞는 지어낸 값은 검증기를 지나가서 실측처럼 보인다. 제일 위험하다.

  이 값은 data/products.json 에 쌓였고 generate_dashboard_runtime.py 가
  그걸 읽어 대시보드에 올렸다. 화면에 뜬 수요 증가율이 지어낸 숫자였다.

  CLAUDE.md: 거짓말 데이터 금지 / 가짜 데이터 금지. 그래서 뺐다.

  같은 워크플로(.github/workflows/jarvis_deep_analysis.yml)의 gosi_collector.py
  도 똑같이 지어낸 시험 공고를 data/gosi.json 에 쓰고 있었다. 같이 고쳤다.

  진짜로 붙이려면 fetch_demand_signals() 안에서 실제로 HTTP 를 때리고
  받아온 응답에서 잘라낸 글자를 raw_snippet 에 넣으면 된다.
  이미 실측으로 도는 수집기가 따로 있다.
    scripts/collect_public_signals.py      Trends·Wikipedia·Allure·openFDA
    scripts/collect_google_trends_beauty.py
    scripts/daiso/score_shopify_demand.py  다이소 실측 지표 기반 점수
  그것들과 겹치지 않게 붙여야 한다. 그 전까지는 빈 채로 둔다.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "products.json"


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def validate_evidence(item: dict) -> bool:
    """증거 3종의 형식을 본다.

    주의: 형식 검사일 뿐이다. 값이 진짜인지는 못 본다.
    예전에 지어낸 값이 이 검사를 그대로 통과했다.
    실측 보장은 fetch_demand_signals() 가 실제로 받아오는 것뿐이다.
    """
    ev = item.get("evidence") or {}
    for k in ("source_url", "collected_at", "raw_snippet"):
        if not ev.get(k):
            return False
    if not str(ev["source_url"]).startswith("http"):
        return False
    try:
        datetime.datetime.fromisoformat(
            str(ev["collected_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def fetch_demand_signals() -> list[dict]:
    """실제 수요 신호를 받아온다.

    아직 구현하지 않았다. 예시 데이터로 채우지 않는다.
    """
    return []


def collect_real_products() -> list[dict]:
    items = fetch_demand_signals()
    valid = [x for x in items if validate_evidence(x)]

    payload = {
        "products": valid,
        "updated_at": now(),
        "수집기": "product_discovery.py",
    }

    if not valid:
        payload["note"] = (
            "수집기가 아직 없다. 지어낸 예시 데이터를 넣지 않으려고 비워 둔다. "
            "예전 버전은 Hydrating Serum 의 수요 증가율 24% 를 소스에 박아 두고 "
            "대시보드에 올렸다. 2026-09-12 에 제거했다. "
            "실측 수요는 scripts/daiso/score_shopify_demand.py 를 본다."
        )

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"{DATA_PATH.relative_to(ROOT)} 저장: {len(valid)}건")
    if not valid:
        print("  (수집기 미구현. 빈 상태로 둔다.)")
    return valid


if __name__ == "__main__":
    collect_real_products()
