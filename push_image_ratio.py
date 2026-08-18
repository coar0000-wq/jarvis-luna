#!/usr/bin/env python3
import subprocess
import os

os.chdir(r'C:\Users\Desktop\Claude\Projects\kms')

print("=" * 70)
print("📱 첫 번째 이미지 비율 조정 - 1:1 정사각형")
print("=" * 70)
print()

subprocess.run(['git', 'add', 'index.html'], check=True)
subprocess.run(['git', 'commit', '-m', '📱 첫 번째 이미지 aspect-ratio 4:3 → 1:1 (정사각형)'], check=True)
result = subprocess.run(['git', 'push', 'origin', 'main'], capture_output=True, text=True)
print(result.stdout)

if result.returncode == 0:
    print("✨ 푸시 성공!")
    print()
    print("✅ aspect-ratio: 1/1 (정사각형)로 변경됨")
    print("✅ 위아래 남색 공간 완전 제거")
    print()
    print("💡 1-2분 후 새로고침(Ctrl+F5)하면 적용됩니다!")

print()
print("=" * 70)
