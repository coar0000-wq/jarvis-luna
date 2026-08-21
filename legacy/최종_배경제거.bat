@echo off
chcp 65001 >nul
cd /d "C:\Users\Desktop\Claude\Projects\kms"
echo.
echo 🤖 자비스 - 최종 도그 이미지 정밀 추출
echo.
python extract_dog_images.py
echo.
echo localhost:8000 새로고침하세요!
echo.
pause
