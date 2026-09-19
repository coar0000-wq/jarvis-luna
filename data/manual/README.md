# 수동 채널 데이터 투입 폴더

자동 수집이 불가능한 채널을 사람이 직접 채우는 곳입니다.

## 넣는 위치

```
C:\Users\Desktop\Claude\Projects\kms\jarvis-luna\data\manual\
```

## 파일명 규칙

`<채널>_<YYYY-MM-DD>.json`

| 채널 앞부분 | 대시보드 채널 | 대상 사이트 |
|---|---|---|
| `ulta` | Ulta Beauty | ulta.com |
| `sephora` | Sephora | sephora.com |
| `amazon` | Amazon Best Sellers | amazon.com |
| `walmart` | Walmart Beauty | walmart.com |
| `tiktok` | TikTok Shop US | shop.tiktok.com |
| `trends` | Google Trends US | trends.google.com |

예: `ulta_2026-09-01.json`

같은 채널 파일이 여러 개면 **날짜가 가장 최근인 것**만 씁니다.
과거 파일은 지우지 않아도 됩니다. 이력으로 남습니다.

## 파일 형식

```json
{
  "source_url": "https://www.ulta.com/shop/skin-care/moisturizers",
  "captured_at": "2026-09-01",
  "products": [
    {
      "rank": 1,
      "product": "CeraVe Moisturizing Cream",
      "brand": "CeraVe",
      "price_usd": 18.99,
      "rating": 4.8,
      "review_count": 12400
    }
  ]
}
```

- `source_url` **필수** — 어느 페이지를 보고 적었는지. 없으면 파일을 거부합니다.
- `captured_at` **필수** — 파일명에 날짜가 있으면 생략 가능합니다.
- `product` 와 `price_usd` 가 없는 항목은 버립니다.
- `brand` / `rating` / `review_count` / `rank` 는 있으면 좋고 없어도 됩니다.

필드 이름은 어느 정도 유연합니다.
`name` `title` `product_name` 도 상품명으로 인식하고,
`price` `sale_price` 도 가격으로 인식합니다.

## Gemini에 넣을 프롬프트

스크린샷을 올린 뒤 아래를 그대로 붙여넣으세요.

```
이 스크린샷은 <사이트 이름>의 상품 목록 화면이다.
보이는 상품만 JSON 배열로 뽑아라. 화면에 없는 값은 절대 지어내지 마라.

각 원소 형식:
{"rank": 순위(정수), "product": "상품명 전체", "brand": "브랜드",
 "price_usd": 가격(숫자만, 통화기호 없이),
 "rating": 평점(숫자 또는 null), "review_count": 리뷰수(정수 또는 null)}

규칙:
- 화면에 안 보이는 필드는 null로 둔다. 추정하지 않는다.
- 할인가와 정가가 같이 보이면 실제 판매가를 price_usd에 넣는다.
- JSON 배열만 출력한다. 설명 문장은 쓰지 마라.
```

Gemini가 준 배열을 위 형식의 `products` 자리에 넣고
`source_url` 과 `captured_at` 을 채워 저장하면 됩니다.

## 반영 방법

파일을 넣은 뒤 JARVIS에게 "수동 채널 반영해줘" 라고 하면
`scripts/ingest_manual_channels.py` 를 돌려 대시보드에 올리고 푸시합니다.
자동 워크플로에서도 매 실행마다 이 폴더를 읽습니다.

## 신뢰 등급

대시보드에 **"수동 입력"** 배지와 수집 날짜가 함께 표시됩니다.
30일이 지나면 오래된 데이터로 표시됩니다. 주기적으로 갱신해 주세요.

## 미국 화장품 공개 판매 법률 입력

Shopify 초안은 자동 생성할 수 있지만, 공개 판매(`public_ready`)는 검증된 MoCRA/FPLA 값이 모두 있을 때만 열립니다. 시스템은 책임자, 사용법, 경고 문구를 추정하지 않습니다.

### 1. 미국 Responsible Person

`legal_responsible_person.example.json`을 검토한 뒤 다음 이름으로 복사합니다.

```
data/manual/legal_responsible_person.json
```

`name`, `address`, `email`, `phone` 네 필드가 모두 필요합니다. 이 저장소는 공개 저장소이므로 실제로 라벨에 공개할 수 있고 법률 검토가 끝난 사업자 연락처만 넣습니다.

### 2. 상품별 영문 사용법·경고

`legal_product_overrides.example.json`을 다음 이름으로 복사하고, `items` 아래에 `canonical_product_id` 또는 `pd_no`별 검증 값을 넣습니다.

```
data/manual/legal_product_overrides.json
```

필수 입력은 `directions`와 `warnings`입니다. 상품별 책임자가 다른 경우에만 `responsible_person`을 함께 넣습니다. 예시 문구를 운영 데이터로 복사하지 말고, 포장·제조사 자료와 법률 검토 결과를 그대로 입력합니다.

### 3. 재생성·검증

```bash
python scripts/build_legal_full.py
python scripts/build_listing_gate.py
python scripts/build_product_master.py --inject-s
python scripts/export_shopify_operational.py
python scripts/validate_commerce_architecture.py
```

`data/legal_full.json`의 `complete`와 `data/listing_gate.json`의 `public_ready`가 증가해야 합니다. 검증 전에는 Export가 `Draft`, `Published=FALSE`, 재고 `0`을 유지합니다.

## Shopify Ontology Action 승인

`data/shopify_action_queue.json`은 `listing_gate.ready` 상품을 Product Variant 그룹 단위의 멱등 Draft Action으로 만듭니다. VT Reedle Shot 100/300처럼 하나의 Shopify Product로 묶이는 상품은 Action도 하나만 생성됩니다.

승인하려면 `shopify_action_approvals.example.json`을 아래 이름으로 복사하고, 큐의 현재 `payload_hash`를 그대로 넣습니다.

```
data/manual/shopify_action_approvals.json
```

승인은 `approved=true`, `approved_payload_hash`, `approved_by`, `approved_at`이 모두 있어야 유효합니다. payload가 바뀌면 hash가 달라져 자동으로 재승인이 필요합니다.

현재 Action 큐는 외부 Shopify 쓰기를 실행하지 않습니다. 실행기를 연결할 때도 Draft, 미공개, 재고 0, `deny`를 read-after-write로 재검증해야 합니다. 공개 Action은 `public_ready`, 법률 담당자 승인, 검증된 실재고, 별도의 공개 승인이 모두 있기 전에는 생성하지 않습니다.
