# AWS Storage Solutions Complete - Graph View

← [[AI_Agents_Multi_Industry_Enterprise_Hub]]

## Core Concept
**AWS 스토리지 서비스 완벽 가이드**
- Playlist: All AWS Videos (69 videos)
- Channel: ImTechnos
- Goal: S3, EBS, EFS 등 모든 스토리지 솔루션 마스터

---

## Amazon S3 - Simple Storage Service

### [[Introduction to AWS S3]]
**Video 61 - Duration: ~12 minutes**

#### S3 Fundamentals
[[S3 Overview]]:
- [[Object Storage]]: 객체 저장소
- [[Scalable]]: 무제한 확장
- [[Durable]]: 99.999999999% 내구성
- [[Accessible]]: 어디서나 접근
- [[Cost-Effective]]: 비용 효율적
- [[Simple API]]: 간단한 인터페이스
- [[Built-in Security]]: 내장 보안

#### S3 Concepts
[[Core Components]]:
- [[Buckets]]: 최상위 컨테이너
- [[Objects]]: 저장된 데이터
- [[Keys]]: 객체 이름
- [[Metadata]]: 데이터 정보
- [[Versions]]: 버전 관리
- [[Access Control]]: 접근 제어
- [[Encryption]]: 암호화

#### S3 Use Cases
[[Applications]]:
- [[Static Websites]]: 정적 웹사이트
- [[Backup & Archive]]: 백업 및 아카이브
- [[Big Data Analytics]]: 빅데이터 분석
- [[Data Lakes]]: 데이터 레이크
- [[Media Storage]]: 미디어 저장
- [[Log Files]]: 로그 파일
- [[Database Backups]]: 데이터베이스 백업

### [[Amazon S3 - Create, Upload, Versioning]]
**Video 30 - Duration: ~14 minutes**

#### Bucket Creation
[[Bucket Setup]]:
1. [[Create Bucket]]: 버킷 생성
2. [[Naming Rules]]: 이름 규칙
3. [[Region Selection]]: 지역 선택
4. [[Block Public Access]]: 공개 접근 차단
5. [[Versioning Setup]]: 버전 관리 설정
6. [[Configure Settings]]: 설정 구성

#### Object Upload
[[Upload Process]]:
- [[Console Upload]]: 콘솔을 통한 업로드
- [[Drag & Drop]]: 드래그 앤 드롭
- [[Batch Upload]]: 일괄 업로드
- [[CLI Upload]]: AWS CLI 사용
- [[SDK Upload]]: 프로그래매틱 업로드
- [[Multipart Upload]]: 대용량 파일

#### Versioning Benefits
[[Version Control]]:
- [[Track Changes]]: 변경 추적
- [[Recover Data]]: 데이터 복구
- [[Compliance]]: 규제 준수
- [[Archive Versions]]: 버전 보관
- [[Rollback]]: 이전 버전으로 되돌리기
- [[Delete Protection]]: 삭제 보호

### [[Amazon S3 Tags, Encryption & Storage Classes]]
**Video 29 - Duration: ~13 minutes**

#### S3 Tags
[[Tagging System]]:
- [[Key-Value Pairs]]: 키-값 쌍
- [[Organize Objects]]: 객체 정리
- [[Cost Allocation]]: 비용 할당
- [[Access Control]]: 접근 제어
- [[Automation]]: 자동화 트리거
- [[Lifecycle Policies]]: 생명주기 정책

#### S3 Encryption
[[Encryption Options]]:

**Server-Side Encryption**:
- [[SSE-S3]]: AWS 관리 키
- [[SSE-KMS]]: KMS 키 사용
- [[SSE-C]]: 고객 제공 키
- [[Transparent]]: 투명한 암호화

**Client-Side Encryption**:
- [[Pre-Upload]]: 업로드 전 암호화
- [[Full Control]]: 완전한 제어
- [[Performance Impact]]: 성능 영향
- [[Key Management]]: 키 관리

#### S3 Storage Classes
[[Storage Tiers]]:

**S3 Standard**:
- [[General Purpose]]: 범용
- [[Frequent Access]]: 빈번한 접근
- [[High Performance]]: 높은 성능
- [[Highest Cost]]: 높은 비용

**S3 Intelligent-Tiering**:
- [[Automatic]]: 자동 분류
- [[Cost Optimization]]: 비용 최적화
- [[Access Patterns]]: 접근 패턴 분석
- [[No Retrieval Fees]]: 검색료 없음

**S3 Standard-IA**:
- [[Infrequent Access]]: 드문 접근
- [[Lower Cost]]: 낮은 비용
- [[Retrieval Fee]]: 검색료 있음
- [[30-day Minimum]]: 30일 최소

**S3 Glacier**:
- [[Archive]]: 아카이브
- [[Long-term Storage]]: 장기 보관
- [[Lowest Cost]]: 가장 저렴
- [[Slow Retrieval]]: 느린 검색

**S3 Glacier Deep Archive**:
- [[Rare Access]]: 매우 드문 접근
- [[Cheapest]]: 가장 저렴
- [[12-hour Retrieval]]: 12시간 검색
- [[Compliance Archive]]: 규제 아카이브

---

## EBS - Elastic Block Store

### [[Amazon EBS Deep Dive]]
**Video 46-47 (Parts 1-2) - Duration: ~28 minutes**

#### EBS Overview
[[EBS Characteristics]]:
- [[Block Storage]]: 블록 스토리지
- [[Network Attached]]: 네트워크 연결
- [[Persistent]]: 영구 저장
- [[Replicated]]: 자동 복제
- [[Snapshots]]: 스냅샷 지원
- [[Encryption]]: 암호화 지원
- [[Performance]]: 높은 성능

#### EBS Volume Operations
[[Management Tasks]]:
1. [[Create Volume]]: 볼륨 생성
2. [[Attach to Instance]]: 인스턴스 연결
3. [[Format Volume]]: 포맷
4. [[Mount]]: 마운트
5. [[Use]]: 사용
6. [[Create Snapshot]]: 스냅샷 생성
7. [[Restore]]: 복구

#### Volume Type Selection
[[Type Comparison]]:

| Type | IOPS | Throughput | Cost | Best For |
|------|------|-----------|------|----------|
| gp3 | 3,000-16,000 | High | Low | General Purpose |
| io2 | 64,000+ | High | High | Databases |
| st1 | 500 | 500 MB/s | Medium | Streaming |
| sc1 | 250 | 250 MB/s | Low | Archive |

### [[AWS EC2 Instance Store Volumes]]
**Video 39 - Duration: ~12 minutes**

#### Instance Store Characteristics
[[Properties]]:
- [[Ephemeral]]: 임시
- [[High IOPS]]: 높은 입출력
- [[No Additional Cost]]: 추가 비용 없음
- [[Lost on Shutdown]]: 종료 시 삭제
- [[Limited Durability]]: 제한된 내구성
- [[Not Suitable for Critical Data]]: 중요 데이터 불가

#### Use Cases
[[When to Use]]:
- [[Caching]]: 캐싱
- [[Temporary Data]]: 임시 데이터
- [[Buffers]]: 버퍼
- [[Working Storage]]: 작업 저장소
- [[Scratch Space]]: 스크래치 공간

---

## Amazon EFS - Elastic File System

### [[Amazon EFS Deep Dive]]
**Video 38-39 (Parts 1-2) - Duration: ~26 minutes**

#### EFS Fundamentals
[[File System]]:
- [[Network File System]]: NFS 기반
- [[Shared Access]]: 공유 접근
- [[Scalable]]: 자동 확장
- [[Multi-AZ]]: 다중 가용 영역
- [[High Performance]]: 높은 성능
- [[Fully Managed]]: 완전 관리형
- [[Built-in Security]]: 내장 보안

#### EFS Setup
[[Configuration]]:
1. [[Create File System]]: 파일 시스템 생성
2. [[Configure Network]]: 네트워크 설정
3. [[Create Mount Targets]]: 마운트 지점 생성
4. [[Attach to EC2]]: EC2 연결
5. [[Mount]]: 마운트
6. [[Use]]: 사용

#### EFS vs EBS vs S3
[[Storage Comparison]]:

| Feature | EFS | EBS | S3 |
|---------|-----|-----|-----|
| Type | File | Block | Object |
| Access | Multiple Instances | Single Instance | HTTP API |
| Durability | High | High | Very High |
| Scalability | Automatic | Manual | Unlimited |
| Performance | Good | Very High | Variable |
| Cost | Medium | Low-High | Low |
| Use Case | Shared Storage | Boot/Databases | Data Lakes |

#### Performance Modes
[[EFS Modes]]:
- [[General Purpose]]: 범용
- [[Max IO]]: 최대 입출력
- [[Throughput Optimized]]: 처리량 최적화

---

## Storage Integration

### [[Multi-Storage Strategy]]

#### Selecting the Right Storage
[[Decision Matrix]]:

**Use S3 When**:
- ✅ Need scalable object storage
- ✅ Data lakes and analytics
- ✅ Static websites
- ✅ Archival storage
- ✅ Cross-region access

**Use EBS When**:
- ✅ Database storage
- ✅ Boot volumes
- ✅ High IOPS requirements
- ✅ Single instance attachment
- ✅ Consistent performance

**Use EFS When**:
- ✅ Multiple instances need access
- ✅ Shared file systems
- ✅ POSIX compliance needed
- ✅ NFS protocol required
- ✅ Auto-scaling workloads

**Use Instance Store When**:
- ✅ Temporary data
- ✅ Caching layers
- ✅ Maximum performance needed
- ✅ Data loss acceptable
- ✅ No extra cost concerns

---

## Summary: Storage Solutions

### [[Key Takeaways]]

✅ **Amazon S3**:
- 무제한 스케일
- 다양한 스토리지 클래스
- 높은 내구성
- 비용 효율적

✅ **Amazon EBS**:
- 블록 스토리지
- 빠른 성능
- 스냅샷 지원
- 영구 저장

✅ **Amazon EFS**:
- 공유 파일 시스템
- 자동 확장
- NFS 기반
- 다중 인스턴스

✅ **Storage Strategy**:
- 용도별 선택
- 계층화 구조
- 비용 최적화
- 성능 향상

---

**Playlist Source**: All AWS Videos
**Channel**: ImTechnos
**Total Storage Videos**: 10 videos
**Coverage**: S3, EBS, EFS, Instance Store, 암호화, 버전 관리

---

## 🔗 Related Graphs (관련 그래프)

**AWS Core**:
- [[AWS_Fundamentals_Graph]] - 기본 개념
- [[AWS_EC2_Compute_Graph]] - EC2와 함께 사용
- [[AWS_Management_Infrastructure_Graph]] - 백업 및 재해복구

← 돌아가기: [[AI_Agents_Multi_Industry_Enterprise_Hub]]
