@echo off
set REPO=C:\Users\Desktop\Claude\Projects\kms\jarvis-luna
cd /d "%REPO%"
python "%REPO%\scripts\repair_conflicts.py" >"%TEMP%\jarvis_repair.log" 2>&1
