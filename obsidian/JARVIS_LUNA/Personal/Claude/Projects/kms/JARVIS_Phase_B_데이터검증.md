# 🔐 JARVIS Phase B - 데이터 검증 시스템

**프로젝트**: JARVIS Level 2.8 → 3.0 발전  
**단계**: Phase B (우선순위 2)  
**기한**: 2026-08-18 (2주)  
**상태**: 🟢 개발 시작

---

## 📋 **목표**

**현재**: Phase A에서 수집한 980개 자료의 검증 없음  
**목표**: 신뢰도 95% 이상만 저장

---

## 🎯 **Skill 2: 데이터 검증 시스템**

### **기능 정의**

```
Phase A에서 수집한 자료에 대해:

1. 📊 신뢰도 점수 계산
   - 출처 신뢰도 (출처 평판)
   - 내용 신뢰도 (팩트체크)
   - 최신도 (발행일 최신성)
   - 인용도 (인용 횟수)
   
2. 🔄 중복 제거
   - 제목 유사도 검사
   - URL 중복 검사
   - 내용 해시 비교
   
3. 🏷️ 품질 필터링
   - 스팸 제거
   - 저품질 자료 제외
   - 관련성 확인
   
4. 📂 자동 카테고리 분류
   - NLP 기반 분류
   - 태그 자동 생성
   - 우선순위 결정
```

### **검증 파이프라인**

```
수집 데이터
  ↓
신뢰도 점수 계산 (1-100)
  ↓
점수 > 70? (기준값)
  ├─ YES → 다음 단계
  └─ NO → 제외
  ↓
중복 검사
  ├─ 중복 아님 → 다음 단계
  └─ 중복 → 제외
  ↓
품질 필터링
  ├─ 통과 → 다음 단계
  └─ 실패 → 제외
  ↓
자동 분류 및 저장
```

### **신뢰도 점수 알고리즘**

```python
신뢰도 점수 = 
  (출처신뢰도 × 0.3) +
  (내용신뢰도 × 0.3) +
  (최신도 × 0.2) +
  (인용도 × 0.2)

최종 점수 기준:
  90-100: 매우 높음 (신뢰할 수 있음)
  70-89:  높음     (대부분 신뢰 가능)
  50-69:  중간     (추가 검증 필요)
  30-49:  낮음     (의심스러움)
  0-29:   매우낮음 (제외 권장)
```

---

## 💻 **구현 계획**

### **Step 1: 출처 신뢰도 분석** (3-4일)

```python
def calculate_source_credibility():
    # 알려진 신뢰 출처
    trusted_sources = {
        "TechCrunch": 0.95,
        "MIT News": 0.98,
        "Nature": 0.99,
        "arXiv": 0.95,
        "IEEE": 0.97,
        ...
    }
    
    # 출처 명성 점수
    for source in data:
        credibility = get_source_score(source)
        return credibility
```

### **Step 2: 내용 신뢰도 분석** (3-4일)

```python
def calculate_content_credibility():
    # 팩트체크
    facts = extract_facts(content)
    verified_facts = verify_facts(facts)
    
    # 신뢰도 점수
    credibility = len(verified_facts) / len(facts)
    return credibility
```

### **Step 3: 최신도 계산** (2-3일)

```python
def calculate_freshness():
    # 발행일 기준
    days_old = (today - publish_date).days
    
    if days_old <= 7:
        freshness = 1.0  # 최신
    elif days_old <= 30:
        freshness = 0.8  # 최근
    elif days_old <= 90:
        freshness = 0.6  # 약간 구식
    else:
        freshness = 0.4  # 구식
    
    return freshness
```

### **Step 4: 인용도 계산** (2-3일)

```python
def calculate_citation_score():
    # 인용 횟수 기반
    citations = get_citation_count(paper)
    
    # 정규화
    citation_score = min(citations / 100, 1.0)
    return citation_score
```

### **Step 5: 통합 검증 엔진** (2-3일)

```python
def validate_all_data():
    for data_item in collected_data:
        # 모든 점수 계산
        trust_score = calculate_all_scores(data_item)
        
        # 필터링
        if trust_score >= 70:
            # 중복 검사
            if not is_duplicate(data_item):
                # 품질 검사
                if passes_quality_check(data_item):
                    # 자동 분류
                    data_item['category'] = auto_classify(data_item)
                    save_to_obsidian(data_item)
```

---

## 📊 **예상 결과**

### **검증 효율**

```
Phase A 수집: 980개
신뢰도 > 70: ~750개 (76%)
중복 제거 후: ~650개 (66%)
품질 필터 후: ~600개 (61%)
최종 저장: ~600개 (신뢰도 95%)
```

### **자료 증가 예상**

```
이전: 5,630개
검증됨: 600개 (높은 신뢰도)
현재: 6,230개 (안정적 자료)
증가: 11% (품질 높음)
```

---

## 🔍 **검증 기준 상세**

### **신뢰 출처 리스트**

| 카테고리 | 출처 | 신뢰도 |
|---------|------|--------|
| 논문 | Nature | 0.99 |
| 논문 | arXiv | 0.95 |
| 뉴스 | MIT News | 0.98 |
| 뉴스 | TechCrunch | 0.95 |
| 기술 | IEEE | 0.97 |

### **스팸 필터 기준**

❌ 제외 기준:
- 광고성 콘텐츠 >50%
- 오타 >10개
- 단어 반복 >20%
- 프로모션 링크 >5개

✅ 통과 기준:
- 오리지널 콘텐츠 >80%
- 정상 문법
- 학문적/뉴스 형식

---

## 📈 **성공 지표**

| 항목 | 목표 | 예상 |
|------|------|------|
| 검증율 | 95%+ | 95% |
| 중복 제거 | 80%+ | 85% |
| 품질 유지 | 90%+ | 92% |
| 처리 시간 | <10초 | 8초 |

---

## ⏰ **일정**

```
2026-08-12 (월): Step 1 시작
2026-08-13 (화): Step 1, 2 진행
2026-08-14 (수): Step 2, 3 진행
2026-08-15 (목): Step 3, 4 진행
2026-08-16 (금): Step 4, 5 진행
2026-08-17 (토): 통합 테스트
2026-08-18 (일): Phase B 완료 ✅
```

---

## 🎯 **Phase B 완료 기준**

- ✅ 신뢰도 점수 계산 시스템 작동
- ✅ 중복 제거 95% 이상
- ✅ 품질 필터링 90% 이상
- ✅ 자동 분류 시스템 작동
- ✅ 최종 자료 600개 이상 저장
- ✅ Obsidian 통합

---

## 📌 **다음 단계**

Phase B 완료 후:
→ **Phase C: 자동 요약 시스템** 개발

---

**상태**: 🟢 개발 진행 중  
**담당**: JARVIS AI System  
**목표**: 2026-08-18 Phase B 완료!

