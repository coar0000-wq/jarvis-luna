# 메타데이터 자동 업데이트 시스템 가이드

**최종 업데이트**: 2026년 7월 31일  
**목적**: Obsidian 메타데이터 자동 관리 시스템  
**상태**: 📋 설정 및 운영 가이드

---

## 📋 개요

이 가이드는 Obsidian Vault의 메타데이터 ("최종 업데이트" 날짜, 노드 수 등)를 자동으로 관리하는 방법을 설명합니다.

### 자동화의 장점
✅ **일관성**: 항상 최신 정보 유지  
✅ **효율성**: 수동 편집 불필요  
✅ **정확성**: 자동 계산으로 오류 감소  
✅ **시간 절약**: 월 1-2시간 절약  

---

## 🛠️ 설정 방법

### 방법 1: Python 스크립트 (권장)

#### 설치

1. **Python 3.8+ 설치** (이미 설치된 경우 스킵)
   ```powershell
   # 설치 확인
   python --version
   ```

2. **스크립트 위치 확인**
   ```
   C:\Users\Desktop\Desktop\도현 physical\update_metadata.py
   ```

#### 실행

**방법 A: 수동 실행**
```powershell
cd "C:\Users\Desktop\Desktop\도현 physical"

# 전체 Vault 업데이트
python update_metadata.py

# 특정 파일만 업데이트
python update_metadata.py --file Graph_Name.md

# 시뮬레이션 (실제 변경 안 함)
python update_metadata.py --dry-run
```

**방법 B: 자동 실행 (Windows 작업 스케줄러)** ← 권장

1. **작업 스케줄러 열기**
   ```
   Windows + R → taskschd.msc → Enter
   ```

2. **작업 만들기**
   - 작업 이름: "Obsidian Metadata Auto-Update"
   - 설명: "메타데이터 자동 업데이트 (날짜, 노드)"

3. **트리거 설정**
   - 반복: 일일
   - 시간: 오후 6시 (작업 후)
   - 반복 간격: 1일

4. **작업 설정**
   ```
   프로그램: python.exe
   
   인수:
   "C:\Users\Desktop\Desktop\도현 physical\update_metadata.py"
   
   시작 위치:
   C:\Users\Desktop\Desktop\도현 physical
   ```

5. **조건 설정**
   - "컴퓨터가 유휴 상태일 때만" 체크 해제
   - "AC 전원에 연결되어 있을 때만" 체크

---

### 방법 2: Obsidian 플러그인

#### 권장 플러그인

**1. "Update Modified Date" 플러그인**
- 기능: 파일 수정 시 메타데이터 자동 업데이트
- 설치:
  1. Obsidian → 설정 → 플러그인
  2. "플러그인 찾기" → "Update Modified Date" 검색
  3. 설치 및 활성화

**2. "Templater" 플러그인** (고급)
- 기능: 템플릿 기반 메타데이터 자동 생성
- 설정:
  ```javascript
  // 템플릿 예시
  **📌 최종 업데이트**: <% tp.date.now("YYYY년 MM월 DD일") %>
  **📌 노드**: [자동 계산]
  ```

**3. "DataviewJS" 플러그인** (선택)
- 기능: 노드 수 자동 계산 및 표시
- 사용: 중앙 허브에서 통계 자동 계산

---

## 📝 메타데이터 표준 형식

### 필수 메타데이터

```markdown
**📌 최종 업데이트**: YYYY년 MM월 DD일
**📌 노드**: [개수]+
**📌 상태**: [활성/진행중/계획중]
**📌 대상**: [대상 청중]
```

### 선택 메타데이터

```markdown
**📌 언어**: [한국어/영어/혼합]
**📌 난이도**: [초보자/중급/고급]
**📌 버전**: [1.0/1.1/등]
**📌 관리자**: [담당자명]
```

### 예시

```markdown
**📌 최종 업데이트**: 2026년 7월 31일
**📌 노드**: 110+
**📌 상태**: 활성
**📌 대상**: AI 초보자
**📌 언어**: 한국어 강의 중심
**📌 난이도**: 초보자 → 중급
```

---

## 🤖 Python 스크립트 사용법

### 노드 수 자동 계산 방식

```
총 노드 = 기본(30) + 헤더(×1) + 링크(×2) + 비디오(×8) + 리스트(÷5)

예시:
  헤더 5개: 5×1 = 5
  링크 15개: 15×2 = 30
  비디오 3개: 3×8 = 24
  리스트 30개: 30÷5 = 6
  ────────────────────
  총: 30 + 5 + 30 + 24 + 6 = 95 → "95+" 또는 "100+"
```

### 스크립트 옵션

```bash
# 도움말
python update_metadata.py --help

# 전체 Vault 업데이트
python update_metadata.py

# 특정 파일만
python update_metadata.py --file AI_Agent_Research_Guide.md

# 시뮬레이션 (변경 없음)
python update_metadata.py --dry-run

# 사용자 정의 Vault 경로
python update_metadata.py --vault "D:\My Obsidian Vault"
```

### 스크립트 출력 예시

```
============================================================
Obsidian Vault 메타데이터 자동 업데이트
============================================================
Vault: C:\Users\Desktop\Desktop\도현 physical
처리 날짜: 2026년 7월 31일
모드: 실행

발견된 마크다운 파일: 68개

✓ 업데이트: AI_Agents_Multi_Industry_Enterprise_Hub.md
✓ 업데이트: Autonomous_AI_Agent_Complete_Graph.md
  스킵: GRAPH_TEMPLATE.md
✓ 업데이트: Statistics_Probability_Foundations.md
...

============================================================
처리 완료
============================================================
처리됨: 68
업데이트: 12
스킵: 56
오류: 0
```

---

## 📊 메타데이터 모니터링

### Obsidian DataView를 사용한 통계

**쿼리**: 최근 업데이트된 파일

```
TABLE
  최종_업데이트,
  노드,
  상태
FROM "C:\Users\Desktop\Desktop\도현 physical"
WHERE 상태 = "활성"
SORT 최종_업데이트 DESC
```

### 수동 검증

```powershell
# 메타데이터가 있는 파일 찾기
Get-ChildItem -Path "C:\Users\Desktop\Desktop\도현 physical" -Filter "*.md" |
  Where-Object {$_ | Select-String "📌 최종 업데이트" -Quiet}

# 파일 수정 시간 확인
Get-ChildItem -Path "C:\Users\Desktop\Desktop\도현 physical" -Filter "*.md" |
  Select-Object Name, LastWriteTime |
  Sort-Object LastWriteTime -Descending
```

---

## 🔍 문제 해결

### Q: Python이 설치되지 않았어요
A: 
```
1. https://www.python.org에서 Python 3.8+ 다운로드
2. 설치 시 "Add Python to PATH" 체크
3. 재부팅 후 python --version 확인
```

### Q: 스크립트 실행 시 오류가 나요
A:
```
1. 인코딩 확인: UTF-8로 저장되어 있는지
2. 경로 확인: 파일명에 한글 없는지
3. 권한 확인: 폴더 쓰기 권한 있는지
4. 시뮬레이션 실행: python update_metadata.py --dry-run
```

### Q: 노드 수가 부정확해요
A:
노드 계산을 수동으로 조정하세요:
```markdown
**📌 노드**: [자동 계산값]+ (실제: 110개)
```

### Q: 특정 파일은 자동 업데이트 하지 말아야 해요
A:
`update_metadata.py`의 `skip_files` 변수에 추가:
```python
skip_files = {'파일명1.md', '파일명2.md', 'GRAPH_TEMPLATE.md'}
```

---

## 📅 권장 자동화 일정

```
월~금 (평일):
  - 오후 6시: 메타데이터 자동 업데이트
  - 오후 10시: Git 백업 + 메타데이터 동기화

토~일 (주말):
  - 오전 10시: 메타데이터 업데이트

특별 상황:
  - YouTube 비디오 추가 후: 즉시 수동 실행
  - 대규모 수정 후: 수동 실행
```

---

## 🚀 고급 사용법

### 배치 파일로 자동화 (Windows)

`update_metadata.bat` 생성:
```batch
@echo off
cd /d "C:\Users\Desktop\Desktop\도현 physical"
python update_metadata.py
echo.
echo 메타데이터 업데이트 완료!
pause
```

실행:
```powershell
.\update_metadata.bat
```

### Git과 연동

```powershell
# 메타데이터 업데이트 + Git 백업
python update_metadata.py
.\auto-backup.ps1 -CommitMessage "메타데이터 일일 자동 업데이트"
```

### 스케줄 태스크 로그 확인

```powershell
Get-EventLog -LogName Application -Source "TaskScheduler" |
  Where-Object {$_.Message -like "*Obsidian*"} |
  Select-Object TimeGenerated, Message |
  Sort-Object TimeGenerated -Descending |
  Format-Table -AutoSize
```

---

## 💡 베스트 프랙티스

### DO ✅
- 매일 자동 업데이트 실행
- 주간 1회 수동 검증
- 대규모 수정 후 즉시 실행
- 메타데이터 포맷 일관성 유지

### DON'T ❌
- 메타데이터 수동 편집 (자동화와 충돌)
- 스크립트 스킵 파일 목록 무단 변경
- 노드 수를 임의로 입력
- 메타데이터 포맷 변경

---

## 🔗 관련 가이드

- [[GIT_BACKUP_GUIDE]] - Git 자동 백업 설정
- [[TEMPLATE_USAGE_GUIDE]] - 새 그래프 생성
- [[GRAPH_TEMPLATE]] - 그래프 템플릿

---

**📌 최종 업데이트**: 2026-07-31  
**📌 상태**: 활성 (실제 사용 중)  
**📌 자동화 도구**:
  - Python 스크립트: update_metadata.py
  - Windows 작업 스케줄러
  - Obsidian 플러그인 (선택)
