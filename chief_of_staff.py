"""
chief_of_staff.py - FULL FILE
팀원 보고 -> 비서실장 자동 수정 -> push -> 보고
"""
import json, datetime, subprocess
from pathlib import Path

ROOT = Path(__file__).parent
TEAM_STATUS_PATH = ROOT / "data" / "team_status.json"

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    return result.returncode == 0, result.stdout + result.stderr

def load_team_status():
    return json.loads(TEAM_STATUS_PATH.read_text(encoding="utf-8"))

def auto_fix_report(report):
    issue = report.get("issue","")
    if "증거" in issue or "products.json" in report.get("file",""):
        ok, out = run_cmd("python product_discovery.py")
        return {"report_id": report["id"], "success": ok, "action": "product_discovery 재수집"}
    elif "gosi" in issue.lower():
        ok, out = run_cmd("python gosi_collector.py")
        return {"report_id": report["id"], "success": ok, "action": "gosi_collector 재수집"}
    elif "dashboard_runtime" in issue:
        ok, out = run_cmd("python generate_dashboard_runtime.py")
        return {"report_id": report["id"], "success": ok, "action": "dashboard_runtime 재생성"}
    elif "daiso" in issue.lower():
        ok, out = run_cmd("python daiso_gosi_validator.py")
        return {"report_id": report["id"], "success": ok, "action": "daiso 검증"}
    else:
        return {"report_id": report["id"], "success": False, "action": "manual_review_needed"}

def push_if_fixed(fixes):
    if not any(f["success"] for f in fixes):
        return False, "no fixes"
    cmds = [
        "git add -A",
        f'git commit -m "fix: chief_of_staff auto-fix {len(fixes)} reports - JARVIS auto"',
        "git push origin main"
    ]
    log = ""
    for cmd in cmds:
        ok, out = run_cmd(cmd)
        log += f"\n$ {cmd}\n{out}\n"
        if not ok and "push" in cmd:
            return False, log
    return True, log

def main():
    status = load_team_status()
    abnormal = [r for r in status["reports"] if r["status"] in ["이상","error","failed"]]
    if not abnormal:
        print("✅ 이상 없음")
        return
    fixes = [auto_fix_report(r) for r in abnormal]
    success, log = push_if_fixed(fixes)
    print(f"처리: {len(abnormal)}건, 성공: {sum(1 for f in fixes if f['success'])}건, Push: {success}")
    print("→ Actions: https://github.com/coar0000-wq/jarvis-luna/actions")

if __name__ == "__main__":
    main()
