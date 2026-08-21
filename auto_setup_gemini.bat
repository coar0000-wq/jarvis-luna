@echo off
REM 🤖 JARVIS Gemini API Key 자동 등록
REM GitHub CLI 사용

setlocal enabledelayedexpansion

echo.
echo ================================================
echo  🤖 JARVIS 자동화 시스템
echo  📝 Gemini API Key 자동 등록
echo ================================================
echo.

REM GitHub CLI 확인
echo [1/5] GitHub CLI 확인 중...
gh --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ❌ GitHub CLI가 설치되지 않았습니다.
    echo.
    echo 💡 설치 방법:
    echo    1. https://cli.github.com/ 방문
    echo    2. 설치 파일 다운로드 및 실행
    echo    3. 또는 PowerShell에서: choco install gh
    echo.
    pause
    exit /b 1
)
echo ✅ GitHub CLI 설치됨
echo.

REM GitHub 인증 확인
echo [2/5] GitHub 인증 확인 중...
gh auth status >nul 2>&1
if errorlevel 1 (
    echo.
    echo ❌ GitHub 인증이 필요합니다.
    echo.
    echo 명령어를 실행하세요:
    echo    gh auth login
    echo.
    pause
    exit /b 1
)
echo ✅ GitHub 인증 완료
echo.

REM API 키 설정
echo [3/5] Gemini API Key 설정 중...
set API_KEY=AQ.Ab8RN6Locpw6kQHtQioDsZrwFj7NZ6yn-4bxY-UuFfpjWN2adg
set REPO=coar0000/kms
echo ✅ API Key: %API_KEY:~0,20%...
echo ✅ Repository: %REPO%
echo.

REM Secrets 등록
echo [4/5] GitHub Secrets 등록 중...
echo !API_KEY! | gh secret set GEMINI_API_KEY -R %REPO%
if errorlevel 1 (
    echo.
    echo ❌ Secrets 등록 실패
    echo.
    echo 수동 등록:
    echo https://github.com/%REPO%/settings/secrets/actions
    echo.
    pause
    exit /b 1
)
echo ✅ GEMINI_API_KEY 등록 완료
echo.

REM 등록 확인
echo [5/5] 등록 확인 중...
timeout /t 2 /nobreak >nul
gh secret list -R %REPO% | find "GEMINI_API_KEY" >nul
if errorlevel 1 (
    echo ⚠️  확인 대기 중...
) else (
    echo ✅ 등록 검증 완료
)
echo.

REM 완료
echo ================================================
echo ✅ 모든 작업 완료!
echo ================================================
echo.
echo 📋 다음 단계:
echo   1. 약 1-2분 후 GitHub Actions 자동 실행
echo   2. 매 10분마다 자동 반복
echo   3. cumulative_products.json 업데이트 확인
echo.
echo 🔗 GitHub Actions 모니터링:
echo   https://github.com/%REPO%/actions
echo.
echo 🔗 설정 확인:
echo   https://github.com/%REPO%/settings/secrets/actions
echo.
pause
