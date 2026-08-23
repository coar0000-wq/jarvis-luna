#!/usr/bin/env powershell
# JARVIS Auto-Apply Design Script
# 원본 JARVIS Adaptive Intelligence 디자인 적용 (4658252)

cd "C:\Users\Desktop\Claude\Projects\kms\jarvis-luna"
Write-Host "🚀 JARVIS 자동화 진행 중..." -ForegroundColor Cyan

# Step 1: 4658252 커밋의 index.html 적용
Write-Host "1️⃣  원본 디자인 적용 (4658252)..." -ForegroundColor Yellow
git show 4658252:index.html | Out-File -FilePath index.html -Encoding UTF8
Write-Host "✅ 디자인 파일 적용 완료" -ForegroundColor Green

# Step 2: 파일 스테이징
Write-Host "2️⃣  Git 스테이징..." -ForegroundColor Yellow
git add index.html
Write-Host "✅ 파일 스테이징 완료" -ForegroundColor Green

# Step 3: 커밋
Write-Host "3️⃣  커밋 생성..." -ForegroundColor Yellow
git commit -m "Apply original JARVIS Adaptive Intelligence design (4658252) with Knowledge Graph"
Write-Host "✅ 커밋 완료" -ForegroundColor Green

# Step 4: GitHub 푸시
Write-Host "4️⃣  GitHub 푸시 중..." -ForegroundColor Yellow
git push --force-with-lease origin main:master
Write-Host "✅ GitHub 푸시 완료" -ForegroundColor Green

# 완료 보고
Write-Host ""
Write-Host "╔════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  ✅ 완료! 원본 JARVIS Adaptive Intelligence    ║" -ForegroundColor Cyan
Write-Host "║     디자인 적용됨 (4658252)                   ║" -ForegroundColor Cyan
Write-Host "║  🌐 웹사이트: https://coar0000-wq.github.io   ║" -ForegroundColor Cyan
Write-Host "║  ⏱️  배포 예상 시간: 30초                      ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════╝" -ForegroundColor Cyan

Write-Host ""
Write-Host "📊 최종 상태:" -ForegroundColor Yellow
git log --oneline -3
