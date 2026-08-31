#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gemini url_context 로 웹 채널을 수집한다.

결정적 파싱(정규식/JSON 엔드포인트)이 불가능한 사이트용 보조 수단이다.
OliveYoung US 처럼 데이터 엔드포인트를 찾을 수 있으면 그쪽을 쓴다.
이 스크립트는 그게 안 될 때만 쓴다.

중요 - 신뢰 등급이 다르다
  이건 LLM 이 페이지를 읽고 옮겨 적는 방식이라 숫자를 잘못 읽을 수 있다.
  그래서 모든 항목에 extraction_method="gemini_url_context" 를 박고
  대시보드에서 결정적 수집과 구분해 표시한다.
  검증되지 않은 값을 실측값인 척 섞지 않는다.

robots.txt (2026-08-31 확인)
  ulta.com     Google-Extended 에 대해 상품/카테고리 경로 허용
               (/wishlists/, /curbside-alert/, /metrics*, /community/groups 만 금지)
  sephora.com  /browse/ 와 /search 금지, Crawl-delay 5
               따라서 /shop/ 경로만 사용하고 요청 간 5초 이상 쉰다

환경변수
  GEMINI_API_KEY  필수
  GEMINI_URL_MODEL  선택 (기본 gemini-3.7-flash)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "gemini_web_channels.json"

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
MODEL = os.environ.get("GEMINI_URL_MODEL", "gemini-3.7-flash")
TIMEOUT = 120
RETRIES = 3

# robots.txt 를 지킨 경로만 넣는다. Crawl-delay 는 delay 로 반영한다.
TARGETS = [
    {
        "key": "ulta_beauty",
        "label": "Ulta Beauty",
        "url": "https://www.ulta.com/shop/skin-care/moisturizers",
        "delay": 3,
        "robots": "ulta.com robots.txt: Google-Extended 에 상품 경로 허용",
    },
    {
        "key": "sephora",
        "label": "Sephora",
        "url": "https://www.sephora.com/shop/moisturizing-cream-oils-mists",
        "delay": 6,   # Crawl-delay 5 보다 여유 있게
        "robots": "sephora.com robots.txt: /browse/ 와 /search 금지, Crawl-delay 5",
    },
]

PROMPT = """Read the product listing page at {url} and extract the products shown.

Return ONLY a JSON array. Each element must be exactly:
{{"product": "<full product name as printed>",
  "brand": "<brand as printed>",
  "price_usd": <number, no currency symbol>,
  "rating": <number or null>,
  "review_count": <integer or null>}}

Hard rules:
- Copy values exactly as they appear on the page. Do not estimate or round.
- If a field is not visible on the page, use null. Never guess a number.
- If the page did not load, is a login wall, or shows no products,
  return an empty array [].
- Do not include products you recall from memory. Only what is on this page.
- Maximum 40 products."""


def call(key: str, url: str) -> tuple[list, str, str]:
    body = {
        "model": MODEL,
        "input": PROMPT.format(url=url),
        "tools": [{"type": "url_context"}],
    }
    data = json.dumps(body).encode("utf-8")
    last = ""
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(
                ENDPOINT, data=data, method="POST",
                headers={"Content-Type": "application/json", "x-goog-api-key": key})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                res = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:250]
            last = f"HTTP {e.code}: {detail}"
            if e.code in (429, 500, 503):
                time.sleep(5 * attempt)
                continue
            return [], last, ""
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(5 * attempt)
    else:
        return [], last or "재시도 소진", ""

    # 응답에서 텍스트와 url_context 상태를 뽑는다
    text, fetch_status = "", ""
    for step in res.get("steps", []):
        st = step.get("type")
        if st == "url_context_result":
            fetch_status = json.dumps(
                {k: v for k, v in step.items() if k != "type"}, ensure_ascii=False)[:300]
        elif st == "model_output":
            for cb in step.get("content", []):
                if cb.get("type") == "text":
                    text += cb.get("text", "")

    if not text:
        return [], f"모델 출력 없음. url_context 상태: {fetch_status or '없음'}", fetch_status

    t = re.sub(r"^```(?:json)?\s*", "", text.strip())
    t = re.sub(r"\s*```$", "", t)
    m = re.search(r"\[.*\]", t, re.S)
    if not m:
        return [], f"JSON 배열 없음: {t[:150]}", fetch_status
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return [], f"JSON 파싱 실패: {e}", fetch_status
    if not isinstance(arr, list):
        return [], "배열이 아님", fetch_status
    return arr, "", fetch_status


def clean(arr: list, target: dict) -> list[dict]:
    """이름과 가격이 둘 다 있는 항목만 인정한다."""
    rows = []
    for x in arr:
        if not isinstance(x, dict):
            continue
        name = str(x.get("product") or "").strip()
        price = x.get("price_usd")
        if not name or len(name) < 4:
            continue
        if not isinstance(price, (int, float)) or price <= 0:
            continue
        rows.append({
            "rank": len(rows) + 1,
            "product": name[:200],
            "brand": str(x.get("brand") or "").strip()[:80],
            "price_usd": round(float(price), 2),
            "rating": x.get("rating") if isinstance(x.get("rating"), (int, float)) else None,
            "review_count": x.get("review_count") if isinstance(x.get("review_count"), int) else None,
            "source_url": target["url"],
            "extraction_method": "gemini_url_context",
        })
    return rows[:40]


def main() -> int:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("GEMINI_API_KEY 가 없습니다.")
        return 1

    channels, total = {}, 0
    for t in TARGETS:
        arr, err, status = call(key, t["url"])
        rows = clean(arr, t) if not err else []
        channels[t["key"]] = {
            "label": t["label"],
            "url": t["url"],
            "robots_note": t["robots"],
            "count": len(rows),
            "status": "ok" if rows else "failed",
            "reason": err or ("" if rows else "페이지에서 상품을 얻지 못함"),
            "url_context_result": status,
            "products": rows,
        }
        total += len(rows)
        print(f"[{t['label']:14s}] {len(rows):2d}건  {err[:70] if err else 'OK'}")
        time.sleep(t["delay"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/collect_via_gemini.py",
        "model": MODEL,
        "method": "Gemini API url_context 도구",
        "trust_note": ("LLM 이 페이지를 읽어 옮긴 값이다. 결정적 파싱보다 신뢰도가 낮다. "
                       "대시보드에서 'AI 추출' 로 구분 표시하며 "
                       "가격 정책 계산에는 사용하지 않는다."),
        "total": total,
        "channels": channels,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n총 {total}건 -> {OUT.relative_to(ROOT)}")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
