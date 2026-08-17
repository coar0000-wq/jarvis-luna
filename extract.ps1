# ZIP 파일 압축 해제 스크립트

$kmsPath = "C:\Users\Desktop\Claude\Projects\kms"
$zipFiles = @(
    "stuffed-dog-digital-clone.zip",
    "stuffed-dog-digital-1to1-style-v2.zip"
)

foreach ($zipName in $zipFiles) {
    $zipPath = Join-Path $kmsPath $zipName
    $extractDir = Join-Path $kmsPath ($zipName -replace '.zip', '')

    if (Test-Path $zipPath) {
        Write-Host "================================================" -ForegroundColor Cyan
        Write-Host "📦 압축 해제: $zipName" -ForegroundColor Green
        Write-Host "================================================" -ForegroundColor Cyan

        # 압축 해제
        Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

        Write-Host "✅ 완료: $extractDir`n" -ForegroundColor Green

        # 파일 구조 출력
        Write-Host "📋 폴더 구조:" -ForegroundColor Yellow
        Get-ChildItem -Path $extractDir -Recurse -Force |
            Select-Object @{Name="Path"; Expression={$_.FullName.Replace($extractDir, "").TrimStart("\")}} |
            ForEach-Object { Write-Host $_.Path }
    }
}

Write-Host "`n✨ 압축 해제 완료!" -ForegroundColor Green
