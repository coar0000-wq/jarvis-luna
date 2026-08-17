#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔧 JARVIS 자동 복구 시스템 (개선버전)
30분마다 자동으로 에러를 감지하고 수정합니다
⚠️ 규칙: 거짓 데이터 금지 / 프로그래밍 에러는 자동 수정 / 시스템 에러도 자동 복구
"""

import json
from datetime import datetime, timezone
from pathlib import Path
import sys


def check_and_recover():
    """JARVIS 시스템 헬스 체크 & 자동 복구"""
    print("🔧 JARVIS 자동 복구 시스템 시작...")
    now_utc = datetime.now(timezone.utc)
    print(f"⏰ {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print()

    fixed_issues = []
    critical_issues = []

    # 1️⃣ 필수 디렉토리 자동 생성
    print("1️⃣ 필수 디렉토리 확인...")
    required_dirs = ['data', 'scripts', '.github/workflows']
    for dir_path in required_dirs:
        if not Path(dir_path).exists():
            Path(dir_path).mkdir(parents=True, exist_ok=True)
            fixed_issues.append(f"✅ 디렉토리 자동 생성: {dir_path}")
            print(f"   ✅ 생성: {dir_path}")
        else:
            print(f"   ✅ 정상: {dir_path}")

    # 2️⃣ 데이터 파일 체크
    print("\n2️⃣ 데이터 파일 확인...")
    log_file = Path('data/jarvis_work_detailed_log.json')

    if not log_file.exists():
        critical_issues.append("❌ 데이터 파일 없음 (GitHub Actions 미실행)")
        print("   ❌ jarvis_work_detailed_log.json 없음")
        print("      → GitHub Actions가 실행되지 않음")
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

            if time_diff > 30:
                critical_issues.append(f"⚠️ 데이터 {time_diff:.0f}분 전 (GitHub Actions 미실행)")
                print(f"   ⚠️ 데이터 {time_diff:.0f}분 이전")
            else:
                print(f"   ✅ 데이터 최신: {time_diff:.1f}분 전")

            completed = len(data.get('completed_today', []))
            print(f"   ✅ 작업 로그: {completed}개")

        except json.JSONDecodeError:
            # JSON 손상 시 기본값으로 복구
            print("   ⚠️ JSON 파일 손상 - 복구 중...")
            create_default_log()
            fixed_issues.append("✅ JSON 파일 자동 복구")
            print("   ✅ 복구 완료")
        except Exception as e:
            critical_issues.append(f"❌ 파일 읽기 오류: {str(e)}")
            print(f"   ❌ 오류: {str(e)}")

    # 3️⃣ 스크립트 파일 확인
    print("\n3️⃣ 스크립트 파일 확인...")
    scripts = [
        'scripts/collect_moe_papers.py',
        'scripts/youtube_moe_analysis.py',
        'scripts/youtube_dropshipping_analysis.py',
        'scripts/google_search_data_collection.py',
        'scripts/moe_neural_network.py',
        'scripts/moe_training.py',
        'scripts/record_task_result.py'
    ]

    missing = [s for s in scripts if not Path(s).exists()]
    if missing:
        critical_issues.append(f"❌ {len(missing)}개 스크립트 누락")
        for script in missing:
            print(f"   ❌ {script} 없음")
    else:
        print(f"   ✅ 모든 스크립트 정상 ({len(scripts)}개)")

    # 4️⃣ 워크플로우 파일 확인
    print("\n4️⃣ 워크플로우 파일 확인...")
    workflows = [
        '.github/workflows/jarvis_final_automation.yml',
        '.github/workflows/jarvis_health_monitor.yml'
    ]

    for workflow in workflows:
        if Path(workflow).exists():
            print(f"   ✅ {workflow}")
        else:
            critical_issues.append(f"❌ 워크플로우 없음: {workflow}")
            print(f"   ❌ {workflow} 없음")

    # 최종 보고
    print("\n" + "="*60)
    print("🔧 자동 복구 결과")
    print("="*60)

    if fixed_issues:
        print(f"\n✅ 수정된 항목 ({len(fixed_issues)}개):")
        for issue in fixed_issues:
            print(f"   {issue}")

    if critical_issues:
        print(f"\n⚠️ 조치 필요 ({len(critical_issues)}개):")
        for issue in critical_issues:
            print(f"   {issue}")
        print("\n💡 해결 방법:")
        print("   • GitHub Actions 워크플로우 로그 확인")
        print("   • jarvis_final_automation.yml 수동 실행")
        print("   • 스크립트 파일 복구 필요")
    else:
        print("✅ 모든 시스템 정상!")

    print("="*60)
    return len(critical_issues) == 0


def create_default_log():
    """기본 로그 파일 생성 (JSON 손상 시 복구용)"""
    now_utc = datetime.now(timezone.utc)
    default = {
        "timestamp": now_utc.isoformat(),
        "current_date": now_utc.strftime("%Y-%m-%d"),
        "completed_today": [],
        "status": "복구됨"
    }
    with open('data/jarvis_work_detailed_log.json', 'w', encoding='utf-8') as f:
        json.dump(default, f, indent=2, ensure_ascii=False)


if __name__ == '__main__':
    success = check_and_recover()
    sys.exit(0 if success else 1)
