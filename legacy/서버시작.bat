@echo off
chcp 65001 >nul
cd /d "C:\Users\Desktop\Claude\Projects\kms"
echo.
echo ========================================
echo 🚀 JARVIS LUNA 웹서버 시작
echo ========================================
echo.
echo http://localhost:8000 에서 접속하세요!
echo.
echo (종료하려면 이 창을 닫으세요)
echo.
echo ========================================
echo.
python -m http.server 8000
