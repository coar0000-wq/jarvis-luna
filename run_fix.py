#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔥 JARVIS - 웹사이트 경로 수정 즉시 실행
"""

import subprocess
import os
from datetime import datetime

REPO_PATH = r"C:\Users\Desktop\Claude\Projects\kms"

def run_cmd(cmd, desc=""):
    """Git 명령 실행"""
    print(f"\n📌 실행: {cmd}")
    if desc:
        print(f"   설명: {desc}")
    try:
        result = subprocess.run(
            cmd, cwd=REPO_PATH, shell=True,
            capture_output=True, text=True,
            encoding='utf-8', errors='ignore', timeout=30
        )
        if result.stdout:
            lines = result.stdout.strip().split('\n')
            for line in lines[:10]:  # 처음 10줄만 표시
                print(f"   {line}")
        if result.returncode != 0 and result.stderr:
            print(f"   ⚠️ 오류: {result.stderr[:200]}")
        return result.returncode == 0
    except Exception as e:
        print(f"   ❌ 예외: {e}")
        return False

print("\n" + "="*80)
print("🔥 JARVIS - 웹사이트 경로 수정 및 GitHub 푸시")
print("="*80)
print(f"\n⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S KST')}")
print(f"📁 경로: {REPO_PATH}\n")

# Step 1: 변경사항 확인
print("✅ Step 1: 변경사항 상태 확인")
run_cmd("git status -s", "변경된 파일 확인")

# Step 2: 스테이징
print("\n✅ Step 2: 변경사항 스테이징")
run_cmd("git add index.html", "index.html 스테이징")

# Step 3: 커밋
print("\n✅ Step 3: GitHub에 커밋")
run_cmd(
    'git commit -m "🔥 FIX: 웹사이트 경로 jarvis-agi → jarvis-luna (실시간 데이터 연동)"',
    "변경사항 커밋"
)

# Step 4: Pull
print("\n✅ Step 4: 최신 변경사항 동기화")
run_cmd("git pull --rebase origin main", "Pull with rebase")

# Step 5: Push
print("\n✅ Step 5: GitHub에 푸시")
run_cmd("git push origin main", "GitHub 푸시")

# Step 6: 최종 확인
print("\n✅ Step 6: 최종 상태 확인")
run_cmd("git log --oneline -3", "최근 커밋")
run_cmd("git status", "작업 상태")

print("\n" + "="*80)
print("✅ 완료!")
print("="*80)
print("\n📊 다음 단계:")
print("   1. GitHub Pages CDN 갱신 대기 (1-5분)")
print("   2. https://coar0000-wq.github.io/jarvis-luna/ 새로고침")
print("   3. 실시간 데이터가 정상 표시되는지 확인")
print("\n" + "="*80 + "\n")

input("엔터키를 눌러서 종료...")
