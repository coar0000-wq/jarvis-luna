# Data Annotation Types Complete - Graph View

← [[AI_Agents_Multi_Industry_Enterprise_Hub]]

## Core Concept
**데이터 주석의 모든 유형 완벽 가이드**
- Topic: Data Labeling Classification
- Goal: 다양한 데이터 주석 방식 마스터

---

## Data Annotation Fundamentals

### [[What is Data Annotation?]]

#### Definition
[[Annotation Basics]]:
- [[Process]]: 데이터에 레이블 추가
- [[Purpose]]: ML 모델 훈련용
- [[Quality Critical]]: 정확도 필수
- [[Labor Intensive]]: 인력 집약적
- [[Cost Factor]]: 상당한 비용

#### Importance
[[Why It Matters]]:
- [[Ground Truth]]: 정답 데이터
- [[Model Accuracy]]: 모델 성능 결정
- [[Data Quality]]: 모든 것의 기초
- [[Scalability]]: 대규모 시스템 필요
- [[Bottleneck]]: AI 개발의 병목

---

## Image Annotation Types

### [[Image Classification Annotation]]

#### Single-label Classification
[[Process]]:
- [[One Class]]: 하나의 카테고리
- [[Tagging]]: 이미지 태그
- [[Categories]]: 개, 고양이, 새 등
- [[Simple]]: 가장 기본
- [[Common]]: 가장 일반적

#### Multi-label Classification
[[Process]]:
- [[Multiple Labels]]: 여러 카테고리
- [[Complex Scenes]]: 복잡한 장면
- [[Multiple Objects]]: 여러 객체
- [[More Flexible]]: 더 유연함

### [[Object Detection Annotation]]

#### Bounding Box
[[Annotation Method]]:
- [[Rectangle Drawing]]: 직사각형 그리기
- [[Coordinates]]: x, y, width, height
- [[Object Location]]: 위치 표시
- [[Size Definition]]: 크기 정의
- [[Most Common]]: 가장 흔함

#### Anchor Points
[[Alternative Method]]:
- [[Corner Points]]: 모서리 점
- [[Center Point]]: 중심점
- [[Polygon]]: 다각형
- [[Flexible Shape]]: 유연한 모양

### [[Semantic Segmentation Annotation]]

#### Pixel-level Labeling
[[Annotation Method]]:
- [[Every Pixel]]: 모든 픽셀
- [[Mask Creation]]: 마스크 생성
- [[Detailed Boundaries]]: 정확한 경계
- [[Dense Prediction]]: 밀집 예측
- [[Labor Intensive]]: 가장 비용 높음

#### Color-coded Maps
[[Visualization]]:
- [[Color Per Class]]: 클래스별 색상
- [[Easy Visualization]]: 시각화 용이
- [[Interpretation]]: 해석 용이

### [[Instance Segmentation Annotation]]

#### Individual Objects
[[Annotation Method]]:
- [[Per-object Mask]]: 객체별 마스크
- [[Object Identity]]: 객체 식별
- [[Overlapping Objects]]: 겹치는 객체
- [[Separate Tracking]]: 개별 추적
- [[Most Complex]]: 가장 복잡

### [[Keypoint Annotation]]

#### Feature Points
[[Annotation Method]]:
- [[Critical Points]]: 중요 지점
- [[Pose Estimation]]: 자세 추정
- [[Landmark Detection]]: 특징점 감지
- [[Skeleton Mapping]]: 골격 매핑
- [[Medical Applications]]: 의료 응용

---

## Text Annotation Types

### [[Text Classification]]

#### Document Level
[[Annotation Method]]:
- [[Sentiment]]: 긍정/부정/중립
- [[Category]]: 주제 분류
- [[Intent]]: 의도 분류
- [[Topic]]: 주제 태그

#### Sentence Level
[[Annotation Method]]:
- [[Sentence Sentiment]]: 문장 감정
- [[Relation]]: 관계 표시
- [[Event]]: 사건 마킹

### [[Named Entity Recognition (NER)]]

#### Entity Tagging
[[Annotation Method]]:
- [[Person]]: 사람 이름
- [[Location]]: 장소 이름
- [[Organization]]: 조직 이름
- [[Date]]: 날짜
- [[Money]]: 금액
- [[Span Selection]]: 구간 선택

### [[Text Relation Annotation]]

#### Relationship Marking
[[Annotation Method]]:
- [[Entity Relations]]: 개체 간 관계
- [[Semantic Relations]]: 의미 관계
- [[Link Creation]]: 링크 생성
- [[Graph Building]]: 그래프 구성

### [[Machine Translation Annotation]]

#### Reference Translation
[[Annotation Method]]:
- [[Human Translation]]: 인간 번역
- [[Quality Assessment]]: 품질 평가
- [[Multiple References]]: 여러 참조
- [[Cultural Adaptation]]: 문화 적응

---

## Audio & Speech Annotation

### [[Speech Transcription]]

#### Audio to Text
[[Annotation Method]]:
- [[Manual Transcription]]: 수동 필사
- [[Accuracy Critical]]: 정확도 필수
- [[Time Intensive]]: 시간 소요
- [[Quality Control]]: 품질 관리

#### Speaker Labeling
[[Annotation Method]]:
- [[Speaker Identity]]: 화자 식별
- [[Speaker Turns]]: 화자 전환
- [[Multiple Speakers]]: 여러 화자
- [[Diarization]]: 화자 분할

### [[Emotion & Tone]]

#### Audio Characteristics
[[Annotation Method]]:
- [[Emotion]]: 감정 (행복, 슬픔, 분노)
- [[Tone]]: 톤 (공식적, 친근한)
- [[Accent]]: 악센트
- [[Speaking Style]]: 말씨

### [[Sound Event Detection]]

#### Audio Events
[[Annotation Method]]:
- [[Event Type]]: 사건 유형
- [[Event Time]]: 발생 시간
- [[Event Duration]]: 지속 시간
- [[Temporal Annotation]]: 시간 주석

---

## Video Annotation Types

### [[Action Recognition]]

#### Video Labeling
[[Annotation Method]]:
- [[Action Type]]: 행동 유형
- [[Temporal Boundaries]]: 시간 경계
- [[Action Duration]]: 행동 지속
- [[Multiple Actions]]: 여러 행동
- [[Frame Range]]: 프레임 범위

### [[Object Tracking]]

#### Motion Annotation
[[Annotation Method]]:
- [[Bounding Box Tracking]]: 박스 추적
- [[Frame-by-frame]]: 프레임별
- [[Continuous Motion]]: 연속 움직임
- [[ID Assignment]]: ID 할당
- [[High Effort]]: 매우 노동 집약적

### [[Scene Description]]

#### Video Content
[[Annotation Method]]:
- [[Scene Content]]: 장면 내용
- [[Context]]: 배경 정보
- [[Narrative]]: 서사
- [[Summary]]: 요약

---

## 3D Data Annotation

### [[3D Point Cloud]]

#### 3D Object Detection
[[Annotation Method]]:
- [[3D Bounding Box]]: 3D 박스
- [[3D Coordinates]]: 3D 좌표
- [[Rotation]]: 회전 정보
- [[Specialized Tools]]: 전문 도구
- [[Complex]]: 매우 복잡

### [[3D Segmentation]]

#### Point-wise Labeling
[[Annotation Method]]:
- [[Per-point Labels]]: 점별 레이블
- [[Instance Separation]]: 인스턴스 분리
- [[Dense Labeling]]: 밀집 레이블
- [[3D Precision]]: 3D 정밀도

---

## Specialized Annotation Types

### [[Medical Imaging Annotation]]

#### Medical-specific
[[Annotation Method]]:
- [[Organ Segmentation]]: 장기 분할
- [[Lesion Marking]]: 병변 표시
- [[Measurement]]: 측정
- [[Diagnosis Support]]: 진단 지원
- [[Expert Needed]]: 전문가 필요

### [[Satellite Imagery Annotation]]

#### Geospatial Data
[[Annotation Method]]:
- [[Land Cover]]: 토지 피복
- [[Change Detection]]: 변화 감지
- [[Object Identification]]: 객체 식별
- [[Large Scale]]: 대규모 데이터
- [[Specialized Knowledge]]: 특화 지식

### [[Synthetic Data Annotation]]

#### AI-generated Labels
[[Annotation Method]]:
- [[Automatic Annotation]]: 자동 생성
- [[Semi-supervised]]: 반자동
- [[Domain Adaptation]]: 도메인 적응
- [[Cost Reduction]]: 비용 절감
- [[Validation Needed]]: 검증 필요

---

## Annotation Quality & Standards

### [[Inter-Annotator Agreement]]

#### Consistency Measurement
[[Metrics]]:
- [[Cohen's Kappa]]: 코헨 카파
- [[Fleiss' Kappa]]: 플라이스 카파
- [[Jaccard Index]]: 자카드 지수
- [[Consistency]]: 일관성 측정

### [[Quality Control]]

#### Validation Process
[[Methods]]:
- [[Gold Standard]]: 금 표준
- [[Expert Review]]: 전문가 검토
- [[Consensus]]: 합의 기반
- [[Iterative Refinement]]: 반복 개선

---

## Summary: Data Annotation Types

### [[Key Takeaways]]

✅ **Image**:
- 분류, 감지, 분할, 키포인트
- 다양한 복잡도

✅ **Text**:
- 분류, NER, 관계, 번역
- 언어 특화

✅ **Audio**:
- 필사, 감정, 사건
- 시간 기반

✅ **Video**:
- 행동, 추적, 장면
- 고노력

✅ **3D**:
- 포인트 클라우드
- 전문 도구

✅ **Special**:
- 의료, 위성, 합성
- 전문 지식 필요

---

**Focus**: Data Annotation Types
**Key Concepts**: Classification, Detection, Segmentation, Tracking
**Applications**: All ML Domains
**Cost Impact**: High (most expensive ML step)

---

## 🔗 Related Graphs

**연구논문**:
- [[Data_Labeling_Research_Papers_Graph]] - 기초 연구논문
- [[Data_Labeling_Advanced_Research_Graph]] - 고급 연구논문

**관련 그래프**:
- [[Data_Annotation_Beginners_Guide_Graph]] - 초보자 가이드
- [[Data_Annotation_Techniques_Graph]] - 기술 & 방법론
- [[Data_Annotation_Tools_Graph]] - 도구 & 플랫폼
- [[AI_Data_Labeling_Economy_Graph]] - 경제 & 일자리
- [[AWS_SageMaker_Complete_Graph]] - Ground Truth

← 돌아가기: [[AI_Agents_Multi_Industry_Enterprise_Hub]]
