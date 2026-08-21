@echo off
chcp 65001 >nul
cd /d "C:\Users\Desktop\Claude\Projects\kms"
echo.
echo 🐕 최종 배경 제거
echo.
python final_cleanup.py
echo.
pause
