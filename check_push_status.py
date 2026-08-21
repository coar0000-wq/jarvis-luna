#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub 푸시 상태 확인
"""
import subprocess
import os

os.chdir(r'C:\Users\Desktop\Claude\Projects\kms')

print("=" * 70)
print("🔍 GitHub 푸시 상태 확인")
print("=" * 70)
print()

# 1. Git status
print("📊 현재 상태:")
result = subprocess.run(['git', 'status'], capture_output=True, text=True)
print(result.stdout)
print()

# 2. 최근 커밋
print("=" * 70)
print("📜 최근 5개 커밋:")
print("=" * 70)
subprocess.run(['git', 'log', '--oneline', '-5'], check=True)
print()

# 3. 원격 상태
print("=" * 70)
print("🌐 원격 저장소 상태:")
print("=" * 70)
result = subprocess.run(['git', 'remote', '-v'], capture_output=True, text=True)
print(result.stdout)
print()

# 4. 변경사항 확인
print("=" * 70)
print("📝 변경사항 확인:")
print("=" * 70)
result = subprocess.run(['git', 'diff', 'origin/main..HEAD'], capture_output=True, text=True)
if result.stdout:
    print("⚠️ 아직 푸시하지 않은 변경사항이 있습니다!")
    print()
    print("변경사항:")
    print(result.stdout[:500])  # 처음 500글자만
    print()
    print("💡 푸시 필요: python push_mobile_fix.py")
else:
    print("✅ 모든 변경사항이 푸시되었습니다!")
    print()
    print("최신 커밋에 모바일 수정사항이 포함되어 있습니다!")

print()
print("=" * 70)
