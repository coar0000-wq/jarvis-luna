@echo off
set REPO=C:\Users\Desktop\Claude\Projects\kms\jarvis-luna
set JARVIS_MSG=JARVIS: restore trained MoE status after corpus rebuild
cd /d "%REPO%"
echo === START %DATE% %TIME% === >"%REPO%\deploy_stdout.txt"
echo --- try local retrain --- >>"%REPO%\deploy_stdout.txt"
python "%REPO%\train_real_knowledge.py" >>"%REPO%\deploy_stdout.txt" 2>&1
python "%REPO%\tune_real_knowledge_moe.py" --experts 3 --learning-rates 1.2 --l2-values 0.0001 --temperatures 0.9 --steps 500 --promote >>"%REPO%\deploy_stdout.txt" 2>&1
echo --- verify training_performed --- >>"%REPO%\deploy_stdout.txt"
python -c "import json;d=json.load(open(r'%REPO%\data\knowledge\training_status.json',encoding='utf-8'));print('trained=',d.get('training_performed'),'acc=',d.get('training_accuracy_on_corpus'))" >>"%REPO%\deploy_stdout.txt" 2>&1
echo --- runtime snapshot --- >>"%REPO%\deploy_stdout.txt"
python "%REPO%\scripts\generate_dashboard_runtime.py" >nul 2>&1
echo done >>"%REPO%\deploy_stdout.txt"
echo --- deploy --- >>"%REPO%\deploy_stdout.txt"
python "%REPO%\JARVIS_AUTO_DEPLOY.py" >>"%REPO%\deploy_stdout.txt" 2>&1
echo === END %TIME% === >>"%REPO%\deploy_stdout.txt"
