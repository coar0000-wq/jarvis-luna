# JARVIS 팀 4개 부서 확장 계획

**상태**: 설계 완료 (2026-08-03)  
**목표 달성 기한**: 2026-08-31  
**투자 리소스**: 12명 신규 채용/할당  
**예상 효과**: Level 2.8 → 2.9 AGI 진화

---

## 📊 현재 팀 구성 (5인)

```
        👑 JARVIS AI Chief
       /  |  \  \
      /   |   \  \
    🔍   🕸️   ✅  📝
    Data Graph  QA  Docs
  Classifier Architect Lead
```

**팀원별 역할**:
- 👑 Chief: 전략 수립, 통합 조율
- 🔍 Data Classifier: 정보 분류 및 카테고리화
- 🕸️ Graph Architect: 지식 그래프 설계
- ✅ QA Lead: 정보 검증 및 품질 관리
- 📝 Documentation: 문서화 및 가이드 작성

**한계점**:
- 정적 학습 (한 번 입력되면 변경 불가)
- 최신 정보 반영 지연 (수동 입력)
- 미디어 자동 분석 불가
- 복잡한 워크플로우 자동화 미흡

---

## 🚀 신규 팀 4개 (+ 12명)

### 팀 A: 미디어 분석팀 (3명)

**목표**: YouTube, Podcast 등 멀티미디어 콘텐츠 자동 분석

#### 역할 정의

| 직책 | 이름 | 책임 | 필수 스킬 |
|------|------|------|---------|
| **미디어 분석 리더** | - | 팀 전략, 품질 관리 | 프로젝트 관리, 미디어 이해 |
| **음성→텍스트 엔지니어** | - | Whisper API 연동, STT | Python, API 통합 |
| **자동 요약 엔지니어** | - | 텍스트 요약 및 추출 | NLP, GPT API |
| **메타 추출가** | - | Obsidian 자동 링크 | JSON/YAML, Obsidian API |

#### 기술 스택

```
입력: YouTube URL
  ↓
[Step 1] 영상 다운로드 (youtube-dl)
  ↓
[Step 2] 음성 추출 → Whisper 전송
  ↓
[Step 3] STT 결과 → GPT-4 요약
  ↓
[Step 4] 메타데이터 추출
  - 제목, 채널, 길이, 조회수
  - 태그, 카테고리
  - 자막 및 스크립트
  ↓
[Step 5] Phase 자동 매핑
  - 키워드 분석
  - 관련 Phase 식별
  ↓
[Step 6] 메모리 파일 자동 생성
  - Markdown 작성
  - YAML 메타데이터
  - 백링크 추가
  ↓
[Step 7] Obsidian 그래프 업데이트
  ↓
출력: 영상당 분석 리포트 (markdown)
```

#### 성과 지표

| 지표 | 목표 | 측정방법 |
|------|------|---------|
| 월간 분석 영상 수 | 50개 | 작업 로그 |
| 분석 시간/영상 | <30분 | 자동화 시스템 |
| 자동 분석 정확도 | 90% | 전문가 검증 |
| Obsidian 링크 자동화율 | 95% | 링크 검증 |

#### 첫 3개월 마일스톤

```
Week 1-2: 환경 설정
- Whisper API 연동
- YouTube API 인증
- 기초 파이프라인 구성

Week 3-4: 자동화 엔진 개발
- STT → 요약 연결
- 메타데이터 추출
- 오류 처리

Week 5-8: 통합 및 테스트
- 전체 파이프라인 테스트
- 정확도 평가
- Obsidian 연동
```

---

### 팀 B: 벡터DB 엔지니어링팀 (3명)

**목표**: RAG 시스템의 성능 최적화, 100만 문서 관리

#### 역할 정의

| 직책 | 이름 | 책임 | 필수 스킬 |
|------|------|------|---------|
| **벡터DB 아키텍트** | - | 시스템 설계, 최적화 전략 | 데이터베이스, 벡터 알고리즘 |
| **Pinecone/Weaviate 전문가** | - | 벡터DB 운영 | 클라우드 DB, 인덱싱 |
| **임베딩 모델 최적화가** | - | 임베딩 알고리즘 튜닝 | ML, 트랜스포머 모델 |
| **검색 정확도 개선가** | - | 검색 품질 향상 | 정보검색, 평가 메트릭 |

#### 기술 스택

```
의료 데이터 소스:
├─ 의료 논문 (arXiv, PubMed): 500만 개
├─ 임상 가이드라인: 10만 개
├─ 약물 정보: 5만 개
├─ 환자 기록 (익명화): 100만 개
└─ 의료 기사 및 리포트: 500만 개
        ↓
    [Document Chunking]
    500char ~ 1500char chunks
        ↓
    [Embedding Generation]
    OpenAI text-embedding-3-large (3072-dim)
        ↓
    [Vector Database]
    Pinecone (Starter Tier → Production)
    또는 Weaviate (Self-hosted)
        ↓
실시간 검색:
쿼리 임베딩 → 코사인 유사도 → Top-K 반환

성능 목표:
- 응답시간: < 100ms
- 처리량: 10,000 쿼리/분
- 정확도: 87%+ (의료 전문가 평가)
```

#### 벡터DB 비교

| 특성 | Pinecone | Weaviate | Milvus |
|------|----------|----------|--------|
| 관리형 | ✅ Yes | ❌ Self-hosted | ❌ Self-hosted |
| 확장성 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| 비용 | 중간 | 낮음 | 낮음 |
| API 쉬움 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| **추천** | **의료(프로덕션)** | 실험/학습 | 대규모 자체호스팅 |

#### 성과 지표

| 지표 | 목표 | 측정방법 |
|------|------|---------|
| 벡터DB 저장소 크기 | 100만 문서 | 데이터베이스 통계 |
| 검색 응답시간 | <100ms | 부하테스트 |
| 검색 정확도 | 87% | 관련성 평가 |
| 시스템 가용성 | 99.9% | 모니터링 대시보드 |
| 비용/월 | <$500 | 구독 청구 |

#### 첫 3개월 마일스톤

```
Week 1-2: 벡터DB 설정
- Pinecone Pro 계정 생성
- 초기 인덱스 생성 (100만 벡터)
- 성능 벤치마크

Week 3-4: 임베딩 파이프라인
- 의료 문서 준비
- 배치 임베딩 생성
- 벡터DB에 로드

Week 5-8: 최적화 및 모니터링
- 검색 성능 조정
- 정확도 개선
- 프로덕션 배포
```

---

### 팀 C: LangGraph 오토메이션팀 (3명)

**목표**: 복잡한 의료 워크플로우 자동화, 상태 머신 설계

#### 역할 정의

| 직책 | 이름 | 책임 | 필수 스킬 |
|------|------|------|---------|
| **LangGraph 아키텍트** | - | 워크플로우 설계, 상태 관리 | 그래프 이론, 상태머신 |
| **상태 머신 설계자** | - | 조건부 로직, 루프 처리 | 프로그래밍, 요구사항 분석 |
| **에러 복구 전문가** | - | 실패 처리, 재시도 전략 | 시스템 설계, 테스트 |
| **성능 최적화가** | - | 실행 속도, 메모리 관리 | 프로파일링, 알고리즘 |

#### 기술 스택

```
LangGraph 의료 워크플로우 예시:

┌─────────────────────────────────────────┐
│   의료 진단 및 치료 계획 워크플로우      │
└─────────────────────────────────────────┘

[START] 환자 내원
  ↓
[NODE: intake_info] 기본 정보 수집
- 성명, 나이, 주증상
- 병력, 약력
- 알레르기
  ↓
[NODE: initial_assessment] 초기 평가
- LLM이 증상 분석
- Chain-of-Thought 추론
- 위험도 평가
  ↓
[CONDITIONAL EDGE]
증상 심각도?
├─ 응급 → [PATH: Emergency] → 응급실 의뢰
├─ 중증 → [PATH: Urgent] → 당일 진료 우선
└─ 경증 → [PATH: Routine] → 일반 진료
  ↓
[NODE: order_tests]
필요한 검사 결정
- 혈액검사
- 영상검사
- 기타 전문 검사
  ↓
[WAIT] 검사 결과 대기
  ↓
[NODE: interpret_results]
검사 결과 해석
- 정상/이상 판정
- 이상 수치 분석
  ↓
[NODE: differential_diagnosis]
감별진단 수립
- LLM이 최상위 5개 진단 제시
- 각 확률 계산
- 근거 제시
  ↓
[NODE: treatment_plan]
치료 계획 수립
- MCP 약물 도구 호출
- 약물 상호작용 확인
- 복용량 최적화
  ↓
[NODE: patient_communication]
환자 설명 및 동의
- 쉬운 용어로 변환
- Q&A 답변
  ↓
[NODE: follow_up_schedule]
추적관찰 계획
- 약속 설정
- 추후 검사 일정
  ↓
[END] 진료 완료
```

#### 상태머신 코드 구조

```python
from langgraph.graph import StateGraph, START, END
from typing import TypedDict

class PatientState(TypedDict):
    patient_id: str
    symptoms: list[str]
    medical_history: dict
    test_results: dict
    diagnosis: list[dict]  # [{name: "...", probability: 0.8}, ...]
    medications: list[str]
    alerts: list[str]
    follow_up: dict

graph = StateGraph(PatientState)

# 노드 정의
def intake_node(state: PatientState):
    # 환자 정보 수집
    return {...updated_state...}

def assess_node(state: PatientState):
    # LLM으로 증상 분석
    return {...updated_state...}

# 조건부 라우팅
def route_by_severity(state: PatientState) -> str:
    severity = state.get("severity_score", 0)
    if severity > 8:
        return "emergency"
    elif severity > 5:
        return "urgent"
    else:
        return "routine"

# 그래프 구성
graph.add_node("intake", intake_node)
graph.add_node("assess", assess_node)
graph.add_node("tests", order_tests_node)
# ... 더 많은 노드

graph.add_edge(START, "intake")
graph.add_edge("intake", "assess")
graph.add_conditional_edges(
    "assess",
    route_by_severity,
    {
        "emergency": "emergency_path",
        "urgent": "urgent_path",
        "routine": "routine_path"
    }
)

# 실행
state = {...initial_state...}
result = graph.invoke(state)
```

#### 성과 지표

| 지표 | 목표 | 측정방법 |
|------|------|---------|
| 워크플로우 완성도 | 100% | 기능 체크리스트 |
| 에러율 | <1% | 로그 분석 |
| 평균 진료 시간 | 40분 | 시스템 기록 |
| 의료진 만족도 | 4.5/5 | 설문조사 |
| 환자 만족도 | 4.5/5 | 설문조사 |

#### 첫 3개월 마일스톤

```
Week 1-2: LangGraph 학습
- 기본 개념 이해
- 예제 코드 실행
- 의료 케이스 분석

Week 3-4: 워크플로우 설계
- 상태 정의
- 노드 설계
- 조건부 로직 구현

Week 5-8: 통합 및 테스트
- 전체 파이프라인 구성
- 에러 처리
- 성능 최적화
- 의료진 피드백 수렴
```

---

### 팀 D: MCP 도구 통합팀 (3명)

**목표**: 의료 시스템과 LLM을 연결, 10개 도구 통합

#### 역할 정의

| 직책 | 이름 | 책임 | 필수 스킬 |
|------|------|------|---------|
| **MCP 프로토콜 전문가** | - | MCP 서버 설계, 표준화 | API 설계, 보안 |
| **EHR 연동 엔지니어** | - | 의료 기록 시스템 연동 | 의료 IT, HL7/FHIR |
| **의료DB API 통합가** | - | 약물, 검사 DB 연결 | 데이터베이스, API |
| **보안 & 감시 전문가** | - | 권한 관리, 감사 로깅 | 정보보호, 의료규제 |

#### 10개 필수 도구

```
의료 MCP 서버 구성:

[MCP Server]
├─ Tool 1: get_patient_info
│   인터페이스: (patient_id) → patient_data
│   권한: 진료중인 환자만
│   로깅: 모든 조회 기록
│
├─ Tool 2: search_medical_records
│   인터페이스: (keyword, date_range) → records
│   권한: 해당 부서 기록만
│   로깅: 검색어 및 결과 기록
│
├─ Tool 3: order_lab_tests
│   인터페이스: (patient_id, test_list) → order_confirmation
│   권한: 의사 권한 필요
│   로깅: 주문 및 승인자 기록
│
├─ Tool 4: query_drug_database
│   인터페이스: (drug_name) → drug_info
│   권한: 모든 사용자
│   로깅: 조회 기록
│
├─ Tool 5: check_drug_interactions
│   인터페이스: (drug_list) → interaction_warnings
│   권한: 모든 사용자
│   로깅: 상호작용 확인 기록
│
├─ Tool 6: get_clinical_guidelines
│   인터페이스: (condition) → guidelines_list
│   권한: 모든 사용자
│   로깅: 조회 기록
│
├─ Tool 7: record_diagnosis
│   인터페이스: (patient_id, diagnosis, icd_code) → confirmation
│   권한: 의사 권한 필요
│   로깅: 진단 기록 및 타임스탬프
│
├─ Tool 8: prescribe_medication
│   인터페이스: (patient_id, drug, dosage, duration) → prescription_id
│   권한: 의사 권한 필요
│   로깅: 처방 기록 및 승인
│
├─ Tool 9: get_patient_allergies
│   인터페이스: (patient_id) → allergy_list
│   권한: 진료중인 의료진만
│   로깅: 알레르기 조회 기록
│
└─ Tool 10: save_clinical_notes
    인터페이스: (patient_id, notes) → note_id
    권한: 의료진만
    로깅: 노트 저장 및 수정 이력
```

#### MCP 서버 구현 구조

```python
from mcp.server import Server
from mcp.types import Tool, Resource

server = Server("medical-llm-server")

# Tool 1: 환자 정보 조회
@server.tool()
def get_patient_info(patient_id: str) -> dict:
    """
    환자의 기본 정보 조회
    권한: 진료 의료진만
    """
    # 권한 확인
    if not has_permission(current_user, patient_id):
        raise PermissionError("Access denied")
    
    # 데이터 조회
    patient = db.query(Patient).filter(id=patient_id).first()
    
    # 감시 로그
    audit_log.record({
        "action": "get_patient_info",
        "user": current_user.id,
        "patient": patient_id,
        "timestamp": datetime.now()
    })
    
    return {
        "name": patient.name,
        "age": patient.age,
        "medical_history": patient.history,
        "medications": patient.current_meds,
        "allergies": patient.allergies
    }

# Tool 5: 약물 상호작용 확인
@server.tool()
def check_drug_interactions(drug_list: list[str]) -> dict:
    """
    약물들 간의 상호작용 확인
    권한: 모든 사용자
    """
    interactions = []
    
    for i, drug1 in enumerate(drug_list):
        for drug2 in drug_list[i+1:]:
            interaction = drug_db.check_interaction(drug1, drug2)
            if interaction:
                interactions.append({
                    "drug1": drug1,
                    "drug2": drug2,
                    "severity": interaction.severity,  # low/medium/high
                    "description": interaction.description,
                    "recommendation": interaction.recommendation
                })
    
    return {
        "interactions": interactions,
        "overall_risk": determine_overall_risk(interactions),
        "timestamp": datetime.now()
    }

# 서버 실행
server.start()
```

#### 보안 및 규제 준수

```
의료 보안 체크리스트:

□ 인증 (Authentication)
  - 의료진 자격증 확인
  - OAuth 2.0 기반 로그인
  - MFA (Multi-Factor Authentication)

□ 권한 관리 (Authorization)
  - Role-Based Access Control (RBAC)
  - 환자별 접근 권한
  - 부서별 데이터 격리

□ 데이터 보호 (Encryption)
  - 전송 암호화: TLS 1.3
  - 저장소 암호화: AES-256
  - 키 관리: HSM

□ 감시 및 로깅 (Auditing)
  - 모든 도구 사용 기록
  - 데이터 접근 로그
  - 이상 탐지 알림

□ 규제 준수 (Compliance)
  - HIPAA (US)
  - GDPR (EU)
  - 개인정보보호법 (한국)

□ 재해 복구 (Disaster Recovery)
  - 일일 백업
  - 지리적 분산 저장
  - RTO < 4시간
```

#### 성과 지표

| 지표 | 목표 | 측정방법 |
|------|------|---------|
| 통합 도구 수 | 10개 | 도구 목록 |
| API 응답시간 | <500ms | 모니터링 |
| 보안 감시 커버리지 | 100% | 로그 검증 |
| 규제 준수 | 100% | 감시 보고서 |
| 시스템 가용성 | 99.95% | SLA 모니터링 |

#### 첫 3개월 마일스톤

```
Week 1-2: MCP 기초 학습
- MCP 프로토콜 이해
- 예제 서버 실행
- 의료 요구사항 정의

Week 3-4: 도구 개발 (1-5번)
- 환자 정보 조회
- 의료 기록 검색
- 검사 주문
- 약물 데이터베이스
- 상호작용 확인

Week 5-6: 도구 개발 (6-10번)
- 임상 가이드라인
- 진단 기록
- 처방약 기록
- 알레르기 조회
- 임상 노트 저장

Week 7-8: 보안 및 테스트
- 권한 관리 구현
- 감사 로깅
- 보안 테스트
- 규제 준수 검증
```

---

## 📈 팀 확장 타임라인

```
시간     마일스톤                 상태      참고
────────────────────────────────────────────────────
2026-08-03  팀 확장 계획 수립      ✅ 완료
2026-08-10  팀원 모집/배치 완료    ⏳ 예정   각 팀 3명씩
2026-08-17  기초 교육 완료          ⏳ 예정   1주 집중교육
2026-08-24  각 팀 프로토타입      ⏳ 예정   기본 기능
2026-08-31  팀별 1차 완성          ⏳ 예정   파일럿 운영
2026-09-30  전체 통합 완료        ⏳ 예정   프로덕션 배포
```

---

## 💰 예산 추정

### 인건비 (월간)

| 팀 | 직급 | 인원 | 연봉 | 월간 비용 |
|------|------|------|------|----------|
| A (미디어) | 리더 | 1 | 6,000만원 | 500만원 |
| A (미디어) | 엔지니어 | 2 | 5,000만원 | 833만원 |
| B (벡터DB) | 리더 | 1 | 6,500만원 | 542만원 |
| B (벡터DB) | 엔지니어 | 2 | 5,500만원 | 917만원 |
| C (LangGraph) | 리더 | 1 | 6,000만원 | 500만원 |
| C (LangGraph) | 엔지니어 | 2 | 5,000만원 | 833만원 |
| D (MCP) | 리더 | 1 | 7,000만원 | 583만원 |
| D (MCP) | 엔지니어 | 2 | 5,500만원 | 917만원 |
| **합계** | - | **12명** | - | **5,128만원** |

### 기술 비용 (월간)

| 항목 | 가격 | 용도 |
|------|------|------|
| Pinecone Pro | $300 | 벡터DB |
| OpenAI API (Embeddings) | $200 | 임베딩 생성 |
| YouTube API | $0 | 영상 메타데이터 |
| Whisper API | $100 | 음성→텍스트 |
| 클라우드 서버 | $500 | MCP 호스팅 |
| 모니터링/로깅 | $200 | DataDog 등 |
| **합계** | **$1,300** | **약 170만원** |

### 총 월간 비용: **약 5,300만원** (인건비 + 기술비)

---

## 🎯 성과 목표 (3개월)

### 정량적 지표

| 지표 | 현재 | 3개월 후 | 증가율 |
|------|------|---------|--------|
| 월간 분석 콘텐츠 | 0개 | 50개 | ∞ |
| 벡터DB 문서 수 | 0개 | 100만개 | ∞ |
| 워크플로우 노드 | 5개 | 20개+ | +300% |
| MCP 도구 수 | 0개 | 10개 | ∞ |
| 메모리 파일 수 | 50개 | 250개+ | +400% |

### 정성적 목표

| 영역 | 목표 |
|------|------|
| **자동화** | 수동 작업 80% 감소 |
| **성능** | RAG 검색 정확도 87% 달성 |
| **신뢰성** | 시스템 가용성 99.9%+ |
| **확장성** | 새 데이터 소스 쉽게 추가 가능 |
| **협력** | 의료진 만족도 4.5/5 이상 |

---

## 🔄 팀 간 협력 구조

```
           👑 JARVIS Chief
           /  |  \  \
          /   |   \  \
        🔍   🕸️   ✅  📝
    (기존 5인 팀)
        ↓↓↓↓↓↓↓↓↓↓
        
      신규 팀 4개
      /  |  \  \
    📺  📊  🔄  🛠️
    미디어 벡터 LG  MCP
    분석  DB  래프  도구
    (3명) (3명) (3명) (3명)
    
협력 흐름:
1. 미디어팀 → 영상 분석 및 메모리 파일 생성
2. Graph팀 → Obsidian에 노드 추가, 링크 생성
3. 벡터DB팀 → 문서 임베딩 및 인덱싱
4. LangGraph팀 → 워크플로우 자동화
5. MCP팀 → 외부 도구 연동
6. QA팀 → 품질 검증
```

---

## ✅ 성공 조건

1. **기술적 요구사항**
   - 모든 팀이 해당 기술 완전 숙달
   - 통합 테스트 통과 (100%)
   - 성능 벤치마크 달성

2. **조직적 요구사항**
   - 팀원 모집 완료
   - 주간 회의 및 협력 체계 확립
   - 명확한 책임 및 권한 구분

3. **비즈니스 요구사항**
   - 예산 범위 내 운영
   - 의료진 만족도 4.5/5 이상
   - 환자 데이터 보안 100% 준수

---

## 🚀 다음 단계

1. **Week 1**: 팀원 모집 공고 발행
2. **Week 2**: 면접 및 선발
3. **Week 3**: 온보딩 및 기초 교육
4. **Week 4+**: 각 팀별 개발 시작

**최종 목표**: 2026년 9월 말 프로덕션 배포 → JARVIS Level 2.9 AGI 진화!

