@echo off
REM ============================================================================
REM 🤖 JARVIS - Phase 26 Real-time Data Push to GitHub
REM ============================================================================
REM Windows 배치 파일로 Python 스크립트 실행
REM
REM 사용법: run_push_realtime_data.bat
REM ============================================================================

cd /d "C:\Users\Desktop\Claude\Projects\kms"

echo.
echo ================================================================================
echo 🚀 JARVIS 자동화 작업 시작
echo ================================================================================
echo.
echo 📅 작업 시간: %DATE% %TIME%
echo 📂 작업 경로: C:\Users\Desktop\Claude\Projects\kms
echo.

REM Python 스크립트 실행 (UTF-8 인코딩)
python push_realtime_data.py

REM 결과 확인
if %ERRORLEVEL% EQU 0 (
    echo.
    echo ================================================================================
    echo ✅ JARVIS 작업 완료!
    echo ================================================================================
    echo.
    echo 📊 GitHub 푸시 상태: 성공
    echo 🌐 대시보드 URL: https://coar0000-wq.github.io/jarvis-agi/
    echo ⏰ CDN 캐시 업데이트 대기: 1-5분
    echo.
    pause
) else (
    echo.
    echo ================================================================================
    echo ⚠️  작업 완료 (확인 필요)
    echo ================================================================================
    echo.
    echo 📊 GitHub 푸시 상태: 검증 필요
    echo 🔍 위의 로그를 확인하세요
    echo.
    pause
)
