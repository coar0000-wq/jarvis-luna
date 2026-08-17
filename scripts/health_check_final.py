#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏥 JARVIS 최종 헬스 체크 (UTC 기반)
자동화 시스템이 정상 작동하는지 검증
"""

import json
from datetime import datetime, timezone
from pathlib import Path
import sys


def parse_iso_timestamp(ts_str: str) -> datetime:
    """ISO 8601 타임스탐프를 파싱 (UTC 기반)"""
    try:
        # Z 형식 처리
        if ts_str.endswith('Z'):
            ts_str = ts_str.replace('Z', '+00:00')

        # +00:00 형식으로 파싱
        dt = datetime.fromisoformat(ts_str)

        # timezone-aware 확인
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt
    except Exception as e:
        print(f"⚠️ 타임스탐프 파싱 오류: {ts_str} - {str(e)}")
        return None


def check_jarvis_health():
    """JARVIS 자동화 시스템 헬스 체크"""
    print("🏥 JARVIS 헬스 체크 시작...")
    now_utc = datetime.now(timezone.utc)
    print(f"⏰ {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print()

    issues = []

    # 1️⃣ 데이터 파일 확인
    print("1️⃣ 데이터 파일 확인...")
    log_file = Path('data/jarvis_work_detailed_log.json')

    if not log_file.exists():
        issues.append("❌ jarvis_work_detailed_log.json 파일 없음")
        print("   ❌ 파일 없음")
        return len(issues) == 0

    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 타임스탐프 파싱
        timestamp_str = data.get('timestamp', '')
        file_time = parse_iso_timestamp(timestamp_str)

        if file_time is None:
            issues.append("❌ 타임스탐프 형식 오류")
            print(f"   ❌ 타임스탐프 형식: {timestamp_str}")
        else:
            # UTC 기준 시간 차이 계산
            time_diff = (now_utc - file_time).total_seconds() / 60

            if time_diff > 30:
                issues.append(f"⚠️ 데이터 오래됨: {time_diff:.1f}분 전")
                print(f"   ⚠️ 마지막 업데이트: {time_diff:.1f}분 전")
            elif time_diff < 0:
                issues.append(f"⚠️ 미래 타임스탐프: {time_diff:.1f}분")
                print(f"   ⚠️ 타임스탐프가 미래: {time_diff:.1f}분")
            else:
                print(f"   ✅ 데이터 최신: {time_diff:.1f}분 전")

        # completed_today 확인
        completed = len(data.get('completed_today', []))
        if completed == 0:
            print(f"   ⚠️ 완료된 작업: 0개")
        else:
            print(f"   ✅ 완료된 작업: {completed}개")

    except json.JSONDecodeError as e:
        issues.append(f"❌ JSON 파일 손상: {str(e)}")
        print(f"   ❌ JSON 손상")
    except Exception as e:
        issues.append(f"❌ 파일 읽기 오류: {str(e)}")
        print(f"   ❌ 오류: {str(e)}")

    # 2️⃣ 스크립트 파일 확인
    print("\n2️⃣ 필수 파일 확인...")
    required_files = [
        'scripts/collect_moe_papers.py',
        'scripts/youtube_moe_analysis.py',
        'scripts/youtube_dropshipping_analysis.py',
        'scripts/google_search_data_collection.py',
        'scripts/moe_neural_network.py',
        'scripts/moe_training.py',
        'scripts/record_task_result.py'
    ]

    missing = []
    for file_path in required_files:
        if not Path(file_path).exists():
            missing.append(file_path)
            issues.append(f"❌ {file_path} 없음")

    if not missing:
        print(f"   ✅ 모든 스크립트 있음 ({len(required_files)}개)")
    else:
        print(f"   ❌ 빠진 파일: {len(missing)}개")

    # 3️⃣ 워크플로우 파일 확인
    print("\n3️⃣ GitHub Actions 워크플로우 확인...")
    workflows = [
        '.github/workflows/jarvis_final_automation.yml',
        '.github/workflows/jarvis_health_monitor.yml'
    ]

    for workflow in workflows:
        if Path(workflow).exists():
            print(f"   ✅ {workflow}")
        else:
            issues.append(f"❌ {workflow} 없음")
            print(f"   ❌ {workflow} 없음")

    # 최종 보고
    print("\n" + "="*60)
    print("📊 헬스 체크 결과")
    print("="*60)

    if not issues:
        print("✅ 모든 시스템 정상!")
        return_code = 0
    else:
        print(f"⚠️ 문제 발견: {len(issues)}개")
        for i, issue in enumerate(issues, 1):
            print(f"   {i}. {issue}")
        return_code = 1

    print("="*60)
    print()

    return return_code == 0


if __name__ == '__main__':
    success = check_jarvis_health()
    sys.exit(0 if success else 1)
