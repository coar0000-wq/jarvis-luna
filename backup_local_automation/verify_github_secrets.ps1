# GitHub Secrets 설정 상태 확인

Write-Host "🔍 GitHub Secrets 설정 상태 확인 중..." -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

$REPO = "coar0000-wq/jarvis-luna"

# GitHub CLI 확인
$ghPath = & where.exe gh 2>$null
if (-not $ghPath) {
    Write-Host "❌ GitHub CLI가 설치되지 않았습니다." -ForegroundColor Red
    Write-Host ""
    Write-Host "📥 GitHub CLI 설치: https://cli.github.com" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "⚠️ 또는 웹에서 직접 확인:" -ForegroundColor Yellow
    Write-Host "https://github.com/coar0000-wq/jarvis-luna/settings/secrets/actions" -ForegroundColor White
    exit 1
}

Write-Host "✅ GitHub CLI 발견" -ForegroundColor Green
Write-Host ""

# Secrets 목록 조회
Write-Host "📋 설정된 Secrets 목록:" -ForegroundColor Cyan
Write-Host ""

$secretsList = & gh secret list --repo $REPO 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host $secretsList -ForegroundColor White
    Write-Host ""

    # 개별 확인
    Write-Host "✅ 설정 상태:" -ForegroundColor Green

    if ($secretsList -match "SENDER_EMAIL") {
        Write-Host "   ✅ SENDER_EMAIL: 설정됨" -ForegroundColor Green
    } else {
        Write-Host "   ❌ SENDER_EMAIL: 미설정" -ForegroundColor Red
    }

    if ($secretsList -match "EMAIL_PASSWORD") {
        Write-Host "   ✅ EMAIL_PASSWORD: 설정됨" -ForegroundColor Green
    } else {
        Write-Host "   ❌ EMAIL_PASSWORD: 미설정" -ForegroundColor Red
    }
} else {
    Write-Host "❌ Secrets 조회 실패" -ForegroundColor Red
    Write-Host $secretsList -ForegroundColor Yellow
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "🎯 자동화 상태:" -ForegroundColor Cyan
Write-Host ""

# 워크플로우 확인
Write-Host "📅 5일 주기 워크플로우: weekly-strategy-report.yml" -ForegroundColor White
Write-Host "   - 첫 실행: 2026-08-22 06:00 UTC" -ForegroundColor White
Write-Host "   - 주기: 매 5일마다" -ForegroundColor White
Write-Host "   - 수신자: coar0000@naver.com" -ForegroundColor White
Write-Host ""

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "🚀 준비 완료!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""





