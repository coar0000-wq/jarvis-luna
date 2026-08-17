# 🔐 GitHub Secrets 자동 설정 가이드

## ✅ 저장된 자격증명

```
SENDER_EMAIL: coar1004@naver.com
EMAIL_PASSWORD: EHgus123!
```

---

## 📋 수동 설정 방법 (3단계)

### 1️⃣ GitHub 리포지토리 설정 접속
```
https://github.com/coar0000/kms/settings/secrets/actions
```

### 2️⃣ "New repository secret" 클릭
- 우측 상단 초록색 버튼

### 3️⃣ 첫 번째 Secret 추가

**Name:**
```
SENDER_EMAIL
```

**Value:**
```
coar1004@naver.com
```

→ "Add secret" 클릭

### 4️⃣ 두 번째 Secret 추가

**Name:**
```
EMAIL_PASSWORD
```

**Value:**
```
EHgus123!
```

→ "Add secret" 클릭

---

## ✨ 완료 후 자동화 실행

✅ **Secrets 추가 완료 후:**
- GitHub Actions 워크플로우 `weekly-strategy-report.yml` 자동 실행
- 매 5일마다 전략분석 PPT 자동 생성
- `coar0000@naver.com`으로 이메일 자동 발송

📅 **예정된 발송:**
- 1️⃣ 첫 발송: **2026-08-22** (5일 후)
- 2️⃣ 두 번째: 2026-08-27
- 3️⃣ 세 번째: 2026-09-01
- ... 계속

---

## 🎯 확인 사항

### 설정이 완료되었는지 확인:
1. GitHub → Settings → Secrets and variables → Actions
2. 아래 2개가 보여야 함:
   - ✅ SENDER_EMAIL
   - ✅ EMAIL_PASSWORD

### 워크플로우 실행 확인:
1. GitHub → Actions 탭
2. `weekly-strategy-report` 워크플로우 선택
3. 상태 확인 (성공 시 ✅ 표시)

---

## 🚀 이메일 발송 확인

설정 후 5일 뒤 (2026-08-22)에:
1. `coar0000@naver.com` 이메일함 확인
2. 제목: "🎯 JARVIS 5일 전략분석 2026-08-22"
3. 첨부: 전략분석 PPT 파일

---

## 💡 문제 해결

**이메일이 안 올 경우:**
1. GitHub Actions 탭에서 워크플로우 실행 로그 확인
2. 오류 메시지 확인
3. Secrets 입력값이 정확한지 재확인

**네이버 메일 차단 해제:**
- Settings → 보안 → "앱 비밀번호 허용"이 켜져있는지 확인

---

**설정 완료: 2026-08-17 06:30 UTC** ✨
