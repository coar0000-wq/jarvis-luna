@echo off
REM ngrok 터널링 자동화 스크립트
REM 로컬 app.py 서버를 HTTPS로 공개하고 대시보드 업데이트

echo ========================================
echo 🚀 ngrok 터널링 자동화 시작
echo ========================================
echo.

REM ngrok 설치 확인
where ngrok >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ ngrok이 설치되지 않았습니다.
    echo.
    echo 설치 방법:
    echo 1. https://ngrok.com/download 에서 다운로드
    echo 2. 압축 해제 후 ngrok.exe를 PATH에 추가
    echo 3. 계정 만들기: https://dashboard.ngrok.com
    echo 4. 인증: ngrok config add-authtoken YOUR_TOKEN
    echo.
    pause
    exit /b 1
)

echo ✅ ngrok 설치 확인됨!
echo.

echo 🔗 localhost:8001에서 HTTPS 터널 생성 중...
echo.

REM ngrok 터널 시작 및 URL 캡처
for /f "tokens=*" %%i in ('ngrok http 8001 --log=stdout 2^>^&1 ^| findstr /R "https://.*ngrok"') do (
    set "NGROK_URL=%%i"
    goto :found
)

:found
if defined NGROK_URL (
    echo ✅ 터널 생성 완료!
    echo.
    echo 🔐 외부 접속 주소:
    echo    %NGROK_URL%
    echo.
    echo 💡 이 주소를 index.html의 API 요청에 사용하세요!
    echo.
    echo 대시보드 주소: https://coar0000-wq.github.io/jarvis-agi/
    echo.
    echo 🛑 터널을 종료하려면: Ctrl+C
    echo.
) else (
    echo ❌ 터널 생성 실패
    pause
    exit /b 1
)

REM ngrok 터널 유지
pause
