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
