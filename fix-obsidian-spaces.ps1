# Obsidian vault 파일명 끝 공백 제거 스크립트

Write-Host "🧹 Obsidian vault 공백 제거 시작..." -ForegroundColor Cyan

$obsidianPath = "C:\Users\Desktop\Obsidian"
Set-Location $obsidianPath

# 파일/폴더명 끝 공백 찾기 및 제거
$files = Get-ChildItem -Recurse -Force | Where-Object {$_.Name -match '\s+$'}

if ($files) {
    Write-Host "찾은 공백 파일/폴더: $($files.Count)개" -ForegroundColor Yellow

    foreach ($file in $files) {
        $newName = $file.Name -replace '\s+$', ''
        $newPath = Join-Path $file.Directory.FullName $newName

        if (Test-Path $newPath) {
            Write-Host "⚠️ '$newName'는 이미 존재합니다. 스킵: $($file.FullName)" -ForegroundColor Yellow
        } else {
            Rename-Item -LiteralPath $file.FullName -NewName $newName
            Write-Host "✅ 제거됨: '$($file.Name)' → '$newName'" -ForegroundColor Green
        }
    }
} else {
    Write-Host "✅ 공백이 없습니다! 모든 파일명이 정상입니다." -ForegroundColor Green
}

Write-Host ""
Write-Host "🎉 공백 제거 완료!" -ForegroundColor Cyan
