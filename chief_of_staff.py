"""
chief_of_staff.py - FULL FILE 전체 덮어쓰기용

역할
----
JARVIS 팀 현황을 읽고 이상 보고를 자동 수정한다.

중요
----
이 파일은 더 이상 git commit / git push를 수행하지 않는다.
GitHub Actions의 chief_of_staff.yml이 최종 commit / push를 담당한다.

이렇게 해야 한 번의 워크플로우 실행에서
"스크립트 내부 push + 워크플로우 push"가 중복으로 발생하지 않는다.
"""

import json
import datetime
import subprocess
from pathlib import Path


ROOT = Path(__file__).parent

TEAM_STATUS_PATH = ROOT / "data" / "team_status.json"
LOG_PATH = ROOT / "data" / "chief_of_staff_log.json"


def utc_now():
    return datetime.datetime.utcnow().isoformat() + "Z"


def run_cmd(cmd):
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )

        return result.returncode == 0, result.stdout + result.stderr

    except Exception as e:
        return False, str(e)


def load_team_status():
    if not TEAM_STATUS_PATH.exists():
        print(f"❌ 팀 현황 파일 없음: {TEAM_STATUS_PATH}")
        return {"reports": []}

    try:
        return json.loads(
            TEAM_STATUS_PATH.read_text(encoding="utf-8")
        )

    except Exception as e:
        print(f"❌ team_status.json 읽기 실패: {e}")
        return {"reports": []}


def auto_fix_report(report: dict) -> dict:
    """
    팀원 보고 1건을 자동 수정
    """

    issue = report.get("issue", "")
    file_name = report.get("file", "")

    fixed_at = utc_now()

    fix_result = {
        "report_id": report.get("id"),
        "fixed_at": fixed_at,
        "action": "",
        "success": False,
        "details": ""
    }

    # ---------------------------------------------------------
    # Case 1: products.json 증거 없음
    # ---------------------------------------------------------
    if "증거" in issue or "products.json" in file_name:

        print(
            f"🔧 자동 수정: "
            f"{report.get('id')} - product_discovery 재수집"
        )

        ok, out = run_cmd(
            "python product_discovery.py"
        )

        fix_result["action"] = (
            "python product_discovery.py"
        )

        fix_result["success"] = ok
        fix_result["details"] = out[:500]

    # ---------------------------------------------------------
    # Case 2: gosi.json 증거 없음
    # ---------------------------------------------------------
    elif (
        "gosi" in issue.lower()
        or "gosi.json" in file_name
    ):

        print(
            f"🔧 자동 수정: "
            f"{report.get('id')} - gosi_collector 재수집"
        )

        ok, out = run_cmd(
            "python gosi_collector.py"
        )

        fix_result["action"] = (
            "python gosi_collector.py"
        )

        fix_result["success"] = ok
        fix_result["details"] = out[:500]

    # ---------------------------------------------------------
    # Case 3: dashboard_runtime.json 생성 실패
    # ---------------------------------------------------------
    elif "dashboard_runtime" in issue:

        print(
            f"🔧 자동 수정: "
            f"{report.get('id')} - dashboard_runtime 재생성"
        )

        ok, out = run_cmd(
            "python generate_dashboard_runtime.py"
        )

        fix_result["action"] = (
            "python generate_dashboard_runtime.py"
        )

        fix_result["success"] = ok
        fix_result["details"] = out[:500]

    # ---------------------------------------------------------
    # Case 4: Daiso GOSI 필수 항목 누락
    # ---------------------------------------------------------
    elif (
        "daiso" in issue.lower()
        or "gosi_ok" in issue
    ):

        print(
            f"🔧 자동 수정: "
            f"{report.get('id')} - daiso_gosi_validator 재검증"
        )

        ok, out = run_cmd(
            "python daiso_gosi_validator.py"
        )

        fix_result["action"] = (
            "python daiso_gosi_validator.py"
        )

        fix_result["success"] = ok
        fix_result["details"] = out[:500]

    # ---------------------------------------------------------
    # Case 5: 알 수 없는 이슈
    # ---------------------------------------------------------
    else:

        print(
            f"⚠️ 알 수 없는 이슈: "
            f"{report.get('id')} - {issue}"
        )

        fix_result["action"] = (
            "manual_review_needed"
        )

        fix_result["success"] = False

        fix_result["details"] = (
            f"수동 확인 필요: {issue}"
        )

    return fix_result


def save_team_status(status):
    TEAM_STATUS_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    TEAM_STATUS_PATH.write_text(
        json.dumps(
            status,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def save_log(fixes, abnormal_count):
    LOG_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    payload = {
        "generated_at": utc_now(),
        "reports_processed": abnormal_count,
        "fixes": fixes
    }

    LOG_PATH.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def main():

    print("🚀 비서실장 자동화 시작")

    status = load_team_status()

    reports = status.get("reports", [])

    # 이상 상태만 필터
    abnormal = [
        report
        for report in reports
        if report.get("status") in [
            "이상",
            "error",
            "failed",
            "abnormal"
        ]
    ]

    # ---------------------------------------------------------
    # 이상 보고가 없으면 정상 종료
    # ---------------------------------------------------------
    if not abnormal:

        print("✅ 이상 보고 없음 - 정상")

        save_log([], 0)

        return

    print(
        f"📋 이상 보고 {len(abnormal)}건 발견"
    )

    fixes = []

    # ---------------------------------------------------------
    # 이상 보고 자동 처리
    # ---------------------------------------------------------
    for report in abnormal:

        result = auto_fix_report(report)

        fixes.append(result)

        # 성공 -> 수정중
        # 실패 -> 수동확인필요
        report["status"] = (
            "수정중"
            if result["success"]
            else "수동확인필요"
        )

        report["fixed_by"] = (
            "chief_of_staff"
        )

        report["fixed_at"] = (
            result["fixed_at"]
        )

    # ---------------------------------------------------------
    # 결과 저장
    # ---------------------------------------------------------
    save_log(
        fixes,
        len(abnormal)
    )

    save_team_status(
        status
    )

    # ---------------------------------------------------------
    # 중요
    #
    # 여기서 git commit / push 하지 않는다.
    #
    # GitHub Actions의 chief_of_staff.yml이
    # 최종적으로 변경사항을 commit/push 한다.
    # ---------------------------------------------------------

    success_count = sum(
        1
        for fix in fixes
        if fix["success"]
    )

    print("")
    print("=== 비서실장 최종 보고 ===")
    print(
        f"처리: {len(abnormal)}건"
    )
    print(
        f"성공: {success_count}건"
    )
    print(
        "Git: GitHub Actions에서 처리"
    )
    print(
        "Push: GitHub Actions에서 처리"
    )
    print(
        "Actions: "
        "https://github.com/coar0000-wq/jarvis-luna/actions"
    )


if __name__ == "__main__":
    main()
