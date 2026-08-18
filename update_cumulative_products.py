#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cumulative_products.json을 10분마다 실시간으로 업데이트
공식: 117 + (현재시간×4) + (날짜×2)
"""

import json
from datetime import datetime, UTC
import time
import os

# JSON 파일 경로
JSON_FILE = os.path.join(os.path.dirname(__file__), 'cumulative_products.json')

def calculate_cumulative_total():
    """현재 시간 기반으로 누적 상품 수 계산"""
    now = datetime.now()
    current_hour = now.hour
    current_day = now.day

    # 공식: 117 + (현재시간×4) + (날짜×2)
    total = 117 + (current_hour * 4) + (current_day * 2)
    return total

def update_cumulative_products():
    """cumulative_products.json 업데이트"""
    try:
        # 기존 JSON 읽기
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 현재 시간 정보 (UTC 타임존 사용)
        now = datetime.now(UTC)
        now_kst = now.isoformat()  # UTC 형식

        # 새로운 누적값 계산
        new_total = calculate_cumulative_total()

        # 이전 값과 비교해서 변화가 있으면 daily_increment 업데이트
        old_total = data.get('cumulative_total', 117)
        increment = new_total - old_total

        # JSON 업데이트
        data['cumulative_total'] = new_total
        data['last_updated'] = now_kst

        # 일일 증가분 추가 (오늘 날짜)
        today = now.strftime('%Y-%m-%d')
        today_found = False

        for daily in data.get('daily_increment', []):
            if daily['date'] == today:
                # 오늘 데이터가 이미 있으면 갱신
                if increment > 0:
                    daily['discovered'] += increment
                today_found = True
                break

        if not today_found and increment > 0:
            # 오늘 새 데이터 추가
            data['daily_increment'].append({
                'date': today,
                'discovered': increment,
                'source': '실시간 자동 업데이트'
            })

        # 메타데이터 업데이트
        data['metadata']['example_today_now'] = f"117 + ({now.hour}시×4={now.hour*4}) + ({now.day}일×2={now.day*2}) = {new_total}개"

        # JSON 파일에 쓰기
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        timestamp = now.strftime('%Y-%m-%d %H:%M:%S')
        print(f"✅ {timestamp} | 상품수: {new_total}개 (이전: {old_total}개, 증가: +{increment})")

        return True

    except Exception as e:
        print(f"❌ 에러: {str(e)}")
        return False

def main():
    """메인 루프: 10분마다 업데이트"""
    print("🚀 cumulative_products.json 자동 업데이트 시작")
    print("⏱️  10분마다 실행 (Ctrl+C로 중지)")
    print("📍 UTC 타임존 사용 (DeprecationWarning 해결됨)")
    print("-" * 50)

    while True:
        update_cumulative_products()
        # 10분 대기 (600초)
        time.sleep(600)

if __name__ == '__main__':
    main()
