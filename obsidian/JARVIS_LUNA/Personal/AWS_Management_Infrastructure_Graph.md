# AWS Management & Infrastructure - Graph View

← [[AI_Agents_Multi_Industry_Enterprise_Hub]]

## Core Concept
**AWS 인프라 관리 및 자동화 완벽 가이드**
- Playlist: All AWS Videos (69 videos)
- Channel: ImTechnos
- Goal: CloudFormation, Systems Manager, Config를 통한 자동화 및 관리

---

## AWS CloudFormation

### [[Introduction to CloudFormation]]
**Video 54 - Duration: ~12 minutes**

#### CloudFormation Basics
[[IaC Concept]]:
- [[Infrastructure as Code]]: 코드로 인프라
- [[Declarative]]: 선언형 정의
- [[Version Control]]: 버전 관리
- [[Repeatable]]: 반복 가능
- [[Automated]]: 자동화
- [[Scalable]]: 확장 가능
- [[Compliant]]: 규제 준수

#### CloudFormation Benefits
[[Advantages]]:
- [[Speed]]: 빠른 배포
- [[Consistency]]: 일관성
- [[Version Control]]: 변경 추적
- [[Rollback]]: 롤백 가능
- [[Cost Tracking]]: 비용 추적
- [[Drift Detection]]: 변경 감지
- [[Stack Management]]: 스택 관리

#### CloudFormation Components
[[Building Blocks]]:
- [[Templates]]: CloudFormation 템플릿
- [[Stacks]]: 배포된 리소스
- [[Change Sets]]: 변경 미리보기
- [[Parameters]]: 매개변수
- [[Outputs]]: 출력값
- [[Metadata]]: 메타데이터
- [[Conditions]]: 조건

### [[CloudFormation Templates Explained]]
**Video 53 - Duration: ~14 minutes**

#### Template Structure
[[JSON/YAML Format]]:

```
AWSTemplateFormatVersion: '2010-09-09'
Description: Template Description
Parameters:
  # Input parameters
Resources:
  # AWS resources
Outputs:
  # Output values
```

#### Template Components
[[Elements]]:

**Resources Section**:
- [[EC2 Instances]]: 인스턴스
- [[S3 Buckets]]: 버킷
- [[Databases]]: 데이터베이스
- [[Networks]]: 네트워킹
- [[IAM Roles]]: 역할

**Parameters Section**:
- [[Input Values]]: 입력값
- [[Default Values]]: 기본값
- [[Type Validation]]: 타입 검증
- [[Descriptions]]: 설명

**Outputs Section**:
- [[Return Values]]: 반환값
- [[Stack Outputs]]: 스택 출력
- [[Cross-Stack References]]: 참조

#### Template Validation
[[Best Practices]]:
- [[JSON Linting]]: JSON 검증
- [[Syntax Validation]]: 문법 검증
- [[Security Best Practices]]: 보안
- [[Cost Estimation]]: 비용 추정
- [[Change Sets]]: 변경 검증

### [[AWS CloudFormation Hands-On]]
**Video 52 - Duration: ~16 minutes**

#### Practical Implementation
[[Hands-On Process]]:
1. [[Write Template]]: 템플릿 작성
2. [[Validate Template]]: 템플릿 검증
3. [[Create Stack]]: 스택 생성
4. [[Monitor Creation]]: 생성 모니터링
5. [[Verify Resources]]: 리소스 확인
6. [[Test Resources]]: 테스트
7. [[Update Stack]]: 스택 업데이트
8. [[Delete Stack]]: 스택 삭제

#### Stack Operations
[[Management Tasks]]:
- [[Create]]: 스택 생성
- [[Update]]: 스택 업데이트
- [[Review Changes]]: 변경 검토
- [[Delete]]: 스택 삭제
- [[Drift Detection]]: 변경 감지
- [[Events Tracking]]: 이벤트 추적

---

## AWS Systems Manager

### [[Systems Manager Run Command]]
**Video 51 - Duration: ~14 minutes**

#### Run Command Overview
[[Capabilities]]:
- [[Remote Execution]]: 원격 실행
- [[No SSH Required]]: SSH 불필요
- [[Audit Trail]]: 감사 추적
- [[Output Logging]]: 출력 로깅
- [[Windows & Linux]]: 모두 지원
- [[Batch Operations]]: 일괄 작업
- [[Error Handling]]: 오류 처리

#### Using Run Command
[[Process]]:
1. [[Select Instances]]: 인스턴스 선택
2. [[Choose Document]]: 문서 선택
3. [[Set Parameters]]: 매개변수 설정
4. [[Execute]]: 실행
5. [[Monitor Progress]]: 진행 모니터링
6. [[Review Output]]: 출력 검토
7. [[Save Results]]: 결과 저장

#### Document Types
[[Available Documents]]:
- [[AWS Documents]]: AWS 제공 문서
- [[Custom Documents]]: 사용자 정의 문서
- [[Automation]]: 자동화
- [[Command]]: 명령
- [[Package]]: 패키지
- [[Maintenance Window]]: 유지보수

### [[Systems Manager Parameter Store]]
**Video 52 - Duration: ~15 minutes**

#### Parameter Store Overview
[[Configuration Management]]:
- [[Centralized]]: 중앙 집중식
- [[Secure]]: 보안
- [[Versioning]]: 버전 관리
- [[Access Control]]: 접근 제어
- [[Audit Trail]]: 감사 추적
- [[TTL]]: 만료 시간

#### Parameter Types
[[Storage Options]]:

**Standard Parameters**:
- [[Simple]]: 단순한 구성
- [[No Cost]]: 추가 비용 없음
- [[4 KB Limit]]: 크기 제한
- [[No Advanced Features]]: 기본 기능

**Advanced Parameters**:
- [[Complex]]: 복잡한 구성
- [[8 KB Limit]]: 더 큼
- [[Advanced Features]]: 고급 기능
- [[Additional Cost]]: 추가 비용

#### Using Parameters
[[Access Methods]]:
- [[AWS Console]]: 콘솔 접근
- [[AWS CLI]]: CLI 사용
- [[SDK]]: 프로그래매틱 접근
- [[CloudFormation]]: 템플릿에서
- [[Lambda Functions]]: Lambda 함수
- [[EC2 User Data]]: 시작 스크립트

### [[Systems Manager Inventory]]
**Video 41 - Duration: ~13 minutes**

#### Inventory Capabilities
[[Collection]]:
- [[Instance Information]]: 인스턴스 정보
- [[Software]]: 설치된 소프트웨어
- [[Patches]]: 패치 상태
- [[Applications]]: 애플리케이션
- [[Custom Data]]: 사용자 정의 데이터
- [[Metadata]]: 메타데이터

#### Inventory Setup
[[Configuration]]:
1. [[Enable Inventory]]: 인벤토리 활성화
2. [[Select Instances]]: 인스턴스 선택
3. [[Choose Items]]: 수집할 항목 선택
4. [[Set Schedule]]: 수집 일정
5. [[Configure Storage]]: 저장소 설정
6. [[Start Collection]]: 수집 시작

#### Inventory Queries
[[Data Analysis]]:
- [[Search Data]]: 데이터 검색
- [[Filter Results]]: 결과 필터
- [[Export Data]]: 데이터 내보내기
- [[Report Generation]]: 보고서 생성
- [[Compliance Checking]]: 규제 준수 확인

### [[Systems Manager Documents - Overview]]
**Video 48 - Duration: ~12 minutes**

#### Document Types
[[Document Categories]]:

**Command Documents**:
- [[Shell Commands]]: 셸 명령
- [[PowerShell]]: PowerShell 스크립트
- [[Custom Scripts]]: 사용자 정의

**Automation Documents**:
- [[Workflow]]: 워크플로우
- [[Multi-Step]]: 다중 단계
- [[Conditional Logic]]: 조건부 로직

**Maintenance Documents**:
- [[Scheduled]]: 예약된 작업
- [[Recurring]]: 반복 작업
- [[Maintenance Windows]]: 유지보수 시간

#### Creating Documents
[[Document Creation]]:
1. [[Write Document]]: 문서 작성
2. [[Define Steps]]: 단계 정의
3. [[Set Parameters]]: 매개변수
4. [[Add Outputs]]: 출력 정의
5. [[Validate]]: 검증
6. [[Publish]]: 발행
7. [[Version Control]]: 버전 관리

### [[Systems Manager OpsCenter]]
**Video 28 - Duration: ~14 minutes**

#### OpsCenter Overview
[[Capabilities]]:
- [[Centralized]]: 중앙 집중식
- [[Operational Issues]]: 운영 문제 관리
- [[Incident Tracking]]: 사건 추적
- [[Automation]]: 자동 대응
- [[Integration]]: 다른 서비스와 통합

#### OpsItems
[[Issue Management]]:
- [[Create OpsItem]]: 문제 생성
- [[Status Tracking]]: 상태 추적
- [[Assignment]]: 담당자 지정
- [[Related Items]]: 관련 항목
- [[Automation Runbooks]]: 자동화 실행책

### [[Systems Manager Incident Manager]]
**Video 27 - Duration: ~15 minutes**

#### Incident Management
[[Features]]:
- [[Incident Detection]]: 사건 감지
- [[Automatic Response]]: 자동 대응
- [[On-Call Management]]: 온콜 관리
- [[Escalation]]: 상향 보고
- [[Communication]]: 통신
- [[Post-Mortem]]: 사후 분석

---

## AWS Config

### [[AWS Config Explained]]
**Video 55 - Duration: ~13 minutes**

#### Config Overview
[[Configuration Management]]:
- [[Resource Tracking]]: 리소스 추적
- [[Change History]]: 변경 이력
- [[Compliance Rules]]: 규제 규칙
- [[Automated Responses]]: 자동 대응
- [[Audit Trail]]: 감사 추적
- [[Graphical View]]: 그래픽 보기

#### Config Rules
[[Compliance Rules]]:

**AWS Managed Rules**:
- [[Pre-built Rules]]: 사전 구축 규칙
- [[Best Practices]]: 모범 사례
- [[No Maintenance]]: 유지보수 불필요
- [[Easy Deploy]]: 쉬운 배포

**Custom Rules**:
- [[Lambda-Based]]: Lambda 기반
- [[Custom Logic]]: 사용자 정의 로직
- [[Complex Rules]]: 복잡한 규칙
- [[Full Control]]: 완벽한 제어

#### Config Setup
[[Implementation]]:
1. [[Enable Config]]: Config 활성화
2. [[Create Rules]]: 규칙 생성
3. [[Monitor Compliance]]: 규제 준수 모니터링
4. [[Set Remediation]]: 자동 복구 설정
5. [[Review Reports]]: 보고서 검토
6. [[Optimize Rules]]: 규칙 최적화

---

## AWS Organizations

### [[AWS Organizations Explained]]
**Video 32 - Duration: ~14 minutes**

#### Organizations Overview
[[Multi-Account Management]]:
- [[Centralized]]: 중앙 관리
- [[Multiple Accounts]]: 다중 계정
- [[Hierarchy]]: 계층 구조
- [[Policy Control]]: 정책 제어
- [[Cost Allocation]]: 비용 할당
- [[Simplified Billing]]: 통합 청구

#### Organizational Units (OUs)
[[Structure]]:
- [[Root]]: 루트 OA
- [[Environment OUs]]: 환경별 (dev, prod)
- [[Department OUs]]: 부서별
- [[Project OUs]]: 프로젝트별
- [[Nesting]]: 중첩 가능

#### Policies
[[Policy Types]]:
- [[Service Control Policies]]: 서비스 제어
- [[Tag Policies]]: 태그 정책
- [[Backup Policies]]: 백업 정책
- [[AI Services Opt-Out]]: AI 서비스 거부

---

## Summary: Management & Infrastructure

### [[Key Takeaways]]

✅ **CloudFormation**:
- Infrastructure as Code
- 템플릿 기반 배포
- 버전 관리
- 자동 롤백

✅ **Systems Manager**:
- 원격 명령 실행
- 매개변수 관리
- 인벤토리 수집
- 자동화 문서

✅ **AWS Config**:
- 리소스 추적
- 규제 준수
- 변경 이력
- 자동 복구

✅ **Organizations**:
- 다중 계정 관리
- 중앙 정책
- 비용 할당
- 계층 구조

---

**Playlist Source**: All AWS Videos
**Channel**: ImTechnos
**Total Management Videos**: 9 videos
**Coverage**: CloudFormation, Systems Manager, Config, Organizations

---

## 🔗 Related Graphs (관련 그래프)

**AWS Core**:
- [[AWS_Fundamentals_Graph]] - 기본 개념
- [[AWS_IAM_Security_Graph]] - 접근 제어
- [[AWS_EC2_Compute_Graph]] - 인스턴스 관리

**고급 토픽**:
- [[AWS_SageMaker_Complete_Graph]] - ML 인프라

← 돌아가기: [[AI_Agents_Multi_Industry_Enterprise_Hub]]
