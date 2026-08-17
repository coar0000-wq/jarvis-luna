# 🤖 Gemini API Key 자동 등록 가이드

## 방법 1: GitHub CLI 사용 (권장) ⭐

### 1단계: GitHub CLI 설치
```bash
# Windows (PowerShell 관리자 모드)
choco install gh

# 또는 직접 다운로드
# https://github.com/cli/cli/releases
```

### 2단계: GitHub 로그인
```bash
gh auth login
```
- 선택: GitHub.com
- 프로토콜: HTTPS
- 인증 방식: Personal access token 또는 브라우저 로그인

### 3단계: Secrets 등록 (한 줄 명령어)
```bash
echo "AQ.Ab8RN6Locpw6kQHtQioDsZrwFj7NZ6yn-4bxY-UuFfpjWN2adg" | gh secret set GEMINI_API_KEY -R coar0000/kms
```

**결과:**
```
✓ Set secret GEMINI_API_KEY for coar0000/kms
```

---

## 방법 2: GitHub 웹 UI (수동)

### 1단계: GitHub 저장소 접속
```
https://github.com/coar0000/kms/settings/secrets/actions
```

### 2단계: "New repository secret" 클릭

### 3단계: 정보 입력
```
Name:   GEMINI_API_KEY
Secret: AQ.Ab8RN6Locpw6kQHtQioDsZrwFj7NZ6yn-4bxY-UuFfpjWN2adg
```

### 4단계: "Add secret" 클릭

---

## 방법 3: Windows PowerShell 자동화

### 1단계: PowerShell 스크립트 생성
파일명: `setup_gemini.ps1`

```powershell
# GitHub Personal Access Token 입력
$token = Read-Host "GitHub Token"
$repo = "coar0000/kms"
$apiKey = "AQ.Ab8RN6Locpw6kQHtQioDsZrwFj7NZ6yn-4bxY-UuFfpjWN2adg"

# Base64 인코딩
$bytes = [System.Text.Encoding]::UTF8.GetBytes($apiKey)
$base64 = [Convert]::ToBase64String($bytes)

# API 호출
$headers = @{
    "Authorization" = "token $token"
    "Accept" = "application/vnd.github.v3+json"
}

# 공개 키 조회
$keyUrl = "https://api.github.com/repos/$repo/actions/secrets/public-key"
$keyResponse = Invoke-RestMethod -Uri $keyUrl -Headers $headers

Write-Host "✅ 공개 키 획득 완료"

# Secrets 등록
$secretUrl = "https://api.github.com/repos/$repo/actions/secrets/GEMINI_API_KEY"
$body = @{
    "encrypted_value" = $base64
    "key_id" = $keyResponse.key_id
} | ConvertTo-Json

Invoke-RestMethod -Uri $secretUrl -Method Put -Headers $headers -Body $body -ContentType "application/json"

Write-Host "✅ GEMINI_API_KEY 등록 완료!"
```

### 2단계: 실행
```powershell
# PowerShell 관리자 모드에서
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
.\setup_gemini.ps1
```

---

## ✅ 등록 확인

### 1단계: GitHub 저장소 Settings 확인
```
https://github.com/coar0000/kms/settings/secrets/actions
```

### 2단계: GEMINI_API_KEY가 보이는지 확인
- ✅ 표시되면 성공

### 3단계: GitHub Actions 확인
```
https://github.com/coar0000/kms/actions
```

- JARVIS-Core-Automation.yml 실행 여부 확인
- 약 10분 후 자동 실행 시작

---

## 🚀 등록 후 예상 결과

### 1분 후:
- ✅ GitHub Actions 워크플로우 시작
- 📊 5개 플랫폼 상품 동시 발굴

### 10분 후:
- ✅ cumulative_products.json 업데이트
- ✅ scheduler_log.json 신규 항목
- ✅ Obsidian 자동 동기화

### 매 10분:
- 🔄 자동 반복 실행
- 📈 누적 상품 수 증가
- 📝 작업 로그 기록

---

## 🛠️ 트러블슈팅

### "GitHub Token이 유효하지 않음"
→ Personal Access Token 재발급
→ https://github.com/settings/tokens

### "권한 부족" 오류
→ Token 생성 시 "repo" 권한 선택
→ 저장소 전체 접근 권한 필요

### "Secrets 등록이 안 됨"
→ 저장소명 확인: coar0000/kms
→ Token 권한 재확인
→ 웹 UI에서 수동 등록 시도

---

## 📋 체크리스트

- [ ] GitHub CLI 설치 (방법 1) 또는 웹 UI (방법 2)
- [ ] GitHub 인증 완료
- [ ] GEMINI_API_KEY 등록 완료
- [ ] 등록 확인 (Settings에서 보임)
- [ ] 약 10분 후 GitHub Actions 실행 확인
- [ ] cumulative_products.json 업데이트 확인

---

**🎉 완료! JARVIS 자동화 시스템이 실행 중입니다.**

