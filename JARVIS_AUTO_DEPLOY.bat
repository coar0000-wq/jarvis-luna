@echo off
set REPO=C:\Users\Desktop\Claude\Projects\kms\jarvis-luna
cd /d "%REPO%"
python "%REPO%\JARVIS_AUTO_DEPLOY.py" >"%REPO%\deploy_stdout.txt" 2>&1
