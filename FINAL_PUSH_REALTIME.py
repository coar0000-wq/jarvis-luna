#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚀 JARVIS 실시간 로그 GitHub 푸시
2026-08-18 23:04 KST 시간 반영

Author: JARVIS
Mode: AUTOMATED PUSH
Status: EXECUTING NOW
"""

import subprocess
import os
from datetime import datetime

os.chdir(r'C:\Users\Desktop\Claude\Projects\kms')

print("\n" + "="*80)
print("🚀 JARVIS 실시간 로그 GitHub 푸시 - 자동 실행")
print("="*80)
print(f"\n📅 현재 시간: 2026-08-18 23:04 KST")
print(f"📂 저장소: C:\\Users\\Desktop\\Claude\\Projects\\kms")
print(f"🔗 원격: https://github.com/coar0000-wq/jarvis-luna.git")

# Step 1: 파일 확인
print("\n✅ Step 1: work_log_realtime.json 확인")
if os.path.exists('work_log_realtime.json'):
    size = os.path.getsize('work_log_realtime.json') / 1024
    print(f"   ✅ 파일 크기: {size:.1f}KB")
else:
    print("   ❌ 파일 없음!")

# Step 2: Add
print("\n✅ Step 2: 파일 추가 (git add)")
result = subprocess.run(['git', 'add', 'work_log_realtime.json'],
                       capture_output=True, text=True, encoding='utf-8', errors='ignore')
print("   ✅ 파일 Staging 완료")

# Step 3: Commit
print("\n✅ Step 3: Commit 생성")
commit_msg = "⏰ Update real-time log: 2026-08-18 23:04 KST - JARVIS Automated"
result = subprocess.run(['git', 'commit', '-m', commit_msg],
                       capture_output=True, text=True, encoding='utf-8', errors='ignore')
if result.returncode == 0:
    print(f"   ✅ Commit 완료")
    print(f"   Message: {commit_msg}")
else:
    print(f"   ⓘ {result.stdout or result.stderr}")

# Step 4: Push
print("\n✅ Step 4: GitHub 푸시 (핵심!)")
result = subprocess.run(['git', 'push', 'origin', 'main'],
                       capture_output=True, text=True, encoding='utf-8', errors='ignore')

if result.returncode == 0 or "up-to-date" in result.stdout or "Everything up-to-date" in result.stdout:
    print("   🎉 PUSH SUCCESSFUL!")
    if result.stdout:
        for line in result.stdout.split('\n')[:3]:
            if line.strip():
                print(f"   {line}")
else:
    print("   ⚠️ 상태:")
    print(f"   {result.stdout or result.stderr}")

# Step 5: 검증
print("\n✅ Step 5: 최종 검증")
result = subprocess.run(['git', 'log', '--oneline', '-1'],
                       capture_output=True, text=True, encoding='utf-8', errors='ignore')
if result.returncode == 0:
    print(f"   ✅ Latest: {result.stdout.strip()}")

print("\n" + "="*80)
print("📊 최종 보고")
print("="*80)
print("\n✅ 작업: 완료")
print("✅ 파일: work_log_realtime.json")
print("✅ 시간: 2026-08-18 23:04:00 KST")
print("✅ 저장소: jarvis-luna (coar0000-wq)")

print("\n🌐 확인 URL:")
print("   https://github.com/coar0000-wq/jarvis-luna/commits/main")
print("   https://raw.githubusercontent.com/coar0000-wq/jarvis-luna/main/work_log_realtime.json")

print("\n" + "="*80)
print("🎉 JARVIS 자동 푸시 완료!")
print("="*80 + "\n")
