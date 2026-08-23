@echo off
set REPO=C:\Users\Desktop\Claude\Projects\kms\jarvis-luna
set JARVIS_MSG=JARVIS: shuffle sitemap sampling for beauty scope, tune run budget
cd /d "%REPO%"
echo === START %DATE% %TIME% === >"%REPO%\deploy_stdout.txt"
del /q "%REPO%\data\daiso_real\crawl_state.json" 2>nul
echo --- collect beauty (40 items, 3s delay) --- >>"%REPO%\deploy_stdout.txt"
set DAISO_MAX_ITEMS=40
set DAISO_DELAY=3
python "%REPO%\scripts\daiso\collect_daiso.py" >>"%REPO%\deploy_stdout.txt" 2>&1
set DAISO_MAX_ITEMS=
set DAISO_DELAY=
echo --- deploy --- >>"%REPO%\deploy_stdout.txt"
python "%REPO%\JARVIS_AUTO_DEPLOY.py" >>"%REPO%\deploy_stdout.txt" 2>&1
echo === END %TIME% === >>"%REPO%\deploy_stdout.txt"
