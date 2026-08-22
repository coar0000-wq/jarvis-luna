@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

rem JARVIS repository root = folder containing this BAT file
set "REPO=%~dp0"
cd /d "%REPO%"

echo.
echo ==============================================
echo   JARVIS real-data pipeline
echo ==============================================
echo   Repository: %REPO%
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not on PATH.
    pause
    exit /b 1
)

set "MISSING=0"
for %%F in (
    "obsidian.py"
    "scripts\normalize_obsidian_links.py"
    "scripts\generate_dashboard_runtime.py"
    "scripts\update_dashboard_runtime_real.py"
    "scripts\validate_dashboard_runtime.py"
    "organize_obsidian_graph.py"
    "tune_real_knowledge_moe.py"
    "train_real_knowledge.py"
) do (
    if not exist "%%~F" (
        echo [ERROR] Missing: %%~F
        set "MISSING=1"
    )
)
if "%MISSING%"=="1" (
    echo.
    echo Required files are missing. Download or copy them into this repository first.
    pause
    exit /b 1
)

if not exist "data\knowledge\training_corpus.jsonl" (
    echo [ERROR] Missing real corpus: data\knowledge\training_corpus.jsonl
    pause
    exit /b 1
)

echo Select execution mode:
echo   [1] Sync real records and update dashboard runtime
echo   [2] Sync records, retrain/promote 3-expert MoE, update runtime
echo   [3] Exit
choice /c 123 /n /m "Choose 1, 2, or 3: "
if errorlevel 3 exit /b 0
if errorlevel 2 goto REFRESH_MOE
if errorlevel 1 goto STANDARD

:STANDARD
echo.
echo [1/3] Synchronizing real records with Obsidian graph...
python "%REPO%obsidian.py"
if errorlevel 1 goto FAILED

echo [2/3] Updating dashboard_runtime.json...
python "%REPO%scripts\update_dashboard_runtime_real.py"
if errorlevel 1 goto FAILED

echo [3/3] Validating Obsidian graph and dashboard runtime...
python "%REPO%scripts\validate_dashboard_runtime.py"
if errorlevel 1 goto FAILED
goto SUCCESS

:REFRESH_MOE
echo.
echo [1/3] Synchronizing real records with Obsidian graph...
python "%REPO%obsidian.py"
if errorlevel 1 goto FAILED

echo [2/3] Retraining and promoting the real-data 3-expert MoE...
python "%REPO%scripts\update_dashboard_runtime_real.py" --refresh-moe --steps 500
if errorlevel 1 goto FAILED

echo [3/3] Validating Obsidian graph and dashboard runtime...
python "%REPO%scripts\validate_dashboard_runtime.py"
if errorlevel 1 goto FAILED

goto SUCCESS

:SUCCESS
echo.
echo ==============================================
echo   JARVIS pipeline completed successfully
echo ==============================================
echo.
echo Runtime file:
echo   %REPO%data\dashboard_runtime.json
echo.
findstr /r /c:"generated_at" /c:"notes" /c:"links" /c:"dangling_links" /c:"experts" /c:"tuning_promoted" "%REPO%data\dashboard_runtime.json"
echo.
echo GitHub Pages dashboard:
echo   https://coar0000-wq.github.io/jarvis-luna/
echo.
pause
exit /b 0

:FAILED
echo.
echo [ERROR] JARVIS pipeline failed. Review the error above.
echo The runtime was not reported as successful unless validation passed.
pause
exit /b 1
