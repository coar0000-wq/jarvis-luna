@echo off
REM 로컬 HTTP 서버 시작 및 대시보드 자동 열기
cd /d C:\Users\Desktop\Claude\Projects\kms

echo ========================================
echo 🚀 로컬 HTTP 서버 시작 중...
echo ========================================
echo.

REM Python이 설치되어 있는지 확인
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python이 설치되지 않았습니다.
    echo Python을 설치해주세요: https://www.python.org
    pause
    exit /b 1
)

REM 포트 8000에서 HTTP 서버 시작
echo ✅ 포트 8000에서 서버 시작...
echo.
echo 📱 접속 주소: http://localhost:8000
echo.
echo 🔗 Obsidian 서버 (localhost:8001)와 연동 중...
echo.
echo 🛑 중지하려면: Ctrl+C 누르기
echo.

REM Chrome 자동 열기
timeout /t 2 /nobreak
start "" "https://coar0000-wq.github.io/jarvis-agi/"
timeout /t 1 /nobreak
start "" "http://localhost:8000"

REM 서버 시작
python -m http.server 8000
