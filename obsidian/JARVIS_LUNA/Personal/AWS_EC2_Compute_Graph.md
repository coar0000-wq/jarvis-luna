# AWS EC2 Compute Complete - Graph View

← [[AI_Agents_Multi_Industry_Enterprise_Hub]]

## Core Concept
**Amazon Elastic Compute Cloud (EC2) 완벽 가이드**
- Playlist: All AWS Videos (69 videos)
- Channel: ImTechnos
- Goal: EC2 인스턴스 생성, 관리, 최적화

---

## EC2 Fundamentals

### [[What is Amazon EC2?]]
**Video 6 - Duration: ~11 minutes**

#### EC2 Definition
[[EC2 Overview]]:
- [[Virtual Servers]]: 클라우드 기반 가상 서버
- [[On-Demand]]: 필요할 때만 사용
- [[Scalable]]: 동적 확장
- [[Flexible]]: 다양한 설정
- [[Cost-Effective]]: 비용 효율적
- [[Reliable]]: 높은 가용성
- [[Secure]]: 보안 기능

#### EC2 Benefits
[[Advantages]]:
- [[No Upfront Costs]]: 선투자 불필요
- [[Pay-as-You-Go]]: 종량제
- [[Elasticity]]: 자동 확장
- [[Flexibility]]: 다양한 인스턴스 타입
- [[Reliability]]: 높은 안정성
- [[Security]]: 내장 보안
- [[Performance]]: 높은 성능

#### EC2 Components
[[Building Blocks]]:
- [[Instances]]: 가상 서버
- [[AMI]]: 머신 이미지
- [[Instance Stores]]: 임시 스토리지
- [[EBS]]: 영구 스토리지
- [[Security Groups]]: 방화벽
- [[Key Pairs]]: SSH 키
- [[Elastic IP]]: 정적 IP

### [[EC2 Instance Types Explained]]
**Video 7 - Duration: ~13 minutes**

#### Instance Type Categories
[[Instance Families]]:

**General Purpose (M)**:
- [[Balanced Computing]]: 균형잡힌 성능
- [[Web Servers]]: 웹 서버
- [[Business Apps]]: 비즈니스 애플리케이션
- [[Small to Medium Databases]]: 소형 데이터베이스
- [[Examples]]: m6i, m5, m4

**Compute Optimized (C)**:
- [[High Performance]]: 높은 성능
- [[Batch Processing]]: 배치 처리
- [[Scientific Modeling]]: 과학 모델링
- [[Media Transcoding]]: 미디어 변환
- [[Examples]]: c6i, c5, c4

**Memory Optimized (R)**:
- [[Large Datasets]]: 대용량 데이터
- [[In-Memory Caches]]: 메모리 캐시
- [[Real-Time Processing]]: 실시간 처리
- [[High Performance Databases]]: 고성능 DB
- [[Examples]]: r6i, r5, r4

**Storage Optimized (I, D, H)**:
- [[High IOPS]]: 높은 입출력
- [[NoSQL Databases]]: NoSQL DB
- [[Data Warehousing]]: 데이터 웨어하우스
- [[Elasticsearch]]: 검색 엔진
- [[Examples]]: i3, d2, h1

**Accelerated Computing (P, G, F)**:
- [[GPU]]: 그래픽 처리
- [[ML Training]]: ML 훈련
- [[Video Encoding]]: 비디오 인코딩
- [[High Performance Computing]]: HPC
- [[Examples]]: p3, g4, f1

#### Instance Size
[[Sizing]]:
- [[Nano]]: 최소 크기
- [[Micro]]: 마이크로
- [[Small]]: 소
- [[Medium]]: 중
- [[Large]]: 대
- [[X-Large]]: 초대
- [[2X-Large]]: 극대

---

## EC2 Setup & Management

### [[Master EC2: Launch, Connect & Deploy]]
**Video 50-51 (Parts 1-2) - Duration: ~40 minutes**

#### EC2 Instance Launch
[[Launch Process]]:
1. [[Choose AMI]]: 이미지 선택
2. [[Select Type]]: 인스턴스 타입
3. [[Configure Details]]: 세부 구성
4. [[Add Storage]]: 스토리지 추가
5. [[Tag Instance]]: 태그 지정
6. [[Configure Security]]: 보안 그룹
7. [[Review & Launch]]: 검토 및 실행

#### AMI Selection
[[Image Choices]]:
- [[Amazon Linux 2]]: AWS 최적화
- [[Ubuntu]]: 인기있는 리눅스
- [[Windows Server]]: 윈도우
- [[Red Hat]]: 엔터프라이즈
- [[CentOS]]: 무료 엔터프라이즈
- [[Custom AMI]]: 사용자 정의

#### Instance Configuration
[[Configuration Steps]]:
- [[Network]]: VPC 선택
- [[Subnet]]: 서브넷 선택
- [[IAM Role]]: IAM 역할 할당
- [[Monitoring]]: CloudWatch 활성화
- [[Shutdown Behavior]]: 종료 동작
- [[Termination Protection]]: 종료 보호
- [[User Data]]: 시작 스크립트

#### Security Group Setup
[[Firewall Rules]]:
- [[Inbound Rules]]: 들어오는 트래픽
- [[Outbound Rules]]: 나가는 트래픽
- [[Protocol Types]]: SSH, HTTP, HTTPS
- [[Port Numbers]]: 포트 설정
- [[CIDR Blocks]]: IP 주소 범위
- [[Security Best Practices]]: 보안 원칙

#### Key Pair Management
[[SSH Keys]]:
1. [[Create Key Pair]]: 키 쌍 생성
2. [[Download Private Key]]: 개인 키 다운로드
3. [[Secure Storage]]: 안전한 저장
4. [[Permission Settings]]: 권한 설정 (400)
5. [[Use for SSH]]: SSH 접속
6. [[Backup Keys]]: 백업 유지

### [[Ways to Connect to EC2 Instance]]
**Video 56 - Duration: ~14 minutes**

#### Connection Methods
[[Access Approaches]]:

**SSH (Secure Shell)**:
- [[Linux/Mac]]: 기본 도구
- [[Windows]]: PuTTY, WSL
- [[Key-Based]]: 개인 키 사용
- [[Terminal Access]]: 명령줄
- [[Secure]]: 암호화 통신

**EC2 Instance Connect**:
- [[Browser-Based]]: 브라우저 통신
- [[No Key Required]]: 키 불필요
- [[Temporary Credentials]]: 임시 자격증명
- [[Linux Only]]: 리눅스 지원
- [[Convenient]]: 간편함

**AWS Systems Manager Session Manager**:
- [[IAM-Based]]: IAM 기반
- [[No Ports]]: 포트 불필요
- [[Audit Trail]]: 감사 기록
- [[Session Logging]]: 세션 로깅
- [[Secure Tunneling]]: 보안 터널

**RDP (Remote Desktop)**:
- [[Windows Instances]]: 윈도우 전용
- [[GUI Access]]: 그래픽 인터페이스
- [[Desktop Tools]]: 데스크톱 도구
- [[Full Control]]: 완벽한 제어

#### Best Practices
[[Connection Security]]:
- [[Use Latest Tools]]: 최신 도구 사용
- [[Rotate Keys]]: 키 순환
- [[Minimal Access]]: 최소 권한
- [[Disable Password]]: 비밀번호 비활성화
- [[Monitor Access]]: 접근 모니터링

### [[Managing Users Keypairs in EC2]]
**Video 59 - Duration: ~12 minutes**

#### Key Pair Lifecycle
[[Keypair Management]]:
- [[Creation]]: 키 쌍 생성
- [[Distribution]]: 배포
- [[Rotation]]: 순환
- [[Revocation]]: 취소
- [[Deletion]]: 삭제

#### User Access Setup
[[User Configuration]]:
1. [[Create Users]]: 사용자 생성
2. [[Generate Keys]]: 키 생성
3. [[Distribute Securely]]: 안전하게 배포
4. [[Set Permissions]]: 권한 설정
5. [[Test Access]]: 접근 테스트
6. [[Rotation Schedule]]: 순환 일정

### [[Multiple Keypairs for EC2]]
**Video 60 - Duration: ~13 minutes**

#### Multi-Key Strategy
[[Key Management Strategy]]:
- [[Different Users]]: 사용자별 다른 키
- [[Role-Based Keys]]: 역할별 키
- [[Service Keys]]: 서비스 키
- [[Emergency Keys]]: 긴급 키
- [[Separated Access]]: 접근 분리

#### Key Organization
[[Keypair Structure]]:
- [[Project Keys]]: 프로젝트별
- [[Environment Keys]]: 환경별 (dev, prod)
- [[Team Keys]]: 팀별
- [[Rotation Schedule]]: 순환 일정
- [[Backup Strategy]]: 백업 전략

---

## EC2 Storage & Data

### [[Amazon EBS - Deep Dive]]
**Video 46-47 (Parts 1-2) - Duration: ~28 minutes**

#### EBS Fundamentals
[[EBS Concept]]:
- [[Block Storage]]: 블록 스토리지
- [[Persistent]]: 영구 저장
- [[Network Attached]]: 네트워크 연결
- [[Snapshots]]: 스냅샷 지원
- [[Encryption]]: 암호화 가능
- [[Replication]]: 자동 복제

#### EBS Volume Types
[[Volume Categories]]:

**General Purpose (gp3, gp2)**:
- [[Balanced]]: 균형잡힌 성능
- [[Web Applications]]: 웹 애플리케이션
- [[Small Databases]]: 소형 DB
- [[Development]]: 개발 환경

**Provisioned IOPS (io2, io1)**:
- [[High Performance]]: 높은 성능
- [[Databases]]: 데이터베이스
- [[Mission-Critical]]: 미션 크리티컬
- [[Low Latency]]: 낮은 지연

**Throughput Optimized (st1)**:
- [[Sequential Access]]: 순차 접근
- [[Big Data]]: 빅데이터
- [[Streaming]]: 스트리밍

**Cold HDD (sc1)**:
- [[Infrequent]]: 드문 접근
- [[Archive]]: 아카이브
- [[Low Cost]]: 저비용

#### EBS Operations
[[Management Tasks]]:
- [[Create Volume]]: 볼륨 생성
- [[Attach Volume]]: 인스턴스 연결
- [[Resize Volume]]: 크기 조정
- [[Create Snapshot]]: 스냅샷 생성
- [[Restore from Snapshot]]: 복구
- [[Delete Volume]]: 삭제

### [[AWS EC2 Instance Store vs EBS]]
**Video 58 - Duration: ~11 minutes**

#### Instance Store
[[Characteristics]]:
- [[Temporary]]: 임시 저장
- [[High Performance]]: 높은 성능
- [[No Cost]]: 추가 비용 없음
- [[Lost on Shutdown]]: 종료 시 삭제
- [[Not Persistent]]: 영구 보관 불가
- [[Limited Availability]]: 제한된 가용성

#### EBS Comparison
[[Differences]]:

| Feature | EBS | Instance Store |
|---------|-----|-----------------|
| Persistence | Persistent | Temporary |
| Performance | Good | Very High |
| Cost | Additional | Included |
| Shutdown | Retained | Lost |
| Snapshots | Supported | Not Supported |
| Use Cases | General | Caching, Temp |

#### Use Case Selection
[[When to Use]]:
- **EBS**: 데이터 보관 필요
- **Instance Store**: 캐시, 임시 데이터

### [[AWS EBS Volume Types]]
**Video 57 - Duration: ~10 minutes**

#### Volume Type Comparison
[[Detailed Comparison]]:
- [[IOPS]]: 입출력 성능
- [[Throughput]]: 처리량
- [[Cost]]: 비용
- [[Durability]]: 내구성
- [[Replication]]: 복제
- [[Snapshots]]: 스냅샷

---

## EC2 Advanced Topics

### [[Mastering AWS AMIs]]
**Video 34-35 (Parts 1-2) - Duration: ~30 minutes**

#### What is an AMI?
[[AMI Definition]]:
- [[Machine Image]]: 머신 이미지
- [[Template]]: 인스턴스 템플릿
- [[Includes]]: OS, 앱, 설정
- [[Reusable]]: 재사용 가능
- [[Shareable]]: 공유 가능
- [[Region-Specific]]: 지역별

#### Creating Custom AMI
[[AMI Creation Steps]]:
1. [[Launch Instance]]: 인스턴스 시작
2. [[Configure Instance]]: 설정
3. [[Install Software]]: 소프트웨어 설치
4. [[Optimize]]: 최적화
5. [[Create AMI]]: AMI 생성
6. [[Test AMI]]: 테스트
7. [[Share if Needed]]: 필요시 공유

#### Using Custom AMI
[[Deployment]]:
- [[Consistent Deployments]]: 일관된 배포
- [[Faster Launch]]: 빠른 시작
- [[Configuration Management]]: 구성 관리
- [[Version Control]]: 버전 관리

#### Copying & Sharing AMI
[[Distribution]]:
- [[Copy to Regions]]: 지역 간 복사
- [[Make Public]]: 공개
- [[Share with Accounts]]: 계정 공유
- [[Encryption]]: 암호화 복사

---

## Summary: EC2 Complete

### [[Key Takeaways]]

✅ **EC2 Instances**:
- 클라우드 기반 가상 서버
- 다양한 인스턴스 타입
- 온디맨드 방식
- 자동 확장

✅ **Launch & Management**:
- AMI 선택
- 보안 그룹 설정
- 키 쌍 관리
- IAM 역할 할당

✅ **Storage Options**:
- EBS: 영구 저장
- Instance Store: 임시 저장
- 스냅샷: 백업
- 자동 복제

✅ **Connectivity**:
- SSH 접속
- Instance Connect
- Session Manager
- RDP (Windows)

✅ **Advanced**:
- Custom AMI
- 키 순환
- 다중 키 관리
- 성능 최적화

---

**Playlist Source**: All AWS Videos
**Channel**: ImTechnos
**Total EC2 Videos**: 12 videos
**Coverage**: EC2 인스턴스, 타입, 연결, 스토리지, AMI, 고급 주제

---

## 🔗 Related Graphs (관련 그래프)

**AWS Core**:
- [[AWS_Fundamentals_Graph]] - 기본 개념
- [[AWS_IAM_Security_Graph]] - IAM 역할
- [[AWS_Storage_Complete_Graph]] - EBS 깊이있는 학습

**인프라**:
- [[AWS_Management_Infrastructure_Graph]] - CloudFormation, Systems Manager

← 돌아가기: [[AI_Agents_Multi_Industry_Enterprise_Hub]]
