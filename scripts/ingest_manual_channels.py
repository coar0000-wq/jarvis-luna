#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""사람이 직접 확인한 채널 데이터를 받아들인다.

왜 필요한가
  Amazon·Walmart·Google Trends·TikTok·Ulta·Sephora 는 공식 API 가 없거나
  봇 차단이 걸려 자동 수집이 안 된다. 대신 사람이 실제 페이지를 보고
  옮겨 적은 값은 진짜 데이터다. 그 경로를 정식으로 만든다.

투입 방법
  data/manual/ 폴더에 JSON 파일을 넣는다.
  파일명 규칙: <채널키>_<YYYY-MM-DD>.json
    예) ulta_2026-09-01.json, amazon_2026-09-01.json
  같은 채널에 파일이 여러 개면 날짜가 가장 최근인 것을 쓴다.

신뢰 등급
  trust="manual" 로 표시한다. 사람이 실제 화면을 보고 넣은 값이라
  LLM 추출보다 신뢰도가 높지만, 특정 시점 스냅샷이라 시간이 지나면 낡는다.
  그래서 captured_at 기준 경과일을 함께 기록하고 오래되면 경고한다.

원칙 (CLAUDE.md: 거짓말 데이터 금지)
  - source_url 과 captured_at 이 없는 파일은 거부한다. 출처 없는 값은 안 받는다.
  - 상품명과 가격이 없는 항목은 버린다.
  - 파일이 없으면 빈 결과를 남긴다. 채워 넣지 않는다.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "data" / "manual"
OUT = ROOT / "data" / "manual_channels.json"

# 파일명 앞부분 -> 대시보드 채널 키
CHANNEL_ALIAS = {
    "ulta": "ulta_beauty",
    "sephora": "sephora",
    "amazon": "amazon_best_sellers",
    "walmart": "walmart_beauty",
    "tiktok": "tiktok_shop_us",
    "trends": "google_trends_us",
    "google_trends": "google_trends_us",
}

STALE_DAYS = 30

# Gemini 출력이 조금씩 달라도 받아들이도록 여러 이름을 허용한다
FIELD = {
    "product": ("product", "name", "title", "product_name", "item"),
    "brand": ("brand", "brand_name", "vendor", "maker"),
    "price_usd": ("price_usd", "price", "sale_price", "amount", "usd"),
    "rating": ("rating", "stars", "score", "review_score"),
    "review_count": ("review_count", "reviews", "num_reviews", "review_cnt"),
    "rank": ("rank", "position", "no", "order"),
}


def pick(d: dict, key: str):
    for k in FIELD[key]:
        if k in d and d[k] not in (None, "", "-"):
            return d[k]
    return None


def to_num(v):
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"[\d,]+(?:\.\d+)?", str(v))
    return float(m.group(0).replace(",", "")) if m else None


def to_int(v):
    n = to_num(v)
    return int(n) if n is not None else None


def parse_file(path: Path) -> tuple[str, dict | None, str]:
    stem = path.stem.lower()
    key = None
    for alias, ch in CHANNEL_ALIAS.items():
        if stem.startswith(alias):
            key = ch
            break
    if not key:
        return "", None, f"파일명에서 채널을 못 알아봄. 앞부분을 {list(CHANNEL_ALIAS)} 중 하나로 지어주세요"

    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        return key, None, f"JSON 파싱 실패: {e}"

    # 배열만 있어도 되고, 메타를 감싼 객체여도 된다
    if isinstance(raw, list):
        items, meta = raw, {}
    elif isinstance(raw, dict):
        items = raw.get("products") or raw.get("items") or raw.get("data") or []
        meta = raw
    else:
        return key, None, "최상위가 배열도 객체도 아님"

    src = str(meta.get("source_url") or meta.get("url") or "").strip()
    cap = str(meta.get("captured_at") or meta.get("date") or "").strip()
    if not cap:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", path.stem)
        cap = m.group(1) if m else ""
    if not src:
        return key, None, "source_url 이 없습니다. 어느 페이지를 보고 적었는지 반드시 넣어야 합니다"
    if not cap:
        return key, None, "captured_at 이 없습니다. 파일명에 날짜를 넣거나 필드로 넣어주세요"

    rows = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(pick(it, "product") or "").strip()
        price = to_num(pick(it, "price_usd"))
        if len(name) < 3 or price is None or price <= 0:
            continue
        rows.append({
            "rank": to_int(pick(it, "rank")) or (len(rows) + 1),
            "product": name[:200],
            "brand": str(pick(it, "brand") or "").strip()[:80],
            "price_usd": round(price, 2),
            "rating": to_num(pick(it, "rating")),
            "review_count": to_int(pick(it, "review_count")),
            "source_url": src,
            "captured_at": cap,
            "extraction_method": "manual_screenshot",
        })
    if not rows:
        return key, None, "상품명과 가격을 함께 가진 항목이 없습니다"

    rows.sort(key=lambda x: x["rank"])
    try:
        age = (datetime.now(timezone.utc).date()
               - datetime.strptime(cap[:10], "%Y-%m-%d").date()).days
    except ValueError:
        age = None

    return key, {
        "count": len(rows),
        "source_url": src,
        "captured_at": cap,
        "age_days": age,
        "stale": bool(age is not None and age > STALE_DAYS),
        "file": path.name,
        "products": rows,
    }, ""


def main() -> int:
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    # _ 로 시작하는 파일은 템플릿·메모용이라 건너뛴다
    files = sorted(f for f in SRC_DIR.glob("*.json") if not f.name.startswith("_"))

    channels, errors, total = {}, [], 0
    for f in files:
        key, data, err = parse_file(f)
        if err:
            errors.append({"file": f.name, "error": err})
            print(f"  [건너뜀] {f.name}: {err}")
            continue
        # 같은 채널이면 더 최근 것을 쓴다
        prev = channels.get(key)
        if prev and (prev.get("captured_at") or "") >= (data.get("captured_at") or ""):
            print(f"  [무시] {f.name}: 더 최근 파일 {prev['file']} 사용")
            continue
        channels[key] = data
        print(f"  [적용] {f.name} -> {key} {data['count']}건 "
              f"({data['captured_at']}, {data['age_days']}일 전)"
              + ("  ※오래됨" if data["stale"] else ""))

    total = sum(c["count"] for c in channels.values())

    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/ingest_manual_channels.py",
        "input_dir": "data/manual/",
        "trust_note": ("사람이 실제 페이지를 보고 넣은 값이다. 자동 수집이 불가능한 "
                       "채널을 채우는 정식 경로다. 특정 시점 스냅샷이라 "
                       f"{STALE_DAYS}일이 지나면 오래된 데이터로 표시한다."),
        "stale_days": STALE_DAYS,
        "files_seen": len(files),
        "total": total,
        "errors": errors,
        "channels": channels,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n파일 {len(files)}개 중 {len(channels)}개 채널 · 총 {total}건 "
          f"-> {OUT.relative_to(ROOT)}")
    if errors:
        print(f"오류 {len(errors)}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
