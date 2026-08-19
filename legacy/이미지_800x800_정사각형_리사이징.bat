@echo off
chcp 65001 >nul
cd /d "C:\Users\Desktop\Claude\Projects\kms"
echo.
echo ========================================
echo 🖼️  이미지 사이즈 확대 (2번부터는 2배)
echo ========================================
echo.
echo 1번: 원본 크기 유지
echo 2번~16번: 1번의 2배 크기로 확대합니다...
echo.
python resize_images_enlarge_from_2.py
echo.
pause
