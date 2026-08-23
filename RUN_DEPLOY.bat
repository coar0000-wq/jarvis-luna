@echo off
set REPO=C:\Users\Desktop\Claude\Projects\kms\jarvis-luna
cd /d "%REPO%"
echo === BACKUP %DATE% %TIME% === >"%REPO%\deploy_stdout.txt"
python "%REPO%\scripts\backup_repo.py" >>"%REPO%\deploy_stdout.txt" 2>&1
echo === END %TIME% === >>"%REPO%\deploy_stdout.txt"
