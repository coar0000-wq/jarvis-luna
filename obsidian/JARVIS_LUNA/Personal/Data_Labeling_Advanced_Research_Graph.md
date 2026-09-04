# Data Labeling Advanced Research - Extended Papers - Graph View

← [[AI_Agents_Multi_Industry_Enterprise_Hub]]

## Core Concept
**데이터 라벨링 고급 연구논문: 확장판**
- Focus: Pseudo-labeling, Curriculum Learning, Contrastive Learning, LLM-based Labeling, Noise Management
- Time Period: 2019-2026 (최신 연구)
- Goal: 데이터 라벨링의 고급 기법과 응용 분야 완벽히 이해

---

## Tier 1: 의사 라벨링 및 자체 훈련 (Pseudo-labeling & Self-training)

### [[Pseudo-labeling Framework Papers]]

#### Paper 13: Curriculum Labeling - Revisiting Pseudo-Labeling

[[Curriculum Labeling]]:
- **Title**: Curriculum Labeling: Revisiting Pseudo-Labeling for Semi-Supervised Learning
- **Year**: 2020
- **Citation**: arXiv:2001.06001
- **Focus**: [[Iterative Learning]]

**Key Approach**:
- [[Pseudo Labels]]: 의사 라벨
- [[Iterative Cycles]]: 반복적 사이클
- [[Self-training]]: 자체 훈련
- [[Confidence Threshold]]: 신뢰도 임계값

#### Paper 14: Label Propagation for Deep Semi-supervised Learning

[[Label Propagation Deep]]:
- **Title**: Label Propagation for Deep Semi-supervised Learning
- **Year**: 2019
- **Citation**: arXiv:1904.04717
- **Focus**: [[Graph-based Method]]

**Methodology**:
- [[Nearest Neighbor Graph]]: 최근접 이웃 그래프
- [[Network Embeddings]]: 네트워크 임베딩
- [[Transductive Learning]]: 전이학습
- [[Iterative Refinement]]: 반복적 개선

#### Paper 15: Two-phase Pseudo Label Densification

[[Pseudo Label Densification]]:
- **Title**: Two-phase Pseudo Label Densification for Self-training Based Domain Adaptation
- **Year**: 2020
- **Citation**: arXiv:2012.04828
- **Focus**: [[Spatial Correlation]]

**Contributions**:
- [[Sliding Window Voting]]: 슬라이딩 윈도우 투표
- [[Confident Predictions]]: 신뢰도 높은 예측
- [[Spatial Correlations]]: 공간 상관성
- [[Domain Adaptation]]: 도메인 적응

#### Paper 16: Revisiting Self-Training with Regularized Pseudo-Labeling

[[Regularized Self-training]]:
- **Title**: Revisiting Self-Training with Regularized Pseudo-Labeling for Tabular Data
- **Year**: 2023
- **Citation**: arXiv:2302.14013
- **Focus**: [[Tabular Domain]]

**Innovation**:
- [[Gradient Boosting]]: 그래디언트 부스팅
- [[Curriculum Pseudo-labeling]]: 커리큘럼 의사 라벨
- [[Algorithm Agnostic]]: 알고리즘 무관
- [[Tabular Data]]: 표 형식 데이터

#### Paper 17: Pseudo-Labeling and Confirmation Bias

[[Confirmation Bias]]:
- **Title**: Pseudo-Labeling and Confirmation Bias in Deep Semi-Supervised Learning
- **Year**: 2019
- **Citation**: arXiv:1908.02983
- **Focus**: [[Bias Analysis]]

**Research Direction**:
- [[Graph-based Refinement]]: 그래프 기반 개선
- [[Hard Pseudo-labels]]: 하드 의사 라벨
- [[Training Dynamics]]: 훈련 역학
- [[Confirmation Bias]]: 확인 편향

#### Paper 18: AggMatch - Aggregating Pseudo Labels

[[Pseudo Label Aggregation]]:
- **Title**: AggMatch: Aggregating Pseudo Labels for Semi-Supervised Learning
- **Year**: 2022
- **Citation**: arXiv:2201.10444
- **Focus**: [[Label Aggregation]]

**Method Combines**:
- [[Pseudo-labeling]]: 의사 라벨링
- [[Consistency Regularization]]: 일관성 정규화
- [[Label Propagation]]: 라벨 전파
- [[Multiple SSL Methods]]: 다중 SSL 방법

---

## Tier 2: 커리큘럼 학습 (Curriculum Learning)

### [[Curriculum Learning for Annotation]]

#### Paper 19: Curriculum Demonstration Selection

[[Curriculum Demonstration]]:
- **Title**: Curriculum Demonstration Selection for In-Context Learning
- **Year**: 2024
- **Citation**: arXiv:2411.18126
- **Focus**: [[Example Selection]]

**Core Strategy**:
- [[Complexity Measurement]]: 복잡도 측정
- [[Easy to Difficult]]: 쉬운 것부터 어려운 것
- [[Curriculum Principles]]: 커리큘럼 원리
- [[In-context Learning]]: 맥락 내 학습

#### Paper 20: Curriculum Learning with Quality-Driven Data Selection

[[Quality-Driven Curriculum]]:
- **Title**: Curriculum Learning with Quality-Driven Data Selection
- **Year**: 2024
- **Citation**: arXiv:2407.00102
- **Focus**: [[Quality Metrics]]

**Data Selection**:
- [[Image-text Correlation]]: 이미지-텍스트 상관성
- [[Model Perplexity]]: 모델 난해도
- [[Progressive Quality]]: 점진적 품질
- [[Training Stages]]: 훈련 단계

#### Paper 21: Curriculum Learning for Medical Image Annotation

[[Medical Curriculum]]:
- **Title**: Curriculum Learning for Annotation-Efficient Medical Image Analysis
- **Year**: 2020
- **Citation**: arXiv:2007.16102
- **Focus**: [[Medical Domain]]

**Framework**:
- [[Scheduling Strategies]]: 스케줄링 전략
- [[Sample Weighting]]: 샘플 가중치
- [[Training Set Reordering]]: 훈련 세트 재정렬
- [[Difficulty Ranking]]: 어려움 순위

#### Paper 22: Disentangling Curriculum Learning in NLP

[[Curriculum Learning Survey]]:
- **Title**: Disentangling Curriculum Learning in NLP: Towards a Unifying Taxonomy
- **Year**: 2024
- **Citation**: arXiv:2607.18984
- **Focus**: [[Taxonomy]]

**Contribution**:
- [[Comprehensive Classification]]: 포괄적 분류
- [[NLP Specific]]: NLP 특화
- [[Unifying Framework]]: 통합 프레임워크
- [[Recent Survey]]: 최신 조사

---

## Tier 3: 대조 학습 (Contrastive Learning)

### [[Self-Supervised Contrastive Methods]]

#### Paper 23: Weakly-Supervised Contrastive Learning

[[Imprecise Labels]]:
- **Title**: Weakly-Supervised Contrastive Learning for Imprecise Class Labels
- **Year**: 2025
- **Citation**: arXiv:2505.22028
- **Focus**: [[Continuous Similarity]]

**Innovation**:
- [[Continuous Similarity]]: 연속 유사성
- [[Imprecise Labels]]: 불정확한 라벨
- [[Positive/Negative Pairs]]: 양/음 쌍
- [[Real-world Scenarios]]: 실제 시나리오

#### Paper 24: A Survey on Contrastive Self-Supervised Learning

[[SSL Survey]]:
- **Title**: A Survey on Contrastive Self-Supervised Learning
- **Year**: 2021
- **Citation**: arXiv:2011.00362
- **Focus**: [[Comprehensive Review]]

**Coverage**:
- [[Vision Domain]]: 시각 영역
- [[NLP Domain]]: 자연어 처리
- [[Methodology]]: 방법론
- [[State-of-the-art]]: 최신 기술

#### Paper 25: Self-Supervised Contrastive Learning for Multi-Label Images

[[Multi-label Contrastive]]:
- **Title**: Self-Supervised Contrastive Learning for Multi-Label Images
- **Year**: 2025
- **Citation**: arXiv:2506.23156
- **Focus**: [[Multi-label]]:

**Approach**:
- [[Multi-label Setting]]: 다중 라벨
- [[Contrastive Learning]]: 대조 학습
- [[Label Ambiguity]]: 라벨 모호성
- [[Positive Pairs]]: 양 쌍

#### Paper 26: Self-Supervised Learning at the Edge

[[Cost of Labeling]]:
- **Title**: Self-Supervised Learning at the Edge: The Cost of Labeling
- **Year**: 2025
- **Citation**: arXiv:2507.07033
- **Focus**: [[Edge Computing]]

**Perspective**:
- [[Labeling Cost]]: 라벨링 비용
- [[Annotation Reduction]]: 주석 감소
- [[Edge Deployment]]: 엣지 배포
- [[Resource Efficiency]]: 리소스 효율

---

## Tier 4: LLM 기반 자동 라벨링 (LLM-based Automatic Labeling)

### [[Large Language Model Annotation]]

#### Paper 27: Large Language Models for Data Annotation Survey

[[LLM Annotation Survey]]:
- **Title**: Large Language Models for Data Annotation and Synthesis: A Survey
- **Year**: 2024
- **Citation**: arXiv:2402.13446
- **Focus**: [[Comprehensive Survey]]

**Key Areas**:
- [[Automated Annotation]]: 자동 주석
- [[LLM Efficiency]]: LLM 효율성
- [[Consistency Improvement]]: 일관성 개선
- [[Labor Reduction]]: 인력 감소

#### Paper 28: Enhancing LLM-Based Data Annotation

[[Error Decomposition]]:
- **Title**: Enhancing LLM-Based Data Annotation with Error Decomposition
- **Year**: 2026
- **Citation**: arXiv:2601.11920
- **Focus**: [[Error Analysis]]

**Method**:
- [[Error Types]]: 오류 유형
- [[Decomposition]]: 분해
- [[Improvement]]: 개선
- [[Robustness]]: 견고성

#### Paper 29: From LLM-anation to LLM-Orchestrator

[[Multi-model Coordination]]:
- **Title**: From LLM-anation to LLM-Orchestrator: Coordinating Small Models for Data Labeling
- **Year**: 2025
- **Citation**: arXiv:2506.16393
- **Focus**: [[Coordination Strategy]]

**Innovation**:
- [[Small Model Coordination]]: 소형 모델 조율
- [[Label Quality]]: 라벨 품질
- [[Model Specialization]]: 모델 특화
- [[Efficiency]]: 효율성

#### Paper 30: Automatic Labelling with Open-source LLMs

[[Dynamic Label Schema]]:
- **Title**: Automatic Labelling with Open-source LLMs using Dynamic Label Schema Integration
- **Year**: 2025
- **Citation**: arXiv:2501.12332
- **Focus**: [[Schema Integration]]

**Approach**:
- [[Open-source Models]]: 오픈소스 모델
- [[Dynamic Schema]]: 동적 스키마
- [[Flexibility]]: 유연성
- [[Cost Reduction]]: 비용 절감

---

## Tier 5: 도메인별 특화 (Domain-Specific)

### [[Autonomous Driving & Medical Annotation]]

#### Paper 31: A Survey on Autonomous Driving Datasets

[[AD Annotation Quality]]:
- **Title**: A Survey on Autonomous Driving Datasets: Statistics, Annotation Quality, and a Future Outlook
- **Year**: 2024
- **Citation**: arXiv:2401.01454
- **Focus**: [[Dataset Quality]]

**Coverage**:
- [[265 Datasets]]: 265개 데이터셋
- [[Annotation Processes]]: 주석 프로세스
- [[Labeling Tools]]: 라벨링 도구
- [[Annotation Standards]]: 주석 표준

#### Paper 32: Attribute Annotation and Bias Evaluation

[[Bias in AD]]:
- **Title**: Attribute Annotation and Bias Evaluation in Visual Datasets for Autonomous Driving
- **Year**: 2023
- **Citation**: arXiv:2312.06306
- **Focus**: [[Bias Detection]]

**Research Direction**:
- [[Attribute Annotation]]: 속성 주석
- [[Bias Evaluation]]: 편향 평가
- [[Fairness]]: 공정성
- [[Dataset Quality]]: 데이터셋 품질

---

## Tier 6: 노이즈 라벨 처리 (Noisy Label Management)

### [[Noise Detection & Cleaning]]

#### Paper 33: Detect and Correct

[[Selective Correction]]:
- **Title**: Detect and Correct: A Selective Noise Correction Method for Learning with Noisy Labels
- **Year**: 2025
- **Citation**: arXiv:2505.13342
- **Focus**: [[Noise Correction]]

**Method**:
- [[Sample Selection]]: 샘플 선택
- [[Noise Separation]]: 노이즈 분리
- [[Noise Transition Matrix]]: 노이즈 전이 행렬
- [[Loss Correction]]: 손실 보정

#### Paper 34: Learning to Detect Noisy Labels

[[Feature-based Detection]]:
- **Title**: Learning to Detect Noisy Labels Using Model-Based Features
- **Year**: 2022
- **Citation**: arXiv:2212.13767
- **Focus**: [[Detection Method]]

**Approach**:
- [[Model-based Features]]: 모델 기반 특성
- [[Self-training]]: 자체 훈련
- [[Text Classification]]: 텍스트 분류
- [[Speech Recognition]]: 음성 인식

#### Paper 35: An Adaptive Data Cleaning Framework

[[Adaptive Cleaning]]:
- **Title**: An Adaptive Data Cleaning Framework for Noisy Label Detection
- **Year**: 2026
- **Citation**: arXiv:2606.07086
- **Focus**: [[Adaptive Method]]

**Framework**:
- [[Local Cues]]: 국소 신호
- [[Global Cues]]: 전역 신호
- [[Learning Dynamics]]: 학습 역학
- [[Dynamic Thresholds]]: 동적 임계값

#### Paper 36: Active Label Cleaning

[[Resource Constraints]]:
- **Title**: Active Label Cleaning for Improved Dataset Quality under Resource Constraints
- **Year**: 2021
- **Citation**: arXiv:2109.00574
- **Focus**: [[Resource Efficiency]]

**Contribution**:
- [[Label Correction]]: 라벨 보정
- [[Resource Aware]]: 리소스 인식
- [[Budget Constraints]]: 예산 제약
- [[Quality Improvement]]: 품질 개선

#### Paper 37: CLIPCleaner - Cleaning Noisy Labels

[[Vision Language]]:
- **Title**: CLIPCleaner: Cleaning Noisy Labels with CLIP
- **Year**: 2024
- **Citation**: arXiv:2408.10012
- **Focus**: [[Vision-Language]]

**Method**:
- [[CLIP Integration]]: CLIP 통합
- [[Visual Semantic]]: 시각-의미론적
- [[Label Correction]]: 라벨 보정
- [[Zero-shot]]: 영점-샷

#### Paper 38: Step-E - Differentiable Data Cleaning

[[Stepwise Elimination]]:
- **Title**: Step-E: A Differentiable Data Cleaning Framework for Robust Learning with Noisy Labels
- **Year**: 2025
- **Citation**: arXiv:2511.17040
- **Focus**: [[Elimination Schedule]]

**Innovation**:
- [[Tight Integration]]: 밀접 통합
- [[Sample Selection]]: 샘플 선택
- [[Elimination Schedule]]: 제거 스케줄
- [[No Clean Validation]]: 검증 데이터 불필요

---

## 요점 정리

### [[Advanced Research Insights]]

✅ **Pseudo-labeling 혁신**:
- 의사 라벨을 통한 반감시 학습
- 신뢰도 기반 필터링
- 라벨 전파 기법

✅ **Curriculum Learning 효과**:
- 단계별 난이도 증가
- 품질 기반 데이터 선택
- 의료/자율주행 도메인 응용

✅ **Contrastive Learning**:
- 자가 감독 학습
- 라벨 감소 가능
- 멀티 모달 지원

✅ **LLM 기반 자동화**:
- LLM으로 자동 라벨링
- 다중 모델 조율
- 비용 획기적 절감

✅ **노이즈 처리**:
- 적응형 노이즈 탐지
- 동적 임계값
- 견고한 학습

---

**Focus**: Advanced Data Labeling Research
**Time Span**: 2019-2026 (최신 연구)
**Paper Count**: 26개 추가 논문
**Research Areas**: Pseudo-labeling, Curriculum Learning, Contrastive Learning, LLM-based, Noise Management
**Total with Previous**: 38개 논문 (12 + 26)

---

## 🔗 Related Graphs

- [[Data_Labeling_Research_Papers_Graph]] - 기초 연구논문 (12개)
- [[Data_Annotation_Types_Graph]] - 주석 유형
- [[Data_Annotation_Techniques_Graph]] - 기술 & 방법론
- [[Data_Annotation_Tools_Graph]] - 도구 & 플랫폼
- [[Data_Annotation_Beginners_Guide_Graph]] - 초보자 가이드
- [[AI_Data_Labeling_Economy_Graph]] - 경제 & 일자리
- [[Agentic_AI_Complete_Course_Graph]] - AI 에이전트

← 돌아가기: [[AI_Agents_Multi_Industry_Enterprise_Hub]]
