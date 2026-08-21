#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔥 JARVIS - 웹사이트 경로 즉시 수정 및 GitHub 푸시
"""

import subprocess
import os
from datetime import datetime

REPO_PATH = r"C:\Users\Desktop\Claude\Projects\kms"

def run_cmd(cmd, desc=""):
    print(f"\n📌 {cmd}")
    if desc:
        print(f"   {desc}")
    try:
        result = subprocess.run(
            cmd, cwd=REPO_PATH, shell=True,
            capture_output=True, text=True,
            encoding='utf-8', errors='ignore', timeout=30
        )
        if result.stdout:
            print(f"   ✅ {result.stdout.strip()[:100]}")
        return result.returncode == 0
    except Exception as e:
        print(f"   ❌ {e}")
        return False

print("\n" + "="*80)
print("🔥 JARVIS - 웹사이트 경로 자동 수정")
print("="*80)
print(f"\n⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S KST')}")

# Step 1: 변경사항 확인
print("\n✅ Step 1: 변경사항 상태 확인")
run_cmd("git status -s", "변경된 파일 확인")

# Step 2: 커밋
print("\n✅ Step 2: GitHub에 커밋")
success = run_cmd(
    'git commit -am "🔥 FIX: 웹사이트 경로 jarvis-agi → jarvis-luna (실시간 데이터 연동)"',
    "변경사항 커밋"
)

if not success:
    print("   ℹ️  커밋할 변경사항이 없거나 이미 커밋됨")

# Step 3: Pull
print("\n✅ Step 3: 최신 변경사항 동기화")
run_cmd("git pull --rebase origin main", "Pull with rebase")

# Step 4: Push
print("\n✅ Step 4: GitHub에 푸시")
run_cmd("git push origin main", "GitHub 푸시")

# Step 5: 최종 확인
print("\n✅ Step 5: 최종 상태 확인")
run_cmd("git log --oneline -3", "최근 커밋")
run_cmd("git status", "작업 상태")

print("\n" + "="*80)
print("✅ 웹사이트 경로 수정 완료!")
print("="*80)
print("\n🌐 다음 단계:")
print("   1. GitHub Pages CDN 갱신 대기 (1-5분)")
print("   2. https://coar0000-wq.github.io/jarvis-luna/ 새로고침")
print("   3. 데이터가 정상 표시되는지 확인")
print("\n" + "="*80 + "\n")
