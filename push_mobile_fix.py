#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
모바일 이미지 박스 여백 제거 - GitHub 푸시
"""
import subprocess
import os
from datetime import datetime

os.chdir(r'C:\Users\Desktop\Claude\Projects\kms')

print("=" * 70)
print("📱 모바일 이미지 박스 여백 제거 - GitHub 푸시")
print("=" * 70)
print()

# 1. Git status
print("📊 변경사항 확인:")
result = subprocess.run(['git', 'status', '--short'], capture_output=True, text=True)
print(result.stdout)
print()

# 2. Add
print("✅ index.html 추가 중...")
subprocess.run(['git', 'add', 'index.html'], check=True)
print("   → 완료!")
print()

# 3. Commit
commit_msg = "📱 모바일 이미지 박스 여백 제거 (aspect-ratio 4:3, max-height 400px)"
print(f"💬 Commit: {commit_msg}")
print()

subprocess.run(['git', 'commit', '-m', commit_msg], check=True)
print("   → Commit 완료!")
print()

# 4. Push
print("🚀 GitHub 푸시 중...")
result = subprocess.run(['git', 'push', 'origin', 'main'], capture_output=True, text=True)
print(result.stdout)

if result.returncode == 0:
    print("\n✨ 푸시 성공!")
    print()
    print("💡 다음 단계:")
    print("1. 1-2분 기다림 (GitHub Pages 갱신)")
    print("2. 모바일에서 https://coar0000-wq.github.io/jarvis-agi/ 접속")
    print("3. Ctrl+Shift+R 강력 새로고침")
    print()
    print("✅ 이미지 위아래 남색 공간이 제거됩니다!")
else:
    print("\n❌ 푸시 실패:")
    print(result.stderr)

print()
print("=" * 70)
print(f"✅ 작업 완료! ({datetime.now().strftime('%H:%M:%S')})")
print("=" * 70)
