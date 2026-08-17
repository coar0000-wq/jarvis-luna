@echo off
chcp 65001 >nul
cd /d "C:\Users\Desktop\Claude\Projects\kms"
echo.
echo 🤖 자비스 - 이미지 파일 검증
echo.
python verify_images.py
echo.
pause
