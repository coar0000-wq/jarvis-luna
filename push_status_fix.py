#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Obsidian 상태 점 동기화 - GitHub 푸시
"""
import subprocess
import os

os.chdir(r'C:\Users\Desktop\Claude\Projects\kms')

print("=" * 70)
print("🔴 Obsidian 상태 점 동기화 - GitHub 푸시")
print("=" * 70)
print()

# Add
print("✅ index.html 추가 중...")
subprocess.run(['git', 'add', 'index.html'], check=True)

# Commit
commit_msg = "🔴 Obsidian 상태 점 동기화 (오프라인 상태에서 회색 점 표시)"
print(f"\n💬 Commit: {commit_msg}")
subprocess.run(['git', 'commit', '-m', commit_msg], check=True)

# Push
print("\n🚀 GitHub 푸시 중...")
result = subprocess.run(['git', 'push', 'origin', 'main'], capture_output=True, text=True)
print(result.stdout)

if result.returncode == 0:
    print("✨ 푸시 성공!")
    print()
    print("✅ 이제:")
    print("1. 오프라인 상태 → 회색 점 + 오프라인 텍스트")
    print("2. 실시간 연동 → 초록 점 + 실시간 텍스트")
    print()
    print("💡 GitHub Pages 갱신: 1-2분 기다린 후 새로고침(Ctrl+F5)")
else:
    print("❌ 푸시 실패")
    print(result.stderr)

print()
print("=" * 70)
