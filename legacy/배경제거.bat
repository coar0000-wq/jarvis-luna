@echo off
chcp 65001 >nul
cd /d "C:\Users\Desktop\Claude\Projects\kms"
echo.
echo 🐕 16개 이미지 배경 제거 중...
echo.
python remove_background_all.py
echo.
pause
