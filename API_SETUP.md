# 실제 데이터 기반 자동화 - API 설정 가이드

## 📋 개요
다이소 상품 자동 발굴 시스템은 **오직 실제 데이터만** 사용합니다.
- ✅ 거짓 데이터 금지
- ✅ 실제 웹 데이터만 수집
- ✅ 검증된 소스만 사용

---

## 1️⃣ 다이소 웹사이트 크롤링

### 준비 사항
```bash
pip install beautifulsoup4 requests
```

### 동작 원리
- 다이소 공식 웹사이트 자동 크롤링
- HTML 파싱으로 상품명, 가격, 평점 추출
- User-Agent 설정으로 차단 우회

### 실행
```bash
python real_product_discovery.py
```

---

## 2️⃣ Amazon 판매 순위 연동

### API 설정 (필수)
1. AWS 계정 생성
2. Product Advertising API 등록
   - https://advertising.amazon.com/
3. Access Key 발급

### GitHub Secrets 설정
```bash
# .github/workflows/auto-update.yml 에서 사용
- name: Amazon API 키 추가
  env:
    AMAZON_API_KEY: ${{ secrets.AMAZON_API_KEY }}
```

### 설정 방법
1. GitHub 저장소 → Settings → Secrets and variables → Actions
2. New repository secret
3. Name: `AMAZON_API_KEY`
4. Value: AWS 발급 키 입력

---

## 3️⃣ Google Trends 분석

### 준비 사항
```bash
pip install pytrends
```

### 기능
- 실시간 검색 트렌드 분석
- 다이소 상품 인기도 추적
- 카테고리별 트렌드 분석

### 자동 실행
```bash
# 매 10분마다 자동 실행 (GitHub Actions)
python real_product_discovery.py
```

---

## 4️⃣ 실시간 리뷰/평점 수집

### 연동 가능한 API
1. **Google Maps API**
   - 다이소 매장별 평점 수집
   - 고객 리뷰 분석

2. **Naver 쇼핑 API**
   - 한국 판매 데이터
   - 실제 고객 평점

3. **Coupang API**
   - 판매량 실시간 추적

### 설정 (별도 진행)
각 API 공식 문서 참조하여 키 발급 후 적용

---

## 📊 데이터 수집 결과

### 저장 위치
```
data/real_products.json
```

### 데이터 구조
```json
{
  "timestamp": "2026-08-18T10:00:00Z",
  "data_sources": [
    {
      "source": "다이소 공식 웹사이트",
      "count": 25,
      "status": "✅ 성공"
    },
    {
      "source": "Amazon 판매 순위",
      "status": "⏳ API 키 필요"
    },
    {
      "source": "Google Trends",
      "keywords_analyzed": 5,
      "status": "✅ 분석 완료"
    }
  ],
  "products": [
    {
      "source": "다이소 공식 웹사이트",
      "name": "상품명",
      "price": "₩1,000",
      "rating": "4.5⭐",
      "verified": true
    }
  ],
  "metadata": {
    "data_quality": "실제 데이터만 사용",
    "fake_data_policy": "금지됨 ✅",
    "verification_status": "검증됨"
  }
}
```

---

## ✅ 데이터 검증

### 거짓 데이터 제거
- ❌ 시뮬레이션 데이터 사용 금지
- ✅ 실제 웹 크롤링 데이터만
- ✅ 공개 API 데이터만
- ✅ 모든 데이터 소스 명시

### 품질 보증
1. 각 상품마다 수집 출처 기록
2. 수집 시간 타임스탐프 기록
3. 검증 상태 표시
4. 오류 시 명확한 실패 메시지

---

## 🔄 자동화 스케줄

### GitHub Actions 실행
- **시간**: 매 10분마다
- **시간대**: UTC (자동)
- **작업**: 
  1. 다이소 웹사이트 크롤링
  2. Amazon 판매 순위 연동
  3. Google Trends 분석
  4. 리뷰/평점 수집
  5. 추천 생성
  6. 데이터 저장

### 모니터링
```
.github/workflows/auto-update.yml
Actions → Daiso Real Data Discovery
```

---

## 📝 주의사항

### 법적 준수
- robots.txt 확인
- 이용약관 준수
- Rate limiting 준수
- 저작권 존중

### 성능
- API 호출 제한 준수
- 타임아웃 설정
- 에러 핸들링
- 재시도 로직

---

## 💡 문제 해결

### API 키 없음
```
⏳ API 키 필요 - 데이터 수집 불가
→ 해결: GitHub Secrets에 API 키 추가
```

### 라이브러리 부족
```
⚠️ pytrends 라이브러리 필요
→ 해결: pip install pytrends
```

### 네트워크 오류
```
❌ 연결 실패
→ 해결: URL 확인, 타임아웃 조정
```

---

## 🚀 다음 단계

1. ✅ API 키 발급 (Amazon)
2. ✅ GitHub Secrets 설정
3. ✅ 첫 실행 확인
4. ✅ 데이터 품질 검증
5. ✅ 대시보드 연동

---

**마지막 업데이트**: 2026-08-18
**정책**: 거짓 데이터 절대 금지 ✅
