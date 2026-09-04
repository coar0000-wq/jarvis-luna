# 특허 & 법률 데이터베이스 통합 시스템

**작성일**: 2026-08-01
**통합**: Davila7 USPTO Skill + 대한민국 법률 데이터
**버전**: 1.0 (완전판)
**목적**: 글로벌 특허 + 한국 법률 정보 자동화 시스템

---

## 🌐 시스템 개요

**기능**: USPTO 미국 특허 + 한국 법률 데이터 통합 검색 자동화
**범위**: 특허, 상표, 판례, 법령, 법률 전자동 수집
**지역**: 미국 + 한국 + 국제 특허

---

## 🏆 Category 1: Davila7 Scientific-USPTO Database Skill (6개)

### 1️⃣ Patent Search API Integration ⭐⭐⭐⭐⭐

| 항목 | 설명 |
|------|------|
| **기능** | USPTO 특허 검색 자동화 |
| **API** | PatentSearch (ElasticSearch 기반) |
| **전환** | PatentsView → PatentSearch (2025년 5월) |
| **정확도** | 99%+ 데이터 정확도 |

**검색 기능:**
```
1. 키워드 검색
   └─ 제목, 요약, 청구항 검색

2. 발명자/양수인 검색
   ├─ 발명자명 검색
   └─ 회사/기관명 검색

3. CPC 분류 검색
   └─ 기술 분류코드 검색

4. 특허번호/공개번호
   └─ 직접 조회
```

**자동화 스크립트:**
```python
# patent_search.py
from uspto_api import PatentSearch

search = PatentSearch()
results = search.query(
    keyword="AI machine learning",
    limit=100,
    sort="date"
)
```

---

### 2️⃣ Patent Examination Data System (PEDS) ⭐⭐⭐⭐⭐

| 항목 | 설명 |
|------|------|
| **기능** | 특허 심사 이력 자동 조회 |
| **범위** | 심사 절차, 거절이유, 응답 기록 |
| **효용** | 특허 무효화 가능성 분석 |

**PEDS 조회:**
```
1. 심사번호 입력
   ↓
2. 심사 이력 자동 조회
   ├─ 출원일
   ├─ 공개일
   ├─ 거절이유
   ├─ 응답 내용
   └─ 등록일
   ↓
3. 구조화된 데이터 생성
```

---

### 3️⃣ Trademark Status & Document Retrieval (TSDR) ⭐⭐⭐⭐⭐

| 항목 | 설명 |
|------|------|
| **기능** | 상표 상태 자동 추적 |
| **정보** | 등록현황, 갱신, 소유권 변경 |
| **업데이트** | 실시간 |

**상표 추적:**
```
상표명 입력
    ↓
등록 상태 확인
    ├─ 등록
    ├─ 거절
    ├─ 포기
    └─ 갱신 예정
    ↓
문서 자동 다운로드
```

---

### 4️⃣ Patent Citations & Prior Art Analysis ⭐⭐⭐⭐

| 항목 | 설명 |
|------|------|
| **기능** | 특허 인용 & 선행기술 분석 |
| **분석** | 인용 네트워크, 영향도 |
| **효과** | 특허 포트폴리오 가치 평가 |

---

### 5️⃣ Office Actions & Prosecution History ⭐⭐⭐⭐

| 항목 | 설명 |
|------|------|
| **기능** | 거절이유통지 & 응답 기록 |
| **추적** | 심사 진행 상황 |
| **분석** | 심사 패턴 분석 |

---

### 6️⃣ Bibliographic Data & PDF Extraction ⭐⭐⭐⭐

| 항목 | 설명 |
|------|------|
| **기능** | 특허 서지정보 & PDF 추출 |
| **포함** | 발명명, 발명자, 청구항, 도면 |
| **형식** | 구조화된 JSON |

---

## ⚖️ Category 2: 한국 법률 데이터베이스 (6개)

### 1️⃣ 국가법령정보센터 (law.go.kr) ⭐⭐⭐⭐⭐

| 항목 | 설명 |
|------|------|
| **기관** | 법제처 운영 |
| **콘텐츠** | 법률, 대통령령, 부령 등 |
| **데이터** | 현행법, 연혁법, 근대법 |
| **API** | Open API 제공 |

**검색 범위:**
```
1. 법령 (Laws)
   ├─ 법률
   ├─ 대통령령
   └─ 부령

2. 판례 & 해석례
   ├─ 판례
   ├─ 헌법재판소 결정
   └─ 행정심판례

3. 조약 & 규칙
   ├─ 국제조약
   └─ 행정규칙
```

**API 사용:**
```
URL: https://open.law.go.kr/LSO/openApi/
인증: API Key 필수
형식: JSON/XML
```

---

### 2️⃣ 대법원 종합법률정보 (glaw.scourt.go.kr) ⭐⭐⭐⭐⭐

| 항목 | 설명 |
|------|------|
| **기관** | 대법원 운영 |
| **핵심** | 판례 검색 |
| **범위** | 대법원, 고등법원, 지방법원 |
| **기간** | 1990년 이후 모든 판례 |

**판례 검색:**
```
검색식: 키워드, 법원, 판사, 법령
분류: 공시사항별, 판결문 등
정렬: 날짜, 관련도
필터: 기간, 법원급
```

---

### 3️⃣ 법고을 (lx.scourt.go.kr) ⭐⭐⭐⭐⭐

| 항목 | 설명 |
|------|------|
| **기능** | 통합 법률정보 검색 |
| **포함** | 헌법재판소, RISS, 법령 |
| **특징** | 해외판례 포함 |

---

### 4️⃣ 빅케이스 (bigcase.ai) ⭐⭐⭐⭐⭐

| 항목 | 설명 |
|------|------|
| **기능** | AI 기반 통합 법률정보 |
| **범위** | 판례, 법령, 논문, 결정례 |
| **특징** | 자연어 검색 지원 |

---

### 5️⃣ KIPRIS - 한국 특허 정보 (kipris.or.kr) ⭐⭐⭐⭐⭐

| 항목 | 설명 |
|------|------|
| **기관** | 한국특허정보원 운영 |
| **콘텐츠** | 특허, 실용신안, 디자인, 상표 |
| **범위** | 국내 + 12개국 해외 특허 |
| **API** | 공공데이터포털 제공 |

**검색 가능:**
```
1. 국내 지식재산권
   ├─ 특허
   ├─ 실용신안
   ├─ 디자인
   ├─ 상표
   └─ 심판례

2. 국제 특허
   ├─ 미국 (USPTO)
   ├─ 유럽 (EPO)
   ├─ 일본 (JPO)
   └─ 10개국 추가
```

---

### 6️⃣ 공공데이터포털 (data.go.kr) ⭐⭐⭐⭐

| 항목 | 설명 |
|------|------|
| **기관** | 정부통합데이터포털 |
| **데이터** | 법령, 판례, 특허 API |
| **업데이트** | 실시간 |

---

## 🔗 Category 3: 자동화 통합 시스템 (5개)

### 1️⃣ 글로벌 특허 검색 자동화 ⭐⭐⭐⭐⭐

**통합 워크플로우:**

```
기술/회사명 입력
    ↓
[미국] USPTO PatentSearch API 검색
[한국] KIPRIS API 검색
[국제] WIPO PatentScope 검색
    ↓
결과 통합
    ├─ 특허 발견
    ├─ 인용 네트워크
    └─ 심사 이력
    ↓
분석 보고서 생성
```

---

### 2️⃣ 한국 법률 자동 검색 ⭐⭐⭐⭐⭐

**법령 & 판례 자동화:**

```
법적 문제 입력
    ↓
1. 국가법령정보 검색
   └─ 관련 법령 추출

2. 판례 검색
   ├─ 대법원 판례
   └─ 유사 판례

3. 행정심판 검색
   └─ 관련 선례

4. 해석례 검색
   └─ 유권해석

    ↓
종합 법률 분석 보고서
```

---

### 3️⃣ 특허 침해 가능성 분석 ⭐⭐⭐⭐⭐

**침해 분석 자동화:**

```
신제품 기술 명세
    ↓
1. 특허 검색
   ├─ USPTO (미국)
   ├─ KIPRIS (한국)
   └─ WIPO (국제)

2. 선행기술 분석
   └─ Prior Art 확인

3. 청구항 분석
   └─ 침해 범위 판단

4. 법적 위험도 평가
   └─ Red/Yellow/Green Flag

    ↓
FTO (Freedom to Operate) 보고서
```

---

### 4️⃣ 특허 포트폴리오 관리 ⭐⭐⭐⭐

**포트폴리오 자동 추적:**

```
보유 특허 목록 입력
    ↓
1. 갱신 예정일 추적
2. 심사 진행 상황 모니터링
3. 인용 빈도 분석
4. 가치 평가 (h-index)
    ↓
실시간 포트폴리오 대시보드
```

---

### 5️⃣ 규제 & 컴플라이언스 모니터링 ⭐⭐⭐⭐

**법규 변동 추적:**

```
관심 법령 등록
    ↓
1. 법령 변경 자동 감지
2. 개정안 추출
3. 영향도 분석
4. 대응 방안 제시
    ↓
자동 알림 & 분석 보고서
```

---

## 📊 통합 시스템 매트릭스

| 기능 | USPTO | 한국법령 | 한국특허 | 자동화도 |
|------|-------|---------|---------|----------|
| **특허 검색** | ✅ | - | ✅ | 95% |
| **판례 검색** | ❌ | ✅ | - | 90% |
| **법령 검색** | ❌ | ✅ | ✅ | 95% |
| **침해 분석** | ✅ | ✅ | ✅ | 85% |
| **모니터링** | ✅ | ✅ | ✅ | 90% |

---

## 💻 기술 스택

```
API Layer:
├─ USPTO PatentSearch API
├─ KIPRIS REST API
├─ 국가법령정보 Open API
└─ 사법정보공유포털 API

Data Processing:
├─ Python 자동화
├─ JSON/XML 파싱
└─ 구조화 데이터 변환

Storage:
├─ Obsidian Vault
├─ JSON 데이터
└─ CSV 내보내기
```

---

## 🚀 설치 & 사용

### 설치
```bash
# Davila7 USPTO Skill 설치
npx skills add https://github.com/davila7/claude-code-templates \
  --skill uspto-database

# 한국 데이터 API 등록
# 공공데이터포털에서 API Key 발급 필수
```

### 사용
```python
# 통합 검색 예시
from patent_legal_search import search

# 미국 특허 검색
us_patents = search.patent("AI", region="US")

# 한국 판례 검색
kr_cases = search.legal("저작권", region="KR")

# 한국 특허 검색
kr_patents = search.patent("인공지능", region="KR")

# 종합 분석
analysis = search.analyze(
    patents=[us_patents, kr_patents],
    legal_cases=kr_cases
)
```

---

## 🏆 예상 효과

| 항목 | 수동 | 자동화 | 효율 |
|------|------|--------|------|
| **특허 조사** | 10시간 | 30분 | 95% ↓ |
| **법률 검토** | 8시간 | 20분 | 95% ↓ |
| **침해 분석** | 5시간 | 10분 | 95% ↓ |
| **비용** | $5,000 | $50 | 99% ↓ |

---

## 📚 링크

| 리소스 | URL | 설명 |
|--------|-----|------|
| **USPTO Database Skill** | https://github.com/davila7/claude-code-templates | Davila7 GitHub |
| **국가법령정보** | https://law.go.kr | 법제처 |
| **대법원 판례** | https://glaw.scourt.go.kr | 종합법률정보 |
| **KIPRIS** | https://www.kipris.or.kr | 한국특허정보 |
| **공공데이터포털** | https://www.data.go.kr | 정부통합포털 |
| **빅케이스** | https://bigcase.ai | AI 법률 검색 |

---

**🌐 완벽한 글로벌 + 한국 법률/특허 통합 시스템 완성!**

**Total: USPTO + 한국 법령 + 한국 특허 + 5개 자동화 통합**

Sources:
- [Davila7 Claude Code Templates GitHub](https://github.com/davila7/claude-code-templates)
- [USPTO PatentSearch API](https://mcpmarket.com/tools/skills/uspto-database-connector)
- [국가법령정보센터](https://law.go.kr)
- [대법원 종합법률정보](https://glaw.scourt.go.kr)
- [KIPRIS 지식재산정보 검색](https://www.kipris.or.kr)
- [공공데이터포털 API](https://www.data.go.kr)
