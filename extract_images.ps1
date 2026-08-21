# Stuffed Dog Digital ZIP에서 이미지 추출
$zipPath = "C:\Users\Desktop\Claude\Projects\kms\stuffed-dog-digital-clone.zip"
$extractPath = "C:\Users\Desktop\Claude\Projects\kms\stuffed-dog-digital-clone"
$imagesPath = "C:\Users\Desktop\Claude\Projects\kms\images"

# ZIP 파일 압축 해제
if (Test-Path $zipPath) {
    Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
    Write-Host "✅ ZIP 추출 완료: $extractPath"

    # 이미지 파일 찾기
    $imageFiles = Get-ChildItem -Path $extractPath -Recurse -Include *.png, *.jpg, *.jpeg, *.gif, *.webp
    Write-Host "📁 찾은 이미지: $($imageFiles.Count)개"

    # 이미지 목록 출력
    $imageFiles | ForEach-Object {
        Write-Host "  - $($_.FullName)"
    }
} else {
    Write-Host "❌ ZIP 파일을 찾을 수 없습니다: $zipPath"
}
