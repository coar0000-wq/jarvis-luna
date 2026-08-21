#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 JARVIS 자동화 스케줄러
로컬 머신에서 모든 자동화 작업 관리
매 10분마다 다이소 상품 발굴
"""
import schedule
import time
import subprocess
import os
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# UTF-8 콘솔 출력 설정 (Windows에서 이모지 지원)
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


class JARVISScheduler:
    """JARVIS 자동화 스케줄러"""

    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.log_file = self.base_dir / "data" / "scheduler_log.json"
        self.is_running = False

    def run_daiso_discovery(self):
        """다이소 상품 발굴 실행"""
        try:
            print(f"\n[{datetime.now(timezone.utc).isoformat()}] 🛍️ 다이소 상품 발굴 시작...")
            result = subprocess.run(
                ["python", str(self.base_dir / "daiso_product_discovery.py")],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=60
            )
            if result.returncode == 0:
                print("✅ 다이소 발굴 완료")
                self.log_event("daiso_discovery", "success")
            else:
                print(f"❌ 다이소 발굴 실패: {result.stderr}")
                self.log_event("daiso_discovery", "failed", result.stderr)
        except Exception as e:
            print(f"❌ 다이소 발굴 오류: {e}")
            self.log_event("daiso_discovery", "error", str(e))

    def check_obsidian_server(self):
        """JARVIS API 서버 상태 확인 (포트 5000)"""
        try:
            import requests
            response = requests.get("http://localhost:5000/health", timeout=5)
            if response.status_code == 200:
                print(f"[{datetime.now(timezone.utc).isoformat()}] ✅ JARVIS API 서버 정상")
                self.log_event("obsidian_check", "online")
            else:
                print(f"⚠️ JARVIS API 서버 응답 비정상 ({response.status_code})")
                self.log_event("obsidian_check", "offline")
                self.restart_obsidian_server()
        except Exception as e:
            print(f"⚠️ JARVIS API 서버 다운 감지, 재시작 시도...")
            self.log_event("obsidian_check", "down", str(e))
            self.restart_obsidian_server()

    def restart_obsidian_server(self):
        """JARVIS API 서버 재시작"""
        try:
            print("🔄 JARVIS API 서버 재시작 중...")
            os.system('taskkill /F /IM python.exe /FI "WINDOWTITLE eq *api_server*" 2>nul')
            time.sleep(2)

            subprocess.Popen(
                ["python", str(self.base_dir / "api_server.py")],
                cwd=str(self.base_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(3)
            print("✅ JARVIS API 서버 재시작 완료")
            self.log_event("obsidian_restart", "success")
        except Exception as e:
            print(f"❌ JARVIS API 서버 재시작 실패: {e}")
            self.log_event("obsidian_restart", "failed", str(e))

    def log_event(self, event_type, status, details=""):
        """이벤트 로그"""
        try:
            log_data = {
                "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                "event_type": event_type,
                "status": status,
                "details": details
            }

            if self.log_file.exists():
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            else:
                logs = {"events": []}

            logs["events"].append(log_data)

            if len(logs["events"]) > 1000:
                logs["events"] = logs["events"][-1000:]

            with open(self.log_file, 'w', encoding='utf-8') as f:
                json.dump(logs, f, ensure_ascii=False, indent=2)

            self.push_to_github()
        except Exception as e:
            print(f"로그 저장 오류: {e}")

    def push_to_github(self):
        """GitHub에 데이터 자동 푸시"""
        try:
            os.chdir(str(self.base_dir))
            os.system("git add data/daiso_products.json data/scheduler_log.json index.html 2>nul")
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            os.system(f'git commit -m "🤖 JARVIS 자동화: 다이소 상품 발굴 + 실시간 데이터 (매 10분, {timestamp})" 2>nul')
            result = os.system("git push origin main 2>nul")
            if result == 0:
                print("✅ GitHub 푸시 완료")
            else:
                print("⚠️ GitHub 푸시 실패 (오프라인 또는 인증 문제)")
        except Exception as e:
            print(f"GitHub 푸시 오류: {e}")

    def start(self):
        """스케줄러 시작"""
        print("\n" + "=" * 60)
        print("🤖 JARVIS 자동화 스케줄러 시작")
        print("=" * 60)

        schedule.every(10).minutes.do(self.run_daiso_discovery)
        schedule.every(15).minutes.do(self.check_obsidian_server)

        print(f"✅ 매 10분마다: 다이소 상품 발굴")
        print(f"✅ 매 15분마다: JARVIS API 서버 모니터링 (포트 5000)")
        print(f"✅ 시작 시간: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print("=" * 60 + "\n")

        self.is_running = True

        print("🚀 초기 작업 실행...")
        self.run_daiso_discovery()
        self.check_obsidian_server()

        while self.is_running:
            try:
                schedule.run_pending()
                time.sleep(60)
            except KeyboardInterrupt:
                print("\n\n🛑 스케줄러 중지됨")
                self.is_running = False
            except Exception as e:
                print(f"❌ 스케줄러 오류: {e}")
                time.sleep(60)


if __name__ == "__main__":
    scheduler = JARVISScheduler()

    try:
        import schedule
    except ImportError:
        print("📦 schedule 라이브러리 설치 중...")
        os.system("pip install schedule --break-system-packages")

    scheduler.start()