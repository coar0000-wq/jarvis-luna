# PowerShell Git 푸시 스크립트
# Phase 27 신경심볼릭 AI 완성

# 1단계: 모든 파일 추가
Write-Host "✅ Step 1: 모든 파일 추가 중..." -ForegroundColor Green
git add .

# 2단계: 커밋
Write-Host "✅ Step 2: 커밋 중..." -ForegroundColor Green
git commit -m "Phase 27 신경심볼릭 AI 완성: 합성 데이터 검증(2,440개) + 신경망 훈련(93.69% 정확도) + 설명가능성(91.05% + 5개 규칙)"

# 3단계: 푸시
Write-Host "✅ Step 3: GitHub에 푸시 중..." -ForegroundColor Green
git push origin main

# 4단계: 결과 확인
Write-Host "✅ Step 4: 결과 확인 중..." -ForegroundColor Green
git log -1 --oneline

Write-Host "🎉 GitHub 푸시 완료!" -ForegroundColor Cyan
Write-Host "✅ Phase 27 신경심볼릭 AI가 GitHub에 업로드되었습니다!" -ForegroundColor Green
