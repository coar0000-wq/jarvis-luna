#!/usr/bin/env python3
"""상품 발굴 누적 데이터를 대시보드용 product_team.json으로 변환한다."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CUMULATIVE_PATH = DATA_DIR / "cumulative_products.json"
SCHEDULER_LOG_PATH = DATA_DIR / "scheduler_log.json"
PRODUCT_TEAM_PATH = DATA_DIR / "product_team.json"

PLATFORM_LABELS = {
    "daiso": "다이소",
    "oliveyoung": "올리브영",
    "naver": "네이버 쇼핑",
    "walmart": "월마트",
    "amazon": "아마존",
}


def read_json(path: Path, default: dict) -> dict:
    try:
        with path.open(encoding="utf-8-sig") as file:
            value = json.load(file)
        return value if isinstance(value, dict) else default
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def calculate_total(data: dict) -> int:
    if isinstance(data.get("cumulative_total"), (int, float)):
        return int(data["cumulative_total"])
    baseline = int(data.get("baseline", 0) or 0)
    sources = data.get("sources", {})
    return baseline + sum(int(value or 0) for value in sources.values())


def calculate_daily_new(log: dict) -> int:
    today = datetime.now(timezone.utc).date()
    total = 0
    for event in log.get("events", []):
        try:
            timestamp = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        if timestamp.date() != today:
            continue
        details = str(event.get("details", ""))
        # 로그 형식: "... 상품 3개 발굴 ..."
        marker = " 상품 "
        if marker in details and "개 발굴" in details:
            try:
                total += int(details.split(marker, 1)[1].split("개 발굴", 1)[0])
            except (ValueError, IndexError):
                pass
    return total


def main() -> None:
    cumulative = read_json(CUMULATIVE_PATH, {})
    scheduler_log = read_json(SCHEDULER_LOG_PATH, {})
    sources = cumulative.get("sources", {})
    total = calculate_total(cumulative)
    daily_new = calculate_daily_new(scheduler_log)

    if sources:
        top_source = max(sources, key=lambda key: int(sources.get(key, 0) or 0))
        top_category = f"{PLATFORM_LABELS.get(top_source, top_source)} 뷰티 & 스킨케어"
    else:
        top_category = "다이소 뷰티 & 스킨케어"

    payload = {
        "active_items": total,
        "daily_new": daily_new,
        "top_category": top_category,
        "status": "5개 플랫폼 뷰티·스킨케어 발굴 중",
        "source": "data/cumulative_products.json",
        "sources": {key: int(value or 0) for key, value in sources.items()},
        "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    with PRODUCT_TEAM_PATH.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")

    print(f"상품 발굴팀 데이터 갱신 완료: {total}개 (오늘 신규 {daily_new}개)")


if __name__ == "__main__":
    main()
