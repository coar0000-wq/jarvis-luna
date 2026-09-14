#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
JARVIS LUNA - Health Check
자동화 시스템의 데이터 / 스크립트 / 워크플로우 상태를 검사합니다.

규칙:
- 실제 파일과 실제 JSON만 검사
- 존재하지 않는 작업을 성공으로 표시하지 않음
- JSON timestamp의 timezone 차이로 실패하지 않음
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


REQUIRED_SCRIPTS = [
    "scripts/collect_moe_papers.py",
    "scripts/youtube_moe_analysis.py",
    "scripts/youtube_dropshipping_analysis.py",
    "scripts/google_search_data_collection.py",
    "scripts/moe_neural_network.py",
    "scripts/moe_training.py",
    "scripts/auto_recovery.py",
]

REQUIRED_WORKFLOWS = [
    ".github/workflows/jarvis_final_automation.yml",
    ".github/workflows/jarvis_health_monitor.yml",
]


def parse_timestamp(value):
    """ISO timestamp를 timezone-aware datetime으로 변환"""
    if not value:
        return None

    value = str(value).strip()

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if dt.tzinfo is None:
            # 기존 JSON이 timezone 없이 저장된 경우 UTC로 간주
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except (ValueError, TypeError):
        return None


def check_jarvis_health():
    print("=" * 70)
    print("🏥 JARVIS LUNA HEALTH CHECK")
    print("=" * 70)

    now = datetime.now(timezone.utc)

    print(f"⏰ 현재 UTC: {now.isoformat()}")
    print()

    issues = []
    warnings = []

    # ============================================================
    # 1. 데이터 디렉토리
    # ============================================================

    print("1️⃣ 데이터 디렉토리 확인")

    data_dir = ROOT / "data"

    if data_dir.exists():
        print("   ✅ data/ 존재")
    else:
        issues.append("data/ 디렉토리 없음")
        print("   ❌ data/ 없음")

    # ============================================================
    # 2. 작업 로그
    # ============================================================

    print("\n2️⃣ JARVIS 작업 로그 확인")

    log_file = ROOT / "data" / "jarvis_work_detailed_log.json"

    if not log_file.exists():

        issues.append("jarvis_work_detailed_log.json 파일 없음")

        print("   ❌ 작업 로그 없음")

    else:

        try:

            with open(log_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            print("   ✅ JSON 정상")

            timestamp = data.get("timestamp")

            file_time = parse_timestamp(timestamp)

            if file_time is None:

                issues.append("timestamp 형식 오류")

                print("   ❌ timestamp 오류")

            else:

                age_minutes = (
                    now - file_time
                ).total_seconds() / 60

                print(
                    f"   📅 마지막 업데이트: "
                    f"{age_minutes:.1f}분 전"
                )

                if age_minutes > 60:

                    warnings.append(
                        f"작업 로그가 {age_minutes:.0f}분 동안 업데이트되지 않음"
                    )

                    print("   ⚠️ 로그 업데이트 지연")

                else:

                    print("   ✅ 로그 최신")

            completed = data.get("completed_today", [])

            if isinstance(completed, list):

                print(
                    f"   ✅ 오늘 완료 작업: "
                    f"{len(completed)}개"
                )

            else:

                issues.append(
                    "completed_today가 배열이 아님"
                )

                print(
                    "   ❌ completed_today 형식 오류"
                )

            daily = data.get("daily_summary", {})

            if daily:

                print(
                    f"   📊 일일 완료: "
                    f"{daily.get('completed', 0)}"
                )

                print(
                    f"   📊 진행중: "
                    f"{daily.get('in_progress', 0)}"
                )

                print(
                    f"   📊 대기: "
                    f"{daily.get('pending', 0)}"
                )

        except json.JSONDecodeError as e:

            issues.append(
                f"JSON 손상: {e}"
            )

            print("   ❌ JSON 손상")

        except Exception as e:

            issues.append(
                f"작업 로그 읽기 오류: {e}"
            )

            print(f"   ❌ {e}")

    # ============================================================
    # 3. 필수 스크립트
    # ============================================================

    print("\n3️⃣ 필수 Python 스크립트 확인")

    missing_scripts = []

    for script in REQUIRED_SCRIPTS:

        path = ROOT / script

        if path.exists():

            print(f"   ✅ {script}")

        else:

            missing_scripts.append(script)

            print(f"   ❌ {script}")

    if missing_scripts:

        issues.append(
            f"필수 스크립트 {len(missing_scripts)}개 누락"
        )

    # ============================================================
    # 4. GitHub Actions
    # ============================================================

    print("\n4️⃣ GitHub Actions 워크플로우 확인")

    missing_workflows = []

    for workflow in REQUIRED_WORKFLOWS:

        path = ROOT / workflow

        if path.exists():

            print(f"   ✅ {workflow}")

        else:

            missing_workflows.append(workflow)

            print(f"   ❌ {workflow}")

    if missing_workflows:

        issues.append(
            f"워크플로우 {len(missing_workflows)}개 누락"
        )

    # ============================================================
    # 5. 핵심 데이터 파일
    # ============================================================

    print("\n5️⃣ 핵심 데이터 파일 확인")

    optional_data = [
        "data/activity_log.json",
        "data/agi_metrics.json",
        "data/jarvis_performance_report.json",
        "data/projects.json",
        "data/team_status.json",
    ]

    for item in optional_data:

        path = ROOT / item

        if path.exists():

            print(f"   ✅ {item}")

        else:

            warnings.append(
                f"선택 데이터 없음: {item}"
            )

            print(f"   ⚠️ {item}")

    # ============================================================
    # 결과
    # ============================================================

    print("\n" + "=" * 70)
    print("📊 HEALTH CHECK RESULT")
    print("=" * 70)

    if issues:

        print(
            f"❌ CRITICAL: {len(issues)}개 문제"
        )

        for i, issue in enumerate(issues, 1):

            print(f"   {i}. {issue}")

    else:

        print("✅ CRITICAL 문제 없음")

    if warnings:

        print(
            f"\n⚠️ WARNING: {len(warnings)}개"
        )

        for i, warning in enumerate(warnings, 1):

            print(f"   {i}. {warning}")

    else:

        print("✅ WARNING 없음")

    print("\n" + "=" * 70)

    if issues:

        print("🔴 JARVIS HEALTH: FAIL")

        return False

    elif warnings:

        print("🟡 JARVIS HEALTH: WARNING")

        return True

    else:

        print("🟢 JARVIS HEALTH: PASS")

        return True


if __name__ == "__main__":

    success = check_jarvis_health()

    sys.exit(0 if success else 1)
