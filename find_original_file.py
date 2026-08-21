#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import subprocess
import os

os.chdir(r'C:\Users\Desktop\Claude\Projects\kms')

print("Git 히스토리 확인 중...")

# 최근 20개 커밋의 index.html 특징 확인
for i in range(1, 21):
    try:
        result = subprocess.run(
            ['git', 'show', f'HEAD~{i}:index.html'],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            content = result.stdout
            size = len(content)

            # 주요 특징 확인
            checks = {
                'character/dog/svg': 'character' in content.lower() or 'dog' in content.lower() or '<circle' in content,
                'AGI Evolution': 'AGI Evolution' in content,
                '작업 상세 로그': '작업 상세 로그' in content,
                '도현': '도현' in content,
                '팀원 실시간 상태': '팀원 실시간 상태' in content,
            }

            match_count = sum(1 for v in checks.values() if v)

            print(f"\n[HEAD~{i}] 크기={size} | 매치={match_count}/5")
            for key, val in checks.items():
                print(f"  {key}: {'✅' if val else '❌'}")

            # 모든 특징이 있으면 저장
            if match_count == 5 or match_count >= 4:
                print(f"\n⭐ 원래 파일 후보: HEAD~{i}")
                with open('original_index_HEAD~' + str(i) + '.html', 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"저장됨: original_index_HEAD~{i}.html")

    except Exception as e:
        print(f"[HEAD~{i}] 오류: {e}")

print("\n완료!")
