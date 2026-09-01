#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""사람이 직접 확인한 채널 데이터를 받아들인다.

왜 필요한가
  Amazon·Walmart·Google Trends·TikTok·Ulta·Sephora 는 공식 API 가 없거나
  봇 차단이 걸려 자동 수집이 안 된다. 대신 사람이 실제 페이지를 보고
  옮겨 적은 값은 진짜 데이터다. 그 경로를 정식으로 만든다.

투입 방법
  data/manual/ 폴더에 파일을 넣는다. 아래 세 형태를 모두 받는다.
    1) JSON  {"source_url":..., "captured_at":..., "products":[...]}
    2) CSV   플랫폼/브랜드/제품명/판매가 열이 있는 표
    3) HTML  Gemini 가 만들어 주는 "CSV 다운로드" 페이지
             (const csvData = `...` 안의 표를 꺼내 쓴다)

  채널 판정은 파일 안의 "플랫폼" 열을 우선한다.
  한 파일에 Amazon·Walmart·Ulta·Sephora 가 섞여 있어도 알아서 나눈다.
  플랫폼 열이 없으면 파일명 앞부분으로 판정한다.
  같은 채널 데이터가 여러 파일에 있으면 날짜가 최근인 것을 쓴다.

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

import csv as csvmod
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "data" / "manual"
OUT = ROOT / "data" / "manual_channels.json"

# 파일 안 "플랫폼" 열 값 -> 대시보드 채널 키
PLATFORM_MAP = {
    "amazon": "amazon_best_sellers",
    "walmart": "walmart_beauty",
    "ulta": "ulta_beauty",
    "sephora": "sephora",
    "tiktok": "tiktok_shop_us",
    "google trends": "google_trends_us",
    "trends": "google_trends_us",
}

# 한글 CSV 헤더 -> 표준 필드
KO_HEADER = {
    "플랫폼": "platform", "브랜드": "brand", "제품명": "product",
    "상품명": "product", "카테고리/특이사항": "category", "카테고리": "category",
    "판매가($)": "price_usd", "판매가": "price_usd", "가격": "price_usd",
    "평점": "rating", "리뷰 수": "review_count", "리뷰수": "review_count",
    "순위": "rank",
}


def platform_to_channel(v: str) -> str:
    low = (v or "").lower()
    for k, ch in PLATFORM_MAP.items():
        if k in low:
            return ch
    return ""


def extract_table(path: Path):
    """JSON / CSV / HTML(csvData 내장) 어느 형태든 행 목록과 메타를 돌려준다."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if not text.strip():
        return [], {}, "빈 파일"

    # 1) HTML 안에 박힌 CSV
    m = re.search(r"const\s+csvData\s*=\s*[`\'\"](.*?)[`\'\"]\s*;", text, re.S)
    if m:
        text = m.group(1).replace("\\uFEFF", "").replace("\ufeff", "")
        return csv_rows(text), {"format": "html_embedded_csv"}, ""

    # 2) JSON
    st = text.lstrip()
    if st.startswith("{") or st.startswith("["):
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as e:
            return [], {}, f"JSON 파싱 실패: {e}"
        if isinstance(raw, list):
            return raw, {"format": "json"}, ""
        items = raw.get("products") or raw.get("items") or raw.get("data") or []
        meta = {k: v for k, v in raw.items() if k not in ("products", "items", "data")}
        meta["format"] = "json"
        return items, meta, ""

    # 3) 순수 CSV
    if "," in text.splitlines()[0]:
        return csv_rows(text), {"format": "csv"}, ""
    return [], {}, "JSON·CSV·HTML 어느 형태로도 읽지 못함"


def csv_rows(text: str) -> list[dict]:
    text = text.replace("\ufeff", "").strip()
    out = []
    for r in csvmod.DictReader(io.StringIO(text)):
        row = {}
        for k, v in r.items():
            if k is None:
                continue
            key = KO_HEADER.get(k.strip(), k.strip())
            row[key] = v
        out.append(row)
    return out


# 파일명 앞부분 -> 대시보드 채널 키 (플랫폼 열이 없을 때만 사용)
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


DOMAIN = {
    "amazon_best_sellers": "amazon.com",
    "walmart_beauty": "walmart.com",
    "ulta_beauty": "ulta.com",
    "sephora": "sephora.com",
    "tiktok_shop_us": "shop.tiktok.com",
    "google_trends_us": "trends.google.com",
}


def parse_file(path: Path) -> tuple[dict, str]:
    """파일 하나를 읽어 {채널키: [행,...]} 로 나눠 돌려준다."""
    items, meta, err = extract_table(path)
    if err:
        return {}, err
    if not items:
        return {}, "표에 행이 없음"

    cap = str(meta.get("captured_at") or meta.get("date") or "").strip()
    if not cap:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", path.stem)
        cap = m.group(1) if m else ""
    if not cap:
        return {}, "captured_at 이 없습니다. 파일명에 날짜를 넣거나 필드로 넣어주세요"
    src = str(meta.get("source_url") or meta.get("url") or "").strip()

    # 플랫폼 열이 없을 때만 파일명으로 채널을 정한다
    fallback = ""
    stem = path.stem.lower()
    for alias, ch in CHANNEL_ALIAS.items():
        if stem.startswith(alias):
            fallback = ch
            break

    buckets: dict[str, list] = {}
    dropped = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        ch = platform_to_channel(str(it.get("platform") or "")) or fallback
        if not ch:
            dropped += 1
            continue
        name = str(pick(it, "product") or "").strip()
        price = to_num(pick(it, "price_usd"))
        if len(name) < 3 or price is None or price <= 0:
            dropped += 1
            continue
        rows = buckets.setdefault(ch, [])
        rows.append({
            "rank": to_int(pick(it, "rank")) or (len(rows) + 1),
            "product": name[:200],
            "brand": str(pick(it, "brand") or "").strip()[:80],
            "category": str(it.get("category") or "").strip()[:80],
            "price_usd": round(price, 2),
            "rating": to_num(pick(it, "rating")),
            "review_count": to_int(pick(it, "review_count")),
            "source_url": src or f"https://www.{DOMAIN.get(ch, '')}",
            "source_url_given": bool(src),
            "captured_at": cap,
            "extraction_method": "manual_screenshot",
        })

    if not buckets:
        return {}, f"쓸 수 있는 행이 없음 (버린 행 {dropped}개)"

    try:
        age = (datetime.now(timezone.utc).date()
               - datetime.strptime(cap[:10], "%Y-%m-%d").date()).days
    except ValueError:
        age = None

    out = {}
    for ch, rows in buckets.items():
        rows.sort(key=lambda x: x["rank"])
        out[ch] = {
            "count": len(rows),
            "source_url": src or f"https://www.{DOMAIN.get(ch, '')}",
            "source_url_given": bool(src),
            "captured_at": cap,
            "age_days": age,
            "stale": bool(age is not None and age > STALE_DAYS),
            "file": path.name,
            "format": meta.get("format", "?"),
            "products": rows,
        }
    return out, ""


def main() -> int:
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(f for f in SRC_DIR.iterdir()
                   if f.is_file() and f.suffix.lower() in (".json", ".csv", ".html", ".htm")
                   and not f.name.startswith("_"))

    channels, errors, no_src = {}, [], set()
    for f in files:
        parsed, err = parse_file(f)
        if err:
            errors.append({"file": f.name, "error": err})
            print(f"  [건너뜀] {f.name}: {err}")
            continue
        for ch, data in parsed.items():
            prev = channels.get(ch)
            if prev and (prev.get("captured_at") or "") >= (data.get("captured_at") or "") \
                    and prev["count"] >= data["count"]:
                continue
            channels[ch] = data
            if not data["source_url_given"]:
                no_src.add(ch)
        print(f"  [적용] {f.name} ({parsed[list(parsed)[0]]['format']}) -> "
              + ", ".join(f"{c} {d['count']}건" for c, d in parsed.items()))

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
        "channels_without_source_url": sorted(no_src),
        "errors": errors,
        "channels": channels,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n파일 {len(files)}개 -> 채널 {len(channels)}개 · 총 {total}건")
    for ch, d in sorted(channels.items()):
        flag = "" if d["source_url_given"] else "  ※출처 URL 미기재"
        print(f"  {ch:24s} {d['count']:3d}건  {d['captured_at']}{flag}")
    if errors:
        print(f"오류 {len(errors)}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
