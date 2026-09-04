# Amazon SageMaker Complete - Machine Learning Platform - Graph View

← [[AI_Agents_Multi_Industry_Enterprise_Hub]]

## Core Concept
**Amazon SageMaker 완벽 가이드**
- Playlist: All AWS Videos (69 videos)
- Channel: ImTechnos
- Goal: 데이터 준비부터 모델 배포, 모니터링까지 완전한 ML 파이프라인

---

## SageMaker Fundamentals

### [[Amazon SageMaker AI Explained]]
**Video 15 - Duration: ~18 minutes**

#### SageMaker Overview
[[Platform Capabilities]]:
- [[End-to-End ML]]: 완전한 ML 파이프라인
- [[No Infrastructure]]: 인프라 관리 불필요
- [[Scalable]]: 자동 확장
- [[Managed]]: 완전 관리형
- [[Integrated]]: AWS 통합
- [[Secure]]: 보안
- [[Cost-Effective]]: 비용 효율적

#### ML Pipeline Stages
[[Workflow Steps]]:
1. [[Data Preparation]]: 데이터 준비
2. [[Feature Engineering]]: 특성 엔지니어링
3. [[Model Training]]: 모델 훈련
4. [[Hyperparameter Tuning]]: 하이퍼파라미터 조정
5. [[Model Evaluation]]: 모델 평가
6. [[Model Deployment]]: 모델 배포
7. [[Monitoring]]: 모니터링
8. [[Retraining]]: 재훈련

#### SageMaker Components
[[Key Services]]:
- [[Notebook Instances]]: 개발 환경
- [[Training Jobs]]: 훈련 작업
- [[Hyperparameter Tuning]]: 자동 조정
- [[Batch Transform]]: 배치 처리
- [[Endpoints]]: 실시간 예측
- [[Pipelines]]: ML 파이프라인
- [[Model Registry]]: 모델 저장소

### [[Amazon SageMaker JumpStart]]
**Video 7 - Duration: ~14 minutes**

#### JumpStart Overview
[[Quick Start]]:
- [[Pre-trained Models]]: 사전 훈련 모델
- [[One-Click Deployment]]: 원클릭 배포
- [[No Coding]]: 코딩 불필요
- [[Quick Results]]: 빠른 결과
- [[Fine-tuning]]: 파인튜닝 가능
- [[Best Practices]]: 모범 사례

#### Available Models
[[Model Categories]]:
- [[Computer Vision]]: 이미지 처리
- [[NLP]]: 자연어 처리
- [[Time Series]]: 시계열
- [[Regression]]: 회귀
- [[Classification]]: 분류
- [[Forecasting]]: 예측
- [[Clustering]]: 클러스터링

#### Using JumpStart
[[Workflow]]:
1. [[Browse Models]]: 모델 검색
2. [[Select Model]]: 모델 선택
3. [[Deploy]]: 배포
4. [[Test]]: 테스트
5. [[Fine-tune if Needed]]: 필요시 파인튜닝
6. [[Use in Production]]: 프로덕션 사용

---

## Data Preparation & Labeling

### [[Data Labeling with SageMaker Ground Truth]]
**Video 9 - Duration: ~19 minutes**

#### Ground Truth Overview
[[Data Annotation]]:
- [[Manual Labeling]]: 수동 라벨링
- [[Automated Labeling]]: 자동 라벨링
- [[Active Learning]]: 능동적 학습
- [[Crowdsourcing]]: 크라우드소싱
- [[Vendor Integration]]: 벤더 통합
- [[Quality Control]]: 품질 관리

#### Labeling Workflows
[[Process]]:
1. [[Define Task]]: 작업 정의
2. [[Create Dataset]]: 데이터셋 생성
3. [[Set Up Labeling]]: 라벨링 설정
4. [[Configure Workforce]]: 작업자 설정
5. [[Monitor Progress]]: 진행 모니터링
6. [[Review Results]]: 결과 검토
7. [[Create Training Data]]: 훈련 데이터 생성

#### Labeling Types
[[Task Types]]:
- [[Image Classification]]: 이미지 분류
- [[Object Detection]]: 객체 탐지
- [[Semantic Segmentation]]: 의미 분할
- [[Text Classification]]: 텍스트 분류
- [[Named Entity Recognition]]: 개체명 인식
- [[3D Point Cloud]]: 3D 포인트 클라우드
- [[Video Frame]]: 비디오 프레임

#### Workforce Options
[[Labeling Options]]:
- [[Private Workforce]]: 자신의 팀
- [[Amazon Mechanical Turk]]: 크라우드
- [[Vendor Partnerships]]: 벤더 파트너
- [[Hybrid]]: 혼합 방식

### [[Preparing Data for ML - Data Wrangler]]
**Video 11 - Duration: ~15 minutes**

#### Data Wrangler Overview
[[Data Preparation]]:
- [[Visual Interface]]: 시각적 인터페이스
- [[No Coding]]: 코딩 불필요
- [[Data Exploration]]: 데이터 탐색
- [[Data Cleaning]]: 데이터 정제
- [[Feature Engineering]]: 특성 엔지니어링
- [[Data Analysis]]: 데이터 분석

#### Data Wrangler Features
[[Capabilities]]:
- [[Data Import]]: 데이터 가져오기
- [[Data Visualization]]: 시각화
- [[Transform Recipes]]: 변환 레시피
- [[Statistical Analysis]]: 통계 분석
- [[Quality Checks]]: 품질 검사
- [[Export]]: 내보내기

#### Workflow
[[Steps]]:
1. [[Import Data]]: 데이터 가져오기
2. [[Explore Data]]: 데이터 탐색
3. [[Apply Transformations]]: 변환 적용
4. [[Create Features]]: 특성 생성
5. [[Check Quality]]: 품질 확인
6. [[Export]]: 내보내기

---

## Model Training & Evaluation

### [[Amazon SageMaker - Train & Deploy]]
**Video 15 Part 2 - Duration: ~20 minutes**

#### Training Jobs
[[Model Training]]:
1. [[Prepare Data]]: 데이터 준비
2. [[Create Training Job]]: 훈련 작업 생성
3. [[Configure]]: 구성
4. [[Monitor Training]]: 훈련 모니터링
5. [[Save Model]]: 모델 저장
6. [[Review Artifacts]]: 결과물 검토

#### Hyperparameter Tuning
[[Optimization]]:
- [[Automatic Tuning]]: 자동 조정
- [[Parameter Ranges]]: 매개변수 범위
- [[Optimization Objective]]: 최적화 목표
- [[Parallel Jobs]]: 병렬 작업
- [[Early Stopping]]: 조기 중단

#### Model Deployment
[[Endpoint Setup]]:
1. [[Create Endpoint]]: 엔드포인트 생성
2. [[Configure]]: 설정
3. [[Deploy Model]]: 모델 배포
4. [[Test Predictions]]: 예측 테스트
5. [[Monitor Performance]]: 성능 모니터링

### [[Detecting Bias - SageMaker Clarify]]
**Video 13 - Duration: ~16 minutes**

#### Bias Detection
[[Fairness Analysis]]:
- [[Pre-Training Bias]]: 훈련 전 편향
- [[Post-Training Bias]]: 훈련 후 편향
- [[Feature Importance]]: 특성 중요도
- [[Partial Dependence]]: 부분 의존성
- [[Shap Values]]: SHAP 값

#### Clarify Features
[[Tools]]:
- [[Bias Detection]]: 편향 감지
- [[Feature Importance]]: 특성 중요도
- [[Model Explainability]]: 모델 설명
- [[Compliance]]: 규제 준수
- [[Fairness Metrics]]: 공정성 메트릭

#### Implementation
[[Process]]:
1. [[Load Model]]: 모델 로드
2. [[Configure Clarify]]: Clarify 설정
3. [[Run Analysis]]: 분석 실행
4. [[Review Results]]: 결과 검토
5. [[Take Action]]: 조치 수행

---

## Model Monitoring & Management

### [[SageMaker Model Monitor - Part 1]]
**Video 8 - Duration: ~18 minutes**

#### Model Monitor Overview
[[Production Monitoring]]:
- [[Data Drift]]: 데이터 변화
- [[Model Performance]]: 모델 성능
- [[Prediction Quality]]: 예측 품질
- [[Real-Time Alerts]]: 실시간 알림
- [[Automated Actions]]: 자동 조치
- [[Compliance Tracking]]: 규제 추적

#### Monitor Setup
[[Configuration]]:
1. [[Enable Monitoring]]: 모니터링 활성화
2. [[Define Baselines]]: 기준 정의
3. [[Set Thresholds]]: 임계값 설정
4. [[Configure Alerts]]: 알림 설정
5. [[Monitor Metrics]]: 메트릭 모니터링

#### Monitor Types
[[Monitoring Categories]]:

**Data Quality**:
- 입력 데이터 변화
- 누락된 값
- 스키마 변경

**Model Quality**:
- 예측 정확도
- 정밀도/재현율
- F1 점수

**Bias Detection**:
- 편향 변화
- 공정성 메트릭
- 감시 대상 특성

**Feature Attribution**:
- 특성 중요도
- SHAP 값
- 영향 분석

### [[SageMaker Model Monitor - Part 2]]
**Video 1 - Duration: ~22 minutes**

#### Advanced Monitoring
[[Deep Dive]]:
- [[Custom Metrics]]: 사용자 정의 메트릭
- [[Baseline Calculation]]: 기준 계산
- [[Constraint Definition]]: 제약 정의
- [[Violation Handling]]: 위반 처리

#### Remediation
[[Automated Response]]:
1. [[Detect Issue]]: 문제 감지
2. [[Trigger Action]]: 조치 시작
3. [[Investigate]]: 조사
4. [[Retrain if Needed]]: 필요시 재훈련
5. [[Redeploy]]: 재배포

---

## SageMaker Pipelines & Automation

### [[Automating ML Workflows]]

#### SageMaker Pipelines
[[Orchestration]]:
- [[Define Pipeline]]: 파이프라인 정의
- [[Step Functions]]: 단계 함수
- [[Conditional Logic]]: 조건부 로직
- [[Parallel Execution]]: 병렬 실행
- [[Error Handling]]: 오류 처리
- [[Version Control]]: 버전 관리

#### Pipeline Steps
[[Components]]:
- [[Processing Steps]]: 데이터 처리
- [[Training Steps]]: 모델 훈련
- [[Tuning Steps]]: 하이퍼파라미터 조정
- [[Evaluation Steps]]: 모델 평가
- [[Deploy Steps]]: 배포
- [[Batch Transform]]: 배치 변환

---

## Summary: SageMaker Complete

### [[Key Takeaways]]

✅ **Data Preparation**:
- Ground Truth 라벨링
- Data Wrangler 전처리
- 품질 관리
- 자동 기능 엔지니어링

✅ **Model Development**:
- JumpStart 사전학습 모델
- 훈련 작업
- 하이퍼파라미터 조정
- 모델 평가

✅ **Production Deployment**:
- 엔드포인트 생성
- 실시간 예측
- 배치 변환
- 자동 스케일링

✅ **Monitoring & Governance**:
- 데이터 드리프트 감지
- 모델 성능 추적
- 편향 탐지
- 규제 준수

✅ **Automation**:
- ML 파이프라인
- 자동 재훈련
- 의사결정 자동화
- 성능 개선 루프

---

**Playlist Source**: All AWS Videos
**Channel**: ImTechnos
**Total SageMaker Videos**: 9 videos
**Coverage**: 전체 ML 파이프라인, 데이터 준비, 훈련, 배포, 모니터링

---

## 🔗 Related Graphs (관련 그래프)

**AI & ML**:
- [[AWS_Bedrock_AI_Graph]] - LLM 서비스
- [[Agentic_AI_Graph]] - AI 에이전트

**데이터 라벨링**:
- [[AI_Data_Labeling_Economy_Graph]] - 데이터 라벨링 경제

**인프라**:
- [[AWS_Storage_Complete_Graph]] - 데이터 저장소
- [[AWS_Management_Infrastructure_Graph]] - 파이프라인 관리

← 돌아가기: [[AI_Agents_Multi_Industry_Enterprise_Hub]]
