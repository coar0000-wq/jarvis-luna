# Semantic Segmentation - Pixel-level Computer Vision - Graph View

← [[AI_Agents_Multi_Industry_Enterprise_Hub]]

## Core Concept
**의미 분할 완벽 가이드**
- Topic: Dense Prediction & Pixel-level Classification
- Goal: 이미지의 각 픽셀을 카테고리로 분류

---

## Semantic Segmentation Fundamentals

### [[What is Semantic Segmentation?]]

#### Core Concept
[[Pixel Classification]]:
- [[Input]]: 이미지
- [[Output]]: 분할 맵 (픽셀마다 클래스)
- [[Granularity]]: 픽셀 수준
- [[Dense Prediction]]: 밀집 예측
- [[Spatial Information]]: 공간 정보 보존

#### Key Differences
[[Comparison]]:

**Classification**:
- 이미지 전체 → 하나 클래스

**Detection**:
- 객체 → 바운딩 박스

**Segmentation**:
- 각 픽셀 → 클래스 레이블

#### Applications
[[Use Cases]]:
- [[Medical Imaging]]: 의료 영상
- [[Autonomous Vehicles]]: 자율주행
- [[Satellite Imagery]]: 위성 이미지
- [[Scene Understanding]]: 장면 이해
- [[Quality Inspection]]: 품질 검사
- [[Agriculture]]: 농업 모니터링

---

## Semantic Segmentation Architectures

### [[Encoder-Decoder Architecture]]

#### Basic Structure
[[Framework]]:

**Encoder**:
- [[Feature Extraction]]: 특성 추출
- [[Downsampling]]: 샘플링 감소
- [[Contextual Information]]: 맥락 정보
- [[Receptive Field]]: 수용 영역 확장

**Decoder**:
- [[Upsampling]]: 샘플링 증가
- [[Spatial Recovery]]: 공간 복구
- [[Skip Connections]]: 스킵 연결
- [[Pixel-wise Prediction]]: 픽셀별 예측

#### Advantages
[[Benefits]]:
- [[Simple]]: 단순한 구조
- [[Effective]]: 효과적
- [[Flexible]]: 유연한 적응
- [[Widely Used]]: 광범위하게 사용

### [[FCN (Fully Convolutional Networks)]]

#### Architecture
[[Key Innovation]]:
- [[End-to-End]]: 전체 합성곱
- [[No FC Layers]]: 완전 연결층 없음
- [[Arbitrary Input Size]]: 임의 크기
- [[Dense Predictions]]: 밀집 예측

#### Skip Connections
[[Combining Features]]:
- [[Coarse Features]]: 대략적 특성
- [[Fine Features]]: 세밀한 특성
- [[Multi-scale]]: 다중 스케일
- [[Spatial Precision]]: 공간 정확도

### [[U-Net]]

#### U-shaped Architecture
[[DESIGN]]:
- [[Symmetric Structure]]: 대칭 구조
- [[Encoder Path]]: 인코더 경로
- [[Decoder Path]]: 디코더 경로
- [[Skip Connections]]: 스킵 연결

#### Advantages
[[Why Effective]]:
- [[Medical Imaging]]: 의료 영상
- [[Small Datasets]]: 작은 데이터셋
- [[High Precision]]: 높은 정확도
- [[Detail Preservation]]: 세부 정보 보존

#### Variants
[[Extensions]]:
- [[3D U-Net]]: 3D 볼륨
- [[ResUNet]]: 잔차 연결
- [[Dense U-Net]]: 밀집 연결
- [[Attention U-Net]]: 주의 메커니즘

### [[SegNet]]

#### Pooling Indices
[[Upsampling Strategy]]:
- [[Store Indices]]: 풀링 인덱스 저장
- [[Efficient Upsampling]]: 효율적 업샘플링
- [[Memory Efficient]]: 메모리 효율
- [[Boundary Preservation]]: 경계 보존

### [[DeepLab Family]]

#### Atrous Convolution
[[Key Innovation]]:
- [[Dilated Convolution]]: 팽창 합성곱
- [[Receptive Field]]: 수용 영역 확대
- [[Parameter Efficiency]]: 매개변수 효율
- [[Multi-scale]]: 다중 스케일

#### DeepLabv3
[[Latest Version]]:
- [[ASPP Module]]: 비동기 공간 피라미드
- [[Better Context]]: 향상된 맥락
- [[High Performance]]: 높은 성능
- [[Efficient]]: 효율적

### [[Transformer-based Models]]

#### ViT for Segmentation
[[Vision Transformer]]:
- [[Self-attention]]: 자기 주의
- [[Global Context]]: 전체 맥락
- [[No Locality Bias]]: 국소 편향 없음
- [[Flexible]]: 유연한 구조

#### SETR
[[Segmentation Transformer]]:
- [[Pure Transformer]]: 순수 트랜스포머
- [[Competitive Performance]]: 경쟁력 있는 성능
- [[Scalable]]: 확장 가능

---

## Loss Functions & Optimization

### [[Segmentation Losses]]

#### Pixel-wise Classification
[[Loss Functions]]:

**Cross-entropy Loss**:
- [[Standard]]: 표준 손실
- [[Per-pixel]]: 픽셀별 계산
- [[Class Imbalance]]: 불균형 처리 필요

**Weighted Cross-entropy**:
- [[Class Weights]]: 클래스 가중치
- [[Rare Classes]]: 드문 클래스 강조
- [[Balance]]: 균형 조정

**Dice Loss**:
- [[Overlap-based]]: 중복 기반
- [[F1-score]]: F1 스코어 사용
- [[Imbalance Robust]]: 불균형 견고

**Focal Loss**:
- [[Hard Examples]]: 어려운 샘플 강조
- [[Class Imbalance]]: 클래스 불균형
- [[Difficult Regions]]: 어려운 영역

**Boundary Loss**:
- [[Edge Focus]]: 경계 강조
- [[Spatial Proximity]]: 공간 근접
- [[Contour Accuracy]]: 윤곽 정확도

### [[Training Strategies]]

#### Class Imbalance
[[Handling]]:
- [[Class Weights]]: 가중치 조정
- [[Sampling Strategy]]: 샘플링 전략
- [[Focal Loss]]: 초점 손실
- [[Hard Negative Mining]]: 음성 샘플 강조

#### Data Augmentation
[[Techniques]]:
- [[Geometric]]: 회전, 뒤집기, 자르기
- [[Photometric]]: 밝기, 명암, 색상
- [[Advanced]]: Mixup, CutMix, Mosaic
- [[Consistency]]: 일관성 유지

---

## Evaluation Metrics

### [[Segmentation Metrics]]

#### Pixel-level Accuracy
[[Performance]]:
- [[Per-pixel Accuracy]]: 픽셀별 정확도
- [[Mean Accuracy]]: 평균 정확도
- [[Class Accuracy]]: 클래스별 정확도

#### Intersection over Union (IoU)
[[Standard Metric]]:
- [[Per-class IoU]]: 클래스별 IoU
- [[Mean IoU]]: 평균 IoU
- [[Frequency Weighted IoU]]: 가중 IoU

#### Dice Coefficient
[[Alternative Metric]]:
- [[Overlap Measure]]: 중복 측정
- [[F1-based]]: F1 기반
- [[Especially Useful]]: 특히 유용
- [[Medical Imaging]]: 의료 영상

#### Boundary Metrics
[[Edge Evaluation]]:
- [[Hausdorff Distance]]: 하우스도르프 거리
- [[Boundary Accuracy]]: 경계 정확도
- [[Distance Map]]: 거리 맵
- [[Contour Evaluation]]: 윤곽 평가

---

## Applications by Domain

### [[Medical Image Segmentation]]

#### Organs & Tissues
[[Medical Applications]]:
- [[Organ Segmentation]]: 장기 분할
- [[Tumor Detection]]: 종양 탐지
- [[Lesion Delineation]]: 병변 경계 표시
- [[Blood Vessel]]: 혈관 분할
- [[Cell Segmentation]]: 세포 분할

#### Modalities
[[Imaging Types]]:
- [[CT Scans]]: CT 스캔
- [[MRI]]: 자기공명
- [[Ultrasound]]: 초음파
- [[Pathology Slides]]: 병리 슬라이드
- [[Endoscopy]]: 내시경

#### Challenges
[[Medical Issues]]:
- [[Annotation Cost]]: 주석 비용
- [[Class Imbalance]]: 클래스 불균형
- [[Small Datasets]]: 작은 데이터셋
- [[Interpretability]]: 설명 가능성

### [[Autonomous Driving]]

#### Scene Understanding
[[Self-driving]]:
- [[Road Segmentation]]: 도로 분할
- [[Lane Segmentation]]: 차선 분할
- [[Obstacle Segmentation]]: 장애물 분할
- [[Sky/Ground]]: 하늘/지면
- [[Drivable Area]]: 주행 가능 영역

### [[Satellite Imagery]]

#### Remote Sensing
[[Earth Observation]]:
- [[Land Cover Classification]]: 토지 피복
- [[Water Bodies]]: 수역
- [[Vegetation Mapping]]: 식생 매핑
- [[Urban Mapping]]: 도시 매핑
- [[Crop Monitoring]]: 농작물 모니터링

### [[Scene Understanding]]

#### Indoor/Outdoor
[[Applications]]:
- [[Room Segmentation]]: 실내 분할
- [[Furniture Detection]]: 가구 탐지
- [[Wall/Floor/Ceiling]]: 벽/바닥/천장
- [[Context Understanding]]: 맥락 이해

---

## Instance Segmentation

### [[Instance vs Semantic]]

#### Differences
[[Key Distinction]]:

**Semantic**:
- 클래스만 구분
- 같은 클래스 = 같은 레이블

**Instance**:
- 개별 객체 구분
- 같은 클래스 ≠ 다른 ID

### [[Mask R-CNN]]

#### Two-stage Approach
[[Architecture]]:
- [[Detection Head]]: 객체 탐지
- [[Segmentation Head]]: 분할 마스크
- [[ROI Align]]: 영역 정렬
- [[Mask Prediction]]: 마스크 예측

#### Advantages
[[Benefits]]:
- [[Accurate Masks]]: 정확한 마스크
- [[Instance-level]]: 인스턴스 수준
- [[Flexible]]: 다양한 작업

---

## Deployment & Optimization

### [[Real-time Segmentation]]

#### Lightweight Models
[[Efficiency]]:
- [[MobileNetV2]]: 모바일 네트워크
- [[EfficientNet]]: 효율적 네트워크
- [[SqueezeNet]]: 압축 네트워크
- [[ShuffleNet]]: 셔플 네트워크

#### Optimization
[[Speed Improvement]]:
- [[Quantization]]: 정수 변환
- [[Pruning]]: 가지치기
- [[Distillation]]: 지식 전이
- [[TensorRT]]: 최적화 엔진

### [[Frameworks]]

#### Implementation Platforms
[[Tools]]:
- [[PyTorch Segmentation]]: PyTorch
- [[TensorFlow Segmentation]]: TensorFlow
- [[OpenCV]]: 전통적 방법
- [[ONNX]]: 모델 교환
- [[AWS SageMaker]]: 클라우드 서비스

---

## Summary: Semantic Segmentation

### [[Key Takeaways]]

✅ **Architectures**:
- FCN, U-Net, DeepLab
- Encoder-Decoder
- Transformer-based

✅ **Techniques**:
- 다중 스케일 특성
- 스킵 연결
- 주의 메커니즘

✅ **Applications**:
- 의료 영상
- 자율주행
- 위성 영상
- 장면 이해

✅ **Challenges**:
- 클래스 불균형
- 작은 객체
- 경계 정확도

---

**Focus**: Semantic Segmentation
**Key Concepts**: FCN, U-Net, DeepLab, Encoder-Decoder
**Tools**: PyTorch, TensorFlow, AWS SageMaker
**Applications**: Medical, Autonomous Driving, Remote Sensing

---

## 🔗 Related Graphs

- [[Image_Classification_Graph]] - 이미지 분류
- [[Object_Detection_Graph]] - 객체 감지
- [[Image_Generation_Graph]] - 이미지 생성
- [[Face_Recognition_Graph]] - 얼굴 인식
- [[AWS_SageMaker_Complete_Graph]] - ML 플랫폼

← 돌아가기: [[AI_Agents_Multi_Industry_Enterprise_Hub]]
