# 가짜 데이터 격리 (2026-09-15)

CLAUDE.md 의 "거짓말 데이터 금지 / 가짜 데이터 금지" 원칙에 따라
아래 파일들을 `scripts/` 에서 제거하고 이곳에 보존한다.

2026-08-31 에 같은 성격의 `amazon_product_discovery.py` 와
`walmart_product_discovery.py` 를 격리했는데(`../fake_data_2026-08-31/`),
이 둘은 그때 같이 걸러지지 않고 `scripts/` 에 남아 있었다.

## 격리 사유

### collect_amazon_products.py

이름은 수집기인데 아무것도 수집하지 않는다. `build()` 안에 상품명과
가격을 8건 박아두고 그대로 `data/amazon_products.json` 에 쓴다.

```python
def build():
    return [
        {"rank":1,"name":"COSRX Advanced Snail 96 Mucin Essence","price_usd":19.99,"trend":"상승"},
        {"rank":2,"name":"Mighty Patch Original","price_usd":12.99,"trend":"상승"},
        ...
    ]
```

`"trend":"상승"` 은 근거가 없다. 어디서 재서 상승이라 한 것인지 알 수 없다.
그리고 마지막에 `print("✅ Amazon : 8 products")` 를 찍어 수집이 된 것처럼
보인다. 상세 URL 도, 평점도, 리뷰 수도 없다. 사람이 열어서 확인할 방법이
없는 숫자다.

### collect_walmart_products.py

동일한 방식. `build()` 하드코딩 8건에 `price_usd` 만 있다.

## 무엇으로 대체했나

`scripts/collect_us_retail.py` 가 넷을 실제로 받는다.

| 채널 | 경로 | 방식 |
|---|---|---|
| amazon | `/gp/bestsellers/beauty/` | Playwright chromium (CI 에서 동작) |
| ulta | `/shop/skin-care` | Playwright chromium (CI 에서 동작) |
| walmart | `/browse/beauty/1085666` | 사람 브라우저 세션 보강 |
| sephora | `/beauty/beauty-best-sellers` | 사람 브라우저 세션 보강 |

각 항목에 상세 URL 과 수집 시각이 들어간다. 못 받으면 사유를 적고
0 건으로 남긴다. 지어내지 않는다.

walmart 와 sephora 는 CI 의 새 chromium 으로는 못 넘는다.

    walmart  "Robot or human?" HUMAN 챌린지 (headless / headful 둘 다)
    sephora  "Access Denied"

사용 기록이 쌓인 실제 프로필의 Chrome 은 통과한다. 그래서 그 둘만
`data/manual/us_retail_assist.json` 에 받아 두고 수집기가 빈 자리에만
쓴다. 브라우저가 직접 받은 곳은 절대 보강분으로 덮지 않는다.
