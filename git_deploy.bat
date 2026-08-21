@echo off
chcp 65001 >nul
cd /d C:\Users\Desktop\Claude\Projects\kms

echo 🚀 JARVIS LUNA 대시보드 배포 중...
git add -A
git commit -m "📋 대시보드 복구: 작업 상세 로그 + 팀원 상태 + 프로젝트 진행도"
git push origin main

echo ✅ 배포 완료! (1-2분 후 사이트에 반영됨)
pause
