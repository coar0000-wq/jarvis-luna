# 다이소 운영 총량과 신규 탐색 분리

일일 수집은 `DAISO_DISCOVERY_ENABLED=1`, `DAISO_OPERATING_UPDATES_ENABLED=0`으로 실행한다. 운영 상품 `products.json`과 운영 점수·게이트·수출·등록 큐는 그대로 유지한다. 후보는 승인된 운영 상품이 아니다.

## 별도 증적

- `data/daiso_real/candidate_pool.json`: 실제 상세/공식 검색 관측으로 확인한 신규 비교 후보. 기존 운영 ID 제외, 공식 상세 URL·가격·관측 시각·실행 ID 필수.
- `candidate_observations.json`: 탐색 중복·실패 재시도·제외 기록. 실패 24시간 대기, 후보 72시간 이후 재확인 가능.
- `candidate_comparison.json`: 동일 결정론적 점수 규칙으로 운영 상품과 비교. 48시간 이내 검증된 채널 및 개별 출처 URL만 시장 신호에 사용한다. 모델 API 호출 없음.
- `collection_status.json`: 후보 성공은 `candidates_collected`와 `last_candidate_success`로 기록한다. 운영 상품 `last_success`를 갱신하지 않는다. 0개 결과는 `no_change`, 오류는 실패다.

기존 crawl_state.visited에는 총량 초과로 버린 ID가 포함되어 있으므로 신규 후보 선정에는 사용하지 않는다. 운영 ID·주차 제외·법률 제외·중복은 계속 제외한다. 핵심 뷰티 카테고리를 순환하며 아직 발견되지 않은 ID를 재확인보다 우선한다. 정상 일일 한도 110건과 robots 최소 30초 대기는 유지한다.

## 교체 제안과 실행 분리

동일 카테고리·동일/호환 제형 운영 상품과 비교해 점수 우위 5점 이상, 최근 후보 관측, 검증된 시장 매칭, 품절/법률 차단 없음일 때만 검토 제안을 만든다. 제안은 운영 수량 변화 0의 비교안일 뿐 실행할 수 없다. 실제 교체는 라벨·성분·법률·재고·가격 검증과 정본 게이트·payload hash 승인을 다시 거쳐야 한다. 기존 승인 및 Shopify draft/unpublished/inventory-zero 보호는 그대로 유지한다.

후보 모드는 운영 상품 파일 SHA-256 불변, 후보 파일/정규화 해시, 현재 실행별 ID·관측 시각을 검사한다. 후보 발행은 세 후보 파일과 관측·대시보드 metadata만 허용한다. 운영 상품 파생 단계는 `mode=collected`에만 실행하며 후보 성공을 운영 성공으로 위장하지 않는다.

`test_daiso_candidates.py`는 오프라인 회귀 및 Pages 배포 필수 검사다. 정상 수집 여부는 실제 후보 ID와 공식 관측 증적으로 확인해야 하며 0건 진단은 신규 수집 복구 증거가 아니다.
