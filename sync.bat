@echo off
chcp 65001 > nul
echo 🔄 [JARVIS] 로컬 변경 사항 임시 저장 중 (Stash)...
git stash

echo 🔄 [JARVIS] 깃허브 최신 내용 가져오는 중 (Pull)...
git pull origin main --rebase

echo 🔄 [JARVIS] 임시 저장했던 변경 사항 복원 중...
git stash pop

echo 🔄 [JARVIS] 로컬 옵시디언 및 저장소 변경사항 동기화 중...
git add .
git commit -m "🧠 JARVIS Local Obsidian Sync"
git push origin main

echo ✅ 완벽 동기화 완료!
pause