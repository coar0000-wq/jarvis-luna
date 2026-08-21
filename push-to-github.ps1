# ========================================
# JARVIS LUNA GitHub 자동 푸시 스크립트
# ========================================

# 변수 설정
$REPO_PATH = "C:\Users\Desktop\Claude\Projects\kms"
$COMMIT_MESSAGE = "Complete: JSON.parse + array order + date format + background unified"
$BRANCH = "main"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "🚀 JARVIS LUNA GitHub 푸시 시작" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 디렉토리 이동
Write-Host "📁 저장소 경로: $REPO_PATH" -ForegroundColor Yellow
cd $REPO_PATH

if (-not (Test-Path ".git")) {
    Write-Host "❌ Git 저장소가 아닙니다!" -ForegroundColor Red
    exit 1
}

# Git 상태 확인
Write-Host ""
Write-Host "📊 Git 상태 확인 중..." -ForegroundColor Yellow
git status

# 모든 변경사항 스테이징
Write-Host ""
Write-Host "📝 변경사항 스테이징..." -ForegroundColor Yellow
git add .

# 커밋
Write-Host ""
Write-Host "💾 커밋 생성: $COMMIT_MESSAGE" -ForegroundColor Yellow
git commit -m "$COMMIT_MESSAGE"

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ 커밋 성공" -ForegroundColor Green
} else {
    Write-Host "⚠️ 커밋 실패 (변경사항 없음일 수 있음)" -ForegroundColor Yellow
}

# 푸시
Write-Host ""
Write-Host "🚀 $BRANCH 브랜치로 푸시 중..." -ForegroundColor Yellow
git push origin $BRANCH

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ 푸시 성공!" -ForegroundColor Green
    Write-Host ""
    Write-Host "📊 최종 상태:" -ForegroundColor Cyan
    git log --oneline -n 3
} else {
    Write-Host "❌ 푸시 실패" -ForegroundColor Red
    Write-Host ""
    Write-Host "💡 해결 방법:" -ForegroundColor Yellow
    Write-Host "  1. git pull --rebase origin $BRANCH" -ForegroundColor Gray
    Write-Host "  2. 충돌 해결" -ForegroundColor Gray
    Write-Host "  3. git push origin $BRANCH" -ForegroundColor Gray
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "✨ 완료!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
