@echo off
chcp 65001 > nul
cd /d C:\Users\Desktop\Claude\Projects\kms
echo.
echo ========================================
echo 🚀 JARVIS: Git Pull + Push 실행 중...
echo ========================================
echo.
git pull origin main
echo.
git push origin main
echo.
echo ========================================
echo 🎉 배포 완료!
echo ========================================
pause
