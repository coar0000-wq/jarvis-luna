@echo off
set PYTHONUTF8=1
cd /d C:\Users\Desktop\Claude\Projects\kms
python scripts/obsidian_realtime_sync.py > sync_log.txt 2>&1
