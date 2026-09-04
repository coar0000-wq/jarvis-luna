# Data Labeling Research Papers - Graph View

← [[AI_Agents_Multi_Industry_Enterprise_Hub]]

## Core Concept
**데이터 라벨링 최상위 연구논문 완벽 가이드**
- Focus: Data Labeling, Weak Supervision, Active Learning, Annotation Quality
- Time Period: 2017-2025 (최신 연구 포함)
- Goal: 데이터 라벨링의 모든 측면을 학술적으로 이해

---

## Tier 1: 기초 논문 (Foundational Research)

### [[Snorkel Framework Papers]]

#### Paper 1: Snorkel - Rapid Training Data Creation with Weak Supervision

[[Snorkel Original Paper]]:
- **Title**: Snorkel: Rapid Training Data Creation with Weak Supervision
- **Authors**: Alexander Ratner, Stephen H. Bach, Henry R. Ehrenberg, et al.
- **Year**: 2017
- **Citation**: arXiv:1711.10160
- **Venue**: Proceedings of the VLDB Endowment (VLDB 2018)
- **Key Innovation**: [[Data Programming]]

**Main Contributions**:
- [[Labeling Functions]]: 휴리스틱 기반 라벨링 함수
- [[Label Denoising]]: 약한 감독 신호의 자동 노이즈 제거
- [[End-to-end System]]: 완전한 데이터 프로그래밍 구현
- [[User Study Results]]: 2.8배 빠른 개발, 45.5% 성능 향상

**Core Concepts**:
- [[Weak Supervision]]: 약한 감독 학습
- [[Data Programming Paradigm]]: 데이터 프로그래밍 패러다임
- [[Generative Model]]: 생성 모델을 통한 라벨 집계
- [[No Hand Labeling]]: 수동 라벨링 없음

#### Paper 2: Snorkel DryBell - Industrial Scale Deployment

[[Snorkel DryBell]]:
- **Title**: Snorkel DryBell: A Case Study in Deploying Weak Supervision at Industrial Scale
- **Authors**: Alexander Ratner, Braden Hancock, Jared Dunnmon, et al.
- **Year**: 2018
- **Citation**: arXiv:1812.00417
- **Contribution**: [[Industrial Application]]

**Key Features**:
- [[Knowledge Resource Integration]]: 조직 전체의 지식 리소스 활용
- [[Production Serving]]: 크로스 피처 프로덕션 서빙
- [[Scalable Execution]]: 확장 가능한 실행
- [[Template-based Ingestion]]: 템플릿 기반 수집

**Impact**:
- [[Development Time Reduction]]: 개발 시간을 1/10으로 단축
- [[Cost Reduction]]: 비용 획기적 감소
- [[Real-world Results]]: 실제 산업 환경에서의 성과

---

## Tier 2: 활발한 학습 및 반자동화 (Active Learning)

### [[Semi-Supervised Active Learning Papers]]

#### Paper 3: Consistency-Based Semi-Supervised Active Learning

[[CSAL Framework]]:
- **Title**: Consistency-Based Semi-Supervised Active Learning: Towards Minimizing Labeling Cost
- **Year**: 2019/2020
- **Citation**: arXiv:1910.07153
- **Focus**: [[Cost Minimization]]

**Key Methodology**:
- [[Consistency Regularization]]: 일관성 정규화
- [[Active Query Strategy]]: 활발한 선택 전략
- [[Labeled & Unlabeled Data]]: 레이블된 데이터와 미레이블 데이터 활용
- [[Minimizing Labeling Cost]]: 라벨링 비용 최소화

**Contributions**:
- [[Sample Selection Metric]]: 표본 선택 메트릭
- [[Semi-supervised Distillation]]: 반감시 증류
- [[Efficiency Gains]]: 라벨링 비용 대폭 감소

#### Paper 4: Exploiting Diversity of Unlabeled Data for Label-Efficient Semi-Supervised Active Learning

[[Diversity-based Active Learning]]:
- **Title**: Exploiting Diversity of Unlabeled Data for Label-Efficient Semi-Supervised Active Learning
- **Year**: 2022
- **Citation**: arXiv:2207.12302
- **Focus**: [[Diversity Sampling]]

**Core Approach**:
- [[Consistency-based Embeddings]]: 일관성 기반 임베딩
- [[Diversity Sampling]]: 다양성 샘플링
- [[Sample Informativeness]]: 정보가 많은 표본 선택
- [[Label Efficiency]]: 라벨 효율성

#### Paper 5: Semi-Supervised Variational Adversarial Active Learning

[[SVAAL Framework]]:
- **Title**: Semi-Supervised Variational Adversarial Active Learning via Learning to Rank and Agreement-Based Pseudo Labeling
- **Year**: 2024
- **Citation**: arXiv:2408.12774
- **Focus**: [[Adversarial Approach]]

**Advanced Techniques**:
- [[Learning to Rank]]: 순위학습
- [[Pseudo Labeling]]: 의사 라벨
- [[Adversarial Network]]: 적대적 네트워크
- [[Acquisition Function]]: 획득 함수

---

## Tier 3: 약한 감독 및 라벨 노이즈 (Weak Supervision & Label Noise)

### [[Label Noise Management]]

#### Paper 6: Unsupervised Selective Labeling for More Effective Semi-Supervised Learning

[[Selective Labeling]]:
- **Title**: Unsupervised Selective Labeling for More Effective Semi-Supervised Learning
- **Year**: 2021
- **Citation**: arXiv:2110.03006
- **Focus**: [[Selective Annotation]]

**Key Insight**:
- [[Right Data Selection]]: 정확한 데이터 선택
- [[Fixed Labeling Budget]]: 고정된 라벨링 예산
- [[Semi-supervised Effectiveness]]: 반감시 학습 효과 극대화
- [[Label Selection Strategy]]: 라벨 선택 전략

#### Paper 7: Self-Supervised Semi-Supervised Learning for Data Labeling and Quality Evaluation

[[Self-Supervised Framework]]:
- **Title**: Self-Supervised Semi-Supervised Learning for Data Labeling and Quality Evaluation
- **Year**: 2021
- **Citation**: arXiv:2111.10932
- **Focus**: [[Quality Verification]]

**Contributions**:
- [[Unifying Framework]]: 통합 프레임워크
- [[Data Labeling]]: 데이터 라벨링
- [[Annotation Verification]]: 주석 검증
- [[Quality Assurance]]: 품질 보증

---

## Tier 4: 전이 학습 및 소수-샷 학습 (Transfer & Few-Shot)

### [[Transfer Learning for Data Reduction]]

#### Paper 8: Meta-Transfer Learning for Few-Shot Learning

[[MTL Framework]]:
- **Title**: Meta-Transfer Learning for Few-Shot Learning
- **Authors**: Qianru Sun, Yaoyao Liu, Tat-Seng Chua, Bernt Schilkorn
- **Year**: 2019
- **Citation**: arXiv:1812.02391
- **Focus**: [[Meta-learning]]

**Key Approach**:
- [[Learning to Adapt]]: 적응 학습
- [[DNN Weight Functions]]: DNN 가중치 함수
- [[Scaling & Shifting]]: 스케일 및 시프트
- [[Few-Shot Performance]]: 소수-샷 성능 향상

#### Paper 9: A Study on Representation Transfer for Few-Shot Learning

[[Transfer Representation Study]]:
- **Title**: A Study on Representation Transfer for Few-Shot Learning
- **Year**: 2022
- **Citation**: arXiv:2209.02073
- **Focus**: [[Feature Representation]]

**Research Coverage**:
- [[MAML Learning]]: MAML 학습
- [[Supervised Classification]]: 지도학습 분류
- [[Self-supervised Tasks]]: 자가감시 작업
- [[Representation Comparison]]: 표현 비교

**Findings**:
- [[Feature Quality]]: 특성 품질
- [[Transfer Effectiveness]]: 전이 효과
- [[Data Annotation Reduction]]: 주석 감소

---

## Tier 5: 최신 및 응용 연구 (Recent & Applied Research)

### [[Modern Data Labeling Approaches]]

#### Paper 10: Data Collection and Labeling Techniques for Machine Learning

[[Comprehensive Survey]]:
- **Title**: Data Collection and Labeling Techniques for Machine Learning
- **Year**: 2024
- **Citation**: arXiv:2407.12793
- **Focus**: [[State-of-the-art]]

**Coverage**:
- [[Data Collection]]: 데이터 수집
- [[Labeling Methods]]: 라벨링 방법
- [[Quality Improvement]]: 품질 개선
- [[State-of-the-art Survey]]: 최신 기술 조사

#### Paper 11: ML-Driven Data Labeling Pipeline for Scientific Data

[[Scientific Application]]:
- **Title**: A Machine-Learning-Driven Data Labeling Pipeline for Scientific Analysis in MLExchange
- **Year**: 2025
- **Citation**: IUCr Journals
- **Focus**: [[Scientific Domain]]

**Innovation**:
- [[AI-guided Tagging]]: AI 기반 태그
- [[Web-based GUIs]]: 웹 기반 인터페이스
- [[Data Clinic]]: 데이터 클리닉
- [[MLCoach]]: ML 코치
- [[Label Maker]]: 라벨 메이커

#### Paper 12: Crowdsourcing Data Labeling - Quality Control

[[Crowdsourcing Quality]]:
- **Title**: Research on Data Quality Control of Crowdsourcing Annotation: A Survey
- **Year**: 2020
- **Citation**: IEEE Conference Publication
- **Focus**: [[Crowd Quality]]

**Key Methods**:
- [[Gold Labels]]: 금 표준 라벨
- [[Reputation Systems]]: 평판 시스템
- [[Attention Checks]]: 주의 확인
- [[Label Aggregation]]: 라벨 집계
- [[EM-based Methods]]: EM 기반 방법
- [[Weighted Voting]]: 가중 투표

---

## 주요 연구 트렌드

### [[Research Trends 2024-2025]]

**자동화 및 AI 지원**:
- [[Model-in-the-Loop]]: 모델 기반 반복
- [[Confidence Routing]]: 신뢰도 기반 라우팅
- [[Active Learning]]: 능동학습
- [[Auto-label & Review]]: 자동 라벨링 및 검토

**데이터 다양성**:
- [[Multi-modal Data]]: 다중 모달 데이터
- [[3D & LiDAR]]: 3D 및 라이다
- [[Video Data]]: 비디오 데이터
- [[Code & Chat]]: 코드 및 채팅 데이터

**규모 확장**:
- [[10M+ Scale]]: 천만 건 이상 규모
- [[Scalable Systems]]: 확장 가능한 시스템
- [[Production Deployment]]: 프로덕션 배포
- [[Cost Optimization]]: 비용 최적화

---

## 논문 간 연결성

### [[Paper Relationships]]

**Weak Supervision 계열**:
- [[Snorkel (2017)]] → [[Snorkel DryBell (2018)]] → [[Modern ML Pipelines (2024-2025)]]

**Active Learning 계열**:
- [[CSAL (2019)]] → [[Diversity-based AL (2022)]] → [[SVAAL (2024)]]

**Label Noise 처리**:
- [[Selective Labeling (2021)]] → [[Self-Supervised SSL (2021)]] → [[Quality Control Survey (2020)]]

**Transfer Learning 계열**:
- [[Meta-Transfer (2019)]] → [[Transfer Study (2022)]] → [[Few-shot Approaches]]

---

## 요점 정리

### [[Key Research Insights]]

✅ **Weak Supervision 혁신**:
- Snorkel: 데이터 프로그래밍 패러다임
- 2.8배 빠른 개발 시간
- 45.5% 성능 향상

✅ **Active Learning 효율성**:
- 라벨링 비용 최소화
- 반감시 학습과의 결합
- 의사 라벨링 기법

✅ **Transfer Learning 성과**:
- 소수-샷 학습 개선
- 전이 표현 효과
- 주석 요구사항 감소

✅ **산업 응용**:
- 크라우드소싱 품질 관리
- 멀티 모달 데이터 지원
- 자동화 및 AI 지원

✅ **미래 방향**:
- 10M+ 규모 시스템
- 모델-기반 반복
- 비용 효율성

---

**Focus**: Data Labeling Research Papers
**Time Span**: 2017-2025 (최신 연구)
**Paper Count**: 12개 주요 논문
**Research Areas**: Weak Supervision, Active Learning, Quality Control, Transfer Learning
**Application**: AI/ML Development, Production Systems, Scientific Research

---

## 🔗 Related Graphs

**연구 시리즈**:
- [[Data_Labeling_Advanced_Research_Graph]] - 고급 연구논문 (26개 추가)

**실무 적용**:
- [[Data_Annotation_Types_Graph]] - 주석 유형
- [[Data_Annotation_Techniques_Graph]] - 기술 & 방법론
- [[Data_Annotation_Tools_Graph]] - 도구 & 플랫폼
- [[Data_Annotation_Beginners_Guide_Graph]] - 초보자 가이드
- [[AI_Data_Labeling_Economy_Graph]] - 경제 & 일자리

**응용 분야**:
- [[Agentic_AI_Graph]] - AI 에이전트
- [[AWS_SageMaker_Complete_Graph]] - ML 플랫폼

← 돌아가기: [[AI_Agents_Multi_Industry_Enterprise_Hub]]
