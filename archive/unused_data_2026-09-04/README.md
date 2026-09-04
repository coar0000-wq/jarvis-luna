# 미사용 data 파일 격리 (2026-09-04)

## 판정 방법

`data/` 아래 105개 파일 전부에 대해, 저장소의 모든
`.py` `.yml` `.html` `.bat` 에서 파일명이 참조되는지 조사했다.
archive / legacy / completed / obsidian 은 조사에서 제외했다.

결과: 참조됨 81개, 미참조 24개.
미참조 24개 중 아래 경우는 제외하고 남겼다.

- `data/manual/*` — `ingest_manual_channels.py` 가 폴더째 glob 하므로 사용 중
- `legal_team.json` — MoCRA 컴플라이언스 정리. 미국 수출 준비에 필요
- `organic_shopify_strategy.json` — 광고비 0원 전략. 판매 구성 결정의 근거

## 격리한 것

| 파일 | 사유 |
|---|---|
| ai_briefing.json | "automation_rate 96" 등 근거 없는 자평 지표. 읽는 곳 없음 |
| executive_kpi.json | today_sales 286 / today_profit 98. 실매출 아님. 읽는 곳 없음 |
| finance_team.json | monthly_revenue 5550 / "정산 완료". 실제 정산 없음 |
| jarvis_level_3_6_declaration.json | "Level 3.6 AGI 공식 선언" 문서. 기능과 무관 |
| phase26_results.json | 과거 Phase 완료 보고서. 현재 파이프라인 미사용 |
| phase27_results.json | 위와 같음 |
| phase28_results.json | 위와 같음 |
| phase29_results.json | 위와 같음 |
| phase31_40_results.json | 위와 같음 |
| strategy_report_20260821_*.json | 2026-08-21 1회성 산출물 |
| strategy_report_20260821_*.pptx | 위와 같음 |

## 중요

`executive_kpi.json` 과 `finance_team.json` 은 매출·이익 숫자를 담고 있었으나
실제 판매 기록이 아니다. 아직 Shopify 스토어가 없다.
대시보드가 읽지 않아 화면에 뜨지는 않았지만,
파일만 보면 실적으로 오인할 수 있어 격리한다.

원본은 이 폴더에 그대로 보존한다. 필요하면 되살릴 수 있다.

## 중첩 경로 오류

`data/data/`, `data/data/data/`, `data/data/data/data/` 가 있었다.
스크립트가 이미 `data/` 안에서 실행되면서 다시 `data/` 를 붙여 만든 것으로 보인다.

포함된 6개 파일은 정상 경로의 같은 이름 파일보다 오래된 사본이었다.
예: `tiktok_shop_us_products.json` 정상 2,012B / 중첩 1,517B

`nested_data_dirs/` 에 보존하고 원본 경로는 제거한다.
