#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Git 히스토리에서 원래 index.html 찾아 복구
"""

import subprocess
import os
import sys

os.chdir(r'C:\Users\Desktop\Claude\Projects\kms')

print("\n🔍 Git 커밋 히스토리 확인...")
print("="*70)

# Git log 확인 (최근 5개 커밋)
result = subprocess.run(
    ['git', 'log', '--oneline', '-20'],
    capture_output=True,
    text=True,
    timeout=30
)

print("📋 최근 커밋:")
print(result.stdout)

# HEAD~3 (3커밋 전) 버전의 index.html 확인
print("\n🔎 이전 버전의 index.html 확인 중...")
for i in range(1, 6):
    try:
        show_result = subprocess.run(
            ['git', 'show', f'HEAD~{i}:index.html'],
            capture_output=True,
            text=True,
            timeout=10
        )

        if show_result.returncode == 0:
            # 파일 크기와 내용 일부 확인
            size = len(show_result.stdout)
            has_dog = 'dog' in show_result.stdout.lower() or 'character' in show_result.stdout.lower()
            has_agi_evolution = 'AGI Evolution' in show_result.stdout

            print(f"\n✅ HEAD~{i}: 크기={size}bytes, AGI Evolution={has_agi_evolution}")

            if has_agi_evolution and size > 10000:
                print(f"\n🎯 HEAD~{i}가 원래 파일인 것 같습니다!")
                print("\n복구 중...")

                # 해당 버전으로 복구
                restore = subprocess.run(
                    ['git', 'checkout', f'HEAD~{i}', '--', 'index.html'],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if restore.returncode == 0:
                    print("✅ 복구 완료!")
                    print("\n현재 상태:")
                    status = subprocess.run(
                        ['git', 'status', 'index.html'],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    print(status.stdout)
                    break
    except Exception as e:
        print(f"⚠️  HEAD~{i} 확인 실패: {e}")

print("\n" + "="*70)
print("다음 단계: git add index.html && git commit -m '...' && git push")
