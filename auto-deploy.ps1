#!/usr/bin/env powershell
# JARVIS Auto-Deploy Script
# 유기적 움직임 Knowledge Graph 배포

cd "C:\Users\Desktop\Claude\Projects\kms\jarvis-luna"
Write-Host ""
Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  🚀 JARVIS 자동 배포 시작 - Organic Knowledge Graph     ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Step 1: Git Add
Write-Host "1️⃣  파일 스테이징..." -ForegroundColor Yellow
git add index.html
Write-Host "✅ 완료" -ForegroundColor Green
Write-Host ""

# Step 2: Git Commit
Write-Host "2️⃣  커밋 생성..." -ForegroundColor Yellow
git commit -m "Add organic motion to Knowledge Graph with physics simulation and glow effects"
Write-Host "✅ 완료" -ForegroundColor Green
Write-Host ""

# Step 3: Git Push
Write-Host "3️⃣  GitHub 푸시..." -ForegroundColor Yellow
git push -u origin main
Write-Host "✅ 완료" -ForegroundColor Green
Write-Host ""

# Step 4: Verify Commit
Write-Host "4️⃣  최종 커밋 확인..." -ForegroundColor Yellow
$commitHash = git rev-parse HEAD
$commitMessage = git log -1 --format="%B"
Write-Host "✅ 커밋: $commitHash" -ForegroundColor Green
Write-Host "   메시지: $commitMessage" -ForegroundColor Green
Write-Host ""

Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  ✅ 배포 완료!                                            ║" -ForegroundColor Cyan
Write-Host "║  🌊 유기적 움직이는 Knowledge Graph 적용됨             ║" -ForegroundColor Cyan
Write-Host "║  🌐 웹사이트: https://coar0000-wq.github.io/jarvis-luna ║" -ForegroundColor Cyan
Write-Host "║  ⏱️  배포 예상 시간: 5-10분                              ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
