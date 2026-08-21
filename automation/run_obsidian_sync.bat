@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "LOG_DIR=%SCRIPT_DIR%logs"
set "CONFIG=%SCRIPT_DIR%obsidian_sync_config.json"
set "PYTHON_CMD=py -3"

if not exist "%CONFIG%" (
  echo [ERROR] obsidian_sync_config.json 파일이 없습니다.
  echo automation\obsidian_sync_config.example.json을 복사한 뒤 vault_path를 실제 Obsidian 볼트 경로로 바꾸세요.
  exit /b 1
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

%PYTHON_CMD% "%SCRIPT_DIR%obsidian_github_sync.py" --config "%CONFIG%" >> "%LOG_DIR%obsidian_sync.log" 2>&1
set "RESULT=%ERRORLEVEL%"

if not "%RESULT%"=="0" (
  echo [ERROR] 동기화에 실패했습니다. 로그: "%LOG_DIR%obsidian_sync.log"
  exit /b %RESULT%
)

echo [OK] Obsidian과 GitHub 동기화가 완료되었습니다.
exit /b 0
