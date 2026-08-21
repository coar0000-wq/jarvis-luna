# GitHub Secrets ?먮룞 ?ㅼ젙 (PowerShell)

Write-Host "?뵍 GitHub Secrets ?먮룞 ?ㅼ젙 ?쒖옉..." -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan

# GitHub CLI ?뺤씤
$ghPath = & where.exe gh 2>$null
if (-not $ghPath) {
    Write-Host "??GitHub CLI媛 ?ㅼ튂?섏? ?딆븯?듬땲??" -ForegroundColor Red
    Write-Host "?뱿 ?ㅼ튂: https://cli.github.com" -ForegroundColor Yellow
    exit 1
}

Write-Host "??GitHub CLI 諛쒓껄: $ghPath" -ForegroundColor Green

# ?몄쬆 ?뺤씤
Write-Host ""
Write-Host "?뵇 GitHub ?몄쬆 ?뺤씤 以?.." -ForegroundColor Cyan
$authStatus = & gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "??GitHub??濡쒓렇?명븯吏 ?딆븯?듬땲??" -ForegroundColor Red
    Write-Host "?뵍 ?ㅼ쓬 紐낅졊?대줈 濡쒓렇?명븯?몄슂:" -ForegroundColor Yellow
    Write-Host "   gh auth login" -ForegroundColor White
    exit 1
}

Write-Host "??GitHub ?몄쬆 ?뺤씤 ?꾨즺" -ForegroundColor Green

# Repository ?ㅼ젙
$REPO = "coar0000-wq/jarvis-luna"

Write-Host ""
Write-Host "?뵩 Secrets ?ㅼ젙 以?.." -ForegroundColor Cyan
Write-Host "Repository: $REPO" -ForegroundColor White

# SENDER_EMAIL ?ㅼ젙
Write-Host ""
Write-Host "1截뤴깵 SENDER_EMAIL 異붽? 以?.." -ForegroundColor Yellow
& gh secret set SENDER_EMAIL --repo $REPO --body "coar1004@naver.com"

if ($LASTEXITCODE -eq 0) {
    Write-Host "??SENDER_EMAIL ?ㅼ젙 ?꾨즺" -ForegroundColor Green
} else {
    Write-Host "??SENDER_EMAIL ?ㅼ젙 ?ㅽ뙣" -ForegroundColor Red
    exit 1
}

# EMAIL_PASSWORD ?ㅼ젙
Write-Host ""
Write-Host "2截뤴깵 EMAIL_PASSWORD 異붽? 以?.." -ForegroundColor Yellow
& gh secret set EMAIL_PASSWORD --repo $REPO --body "EHgus123!"

if ($LASTEXITCODE -eq 0) {
    Write-Host "??EMAIL_PASSWORD ?ㅼ젙 ?꾨즺" -ForegroundColor Green
} else {
    Write-Host "??EMAIL_PASSWORD ?ㅼ젙 ?ㅽ뙣" -ForegroundColor Red
    exit 1
}

# ?뺤씤
Write-Host ""
Write-Host "?뱥 ?ㅼ젙??Secrets ?뺤씤 以?.." -ForegroundColor Cyan
& gh secret list --repo $REPO

Write-Host ""
Write-Host "==================================" -ForegroundColor Cyan
Write-Host "?럦 GitHub Secrets ?ㅼ젙 ?꾨즺!" -ForegroundColor Green
Write-Host "==================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "???ㅼ젙 ?꾨즺:" -ForegroundColor Green
Write-Host "   - SENDER_EMAIL: coar1004@naver.com" -ForegroundColor White
Write-Host "   - EMAIL_PASSWORD: [?ㅼ젙??" -ForegroundColor White
Write-Host ""
Write-Host "?? ?먮룞???쒖옉:" -ForegroundColor Cyan
Write-Host "   - 5?쇰쭏???먮룞 ?ㅽ뻾" -ForegroundColor White
Write-Host "   - ?ㅼ쓬 諛쒖넚: 2026-08-22" -ForegroundColor White
Write-Host ""


