@echo off
chcp 65001 > nul
cd /d C:\Users\Desktop\Claude\Projects\kms
echo.
echo ========================================
echo 🔧 Git 상태 복구 중...
echo ========================================
echo.
echo [1/4] Merge 충돌 해제...
git merge --abort
echo [2/4] 로컬 상태 초기화...
git reset --hard HEAD
echo [3/4] 원격 변경사항 동기화...
git pull origin main
echo [4/4] 로컬 변경사항 업로드...
git push origin main
echo.
echo ========================================
echo ✅ 모든 작업 완료!
echo ========================================
pause
