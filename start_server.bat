@echo off
chcp 65001 > nul

echo.
echo ============================================================
echo  🌐 JARVIS LUNA 로컬 웹 서버 시작
echo ============================================================
echo.

cd /d C:\Users\Desktop\Claude\Projects\kms

echo 📍 주소: http://localhost:8000
echo 📁 폴더: %CD%
echo.
echo ✅ 브라우저에서 http://localhost:8000 로 이동하세요
echo 💡 파일 저장 후 브라우저 새로고침(F5)하면 즉시 반영됩니다!
echo ⚠️ 서버를 종료하려면 이 창을 닫으세요
echo.
echo ============================================================
echo.

python -m http.server 8000

pause
