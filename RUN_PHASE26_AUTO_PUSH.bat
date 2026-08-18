@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

cls
echo.
echo ════════════════════════════════════════════════════════════════════════════════
echo 🚀 Phase 26 MoE - Auto Push Execution
echo ════════════════════════════════════════════════════════════════════════════════
echo.
echo 📅 Timestamp: %date% %time%
echo 📂 Repository: C:\Users\Desktop\Claude\Projects\kms
echo 👤 Executor: JARVIS (Automated)
echo 📋 Task: GitHub Push + Test Execution
echo.

cd /d C:\Users\Desktop\Claude\Projects\kms

if not exist "auto_push_final.py" (
    echo ❌ ERROR: auto_push_final.py not found!
    echo 📂 Expected path: C:\Users\Desktop\Claude\Projects\kms\auto_push_final.py
    echo.
    pause
    exit /b 1
)

echo ✅ Script found. Starting execution...
echo.
echo ════════════════════════════════════════════════════════════════════════════════
echo 🧬 Executing auto_push_final.py
echo ════════════════════════════════════════════════════════════════════════════════
echo.

python auto_push_final.py

if errorlevel 0 (
    echo.
    echo ════════════════════════════════════════════════════════════════════════════════
    echo ✅ EXECUTION COMPLETED
    echo ════════════════════════════════════════════════════════════════════════════════
    echo.
    echo 📈 Next Steps:
    echo    1. Check GitHub: https://github.com/coar0000/kms/commits/main
    echo    2. Wait 1-2 minutes for GitHub Pages update
    echo    3. Verify tests passed (10/10)
    echo.
) else (
    echo.
    echo ════════════════════════════════════════════════════════════════════════════════
    echo ⚠️  EXECUTION COMPLETED WITH ISSUES
    echo ════════════════════════════════════════════════════════════════════════════════
    echo.
    echo 📋 Check output above for details
    echo.
)

pause
