@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "LOG_DIR=%SCRIPT_DIR%logs"
set "LOG_FILE=%LOG_DIR%\obsidian_sync.log"
set "CONFIG=%SCRIPT_DIR%obsidian_sync_config.json"
set "PYTHON_CMD=py -3"

if not exist "%CONFIG%" (
  echo [ERROR] obsidian_sync_config.json is missing.
  echo Copy obsidian_sync_config.example.json, then set vault_path to the actual Obsidian vault path.
  exit /b 1
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

%PYTHON_CMD% "%SCRIPT_DIR%obsidian_github_sync.py" --config "%CONFIG%" >> "%LOG_FILE%" 2>&1
set "RESULT=%ERRORLEVEL%"

if not "%RESULT%"=="0" (
  echo [ERROR] Synchronization failed. Log: "%LOG_FILE%"
  exit /b %RESULT%
)

echo [OK] Obsidian and GitHub synchronization completed.
exit /b 0
