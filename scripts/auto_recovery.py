#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
JARVIS LUNA - Automatic Recovery

목표:
1. 필수 디렉토리 생성
2. JSON 손상 복구
3. 필수 파일 존재 확인
4. 잘못된 timestamp 처리
5. 복구 결과를 recovery_log.json에 기록

주의:
- 존재하지 않는 데이터를 성공으로 만들지 않음
- 가짜 작업 결과를 생성하지 않음
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
SCRIPTS_DIR = ROOT / "scripts"
WORKFLOW_DIR = ROOT / ".github" / "workflows"

LOG_FILE = DATA_DIR / "jarvis_work_detailed_log.json"
RECOVERY_LOG = DATA_DIR / "recovery_log.json"


REQUIRED_SCRIPTS = [
    "collect_moe_papers.py",
    "youtube_moe_analysis.py",
    "youtube_dropshipping_analysis.py",
    "google_search_data_collection.py",
    "moe_neural_network.py",
    "moe_training.py",
]


REQUIRED_WORKFLOWS = [
    "jarvis_final_automation.yml",
    "jarvis_health_monitor.yml",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def write_recovery_log(events):

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    payload = {
        "timestamp": now_iso(),
        "events": events,
        "status": "completed"
    }

    with open(
        RECOVERY_LOG,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            payload,
            f,
            ensure_ascii=False,
            indent=2
        )


def create_empty_log():

    payload = {
        "timestamp": now_iso(),
        "current_date": datetime.now().strftime(
            "%Y-%m-%d"
        ),
        "daily_summary": {
            "completed": 0,
            "in_progress": 0,
            "pending": 0,
            "total": 0,
            "completion_rate": "0%"
        },
        "completed_today": [],
        "performance_metrics": {
            "total_execution_time": "0초",
            "average_task_duration": "0초",
            "success_rate": "0%",
            "data_collected": {},
            "violations_found": 0,
            "violations_rate": "0%"
        },
        "status": {
            "overall": "⚠️ 복구됨 - 자동화 실행 대기",
            "data_collection": "대기",
            "automation": "대기",
            "verification": "대기",
            "deployment": "대기"
        }
    }

    with open(
        LOG_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            payload,
            f,
            ensure_ascii=False,
            indent=2
        )


def check_and_recover():

    print("=" * 70)
    print("🔧 JARVIS LUNA AUTO RECOVERY")
    print("=" * 70)

    events = []
    critical = []

    # ============================================================
    # 1. 디렉토리
    # ============================================================

    print("\n1️⃣ 디렉토리 확인")

    for directory in [
        DATA_DIR,
        SCRIPTS_DIR,
        WORKFLOW_DIR,
    ]:

        if not directory.exists():

            directory.mkdir(
                parents=True,
                exist_ok=True
            )

            event = (
                f"디렉토리 생성: "
                f"{directory.relative_to(ROOT)}"
            )

            events.append(event)

            print(f"   ✅ {event}")

        else:

            print(
                f"   ✅ {directory.relative_to(ROOT)}"
            )

    # ============================================================
    # 2. JSON
    # ============================================================

    print("\n2️⃣ 작업 로그 확인")

    if not LOG_FILE.exists():

        create_empty_log()

        events.append(
            "작업 로그 생성"
        )

        print(
            "   ⚠️ 작업 로그 없음 → 빈 로그 생성"
        )

    else:

        try:

            with open(
                LOG_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

            print("   ✅ JSON 정상")

            if not isinstance(
                data.get("completed_today"),
                list
            ):

                data["completed_today"] = []

                with open(
                    LOG_FILE,
                    "w",
                    encoding="utf-8"
                ) as f:

                    json.dump(
                        data,
                        f,
                        ensure_ascii=False,
                        indent=2
                    )

                events.append(
                    "completed_today 배열 복구"
                )

                print(
                    "   🔧 completed_today 복구"
                )

        except json.JSONDecodeError:

            backup = LOG_FILE.with_suffix(
                ".corrupt.json"
            )

            try:
                LOG_FILE.replace(backup)

                events.append(
                    f"손상 JSON 백업: {backup.name}"
                )

            except Exception as e:

                critical.append(
                    f"손상 JSON 백업 실패: {e}"
                )

            create_empty_log()

            events.append(
                "손상 JSON → 정상 구조로 복구"
            )

            print(
                "   🔧 손상 JSON 복구 완료"
            )

        except Exception as e:

            critical.append(
                f"작업 로그 접근 실패: {e}"
            )

            print(
                f"   ❌ {e}"
            )

    # ============================================================
    # 3. Python scripts
    # ============================================================

    print("\n3️⃣ Python 스크립트 확인")

    for script in REQUIRED_SCRIPTS:

        path = SCRIPTS_DIR / script

        if path.exists():

            print(
                f"   ✅ scripts/{script}"
            )

        else:

            critical.append(
                f"스크립트 누락: scripts/{script}"
            )

            print(
                f"   ❌ scripts/{script}"
            )

    # ============================================================
    # 4. Workflows
    # ============================================================

    print("\n4️⃣ GitHub Actions 확인")

    for workflow in REQUIRED_WORKFLOWS:

        path = WORKFLOW_DIR / workflow

        if path.exists():

            print(
                f"   ✅ .github/workflows/{workflow}"
            )

        else:

            critical.append(
                f"워크플로우 누락: {workflow}"
            )

            print(
                f"   ❌ {workflow}"
            )

    # ============================================================
    # 5. Recovery log
    # ============================================================

    write_recovery_log(events)

    # ============================================================
    # Result
    # ============================================================

    print("\n" + "=" * 70)
    print("📊 RECOVERY RESULT")
    print("=" * 70)

    print(
        f"🔧 자동 수정: {len(events)}개"
    )

    print(
        f"❌ Critical: {len(critical)}개"
    )

    if critical:

        for item in critical:

            print(
                f"   ❌ {item}"
            )

        print(
            "\n🔴 JARVIS RECOVERY: FAILED"
        )

        return False

    print(
        "\n🟢 JARVIS RECOVERY: SUCCESS"
    )

    return True


if __name__ == "__main__":

    success = check_and_recover()

    sys.exit(0 if success else 1)
