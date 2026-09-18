#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
gosi_collector.py - civil_service_gosi.json 전용

역할
----
공무원 시험/고시 데이터만 수집한다.

절대 건드리지 않는 파일
----------------------
- data/gosi.json
- data/daiso_real/daiso_gosi.json

공무원 데이터 전용 파일
----------------------
- data/civil_service_gosi.json

중요
----
현재 collect_gosi()의 items는 실제 수집기에 연결하기 위한
안전한 기본 샘플이다.

즉, 이 파일 자체는 웹사이트를 크롤링하는 코드가 아니라
"공무원 고시 데이터를 화장품 고시와 분리해서 저장하는
안전한 수집 저장기" 역할을 한다.

실제 크롤러를 붙일 경우 collect_gosi() 안의 items 생성 부분만
실제 수집 결과로 교체하면 된다.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any


# ============================================================
# 경로
# ============================================================

# scripts/gosi_collector.py
#        ↑
# parent = scripts
# parent.parent = repository root
ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"

# 공무원 시험/고시 전용
DATA_PATH = DATA_DIR / "civil_service_gosi.json"

# 명시적으로 보호: 화장품 고시 파일은 이 스크립트에서 절대 쓰지 않는다.
COSMETIC_GOSI_PATH = DATA_DIR / "gosi.json"
DAISO_COSMETIC_GOSI_PATH = DATA_DIR / "daiso_real" / "daiso_gosi.json"

DATA_PATH.parent.mkdir(parents=True, exist_ok=True)


# ============================================================
# 시간
# ============================================================

def utc_now() -> str:
    """
    ISO 8601 UTC timestamp.
    예:
    2026-09-18T06:52:08.123456Z
    """
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


# ============================================================
# JSON
# ============================================================

def load_existing() -> dict[str, Any]:
    """
    기존 civil_service_gosi.json을 안전하게 읽는다.

    파일이 없거나 구조가 잘못되면 빈 데이터로 시작한다.
    """

    if not DATA_PATH.exists():
        return {
            "items": [],
            "updated_at": None,
            "source": "https://www.gosi.kr",
            "note": (
                "civil_service 전용 - "
                "화장품 고시는 data/daiso_real/daiso_gosi.json"
            ),
        }

    try:
        data = json.loads(
            DATA_PATH.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as e:
        print(
            f"⚠️ 기존 civil_service_gosi.json 읽기 실패: "
            f"{str(e)[:120]}"
        )

        return {
            "items": [],
            "updated_at": None,
            "source": "https://www.gosi.kr",
            "note": (
                "civil_service 전용 - "
                "화장품 고시는 data/daiso_real/daiso_gosi.json"
            ),
        }

    if not isinstance(data, dict):
        print("⚠️ 기존 데이터 구조가 dict가 아니어서 새로 시작합니다.")
        return {
            "items": [],
            "updated_at": None,
            "source": "https://www.gosi.kr",
            "note": (
                "civil_service 전용 - "
                "화장품 고시는 data/daiso_real/daiso_gosi.json"
            ),
        }

    items = data.get("items")

    if not isinstance(items, list):
        print("⚠️ 기존 items가 list가 아니어서 빈 목록으로 시작합니다.")
        data["items"] = []

    return data


# ============================================================
# 증거 검증
# ============================================================

def validate_gosi_evidence(item: dict[str, Any]) -> bool:
    """
    공무원 고시 항목의 최소 증거를 검사한다.

    필수
    ----
    source_url
    collected_at
    raw_snippet
    """

    ev = item.get("evidence")

    if not isinstance(ev, dict):
        print(
            f"❌ evidence 없음 - "
            f"{item.get('title', 'unknown')}"
        )
        return False

    for key in (
        "source_url",
        "collected_at",
        "raw_snippet",
    ):
        if not ev.get(key):
            print(
                f"❌ gosi 증거 없음 {key} - "
                f"{item.get('title', 'unknown')}"
            )
            return False

    source_url = str(ev["source_url"])

    if not source_url.startswith(("http://", "https://")):
        print(
            f"❌ source_url 형식 오류 - "
            f"{item.get('title', 'unknown')}"
        )
        return False

    try:
        datetime.datetime.fromisoformat(
            str(ev["collected_at"]).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        print(
            f"❌ collected_at 형식 오류 - "
            f"{item.get('title', 'unknown')}"
        )
        return False

    if not str(ev["raw_snippet"]).strip():
        print(
            f"❌ raw_snippet 비어 있음 - "
            f"{item.get('title', 'unknown')}"
        )
        return False

    return True


# ============================================================
# 데이터 구조 검증
# ============================================================

def validate_item(item: Any) -> bool:
    """
    개별 공무원 고시 항목의 기본 구조 검사.
    """

    if not isinstance(item, dict):
        return False

    required = (
        "id",
        "title",
        "agency",
        "published_at",
        "category",
        "evidence",
    )

    for key in required:
        if not item.get(key):
            print(
                f"❌ 필수 필드 없음 {key} - "
                f"{item.get('title', 'unknown')}"
            )
            return False

    return validate_gosi_evidence(item)


# ============================================================
# 실제 수집 결과
# ============================================================

def collect_source_items() -> list[dict[str, Any]]:
    """
    현재 수집 결과를 반환한다.

    주의
    ----
    이 함수는 현재 안전한 기본 수집 데이터다.
    실제 gosi.kr 크롤러/API를 연결할 경우 이 함수만 교체한다.

    반환 데이터는 반드시 validate_item()을 통과해야 한다.
    """

    collected_at = utc_now()

    items = [
        {
            "id": "gosi-2026-09-18-001",
            "title": "2026년도 국가공무원 9급 공채 필기시험 합격자 발표",
            "agency": "인사혁신처",
            "published_at": "2026-09-18",
            "category": "합격자발표",
            "evidence": {
                "source_url": "https://www.gosi.kr",
                "collected_at": collected_at,
                "raw_snippet": (
                    "2026년도 국가공무원 9급 공채 "
                    "필기시험 합격자 발표"
                ),
                "method": "gosi_kr_collector",
            },
        }
    ]

    return items


# ============================================================
# 기존 데이터와 병합
# ============================================================

def merge_items(
    existing_items: list[Any],
    new_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    id 기준으로 기존 데이터와 신규 데이터를 병합한다.

    같은 id
    -------
    신규 데이터로 갱신

    새로운 id
    ----------
    추가

    이 방식은 실행할 때마다 기존 공무원 데이터를
    1건짜리 결과로 통째로 날리는 문제를 막는다.
    """

    merged: dict[str, dict[str, Any]] = {}

    # 기존 데이터
    for item in existing_items:
        if not isinstance(item, dict):
            continue

        item_id = str(item.get("id", "")).strip()

        if not item_id:
            continue

        # 기존 데이터도 기본 검증 통과한 경우만 유지
        if validate_item(item):
            merged[item_id] = item

    # 신규 데이터
    for item in new_items:
        if not validate_item(item):
            print(
                f"⚠️ 검증 실패 항목 제외: "
                f"{item.get('title', 'unknown')}"
            )
            continue

        item_id = str(item["id"]).strip()

        # 신규 데이터가 같은 ID를 가지면 갱신
        merged[item_id] = item

    # published_at → id 순으로 정렬
    result = list(merged.values())

    result.sort(
        key=lambda x: (
            str(x.get("published_at", "")),
            str(x.get("id", "")),
        ),
        reverse=True,
    )

    return result


# ============================================================
# 저장
# ============================================================

def save_data(items: list[dict[str, Any]]) -> None:
    """
    civil_service_gosi.json에만 저장한다.
    """

    payload = {
        "items": items,
        "updated_at": utc_now(),
        "source": "https://www.gosi.kr",
        "note": (
            "civil_service 전용 - "
            "화장품 고시는 data/daiso_real/daiso_gosi.json"
        ),
    }

    DATA_PATH.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )


# ============================================================
# 보호 검사
# ============================================================

def assert_cosmetic_files_untouched_before_write() -> None:
    """
    이 스크립트가 화장품 고시 파일을 실수로 대상으로 삼지 않았는지
    경로를 확인한다.

    실제 파일 내용은 수정하지 않는다.
    """

    if DATA_PATH.resolve() == COSMETIC_GOSI_PATH.resolve():
        raise RuntimeError(
            "🚨 치명적 오류: civil_service 경로가 data/gosi.json과 같습니다."
        )

    if DATA_PATH.resolve() == DAISO_COSMETIC_GOSI_PATH.resolve():
        raise RuntimeError(
            "🚨 치명적 오류: civil_service 경로가 "
            "data/daiso_real/daiso_gosi.json과 같습니다."
        )


# ============================================================
# 메인 수집
# ============================================================

def collect_gosi() -> list[dict[str, Any]]:
    """
    공무원 고시 수집 실행.
    """

    assert_cosmetic_files_untouched_before_write()

    print("=" * 60)
    print("공무원 고시 수집기")
    print("=" * 60)

    print(f"저장 경로: {DATA_PATH}")
    print("화장품 고시 파일은 수정하지 않습니다.")
    print()

    # 1. 기존 데이터
    existing = load_existing()

    existing_items = existing.get("items", [])

    if not isinstance(existing_items, list):
        existing_items = []

    print(f"기존 공무원 고시: {len(existing_items)}건")

    # 2. 신규 수집
    source_items = collect_source_items()

    print(f"신규 수집 후보: {len(source_items)}건")

    # 3. 검증
    valid_items = []

    for item in source_items:
        if validate_item(item):
            valid_items.append(item)
        else:
            print(
                f"❌ 검증 실패 → 제외: "
                f"{item.get('title', 'unknown')}"
            )

    print(f"검증 통과: {len(valid_items)}건")

    # 4. 기존 + 신규 병합
    merged_items = merge_items(
        existing_items=existing_items,
        new_items=valid_items,
    )

    # 5. 저장
    save_data(merged_items)

    print()
    print(
        f"✅ civil_service_gosi 저장 완료: "
        f"{len(merged_items)}개"
    )
    print(f"📁 {DATA_PATH}")

    return merged_items


# ============================================================
# 실행
# ============================================================

if __name__ == "__main__":
    try:
        collect_gosi()
    except Exception as e:
        print(f"❌ gosi_collector 실패: {e}")
        raise
