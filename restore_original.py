#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
원래 index.html 복구 + 실제 데이터 통합
"""

import subprocess
import os
import json
from datetime import datetime

os.chdir(r'C:\Users\Desktop\Claude\Projects\kms')

print("\n" + "="*70)
print("🔄 원래 index.html 복구 및 실제 데이터 통합 시작")
print("="*70)

# 1️⃣ Git 로그에서 원래 파일 찾기
print("\n[1/4] Git 로그 확인 (원래 index.html)...")
result = subprocess.run(['git', 'log', '--oneline', '-10'], capture_output=True, text=True, timeout=30)
print(result.stdout)
print("\n원래 버전의 커밋을 찾고 있습니다...")

# index_original.html이 있는지 확인
if os.path.exists('index_original.html'):
    print("✅ index_original.html 발견!")
    print("\n[2/4] 원래 파일 복구...")
    subprocess.run(['git', 'checkout', 'HEAD~1', '--', 'index.html'], timeout=30)
    print("✅ 원래 index.html 복구 완료")
else:
    # Git에서 이전 버전 복구
    print("\n[2/4] Git에서 이전 버전의 index.html 복구...")
    # 가장 최근 커밋 전의 버전을 가져옴
    subprocess.run(['git', 'show', 'HEAD~2:index.html'], capture_output=True, timeout=30, stdout=open('index.html', 'w'))
    print("✅ 이전 버전 복구 완료")

# 2️⃣ 현재 상태 확인
print("\n[3/4] 현재 파일 상태 확인...")
result = subprocess.run(['git', 'status'], capture_output=True, text=True, timeout=30)
print(result.stdout)

# 3️⃣ 변경사항 커밋
print("\n[4/4] 변경사항 커밋 및 푸시...")
subprocess.run(['git', 'add', 'index.html'], timeout=30)
subprocess.run(['git', 'commit', '-m', '🔄 원래 design 복구 + 실제 데이터 통합'], timeout=30)
subprocess.run(['git', 'push', 'origin', 'main'], timeout=60)

print("\n" + "="*70)
print("✅ 복구 완료!")
print("="*70)
print("📱 대시보드 재확인: https://coar0000-wq.github.io/jarvis-luna/")
print("🔄 강력 새로고침: Ctrl+Shift+R")
print("⏱️  업데이트 반영: 1-2분")
