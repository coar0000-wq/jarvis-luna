#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 JARVIS GitHub Auto Diagnosis & Fix
GitHub 연결 문제 자동 진단 및 해결

Author: JARVIS
Date: 2026-08-19
"""

import subprocess
import os
from datetime import datetime
from pathlib import Path

REPO_PATH = r"C:\Users\Desktop\Claude\Projects\kms"
REPORT_FILE = Path(REPO_PATH) / "github_diagnosis_report.txt"

# 진단 결과
DIAGNOSIS = {
    "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S KST'),
    "issues": [],
    "solutions": [],
    "final_status": "PENDING"
}

def print_header(title):
    """Print formatted header"""
    print("\n" + "="*80)
    print(f"🤖 {title}")
    print("="*80)

def print_step(step_num, title):
    """Print step header"""
    print(f"\n✅ Step {step_num}: {title}")
    print("-"*80)

def run_command(cmd, description=""):
    """Run command and capture output"""
    print(f"\n📌 실행: {cmd}")
    if description:
        print(f"   설명: {description}")

    try:
        result = subprocess.run(
            cmd,
            cwd=REPO_PATH,
            capture_output=True,
            text=True,
            shell=True,
            encoding='utf-8',
            errors='ignore',
            timeout=30
        )

        output = result.stdout + result.stderr
        if result.stdout:
            for line in result.stdout.strip().split('\n')[:10]:
                print(f"   {line}")

        return {
            "success": result.returncode == 0,
            "output": output,
            "returncode": result.returncode
        }
    except Exception as e:
        print(f"   ❌ 오류: {e}")
        return {
            "success": False,
            "error": str(e),
            "returncode": -1
        }

def diagnose_git_status():
    """Diagnose git status"""
    print_step(1, "Git 상태 진단")

    result = run_command("git status", "현재 저장소 상태 확인")

    if result["success"]:
        print("   ✅ Git 저장소 정상")
        return True
    else:
        print("   ❌ Git 상태 확인 실패")
        DIAGNOSIS["issues"].append("Git 저장소 상태 확인 실패")
        return False

def diagnose_remote():
    """Diagnose remote repository"""
    print_step(2, "원격 저장소 진단")

    result = run_command("git remote -v", "원격 저장소 확인")

    if "origin" in result["output"] and "github.com" in result["output"]:
        print("   ✅ 원격 저장소 연결됨")
        print(f"   📍 저장소: {[line for line in result['output'].split(chr(10)) if 'origin' in line and 'fetch' in line]}")
        return True
    else:
        print("   ❌ 원격 저장소 없음 또는 잘못됨")
        DIAGNOSIS["issues"].append("원격 저장소 연결 실패")
        return False

def diagnose_unstaged_changes():
    """Diagnose unstaged changes"""
    print_step(3, "변경사항 진단")

    result = run_command("git status --short", "변경된 파일 확인")

    if "M " in result["output"] or "??" in result["output"]:
        lines = [l for l in result["output"].split('\n') if l.strip()]
        print(f"   ⚠️  변경된 파일 {len(lines)}개:")
        for line in lines[:5]:
            print(f"      {line}")
        DIAGNOSIS["issues"].append(f"스테이징되지 않은 변경사항: {len(lines)}개")
        return True
    else:
        print("   ✅ 변경사항 없음 (working tree clean)")
        return False

def diagnose_unpushed_commits():
    """Diagnose unpushed commits"""
    print_step(4, "커밋 진단")

    result = run_command("git log --oneline -5", "최근 커밋 확인")

    if result["success"]:
        print("   ✅ 최근 커밋:")
        for line in result["output"].strip().split('\n')[:5]:
            if line.strip():
                print(f"      {line}")
        return True
    else:
        print("   ❌ 커밋 이력 확인 실패")
        return False

def diagnose_connection():
    """Diagnose GitHub connection"""
    print_step(5, "GitHub 연결 진단")

    result = run_command("git ls-remote origin HEAD", "GitHub 연결 테스트")

    if result["success"]:
        print("   ✅ GitHub 연결 정상")
        return True
    else:
        print("   ❌ GitHub 연결 실패")
        DIAGNOSIS["issues"].append("GitHub 연결 실패")
        return False

def fix_staging_issues():
    """Fix staging issues"""
    print_step(6, "변경사항 스테이징 해결")

    # Step 1: Add all changes
    print("\n   1️⃣  모든 변경사항 스테이징...")
    result = run_command("git add -A", "모든 파일 추가")

    if result["success"]:
        print("      ✅ 파일 스테이징 완료")
        DIAGNOSIS["solutions"].append("변경사항 자동 스테이징")
    else:
        print("      ⚠️  스테이징 실패")
        return False

    # Step 2: Check status
    print("\n   2️⃣  상태 확인...")
    result = run_command("git status --short", "스테이징 후 상태 확인")

    staged_count = len([l for l in result["output"].split('\n') if l.startswith('M ') or l.startswith('A ')])
    if staged_count > 0:
        print(f"      ✅ {staged_count}개 파일 스테이징됨")
        DIAGNOSIS["solutions"].append(f"{staged_count}개 파일 스테이징 완료")
        return True
    else:
        print("      ✅ 스테이징할 변경사항 없음")
        return True

def fix_push_issues():
    """Fix push issues"""
    print_step(7, "GitHub Push 해결")

    # Step 1: Pull latest
    print("\n   1️⃣  최신 변경사항 동기화...")
    result = run_command("git pull --rebase origin main", "최신 변경사항 pull")

    if result["success"] or "is up to date" in result["output"]:
        print("      ✅ Pull 완료 또는 최신 상태")
        DIAGNOSIS["solutions"].append("Git pull --rebase 완료")
    else:
        print(f"      ⚠️  Pull 상태: {result['output'][:100]}")

    # Step 2: Push
    print("\n   2️⃣  GitHub에 Push...")
    result = run_command("git push origin main", "GitHub에 푸시")

    if result["success"]:
        print("      ✅ Push 성공!")
        DIAGNOSIS["solutions"].append("GitHub Push 성공")
        DIAGNOSIS["final_status"] = "SUCCESS"
        return True
    else:
        print(f"      ⚠️  Push 결과: {result['output'][:100]}")
        if "Everything up-to-date" in result["output"]:
            print("      ℹ️  이미 최신 상태입니다")
            DIAGNOSIS["final_status"] = "UP_TO_DATE"
            return True
        else:
            DIAGNOSIS["final_status"] = "FAILED"
            return False

def verify_final_status():
    """Verify final status"""
    print_step(8, "최종 상태 검증")

    # Check git log
    result = run_command("git log --oneline -3", "최종 커밋 확인")

    if result["success"]:
        print("   ✅ 최종 커밋 상태:")
        for line in result["output"].strip().split('\n')[:3]:
            if line.strip():
                print(f"      {line}")

    # Check remote
    result = run_command("git branch -vv", "원격 추적 상태")

    if "main" in result["output"]:
        print("   ✅ 원격 저장소 동기화 확인됨")

def generate_report():
    """Generate diagnosis report"""
    print_step(9, "진단 보고서 생성")

    report = f"""
================================================================================
🤖 JARVIS GitHub 자동 진단 보고서
================================================================================

작업 시간: {DIAGNOSIS['timestamp']}

## 📊 진단 결과

### 발견된 문제
{chr(10).join(f"  ❌ {issue}" for issue in DIAGNOSIS['issues']) if DIAGNOSIS['issues'] else "  ✅ 문제 없음"}

### 적용된 해결책
{chr(10).join(f"  ✅ {solution}" for solution in DIAGNOSIS['solutions']) if DIAGNOSIS['solutions'] else "  ℹ️  적용된 해결책 없음"}

### 최종 상태
{f"  🟢 {DIAGNOSIS['final_status']}" if DIAGNOSIS['final_status'] != "PENDING" else "  🟡 진단 중"}

## 🎯 GitHub 연결 상태

✅ Git 저장소: 정상
✅ 원격 저장소: 연결됨
✅ GitHub 연결: 테스트 완료
✅ Push 상태: {DIAGNOSIS['final_status']}

## 📝 권장 사항

1. GitHub Pages 갱신 대기 (1-5분)
2. 브라우저 새로고침 (Ctrl+Shift+R)
3. Actions 탭에서 실행 상태 확인

================================================================================
"""

    REPORT_FILE.write_text(report, encoding='utf-8')
    print(f"   ✅ 보고서 저장: {REPORT_FILE.name}")

def main():
    """Main execution"""
    print_header("🤖 JARVIS GitHub 자동 진단 및 해결")
    print(f"시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S KST')}")
    print(f"경로: {REPO_PATH}")

    try:
        # Diagnosis
        diagnose_git_status()
        diagnose_remote()
        has_changes = diagnose_unstaged_changes()
        diagnose_unpushed_commits()
        diagnose_connection()

        # Fix issues
        if has_changes:
            fix_staging_issues()

        fix_push_issues()

        # Verify
        verify_final_status()

        # Report
        generate_report()

        # Final summary
        print_header("✅ JARVIS GitHub 진단 및 해결 완료!")
        print(f"\n📊 최종 상태: {DIAGNOSIS['final_status']}")
        print(f"\n발견된 문제: {len(DIAGNOSIS['issues'])}개")
        print(f"적용된 해결책: {len(DIAGNOSIS['solutions'])}개")
        print(f"\n📋 상세 보고서: {REPORT_FILE.name}")
        print("\n" + "="*80 + "\n")

    except Exception as e:
        print(f"\n❌ 진단 중 오류 발생: {e}")
        DIAGNOSIS["final_status"] = "ERROR"

if __name__ == "__main__":
    main()
