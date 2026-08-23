#!/usr/bin/env powershell
# Hero Background Image Copy & Auto Deploy Script

$sourceImage = "C:\Users\Desktop\AppData\Roaming\Claude\local-agent-mode-sessions\ab2eb384-63dc-4ae8-905a-71460e9ab5d4\f0933c22-8c2d-42bf-80b4-5a7cd933feaf\local_062e88da-5cc1-4a51-a825-03661f67e32c\uploads\111.jpg"
$destImage = "C:\Users\Desktop\Claude\Projects\kms\jarvis-luna\hero-bg.jpg"
$projectPath = "C:\Users\Desktop\Claude\Projects\kms\jarvis-luna"

cd $projectPath
Write-Host ""
Write-Host "Copy Image & Deploy Start" -ForegroundColor Cyan
Write-Host ""

# Step 1: Copy Image
Write-Host "Step 1: Copy hero background image..." -ForegroundColor Yellow
Copy-Item -Path $sourceImage -Destination $destImage -Force
Write-Host "OK - Image copied: hero-bg.jpg" -ForegroundColor Green
Write-Host ""

# Step 2: Git Add
Write-Host "Step 2: Git staging..." -ForegroundColor Yellow
git add index.html hero-bg.jpg
Write-Host "OK - Files staged" -ForegroundColor Green
Write-Host ""

# Step 3: Git Commit
Write-Host "Step 3: Git commit..." -ForegroundColor Yellow
git commit -m "Add hero background image - underground wine cellar scene with JARVIS theme"
Write-Host "OK - Commit created" -ForegroundColor Green
Write-Host ""

# Step 4: Git Push
Write-Host "Step 4: GitHub push..." -ForegroundColor Yellow
git push -u origin main
Write-Host "OK - GitHub push completed" -ForegroundColor Green
Write-Host ""

# Step 5: Verify
Write-Host "Step 5: Final verify..." -ForegroundColor Yellow
$commitHash = git rev-parse HEAD
$commitMessage = git log -1 --format="%B"
Write-Host "OK - Commit: $commitHash" -ForegroundColor Green
Write-Host "   Message: $commitMessage" -ForegroundColor Green
Write-Host ""

Write-Host "Deploy Complete!" -ForegroundColor Cyan
Write-Host "Website: https://coar0000-wq.github.io/jarvis-luna/" -ForegroundColor Cyan
Write-Host "Expected update: 5-10 minutes" -ForegroundColor Cyan
Write-Host ""
