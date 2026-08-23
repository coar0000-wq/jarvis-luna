@echo off
REM Obsidian 볼트 동기화. 더블클릭하거나 작업 스케줄러가 호출한다.
cd /d "C:\Users\Desktop\Claude\Projects\kms\jarvis-luna"
python "automation\vault_sync.py"
