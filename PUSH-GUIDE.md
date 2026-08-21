# 🚀 JARVIS LUNA GitHub 푸시 가이드

터미널에서 GitHub에 자동으로 파일을 커밋하고 푸시하는 스크립트입니다.

---

## 📋 스크립트 종류

### 1️⃣ PowerShell (권장 - Windows 사용자)
**파일:** `push-to-github.ps1`

**실행 방법:**
```powershell
# PowerShell 열기
# 경로: C:\Users\Desktop\Claude\Projects\kms

# 실행 정책 임시 변경 (필요시)
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process

# 스크립트 실행
.\push-to-github.ps1
```

### 2️⃣ Batch (Windows CMD)
**파일:** `push-to-github.bat`

**실행 방법:**
```cmd
# Command Prompt 또는 PowerShell에서
C:\Users\Desktop\Claude\Projects\kms\push-to-github.bat

# 또는 파일 탐색기에서 더블클릭
```

### 3️⃣ Bash (Git Bash / Linux / macOS)
**파일:** `push-to-github.sh`

**실행 방법:**
```bash
# Git Bash 열기
cd /c/Users/Desktop/Claude/Projects/kms

# 스크립트 실행 권한 부여
chmod +x push-to-github.sh

# 실행
./push-to-github.sh
```

---

## ⚡ 빠른 실행

### PowerShell (가장 간단)
```powershell
cd C:\Users\Desktop\Claude\Projects\kms
.\push-to-github.ps1
```

### Batch (가장 빠름)
```
C:\Users\Desktop\Claude\Projects\kms\push-to-github.bat
```

---

## 🔧 스크립트 기능

✅ **자동 기능:**
- 📁 저장소 경로로 자동 이동
- 📊 Git 상태 확인
- 📝 모든 변경사항 스테이징 (`git add .`)
- 💾 자동 커밋 (메시지: "Complete: JSON.parse + array order + date format + background unified")
- 🚀 main 브랜치로 자동 푸시
- 📊 최종 커밋 로그 표시

---

## 💡 트러블슈팅

### "Permission denied" 오류 (Bash)
```bash
chmod +x push-to-github.sh
./push-to-github.sh
```

### "정책에 의해 실행이 차단됨" (PowerShell)
```powershell
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
.\push-to-github.ps1
```

### 푸시 실패 (충돌 발생)
```bash
git pull --rebase origin main
# 충돌 해결 후
git push origin main
```

---

## 📝 커밋 메시지 변경

스크립트를 열어서 다음 부분을 수정하세요:

**PowerShell:**
```powershell
$COMMIT_MESSAGE = "Your custom message here"
```

**Batch:**
```batch
set "COMMIT_MESSAGE=Your custom message here"
```

**Bash:**
```bash
COMMIT_MESSAGE="Your custom message here"
```

---

## ✅ 성공 확인

스크립트 실행 후 다음이 표시되면 성공입니다:
```
✅ 커밋 성공
✅ 푸시 성공!
```

---

## 🎯 사용 팁

1. **자주 사용할 예정이면:** 바탕화면에 `.bat` 파일을 단축키로 만들기
2. **Git 설정 확인:** `git config --global user.email` / `git config --global user.name`
3. **브랜치 변경:** 스크립트의 `BRANCH` 변수 수정
4. **로그 확인:** 스크립트 완료 후 `git log --oneline -n 10`

---

**🚀 Happy Pushing!** 🎉
