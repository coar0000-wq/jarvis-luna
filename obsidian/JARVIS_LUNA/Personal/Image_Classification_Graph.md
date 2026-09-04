# Image Classification - Computer Vision Complete - Graph View

← [[AI_Agents_Multi_Industry_Enterprise_Hub]]

## Core Concept
**이미지 분류 완벽 가이드**
- Topic: Computer Vision Fundamentals
- Goal: 사진에서 객체/장면을 자동으로 인식하는 AI 모델 마스터

---

## Image Classification Fundamentals

### [[What is Image Classification?]]

#### Core Concept
[[Classification Basics]]:
- [[Input]]: 디지털 이미지
- [[Output]]: 객체 카테고리 레이블
- [[Process]]: 이미지 → 특성 추출 → 분류
- [[Goal]]: 이미지의 주요 내용 식별
- [[Applications]]: 사진 분류, 의료 진단, 품질 검사

#### Classification Types
[[Approaches]]:

**Binary Classification**:
- [[Two Classes]]: 고양이 vs 개
- [[Yes/No Decision]]: 존재 여부
- [[Simplest Form]]: 기본 모델

**Multi-Class**:
- [[Multiple Categories]]: 개, 고양이, 새
- [[Single Label]]: 하나의 클래스만 선택
- [[One-vs-All]]: 각 클래스별 이진 분류

**Multi-Label**:
- [[Multiple Labels]]: 여러 객체 동시
- [[Multiple Outputs]]: 여러 카테고리 할당
- [[Complex Scenarios]]: 복잡한 상황

---

## Deep Learning for Classification

### [[Convolutional Neural Networks (CNN)]]

#### CNN Architecture
[[Network Structure]]:

**Convolutional Layer**:
- [[Filters/Kernels]]: 특성 추출
- [[Stride]]: 이동 간격
- [[Padding]]: 경계 처리
- [[Output Maps]]: 특성맵

**Pooling Layer**:
- [[Max Pooling]]: 최대값 선택
- [[Avg Pooling]]: 평균값 계산
- [[Dimensionality Reduction]]: 차원 축소
- [[Noise Reduction]]: 노이즈 제거

**Fully Connected Layer**:
- [[Classification]]: 분류 계층
- [[Softmax]]: 확률 계산
- [[Decision]]: 최종 판정

#### Activation Functions
[[Non-linearity]]:
- [[ReLU]]: 가장 인기 있는 함수
- [[Sigmoid]]: 이진 분류
- [[Tanh]]: 균형잡힌 범위
- [[Softmax]]: 다중 클래스

### [[Popular CNN Architectures]]

#### Classic Models
[[Proven Architectures]]:

**LeNet**:
- [[Historical]]: 최초 성공한 CNN
- [[Simple]]: 작은 네트워크
- [[MNIST]]: 손글씨 인식

**AlexNet**:
- [[Breakthrough]]: Deep learning 혁명
- [[ImageNet]]: 2012 우승
- [[ReLU]]: 활성화 함수 혁신

**VGG**:
- [[Simple Design]]: 단순 아키텍처
- [[Deep]]: 16-19 층
- [[Effective]]: 높은 정확도

**ResNet (Residual Network)**:
- [[Skip Connections]]: 잔차 연결
- [[Very Deep]]: 100+ 층 가능
- [[Identity Mapping]]: 항등식 학습

**Inception Network**:
- [[Multi-scale]]: 다양한 크기 필터
- [[Efficient]]: 매개변수 효율적
- [[Flexible]]: 병렬 경로

**MobileNet**:
- [[Lightweight]]: 모바일 친화적
- [[Efficient]]: 저전력
- [[Real-time]]: 빠른 추론

#### Modern Architectures
[[State-of-the-Art]]:
- [[EfficientNet]]: 크기-정확도 균형
- [[Vision Transformer (ViT)]]: 트랜스포머 기반
- [[DenseNet]]: 밀집 연결
- [[SENet]]: 채널 주의 메커니즘

---

## Training & Optimization

### [[Data Preparation]]

#### Dataset Requirements
[[Preparation Steps]]:
1. [[Data Collection]]: 이미지 수집
2. [[Cleaning]]: 노이즈 제거
3. [[Labeling]]: 레이블 지정
4. [[Augmentation]]: 데이터 증강
5. [[Splitting]]: 훈련/검증/테스트 분할
6. [[Normalization]]: 정규화

#### Data Augmentation
[[Techniques]]:
- [[Rotation]]: 회전
- [[Flipping]]: 좌우 반전
- [[Cropping]]: 자르기
- [[Brightness]]: 밝기 조정
- [[Contrast]]: 명암 조정
- [[Noise Addition]]: 노이즈 추가
- [[Zoom]]: 확대/축소

### [[Training Process]]

#### Loss Functions
[[Optimization]]:
- [[Cross-Entropy]]: 분류 손실
- [[Focal Loss]]: 불균형 클래스
- [[Triplet Loss]]: 거리 학습
- [[Contrastive Loss]]: 유사도 학습

#### Optimization Algorithms
[[Optimizers]]:
- [[SGD]]: 확률적 경사하강법
- [[Momentum]]: 모멘텀
- [[Adam]]: 적응형 모멘트
- [[RMSprop]]: 이차 모멘트
- [[AdaGrad]]: 적응형 학습률

### [[Hyperparameter Tuning]]

#### Key Parameters
[[Optimization]]:
- [[Learning Rate]]: 학습률
- [[Batch Size]]: 배치 크기
- [[Epochs]]: 훈련 반복
- [[Dropout]]: 과적합 방지
- [[Weight Decay]]: L2 정규화
- [[Early Stopping]]: 조기 중단

---

## Model Evaluation & Metrics

### [[Classification Metrics]]

#### Accuracy Metrics
[[Performance Measures]]:
- [[Accuracy]]: 전체 정확도
- [[Precision]]: 양성 정확도
- [[Recall]]: 민감도
- [[F1-Score]]: 조화 평균
- [[ROC-AUC]]: 곡선 아래 면적
- [[Confusion Matrix]]: 혼동 행렬

#### Class-specific Metrics
[[Per-Class Performance]]:
- [[Per-Class Accuracy]]: 클래스별 정확도
- [[Macro Average]]: 단순 평균
- [[Weighted Average]]: 가중 평균
- [[Class Imbalance]]: 불균형 처리

### [[Transfer Learning]]

#### Pre-trained Models
[[Leverage Existing]]:
- [[ImageNet Pre-training]]: 대규모 데이터
- [[Fine-tuning]]: 마지막 층 조정
- [[Feature Extraction]]: 특성 추출
- [[Domain Adaptation]]: 도메인 전이

#### Benefits
[[Advantages]]:
- [[Reduced Training Time]]: 빠른 훈련
- [[Less Data Needed]]: 적은 데이터
- [[Better Accuracy]]: 높은 정확도
- [[Computational Efficiency]]: 효율성

---

## Real-world Applications

### [[Medical Image Classification]]

#### Use Cases
[[Healthcare Applications]]:
- [[X-ray Analysis]]: 엑스레이 진단
- [[CT Scans]]: CT 스캔 분석
- [[Pathology]]: 병리 이미지
- [[Disease Detection]]: 질병 진단
- [[Tumor Classification]]: 종양 분류

#### Challenges
[[Medical Specifics]]:
- [[Data Privacy]]: HIPAA 준수
- [[Annotation Cost]]: 전문가 필요
- [[Class Imbalance]]: 드문 질병
- [[Interpretability]]: 설명 가능성

### [[E-Commerce Applications]]

#### Product Classification
[[Retail Use]]:
- [[Category Prediction]]: 자동 분류
- [[Quality Control]]: 품질 검사
- [[Defect Detection]]: 결함 감지
- [[Visual Search]]: 시각 검색

### [[Autonomous Vehicles]]

#### Applications
[[Self-Driving]]:
- [[Road Sign Recognition]]: 표지판 인식
- [[Traffic Light Detection]]: 신호등
- [[Lane Detection]]: 차선 감지
- [[Obstacle Classification]]: 장애물 분류

---

## Deployment & Optimization

### [[Model Deployment]]

#### Frameworks
[[Tools]]:
- [[TensorFlow]]: Google의 프레임워크
- [[PyTorch]]: Meta의 프레임워크
- [[ONNX]]: 모델 교환 형식
- [[TensorFlow Lite]]: 모바일 버전

#### Optimization Techniques
[[Efficiency]]:
- [[Quantization]]: 정수 변환
- [[Pruning]]: 불필요한 가중치 제거
- [[Distillation]]: 작은 모델 훈련
- [[Model Compression]]: 크기 축소

---

## Summary: Image Classification

### [[Key Takeaways]]

✅ **Fundamentals**:
- 이미지 분류 개념
- CNN 아키텍처
- 사전학습 모델

✅ **Training**:
- 데이터 준비
- 모델 훈련
- 하이퍼파라미터 조정

✅ **Evaluation**:
- 성능 메트릭
- 교차 검증
- 과적합 방지

✅ **Applications**:
- 의료 영상
- 전자상거래
- 자율주행

---

**Focus**: Image Classification
**Key Concepts**: CNN, Transfer Learning, Fine-tuning, Metrics
**Tools**: TensorFlow, PyTorch, AWS SageMaker, AWS Rekognition
**Applications**: Medical, E-commerce, Autonomous Vehicles

---

## 🔗 Related Graphs

- [[Object_Detection_Graph]] - 객체 감지
- [[Semantic_Segmentation_Graph]] - 의미 분할
- [[Image_Generation_Graph]] - 이미지 생성
- [[Face_Recognition_Graph]] - 얼굴 인식
- [[AWS_SageMaker_Complete_Graph]] - ML 플랫폼
- [[AWS_Bedrock_AI_Graph]] - 이미지 생성

← 돌아가기: [[AI_Agents_Multi_Industry_Enterprise_Hub]]
