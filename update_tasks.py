#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 JARVIS 자동 작업 진행도 업데이트 스크립트
GitHub Actions에서 매 1분마다 실행됨
"""

import json
import random
from datetime import datetime

DATA_FILE = './data/tasks.json'

def update_tasks_progress():
    """작업 진행도 자동 업데이트"""
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print("❌ tasks.json 파일을 찾을 수 없습니다")
        return False

    print("=" * 60)
    print("🤖 [JARVIS] 자동 작업 진행도 업데이트")
    print("=" * 60)

    updated_count = 0

    # 각 작업의 진행도 증가 (무작위: 1-3%)
    for task in data['tasks']:
        current_progress = task.get('progress', 0)

        # 완료되지 않은 작업만 진행도 증가
        if current_progress < 100:
            increase = random.randint(1, 3)
            new_progress = min(100, current_progress + increase)
            task['progress'] = new_progress
            task['updated'] = datetime.now().isoformat() + 'Z'

            status = "✅ 완료" if new_progress == 100 else "⏳ 진행중"
            print(f"  {task['name']}: {current_progress}% → {new_progress}% ({status})")

            updated_count += 1
        else:
            print(f"  {task['name']}: {current_progress}% (✅ 완료됨)")

    # 전체 업데이트 시간
    data['lastUpdate'] = datetime.now().isoformat() + 'Z'

    # JSON 파일 저장
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print()
        print(f"✅ 총 {updated_count}개 작업 업데이트됨")
        print(f"📍 마지막 업데이트: {data['lastUpdate']}")
        print("=" * 60)
        return True
    except Exception as e:
        print(f"❌ 파일 저장 실패: {e}")
        return False

if __name__ == '__main__':
    success = update_tasks_progress()
    exit(0 if success else 1)
