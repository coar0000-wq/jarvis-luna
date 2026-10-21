# Shop 벤치마킹 실행 연결: 비교 근거와 팀 지시 보존

기준 코드: `38407208306fa4fc1017d955d21312b4a6f52ac5` (2026-10-21 로컬 통합 기준).
기존 7파일 패치의 구현을 그대로 재사용해 최신 코드에 재적용했다.
벤치마킹 자료·7팀 원천은 이 기준에 존재하는
`docs/learning/2026-10-20-shop-beauty-benchmark.md`와
`data/manual/team_briefings.json`을 따른다. 이 변경은 그 두 파일을 수정하지 않는다.

## 변경 범위

- `build_beauty_price_strategy.py`: 가격을 결정하거나 저장하지 않는다. 기존 입력을
  읽는 오프라인 보고서의 `verified` 증거 판정만 보수적으로 바꾼다.
- `build_team_feeds.py`: 원천의 ID, 수신팀별 업무, 제한 선언과 근거를 생성피드에
  보존한다. 피드 생성은 수신·업무 수행·승인 증거가 아니다.
- `preflight.yml`: 기존 검사를 모두 유지하고 아래 3개 테스트 실행만 추가한다.
- 운영 JSON, 현재 가격, Shopify 상품·이미지·상태, 결제, 판매 게시, 고객 데이터는
  변경하거나 전송하지 않는다. 이미지·성분·DRAFT 보존 수리는 별도 변경이다.

## 가격 비교

종전에는 상품 가격과 배송비만 있으면 `delivered_*`/`verified_*`가 가능했다.
이제 세금·필수 부대비용과 동일 배송 조건이 미확인이면 `provisional_*`만 남긴다.
정확한 용량·단위·묶음 개수가 달라도 단위당 참고 비교는 유지하지만 검증된 동일
상품 가격 우위로 승격하지 않는다. g와 ml는 계속 비교하지 않는다.
`30ml (2pcs)`처럼 용량의 묶음 수와 별도 개수 표기가 충돌하면 수량을
`ambiguous`로 처리한다.

선택적 `checkout_quote`를 경쟁 상품 행과 자사 ACTIVE 등록 행에 기록할 수 있다.
현재 수집기·운영 데이터에 이 필드를 자동 생성하지 않는다. 증거가 없으면 값을
추정하지 않고 미확인으로 유지한다.
현재 신뢰할 수 있는 결제 총액 관측 수집기는 연결되어 있지 않다. 따라서 입력이
모두 채워져도 `source_verified`는 항상 false이고, 출처 미검증 사유를 남긴다.
입력의 `verified`, `source_verified`, `reviewed`, 승인 상태, 해시 또는 단순 HTTPS
URL은 출처 인증이 아니다. 이 필드를 추가하는 것만으로 검증 점수를 얻을 수 없다.

필수 견적 필드:

- `item_id`: 경쟁 행의 정규화 item ID, 자사는 정확한 `pd_no` 문자열
- `item_price_usd`: 해당 관측 상품 가격과 같은 금액
- `shipping_usd`: 기존 경쟁 행 배송비 또는 자사의 명시적 `--own-shipping-usd`와 같은 금액
- `tax_usd`: 해당 주문에 구매자가 부담하는 세금 총액
- `mandatory_fees_usd`: 필수 부대비용·구매자 부담 관세/통관 비용 총액
- `currency`: `USD`, `market`: `US`, `quantity`: 정수 `1`
- `shipping_method`: `standard`
- `destination_key`: 양쪽이 동일한 비고객 미국 비교 목적지의 익명 키
  (`us_` 뒤 소문자·숫자·밑줄 3~64자). 고객 주소·이메일·고객 ID를 넣지 않는다.
- `observed_at`: 시간대가 있는 ISO 시각. 보고서 기준 24시간 이내이며 미래 시각 불가
- `source_url`: 관측 근거의 HTTPS URL

여기서 quantity 1은 판매 단위 1개다. 5ml×6 묶음과 30ml×1은 서로 다른 판매
단위이다. 무료배송도 세금·수수료까지 무료라는 뜻이 아니다. 세금이나 관세가
나중에 정해지면 총액은 미확인이다. 명시적 0만 0으로 계산하고 누락·음수·불리언·
NaN은 거부한다.
금액은 센트 단위이며 각 항목은 1,000,000 USD 이하만 지원한다. 소수 센트와
과대 숫자는 예외를 발생시키지 않고 미확인으로 처리한다.

`known`은 기록의 산술적 완전성만 뜻한다. `delivered_price_usd`는 완전한 기록이
있을 때만 계산하며, 이 값이 있어도 출처가 검증되었다는 뜻은 아니다.
기존 상품가+배송비 소계는 `item_shipping_subtotal_usd`로 남긴다.
가격 우위는 관측된 비교 상품 집합에만 해당하며 미국 전체 최저가 주장이 아니다.
저렴한 상품가의 비교품에 총액이 빠져 있어도 검증된 최저가를 단정하지 않는다.
단위 가격의 표시용 반올림은 순위·동률·불완전 총액의 하한 비교에 사용하지 않는다.

이 검사는 기록된 견적의 일관성 검증이다. 사람·사이트의 진위나 법적 적합성을
인증하지 않는다. 원본 관측·출처의 진위는 따로 검토해야 한다. 기존 마진
경고/면제, 등급, S등급 선별, 법적 hold, 가격 쓰기 경로는 바꾸지 않는다.

## 팀 피드와 상태

기존 title, url, date, summary, teams, by_hand, 정렬 방식은 유지한다.
ID가 없는 예전 항목과 다른 자료는 기존 `(title, url)` 중복 제거를 유지한다.
ID가 있는 업무는 ID로 구분해 제목·출처가 같아도 서로 다른 지시를 잃지 않는다.
수신팀별 행에는 다음 정보를 추가한다.

- `briefing_id`: 원천 ID 그대로. 없는 예전 항목은 기존처럼 처리한다.
- `team_action`: 해당 수신팀의 업무만 복사
- `scope_limits`, `review_path`, `source_urls`: 원천의 제한과 근거 보존
- `scope_limits_authority`: `source_declaration_only`
- `status`: `generated_for_review_not_acknowledged`
- `receipt_scope`: `feed_generation_only`
- `execution_verified`: false, `business_approval`: false

원천에 임의의 완료·승인값이 있어도 전파하지 않는다. scope_limits의 true는
실행 권한이 아니다. 같은 ID가 두 번 나타나면 출력 교체 전에 오류로 중단한다.
각 팀 이름을 바꾸거나 다른 팀으로 재배정하지 않는다.

원천 반영 → 실제 생성피드 반영 → 팀의 수신/실행 결과는 서로 다른 상태다.
이 기능에는 읽음이나 실제 작업 완료 영수증을 만드는 기능이 없다.

## 오프라인 검증

```
python -B -m unittest discover -s scripts -p "test_beauty_price_strategy.py"
python -B -m unittest discover -s scripts -p "test_checkout_price_evidence.py"
python -B -m unittest discover -s scripts -p "test_team_briefing_feeds.py"
```

회귀 범위: unknown≠0, 총액 순위 역전, 정확한 용량/묶음, 다른 목적지,
오래된/미래 견적, 가격·ID 불일치, 원본 불변, 마진/hold 보존, 기존 피드 호환,
수신팀별 업무, ID 중복, 별도 ID의 같은 제목·출처, 임의 완료·승인값,
재실행 중복, CI 실행 등록, 자기신고 출처 검증 우회, 동률 반올림, 과대 금액.
알고리즘의 검증된 총액 분기는 명시적으로 주입한 내부 합성 신뢰 경계로만
시험한다. 별도 테스트는 실제 정규화 경로에 자기신고 검증값을 넣어도 점수 0임을
확인한다.

CPython 3.11.17에서 로컬 집중 검사 144개와 최신 원천 통합 검사 8개를 통과했다.
workflow와 helper가 등록한 기존 고유 테스트 대상 93개를 모두 유지하고 정확히
3개만 추가했다(총 96개). 실행 workflow는 그 3줄을 제거하면 기준 파일과 바이트가 같다. 전체 저장소 suite를
실행한 결과는 아니다. 기준 SHA의 기존 자료를 사용한 추가 dry-run에서도
214개 상품의 가격·등급·법적 hold·우선순위와 11팀 643행의 기존 필드·순서·요약이
같았다. 원천 41파일은 수정하지 않았고 네트워크 연결 시도는 0이었다.
실제 원천 15개 항목의 ID·수신팀을 확인하고, 선택 필드를 제거한 예전 입력의
호환성도 별도 검사했다. 실제 7팀 항목에 완료·승인·scope true를 주입해도
생성피드의 승인·실행은 false, 제한 선언의 권한은 source_declaration_only였다.
새 판매감사 입력이나 관측 수집기는 추가하지 않았다.
기존 선택 입력 `manual/sephora_2026-09-01.json`은 실제 내용이 HTML이라
이전·이후 모두 JSON 로딩 실패로 제외됐다. 새 FDA 수집과 비공개 운영 증거
파일은 이 로컬 검증 범위에 없다.
전체 운영 회차 성공, 라이브 등록 또는 판매 개선 성과를 입증하지 않는다.
