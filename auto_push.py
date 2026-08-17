#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import os
import sys

os.chdir(r'C:\Users\Desktop\Claude\Projects\kms')

print("🚀 JARVIS LUNA GitHub 자동 푸시 시작")
print("=" * 50)
print()

# Git 상태 확인
print("📊 Git 상태 확인 중...")
subprocess.run(['git', 'status'])
print()

# 모든 변경사항 스테이징
print("📝 변경사항 스테이징...")
subprocess.run(['git', 'add', '.'])
print()

# 커밋
commit_msg = "Complete: JSON.parse + array order + date format + background unified"
print(f"💾 커밋 생성: {commit_msg}")
result = subprocess.run(['git', 'commit', '-m', commit_msg])
print()

if result.returncode == 0:
    print("✅ 커밋 성공")
else:
    print("⚠️ 커밋 실패 (변경사항 없음일 수 있음)")

print()

# 푸시
print("🚀 main 브랜치로 푸시 중...")
result = subprocess.run(['git', 'push', 'origin', 'main'])
print()

if result.returncode == 0:
    print("✅ 푸시 성공!")
    print()
    print("📊 최종 상태:")
    subprocess.run(['git', 'log', '--oneline', '-n', '3'])
else:
    print("❌ 푸시 실패")
    print()
    print("💡 해결 방법:")
    print("  1. git pull --rebase origin main")
    print("  2. 충돌 해결")
    print("  3. git push origin main")

print()
print("=" * 50)
print("✨ 완료!")
