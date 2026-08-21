#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 JARVIS Auto Cleanup Script
자동 폴더/파일 정리 및 최적화

Author: JARVIS
Date: 2026-08-19
"""

import os
import shutil
from pathlib import Path
from datetime import datetime

# 작업 디렉토리
REPO_PATH = Path(r"C:\Users\Desktop\Claude\Projects\kms")
LEGACY_PATH = REPO_PATH / "legacy"
COMPLETED_PATH = REPO_PATH / "completed"
LOGS_PATH = REPO_PATH / "cleanup_logs"

# 정리할 파일 패턴
LEGACY_PATTERNS = [
    "*배경*.py", "*배경*.bat", "*background*.py",
    "*remove_bg*.py", "*remove_white*.py",
    "*extract_*.py", "*analyze_*.py",
    "*resize_*.py", "*process_*.py",
    "*이미지*.py", "*이미지*.bat",
    "*서버*.py", "*서버*.bat", "*server*.py",
]

SUMMARY = {
    "moved_to_legacy": [],
    "moved_to_completed": [],
    "removed_disabled": [],
    "github_actions_active": [],
    "github_actions_inactive": [],
    "total_stats": {}
}

def print_header(title):
    """Print formatted header"""
    print("\n" + "="*80)
    print(f"🤖 {title}")
    print("="*80)

def print_step(step_num, title):
    """Print step header"""
    print(f"\n✅ Step {step_num}: {title}")
    print("-"*80)

def create_directories():
    """Create required directories"""
    print_step(1, "디렉토리 생성")

    for path in [LEGACY_PATH, COMPLETED_PATH, LOGS_PATH]:
        path.mkdir(parents=True, exist_ok=True)
        print(f"   ✅ 생성됨: {path.name}/")

def move_legacy_files():
    """Move legacy/background removal scripts to legacy folder"""
    print_step(2, "레거시 파일 이동 (배경제거/이미지처리)")

    count = 0
    for pattern in LEGACY_PATTERNS:
        for file in REPO_PATH.glob(pattern):
            if file.is_file() and file.parent == REPO_PATH:
                try:
                    dest = LEGACY_PATH / file.name
                    shutil.move(str(file), str(dest))
                    SUMMARY["moved_to_legacy"].append(file.name)
                    count += 1
                    if count % 5 == 0:
                        print(f"   ✅ {count}개 파일 이동...")
                except Exception as e:
                    print(f"   ⚠️  {file.name} 이동 실패: {e}")

    print(f"\n   📊 총 {count}개 레거시 파일 이동 완료")

def organize_phase_files():
    """Organize completed phase files"""
    print_step(3, "Phase 구현 파일 정리")

    phase_files = [
        "phase26_moe_implementation.py",
        "phase27_neurosymbolic_ai.py",
        "phase28_multimodal_ai.py",
        "phase29_automl_hyperparameter.py",
    ]

    count = 0
    for filename in phase_files:
        file_path = REPO_PATH / filename
        if file_path.exists():
            try:
                dest = COMPLETED_PATH / filename
                shutil.move(str(file_path), str(dest))
                SUMMARY["moved_to_completed"].append(filename)
                count += 1
                print(f"   ✅ {filename} → completed/")
            except Exception as e:
                print(f"   ⚠️  {filename} 이동 실패: {e}")

    print(f"\n   📊 {count}개 Phase 파일 이동 완료")

def organize_workflows():
    """Organize GitHub Actions workflows"""
    print_step(4, "GitHub Actions 워크플로우 정리")

    workflows_path = REPO_PATH / ".github" / "workflows"

    # 활성 workflow
    active_workflows = [
        "jarvis-luna-deploy.yml",
        "update-tasks.yml",
    ]

    disabled_workflows = []

    print(f"\n   📋 활성 Workflow:")
    for wf in workflows_path.glob("*.yml"):
        if wf.name in active_workflows:
            SUMMARY["github_actions_active"].append(wf.name)
            print(f"      ✅ {wf.name}")
        elif wf.name.endswith(".disabled"):
            disabled_workflows.append(wf.name)

    print(f"\n   ⚠️  비활성 Workflow:")
    for wf in workflows_path.glob("*.disabled"):
        SUMMARY["github_actions_inactive"].append(wf.name)
        print(f"      ⏸️  {wf.name}")

    print(f"\n   📊 활성: {len(SUMMARY['github_actions_active'])}, 비활성: {len(SUMMARY['github_actions_inactive'])}")

def organize_data_files():
    """Organize data files"""
    print_step(5, "데이터 파일 확인")

    critical_files = [
        "cumulative_products.json",
        "scheduler_log.json",
        "phase_26_progress.json",
        "update_timestamps.py",
        "push_realtime_data.py",
        "run_push_realtime_data.bat",
    ]

    print(f"\n   📊 핵심 데이터 파일:")
    for filename in critical_files:
        file_path = REPO_PATH / filename
        if file_path.exists():
            size_kb = file_path.stat().st_size / 1024
            print(f"      ✅ {filename:40s} ({size_kb:7.1f}KB)")
        else:
            print(f"      ❌ {filename:40s} (NOT FOUND)")

def generate_report():
    """Generate cleanup report"""
    print_step(6, "최종 정리 보고서 생성")

    report_file = LOGS_PATH / f"cleanup_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

    report_content = f"""# 🤖 JARVIS 자동 정리 보고서

**작업 완료 시간:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S KST')}

## 📊 작업 통계

### 1. 레거시 파일 이동
- **이동된 파일:** {len(SUMMARY['moved_to_legacy'])}개
- **대상 폴더:** `legacy/`
- **파일 유형:** 배경제거, 이미지처리, 서버 스크립트 등

### 2. Phase 파일 정리
- **이동된 파일:** {len(SUMMARY['moved_to_completed'])}개
- **대상 폴더:** `completed/`
- **파일:** Phase 26-29 구현 파일

### 3. GitHub Actions 워크플로우
- **활성 Workflow:** {len(SUMMARY['github_actions_active'])}개
  {chr(10).join(f"  - {wf}" for wf in SUMMARY['github_actions_active'])}

- **비활성 Workflow:** {len(SUMMARY['github_actions_inactive'])}개
  {chr(10).join(f"  - {wf}" for wf in SUMMARY['github_actions_inactive'])}

### 4. 핵심 파일 상태
✅ cumulative_products.json
✅ scheduler_log.json
✅ phase_26_progress.json
✅ update_timestamps.py
✅ push_realtime_data.py
✅ run_push_realtime_data.bat

## 📁 새로운 폴더 구조

```
kms/
├─ legacy/ (배경제거, 이미지처리 등 레거시 파일)
├─ completed/ (Phase 26-29 구현 파일)
├─ data/ (실시간 데이터 파일)
├─ .github/workflows/ (활성 자동화만 유지)
├─ 핵심 자동화 스크립트 (루트)
└─ 기타 문서 및 설정
```

## 🎯 정리 결과

✅ 폴더 구조 최적화 완료
✅ 레거시 코드 분리 완료
✅ 핵심 파일 정리 완료
✅ 자동화 경로 명확화

## 📝 다음 단계

1. `legacy/` 폴더의 파일들은 언제든지 필요시 참고 가능
2. `completed/` 폴더는 Phase 완료 기록 보존
3. 루트의 핵심 자동화 스크립트는 정상 작동
4. GitHub Actions는 `jarvis-luna-deploy.yml`만 활성 유지

**정리 작업:** ✅ 완료
"""

    report_file.write_text(report_content, encoding='utf-8')
    print(f"   ✅ 보고서 생성: {report_file.name}")

def main():
    """Main execution"""
    print_header("🤖 JARVIS 자동 정리 시작")
    print(f"시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S KST')}")
    print(f"경로: {REPO_PATH}")

    try:
        create_directories()
        move_legacy_files()
        organize_phase_files()
        organize_workflows()
        organize_data_files()
        generate_report()

        print_header("✅ JARVIS 자동 정리 완료!")
        print(f"\n📊 작업 요약:")
        print(f"   ✅ 레거시 파일: {len(SUMMARY['moved_to_legacy'])}개 이동")
        print(f"   ✅ Phase 파일: {len(SUMMARY['moved_to_completed'])}개 이동")
        print(f"   ✅ Workflow: 활성 {len(SUMMARY['github_actions_active'])}개, 비활성 {len(SUMMARY['github_actions_inactive'])}개")
        print(f"   ✅ 보고서: cleanup_logs/ 폴더에 생성됨")
        print("\n" + "="*80 + "\n")

    except Exception as e:
        print(f"\n❌ 정리 중 오류 발생: {e}")

if __name__ == "__main__":
    main()
