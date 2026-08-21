#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Obsidian 실시간 동기화 함수 추가 후 GitHub에 푸시하는 스크립트
"""
import subprocess
import os
from datetime import datetime

# kms 폴더로 이동
os.chdir(r'C:\Users\Desktop\Claude\Projects\kms')

print("=" * 60)
print("🚀 GitHub Push Script - Obsidian 실시간 동기화")
print("=" * 60)
print()

# 1. Git status 확인
print("📊 Git 상태 확인 중...")
result = subprocess.run(['git', 'status', '--porcelain'], capture_output=True, text=True)
print(result.stdout)
print()

# 2. index.html 추가
print("✅ index.html 추가 중...")
subprocess.run(['git', 'add', 'index.html'], check=True)
print("   → 완료!")
print()

# 3. Commit 메시지
commit_msg = "🔄 Obsidian 실시간 동기화 함수 추가 (10초 주기 자동 업데이트)"
print(f"💬 Commit 메시지: {commit_msg}")
print()

# 4. Commit 실행
print("📝 Git commit 실행 중...")
subprocess.run(['git', 'commit', '-m', commit_msg], check=True)
print("   → Commit 완료!")
print()

# 5. Git push 실행
print("🚀 GitHub에 푸시 중...")
result = subprocess.run(['git', 'push', 'origin', 'main'], capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print("⚠️  경고:", result.stderr)

print()
print("=" * 60)
print("✨ 모든 작업 완료!")
print(f"⏰ 완료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)
print()

# 최종 Git log 확인
print("📜 최근 커밋 확인:")
subprocess.run(['git', 'log', '--oneline', '-5'], check=True)
