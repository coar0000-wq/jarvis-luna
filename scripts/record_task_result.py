#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
📝 JARVIS 작업 결과 기록 스크립트
각 작업의 성공/실패를 실시간으로 JSON에 기록
⚠️ 모든 timestamp는 UTC+00:00 ISO 형식 사용
"""

import json
from datetime import datetime, timezone
from pathlib import Path
import sys


def record_task(task_name: str, status: str, data_collected: int = 0, duration_sec: int = 0, error_msg: str = ""):
    """작업 결과를 JSON에 기록

    Args:
        task_name: 작업 이름 (e.g., "arXiv MoE 논문 수집")
        status: "completed" or "failed"
        data_collected: 수집한 데이터 개수
        duration_sec: 작업 소요 시간 (초)
        error_msg: 에러 메시지
    """

    log_file = Path('data/jarvis_work_detailed_log.json')

    # UTC 기반 타임스탐프 (ISO 8601 형식)
    now_utc = datetime.now(timezone.utc)
    now_iso = now_utc.strftime('%Y-%m-%dT%H:%M:%S+00:00')

    # 기존 데이터 읽기
    if log_file.exists():
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError:
            data = create_default_log_structure(now_iso)
    else:
        data = create_default_log_structure(now_iso)

    # 새 작업 항목 생성
    task_id = f"task_{len(data['completed_today']) + 1:03d}"

    # 소요 시간 포맷팅
    if duration_sec > 0:
        minutes = duration_sec // 60
        seconds = duration_sec % 60
        duration_str = f"{minutes}분 {seconds}초" if minutes > 0 else f"{seconds}초"
    else:
        duration_str = "0초"

    task_entry = {
        "id": task_id,
        "task": task_name,
        "start_time": now_iso,
        "end_time": now_iso,
        "duration": duration_str,
        "status": "✅ 완료" if status == "completed" else "❌ 실패",
        "data_collected": f"{data_collected}개" if data_collected > 0 else "0개",
        "result": "성공" if status == "completed" else f"실패: {error_msg}"
    }

    # completed_today에 추가
    if "completed_today" not in data:
        data["completed_today"] = []

    data["completed_today"].append(task_entry)

    # timestamp 업데이트
    data["timestamp"] = now_iso
    data["current_date"] = now_utc.strftime("%Y-%m-%d")

    # 통계 업데이트
    if "performance_metrics" not in data:
        data["performance_metrics"] = {
            "total_execution_time": "0초",
            "average_task_duration": "0초",
            "success_rate": "0%",
            "data_collected": {},
            "violations_found": 0,
            "violations_rate": "0%"
        }

    # 파일 저장
    try:
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"✅ 작업 기록: {task_name} ({status})")
        return True
    except Exception as e:
        print(f"❌ 기록 실패: {str(e)}", file=sys.stderr)
        return False


def create_default_log_structure(timestamp: str) -> dict:
    """기본 로그 구조 생성 (UTC ISO 형식)"""
    date_str = timestamp.split('T')[0] if 'T' in timestamp else datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return {
        "timestamp": timestamp,
        "current_date": date_str,
        "completed_today": [],
        "performance_metrics": {
            "total_execution_time": "0초",
            "average_task_duration": "0초",
            "success_rate": "0%",
            "data_collected": {},
            "violations_found": 0,
            "violations_rate": "0%"
        },
        "status": {
            "overall": "🔄 실행 중",
            "data_collection": "대기 중",
            "automation": "대기 중",
            "verification": "대기 중",
            "deployment": "대기 중"
        }
    }


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python record_task_result.py <task_name> <status> [data_collected] [duration_sec] [error_msg]")
        sys.exit(1)

    task_name = sys.argv[1]
    status = sys.argv[2]
    data_collected = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    duration_sec = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    error_msg = sys.argv[5] if len(sys.argv) > 5 else ""

    success = record_task(task_name, status, data_collected, duration_sec, error_msg)
    sys.exit(0 if success else 1)
