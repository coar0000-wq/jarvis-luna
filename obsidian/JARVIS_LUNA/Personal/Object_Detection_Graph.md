# Object Detection - Computer Vision Complete - Graph View

← [[AI_Agents_Multi_Industry_Enterprise_Hub]]

## Core Concept
**객체 감지 완벽 가이드**
- Topic: Advanced Computer Vision
- Goal: 이미지에서 여러 객체를 찾아 위치와 클래스 식별

---

## Object Detection Fundamentals

### [[What is Object Detection?]]

#### Core Concept
[[Detection Basics]]:
- [[Input]]: 이미지/비디오
- [[Output]]: 바운딩 박스 + 클래스 레이블
- [[Coordinates]]: (x, y, width, height)
- [[Confidence Score]]: 신뢰도
- [[Multiple Objects]]: 여러 객체 동시 감지

#### Key Differences from Classification
[[Comparison]]:
- **Classification**: 이미지 전체 분류
- **Detection**: 객체의 위치와 클래스
- **Complexity**: 더 복잡한 작업
- **Output**: 여러 바운딩 박스

---

## Object Detection Architectures

### [[Two-Stage Detectors]]

#### R-CNN (Region-based CNN)
[[Original Approach]]:
- [[Region Proposals]]: 관심 영역 추출
- [[CNN Classification]]: 각 영역 분류
- [[Bounding Box Regression]]: 박스 조정
- [[Slow but Accurate]]: 느리지만 정확

#### Fast R-CNN
[[Improvements]]:
- [[Shared Computation]]: 공유 계산
- [[ROI Pooling]]: 영역 풀링
- [[Faster Training]]: 빠른 훈련
- [[Better Accuracy]]: 높은 정확도

#### Faster R-CNN
[[Modern Approach]]:
- [[Region Proposal Network (RPN)]]: 자동 제안
- [[Anchor Boxes]]: 앵커 박스
- [[End-to-End Training]]: 전체 훈련
- [[Standard Baseline]]: 표준 방식

#### Mask R-CNN
[[Extension]]:
- [[Instance Segmentation]]: 인스턴스 분할
- [[Pixel-level Masks]]: 픽셀 마스크
- [[Object Outlines]]: 객체 윤곽
- [[Additional Output]]: 추가 정보

### [[One-Stage Detectors]]

#### YOLO (You Only Look Once)
[[Single Pass]]:
- [[Speed]]: 매우 빠름
- [[Real-time]]: 실시간 처리
- [[Single Network]]: 하나의 네트워크
- [[Trade-off]]: 속도 vs 정확도

**YOLOv1-v8 Evolution**:
- [[YOLOv1]]: 원본 개념
- [[YOLOv3]]: 멀티스케일 예측
- [[YOLOv4]]: 개선 최적화
- [[YOLOv5]]: PyTorch 구현
- [[YOLOv8]]: 최신 버전

#### SSD (Single Shot Detector)
[[Multi-scale Detection]]:
- [[Feature Pyramids]]: 특성 피라미드
- [[Multiple Scales]]: 다양한 크기
- [[Balanced Speed]]: 속도-정확도 균형
- [[Efficient]]: 효율적

#### RetinaNet
[[Focal Loss]]:
- [[Class Imbalance]]: 클래스 불균형 해결
- [[Focal Loss]]: 새로운 손실함수
- [[Dense Object Detection]]: 밀집 감지
- [[High Accuracy]]: 높은 정확도

---

## Detection Components

### [[Region Proposal Generation]]

#### Methods
[[Proposal Strategies]]:
- [[Selective Search]]: 선택적 검색
- [[EdgeBoxes]]: 엣지 박스
- [[RPN (Region Proposal Network)]]: 신경망 기반
- [[Anchor Boxes]]: 앵커 기반

#### Anchor Configuration
[[Anchor Setup]]:
- [[Sizes]]: 다양한 크기
- [[Aspect Ratios]]: 가로세로비
- [[Scales]]: 스케일 (0.5x, 1x, 2x)
- [[Stride]]: 그리드 간격

### [[Bounding Box Regression]]

#### Box Prediction
[[Coordinate Prediction]]:
- [[Center Point]]: 중심 좌표
- [[Width & Height]]: 크기
- [[Offset Learning]]: 오프셋 학습
- [[Smooth L1 Loss]]: 손실함수

#### Non-Maximum Suppression (NMS)
[[Post-processing]]:
- [[Duplicate Removal]]: 중복 제거
- [[Confidence Thresholding]]: 임계값
- [[IoU Calculation]]: 교집합 비율
- [[Greedy Selection]]: 탐욕적 선택

### [[Feature Pyramid Networks]]

#### Multi-scale Features
[[Hierarchical Features]]:
- [[High Resolution]]: 작은 객체
- [[Low Resolution]]: 큰 객체
- [[Semantic Info]]: 의미 정보
- [[Spatial Details]]: 공간 정보

#### FPN Architecture
[[Structure]]:
- [[Backbone]]: 기본 네트워크
- [[Top-down Pathway]]: 상향식
- [[Lateral Connections]]: 측면 연결
- [[Unified Prediction]]: 통합 예측

---

## Training & Optimization

### [[Data Preparation for Detection]]

#### Annotation Formats
[[Label Formats]]:
- [[Pascal VOC]]: XML 형식
- [[COCO]]: JSON 형식
- [[YOLO]]: 텍스트 형식
- [[Custom]]: 사용자 정의

#### Challenges
[[Dataset Issues]]:
- [[Small Objects]]: 작은 객체
- [[Occlusion]]: 부분 가림
- [[Scale Variation]]: 크기 변화
- [[Class Imbalance]]: 클래스 불균형
- [[Annotation Cost]]: 라벨링 비용

### [[Loss Functions]]

#### Detection Losses
[[Optimization]]:
- [[Confidence Loss]]: 객체 유무
- [[Localization Loss]]: 박스 위치
- [[Classification Loss]]: 클래스 확률
- [[Total Loss]]: 가중 합계

#### Advanced Losses
[[Techniques]]:
- [[Focal Loss]]: 어려운 샘플 강조
- [[GIoU Loss]]: 교집합 손실
- [[DIoU Loss]]: 거리 기반
- [[CIoU Loss]]: 완전 IoU 손실

---

## Evaluation Metrics

### [[Detection Metrics]]

#### Intersection over Union (IoU)
[[Box Overlap]]:
- [[Definition]]: 교집합/합집합
- [[Threshold]]: 0.5 (COCO: 0.5-0.95)
- [[Match Decision]]: 정답 판정
- [[Confidence-based]]: 신뢰도 순서

#### mAP (mean Average Precision)
[[Standard Metric]]:
- [[Per-class AP]]: 클래스별 AP
- [[Precision-Recall]]: 정밀도-재현율
- [[Average]]: 평균값
- [[COCO mAP]]: COCO 기준

#### Speed Metrics
[[Performance]]:
- [[FPS (Frames per Second)]]: 초당 프레임
- [[Latency]]: 지연시간
- [[Throughput]]: 처리량
- [[Model Size]]: 모델 크기

---

## Real-world Applications

### [[Autonomous Vehicles]]

#### Vehicle Detection
[[Self-driving]]:
- [[Car Detection]]: 자동차 감지
- [[Pedestrian Detection]]: 보행자 감지
- [[Traffic Sign]]: 신호판 감지
- [[Lane Detection]]: 차선 감지
- [[Real-time Critical]]: 실시간 필수

### [[Surveillance & Security]]

#### Video Monitoring
[[Security Applications]]:
- [[Person Detection]]: 사람 감지
- [[Anomaly Detection]]: 이상 감지
- [[Activity Recognition]]: 활동 인식
- [[Crowd Analysis]]: 군중 분석

### [[Retail & Manufacturing]]

#### Industrial Applications
[[Production]]:
- [[Defect Detection]]: 결함 감지
- [[Quality Control]]: 품질 관리
- [[Inventory Tracking]]: 재고 추적
- [[Shelf Monitoring]]: 선반 모니터링

### [[Medical Imaging]]

#### Healthcare Detection
[[Diagnosis]]:
- [[Tumor Detection]]: 종양 감지
- [[Lesion Detection]]: 병변 감지
- [[Organ Segmentation]]: 장기 분할
- [[Disease Localization]]: 질병 위치

---

## Deployment & Optimization

### [[Model Optimization]]

#### Techniques
[[Efficiency]]:
- [[Quantization]]: 정수 변환
- [[Pruning]]: 가지치기
- [[Knowledge Distillation]]: 지식 전이
- [[Neural Architecture Search]]: 자동 설계

#### Hardware Acceleration
[[Performance]]:
- [[GPU]]: NVIDIA CUDA
- [[TPU]]: Google TPU
- [[Edge Devices]]: 엣지 기기
- [[Mobile]]: 모바일 최적화

### [[Popular Frameworks]]

#### Implementation Platforms
[[Tools]]:
- [[TensorFlow Object Detection API]]: TensorFlow
- [[Detectron2]]: Meta 프레임워크
- [[PyTorch YOLOv5]]: 인기 YOLO
- [[OpenCV]]: 전통적 방법
- [[AWS Lookout for Vision]]: AWS 서비스

---

## Summary: Object Detection

### [[Key Takeaways]]

✅ **Architectures**:
- Two-stage vs One-stage
- R-CNN 계열
- YOLO 계열
- 최신 방법

✅ **Components**:
- 영역 제안
- 바운딩 박스 회귀
- 다중 스케일 특성
- 후처리

✅ **Training**:
- 데이터 준비
- 손실함수
- 하이퍼파라미터
- 평가 지표

✅ **Applications**:
- 자율주행
- 보안 감시
- 산업 검사
- 의료 영상

---

**Focus**: Object Detection
**Key Concepts**: R-CNN, YOLO, Feature Pyramids, NMS
**Tools**: TensorFlow, PyTorch, AWS Rekognition
**Applications**: Autonomous Vehicles, Security, Manufacturing, Healthcare

---

## 🔗 Related Graphs

- [[Image_Classification_Graph]] - 이미지 분류
- [[Semantic_Segmentation_Graph]] - 의미 분할
- [[Image_Generation_Graph]] - 이미지 생성
- [[Face_Recognition_Graph]] - 얼굴 인식
- [[AWS_Advanced_Services_Graph]] - AWS Rekognition

← 돌아가기: [[AI_Agents_Multi_Industry_Enterprise_Hub]]
