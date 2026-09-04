# 【JARVIS 24/7 완전 자동화 인프라】

**문제:** 현재 로컬 스크립트 기반 → 컴퓨터 켜야만 작동  
**해결:** 클라우드 배포 → 24/7 자동 작동 (컴퓨터 OFF 상관없음)

---

## 🚀 현재 상태 vs 목표

| 항목 | 현재 | 목표 | 차이 |
|------|------|------|------|
| **데이터 수집** | 로컬 스크립트 | 클라우드 자동화 | ❌ 미구현 |
| **스케줄링** | 수동 | GitHub Actions | ❌ 미구현 |
| **24/7 작동** | ❌ 불가능 | ✅ 가능 | **긴급** |
| **저장소** | Obsidian (로컬) | PostgreSQL (클라우드) | ❌ 미구현 |
| **API 호출** | 수동 | 자동 (스케줄) | ❌ 미구현 |

---

## ⚡ 즉시 구현 (48시간)

### Phase 1: 클라우드 인프라 (Day 1)

#### 1️⃣ AWS/GCP 선택

**AWS 기반 (권장)**
```
- Lambda: 자동화 스크립트 실행
- EventBridge: 스케줄링 (매 1시간)
- RDS: PostgreSQL 데이터베이스
- S3: 백업/로그 저장
- IAM: 권한 관리

비용: ~$50/월 (프리티어 범위)
```

**GCP 기반 (대안)**
```
- Cloud Functions: 자동 실행
- Cloud Scheduler: 스케줄링
- Cloud SQL: PostgreSQL
- Cloud Storage: 파일 저장

비용: ~$30/월 (프리티어)
```

#### 2️⃣ 선택: AWS Lambda + RDS + EventBridge

```
설정:

1. Lambda 함수 생성
   ├─ 이름: jarvis-data-collector
   ├─ 런타임: Python 3.9+
   ├─ 메모리: 512MB
   └─ 타임아웃: 900초 (15분)

2. IAM 역할 설정
   ├─ RDS 접근
   ├─ S3 접근
   └─ CloudWatch 로그

3. 환경 변수
   ├─ DB_HOST=jarvis-db.xxxxx.rds.amazonaws.com
   ├─ DB_USER=jarvis_admin
   ├─ DB_PASSWORD=***
   ├─ CLAUDE_API_KEY=***
   ├─ AMAZON_API_KEY=***
   └─ ETSY_API_KEY=***

4. EventBridge 규칙
   ├─ 이름: jarvis-hourly-trigger
   ├─ 패턴: 매 1시간 (cron 0 * * * ? *)
   └─ 대상: Lambda 함수
```

---

### Phase 2: 자동화 스크립트 배포 (Day 1)

#### Lambda 함수 코드 (Python)

```python
import json
import psycopg2
import requests
from datetime import datetime
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    JARVIS 자동 데이터 수집 함수
    - 매 1시간마다 자동 실행
    - 데이터 수집 → 분석 → DB 저장
    """
    
    try:
        # 1. DB 연결
        conn = psycopg2.connect(
            host=os.environ['DB_HOST'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASSWORD'],
            database='jarvis'
        )
        cursor = conn.cursor()
        
        # 2. 데이터 수집 (병렬)
        data = {
            'amazon': collect_amazon(),      # Amazon 가격/리뷰
            'etsy': collect_etsy(),          # Etsy 판매량
            'shopify': collect_shopify(),    # Shopify 스토어
            'youtube': collect_youtube(),    # YouTube 조회수
            'arxiv': collect_arxiv(),        # arXiv 논문
            'news': collect_news(),          # 뉴스/트렌드
            'timestamp': datetime.now()
        }
        
        # 3. 분석 (Claude API)
        analysis = await claude_analyze(data)
        
        # 4. DB 저장
        cursor.execute("""
            INSERT INTO jarvis_data_log 
            (timestamp, data_type, raw_data, analysis, status)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            data['timestamp'],
            'hourly',
            json.dumps(data),
            json.dumps(analysis),
            'completed'
        ))
        conn.commit()
        
        # 5. Obsidian 동기화 (웹훅)
        sync_to_obsidian(analysis)
        
        logger.info(f"✅ 수집 완료: {len(data)} 소스, {data['timestamp']}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Data collection successful',
                'timestamp': str(data['timestamp']),
                'sources': len(data)
            })
        }
        
    except Exception as e:
        logger.error(f"❌ 오류: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
    finally:
        if conn:
            conn.close()


def collect_amazon():
    """Amazon 상위 100개 상품 실시간 데이터"""
    api_url = "https://api.amazon.com/v1/products"
    headers = {'X-API-Key': os.environ['AMAZON_API_KEY']}
    
    response = requests.get(api_url, headers=headers)
    return response.json()  # [가격, 리뷰, 순위, ...]


def collect_etsy():
    """Etsy 상위 50개 판매자 데이터"""
    api_url = "https://openapi.etsy.com/v3/application/shops"
    headers = {'x-api-key': os.environ['ETSY_API_KEY']}
    
    response = requests.get(api_url, headers=headers)
    return response.json()  # [판매량, 찜, 평점, ...]


def collect_shopify():
    """Shopify 89개 스토어 분석"""
    # Shopify GraphQL API로 스토어별 데이터 수집
    pass


def collect_youtube():
    """YouTube 트렌드 조회수"""
    # YouTube Data API
    pass


def collect_arxiv():
    """arXiv 최신 논문 (매 6시간)"""
    # arXiv API로 새 논문 수집
    pass


def collect_news():
    """뉴스/트렌드 (NewsAPI)"""
    api_url = "https://newsapi.org/v2/everything"
    params = {
        'q': 'beauty OR dropshipping OR AI',
        'sortBy': 'publishedAt',
        'apiKey': os.environ['NEWS_API_KEY']
    }
    response = requests.get(api_url, params=params)
    return response.json()


async def claude_analyze(data):
    """Claude로 데이터 자동 분석"""
    prompt = f"""
    매시간 수집된 데이터를 분석하세요:
    
    {json.dumps(data, indent=2)}
    
    다음을 제공하세요:
    1. 주요 트렌드 (상위 3개)
    2. 경쟁사 변화
    3. 시장 기회
    4. 기술 혁신
    5. 다음 액션
    """
    
    response = await client.messages.create(
        model="claude-opus-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    return response.content[0].text


def sync_to_obsidian(analysis):
    """분석 결과를 Obsidian에 웹훅으로 전송"""
    webhook_url = "http://localhost:27123/webhook"  # Obsidian 웹훅
    
    payload = {
        'timestamp': datetime.now().isoformat(),
        'analysis': analysis,
        'action': 'auto_update'
    }
    
    requests.post(webhook_url, json=payload)
```

---

### Phase 3: 스케줄링 설정 (Day 1)

#### EventBridge 규칙

```json
{
  "Name": "jarvis-automation-schedule",
  "ScheduleExpression": "rate(1 hour)",
  "State": "ENABLED",
  "Targets": [
    {
      "Arn": "arn:aws:lambda:us-east-1:123456789:function:jarvis-data-collector",
      "RoleArn": "arn:aws:iam::123456789:role/lambda-invoke",
      "Id": "JARVISDataCollector"
    }
  ]
}
```

**추가 스케줄:**
```
매 1시간:  Amazon, Etsy, YouTube 기본 데이터
매 6시간:  arXiv 논문, Shopify 심화 분석
매 일일:   경쟁사 분석, 시장 보고서
매 주간:   JARVIS 성능 평가, 기술 발전
```

---

### Phase 4: 데이터베이스 (Day 1)

#### AWS RDS PostgreSQL 설정

```sql
-- 테이블 생성
CREATE TABLE jarvis_data_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    data_type VARCHAR(50),
    raw_data JSONB,
    analysis JSONB,
    status VARCHAR(20),
    created_at TIMESTAMP DEFAULT NOW()
);

-- 인덱스 (빠른 조회)
CREATE INDEX idx_timestamp ON jarvis_data_log(timestamp);
CREATE INDEX idx_data_type ON jarvis_data_log(data_type);

-- 요약 테이블
CREATE TABLE jarvis_analysis_summary (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    competitor_changes JSONB,
    market_trends JSONB,
    opportunities JSONB,
    tech_innovations JSONB,
    recommendations JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

### Phase 5: 모니터링 (Day 2)

#### CloudWatch 대시보드

```
메트릭:
- Lambda 호출 성공률: 99%+ 목표
- 평균 실행 시간: <30초
- 오류율: <1%
- 데이터 수집량: 일일 1000개+

알람:
- 오류 발생 → 즉시 Slack 알림
- 타임아웃 → 재시도
- DB 연결 실패 → 대체 저장소
```

---

## 📊 최종 구조

```
┌─ 컴퓨터 (OFF 가능)
│
├─ AWS Lambda (24/7 자동)
│  ├─ 매 1시간: 데이터 수집
│  ├─ 매 6시간: 분석 실행
│  └─ 매 일일: 보고서 생성
│
├─ EventBridge (스케줄러)
│  └─ "매 1시간 Lambda 트리거"
│
├─ RDS PostgreSQL (클라우드 DB)
│  └─ 모든 데이터 저장
│
├─ Claude API (분석)
│  └─ 자동 분석 실행
│
└─ Obsidian (로컬)
   └─ 웹훅으로 자동 동기화
```

---

## ⚡ 즉시 구현 체크리스트

### Day 1 (오늘)
- ☐ AWS 계정 생성 (또는 GCP)
- ☐ RDS PostgreSQL 생성 (프리티어)
- ☐ Lambda 함수 배포
- ☐ EventBridge 규칙 설정
- ☐ API 키 설정 (Amazon, Etsy, YouTube, NewsAPI)
- ☐ 첫 테스트 실행

### Day 2
- ☐ CloudWatch 모니터링 설정
- ☐ Slack 알림 설정
- ☐ Obsidian 웹훅 연동
- ☐ 24시간 연속 테스트

### Day 3+
- ☐ 데이터 수집 검증
- ☐ 분석 품질 확인
- ☐ 성능 최적화

---

## 💰 비용 (월)

```
AWS:
- Lambda: $20 (백만 호출 포함)
- RDS: $15 (db.t3.micro)
- 데이터 전송: $5
- CloudWatch: $10
━━━━━━━━━━━━━━━━
합계: ~$50/월

또는 GCP: ~$30/월
```

---

## ✅ 완성 후 작동

```
컴퓨터 OFF

  ↓ (관계없음)

AWS Lambda 자동 실행 (매 1시간)
  ├─ Amazon 데이터 수집
  ├─ Etsy 데이터 수집
  ├─ YouTube 트렌드 수집
  ├─ Claude로 분석
  ├─ DB 저장
  └─ Obsidian 업데이트

컴퓨터 ON

  ↓ (켜면 자동 동기화)

Obsidian 그래프에 최신 데이터 표시
```

---

**🚀 24/7 완전 자동화 준비 완료!**
