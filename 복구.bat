@echo off
chcp 65001 >nul
cd /d C:\Users\Desktop\Claude\Projects\kms

echo.
echo ====================================================================
echo   🔄 JARVIS LUNA 원래 파일 복구 및 배포
echo ====================================================================
echo.

python find_and_restore.py

echo.
echo [다음] 변경사항 커밋 및 푸시...
git add index.html
git commit -m "🔄 원래 index.html 복구 + 실제 데이터 통합"
git push origin main

echo.
echo ====================================================================
echo ✅ 복구 및 배포 완료!
echo ====================================================================
echo.
echo 📱 대시보드: https://coar0000-wq.github.io/jarvis-luna/
echo 🔄 강력 새로고침: Ctrl+Shift+R
echo ⏱️  업데이트 반영: 1-2분
echo.
pause
