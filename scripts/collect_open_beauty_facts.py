#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Open Beauty Facts 실데이터 수집기.

world.openbeautyfacts.org 는 인증이 필요 없는 공개 오픈데이터다.
크라우드소싱 화장품 DB로 라이선스상 재사용이 자유롭다.

용도
  수요 신호가 아니라 상품 정보 보강용이다.
  다이소 실수집 상품의 카테고리를 국제 표준 분류와 성분 정보에 연결해
  Shopify 상세 페이지 작성에 쓴다.

원칙
  - 응답이 없으면 빈 결과를 저장한다. 절대 지어내지 않는다.
  - 각 항목에 원본 바코드(code)와 URL 을 남겨 검증 가능하게 한다.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "open_beauty_facts.json"

BASE = "https://world.openbeautyfacts.org/api/v2/search"
UA = "JARVIS-LUNA/1.0 (https://github.com/coar0000-wq/jarvis-luna)"
TIMEOUT = 30
DELAY = 1.0          # 공개 오픈데이터지만 예의상 요청 간 1초
PER_CATEGORY = 12

# 다이소 12개 수집 카테고리 -> Open Beauty Facts 카테고리 태그
CATEGORY_MAP = {
    "스킨케어":   "skin-care",
    "마스크팩":   "face-masks",
    "클렌징":     "cleansers",
    "선케어":     "sunscreens",
    "메이크업":   "face-creams",
    "헤어케어":   "hair-care",
    "바디케어":   "soaps",
    "구강용품":   "toothpastes",
    "향수":       "perfumes",
    "핸드케어":   "hand-creams",
    "데오드란트": "deodorants",
    "립케어":     "lip-balms",
}

FIELDS = "code,product_name,brands,categories_tags_en,countries_tags_en,ingredients_text,image_url"


def fetch(category_tag: str) -> tuple[list[dict], str]:
    params = urllib.parse.urlencode({
        "categories_tags_en": category_tag,
        "fields": FIELDS,
        "page_size": PER_CATEGORY,
        "sort_by": "unique_scans_n",
    })
    url = f"{BASE}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return [], f"{type(e).__name__}: {e}"
    return data.get("products") or [], ""


def main() -> None:
    products: list[dict] = []
    errors: dict[str, str] = {}
    per_cat: dict[str, int] = {}

    for ko, tag in CATEGORY_MAP.items():
        items, err = fetch(tag)
        if err:
            errors[ko] = err
            per_cat[ko] = 0
            print(f"[{ko:8s}] 실패 - {err}")
            time.sleep(DELAY)
            continue

        kept = 0
        for p in items:
            name = (p.get("product_name") or "").strip()
            code = (p.get("code") or "").strip()
            if not name or not code:
                continue
            products.append({
                "code": code,
                "product_name": name,
                "brands": (p.get("brands") or "").strip(),
                "category": ko,
                "obf_category": tag,
                "countries": p.get("countries_tags_en") or [],
                "ingredients_text": (p.get("ingredients_text") or "").strip(),
                "image_url": p.get("image_url") or "",
                "url": f"https://world.openbeautyfacts.org/product/{code}",
            })
            kept += 1
        per_cat[ko] = kept
        print(f"[{ko:8s}] {kept}건")
        time.sleep(DELAY)

    payload = {
        "source": "world.openbeautyfacts.org /api/v2/search",
        "license": "Open Database License (ODbL) - 재사용 허용",
        "auth_required": False,
        "note": (
            "수요 신호가 아니라 상품 정보 보강용 오픈데이터. "
            "각 항목은 바코드(code)와 원본 URL 로 검증 가능하다."
        ),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "category_map": CATEGORY_MAP,
        "per_category": per_cat,
        "errors": errors,
        "count": len(products),
        "products": products,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"\n총 {len(products)}건 저장 -> {OUT.relative_to(ROOT)}")
    if errors:
        print(f"실패 카테고리 {len(errors)}개: {list(errors)}")


if __name__ == "__main__":
    main()
