#!/usr/bin/env powershell

# 작업 경로
$projectPath = "C:\Users\Desktop\Claude\Projects\kms\jarvis-luna"
$sourceImage = "C:\Users\Desktop\Claude\Projects\kms\images\111.jpg"
$destImage = "$projectPath\hero-bg.jpg"

Write-Host ""
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "JARVIS-LUNA Hero Section Deploy" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: 이미지 복사
Write-Host "Step 1: Copy hero background image..." -ForegroundColor Yellow
Copy-Item -Path $sourceImage -Destination $destImage -Force
Write-Host "OK - Image copied: hero-bg.jpg" -ForegroundColor Green
Write-Host ""

# Step 2: 프로젝트 폴더로 이동
Write-Host "Step 2: Change to project directory..." -ForegroundColor Yellow
cd $projectPath
Write-Host "OK - Working directory: $projectPath" -ForegroundColor Green
Write-Host ""

# Step 3: Git 상태 확인
Write-Host "Step 3: Check git status..." -ForegroundColor Yellow
git status
Write-Host ""

# Step 4: Git Add
Write-Host "Step 4: Stage files..." -ForegroundColor Yellow
git add index.html hero-bg.jpg
Write-Host "OK - Files staged for commit" -ForegroundColor Green
Write-Host ""

# Step 5: Git Commit
Write-Host "Step 5: Commit changes..." -ForegroundColor Yellow
git commit -m "Update hero section: wine cellar background + white text + new styling"
Write-Host "OK - Changes committed" -ForegroundColor Green
Write-Host ""

# Step 6: Git Push
Write-Host "Step 6: Push to GitHub..." -ForegroundColor Yellow
git push origin main
Write-Host "OK - GitHub push completed" -ForegroundColor Green
Write-Host ""

# Step 7: 최종 확인
Write-Host "Step 7: Final verification..." -ForegroundColor Yellow
$commitHash = git rev-parse HEAD
$commitMessage = git log -1 --format="%B"
Write-Host "OK - Commit hash: $commitHash" -ForegroundColor Green
Write-Host "     Message: $commitMessage" -ForegroundColor Green
Write-Host ""

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "Deploy Complete!" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "Website: https://coar0000-wq.github.io/jarvis-luna/" -ForegroundColor Cyan
Write-Host "Expected update time: 5-10 minutes" -ForegroundColor Cyan
Write-Host ""
