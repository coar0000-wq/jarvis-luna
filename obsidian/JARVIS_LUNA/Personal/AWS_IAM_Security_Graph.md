# AWS IAM & Security Complete - Graph View

← [[AI_Agents_Multi_Industry_Enterprise_Hub]]

## Core Concept
**AWS Identity and Access Management (IAM) 완벽 가이드**
- Playlist: All AWS Videos (69 videos)
- Channel: ImTechnos
- Goal: IAM을 통한 보안, 사용자 관리, 접근 제어 마스터

---

## Introduction to IAM Users and Groups

### [[IAM Users Basics]]
**Video 64 - Duration: ~12 minutes**

#### IAM User Components
[[User Management]]:
- [[User Account]]: 개별 계정
- [[Access Keys]]: 프로그래매틱 접근
- [[Login Credentials]]: 콘솔 로그인
- [[Attached Policies]]: 권한 정책
- [[MFA Device]]: 다중 인증
- [[Active Status]]: 활성 상태 관리

#### Creating IAM Users
[[User Creation Steps]]:
1. [[Create User]]: 사용자 생성
2. [[Set Permissions]]: 권한 설정
3. [[Attach Policies]]: 정책 연결
4. [[Generate Credentials]]: 자격증명 생성
5. [[Configure MFA]]: MFA 설정
6. [[Test Access]]: 접근 테스트

#### Access Key Management
[[Keys]]:
- [[Access Key ID]]: 공개 ID
- [[Secret Access Key]]: 비밀 키
- [[Key Rotation]]: 정기 변경
- [[Deactivation]]: 비활성화
- [[Deletion]]: 삭제
- [[Best Practices]]: 안전한 관리

### [[Introduction to IAM Users and Groups]]
**Video 65 - Duration: ~13 minutes**

#### Groups Overview
[[Group Benefits]]:
- [[Bulk Management]]: 그룹 단위 관리
- [[Policy Inheritance]]: 정책 상속
- [[Consistency]]: 일관성 유지
- [[Efficiency]]: 효율성 증대
- [[Scalability]]: 확장 가능
- [[Simplified Permissions]]: 단순화된 권한

#### Creating Groups
[[Group Setup]]:
1. [[Create Group]]: 그룹 생성
2. [[Define Purpose]]: 목적 정의
3. [[Attach Policies]]: 정책 연결
4. [[Add Users]]: 사용자 추가
5. [[Verify Permissions]]: 권한 확인
6. [[Monitor Usage]]: 사용 모니터링

#### Best Practices
[[Group Strategy]]:
- [[Role-Based]]: 역할 기반 그룹화
- [[Department-Based]]: 부서별 그룹화
- [[Project-Based]]: 프로젝트별 그룹화
- [[Function-Based]]: 기능별 그룹화
- [[Principle of Least Privilege]]: 최소 권한 원칙
- [[Regular Audits]]: 정기적 감사

---

## AWS IAM Deep Dive

### [[AWS IAM Users - Complete Hands-On]]
**Video 44 - Duration: ~18 minutes**

#### User Lifecycle Management
[[User Management]]:
- [[Planning]]: 사용자 계획
- [[Creation]]: 사용자 생성
- [[Onboarding]]: 온보딩
- [[Permission Assignment]]: 권한 할당
- [[Access Verification]]: 접근 확인
- [[Monitoring]]: 모니터링
- [[Offboarding]]: 오프보딩

#### Permission Types
[[Permission Models]]:

**Attached Policies**:
- [[Managed Policies]]: AWS 관리형
- [[Customer Managed]]: 고객 관리형
- [[Inline Policies]]: 인라인 정책
- [[Policy Attachment]]: 정책 연결

**Permission Boundaries**:
- [[Maximum Permissions]]: 최대 권한 설정
- [[Effective Permissions]]: 유효 권한
- [[Permission Reduction]]: 권한 제한

#### Practical Implementation
[[Setup Process]]:
1. [[Assess Needs]]: 필요 권한 평가
2. [[Create Policies]]: 정책 작성
3. [[Create Users]]: 사용자 생성
4. [[Attach Policies]]: 정책 연결
5. [[Test Permissions]]: 권한 테스트
6. [[Document]]: 문서화

### [[AWS IAM User Groups Hands-on]]
**Video 43 - Duration: ~16 minutes**

#### Group-Based Permission Management
[[Group Permissions]]:
- [[Policy Inheritance]]: 정책 상속
- [[Inline Group Policies]]: 인라인 그룹 정책
- [[Managed Group Policies]]: 관리형 정책
- [[Permission Evaluation]]: 권한 평가
- [[Conflict Resolution]]: 충돌 해결

#### Real-World Group Examples
[[Typical Groups]]:
- [[Developers]]: 개발자 그룹
- [[DevOps]]: DevOps 엔지니어
- [[Admin]]: 관리자
- [[Finance]]: 재무 부서
- [[Support]]: 지원 팀
- [[Analysts]]: 분석가

---

## IAM Roles & Cross-Account Access

### [[AWS IAM Roles Explained]]
**Video 36 - Duration: ~14 minutes**

#### Role Fundamentals
[[Roles Concept]]:
- [[Temporary Credentials]]: 임시 자격증명
- [[Trust Relationship]]: 신뢰 관계
- [[Assume Role]]: 역할 맡기
- [[MFA Protection]]: MFA 보호
- [[Session Duration]]: 세션 지속 시간
- [[Audit Trail]]: 감사 추적

#### Role vs User
[[Differences]]:

**Roles**:
- 임시 자격증명
- 신뢰 관계 기반
- 자동 순환
- 세션 기반

**Users**:
- 장기 자격증명
- 영구 계정
- 수동 관리
- 계정 기반

#### Role Types
[[Role Categories]]:
- [[EC2 Instance Roles]]: EC2 인스턴스
- [[Lambda Execution]]: Lambda 함수
- [[Cross-Account Roles]]: 계정 간 역할
- [[Service Roles]]: 서비스 역할
- [[Federated Roles]]: 연합 역할

### [[AWS IAM Roles Explained - Accessing AWS Services]]
**Video 37 - Duration: ~15 minutes**

#### EC2 Instance Roles
[[Instance Role Usage]]:
- [[No Hardcoding]]: 자격증명 하드코딩 불필요
- [[Automatic Rotation]]: 자동 순환
- [[Secure Access]]: 보안 접근
- [[Audit-Friendly]]: 감사 용이
- [[Best Practice]]: 권장 방식

#### Service Access Patterns
[[Access Methods]]:
1. [[Create IAM Role]]: IAM 역할 생성
2. [[Define Trust]]: 신뢰 관계 정의
3. [[Attach Policies]]: 정책 연결
4. [[Assign to Service]]: 서비스에 할당
5. [[Use Service]]: 서비스 사용
6. [[Verify Access]]: 접근 확인

#### Cross-Service Role Usage
[[Service Interactions]]:
- [[EC2 to S3]]: EC2에서 S3 접근
- [[Lambda to DynamoDB]]: Lambda에서 데이터베이스
- [[ECS to ECR]]: 컨테이너 이미지 접근
- [[SageMaker Roles]]: ML 작업
- [[Other Services]]: 기타 서비스

### [[Cross-Account Access using IAM Roles]]
**Video 35 - Duration: ~17 minutes**

#### Cross-Account Architecture
[[Account Separation]]:
- [[Multiple AWS Accounts]]: 여러 계정
- [[Account Isolation]]: 계정 격리
- [[Trust Relationship]]: 신뢰 관계 설정
- [[Role Delegation]]: 역할 위임
- [[STS AssumeRole]]: 역할 가정

#### Setting Up Cross-Account Access
[[Setup Steps]]:
1. [[Identify Accounts]]: 계정 식별
2. [[Create Role in Target]]: 대상 계정에서 역할 생성
3. [[Define Trust Policy]]: 신뢰 정책 정의
4. [[Add Permissions]]: 권한 추가
5. [[Create Role in Source]]: 원본 계정에서 역할 생성
6. [[Test Access]]: 접근 테스트

#### Use Cases
[[Cross-Account Scenarios]]:
- [[Multi-Environment]]: 다중 환경 (dev, staging, prod)
- [[Multi-Team]]: 여러 팀 협업
- [[Central Logging]]: 중앙 로깅
- [[Cost Allocation]]: 비용 할당
- [[Compliance]]: 규제 준수
- [[Delegation]]: 권한 위임

---

## IAM Security & Authentication

### [[Protect Your AWS Account - MFA]]
**Video 40 - Duration: ~12 minutes**

#### Multi-Factor Authentication Basics
[[MFA Concept]]:
- [[Two-Factor]]: 2가지 인증 방식
- [[Something You Know]]: 비밀번호
- [[Something You Have]]: 물리 기기
- [[Something You Are]]: 생체 인식
- [[Enhanced Security]]: 보안 강화
- [[Industry Standard]]: 업계 표준

#### MFA Device Types
[[MFA Options]]:
- [[Virtual MFA]]: 앱 (Google Authenticator, Authy)
- [[Hardware MFA]]: 물리 기기
- [[U2F Security Keys]]: FIDO U2F
- [[SMS]]: 문자 메시지 (권장 안 함)

#### MFA Setup for Root Account
[[Root Account Protection]]:
1. [[Access AWS Console]]: AWS 콘솔 접근
2. [[Go to IAM]]: IAM 섹션
3. [[Activate MFA]]: MFA 활성화
4. [[Choose Device]]: 기기 선택
5. [[Configure Device]]: 기기 구성
6. [[Verify Codes]]: 코드 확인
7. [[Store Backup]]: 백업 저장

#### MFA for IAM Users
[[User MFA]]:
- [[Enable for Users]]: 사용자 MFA 활성화
- [[Enforce Policy]]: MFA 필수 정책
- [[Backup Codes]]: 백업 코드 생성
- [[Device Management]]: 기기 관리
- [[Deactivation]]: 기기 제거

#### Best Practices
[[MFA Strategy]]:
- [[All Users]]: 모든 사용자에게 필수
- [[Root Account First]]: 루트 계정 우선
- [[Multiple Devices]]: 여러 기기 등록
- [[Backup Codes]]: 백업 코드 안전 보관
- [[Regular Updates]]: 정기적 검토

---

## IAM Best Practices

### [[Principle of Least Privilege]]

#### Least Privilege Definition
[[Security Principle]]:
- [[Minimal Permissions]]: 최소한의 권한
- [[Task-Specific]]: 작업 필요분만
- [[Regular Review]]: 정기적 검토
- [[Automatic Reduction]]: 자동 축소
- [[Audit Trail]]: 감사 기록
- [[Compliance Ready]]: 규제 준수

#### Implementation Strategy
[[Practical Application]]:
1. [[Identify Role]]: 역할 식별
2. [[Define Tasks]]: 작업 정의
3. [[Required Permissions]]: 필요 권한 파악
4. [[Create Policy]]: 최소 정책 작성
5. [[Regular Audits]]: 정기적 감시
6. [[Reduce Over Time]]: 시간 경과에 따른 축소

---

## Summary: IAM & Security

### [[Key Takeaways]]

✅ **IAM Users**:
- 개별 계정 관리
- 접근 키 관리
- 장기 자격증명
- 콘솔 + API 접근

✅ **IAM Groups**:
- 효율적 권한 관리
- 정책 상속
- 확장 가능
- 일관성 유지

✅ **IAM Roles**:
- 임시 자격증명
- 신뢰 기반
- 자동 순환
- 감사 기반

✅ **Cross-Account Access**:
- 계정 간 신뢰
- STS 사용
- 역할 위임
- 다중 환경

✅ **Security**:
- MFA 필수
- 최소 권한
- 정기적 감사
- 규제 준수

---

**Playlist Source**: All AWS Videos
**Channel**: ImTechnos
**Total IAM Videos**: 9 videos
**Coverage**: IAM users, groups, roles, cross-account access, MFA, best practices

---

## 🔗 Related Graphs (관련 그래프)

**AWS Core**:
- [[AWS_Fundamentals_Graph]] - 기본 개념
- [[AWS_EC2_Compute_Graph]] - EC2 역할 할당
- [[AWS_Storage_Complete_Graph]] - S3 권한

**관리 & 모니터링**:
- [[AWS_Management_Infrastructure_Graph]] - 고급 관리

← 돌아가기: [[AI_Agents_Multi_Industry_Enterprise_Hub]]
