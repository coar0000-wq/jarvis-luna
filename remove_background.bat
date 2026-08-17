@echo off
chcp 65001 >nul
cd /d "C:\Users\Desktop\Claude\Projects\kms"
echo 🐕 이미지 배경 제거 중...
python remove_white_background.py
pause
