@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

cd /d "C:\Users\Desktop\Claude\Projects\kms"

echo.
echo ================================================================================
echo 🔥 JARVIS - 웹사이트 경로 자동 수정
echo ================================================================================
echo.

REM Step 1: 상태 확인
echo ✅ Step 1: 변경사항 상태 확인
git status -s
echo.

REM Step 2: 스테이징 및 커밋
echo ✅ Step 2: GitHub에 커밋
git add index.html
git commit -m "🔥 FIX: 웹사이트 경로 jarvis-agi → jarvis-luna (실시간 데이터 연동)"
echo.

REM Step 3: Pull
echo ✅ Step 3: 최신 변경사항 동기화
git pull --rebase origin main
echo.

REM Step 4: Push
echo ✅ Step 4: GitHub에 푸시
git push origin main
echo.

REM Step 5: 최종 확인
echo ✅ Step 5: 최종 상태 확인
git log --oneline -3
echo.
git status
echo.

echo ================================================================================
echo ✅ 웹사이트 경로 수정 완료!
echo ================================================================================
echo.
echo 🌐 다음 단계:
echo    1. GitHub Pages CDN 갱신 대기 (1-5분)
echo    2. https://coar0000-wq.github.io/jarvis-luna/ 새로고침
echo    3. 데이터가 정상 표시되는지 확인
echo.
echo ================================================================================
echo.
