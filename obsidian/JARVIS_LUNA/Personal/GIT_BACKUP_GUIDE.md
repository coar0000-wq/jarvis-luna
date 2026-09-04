# Obsidian Vault Git 백업 가이드

**최종 업데이트**: 2026년 7월 31일  
**상태**: 📋 설정 가이드  
**목적**: Claude Cowork + Obsidian 자동 백업 시스템

---

## 📋 개요

이 가이드는 Obsidian Vault를 Git으로 버전 관리하고 자동 백업하는 방법을 설명합니다.

### 장점
✅ **버전 관리**: 모든 변경사항 추적 가능  
✅ **자동 백업**: 정기적 자동 커밋  
✅ **충돌 해결**: 여러 곳에서 편집할 때 병합 가능  
✅ **히스토리**: 과거 상태 복구 가능  

---

## 🔧 설정 단계

### 1단계: Git 초기화 (처음 한 번)

```powershell
# PowerShell에서 실행
cd "C:\Users\Desktop\Desktop\도현 physical"
git init
git config user.name "Claude Vault Auto-backup"
git config user.email "claude@vault.local"
git add -A
git commit -m "Initial commit: Obsidian Vault setup"
```

### 2단계: 리모트 저장소 추가 (선택사항)

#### GitHub 사용
```powershell
git remote add origin https://github.com/YOUR_USERNAME/obsidian-vault.git
git branch -M main
git push -u origin main
```

#### GitLab 사용
```powershell
git remote add origin https://gitlab.com/YOUR_USERNAME/obsidian-vault.git
git branch -M main
git push -u origin main
```

#### 로컬만 사용 (권고)
리모트 없이 로컬 Git만 사용하면 더 간단합니다.

### 3단계: 자동 백업 스크립트 설정

#### 방법 A: 수동 실행
```powershell
# PowerShell 실행 정책 변경 (처음 한 번만)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 스크립트 실행
.\auto-backup.ps1
```

#### 방법 B: 자동 실행 (Windows 작업 스케줄러)

**1. 작업 스케줄러 열기**
```
Windows + R → taskschd.msc → Enter
```

**2. 작업 만들기**
- 작업 이름: "Obsidian Vault Auto-Backup"
- 설명: "Claude Cowork과 동기화된 Obsidian 자동 백업"

**3. 트리거 설정 탭**
- 반복 주기: 시간마다 / 일일 / 주간 (선호도에 따라)
- 권장: 매일 오후 6시, 오후 10시 (하루 2회)

**4. 작업 설정 탭**
```
프로그램: powershell.exe

인수:
-NoProfile -ExecutionPolicy Bypass -File "C:\Users\Desktop\Desktop\도현 physical\auto-backup.ps1"
```

**5. 조건 탭**
- "컴퓨터가 유휴 상태일 때만 작업 실행" 체크 해제
- "AC 전원에 연결되어 있을 때만" 체크

**6. 설정 탭**
- "작업이 실패하면 다시 시도" 체크
- 재시도 간격: 5분

---

## 📊 자동 백업 스크립트 사용법

### 기본 실행
```powershell
.\auto-backup.ps1
```

### 커스텀 메시지와 함께 실행
```powershell
.\auto-backup.ps1 -CommitMessage "YouTube 비디오 4개 추가 + 노드 수 업데이트"
```

### 다른 Vault 경로 지정
```powershell
.\auto-backup.ps1 -VaultPath "D:\My Obsidian Vault"
```

---

## 📈 스크립트 동작 원리

```
1. 변경 사항 확인
   └─ Git status 체크
   └─ 변경 없으면 종료

2. 파일 스테이징
   └─ git add -A

3. 커밋 생성
   └─ 타임스탬프 포함한 메시지

4. 원격 푸시 (선택적)
   └─ 리모트가 설정되면 GitHub/GitLab에 푸시
   └─ 없으면 로컬 저장소만 유지

5. 로그 출력
   └─ 성공/실패 상태 표시
```

---

## 🔍 주요 파일 및 폴더

### 추적됨 (✅ 백업)
```
├── AI_Agents_Multi_Industry_Enterprise_Hub.md
├── Autonomous_AI_Agent_Complete_Graph.md
├── AWS_*.md (모든 AWS 그래프)
├── Data_*.md (모든 데이터 그래프)
└── [모든 .md 마크다운 파일]
```

### 제외됨 (❌ 백업 안 함)
```
├── .obsidian/plugins/          (플러그인)
├── .obsidian/workspace.json    (UI 상태)
├── .obsidian/cache/            (캐시)
├── .DS_Store                   (시스템)
├── Thumbs.db                   (시스템)
└── *.tmp, *.log                (임시)
```

---

## 🔐 보안 권장사항

### 1. 민감 정보 제외
.gitignore에 추가:
```
# 민감 정보
*.secret
*.token
.env
credentials.md
```

### 2. 리모트 사용 시
- **Private Repository** 사용 (GitHub/GitLab)
- 2FA (Two-Factor Authentication) 활성화
- Personal Access Token 사용 (비밀번호 대신)

### 3. 로컬만 사용 시
- 정기적으로 외장 하드 드라이브에 백업
- 클라우드 동기화 (OneDrive, Dropbox) 추가

---

## 📝 로그 및 디버깅

### 스크립트 실행 로그 확인
```powershell
# 작업 스케줄러 로그
Get-EventLog -LogName Application | Where-Object {$_.Source -like "*Task*"}

# 수동 로그 저장
.\auto-backup.ps1 | Tee-Object -FilePath "backup-log.txt"
```

### 문제 해결

**오류: "not a git repository"**
```powershell
cd "C:\Users\Desktop\Desktop\도현 physical"
git init
```

**오류: "permission denied"**
- PowerShell을 관리자로 실행
- 실행 정책 변경: `Set-ExecutionPolicy RemoteSigned`

**오류: "Your branch is ahead of origin"**
```powershell
git push origin main
```

---

## 🎯 권장 자동 백업 일정

```
주간 기준:

월-금 (평일): 매일 오후 6시 (작업 후)
토-일 (주말): 매일 오전 10시 (여유 있을 때)

특별 상황:
- 중요 수정 후: 수동 커밋 권장
- 중대 변경 전: 브랜치 생성 고려
- 학습 세션 후: 즉시 커밋
```

---

## 📚 고급 기능

### 특정 파일만 백업
```powershell
git add AI_Agents_Multi_Industry_Enterprise_Hub.md
git commit -m "Update: Hub 노드 수 변경"
```

### 변경 이력 보기
```powershell
git log --oneline -10        # 최근 10개 커밋
git log --stat              # 파일별 통계
git diff HEAD~1             # 마지막 변경사항
```

### 특정 시점으로 복구
```powershell
git log --oneline           # 커밋 해시 확인
git checkout <commit-hash>  # 해당 시점으로 복구
git checkout main           # 최신 버전으로 돌아오기
```

### 브랜치 사용
```powershell
git branch experiment               # 새 브랜치 생성
git checkout experiment             # 브랜치 전환
# ... 수정 작업 ...
git add -A
git commit -m "Experiment: 새 기능"
git checkout main                   # main으로 돌아오기
git merge experiment                # 병합
```

---

## 📞 지원

### Git 공식 문서
- https://git-scm.com/doc

### Obsidian + Git 커뮤니티
- https://forum.obsidian.md

### PowerShell 문서
- https://docs.microsoft.com/powershell

---

**마지막 업데이트**: 2026-07-31  
**다음 검토**: 2026-08-31 (월간 정기 검토)
