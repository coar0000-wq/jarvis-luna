@echo off
chcp 65001 >nul
cd /d "C:\Users\Desktop\Claude\Projects\kms"
echo.
echo 🤖 자비스 - 스마트 배경 제거 시작
echo.
python smart_background_removal.py
echo.
echo 완료! localhost:8000을 새로고침하세요 (Ctrl+F5)
echo.
pause
