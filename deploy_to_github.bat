@echo off
REM JARVIS LUNA - Automated GitHub Deployment
REM This script commits and pushes changes to GitHub

chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo ========================================
echo  🤖 JARVIS LUNA - Auto Deploy
echo ========================================
echo.

cd /d "C:\Users\Desktop\Claude\Projects\kms"

REM Check git status
echo [1/4] Checking Git Status...
git status

REM Add all files
echo.
echo [2/4] Staging all changes...
git add -A

REM Commit changes
echo.
echo [3/4] Creating commit...
git commit -m "🎨 JARVIS Overnight Design + GitHub Pages Setup - $(date '+%%Y-%%m-%%d %%H:%%M:%%S')"

REM Push to GitHub
echo.
echo [4/4] Pushing to GitHub...
git push origin main

echo.
echo ========================================
echo  ✅ Deployment Complete!
echo ========================================
echo.
echo GitHub Repository: https://github.com/coar0000-wq/jarvis-luna
echo.
echo Next step: Enable GitHub Pages in Settings
echo - Settings → Pages
echo - Source: Deploy from a branch (main / root)
echo.
pause
