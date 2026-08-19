@echo off
chcp 65001 >nul
cd /d "C:\Users\Desktop\Claude\Projects\kms"
echo.
echo 🐕 공격적인 배경 제거 - 도그만 남기고 모든 배경을 흰색으로!
echo.
python aggressive_bg_removal.py
echo.
pause
