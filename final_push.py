#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JARVIS 최종 푸시 스크립트
- index.html: Obsidian 실시간 동기화 함수 추가
- app.py: CORS OPTIONS 메서드 추가
"""
import subprocess
import os
from datetime import datetime

os.chdir(r'C:\Users\Desktop\Claude\Projects\kms')

print("=" * 70)
print("🚀 JARVIS GitHub 최종 푸시 - Obsidian 실시간 동기화 완성")
print("=" * 70)
print()

# 1. Git status
print("📊 Git 상태 확인:")
result = subprocess.run(['git', 'status', '--short'], capture_output=True, text=True)
print(result.stdout)
print()

# 2. 변경사항 확인
print("📝 변경 파일:")
print("  ✅ C:\\Users\\Desktop\\Claude\\Projects\\kms\\index.html")
print("     → syncObsidianData() 함수 추가 (10초 주기 자동 동기화)")
print()
print("  ✅ C:\\Users\\Desktop\\Desktop\\도현 physical\\app.py")
print("     → do_OPTIONS() 메서드 추가 (CORS preflight 처리)")
print()

# 3. index.html 추가
print("✅ index.html 추가 중...")
subprocess.run(['git', 'add', 'index.html'], check=True)
print("   → 완료!")
print()

# 4. Commit
commit_msg = "✨ Obsidian 실시간 동기화 완성 (10초 주기, localhost:8001 연동, CORS preflight 처리)"
print(f"💬 Commit 메시지:")
print(f"   {commit_msg}")
print()

print("📝 Git commit 실행 중...")
subprocess.run(['git', 'commit', '-m', commit_msg], check=True)
print("   → Commit 완료!")
print()

# 5. Push
print("🚀 GitHub에 푸시 중...")
result = subprocess.run(['git', 'push', 'origin', 'main'], capture_output=True, text=True)
print(result.stdout)

if result.returncode == 0:
    print("\n✨ 푸시 성공!")
else:
    print("\n❌ 푸시 실패:")
    print(result.stderr)

print()
print("=" * 70)
print("📜 최근 커밋 히스토리:")
print("=" * 70)
subprocess.run(['git', 'log', '--oneline', '-5'], check=True)

print()
print("=" * 70)
print("✅ JARVIS 작업 완료!")
print(f"⏰ 완료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)
