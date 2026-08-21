#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JARVIS 자동 Git Push 스크립트
작업: index.html을 kms에서 jarvis-agi-repo로 복사 후 GitHub에 푸시
"""

import shutil
import subprocess
import os
import sys

def run_command(cmd, description):
    """명령 실행 및 상태 출력"""
    try:
        print(f"⏳ {description}...")
        result = subprocess.run(cmd, shell=True, cwd=r"C:\Users\Desktop\Claude\Projects\jarvis-agi-repo",
                              capture_output=True, text=True, encoding='utf-8')

        if result.returncode == 0:
            print(f"✅ {description} 완료")
            if result.stdout:
                print(f"   출력: {result.stdout.strip()[:100]}")
            return True
        else:
            print(f"❌ {description} 실패")
            if result.stderr:
                print(f"   에러: {result.stderr.strip()[:100]}")
            return False
    except Exception as e:
        print(f"❌ {description} 중 오류: {str(e)}")
        return False

def main():
    print("=" * 60)
    print("🤖 JARVIS 자동 Git Push 시작!")
    print("=" * 60)

    # 1. 파일 복사
    try:
        src = r"C:\Users\Desktop\Claude\Projects\kms\index.html"
        dst = r"C:\Users\Desktop\Claude\Projects\jarvis-agi-repo\index.html"
        shutil.copy2(src, dst)
        print("✅ index.html 파일 복사 완료")
    except Exception as e:
        print(f"❌ 파일 복사 실패: {str(e)}")
        return False

    # 2. Git Add
    if not run_command("git add index.html", "git add"):
        return False

    # 3. Git Commit
    if not run_command('git commit -m "🎨 Fix: 박스창 고정, 이미지는 cover로 꽉 채우기"', "git commit"):
        return False

    # 4. Git Push
    if not run_command("git push origin main", "git push"):
        return False

    print("=" * 60)
    print("🎉 모든 작업 완료! GitHub에 배포되었습니다!")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
