#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import subprocess
import os

os.chdir(r'C:\Users\Desktop\Claude\Projects\kms')

print("\n🔍 Git 히스토리 확인...")
print("=" * 70)

# 최근 30개 커밋 확인
result = subprocess.run(
    ['git', 'log', '--oneline', '-30'],
    capture_output=True,
    text=True
)

print("📋 최근 커밋 히스토리:")
print(result.stdout)

# HEAD~1부터 HEAD~10까지 각 버전의 index.html 크기 확인
print("\n" + "=" * 70)
print("각 버전의 index.html 파일 크기 및 내용 확인:")
print("=" * 70)

for i in range(1, 11):
    try:
        show_result = subprocess.run(
            ['git', 'show', f'HEAD~{i}:index.html'],
            capture_output=True,
            text=True,
            timeout=5
        )

        if show_result.returncode == 0:
            content = show_result.stdout
            size = len(content)

            # 주요 특징 확인
            has_character = 'character' in content.lower() or 'svg' in content.lower() or '<circle' in content.lower()
            has_dog_image = 'dog' in content.lower()
            has_agi_evolution = 'AGI Evolution' in content
            has_task_log = '작업 상세 로그' in content
            has_doohyeon = '도현' in content

            print(f"\n✅ HEAD~{i}: 크기={size} bytes")
            print(f"   - SVG/character: {has_character}")
            print(f"   - dog image: {has_dog_image}")
            print(f"   - AGI Evolution: {has_agi_evolution}")
            print(f"   - 작업 상세 로그: {has_task_log}")
            print(f"   - 도현: {has_doohyeon}")

            # 기본 정보
            if "<!DOCTYPE" in content[:100]:
                title_start = content.find('<title>') + 7
                title_end = content.find('</title>')
                title = content[title_start:title_end] if title_start > 6 else "Unknown"
                print(f"   - 제목: {title}")
    except Exception as e:
        pass

print("\n" + "=" * 70)
