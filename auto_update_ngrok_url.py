#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ngrok HTTPS 터널링 URL 자동 감지 및 대시보드 업데이트
"""
import subprocess
import re
import time
import os

print("=" * 70)
print("🚀 ngrok 터널링 자동 설정")
print("=" * 70)
print()

# Step 1: ngrok 설치 확인
print("✅ ngrok 설치 확인 중...")
result = subprocess.run(['where', 'ngrok'], capture_output=True, text=True)
if result.returncode != 0:
    print("❌ ngrok이 설치되지 않았습니다!")
    print()
    print("설치 방법:")
    print("1. https://ngrok.com/download 에서 다운로드")
    print("2. 압축 해제 후 PATH에 추가")
    print("3. 계정 만들기: https://dashboard.ngrok.com")
    print("4. 인증: ngrok config add-authtoken YOUR_TOKEN")
    print()
    input("Press Enter to exit...")
    exit(1)

print("✅ ngrok 설치됨!")
print()

# Step 2: ngrok 터널 시작
print("🔗 localhost:8001 터널 시작 중...")
print("   (이 창을 닫지 마세요)")
print()

try:
    # ngrok 프로세스 시작
    proc = subprocess.Popen(
        ['ngrok', 'http', '8001'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    ngrok_url = None
    timeout = time.time() + 10  # 10초 타임아웃

    # ngrok URL 찾기
    for line in proc.stdout:
        print(f"[ngrok] {line.strip()}")

        # HTTPS URL 패턴 매칭
        if 'https://' in line and 'ngrok' in line:
            match = re.search(r'(https://[a-zA-Z0-9\-]+\.ngrok[\w\-\.]+)', line)
            if match:
                ngrok_url = match.group(1)
                print()
                print("=" * 70)
                print("✅ 터널 생성 완료!")
                print("=" * 70)
                print()
                print(f"🔐 외부 접속 주소: {ngrok_url}")
                print()
                break

        if time.time() > timeout:
            break

    if ngrok_url:
        print("💡 다음 단계:")
        print("1. index.html의 fetch 주소 변경:")
        print(f"   fetch('{ngrok_url}/api/stats')")
        print()
        print("2. GitHub에 푸시")
        print()
        print("3. https://coar0000-wq.github.io/jarvis-agi/ 접속")
        print()
        print("🛑 터널을 종료하려면 이 창을 닫으세요.")

        # 프로세스 계속 실행
        proc.wait()
    else:
        print("❌ 터널 URL을 찾을 수 없습니다.")
        proc.terminate()

except KeyboardInterrupt:
    print("\n🛑 터널링 중단됨")
    proc.terminate()
except Exception as e:
    print(f"❌ 오류: {e}")
