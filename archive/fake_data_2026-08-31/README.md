# 가짜 데이터 격리 (2026-08-31)

CLAUDE.md 의 "거짓말 데이터 금지 / 가짜 데이터 금지" 원칙에 따라
아래 파일들을 대시보드 파이프라인에서 제거하고 이곳에 보존한다.

## 격리 사유

### amazon_product_discovery.py
`CATALOG` 상수에 상품명·가격·"상승/유지" 추세를 사람이 직접 적어 두고
그것을 "Amazon Best Sellers"로 대시보드에 순위와 함께 표시했다.
실제 네트워크 수집을 하지 않는다.

### walmart_product_discovery.py
동일한 하드코딩 카탈로그 방식.

### oliveyoung_us_discovery.py
`source: "us.oliveyoung.com (curated bestseller mirror)"` 로 표기된
하드코딩 15건. 순위와 평점이 실측값이 아니다.

### sync_channels.py.bak
`FALLBACK` 딕셔너리에 8개 채널 전부의 가짜 상품 목록을 갖고 있었고,
`pick()` 함수가 실제 수집이 비면 말없이 이 값으로 대체했다.
Ulta 평점은 `round(4.3 + (i % 5) * 0.1, 1)` 로 계산해 만들어 냈고,
`from_shopify()` 의 demand_score·predicted_orders·expected_roas 는
인덱스 산술로 생성한 값이었다. 환율 기본값 1383.49 도 하드코딩이었다.

### tiktok_shop_us_products.json
`source: "TikTok Shop US viral beauty (curated)"` 로 사람이 적은 목록.

## 왜 되살릴 수 없는가

- Ulta / Sephora: 공식 공개 API 없음 (Sephora 개발자 포털 비공개, Ulta 포털 부재)
- Amazon: PA-API 5.0 신규 가입 중단 + 2026-05-15 지원 종료.
  후속 Creators API 는 최근 30일 어필리에이트 판매 10건 이상 필요하고
  데이터 보존 24시간 제한이 있어 순위를 저장소에 커밋할 수 없다.
- Walmart: Affiliate API 가 승인된 파트너 전용
- TikTok: Partner API 는 자기 상점 데이터만 제공
- Google Trends: 공식 API 가 승인제 alpha 단계

## 실제로 살아 있는 데이터

- 다이소 실수집 (scripts/daiso/collect_daiso.py) - daisomall.co.kr 실크롤링, robots.txt 준수
- 환율 (open.er-api.com 등 3중 폴백)
- arXiv Atom API
- Google Custom Search API
- Open Beauty Facts (scripts/collect_open_beauty_facts.py) - 인증 불필요 오픈데이터
