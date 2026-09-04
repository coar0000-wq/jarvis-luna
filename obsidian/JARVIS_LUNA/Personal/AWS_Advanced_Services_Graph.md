# AWS Advanced Services & Architecture - Graph View

← [[AI_Agents_Multi_Industry_Enterprise_Hub]]

## Core Concept
**AWS 고급 서비스 및 아키텍처 완벽 가이드**
- Playlist: All AWS Videos (69 videos)
- Channel: ImTechnos
- Goal: 고급 AWS 서비스 및 Well-Architected 프레임워크

---

## AWS AMI (Amazon Machine Image) Management

### [[Mastering AWS AMIs - Parts 1-2]]
**Video 34-35 - Duration: ~30 minutes**

#### AMI Overview
[[Machine Image]]:
- [[Template]]: 인스턴스 템플릿
- [[Includes OS]]: 운영체제 포함
- [[Pre-configured]]: 사전 구성
- [[Reusable]]: 재사용 가능
- [[Shareable]]: 공유 가능
- [[Region-specific]]: 지역별
- [[Version Control]]: 버전 관리

#### AMI Components
[[Building Blocks]]:
- [[Root Volume]]: 루트 볼륨
- [[Block Device Mappings]]: 블록 디바이스
- [[Permissions]]: 접근 권한
- [[Metadata]]: 메타데이터
- [[Architecture]]: 아키텍처
- [[Kernel ID]]: 커널

#### Creating Custom AMI
[[Development Process]]:
1. [[Launch Instance]]: 인스턴스 시작
2. [[Configure]]: 구성
3. [[Install Software]]: 소프트웨어 설치
4. [[Customize]]: 커스터마이징
5. [[Optimize]]: 최적화
6. [[Create Image]]: AMI 생성
7. [[Test]]: 테스트
8. [[Document]]: 문서화

#### AMI Lifecycle
[[Management]]:
- [[Creation]]: AMI 생성
- [[Tagging]]: 태그 지정
- [[Versioning]]: 버전 관리
- [[Sharing]]: 공유
- [[Copying]]: 지역 간 복사
- [[Deprecation]]: 사용 중단
- [[Deletion]]: 삭제

#### Copy & Share AMI
[[Distribution]]:

**Copying Across Regions**:
- 다른 지역으로 복사
- 자동 복제
- 암호화 옵션
- 스냅샷 포함

**Sharing with Accounts**:
- 계정 간 공유
- 권한 제어
- 용량 할당
- 감사 추적

#### AMI Best Practices
[[Guidelines]]:
- [[Naming Convention]]: 명확한 이름
- [[Regular Updates]]: 정기적 업데이트
- [[Minimal Installation]]: 최소 설치
- [[Optimization]]: 성능 최적화
- [[Security Hardening]]: 보안 강화
- [[Documentation]]: 문서화
- [[Version Control]]: 버전 관리

---

## Amazon Rekognition - Computer Vision

### [[Getting Started with Amazon Rekognition]]
**Video 19 - Duration: ~14 minutes**

#### Rekognition Overview
[[Computer Vision Service]]:
- [[Image Analysis]]: 이미지 분석
- [[Video Analysis]]: 비디오 분석
- [[Object Detection]]: 객체 탐지
- [[Face Recognition]]: 얼굴 인식
- [[Text Detection]]: 텍스트 감지
- [[Moderation]]: 콘텐츠 조정
- [[Custom Labels]]: 사용자 정의 레이블

#### Rekognition APIs
[[Available Services]]:

**Image Analysis**:
- [[DetectLabels]]: 객체/장면 감지
- [[DetectFaces]]: 얼굴 감지
- [[RecognizeCelebrities]]: 유명인 인식
- [[DetectText]]: 텍스트 인식
- [[DetectModerationLabels]]: 유해 콘텐츠 감지
- [[SearchFacesByImage]]: 얼굴 검색

**Video Analysis**:
- [[StartLabelDetection]]: 라벨 감지
- [[StartFaceDetection]]: 얼굴 감지
- [[StartPersonTracking]]: 사람 추적
- [[StartCelebrityRecognition]]: 유명인 인식
- [[StartTextDetection]]: 텍스트 감지

#### Use Cases
[[Applications]]:
- [[Photo Organization]]: 사진 분류
- [[Security Monitoring]]: 보안 모니터링
- [[Content Moderation]]: 콘텐츠 검수
- [[Retail Analytics]]: 소매 분석
- [[Media Analysis]]: 미디어 분석
- [[Accessibility]]: 접근성
- [[Document Analysis]]: 문서 분석

#### Hands-On Implementation
[[Process]]:
1. [[Prepare Images]]: 이미지 준비
2. [[Use AWS Console]]: 콘솔 사용
3. [[Call API]]: API 호출
4. [[Process Results]]: 결과 처리
5. [[Build Application]]: 애플리케이션 구축
6. [[Test]]: 테스트

---

## AWS Well-Architected Framework

### [[AWS Well-Architected Framework]]
**Video 45 - Duration: ~18 minutes**

#### Framework Overview
[[Architecture Principles]]:
- [[Design Guide]]: 설계 가이드
- [[Best Practices]]: 모범 사례
- [[Operational Excellence]]: 운영 우수성
- [[Security]]: 보안
- [[Reliability]]: 안정성
- [[Performance Efficiency]]: 성능 효율성
- [[Cost Optimization]]: 비용 최적화

#### Five Pillars
[[Core Principles]]:

**1. Operational Excellence**:
- [[IaC]]: Infrastructure as Code
- [[Monitoring]]: 모니터링
- [[Automation]]: 자동화
- [[Continuous Improvement]]: 지속적 개선
- [[Documentation]]: 문서화
- [[Incident Management]]: 사건 관리

**2. Security**:
- [[IAM]]: 접근 제어
- [[Encryption]]: 암호화
- [[Network Security]]: 네트워크 보안
- [[Data Protection]]: 데이터 보호
- [[Compliance]]: 규제 준수
- [[Incident Response]]: 사건 대응

**3. Reliability**:
- [[High Availability]]: 고가용성
- [[Disaster Recovery]]: 재해복구
- [[Fault Tolerance]]: 내결함성
- [[Capacity Management]]: 용량 관리
- [[Testing]]: 테스트
- [[Monitoring]]: 모니터링

**4. Performance Efficiency**:
- [[Right Sizing]]: 적절한 크기
- [[Caching]]: 캐싱
- [[Auto Scaling]]: 자동 확장
- [[Optimization]]: 최적화
- [[Monitoring]]: 성능 모니터링
- [[Architecture]]: 아키텍처 선택

**5. Cost Optimization**:
- [[Resource Tagging]]: 리소스 태그
- [[Reserved Capacity]]: 예약 용량
- [[Spot Instances]]: 스팟 인스턴스
- [[Right Sizing]]: 적절한 크기
- [[Monitoring]]: 비용 모니터링
- [[Automation]]: 자동화

#### Assessment Process
[[Review Steps]]:
1. [[Prepare]]: 준비
2. [[Review Architecture]]: 아키텍처 검토
3. [[Answer Questions]]: 질문 응답
4. [[Identify Risks]]: 위험 식별
5. [[Prioritize Improvements]]: 개선 우선순위
6. [[Develop Plan]]: 계획 수립
7. [[Implement]]: 구현

#### Design Principles
[[Guidelines]]:
- [[Stop Guessing Capacity]]: 용량 추정 자동화
- [[Test at Production Scale]]: 프로덕션 규모 테스트
- [[Automate]]: 자동화
- [[Allow Evolutionary Architectures]]: 진화 가능한 아키텍처
- [[Data-Driven]]: 데이터 기반 결정
- [[Improve Through Games]]: 카오스 엔지니어링

---

## Integration & Best Practices

### [[Networking & Architecture]]

#### VPC Architecture
[[Network Design]]:
- [[Virtual Private Cloud]]: VPC 생성
- [[Subnets]]: 서브넷 분리
- [[Security Groups]]: 보안 그룹
- [[NACLs]]: 네트워크 ACL
- [[Routing]]: 라우팅 테이블
- [[NAT Gateway]]: NAT 게이트웨이
- [[VPN/Direct Connect]]: 연결

#### High Availability Design
[[Resilience]]:
- [[Multi-AZ]]: 다중 가용 영역
- [[Load Balancing]]: 로드 분산
- [[Auto Scaling]]: 자동 확장
- [[Database Replication]]: 데이터베이스 복제
- [[Backup & Recovery]]: 백업 및 복구
- [[Health Checks]]: 상태 확인

### [[Monitoring & Observability]]

#### CloudWatch
[[Monitoring]]:
- [[Metrics]]: 메트릭 수집
- [[Logs]]: 로그 수집
- [[Alarms]]: 알림
- [[Dashboards]]: 대시보드
- [[Events]]: 이벤트
- [[Insights]]: 통찰력

#### Logging Strategy
[[Log Management]]:
- [[Centralized Logging]]: 중앙 로깅
- [[Log Retention]]: 로그 보관
- [[Log Analysis]]: 로그 분석
- [[Log Encryption]]: 로그 암호화
- [[Compliance Logging]]: 규제 로깅

---

## Advanced Architecture Patterns

### [[Microservices Architecture]]

#### Components
[[Building Blocks]]:
- [[Container Services]]: ECS/EKS
- [[API Gateway]]: API Gateway
- [[Lambda]]: 서버리스
- [[Databases]]: 데이터베이스
- [[Message Queues]]: 메시지 큐
- [[Monitoring]]: 모니터링

#### Benefits
[[Advantages]]:
- [[Scalability]]: 확장성
- [[Flexibility]]: 유연성
- [[Resilience]]: 복원력
- [[Speed]]: 속도
- [[Team Independence]]: 팀 독립성

### [[Serverless Architecture]]

#### Characteristics
[[Pattern]]:
- [[No Servers]]: 서버 관리 불필요
- [[Auto-Scaling]]: 자동 확장
- [[Pay-per-Use]]: 사용에 따른 비용
- [[High Availability]]: 높은 가용성
- [[Minimal Ops]]: 최소 운영

#### Services
[[AWS Services]]:
- [[Lambda]]: 함수 실행
- [[API Gateway]]: API
- [[DynamoDB]]: 데이터베이스
- [[S3]]: 스토리지
- [[SQS/SNS]]: 메시징
- [[EventBridge]]: 이벤트 라우팅

---

## Summary: Advanced Services

### [[Key Takeaways]]

✅ **AMI Management**:
- 사용자 정의 이미지
- 버전 관리
- 지역 간 복사
- 공유 및 배포

✅ **Computer Vision**:
- 이미지 분석
- 비디오 분석
- 객체 감지
- 얼굴 인식

✅ **Well-Architected**:
- 다섯 가지 기둥
- 모범 사례
- 평가 프레임워크
- 지속적 개선

✅ **Advanced Patterns**:
- 마이크로서비스
- 서버리스
- 고가용성
- 비용 최적화

---

**Playlist Source**: All AWS Videos
**Channel**: ImTechnos
**Total Advanced Videos**: 6 videos
**Coverage**: AMI, Rekognition, Well-Architected, 고급 아키텍처

---

## 🔗 Related Graphs (관련 그래프)

**AWS Core**:
- [[AWS_Fundamentals_Graph]] - 기본 개념
- [[AWS_EC2_Compute_Graph]] - EC2와 AMI
- [[AWS_Management_Infrastructure_Graph]] - 인프라 관리

**AI & Services**:
- [[AWS_SageMaker_Complete_Graph]] - ML 플랫폼
- [[AWS_Bedrock_AI_Graph]] - 생성형 AI

← 돌아가기: [[AI_Agents_Multi_Industry_Enterprise_Hub]]
