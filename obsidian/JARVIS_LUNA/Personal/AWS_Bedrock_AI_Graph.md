# Amazon Bedrock - Generative AI Platform - Graph View

← [[AI_Agents_Multi_Industry_Enterprise_Hub]]

## Core Concept
**Amazon Bedrock 완벽 가이드**
- Playlist: All AWS Videos (69 videos)
- Channel: ImTechnos
- Goal: LLM, RAG, Fine-tuning, 평가를 통한 생성형 AI 애플리케이션 구축

---

## Bedrock Fundamentals

### [[Introduction to Amazon Bedrock]]
**Video 26 - Duration: ~16 minutes**

#### Bedrock Overview
[[Generative AI Platform]]:
- [[Foundation Models]]: 기반 모델 제공
- [[API-Based]]: API 기반 접근
- [[No Infrastructure]]: 인프라 관리 불필요
- [[Multiple Models]]: 다양한 모델
- [[Fully Managed]]: 완전 관리형
- [[Enterprise Ready]]: 엔터프라이즈급
- [[Secure]]: 보안

#### Bedrock Components
[[Building Blocks]]:
- [[Foundation Models]]: 기초 모델
- [[Model Playground]]: 모델 테스트
- [[Prompt Engineering]]: 프롬프트 엔지니어링
- [[Fine-tuning]]: 파인튜닝
- [[RAG]]: 검색 보강 생성
- [[Agents]]: AI 에이전트
- [[Evaluation]]: 모델 평가

#### Available Models
[[Model Categories]]:
- [[Claude (Anthropic)]]: 최신 Claude 모델
- [[Titan (AWS)]]: AWS Titan 모델
- [[Llama (Meta)]]: Meta Llama 모델
- [[Mistral]]: Mistral 모델
- [[Cohere]]: Cohere 모델
- [[Stable Diffusion]]: 이미지 생성
- [[Multimodal]]: 다중모달

### [[Amazon Bedrock Explained]]
**Video 25 - Duration: ~17 minutes**

#### Bedrock Capabilities
[[Key Features]]:
- [[Text Generation]]: 텍스트 생성
- [[Image Generation]]: 이미지 생성
- [[Embeddings]]: 임베딩 생성
- [[Fine-tuning]]: 모델 커스터마이징
- [[RAG]]: 컨텍스트 기반 생성
- [[Agents]]: 자율 에이전트
- [[Model Evaluation]]: 모델 평가

#### Use Cases
[[Applications]]:
- [[Content Creation]]: 콘텐츠 생성
- [[Customer Service]]: 고객 서비스
- [[Code Generation]]: 코드 생성
- [[Data Analysis]]: 데이터 분석
- [[Document Summarization]]: 문서 요약
- [[Translation]]: 번역
- [[Question Answering]]: 질의응답

---

## Model Playground & Prompting

### [[Getting Started with Bedrock]]
**Video 26 Part 2 - Duration: ~14 minutes**

#### Playground Overview
[[Interactive Testing]]:
- [[Model Testing]]: 모델 테스트
- [[Prompt Experimentation]]: 프롬프트 실험
- [[Parameter Adjustment]]: 매개변수 조정
- [[Real-time Interaction]]: 실시간 상호작용
- [[Response Analysis]]: 응답 분석
- [[Comparison]]: 모델 비교

#### Prompt Engineering
[[Best Practices]]:
- [[Clear Instructions]]: 명확한 지시
- [[Context Provision]]: 컨텍스트 제공
- [[Example Showing]]: 예시 제시
- [[Output Format]]: 출력 형식 지정
- [[Role Definition]]: 역할 정의
- [[Temperature Control]]: 창의성 조절

#### Model Parameters
[[Configuration]]:
- [[Temperature]]: 다양성 (0-1)
- [[Top P]]: 누적 확률
- [[Top K]]: 상위 K 선택
- [[Max Tokens]]: 최대 토큰
- [[Stop Sequences]]: 중지 시퀀스

---

## Advanced Bedrock Features

### [[Bedrock RAG - Retrieval Augmented Generation]]
**Video 23 - Duration: ~18 minutes**

#### RAG Overview
[[Concept]]:
- [[Retrieval]]: 관련 문서 검색
- [[Augmentation]]: 컨텍스트 추가
- [[Generation]]: 응답 생성
- [[Accuracy]]: 정확도 향상
- [[Relevance]]: 관련성 증가
- [[Citation]]: 출처 제시
- [[Custom Knowledge]]: 맞춤 지식

#### RAG Components
[[Architecture]]:

**Retrieval Component**:
- [[Document Store]]: 문서 저장소
- [[Embeddings]]: 벡터 임베딩
- [[Vector DB]]: 벡터 데이터베이스
- [[Search Index]]: 검색 인덱스

**Generation Component**:
- [[LLM]]: 언어 모델
- [[Prompt Template]]: 프롬프트 템플릿
- [[Context Integration]]: 컨텍스트 통합
- [[Response Generation]]: 응답 생성

#### RAG Implementation
[[Setup Steps]]:
1. [[Prepare Documents]]: 문서 준비
2. [[Create Embeddings]]: 임베딩 생성
3. [[Store in Vector DB]]: 벡터 DB 저장
4. [[Create Retriever]]: 검색 도구 생성
5. [[Build Prompt Template]]: 템플릿 작성
6. [[Test RAG Pipeline]]: 파이프라인 테스트
7. [[Optimize Performance]]: 성능 최적화

### [[Bedrock Fine-Tuning]]
**Video 24 - Duration: ~19 minutes**

#### Fine-tuning Overview
[[Customization]]:
- [[Domain Adaptation]]: 도메인 적응
- [[Style Matching]]: 스타일 일치
- [[Task Specialization]]: 작업 특화
- [[Performance Improvement]]: 성능 개선
- [[Cost Efficiency]]: 비용 효율성
- [[Faster Inference]]: 빠른 추론

#### Fine-tuning Process
[[Steps]]:
1. [[Prepare Training Data]]: 훈련 데이터 준비
2. [[Format Data]]: 데이터 포맷
3. [[Upload Data]]: 데이터 업로드
4. [[Configure Training]]: 훈련 구성
5. [[Start Training]]: 훈련 시작
6. [[Monitor Progress]]: 진행 모니터링
7. [[Evaluate Model]]: 모델 평가
8. [[Deploy Fine-tuned Model]]: 배포

#### Training Data Requirements
[[Data Format]]:
- [[Text Pairs]]: 입력-출력 쌍
- [[Instruction-Following]]: 지시 따르기
- [[Conversation Format]]: 대화 형식
- [[JSON Format]]: JSON 구조
- [[Minimum Size]]: 최소 크기
- [[Quality Requirements]]: 품질 요구사항

### [[Bedrock Agents]]
**Video 16 - Duration: ~17 minutes**

#### Agents Overview
[[Autonomous Systems]]:
- [[Self-Directed]]: 자율적 행동
- [[Tool Usage]]: 도구 사용
- [[Planning]]: 계획 수립
- [[Reasoning]]: 추론
- [[Iteration]]: 반복 실행
- [[Error Recovery]]: 오류 복구

#### Agent Components
[[Building Blocks]]:
- [[LLM Backbone]]: LLM 기반
- [[Tools/APIs]]: 사용 가능한 도구
- [[Memory]]: 메모리 관리
- [[Reasoning Engine]]: 추론 엔진
- [[Orchestration]]: 조정

#### Agent Creation
[[Implementation]]:
1. [[Define Objective]]: 목표 정의
2. [[Prepare Tools]]: 도구 준비
3. [[Configure Agent]]: 에이전트 설정
4. [[Set Parameters]]: 매개변수 설정
5. [[Test Agent]]: 에이전트 테스트
6. [[Iterate]]: 반복 개선
7. [[Deploy]]: 배포

#### Common Tools
[[Available Tools]]:
- [[AWS APIs]]: AWS 서비스
- [[HTTP Endpoints]]: REST API
- [[Databases]]: 데이터베이스
- [[Search Engines]]: 검색 엔진
- [[Custom Functions]]: 사용자 정의 함수

### [[Bedrock Guardrails]]
**Video 14 - Duration: ~16 minutes**

#### Guardrails Overview
[[Safety Controls]]:
- [[Content Filtering]]: 콘텐츠 필터링
- [[Pii Redaction]]: PII 제거
- [[Harmful Content]]: 유해 콘텐츠 차단
- [[Jailbreak Prevention]]: 탈출 방지
- [[Custom Rules]]: 사용자 정의 규칙
- [[Sensitive Redaction]]: 민감 정보 제거

#### Guardrail Types
[[Safety Categories]]:
- [[Hate and Violence]]: 혐오와 폭력
- [[Sexual Content]]: 성인 콘텐츠
- [[Violence]]: 폭력
- [[Self-Harm]]: 자해
- [[Illegal Activities]]: 불법 활동
- [[Custom Categories]]: 사용자 정의

### [[Bedrock Prompt Management]]
**Video 18 - Duration: ~14 minutes**

#### Prompt Management Overview
[[Lifecycle Management]]:
- [[Versioning]]: 버전 관리
- [[Collaboration]]: 협업
- [[Organization]]: 조직화
- [[Sharing]]: 공유
- [[Documentation]]: 문서화
- [[Testing]]: 테스트

#### Prompt Organization
[[Structure]]:
- [[Prompt Libraries]]: 라이브러리
- [[Versions]]: 버전 관리
- [[Metadata]]: 메타데이터
- [[Performance Metrics]]: 성능 메트릭
- [[Change History]]: 변경 이력

---

## Advanced Prompt Engineering

### [[Bedrock Prompt Flows]]
**Video 17 - Duration: ~15 minutes**

#### Prompt Flows Overview
[[Workflow Automation]]:
- [[Sequential Steps]]: 순차적 단계
- [[Conditional Logic]]: 조건부 로직
- [[Parallel Execution]]: 병렬 실행
- [[Error Handling]]: 오류 처리
- [[Integration]]: 외부 통합

#### Flow Components
[[Building Blocks]]:
- [[LLM Calls]]: 모델 호출
- [[Logic Nodes]]: 로직 노드
- [[Data Transform]]: 데이터 변환
- [[Conditional Branching]]: 조건부 분기
- [[Loops]]: 반복

#### Creating Flows
[[Development]]:
1. [[Define Workflow]]: 워크플로우 정의
2. [[Create Steps]]: 단계 생성
3. [[Configure Conditions]]: 조건 설정
4. [[Test Flow]]: 흐름 테스트
5. [[Optimize]]: 최적화
6. [[Deploy]]: 배포

---

## Model Evaluation & Quality

### [[Bedrock Model Evaluation]]

#### Evaluation Overview
[[Quality Assessment]]:
- [[Performance Metrics]]: 성능 메트릭
- [[Human Evaluation]]: 인간 평가
- [[Automated Evaluation]]: 자동 평가
- [[Comparison]]: 모델 비교
- [[Benchmarking]]: 벤치마킹

#### Evaluation Types

**Automatic Evaluation**:
- [[Programmatic Evaluation]] - 자동 프로그래매틱 평가
- [[LLM as Judge]] - LLM 판정자
- [[BLEU/ROUGE]] - 텍스트 유사도
- [[Semantic Similarity]] - 의미 유사도

**Human Evaluation**:
- [[Manual Review]] - 수동 검토
- [[Expert Assessment]] - 전문가 평가
- [[User Testing]] - 사용자 테스트
- [[A/B Testing]] - A/B 테스트

### [[Bedrock Human Evaluation]]
**Videos 20-22 - Duration: ~45 minutes**

#### Human Evaluation Process
[[Setup]]:
1. [[Define Criteria]]: 평가 기준 정의
2. [[Create Dataset]]: 테스트 셋 생성
3. [[Configure Tasks]]: 평가 작업 설정
4. [[Recruit Evaluators]]: 평가자 모집
5. [[Manage Evaluations]]: 평가 관리
6. [[Analyze Results]]: 결과 분석

#### Evaluation Criteria
[[Metrics]]:
- [[Accuracy]]: 정확도
- [[Relevance]]: 관련성
- [[Clarity]]: 명확성
- [[Completeness]]: 완전성
- [[Safety]]: 안전성
- [[Tone]]: 톤
- [[Structure]]: 구조

---

## Summary: Bedrock Complete

### [[Key Takeaways]]

✅ **Foundation Models**:
- 다양한 기반 모델
- API 기반 접근
- 프롬프트 엔지니어링
- 매개변수 조정

✅ **RAG System**:
- 검색 기반 생성
- 컨텍스트 주입
- 정확도 향상
- 출처 제시

✅ **Fine-tuning**:
- 맞춤형 모델
- 도메인 특화
- 성능 개선
- 비용 효율성

✅ **Agents**:
- 자율적 행동
- 도구 사용
- 계획 수립
- 반복 실행

✅ **Safety & Quality**:
- 가드레일
- 콘텐츠 필터
- 모델 평가
- 인간 검증

---

**Playlist Source**: All AWS Videos
**Channel**: ImTechnos
**Total Bedrock Videos**: 8 videos
**Coverage**: 모든 생성형 AI 기능, LLM, RAG, Fine-tuning, Agents, 평가

---

## 🔗 Related Graphs (관련 그래프)

**AI & ML**:
- [[AWS_SageMaker_Complete_Graph]] - 기계학습 플랫폼
- [[Agentic_AI_Graph]] - AI 에이전트 아키텍처
- [[AEO_Graph]] - AI 엔진 최적화

**데이터 기반**:
- [[AI_Data_Labeling_Economy_Graph]] - 훈련 데이터

← 돌아가기: [[AI_Agents_Multi_Industry_Enterprise_Hub]]
