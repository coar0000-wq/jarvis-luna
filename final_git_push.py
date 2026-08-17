#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚀 JARVIS: 최종 Git 동기화 (모든 데이터 파일)
"""

import subprocess
import os
from datetime import datetime

os.chdir(r'C:\Users\Desktop\Claude\Projects\kms')

print("\n" + "="*70)
print("🚀 JARVIS: 최종 Git 동기화 시작")
print("="*70)
print(f"⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"📍 경로: {os.getcwd()}")

# 1️⃣ Git status 확인
print("\n[1/5] 현재 Git 상태 확인...")
subprocess.run(['git', 'status'], timeout=30)

# 2️⃣ Git pull (remote 변경사항 가져오기)
print("\n[2/5] Remote 변경사항 가져오기...")
result = subprocess.run(['git', 'pull', 'origin', 'main'], timeout=30)
if result.returncode != 0:
    print("\n⚠️  Git pull 실패 - 충돌이 있을 수 있습니다")

# 3️⃣ 모든 파일 추가
print("\n[3/5] 모든 변경사항 스테이징...")
subprocess.run(['git', 'add', '.'], timeout=30)

# 4️⃣ 커밋
print("\n[4/5] 커밋...")
subprocess.run(['git', 'commit', '-m', '🤖 JARVIS LUNA 대시보드 배포: 실제 데이터 자동 로드'], timeout=30)

# 5️⃣ 푸시
print("\n[5/5] GitHub에 푸시...")
subprocess.run(['git', 'push', 'origin', 'main'], timeout=60)

print("\n" + "="*70)
print("✅ 모든 작업 완료!")
print("="*70)
print("📱 대시보드 확인: https://coar0000-wq.github.io/jarvis-luna/")
print("⏱️  업데이트 시간: 1-2분 (캐시 반영)")
print("🔄 강력 새로고침: Ctrl+Shift+R")
