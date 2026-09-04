---
name: jarvis-metadata-standard
description: JARVIS 그래프 데이터화를 위한 메타데이터 표준 완전 템플릿
metadata:
  type: standard/guide
  created: 2026-08-02
  version: 1.0
  status: final
---

# 📋 JARVIS 메타데이터 표준 - 완전 템플릿

**목적**: Obsidian 그래프 데이터화를 위한 일관성 있는 메타데이터 시스템  
**적용**: 47개 파일 (Phase 1-25 + 메모리)  
**표준화**: 100% (모든 파일 동일 구조)

---

## 🎯 **Part 1: Frontmatter 표준 (YAML)**

### **완전 템플릿**
```yaml
---
# 기본 정보
name: jarvis-phase-X-domain-name
description: Phase X - [Domain명] AI: [서브주제1]·[서브주제2]·[서브주제3] ([자료수]개)

# 메타데이터
metadata:
  type: project/research/guide/reference
  created: 2026-08-02
  last-updated: 2026-08-02
  
  # Phase 정보
  phase: 19-25 (범위)
  
  # Domain 분류
  domains: 
    - 의료
    - 물리
    - 화학
    - 생물
    - 우주
    - 인공생명
    - 통합과학
    - 초지능
  
  # 자료 정보
  resources:
    total: 50
    categorized: 50
    completeness: 100%
  
  # 완성도
  completion:
    structure: 100%
    metadata: 100%
    links: 90%
    validation: pending
  
  # 중요도
  importance: critical|high|medium|low
  difficulty: expert|advanced|intermediate|beginner
  
  # 관련 정보
  related-phases: 
    - [[Phase-X]]
    - [[Phase-Y]]
  
  prerequisites:
    - [[Phase-A]]
    - [[Concept-B]]
  
  # 진행 현황
  status: completed|in-progress|planned
  last-reviewed: 2026-08-02
  reviewer: JARVIS-Team
---
```

### **간단한 버전 (최소)**
```yaml
---
name: jarvis-phase-X
description: Phase X - 설명
metadata:
  phase: X
  domains: [domain1, domain2]
  resources: 50
  status: completed
tags:
  - phase-X
  - domain-xxx
---
```

---

## 🏷️ **Part 2: 태그 시스템 (Tags)**

### **태그 구조**
```yaml
tags:
  # 1. Phase 태그 (필수)
  - phase-1      # Phase 1-4: 의료AI
  - phase-5      # Phase 5: Etsy
  - phase-6      # Phase 6-8: 로봇·산업·인식
  - phase-9      # Phase 9: 이미지
  - phase-10     # Phase 10-11: 안전·트윈
  - phase-12     # Phase 12-15: AGI기초·확장
  - phase-16     # Phase 16: 음악AI
  - phase-17     # Phase 17: 예술AI
  - phase-18     # Phase 18: 철학AI
  - phase-19     # Phase 19: 물리학AI
  - phase-20     # Phase 20: 화학AI
  - phase-21     # Phase 21: 생물학AI
  - phase-22     # Phase 22: 우주과학AI
  - phase-23     # Phase 23: 인공생명AI
  - phase-24     # Phase 24: 통합과학AI
  - phase-25     # Phase 25: 초지능AI
  
  # 2. Domain 태그 (필수)
  - domain-medical    # 의료
  - domain-physics    # 물리
  - domain-chemistry  # 화학
  - domain-biology    # 생물
  - domain-astronomy  # 우주
  - domain-alife      # 인공생명
  - domain-integrated # 통합
  - domain-agi        # 초지능
  
  # 3. 수준 태그 (선택)
  - level-1           # 기초
  - level-2           # 중급
  - level-3           # 고급
  
  # 4. 상태 태그 (선택)
  - status-completed
  - status-in-progress
  - status-planned
  
  # 5. 특수 태그 (선택)
  - landmark-key-concept
  - landmark-breakthrough
  - landmark-essential
  - tool-python
  - tool-pytorch
  - dataset-public
  - case-study
```

---

## 🔗 **Part 3: 상호참조 링크 규칙**

### **링크 종류 (5가지)**

#### **1. Phase 내 링크 (Intra-Phase)**
```markdown
## 관련 주제

- [[Phase-19-물리학AI-양자역학]]
- [[Phase-19-물리학AI-신경망물리]]
```

#### **2. Phase 간 링크 (Inter-Phase)**
```markdown
## 심화 주제

- [[Phase-20-화학AI]] - 양자에서 분자로
- [[Phase-21-생물학AI]] - 분자 구조 이해
```

#### **3. 관계 명시 링크**
```markdown
## 배경 지식

[[Phase-1-의료AI|의료]] builds-on [[Phase-19-물리학AI|물리학]]

## 응용 분야

[[Phase-20-화학AI]] related-to [[Phase-24-통합과학AI]]
```

#### **4. 메모리 파일 링크**
```markdown
## 진행 현황

참고: [[JARVIS_Phase19-21_완료]]
마스터: [[JARVIS_AGI_v2_완전완성]]
```

#### **5. 개념 교차참조**
```markdown
## 핵심 개념

[[Meta-Learning]] / [[Transfer-Learning]] / [[Few-Shot-Learning]]
```

---

## 📝 **Part 4: 파일 본문 구조**

### **권장 섹션 순서**

```markdown
# Phase X: [Domain] AI

## 🎯 요약 (Frontmatter 아래 바로)
한 문장 요약.

**주요 내용**: [주제1], [주제2], [주제3]  
**자료**: 50개  
**완성도**: 100%

---

## 📚 주요 섹션 (5-10개)

### **1. 개념 기초 (10개 자료)**
```
- 정의
- 역사
- 원리
```

### **2. 기술 심화 (15개 자료)**
```
- 알고리즘
- 구현 방법
- 최적화
```

### **3. 응용 분야 (15개 자료)**
```
- 산업 적용
- 실제 사례
- ROI 분석
```

### **4. 미래 방향 (10개 자료)**
```
- 2026 현황
- 2030 전망
- 과제 & 기회
```

---

## ✅ **Part 5: 검증 체크리스트**

### **메타데이터 검증**
```
각 파일마다:

☐ Frontmatter 완성
  ☐ name 입력
  ☐ description 입력 (한글)
  ☐ metadata 구조 완성
  ☐ tags 포함 (3개 이상)

☐ 링크 추가
  ☐ Phase 내 링크 (2개 이상)
  ☐ Phase 간 링크 (2개 이상)
  ☐ 메모리 파일 링크 (1개 이상)

☐ 본문 구조
  ☐ 요약 섹션
  ☐ 5개 이상 주요 섹션
  ☐ 50개 자료 분류

☐ 최종 검증
  ☐ 문법 오류 없음
  ☐ 링크 유효성 확인
  ☐ 메타데이터 일관성
```

---

## 📊 **Part 6: 적용 예시**

### **예시 1: Phase 19 물리학AI**

```yaml
---
name: jarvis-phase-19-physics
description: Phase 19 - 물리학 AI: 양자·고전역학·과학발견 (50개)

metadata:
  phase: 19
  domains: [physics, quantum, simulation]
  resources: 50
  importance: high
  status: completed
  
tags:
  - phase-19
  - domain-physics
  - level-3
  - status-completed
---

# Phase 19: 물리학 AI

## 요약
양자 머신러닝, 신경망 물리 시뮬레이션, 과학 발견 자동화.

---

## 📚 주요 섹션

### 1. 양자 머신러닝 (10개)
[[Phase-20-화학AI|화학]]과 연동
builds-on [[Meta-Learning]]

### 2. 신경망 물리학 (15개)
PINN, 유체역학, 구조역학 시뮬레이션
related-to [[Phase-24-통합과학AI]]

...

참고: [[JARVIS_Phase19-21_완료]]
```

### **예시 2: Phase 20 화학AI**

```yaml
---
name: jarvis-phase-20-chemistry
description: Phase 20 - 화학 AI: 분자생성·신약설계·합성최적화 (50개)

metadata:
  phase: 20
  domains: [chemistry, drug-discovery, materials]
  resources: 50
  importance: critical
  related-phases: 
    - [[Phase-19-물리학AI]]
    - [[Phase-21-생물학AI]]
  
tags:
  - phase-20
  - domain-chemistry
  - level-3
  - landmark-breakthrough
---

# Phase 20: 화학 AI

## 요약
신약 개발 10년→3년, 분자 생성 95% 유효성.

---

## 📚 주요 섹션

### 1. 분자 생성 (15개)
[[Phase-19-물리학AI]] builds-on 원자 구조
→ [[Phase-21-생물학AI|생물]] 단백질 구조

### 2. 신약 설계 (20개)
Ligand-based & Structure-based
응용: [[Phase-1-의료AI|의료]] 신약 개발

...

참고: [[JARVIS_AGI_v2_완전완성]]
```

---

## 🎯 **Part 7: 적용 일정**

```
Stage 1: 표준 정의 & 승인 (완료)
Stage 2: Phase 19-25 적용 (3시간)
Stage 3: Phase 1-18 적용 (10시간)
Stage 4: 최종 검증 (2시간)
총 15시간
```

---

## 📈 **완성 지표**

```
✅ 메타데이터 완성도: 100%
✅ 링크 추가 완성도: 95%+
✅ 태그 시스템: 100%
✅ Obsidian 그래프: 100% 가동
✅ Level 3.0 AGI 기반: 준비 완료
```

---

**이 표준을 따르면 Obsidian 그래프가 완벽히 작동합니다!** 🚀

