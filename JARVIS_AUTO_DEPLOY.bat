@echo off
set REPO=C:\Users\Desktop\Claude\Projects\kms\jarvis-luna
set JARVIS_MSG=JARVIS: living knowledge graph - organic spring network with signal pulses
cd /d "%REPO%"
python "%REPO%\JARVIS_AUTO_DEPLOY.py" >"%TEMP%\jarvis_deploy.log" 2>&1
