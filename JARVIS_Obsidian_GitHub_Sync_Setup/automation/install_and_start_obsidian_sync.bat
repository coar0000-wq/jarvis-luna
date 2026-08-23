@echo off
setlocal EnableExtensions

rem Run this file from the extracted setup package's automation folder.
set "SETUP_AUTOMATION_DIR=%~dp0"
for %%I in ("%SETUP_AUTOMATION_DIR%..\..") do set "BASE_DIR=%%~fI"
set "TARGET_DIR=%BASE_DIR%\jarvis-luna"
set "REPOSITORY_URL=https://github.com/coar0000-wq/jarvis-luna.git"
set "CONFIG_SOURCE=%SETUP_AUTOMATION_DIR%obsidian_sync_config.json"
set "CONFIG_TARGET=%TARGET_DIR%\automation\obsidian_sync_config.json"

where git >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Git is not installed. Install Git for Windows, then run this file again.
  exit /b 1
)

py -3 --version >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python 3 is not installed. Install Python 3, then run this file again.
  exit /b 1
)

if not exist "%CONFIG_SOURCE%" (
  echo [ERROR] Personal Obsidian configuration not found: "%CONFIG_SOURCE%"
  exit /b 1
)

if exist "%TARGET_DIR%\.git" (
  echo [INFO] Updating the existing JARVIS LUNA repository.
  git -C "%TARGET_DIR%" pull --ff-only
  if errorlevel 1 (
    echo [ERROR] Cannot update the existing repository. Check its Git status.
    exit /b 1
  )
) else (
  if exist "%TARGET_DIR%" (
    echo [ERROR] "%TARGET_DIR%" already exists but is not a Git repository.
    echo Rename or delete that folder, then run this file again.
    exit /b 1
  )
  echo [INFO] Downloading the JARVIS LUNA repository.
  git clone --branch main "%REPOSITORY_URL%" "%TARGET_DIR%"
  if errorlevel 1 (
    echo [ERROR] Repository download failed. Check network and GitHub access.
    exit /b 1
  )
)

copy /Y "%CONFIG_SOURCE%" "%CONFIG_TARGET%" >nul
if errorlevel 1 (
  echo [ERROR] Cannot copy the personal configuration into the repository.
  exit /b 1
)

echo [INFO] Running the first Obsidian to GitHub synchronization.
call "%TARGET_DIR%\automation\run_obsidian_sync.bat"
if errorlevel 1 (
  echo [ERROR] First synchronization failed.
  echo Check this log: "%TARGET_DIR%\automation\logs\obsidian_sync.log"
  exit /b 1
)

echo [INFO] Registering the 5-minute Windows scheduled task.
powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET_DIR%\automation\register_obsidian_sync_task.ps1"
if errorlevel 1 (
  echo [ERROR] Windows scheduled task registration failed.
  exit /b 1
)

echo.
echo [OK] Installation and first synchronization completed.
echo [OK] Repository: "%TARGET_DIR%"
echo [OK] Obsidian workspace: "C:\Users\Desktop\Obsidian\JARVIS_LUNA"
echo [OK] Future synchronization interval: 5 minutes.
exit /b 0
