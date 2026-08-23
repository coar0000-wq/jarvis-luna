@echo off
set REPO=C:\Users\Desktop\Claude\Projects\kms\jarvis-luna
cd /d "%REPO%"
echo === START %DATE% %TIME% === >"%REPO%\deploy_stdout.txt"
python --version >>"%REPO%\deploy_stdout.txt" 2>&1
echo --- runtime --- >>"%REPO%\deploy_stdout.txt"
python "%REPO%\scripts\generate_dashboard_runtime.py" >>"%REPO%\deploy_stdout.txt" 2>&1
echo --- deploy --- >>"%REPO%\deploy_stdout.txt"
python "%REPO%\JARVIS_AUTO_DEPLOY.py" >>"%REPO%\deploy_stdout.txt" 2>&1
echo === END %TIME% === >>"%REPO%\deploy_stdout.txt"
