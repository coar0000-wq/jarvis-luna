#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚀 JARVIS: Git Pull + Push 자동 실행 (동기화)
"""

import subprocess
import os
from datetime import datetime

def git_pull_push():
    """Git pull + push 실행"""
    os.chdir(r'C:\Users\Desktop\Claude\Projects\kms')

    print("\n" + "="*70)
    print("🚀 JARVIS: Git 동기화 (Pull + Push) 자동 실행")
    print("="*70)
    print(f"⏰ 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📍 작업 경로: {os.getcwd()}")

    # 1️⃣ Git pull
    print("\n[1/2] git pull origin main 실행 중...")
    result = subprocess.run(
        ['git', 'pull', 'origin', 'main'],
        capture_output=True,
        text=True,
        timeout=60
    )

    if result.returncode == 0:
        print("✅ Git pull 완료!")
        if result.stdout:
            print(f"📊 출력:\n{result.stdout}")
    else:
        print(f"⚠️  Git pull 메시지:")
        print(f"{result.stdout or result.stderr}")
        if "Already up to date" in result.stdout:
            print("✅ 이미 최신 상태입니다.")
        else:
            return False

    # 2️⃣ Git push
    print("\n[2/2] git push origin main 실행 중...")
    result = subprocess.run(
        ['git', 'push', 'origin', 'main'],
        capture_output=True,
        text=True,
        timeout=60
    )

    print("\n" + "="*70)
    print("📤 Git Push 결과")
    print("="*70)

    if result.returncode == 0:
        print("✅ Push 성공!")
        if result.stdout:
            print(f"\n📊 출력:\n{result.stdout}")
        print("\n🎉 모든 변경사항이 GitHub에 푸시되었습니다!")
        return True
    else:
        print(f"❌ Push 실패!")
        print(f"\n❌ 에러 메시지:\n{result.stderr}")
        if "Everything up-to-date" in result.stdout:
            print("\n💡 이미 모든 변경사항이 업로드되어 있습니다.")
            return True
        return False

def verify_deployment():
    """배포 검증"""
    print("\n" + "="*70)
    print("🔍 배포 상태 검증")
    print("="*70)

    # Git status 확인
    print("\n📊 최종 Git 상태...")
    result = subprocess.run(
        ['git', 'status'],
        capture_output=True,
        text=True,
        cwd=r'C:\Users\Desktop\Claude\Projects\kms'
    )

    if result.returncode == 0:
        print("✅ Git 상태:")
        for line in result.stdout.strip().split('\n')[:5]:
            print(f"   {line}")

        if "nothing to commit, working tree clean" in result.stdout:
            print("✅ 작업 폴더가 깨끗합니다!")
            return True
        else:
            print("⚠️  커밋 대기 중인 파일이 있습니다.")
            return False
    else:
        print(f"❌ 상태 확인 실패: {result.stderr}")
        return False

def main():
    """메인 함수"""
    try:
        # Git pull + push 실행
        if not git_pull_push():
            print("\n⚠️  Git 동기화 중 문제 발생했습니다.")
            return False

        # 배포 검증
        if verify_deployment():
            print("\n" + "="*70)
            print("🎉 JARVIS: 모든 작업 완료!")
            print("="*70)
            print("\n✅ 최종 상태:")
            print("   ✅ Git pull (원격 변경사항 동기화)")
            print("   ✅ Git push (로컬 변경사항 업로드)")
            print("   ✅ 배포 검증")
            print("\n📱 라이브 대시보드:")
            print("   🌐 https://coar0000-wq.github.io/jarvis-luna/")
            print("   ⏱️  업데이트: 1-2분 후 반영됨 (캐시)")
            print("   🔄 강력 새로고침: Ctrl+Shift+R")
            print("\n" + "="*70)
            return True
        else:
            print("\n⚠️  검증 완료 (경고 있음)")
            return True

    except Exception as e:
        print(f"\n❌ 에러 발생: {e}")
        return False

    finally:
        print(f"\n⏰ 완료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)
