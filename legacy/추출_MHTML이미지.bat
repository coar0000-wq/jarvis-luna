@echo off
chcp 65001 >nul
cd /d "C:\Users\Desktop\Claude\Projects\kms"
echo.
echo 🐕 자비스 - MHTML 파일에서 이미지 추출 중...
echo.
python 추출_MHTML이미지.py
echo.
pause
