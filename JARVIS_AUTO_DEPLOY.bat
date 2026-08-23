@echo off
set REPO=C:\Users\Desktop\Claude\Projects\kms\jarvis-luna
set JARVIS_MSG=JARVIS: remove temporary mobile preview harness
cd /d "%REPO%"
del /q "%REPO%\mobile-preview.html" 2>nul
del /q "%REPO%\_mobile_preview.html" 2>nul
python "%REPO%\JARVIS_AUTO_DEPLOY.py" >"%TEMP%\jarvis_deploy.log" 2>&1
