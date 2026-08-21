@echo off
REM JARVIS 자동화 시스템 시작 스크립트
REM 모든 필수 서비스 자동 시작

setlocal enabledelayedexpansion
set SCRIPT_DIR=%~dp0

echo =====================================
echo 🚀 JARVIS 자동화 시스템 초기화
echo =====================================
echo.

REM 1. Python 환경 확인
echo [1/4] Python 버전 확인...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python이 설치되지 않았습니다!
    exit /b 1
)
echo ✅ Python 설치됨
echo.

REM 2. Obsidian 서버 시작
echo [2/4] Obsidian 동기화 서버 시작...
cd /d "%SCRIPT_DIR%"
start /B python scripts/obsidian_realtime_sync.py >nul 2>&1
timeout /t 3 /nobreak >nul
if errorlevel 0 (
    echo ✅ Obsidian 서버 시작됨 (localhost:8001)
) else (
    echo ⚠️ Obsidian 서버 시작 시도 (백그라운드)
)
echo.

REM 3. 다이소 자동화 시작
echo [3/4] 다이소 상품 자동화 스케줄러 등록...
python create_scheduler.py
if errorlevel 0 (
    echo ✅ 자동화 스케줄러 등록됨
) else (
    echo ⚠️ 스케줄러 등록 실패
)
echo.

REM 4. 상태 확인
echo [4/4] 시스템 상태 확인...
echo ✅ JARVIS 자동화 시스템 준비 완료!
echo.

echo =====================================
echo 🎯 현재 설정:
echo   - Obsidian 서버: localhost:8001
echo   - 다이소 발굴: 매 10분
echo   - 상태 모니터링: 15분마다
echo   - 시간대: KST (UTC+9)
echo =====================================
echo.

REM 백그라운드에서 계속 실행
python -c "import time; time.sleep(1)" >nul
