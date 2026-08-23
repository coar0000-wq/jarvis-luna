@echo off
set REPO=C:\Users\Desktop\Claude\Projects\kms\jarvis-luna
set JARVIS_MSG=JARVIS: accumulate knowledge corpus every run, target revenue tile
cd /d "%REPO%"
echo === START %DATE% %TIME% === >"%REPO%\deploy_stdout.txt"
echo --- rebuild corpus (accumulating) --- >>"%REPO%\deploy_stdout.txt"
python "%REPO%\prepare_real_training_corpus.py" >>"%REPO%\deploy_stdout.txt" 2>&1
echo --- runtime snapshot --- >>"%REPO%\deploy_stdout.txt"
python "%REPO%\scripts\generate_dashboard_runtime.py" >nul 2>&1
echo done >>"%REPO%\deploy_stdout.txt"
echo --- deploy --- >>"%REPO%\deploy_stdout.txt"
python "%REPO%\JARVIS_AUTO_DEPLOY.py" >>"%REPO%\deploy_stdout.txt" 2>&1
echo === END %TIME% === >>"%REPO%\deploy_stdout.txt"
