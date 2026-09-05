#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S등급 다이소 상품의 영문 Shopify 리스팅 카피를 Gemini 로 생성한다.

입력  data/daiso_real/shopify_s_recommendations.json  (실크롤링 기반 S등급)
출력  data/shopify_listing_copy.json

원칙 (CLAUDE.md: 거짓말 데이터 금지 / 가짜 데이터 금지)
  - Gemini 응답이 없거나 파싱 실패하면 그 상품은 비운 채로 두고 사유를 남긴다.
    사람이 쓴 것처럼 보이는 문구를 스크립트가 지어내지 않는다.
  - 원본 한국어 상품명·가격·평점·리뷰수를 함께 저장해 대조 가능하게 한다.
  - 성분·효능·인증 같은 검증 불가한 주장은 프롬프트에서 금지한다.
    (미국 화장품 표시 규제상 근거 없는 효능 표현은 위험하다)

환경변수
  GEMINI_API_KEY   Google AI Studio 키 (필수)
  GEMINI_MODEL     선택. 없으면 ListModels 로 사용 가능한 모델을 고른다.
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
SRC = ROOT / "data" / "daiso_real" / "shopify_s_recommendations.json"
FULL = ROOT / "data" / "daiso_real" / "shopify_demand_score.json"
OUT = ROOT / "data" / "shopify_listing_copy.json"

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT = 90
RETRIES = 3
DELAY = 2.0

PROMPT = """You are writing Shopify product listings for a US storefront that
resells Korean beauty products sourced from Daiso Korea.

Korean product name: {name}
Category: {bucket}
Source price (KRW, retail in Korea): {price_krw}
Customer rating on daisomall.co.kr: {rating} from {reviews} reviews

Write the English listing. Rules you must follow:
- Base everything on the Korean product name only. Do not invent ingredients,
  certifications, clinical results, or country-of-manufacture claims.
- NEVER use any of these phrases. They turn a cosmetic into an unapproved drug
  under US rules, so they must not appear anywhere in the listing:
{banned}
- Korea labels some products as "functional cosmetics" (whitening, anti-wrinkle).
  The US has no such category. Never translate or reference it.
- Use appearance-based wording instead. Say "smooths the look of fine lines",
  not "removes wrinkles". Say "for a brighter-looking complexion", not "whitening".
- Do not mention Daiso, the Korean retail price, or that this is a resale.
- If the Korean name states a specific ingredient (for example heartleaf,
  snail mucin, centella, collagen, PDRN, mineral/physical sunscreen) you may
  name that ingredient, because it comes from the product name itself.
- Keep the volume/size if the Korean name has one.

Return ONLY a JSON object, no markdown fence, with exactly these keys:
{{
  "title": "under 70 characters, product name in English",
  "description_html": "2 short paragraphs in simple HTML using <p> tags only",
  "seo_title": "under 70 characters",
  "seo_description": "under 320 characters",
  "tags": ["6 to 10 lowercase search keywords, hyphens instead of spaces"],
  "product_type": "short product type such as Sunscreen or Face Serum"
}}"""


def http_json(url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json",
                 "User-Agent": "JARVIS-LUNA/1.0"},
        method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def pick_model(key: str) -> tuple[str, str]:
    """사용 가능한 모델을 실제로 조회해서 고른다. 모델명 하드코딩을 피한다."""
    forced = os.environ.get("GEMINI_MODEL", "").strip()
    if forced:
        return forced, "GEMINI_MODEL 환경변수 지정"
    try:
        data = http_json(f"{API_ROOT}/models?key={key}&pageSize=200")
    except Exception as e:
        raise RuntimeError(f"모델 목록 조회 실패: {type(e).__name__}: {e}") from e

    usable = [m["name"] for m in data.get("models", [])
              if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    if not usable:
        raise RuntimeError("generateContent 를 지원하는 모델이 없음")

    # 저렴하고 빠른 flash 계열 우선, 그다음 pro
    for pat in (r"flash-lite", r"flash", r"pro"):
        for n in sorted(usable, reverse=True):
            if re.search(pat, n) and "vision" not in n and "embedding" not in n:
                return n.replace("models/", ""), f"ListModels 자동 선택 ({len(usable)}개 중)"
    return usable[0].replace("models/", ""), "ListModels 첫 번째"


def extract_json(text: str) -> dict | None:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


REQUIRED = ("title", "description_html", "seo_title", "seo_description",
            "tags", "product_type")

RULES_PATH = ROOT / "data" / "us_claim_rules.json"


def load_rules() -> tuple[list[str], str]:
    """미국에서 쓰면 안 되는 표현. 경고가 아니라 생성 자체를 막는 데 쓴다."""
    try:
        d = json.loads(RULES_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return [], ""
    terms = [t.lower() for group in (d.get("banned") or {}).values() for t in group]
    lines = []
    for group, ts in (d.get("banned") or {}).items():
        lines.append("  " + ", ".join(f'"{t}"' for t in ts))
    return terms, "\n".join(lines)


BANNED, BANNED_TEXT = load_rules()


def find_banned(copy: dict) -> list[str]:
    """생성 결과에 금지 표현이 남았는지 본다. 남으면 그 항목은 버린다."""
    blob = " ".join(str(copy.get(k) or "") for k in REQUIRED).lower()
    blob += " " + " ".join(str(t) for t in (copy.get("tags") or []))
    return sorted({t for t in BANNED if t in blob.lower()})


def generate(key: str, model: str, p: dict) -> tuple[dict | None, str]:
    prompt = PROMPT.replace("{banned}", BANNED_TEXT).format(
        name=p.get("name", ""), bucket=p.get("bucket", ""),
        price_krw=p.get("price_krw", ""), rating=p.get("rating", ""),
        reviews=p.get("review_count", ""))
    url = f"{API_ROOT}/models/{model}:generateContent?key={key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1200,
                             "responseMimeType": "application/json"},
    }
    last = ""
    for attempt in range(1, RETRIES + 1):
        try:
            res = http_json(url, body)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            last = f"HTTP {e.code}: {detail}"
            if e.code in (429, 500, 503):
                time.sleep(DELAY * attempt * 2)
                continue
            return None, last
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(DELAY * attempt)
            continue

        cands = res.get("candidates") or []
        if not cands:
            fb = res.get("promptFeedback", {})
            return None, f"응답에 candidates 없음 {json.dumps(fb, ensure_ascii=False)[:150]}"
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(x.get("text", "") for x in parts)
        obj = extract_json(text)
        if not obj:
            last = f"JSON 파싱 실패: {text[:150]}"
            time.sleep(DELAY)
            continue
        missing = [k for k in REQUIRED if not obj.get(k)]
        if missing:
            last = f"필수 키 누락 {missing}"
            time.sleep(DELAY)
            continue
        if isinstance(obj.get("tags"), str):
            obj["tags"] = [t.strip() for t in obj["tags"].split(",") if t.strip()]
        bad = find_banned(obj)
        if bad:
            # 금지 표현이 남았으면 다시 시킨다. 끝까지 남으면 버린다.
            # 경고만 띄우고 넘기면 그 문구가 스토어에 올라간다.
            last = "금지 표현 포함: " + ", ".join(bad[:5])
            time.sleep(DELAY)
            continue
        return obj, ""
    return None, last or "원인 미상"


def main() -> int:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("GEMINI_API_KEY 가 없습니다. GitHub Secrets 에 등록하세요.")
        return 1
    if not SRC.exists():
        print(f"입력 파일 없음: {SRC}")
        return 1

    src = json.loads(SRC.read_text(encoding="utf-8"))
    products = src.get("recommendations") or []
    if not products:
        print("S등급 추천이 비어 있습니다.")
        return 1

    # S등급 파일에는 평점·리뷰수·이미지가 없어서 전체 점수 파일에서 보완한다.
    detail = {}
    if FULL.exists():
        try:
            for x in (json.loads(FULL.read_text(encoding="utf-8")).get("all_scored") or []):
                detail[str(x.get("pd_no"))] = x
        except (OSError, json.JSONDecodeError):
            pass
    for p in products:
        d = detail.get(str(p.get("pd_no"))) or {}
        for k in ("rating", "review_count", "image_url", "url"):
            if not p.get(k) and d.get(k) is not None:
                p[k] = d[k]

    model, how = pick_model(key)
    print(f"모델: {model}  ({how})")

    items, ok, fail = [], 0, 0
    for i, p in enumerate(products, 1):
        copy, err = generate(key, model, p)
        row = {
            "pd_no": p.get("pd_no"),
            "name_ko": p.get("name"),
            "bucket": p.get("bucket"),
            "price_krw": p.get("price_krw"),
            "rating": p.get("rating"),
            "review_count": p.get("review_count"),
            "shopify_score": p.get("shopify_score"),
            "source_url": p.get("url"),
            "image_url": p.get("image_url"),
            "copy": copy,
            "copy_status": "ok" if copy else "failed",
            "error": err,
        }
        items.append(row)
        if copy:
            ok += 1
            print(f"  [{i:2d}/{len(products)}] OK   {p.get('name','')[:34]} -> {copy['title'][:44]}")
        else:
            fail += 1
            print(f"  [{i:2d}/{len(products)}] FAIL {p.get('name','')[:34]} :: {err[:70]}")
        time.sleep(DELAY)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/gemini_listing_copy.py",
        "model": model,
        "model_selection": how,
        "source": "data/daiso_real/shopify_s_recommendations.json (다이소 실크롤링 S등급)",
        "note": ("영문 카피는 Gemini 생성물이므로 게시 전 사람이 검수해야 한다. "
                 "실패한 항목은 비워 두며 스크립트가 대체 문구를 지어내지 않는다."),
        "total": len(items), "ok": ok, "failed": fail,
        "items": items,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n{ok}/{len(items)}건 생성 -> {OUT.relative_to(ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
