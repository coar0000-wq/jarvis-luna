#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
guard_gosi.py v5 - 화장품 고시 보호 최종본

목적
----
1. data/gosi.json 이 공무원 시험 데이터로 덮어써졌는지 사전 검사
2. data/daiso_real/daiso_gosi.json 의 화장품 고시 상태 검사
3. missing 상태는 가능하면 Git 기록에서 복구
4. 1~4건처럼 비정상적으로 축소된 경우에는 복구 실패 시 중단
5. preflight.py 가 사용할 수 있도록 judge(text) 제공

경로 역할
---------
- data/gosi.json
    화장품 고시 canonical 데이터
    preflight.py 에서 "공무원 시험 데이터가 섞이지 않았는지" 검사

- data/daiso_real/daiso_gosi.json
    실수집/비전 기반 다이소 화장품 고시 데이터
    root collector 가 보호하는 대상

- data/civil_service_gosi.json
    공무원 시험 공고 전용
"""

import json
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 화장품 고시 canonical
CANONICAL_GOSI = ROOT / "data" / "gosi.json"

# 실제 다이소 화장품 고시 보호 대상
COSMETIC_GOSI = ROOT / "data" / "daiso_real" / "daiso_gosi.json"

# 공무원 시험 공고 전용
CIVIL_GOSI = ROOT / "data" / "civil_service_gosi.json"

GUARD_LOG = ROOT / "data" / "guard_gosi_log.json"

# 최소 정상 상품 수
MIN_GOOD_ITEMS = 5


# ──────────────────────────────────────────────────────────────
# 공통 JSON
# ──────────────────────────────────────────────────────────────

def load_json_safe(path: Path):
    """JSON 파일을 안전하게 읽는다."""
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_json_text(text: str):
    """문자열 JSON을 안전하게 파싱한다."""
    try:
        return json.loads(text)
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────
# preflight.py 용 judge()
# ──────────────────────────────────────────────────────────────

def judge(text: str):
    """
    preflight.py 가 data/gosi.json 이 진짜 화장품 고시인지 판정할 때 사용.

    반환:
        (True, 설명)
        (False, 실패 사유)

    중요한 구분
    -----------
    화장품 고시:
        {
          "items": {
            "1048583": {...},
            "1045146": {...}
          }
        }

    공무원 시험:
        {
          "items": [
            {...}
          ]
        }

    즉, items가 dict 형태인지가 매우 중요한 1차 구분점이다.
    """
    data = parse_json_text(text)

    if data is None:
        return False, "JSON 파싱 실패"

    if not isinstance(data, dict):
        return False, f"최상위 구조가 dict가 아님: {type(data).__name__}"

    items = data.get("items")

    if items is None:
        return False, "items 필드가 없음"

    # 공무원 시험 고시 데이터는 items가 list 형태다.
    if isinstance(items, list):
        return False, "items가 list — 공무원 시험/비화장품 구조로 판단"

    # 화장품 고시는 상품번호 -> 상품정보 dict 형태다.
    if not isinstance(items, dict):
        return False, f"items 구조가 dict가 아님: {type(items).__name__}"

    if len(items) < MIN_GOOD_ITEMS:
        return False, f"화장품 상품 {len(items)}건뿐임 (최소 {MIN_GOOD_ITEMS}건)"

    # 상품번호/상품정보 구조 확인
    valid_product_keys = 0
    valid_product_records = 0

    for key, item in items.items():
        key_text = str(key).strip()

        # 다이소 상품번호는 숫자 문자열 형태
        if key_text.isdigit():
            valid_product_keys += 1

        if isinstance(item, dict):
            # 화장품 고시에서 실제로 사용되는 대표 필드
            markers = 0

            for field in (
                "name",
                "ingredients",
                "volume",
                "maker",
                "origin",
                "warnings",
                "functional",
                "gosi_image",
                "detail_images",
            ):
                value = item.get(field)
                if value not in (None, "", [], {}):
                    markers += 1

            # 상품 레코드로 볼 만한 최소한의 구조
            if markers >= 2:
                valid_product_records += 1

    if valid_product_keys < MIN_GOOD_ITEMS:
        return (
            False,
            f"상품번호 형태 데이터가 {valid_product_keys}건뿐임"
        )

    if valid_product_records < MIN_GOOD_ITEMS:
        return (
            False,
            f"화장품 상품 레코드가 {valid_product_records}건뿐임"
        )

    return (
        True,
        f"화장품 고시 정상 — 상품 {len(items)}건"
    )


# ──────────────────────────────────────────────────────────────
# 다이소 실고시 검사
# ──────────────────────────────────────────────────────────────

def check_cosmetic_gosi():
    """
    data/daiso_real/daiso_gosi.json 상태를 검사.

    반환:
        (is_ok, status, count)
    """

    data = load_json_safe(COSMETIC_GOSI)

    if data is None:
        print(f"⚠️ 화장품 고시 없음: {COSMETIC_GOSI}")
        return False, "missing", 0

    if isinstance(data, dict):
        items = data.get("items", data)

        if isinstance(items, dict):
            count = len(items)
        elif isinstance(items, list):
            count = len(items)
        else:
            count = 0

    elif isinstance(data, list):
        count = len(data)

    else:
        count = 0

    if count < MIN_GOOD_ITEMS:
        print(
            f"❌ 화장품 고시 손상 감지: "
            f"{count}건 (기대 {MIN_GOOD_ITEMS}건+)"
        )
        return False, f"damaged_count_{count}", count

    print(f"✅ 화장품 고시 정상: {count}건")
    return True, f"ok_{count}", count


# ──────────────────────────────────────────────────────────────
# Git 마지막 정상 버전 복구
# ──────────────────────────────────────────────────────────────

def restore_from_last_good():
    """
    Git history에서 마지막 정상 화장품 고시를 찾아 복구.
    """

    relative_path = COSMETIC_GOSI.relative_to(ROOT).as_posix()

    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--oneline",
                "--follow",
                "--",
                relative_path,
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )

        if result.returncode != 0:
            print(f"❌ git log 실패: {result.stderr.strip()[:200]}")
            return False

        commits = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip()
        ][:20]

        if not commits:
            print("❌ 복구할 Git 커밋 기록이 없음")
            return False

        for commit_line in commits:
            parts = commit_line.split()

            if not parts:
                continue

            commit_hash = parts[0]

            show_result = subprocess.run(
                [
                    "git",
                    "show",
                    f"{commit_hash}:{relative_path}",
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )

            if show_result.returncode != 0:
                continue

            raw = show_result.stdout.strip()

            if not raw:
                continue

            data = parse_json_text(raw)

            if data is None:
                continue

            # 구조 검사
            if isinstance(data, dict):
                items = data.get("items", data)
            elif isinstance(data, list):
                items = data
            else:
                continue

            if not isinstance(items, (dict, list)):
                continue

            count = len(items)

            if count < MIN_GOOD_ITEMS:
                continue

            # 정상 버전 발견
            COSMETIC_GOSI.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            # 원본 내용을 최대한 그대로 복구
            COSMETIC_GOSI.write_text(
                raw + "\n",
                encoding="utf-8"
            )

            print(
                f"✅ 화장품 고시 복구 완료: "
                f"{commit_hash} 에서 {count}건 복원"
            )

            return True

        print("❌ 복구할 정상 커밋을 찾지 못함")
        return False

    except Exception as e:
        print(f"❌ 복구 실패: {e}")
        return False


# ──────────────────────────────────────────────────────────────
# 시작 상태 기록
# ──────────────────────────────────────────────────────────────

def write_guard_log(status, count, is_ok):
    """가드 실행 결과를 JSON으로 저장."""

    log = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "cosmetic_gosi_path": str(
            COSMETIC_GOSI.relative_to(ROOT)
        ),
        "status": status,
        "count": count,
        "is_ok": is_ok,
    }

    try:
        GUARD_LOG.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        GUARD_LOG.write_text(
            json.dumps(
                log,
                indent=2,
                ensure_ascii=False
            ),
            encoding="utf-8"
        )

        print(
            f"📝 시작 상태 기록: "
            f"{GUARD_LOG} - {status} ({count}건)"
        )

    except Exception as e:
        print(f"⚠️ 로그 기록 실패: {e}")


# ──────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────

def main():
    is_restore = "--restore" in sys.argv

    # ----------------------------------------------------------
    # 일반 실행
    # ----------------------------------------------------------
    if not is_restore:

        is_ok, status, count = check_cosmetic_gosi()

        write_guard_log(
            status=status,
            count=count,
            is_ok=is_ok,
        )

        return 0

    # ----------------------------------------------------------
    # --restore 실행
    # ----------------------------------------------------------

    is_ok, status, count = check_cosmetic_gosi()

    # 정상
    if is_ok:
        print(
            f"✅ 화장품 고시 보호: "
            f"정상 {count}건 - 커밋 진행"
        )
        return 0

    print(
        f"🚨 화장품 고시 상태: "
        f"{status} ({count}건)"
    )

    # ----------------------------------------------------------
    # missing
    # ----------------------------------------------------------

    if status == "missing":

        print(
            "⚠️ 화장품 고시 파일 없음 - "
            "Git 복구 시도"
        )

        if restore_from_last_good():

            print("✅ 복구 성공 - 커밋 진행")
            return 0

        print(
            "⚠️ 복구할 커밋 없음 - "
            "inci_converter가 새로 생성할 수 있으므로 진행"
        )

        print(
            "::warning::"
            "화장품 고시 파일이 없어 새로 생성됩니다. "
            "다음 수집/비전 단계에서 생성될 예정입니다."
        )

        # missing은 워크플로를 막지 않는다.
        return 0

    # ----------------------------------------------------------
    # damaged_count
    # ----------------------------------------------------------

    print(
        f"🚨 화장품 고시 손상 감지: "
        f"{count}건 - 복구 시도"
    )

    if restore_from_last_good():

        print("✅ 복구 성공 - 커밋 진행")
        return 0

    # 1~4건처럼 비정상적으로 축소된 상태에서
    # 복구 실패하면 망가진 고시를 발행하지 않는다.
    print(
        "❌ 복구 실패 - "
        "손상된 화장품 고시를 그대로 발행하지 않음"
    )

    print(
        "::error::"
        f"화장품 고시 손상 상태({count}건)이며 "
        "정상 Git 버전 복구에도 실패했습니다."
    )

    return 1


if __name__ == "__main__":
    sys.exit(main())
