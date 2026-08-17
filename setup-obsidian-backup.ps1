# Obsidian Vault GitHub 자동 백업 설정 스크립트

Write-Host "🧠 Obsidian Vault 백업 설정 시작..." -ForegroundColor Cyan

# 1. Obsidian 폴더로 이동
Set-Location "C:\Users\Desktop\Obsidian"
Write-Host "✅ Obsidian 폴더로 이동" -ForegroundColor Green

# 2. git 초기화
git init
Write-Host "✅ git 초기화 완료" -ForegroundColor Green

# 3. git 설정
git config user.name "도현"
git config user.email "coar0000@naver.com"
Write-Host "✅ git 설정 완료" -ForegroundColor Green

# 4. .gitignore 파일 생성
$gitignore = @"
.obsidian/cache/
.obsidian/plugins/
.DS_Store
Thumbs.db
*.log
node_modules/
.env
"@
$gitignore | Out-File -Encoding UTF8 .gitignore
Write-Host "✅ .gitignore 생성 완료" -ForegroundColor Green

# 5. 모든 파일 추가
git add .
Write-Host "✅ 파일 추가 완료" -ForegroundColor Green

# 6. GitHub remote 추가
git remote add origin "https://github.com/coar0000-wq/obsidian-vault-backup.git"
Write-Host "✅ GitHub remote 추가 완료" -ForegroundColor Green

# 7. main 브랜치로 변경
git branch -M main
Write-Host "✅ main 브랜치 설정 완료" -ForegroundColor Green

# 8. 첫 커밋
git commit -m "🧠 Obsidian vault 초기 백업 - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "✅ 첫 커밋 완료" -ForegroundColor Green

# 9. GitHub에 푸시
git push -u origin main
Write-Host "✅ GitHub 푸시 완료" -ForegroundColor Green

Write-Host ""
Write-Host "🎉 Obsidian vault 백업이 완료되었습니다!" -ForegroundColor Cyan
Write-Host "📍 GitHub: https://github.com/coar0000-wq/obsidian-vault-backup" -ForegroundColor Yellow
