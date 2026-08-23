@echo off
set REPO=C:\Users\Desktop\Claude\Projects\kms\jarvis-luna
set JARVIS_MSG=JARVIS: cumulative ledger for records/notes/links - show 기존 + 신규
cd /d "%REPO%"
python "%REPO%\scripts\generate_dashboard_runtime.py" >"%TEMP%\jarvis_runtime.log" 2>&1
python "%REPO%\JARVIS_AUTO_DEPLOY.py" >"%TEMP%\jarvis_deploy.log" 2>&1
