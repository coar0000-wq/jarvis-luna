@echo off
chcp 65001 >nul
cd /d "C:\Users\Desktop\Claude\Projects\kms"
echo.
echo 🤖 AI 기반 배경 제거 중...
echo (첫 실행 시 rembg 라이브러리 자동 설치)
echo.
python remove_bg_ai.py
echo.
pause
