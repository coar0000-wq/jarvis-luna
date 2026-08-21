@echo off
chcp 65001 >nul
cd /d "C:\Users\Desktop\Claude\Projects\kms"
echo.
echo 🔍 이미지 배경 색상 분석 중...
echo.
python analyze_image.py
echo.
pause
