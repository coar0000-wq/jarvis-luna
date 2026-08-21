#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 JARVIS GitHub Advanced Fix
GitHub 연결 문제 고급 해결

Author: JARVIS
Date: 2026-08-19
"""

import subprocess
import os
from datetime import datetime

REPO_PATH = r"C:\Users\Desktop\Claude\Projects\kms"

def print_header(title):
    print("\n" + "="*80)
    print(f"🤖 {title}")
    print("="*80)

def print_step(step_num, title):
    print(f"\n✅ Step {step_num}: {title}")
    print("-"*80)

def run_command(cmd, description=""):
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

        if result.stdout:
            for line in result.stdout.strip().split('\n')[:15]:
                print(f"   {line}")

        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr,
            "returncode": result.returncode
        }
    except Exception as e:
        print(f"   ❌ 오류: {e}")
        return {"success": False, "error": str(e)}

def main():
    print_header("🤖 JARVIS GitHub 고급 해결 시작")
    print(f"시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S KST')}")

    # Step 1: Check current status
    print_step(1, "현재 상태 상세 확인")

    result = run_command("git status -s", "모든 변경사항 나열")
    deleted_count = len([l for l in result["output"].split('\n') if 'D' in l])
    renamed_count = len([l for l in result["output"].split('\n') if 'R' in l])

    print(f"\n   📊 Deleted: {deleted_count}개, Renamed: {renamed_count}개")

    # Step 2: Reset and try clean approach
    print_step(2, "변경사항 초기화 (안전한 방식)")

    print("\n   1️⃣  모든 변경사항 스테이징...")
    result = run_command("git add -A", "모든 파일 추가")

    if not result["success"]:
        print("   ⚠️  git add -A 실패, 재시도...")
        result = run_command("git add .", "현재 디렉토리 모든 파일 추가")

    # Step 3: Check status after add
    print_step(3, "스테이징 상태 확인")

    result = run_command("git status", "현재 상태 확인")

    if "nothing to commit" in result["output"]:
        print("   ✅ 커밋할 변경사항 없음 (이미 동기화됨)")
    elif "Changes to be committed" in result["output"]:
        print("   ✅ 변경사항 스테이징됨")

        # Step 4: Commit
        print_step(4, "변경사항 커밋")

        commit_msg = "🤖 JARVIS: Auto cleanup + organize files"
        result = run_command(
            f'git commit -m "{commit_msg}"',
            "변경사항 커밋"
        )

        if result["success"]:
            print("   ✅ 커밋 성공!")
        else:
            print(f"   ⚠️  커밋 상태: {result['error'][:100]}")

    # Step 5: Pull with rebase
    print_step(5, "최신 변경사항 동기화")

    result = run_command(
        "git pull --rebase origin main",
        "최신 커밋 pull"
    )

    if "up to date" in result["output"] or result["success"]:
        print("   ✅ Pull 완료 또는 이미 최신 상태")
    else:
        print(f"   ⚠️  Pull 결과: {result['output'][:100]}")

    # Step 6: Push
    print_step(6, "GitHub에 푸시")

    result = run_command("git push origin main", "GitHub 푸시")

    if result["success"]:
        print("   ✅ Push 성공!")
    elif "up-to-date" in result["output"] or "Everything up-to-date" in result["output"]:
        print("   ✅ 이미 최신 상태 (Push 불필요)")
    else:
        print(f"   ⚠️  Push 상태: {result['output'][:100]}")
        print(f"   오류: {result['error'][:100]}")

    # Step 7: Verify
    print_step(7, "최종 검증")

    result = run_command("git log --oneline -3", "최종 커밋 확인")
    print("   ✅ 최종 커밋:")
    for line in result["output"].strip().split('\n')[:3]:
        if line.strip():
            print(f"      {line}")

    result = run_command("git status", "최종 상태")
    if "working tree clean" in result["output"] or "nothing to commit" in result["output"]:
        print("   ✅ Working tree clean - 모든 변경사항 동기화됨!")
    else:
        print("   ⚠️  여전히 변경사항 있음")

    print_header("✅ JARVIS GitHub 고급 해결 완료!")
    print("\n🎯 다음 단계:")
    print("   1. GitHub Pages CDN 갱신 대기 (1-5분)")
    print("   2. 웹사이트 새로고침 (Ctrl+Shift+R)")
    print("   3. GitHub Actions 실행 상태 확인")
    print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    main()
