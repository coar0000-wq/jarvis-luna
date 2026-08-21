@echo off
setlocal EnableExtensions

rem This installer is designed to run from the extracted setup package's automation folder.
set "SETUP_AUTOMATION_DIR=%~dp0"
set "SETUP_ROOT=%SETUP_AUTOMATION_DIR%.."
set "BASE_DIR=%USERPROFILE%\Desktop\Claude\Projects\kms"
set "TARGET_DIR=%BASE_DIR%\jarvis-luna"
set "REPOSITORY_URL=https://github.com/coar0000-wq/jarvis-luna.git"
set "CONFIG_SOURCE=%SETUP_AUTOMATION_DIR%obsidian_sync_config.json"
set "CONFIG_TARGET=%TARGET_DIR%\automation\obsidian_sync_config.json"

where git >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Git이 설치되어 있지 않습니다. Git for Windows를 설치한 뒤 다시 실행하세요.
  exit /b 1
)

py -3 --version >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python 3이 설치되어 있지 않습니다. Python 3을 설치한 뒤 다시 실행하세요.
  exit /b 1
)

if not exist "%CONFIG_SOURCE%" (
  echo [ERROR] 개인 Obsidian 설정 파일을 찾을 수 없습니다: "%CONFIG_SOURCE%"
  exit /b 1
)

if exist "%TARGET_DIR%\.git" (
  echo [INFO] 기존 JARVIS LUNA 저장소를 최신 상태로 갱신합니다.
  git -C "%TARGET_DIR%" pull --ff-only
  if errorlevel 1 (
    echo [ERROR] 기존 저장소 갱신에 실패했습니다. Git 상태를 확인하세요.
    exit /b 1
  )
) else (
  if exist "%TARGET_DIR%" (
    echo [ERROR] "%TARGET_DIR%" 폴더가 이미 존재하지만 Git 저장소가 아닙니다.
    echo 폴더 이름을 바꾸거나 삭제한 뒤 다시 실행하세요.
    exit /b 1
  )
  echo [INFO] JARVIS LUNA 저장소를 내려받습니다.
  git clone --branch main "%REPOSITORY_URL%" "%TARGET_DIR%"
  if errorlevel 1 (
    echo [ERROR] 저장소 다운로드에 실패했습니다. 인터넷 연결과 GitHub 접근 권한을 확인하세요.
    exit /b 1
  )
)

copy /Y "%CONFIG_SOURCE%" "%CONFIG_TARGET%" >nul
if errorlevel 1 (
  echo [ERROR] 개인 설정 파일을 저장소에 복사하지 못했습니다.
  exit /b 1
)

echo [INFO] 첫 Obsidian ↔ GitHub 동기화를 실행합니다.
call "%TARGET_DIR%\automation\run_obsidian_sync.bat"
if errorlevel 1 (
  echo [ERROR] 첫 동기화에 실패했습니다.
  echo 로그 확인: "%TARGET_DIR%\automation\logs\obsidian_sync.log"
  exit /b 1
)

echo [INFO] 5분 자동 동기화 작업을 등록합니다.
powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET_DIR%\automation\register_obsidian_sync_task.ps1"
if errorlevel 1 (
  echo [ERROR] Windows 자동 실행 등록에 실패했습니다.
  exit /b 1
)

echo.
echo [OK] 설치와 첫 동기화가 완료되었습니다.
echo [OK] 저장소: "%TARGET_DIR%"
echo [OK] Obsidian 작업 폴더: "C:\Users\Desktop\Obsidian\JARVIS_LUNA"
echo [OK] 이후 5분마다 자동 동기화됩니다.
exit /b 0
