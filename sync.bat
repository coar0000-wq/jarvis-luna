@echo off
chcp 65001 > nul
echo 🔄 [JARVIS] 로컬 옵시디언 및 저장소 변경사항 동기화 시작...
git add .
git commit -m "🧠 JARVIS Local Obsidian Sync: $(date)"
git push origin main
echo ✅ 동기화 완료!
pause