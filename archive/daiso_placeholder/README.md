# 다이소 기획용 플레이스홀더 자료 (보관)

보관일: 2026-08-23T05:57:21.551218+00:00

여기 있는 파일들은 사업 **준비 단계에서 화면 구성을 확인하려고 만든 예시 값**이며
실제 측정치가 아니다. 대시보드가 이 값을 실데이터로 표시하지 않도록 저장소 루트에서
분리해 보관한다.

## 왜 분리했나

`daiso_product_discovery.py` 는 상품을 발굴하지 않는다. 실행할 때마다
`random.randint(3, 5)` 개의 `"다이소 뷰티·스킨케어 후보 (473)"` 같은 난수 이름을
JSON에 덧붙여 개수만 늘린다. 가격도 마진도 없다. 이 스크립트가
`daiso-discovery.yml` 워크플로로 매일 돌면서 `cumulative_products.json` 의
누적 상품 수를 부풀리고 있었다.

`data/daiso_products.json` 의 금액도 단위가 맞지 않는다. 마커펜 원가 $1,129,
판매가 $8,140, 월 순익 $399,627 처럼 원화 값에 달러 기호가 붙어 있다.
`daiso_business_plan.json` 의 형광펜 월 순익 $275,000, 측정 스푼 $4,144,932,
전체 순익 $1,000,000+ 도 같은 이유로 근거가 없다.

## 대체 파이프라인

실제 데이터는 `scripts/daiso/collect_daiso.py` 가 다이소몰의 robots.txt 허용
경로에서 수집하며 결과는 `data/daiso_real/` 에 쌓인다. 상품 페이지에 실제로
표시된 원화 가격과 공개 API의 실시간 환율만 저장하고, 배송비·관세·수수료처럼
확정 견적이 없는 값은 계산하지 않는다.

## 같은 패턴의 다른 사이트들

다이소만의 문제가 아니었다. 아마존·월마트·올리브영·네이버 수집기도 글자만 바뀐
같은 코드였다.

    amazon_product_discovery.py    "아마존 뷰티·스킨케어 후보 (473)"
    walmart_product_discovery.py   "월마트 뷰티·스킨케어 후보 (218)"
    oliveyoung_product_discovery.py "올리브영 뷰티·스킨케어 후보 (655)"
    naver_product_discovery.py     "네이버 뷰티·스킨케어 후보 (901)"

넷 다 `random.randint(3, 5)` 개씩 난수 이름을 찍어내며 가격도 URL도 없다.
산출물 JSON과 함께 보관 처리했다.

`phase_26_progress_realtime.py` 는 `epoch = random.randint(30, 85)` 로 학습
진행률을 만들어 냈고, `update_tasks.py` 는 작업 진행률을 `random.randint(1, 3)`
씩 올렸다. 대시보드 수치의 근거를 무너뜨리므로 함께 보관한다.

## 실제 요청을 보내는 스크립트 (보관 대상 아님)

`oliveyoung_discovery.py`, `naver_shopping_discovery.py`, `walmart_discovery.py`,
`global_daiso_dropshipping.py` 는 `requests.get` 으로 실제 HTTP 요청을 보낸다.
동작 검증은 별도로 필요하지만 난수 생성기는 아니므로 저장소에 남겨 둔다.

## 유효한 부분

`global_daiso_dropshipping.json` 은 원화 가격(식기건조대 3,000원 등)과 환율이
정상이라 저장소에 남겨두었다. 다만 상품 수가 적다.
