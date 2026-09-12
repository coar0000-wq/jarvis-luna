"""
chief_of_staff.py - FULL FILE 전체 덮어쓰기용
JARVIS 팀 현황: 팀원 보고 -> 비서실장 자동 수정 -> push -> 보고
CLAUDE.md Rule 3: JARVIS가 무조건 push하고 성공여부 보고
"""

import json
import datetime
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
TEAM_STATUS_PATH = ROOT / "data" / "team_status.json"
LOG_PATH = ROOT / "data" / "chief_of_staff_log.json"

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)

def load_team_status():
    if not TEAM_STATUS_PATH.exists():
        print(f"❌ 팀 현황 파일 없음: {TEAM_STATUS_PATH}")
        return {"reports": []}
    return json.loads(TEAM_STATUS_PATH.read_text(encoding="utf-8"))

def auto_fix_report(report: dict) -> dict:
    """
    팀원 보고 1건을 자동 수정
    report 예시:
    {
      "id": "report-001",
      "team": "product_discovery",
      "reporter": "agent-1",
      "issue": "products.json 증거 없음",
      "file": "data/products.json",
      "severity": "high",
      "status": "이상"
    }
    """
    issue = report.get("issue","")
    file_path = ROOT / report.get("file","")
    
    fix_result = {
        "report_id": report.get("id"),
        "fixed_at": datetime.datetime.utcnow().isoformat() + "Z",
        "action": "",
        "success": False,
        "details": ""
    }
    
    # Case 1: products.json 증거 없음 -> product_discovery.py 재실행
    if "증거" in issue or "products.json" in report.get("file",""):
        print(f"🔧 자동 수정: {report['id']} - product_discovery 재수집")
        ok, out = run_cmd("python product_discovery.py")
        fix_result["action"] = "python product_discovery.py"
        fix_result["success"] = ok
        fix_result["details"] = out[:500]
    
    # Case 2: gosi.json 증거 없음 -> gosi_collector 재실행
    elif "gosi" in issue.lower() or "gosi.json" in report.get("file",""):
        print(f"🔧 자동 수정: {report['id']} - gosi_collector 재수집")
        ok, out = run_cmd("python gosi_collector.py")
        fix_result["action"] = "python gosi_collector.py"
        fix_result["success"] = ok
        fix_result["details"] = out[:500]
    
    # Case 3: dashboard_runtime.json 생성 실패
    elif "dashboard_runtime" in issue:
        print(f"🔧 자동 수정: {report['id']} - dashboard_runtime 재생성")
        ok, out = run_cmd("python generate_dashboard_runtime.py")
        fix_result["action"] = "python generate_dashboard_runtime.py"
        fix_result["success"] = ok
        fix_result["details"] = out[:500]
    
    # Case 4: daiso_gosi 필수 항목 누락
    elif "daiso" in issue.lower() or "gosi_ok" in issue:
        print(f"🔧 자동 수정: {report['id']} - daiso_gosi_validator 재검증")
        ok, out = run_cmd("python daiso_gosi_validator.py")
        fix_result["action"] = "python daiso_gosi_validator.py"
        fix_result["success"] = ok
        fix_result["details"] = out[:500]
    
    else:
        # 알 수 없는 이슈는 로그만 남기고 수동 확인 요청
        print(f"⚠️ 알 수 없는 이슈: {report['id']} - {issue}")
        fix_result["action"] = "manual_review_needed"
        fix_result["success"] = False
        fix_result["details"] = f"수동 확인 필요: {issue}"
    
    return fix_result

def push_if_fixed(fixes):
    """수정 성공한 것이 있으면 git push (CLAUDE.md 필수)"""
    if not any(f["success"] for f in fixes):
        print("ℹ️ 수정 성공 없음 - push 스킵")
        return False, "no fixes"
    
    cmds = [
        "git status",
        "git diff --stat",
        "git add -A",
        f'git commit -m "fix: chief_of_staff auto-fix {len(fixes)} reports - JARVIS auto"',
        "git push origin main"
    ]
    
    full_log = ""
    for cmd in cmds:
        ok, out = run_cmd(cmd)
        full_log += f"\n$ {cmd}\n{out}\n"
        if not ok and "push" in cmd:
            print(f"❌ Push 실패: {out}")
            return False, full_log
        if not ok and "commit" in cmd and "nothing to commit" in out:
            print("ℹ️ 커밋할 변경 없음")
            continue
    
    print("✅ Push 성공")
    return True, full_log

def main():
    print("🚀 비서실장 자동화 시작")
    status = load_team_status()
    reports = status.get("reports", [])
    
    # 이상 상태만 필터
    abnormal = [r for r in reports if r.get("status") in ["이상", "error", "failed", "abnormal"]]
    
    if not abnormal:
        print("✅ 이상 보고 없음 - 정상")
        return
    
    print(f"📋 이상 보고 {len(abnormal)}건 발견")
    fixes = []
    for report in abnormal:
        result = auto_fix_report(report)
        fixes.append(result)
        # 보고서 상태를 수정중으로 업데이트
        report["status"] = "수정중" if result["success"] else "수동확인필요"
        report["fixed_by"] = "chief_of_staff"
        report["fixed_at"] = result["fixed_at"]
    
    # 로그 저장
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps({
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "reports_processed": len(abnormal),
        "fixes": fixes
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    
    # Push 시도 (CLAUDE.md Rule 3)
    success, log = push_if_fixed(fixes)
    
    # 최종 보고
    print("\n=== 비서실장 최종 보고 ===")
    print(f"처리: {len(abnormal)}건")
    print(f"성공: {sum(1 for f in fixes if f['success'])}건")
    print(f"Push: {'성공' if success else '실패/스킵'}")
    print(f"Actions: https://github.com/coar0000-wq/jarvis-luna/actions")
    
    # team_status 업데이트 저장
    TEAM_STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
