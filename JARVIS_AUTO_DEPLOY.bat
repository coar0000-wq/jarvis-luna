@echo off
set REPO=C:\Users\Desktop\Claude\Projects\kms\jarvis-luna
cd /d "%REPO%"
echo START >"%REPO%\deploy_stdout.txt"
where python >>"%REPO%\deploy_stdout.txt" 2>&1
python "%REPO%\JARVIS_AUTO_DEPLOY.py" >>"%REPO%\deploy_stdout.txt" 2>&1
if errorlevel 1 py -3 "%REPO%\JARVIS_AUTO_DEPLOY.py" >>"%REPO%\deploy_stdout.txt" 2>&1
echo DONE >>"%REPO%\deploy_stdout.txt"
