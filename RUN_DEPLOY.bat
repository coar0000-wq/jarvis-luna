@echo off
set REPO=C:\Users\Desktop\Claude\Projects\kms\jarvis-luna
set JARVIS_MSG=JARVIS: real Daiso collection pipeline + archive placeholder data
cd /d "%REPO%"
echo === START %DATE% %TIME% === >"%REPO%\deploy_stdout.txt"
echo --- archive legacy --- >>"%REPO%\deploy_stdout.txt"
python "%REPO%\scripts\daiso\archive_legacy.py" >>"%REPO%\deploy_stdout.txt" 2>&1
echo --- smoke test collector (3 items, 5s delay) --- >>"%REPO%\deploy_stdout.txt"
set DAISO_MAX_ITEMS=3
set DAISO_DELAY=5
python "%REPO%\scripts\daiso\collect_daiso.py" >>"%REPO%\deploy_stdout.txt" 2>&1
set DAISO_MAX_ITEMS=
set DAISO_DELAY=
echo --- deploy --- >>"%REPO%\deploy_stdout.txt"
python "%REPO%\JARVIS_AUTO_DEPLOY.py" >>"%REPO%\deploy_stdout.txt" 2>&1
echo === END %TIME% === >>"%REPO%\deploy_stdout.txt"
