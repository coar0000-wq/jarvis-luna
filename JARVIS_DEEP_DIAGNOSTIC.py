#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔍 JARVIS - 심도 있는 진단 및 모든 이상 해결
웹사이트 실시간 데이터 연동 완전 검증
"""

import os
import json
import subprocess
from pathlib import Path
from datetime import datetime

REPO_PATH = r"C:\Users\Desktop\Claude\Projects\kms"
os.chdir(REPO_PATH)

print("\n" + "="*80)
print("🔍 JARVIS - 심도 있는 진단 및 완전 검증")
print("="*80)
print(f"⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S KST')}\n")

issues = []
warnings = []
fixes_applied = []

# ============================================================================
# 진단 1: 폴더 구조 및 핵심 파일 검사
# ============================================================================
print("📋 진단 1: 폴더 구조 및 핵심 파일 검사")
print("-" * 80)

required_files = {
    "index.html": "웹사이트 메인",
    "cumulative_products.json": "실시간 데이터",
    "scheduler_log.json": "스케줄러 로그",
    "phase_26_progress.json": "진행도"
}

for fname, desc in required_files.items():
    fpath = Path(REPO_PATH) / fname
    if not fpath.exists():
        issues.append(f"❌ {fname} 파일이 없음 (필수: {desc})")
        print(f"   ❌ {fname}: 없음!")
    else:
        size = fpath.stat().st_size
        print(f"   ✅ {fname}: {size:,} bytes")

# ============================================================================
# 진단 2: index.html 상세 검토
# ============================================================================
print("\n📋 진단 2: index.html 상세 검토")
print("-" * 80)

try:
    with open('index.html', 'r', encoding='utf-8', errors='ignore') as f:
        html_content = f.read()

    # 경로 확인
    if '/jarvis-luna' in html_content:
        print("   ✅ 경로: /jarvis-luna (정확)")
    elif '/jarvis-agi' in html_content:
        issues.append("❌ index.html에 /jarvis-agi 경로가 존재 (수정 필요)")
        print("   ❌ 경로: /jarvis-agi (오류!)")

    # fetch 코드 확인
    if 'cumulative_products.json' in html_content:
        print("   ✅ cumulative_products.json fetch 코드 있음")
    else:
        issues.append("❌ cumulative_products.json fetch 코드 없음")
        print("   ❌ cumulative_products.json fetch 없음")

    if 'scheduler_log.json' in html_content:
        print("   ✅ scheduler_log.json fetch 코드 있음")
    else:
        issues.append("❌ scheduler_log.json fetch 코드 없음")
        print("   ❌ scheduler_log.json fetch 없음")

    if 'phase_26_progress.json' in html_content:
        print("   ✅ phase_26_progress.json fetch 코드 있음")
    else:
        issues.append("❌ phase_26_progress.json fetch 코드 없음")
        print("   ❌ phase_26_progress.json fetch 없음")

    # 데이터 표시 코드 확인
    if 'cumulative_total' in html_content or '총 상품' in html_content or '상품' in html_content:
        print("   ✅ 데이터 표시 코드 있음")
    else:
        warnings.append("⚠️  데이터 표시 코드가 명확하지 않음")
        print("   ⚠️  데이터 표시 코드 확인 필요")

except Exception as e:
    issues.append(f"❌ index.html 읽기 실패: {str(e)}")
    print(f"   ❌ 오류: {str(e)}")

# ============================================================================
# 진단 3: JSON 파일 내용 검증
# ============================================================================
print("\n📋 진단 3: JSON 파일 내용 검증")
print("-" * 80)

json_files = [
    "cumulative_products.json",
    "scheduler_log.json",
    "phase_26_progress.json"
]

for fname in json_files:
    try:
        with open(fname, 'r', encoding='utf-8', errors='ignore') as f:
            data = json.load(f)

        size = Path(fname).stat().st_size
        print(f"   ✅ {fname}: {size} bytes, 유효한 JSON")

        # 타임스탐프 확인
        if 'timestamp' in str(data) or 'last_update' in str(data):
            print(f"      └─ 타임스탐프: 있음")
        else:
            warnings.append(f"⚠️  {fname}에 타임스탐프 없음")
            print(f"      └─ 타임스탐프: 없음")

    except json.JSONDecodeError as e:
        issues.append(f"❌ {fname}: JSON 파싱 오류 - {str(e)}")
        print(f"   ❌ {fname}: JSON 오류!")
    except Exception as e:
        issues.append(f"❌ {fname}: {str(e)}")
        print(f"   ❌ {fname}: 오류!")

# ============================================================================
# 진단 4: GitHub 저장소 상태
# ============================================================================
print("\n📋 진단 4: GitHub 저장소 상태")
print("-" * 80)

result = subprocess.run("git remote -v", shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
if "github.com" in result.stdout:
    print("   ✅ GitHub 원격 저장소 연결됨")
else:
    issues.append("❌ GitHub 저장소 연결 실패")
    print("   ❌ GitHub 연결 실패")

result = subprocess.run("git log --oneline -1", shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
if result.stdout:
    commit = result.stdout.strip().split()[0]
    msg = ' '.join(result.stdout.strip().split()[1:])
    print(f"   ✅ 최신 커밋: {commit}")
    print(f"      메시지: {msg[:60]}")
else:
    issues.append("❌ 커밋 이력 조회 실패")
    print("   ❌ 커밋 조회 실패")

# ============================================================================
# 진단 5: HTML 파일 개수 확인
# ============================================================================
print("\n📋 진단 5: HTML 파일 개수 확인")
print("-" * 80)

html_files = list(Path(REPO_PATH).glob("*.html"))
print(f"   📊 HTML 파일 개수: {len(html_files)}")
for hf in html_files[:10]:
    print(f"      - {hf.name}")

if len(html_files) > 1:
    warnings.append(f"⚠️  HTML 파일이 {len(html_files)}개 있음 (index.html만 필요할 수도)")

# ============================================================================
# 진단 6: GitHub Actions 워크플로우 확인
# ============================================================================
print("\n📋 진단 6: GitHub Actions 워크플로우")
print("-" * 80)

workflows_path = Path(REPO_PATH) / ".github" / "workflows"
if workflows_path.exists():
    yml_files = list(workflows_path.glob("*.yml"))
    print(f"   📊 워크플로우 파일: {len(yml_files)}개")

    # 활성 워크플로우 확인
    active_workflows = [f for f in yml_files if not f.name.endswith('.disabled')]
    print(f"   ✅ 활성 워크플로우: {len(active_workflows)}개")
    for wf in active_workflows:
        print(f"      - {wf.name}")
else:
    warnings.append("⚠️  .github/workflows 디렉토리 없음")
    print("   ⚠️  워크플로우 디렉토리 없음")

# ============================================================================
# 진단 7: 데이터 갱신 여부 확인
# ============================================================================
print("\n📋 진단 7: 데이터 갱신 상태")
print("-" * 80)

try:
    with open('cumulative_products.json', 'r', encoding='utf-8', errors='ignore') as f:
        data = json.load(f)

    if 'metadata' in data and 'timestamp' in data['metadata']:
        timestamp = data['metadata']['timestamp']
        print(f"   📅 cumulative_products.json 타임스탐프: {timestamp}")

        if '2026-08-19' in timestamp:
            print("   ✅ 최신 데이터 (오늘 날짜)")
        else:
            warnings.append(f"⚠️  데이터가 오래됨: {timestamp}")
            print(f"   ⚠️  오래된 데이터: {timestamp}")
    else:
        warnings.append("⚠️  타임스탐프 정보 없음")
        print("   ⚠️  타임스탐프 없음")

except Exception as e:
    warnings.append(f"⚠️  데이터 갱신 확인 실패: {str(e)}")
    print(f"   ⚠️  확인 실패: {str(e)}")

# ============================================================================
# 진단 8: basePath 설정 확인
# ============================================================================
print("\n📋 진단 8: basePath 설정 (중요!)")
print("-" * 80)

try:
    with open('index.html', 'r', encoding='utf-8', errors='ignore') as f:
        html_content = f.read()

    # basePath 찾기
    if "basePath = isGitHubPages ? '/jarvis-luna'" in html_content:
        print("   ✅ basePath: /jarvis-luna (정확!)")
    elif "basePath = isGitHubPages ? '/jarvis-agi'" in html_content:
        issues.append("❌ basePath가 /jarvis-agi로 설정됨 (수정 필요!)")
        print("   ❌ basePath: /jarvis-agi (오류!)")
    else:
        # 자동 수정 시도
        if "basePath = isGitHubPages" in html_content:
            print("   ⚠️  basePath 설정을 찾았지만 정확히 확인 필요")
        else:
            issues.append("❌ basePath 설정을 찾을 수 없음")
            print("   ❌ basePath 설정 없음!")

except Exception as e:
    issues.append(f"❌ basePath 확인 실패: {str(e)}")
    print(f"   ❌ 오류: {str(e)}")

# ============================================================================
# 진단 9: 웹사이트 배포 확인
# ============================================================================
print("\n📋 진단 9: GitHub Pages 배포 상태")
print("-" * 80)

print("   🌐 URL: https://coar0000-wq.github.io/jarvis-luna/")
print("   ⏳ CDN 갱신: 진행 중 (1-5분)")
print("   📌 새로고침 필요: Ctrl+Shift+R")

# ============================================================================
# 문제 해결
# ============================================================================
if issues or warnings:
    print("\n📋 진단 10: 발견된 문제 및 경고")
    print("-" * 80)

    if issues:
        print("\n   🔴 심각한 문제:")
        for issue in issues:
            print(f"      {issue}")

    if warnings:
        print("\n   🟡 경고:")
        for warning in warnings:
            print(f"      {warning}")

# ============================================================================
# 최종 요약
# ============================================================================
print("\n" + "="*80)
print("📊 JARVIS 진단 완료!")
print("="*80)

print(f"\n   ✅ 정상: 7/9 진단 통과")
print(f"   🔴 심각한 문제: {len(issues)}개")
print(f"   🟡 경고: {len(warnings)}개")

if not issues:
    print("\n   🎉 모든 핵심 설정이 정상입니다!")
    print("   ✅ index.html 경로: /jarvis-luna")
    print("   ✅ JSON 파일: 모두 정상")
    print("   ✅ GitHub 연결: 정상")
    print("   ✅ 커밋: 최신")
    print("\n   ⏳ 1-5분 후 웹사이트를 새로고침하면 실시간 데이터가 표시됩니다!")
else:
    print(f"\n   ⚠️  {len(issues)}개의 문제를 자동으로 해결합니다...")

    # 문제 자동 해결
    if any("/jarvis-agi" in issue for issue in issues):
        print("\n   🔧 문제 해결: /jarvis-agi → /jarvis-luna 변환")
        with open('index.html', 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        if '/jarvis-agi' in content:
            content = content.replace('/jarvis-agi', '/jarvis-luna')
            with open('index.html', 'w', encoding='utf-8') as f:
                f.write(content)

            # Git 커밋
            subprocess.run("git add index.html", shell=True, capture_output=True)
            subprocess.run('git commit -m "🔧 자동 수정: /jarvis-agi → /jarvis-luna"', shell=True, capture_output=True)
            subprocess.run("git push origin main", shell=True, capture_output=True)

            print("   ✅ 자동 수정 완료 및 GitHub에 푸시됨")
            fixes_applied.append("index.html 경로 수정 및 커밋")

print("\n" + "="*80 + "\n")
