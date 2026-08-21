#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JARVIS LUNA - Obsidian 동기화 스크립트
작업상세로그 데이터를 Obsidian 그래프뷰에 자동 저장
"""

import json
import os
from datetime import datetime
from pathlib import Path

# 경로 설정
JARVIS_LOG_PATH = "data/jarvis_work_detailed_log.json"
OBSIDIAN_BASE = r"C:\Users\Desktop\Obsidian"
OBSIDIAN_JARVIS_DIR = os.path.join(OBSIDIAN_BASE, "JARVIS", "tasks")
OBSIDIAN_STATS_FILE = os.path.join(OBSIDIAN_BASE, "JARVIS", "JARVIS_자동화_통계.md")

def ensure_obsidian_dir():
    """Obsidian 디렉토리 생성"""
    os.makedirs(OBSIDIAN_JARVIS_DIR, exist_ok=True)
    print(f"✅ Obsidian 디렉토리 확인: {OBSIDIAN_JARVIS_DIR}")

def get_utc_timestamp():
    """UTC 현재 시간"""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00")

def get_today_date():
    """오늘 날짜 (YYYY-MM-DD)"""
    return datetime.utcnow().strftime("%Y-%m-%d")

def categorize_task(task_name):
    """작업 이름으로 카테고리 추출"""
    task_lower = task_name.lower()
    if "arxiv" in task_lower:
        return "arXiv", "arXiv 논문 수집"
    elif "youtube moe" in task_lower:
        return "YouTube MoE", "YouTube MoE 분석"
    elif "dropshipping" in task_lower:
        return "Dropshipping", "드롭쉬핑 영상 분석"
    elif "google" in task_lower:
        return "Google", "Google 검색 데이터"
    elif "신경망" in task_lower or "neural" in task_lower:
        return "Neural Network", "신경망 훈련"
    else:
        return "Other", "기타"

def create_task_entry(task):
    """개별 작업 항목을 마크다운으로 변환"""
    task_id = task.get("id", "unknown")
    task_name = task.get("task", "작업")
    status = task.get("status", "❌ 실패")
    duration = task.get("duration", "0초")
    data_collected = task.get("data_collected", "0개")
    result = task.get("result", "실패")
    start_time = task.get("start_time", "")
    end_time = task.get("end_time", "")

    # 카테고리 추출
    category_tag, category_kr = categorize_task(task_name)

    # 마크다운 포맷
    md_content = f"""## {status} {task_name}

**ID**: `{task_id}`
**카테고리**: [[{category_tag}]]
**결과**: {result}

### 실행 정보
- **시작**: {start_time}
- **종료**: {end_time}
- **소요 시간**: {duration}
- **수집 데이터**: {data_collected}

**태그**: #자동화 #작업로그 #{category_tag.lower().replace(' ', '-')}

---
"""
    return md_content

def create_daily_report(tasks_data):
    """일일 작업 보고서 생성"""
    today = get_today_date()
    daily_file = os.path.join(OBSIDIAN_JARVIS_DIR, f"{today}.md")

    # 프론트매터
    frontmatter = f"""---
created: {get_utc_timestamp()}
updated: {get_utc_timestamp()}
date: {today}
type: daily-report
status: 자동화 완료
---

# JARVIS 자동화 일일 보고서

**날짜**: {today} (UTC)
**생성 시간**: {get_utc_timestamp()}

"""

    # 통계
    completed_tasks = tasks_data.get("completed_today", [])
    total_tasks = len(completed_tasks)
    success_count = sum(1 for t in completed_tasks if "완료" in t.get("status", ""))

    stats_section = f"""## 📊 일일 통계

| 항목 | 값 |
|------|-----|
| 총 작업 수 | {total_tasks} |
| 성공 | {success_count} |
| 실패 | {total_tasks - success_count} |
| 수집 데이터 | {sum(int(t.get('data_collected', '0').replace('개', '')) for t in completed_tasks):,}개 |
| 소요 시간 | {tasks_data.get('performance_metrics', {}).get('total_execution_time', 'N/A')} |

---

## 📋 작업 상세

"""

    # 개별 작업 항목
    task_details = ""
    for task in completed_tasks:
        task_details += create_task_entry(task)

    # 카테고리별 집계
    categories = {}
    for task in completed_tasks:
        category_tag, category_kr = categorize_task(task.get("task", ""))
        if category_tag not in categories:
            categories[category_tag] = 0
        try:
            count = int(task.get("data_collected", "0").replace("개", ""))
            categories[category_tag] += count
        except:
            pass

    category_section = "\n## 🏷️ 카테고리별 데이터\n\n"
    for cat, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
        category_section += f"- [[{cat}]]: {count:,}개\n"

    # 전체 마크다운
    full_content = frontmatter + stats_section + category_section + "\n" + task_details

    # 파일 저장
    with open(daily_file, 'w', encoding='utf-8') as f:
        f.write(full_content)

    print(f"✅ 일일 보고서 저장: {daily_file}")
    return daily_file

def create_statistics_page(tasks_data):
    """통계 페이지 생성 (Obsidian 홈용)"""
    completed_tasks = tasks_data.get("completed_today", [])
    total_tasks = len(completed_tasks)
    success_count = sum(1 for t in completed_tasks if "완료" in t.get("status", ""))

    # 카테고리별 통계
    categories = {}
    for task in completed_tasks:
        category_tag, _ = categorize_task(task.get("task", ""))
        if category_tag not in categories:
            categories[category_tag] = {"count": 0, "data": 0}
        categories[category_tag]["count"] += 1
        try:
            data = int(task.get("data_collected", "0").replace("개", ""))
            categories[category_tag]["data"] += data
        except:
            pass

    # 마크다운
    content = f"""---
created: {get_utc_timestamp()}
updated: {get_utc_timestamp()}
type: statistics
status: 자동화 통계
---

# 🤖 JARVIS 자동화 통계

**마지막 업데이트**: {get_utc_timestamp()}

## 📈 실시간 지표

| 지표 | 값 |
|------|-----|
| 총 작업 수 | {total_tasks} |
| 성공률 | {(success_count/total_tasks*100):.1f}% |
| 일일 데이터 수집 | {sum(int(t.get('data_collected', '0').replace('개', '')) for t in completed_tasks):,}개 |
| 자동화율 | ✅ 100% |

## 🗂️ 카테고리별 성과

"""

    for cat, stats in sorted(categories.items(), key=lambda x: x[1]["data"], reverse=True):
        content += f"### [[{cat}]]\n- 작업 수: {stats['count']}회\n- 수집 데이터: {stats['data']:,}개\n\n"

    # 관련 링크
    content += """## 📂 관련 문서

- [[JARVIS 자동화 완전완료]]
- [[JARVIS 현재 진화 상태]]

---

**자동 생성됨**: JARVIS LUNA 자동화 시스템
"""

    with open(OBSIDIAN_STATS_FILE, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"✅ 통계 페이지 저장: {OBSIDIAN_STATS_FILE}")

def load_task_data():
    """작업 데이터 로드"""
    if not os.path.exists(JARVIS_LOG_PATH):
        print(f"❌ 로그 파일 없음: {JARVIS_LOG_PATH}")
        return None

    try:
        with open(JARVIS_LOG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(f"✅ 작업 데이터 로드: {len(data.get('completed_today', []))}개 작업")
        return data
    except Exception as e:
        print(f"❌ 데이터 로드 실패: {e}")
        return None

def main():
    """메인 함수"""
    print("=" * 60)
    print("🤖 JARVIS LUNA - Obsidian 동기화 시작")
    print("=" * 60)

    # Obsidian 디렉토리 준비
    ensure_obsidian_dir()

    # 작업 데이터 로드
    tasks_data = load_task_data()
    if not tasks_data:
        print("❌ 작업 데이터 없음, 종료")
        return

    # 일일 보고서 생성
    create_daily_report(tasks_data)

    # 통계 페이지 생성
    create_statistics_page(tasks_data)

    print("=" * 60)
    print("✅ Obsidian 동기화 완료")
    print("=" * 60)

if __name__ == "__main__":
    main()
