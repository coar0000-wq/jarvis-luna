#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏥 JARVIS 헬스 체크 스크립트 (개선버전)
자동화 시스템이 정상 작동하는지 모니터링 - UTC 기반
"""

import json
from datetime import datetime, timezone
from pathlib import Path
import sys


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
    else:
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # UTC 기반 타임스탐프 처리
            timestamp_str = data.get('timestamp', '')
            if timestamp_str.endswith('Z'):
                timestamp_str = timestamp_str.replace('Z', '+00:00')

            file_time = datetime.fromisoformat(timestamp_str)

            # UTC 시간으로 비교
            if file_time.tzinfo is None:
                file_time = file_time.replace(tzinfo=timezone.utc)

            time_diff = (now_utc - file_time).total_seconds() / 60

            if time_diff > 30:  # 30분 이상
                issues.append(f"⚠️ 데이터 오래됨: {time_diff:.0f}분 전")
                print(f"   ⚠️ 마지막 업데이트: {time_diff:.0f}분 전")
            else:
                print(f"   ✅ 데이터 최신: {time_diff:.1f}분 전")

            # completed_today 확인
            completed = len(data.get('completed_today', []))
            if completed == 0:
                print(f"   ⚠️ 완료된 작업: 0개 (아직 실행 안 됨)")
            else:
                print(f"   ✅ 완료된 작업: {completed}개")

        except json.JSONDecodeError as e:
            issues.append(f"❌ JSON 파일 손상: {str(e)}")
            print(f"   ❌ JSON 손상")
        except Exception as e:
            issues.append(f"❌ 파일 읽기 오류: {str(e)}")
            print(f"   ❌ 오류: {str(e)}")

    # 2️⃣ 스크립트 파일 확인
    print("\n2️⃣ 스크립트 파일 확인...")
    scripts = [
        'scripts/collect_moe_papers.py',
        'scripts/youtube_moe_analysis.py',
        'scripts/youtube_dropshipping_analysis.py',
        'scripts/google_search_data_collection.py',
        'scripts/moe_neural_network.py',
        'scripts/moe_training.py',
        'scripts/record_task_result.py'
    ]

    missing_scripts = []
    for script in scripts:
        if not Path(script).exists():
            missing_scripts.append(script)
            issues.append(f"❌ {script} 파일 없음")

    if not missing_scripts:
        print(f"   ✅ 모든 스크립트 있음 ({len(scripts)}개)")
    else:
        print(f"   ❌ 빠진 스크립트: {len(missing_scripts)}개")

    # 3️⃣ 워크플로우 파일 확인
    print("\n3️⃣ 워크플로우 파일 확인...")
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
        print("✅ 모든 시스템 정상! JARVIS 자동화가 제대로 작동 중입니다.")
        return_code = 0
    else:
        print(f"⚠️ 주의: {len(issues)}개 문제 발견")
        for i, issue in enumerate(issues, 1):
            print(f"   {i}. {issue}")
        return_code = 1

    print("="*60)
    print()

    return return_code == 0


if __name__ == '__main__':
    success = check_jarvis_health()
    sys.exit(0 if success else 1)
