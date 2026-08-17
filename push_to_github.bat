@echo off
chcp 65001 > nul
cd /d C:\Users\Desktop\Claude\Projects\kms

echo ========================================
echo JARVIS LUNA - GitHub Pages Push
echo ========================================
echo.
echo 1. Adding files...
git add index.html dashboard.html data/

echo.
echo 2. Committing changes...
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c-%%a-%%b)
for /f "tokens=1-2 delims=/:" %%a in ('time /t') do (set mytime=%%a%%b)
git commit -m "JARVIS LUNA - GitHub Pages Deploy (index.html + dashboard) - %mydate% %mytime%"

echo.
echo 3. Pushing to GitHub...
git push origin main

echo.
echo ========================================
echo Push Complete!
echo ========================================
echo.
echo Website URL: https://coar0000-wq.github.io/jarvis-luna/
echo (Build in progress... wait 5-10 minutes)
echo.
pause
