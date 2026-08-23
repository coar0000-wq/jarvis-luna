@echo off
set REPO=C:\Users\Desktop\Claude\Projects\kms\jarvis-luna
set JARVIS_MSG=JARVIS: temporary mobile preview harness
cd /d "%REPO%"
python "%REPO%\JARVIS_AUTO_DEPLOY.py" >"%TEMP%\jarvis_deploy.log" 2>&1
