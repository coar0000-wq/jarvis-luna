# AWS Cloud Fundamentals - Graph View

← [[AI_Agents_Multi_Industry_Enterprise_Hub]]

## Core Concept
**AWS 클라우드 컴퓨팅 기초**
- Playlist: All AWS Videos (69 videos)
- Channel: ImTechnos
- Goal: AWS 클라우드 컴퓨팅의 기본 개념, 모델, 가격 체계 이해

---

## Introduction to Cloud Computing

### [[What is Cloud Computing?]]
**Video 12 - Duration: ~10 minutes**

#### Cloud Computing Basics
[[Cloud Definition]]:
- [[On-Demand Resources]]: 필요할 때 리소스 사용
- [[Pay-as-You-Go]]: 사용한 만큼 비용 지불
- [[Scalability]]: 자동 확장/축소
- [[Accessibility]]: 인터넷 연결만으로 접근
- [[Reliability]]: 높은 가용성
- [[Security]]: 내장된 보안
- [[Flexibility]]: 다양한 서비스 조합
- [[Cost Efficiency]]: CAPEX → OPEX 전환

#### Real-World Cloud Examples
[[Cloud Applications]]:
- [[Email Services]]: Gmail, Outlook
- [[Storage Services]]: Google Drive, Dropbox
- [[Video Streaming]]: Netflix, YouTube
- [[Social Media]]: Facebook, Instagram
- [[Productivity Tools]]: Microsoft 365, Google Workspace
- [[Banking Services]]: Online banking
- [[E-Commerce]]: Amazon, eBay
- [[Collaboration Tools]]: Slack, Teams

---

## Virtualization & Cloud Models

### [[Virtualization Explained]]
**Video 63 - Duration: ~15 minutes**

#### What is Virtualization?
[[Virtualization Concept]]:
- [[Physical to Virtual]]: 물리 서버 → 가상 인스턴스
- [[Resource Sharing]]: 한 서버에서 여러 가상 환경
- [[Isolation]]: 환경 간 격리
- [[Efficiency]]: 리소스 활용률 극대화
- [[Flexibility]]: 빠른 프로비저닝
- [[Cost Reduction]]: 하드웨어 비용 절감

#### Types of Virtualization
[[Virtualization Models]]:
- [[Server Virtualization]]: 서버 가상화
- [[Storage Virtualization]]: 스토리지 추상화
- [[Network Virtualization]]: 네트워크 가상화
- [[Desktop Virtualization]]: 데스크톱 환경
- [[Application Virtualization]]: 앱 가상화
- [[Container Virtualization]]: 컨테이너 기술

### [[Cloud Deployment Models]]
**Video 2 - Duration: ~12 minutes**

#### Types of Cloud
[[Cloud Models]]:

**Public Cloud**:
- [[Third-Party Providers]]: AWS, Azure, GCP
- [[Multi-Tenant]]: 여러 고객 공유
- [[Cost Effective]]: 비용 효율적
- [[Scalable]]: 무제한 확장
- [[Security Shared]]: 공급자가 담당
- [[Best For]]: 대부분의 기업

**Private Cloud**:
- [[On-Premises]]: 자신의 데이터센터
- [[Single-Tenant]]: 전용 리소스
- [[Full Control]]: 완전 제어
- [[Higher Cost]]: 높은 초기 비용
- [[Compliance]]: 규제 준수
- [[Best For]]: 금융, 의료, 정부

**Hybrid Cloud**:
- [[Mixed Model]]: Public + Private 조합
- [[Flexibility]]: 최상의 선택
- [[Complex]]: 복잡한 관리
- [[Best For]]: 과도기 상황

---

## AWS Overview & Architecture

### [[AWS Infrastructure Explained]]
**Video 3 - Duration: ~14 minutes**

#### AWS Global Infrastructure
[[AWS Structure]]:
- [[Regions]]: 지역별 데이터센터
- [[Availability Zones]]: 가용 영역 (AZ)
- [[Edge Locations]]: 엣지 로케이션
- [[Local Zones]]: 로컬 영역
- [[Global Services]]: 전 세계 서비스

#### Regions Overview
[[Regions Details]]:
- [[Geographic Distribution]]: 전 세계 30+ 지역
- [[Data Residency]]: 데이터 위치 제어
- [[Compliance]]: 지역 규제 준수
- [[Latency]]: 지역별 지연 최소화
- [[Disaster Recovery]]: 재해 복구
- [[High Availability]]: 가용성 향상

#### Availability Zones
[[AZ Characteristics]]:
- [[Multiple Data Centers]]: 각 지역 3+ AZ
- [[Independent Power]]: 독립적 전력
- [[Network Isolation]]: 네트워크 격리
- [[Low Latency]]: 낮은 지연
- [[Redundancy]]: 중복성
- [[Failover]]: 자동 장애조치

### [[AWS Security Model]]
**Video 3 Part 2 - Duration: ~16 minutes**

#### Security Architecture
[[AWS Security]]:
- [[Infrastructure Security]]: 물리 보안
- [[Perimeter Security]]: 경계 보안
- [[Access Control]]: 접근 제어
- [[Encryption]]: 암호화
- [[Monitoring]]: 모니터링
- [[Incident Response]]: 사건 대응
- [[Compliance]]: 규제 준수

---

## AWS Pricing & Cost Management

### [[AWS Pricing Model]]
**Video 4 - Duration: ~13 minutes**

#### How AWS Pricing Works
[[Pricing Principles]]:
- [[Pay-As-You-Go]]: 종량제
- [[No Upfront Costs]]: 선투자 없음
- [[No Long-term Contracts]]: 약정 없음
- [[Reserve Capacity]]: 예약 인스턴스
- [[Spot Instances]]: 스팟 가격
- [[Data Transfer]]: 데이터 전송료
- [[Storage]]: 스토리지 요금

#### Service-Specific Pricing
[[Pricing Examples]]:
- [[EC2]]: 시간 단위 계산
- [[S3]]: 스토리지 + 요청료
- [[Lambda]]: 요청 + 실행 시간
- [[Database]]: 인스턴스 유형별
- [[Data Transfer]]: 외부 전송료
- [[Support]]: 지원 플랜

#### Cost Optimization
[[Saving Strategies]]:
- [[Reserved Instances]]: 예약 할인 (1-3년)
- [[Spot Instances]]: 스팟 할인 (70% 저렴)
- [[Savings Plans]]: 유연한 약정
- [[Right Sizing]]: 적절한 크기
- [[Unused Resources]]: 미사용 리소스 정리
- [[Auto Scaling]]: 자동 조정

### [[AWS Billing & Cost Management]]
**Video 65 - Duration: ~12 minutes**

#### Billing Basics
[[Cost Tracking]]:
- [[Cost Explorer]]: 비용 분석
- [[Billing Dashboard]]: 청구 대시보드
- [[Cost Budgets]]: 예산 설정
- [[Alerts]]: 비용 알림
- [[Tags]]: 비용 태그
- [[Reports]]: 청구 보고서

#### Cost Management Tools
[[Tools Available]]:
- [[AWS Cost Explorer]]: 시각화
- [[AWS Budgets]]: 예산 관리
- [[AWS Cost Anomaly Detection]]: 이상 감지
- [[Trusted Advisor]]: 최적화 조언
- [[Reserved Capacity Planner]]: 예약 계획
- [[Pricing Calculator]]: 비용 추정

---

## AWS Shared Responsibility Model

### [[Shared Responsibility Explained]]
**Video 66 - Duration: ~11 minutes**

#### Responsibility Division
[[AWS Responsibilities]]:
- [[Infrastructure]]: 물리 데이터센터
- [[Network]]: 네트워크 인프라
- [[Hypervisor]]: 가상화 기술
- [[Power & Cooling]]: 전력 냉각
- [[Managed Services]]: 일부 관리 서비스

#### Customer Responsibilities
[[Your Responsibilities]]:
- [[Data]]: 데이터 보안
- [[Access Management]]: IAM 설정
- [[Encryption]]: 암호화 구성
- [[Compliance]]: 규제 준수
- [[Patch Management]]: 패치 적용
- [[Monitoring]]: 모니터링 설정
- [[Configuration]]: 서비스 구성

#### Service Type Variation
[[Responsibility by Service Type]]:

**Infrastructure as a Service (IaaS)**:
- [[Customer Controls]]: OS, 미들웨어, 앱
- [[AWS Controls]]: 인프라, 가상화

**Platform as a Service (PaaS)**:
- [[Customer Controls]]: 데이터, 애플리케이션
- [[AWS Controls]]: 플랫폼, 인프라

**Software as a Service (SaaS)**:
- [[Customer Controls]]: 데이터만
- [[AWS Controls]]: 대부분의 것

---

## IAM Fundamentals

### [[Introduction to IAM]]
**Video 5 - Duration: ~10 minutes**

#### IAM Basics
[[IAM Concept]]:
- [[Identity Management]]: 신원 관리
- [[Access Control]]: 접근 제어
- [[Permissions]]: 권한 관리
- [[Authentication]]: 인증
- [[Authorization]]: 승인
- [[Audit]]: 감사 추적
- [[MFA]]: 다중 인증

#### IAM Users and Groups
[[IAM Structure]]:
- [[Root Account]]: 루트 계정 (최상위)
- [[IAM Users]]: 개별 사용자
- [[Groups]]: 사용자 그룹
- [[Roles]]: 역할
- [[Policies]]: 정책
- [[Permissions]]: 권한

### [[JSON Policies]]
**Video 67 - Duration: ~14 minutes**

#### Policy Structure
[[JSON Format]]:
```
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow/Deny",
      "Action": "service:action",
      "Resource": "arn:aws:..."
    }
  ]
}
```

#### Policy Elements
[[Components]]:
- [[Version]]: 정책 버전
- [[Statement]]: 명령문 배열
- [[Effect]]: Allow 또는 Deny
- [[Action]]: 수행 가능한 작업
- [[Resource]]: 대상 리소스
- [[Principal]]: 주체 (역할/사용자)
- [[Condition]]: 조건

---

## Summary: AWS Fundamentals

### [[Key Takeaways]]

✅ **Cloud Computing**:
- 온디맨드 리소스
- 종량제 모델
- 자동 확장
- 높은 신뢰성

✅ **AWS Infrastructure**:
- 글로벌 인프라
- 여러 지역과 AZ
- 엣지 로케이션
- 높은 가용성

✅ **Pricing**:
- 선투자 없음
- 사용한 만큼 지불
- 예약 할인 가능
- 스팟 인스턴스 활용

✅ **Security**:
- 공동 책임 모델
- IAM으로 접근 제어
- 암호화 지원
- 감사 기능

✅ **Cost Management**:
- 비용 추적 도구
- 예산 알림
- 이상 감지
- 최적화 조언

---

**Playlist Source**: All AWS Videos
**Channel**: ImTechnos
**Total Videos in Fundamentals**: 12 videos
**Coverage**: Cloud basics, virtualization, AWS infrastructure, pricing, security, IAM

---

## 🔗 Related Graphs (관련 그래프)

**AWS 인프라**:
- [[AWS_IAM_Security_Graph]] - IAM 심화
- [[AWS_EC2_Compute_Graph]] - EC2 컴퓨팅
- [[AWS_Storage_Complete_Graph]] - 스토리지 솔루션

**AWS 관리**:
- [[AWS_Management_Infrastructure_Graph]] - 관리 도구

**AI & ML**:
- [[AWS_SageMaker_Complete_Graph]] - ML 플랫폼
- [[AWS_Bedrock_AI_Graph]] - LLM 서비스

← 돌아가기: [[AI_Agents_Multi_Industry_Enterprise_Hub]]
