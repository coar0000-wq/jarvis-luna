# 상품 갤러리 완성 판정과 보완 검토

## 범위

이미지 개수나 영문화 성공을 갤러리 완성으로 취급하지 않습니다. 11장 고정 기준도 없습니다.
근거 검사와 누락 사진의 추가만 수행합니다. 기존 사진의 삭제·교체·재정렬과 본문·가격·상태 변경은 하지 않습니다. 판매 활성화는 사용자가 최종 결정합니다.
실제 제품의 권리 또는 패키지 라벨 증거를 새로 확보한 변경이 아닙니다. 테스트 자료는 전부 합성 자료입니다.

필수 역할은 대표 이미지(`representative`), 구성·제형(`composition_texture`), 사용법(`usage`), 성분 또는 제품 정보(`product_information`), 주의사항(`cautions`)입니다.
각 역할은 해당 SKU 원본에 근거해야 합니다. 이미지 파일명·개수·자동 추측으로 역할을 충족시키지 않습니다. 서로 다른 역할을 실제로 담은 한 장은 여러 역할을 설명할 수 있지만 동일 바이트를 여러 장으로 세지는 않습니다.

## 상태와 보수적인 보완 계획

- `review_required` / `partial`: 원본·자산·검수 기록·역할·권리·실제 라벨 중 하나 이상이 미확인입니다.
- `prepared`: 준비 자산과 검수 문서의 연결 및 신선도가 일치합니다. 실제 갤러리 완성을 뜻하지 않습니다.
- `additions_prepared`: 현재 정확한 DRAFT 상품의 전체 기존 미디어를 확인했고, 누락된 자산의 해시만 추가 계획에 나옵니다.
- `complete`: 준비된 모든 자산의 실제 바이트가 현재 DRAFT 갤러리에 이미 확인됐습니다. 게시 또는 법적·안전 승인 상태가 아닙니다.

`BACKFILL_DRAFT_IMAGES=1`은 0·2·3장 등 모든 등록된 DRAFT를 다시 검토하며 저장된 `gallery_complete`를 믿지 않습니다. 현재 정확한 DRAFT의 전체 미디어가 0장이면 기존 허용 목록/영문화 QA를 통과한 이미지 첨부 경로를 유지합니다. 업로드한 정확한 바이트 해시와 현재 상태를 재검증하지만, 일부 사진 첨부를 갤러리 완성으로 표시하지는 않습니다. 기존 사진이 있는 경우에는 모든 역할·권리·실제 라벨 검수 근거가 완전하고 기존 미디어 바이트가 준비 자산과 정확히 대응할 때만 누락 자산을 추가합니다.
`BACKFILL_DRAFT_IMAGES_LIMIT`은 현재 미디어 조회 상품 수의 상한입니다. 상한 밖 일반 후보도 보고서에 남고 `current_inventory_read_deferred`로 표시됩니다. 미확정 첨부 예약은 현재 저장 상태와 관계없이 먼저 확인하고 일반 후보는 영속 순번으로 순환하므로 앞쪽의 같은 상품만 반복 조회하지 않습니다. 예약을 조회 상한/비활성화 플래그 때문에 확인하지 못해도 새로운 쓰기 차단은 유지됩니다.
ACTIVE·ARCHIVED·다른 SKU·불완전한 페이지·오래된 관찰은 추가 계획이 차단됩니다. 기존 미디어 ID는 보존 목록에 남습니다.
현재 Shopify 읽기 어댑터는 ID/상태/페이지 완전성과 실제 CDN 이미지 바이트를 확인합니다. HTTPS cdn.shopify.com의 정규 파일 경로만 읽고 리다이렉트는 따라가지 않으며 파일 크기를 제한합니다. URL·alt·파일명에서 해시를 만들어내지 않습니다. 기존 사진의 바이트 또는 준비 자산과의 대응을 확인하지 못하면 검토 대기 상태를 유지합니다. 해시를 맞추려고 기존 사진을 삭제하거나 다시 올리지 않습니다. Shopify가 이미지 바이트를 변환했다면 별도 대응 근거가 필요하며 자동으로 동일 사진이라고 추측하지 않습니다.

## 경합과 불확실한 첨부

업로드 전과 상품 첨부 직전에 현재 DRAFT와 전체 미디어를 재조회하고, 첨부 후에도 기존 ID/바이트 보존과 정확한 추가 자산을 확인합니다. 이 API 경로는 상태 확인과 첨부를 원자적으로 묶지 못하므로 그 사이의 소유자 변경 가능성이 남습니다. 불일치나 불확실한 결과를 만나면 그 실행에서 이후 갤러리 첨부와 신규 상품 생성을 중단하며 상태 변경·삭제·교체로 자동 복구하지 않습니다.

첨부 전에 기존 ID/해시와 기대하는 추가 해시를 원자적 로컬 레지스트리에 기록합니다. 응답 유실이나 정상적인 이미지 처리 지연은 완료로 처리하지 않습니다. 다음 실행은 현재 정확한 DRAFT와 바이트가 기록과 일치하는 경우에만 읽기 전용으로 결과를 재확인하며 동일 첨부를 재시도하지 않습니다. 실제 일치가 없으면 단순 `verified` 플래그나 사람 검토 완료 선언으로 해제하지 않습니다.

## 비공개 증거 구조

상품별 파일은 `data/manual/gallery_review/<pd_no>.json`입니다. 해당 디렉터리는 Git 제외 대상입니다. 모든 파일 참조는 검사 루트 기준 상대 경로이며 외부 경로·상위 경로 탈출·외부 심볼릭 링크를 거부합니다. 실제 파일 바이트와 SHA-256이 모두 있어야 합니다.

최상위 키:
- `schema_version`: 1
- `pd_no`: 정확한 상품 번호 문자열
- `assets`: 아래 자산 목록
- `review_evidence`: `rights`, `label` 각각 `{file, sha256}` 검수 문서 참조

자산 키:
- `pd_no`, `asset_file`, `asset_sha256`
- 보존한 실제 원본의 `source_file`, `source_sha256`, `source_url`(HTTPS)
- `review_receipt`: `{file, sha256}`

자산 검수 문서 키:
- `kind`: `gallery_asset_review`
- `pd_no`, `reviewed_at`(시간대 포함), `reviewer`
- 정확하게 일치하는 `asset_sha256`, `source_sha256`, `source_url`
- `roles`: 위 역할 중 실제 확인된 것
- `role_evidence`: 역할별 원본 근거 문구 또는 검토 설명
- `qa`: `face_check`, `claim_check`, `residual_text_check`, `sku_check`가 모두 `pass`

권리·라벨 검수 문서 공통 키:
- `kind`: `gallery_rights_review` 또는 `gallery_label_review`
- `pd_no`, `reviewed_at`, `reviewer`, `disposition`
- `asset_sha256s`: 준비 자산 전체와 정확히 같은 집합
- `evidence_file`, `evidence_sha256`: 실제 검토한 증거 파일

권리는 추가로 `source_sha256s`가 모든 사용 원본과 일치해야 하고 `permission_scope`가 `reproduce`, `adapt`, `store_product_gallery`를 포함해야 합니다.
라벨은 `verification_basis`가 `actual_package_label`이어야 합니다. 공급자 고시만 읽은 경우 이를 실제 패키지 확인으로 승격하지 않습니다.
미확인 권리·라벨은 `disposition: pending`으로 남깁니다. 단순히 성공 플래그를 붙이거나 증거 파일 없이 `confirmed`를 선언해도 통과하지 못합니다.
모든 검수 기록은 미래 시각이 아니며 30일 이내여야 합니다. 파일 삭제·변조·기간 만료는 다음 검사에서 다시 차단됩니다. 추가 계획은 검사 결과를 매번 새로 계산하고 현재 상품 관찰은 5분 이내여야 합니다.

검사는 기록과 바이트의 일관성을 확인하는 장치입니다. 검토자의 신원이나 문서의 진위를 인증하거나 저작권 허가·제품 안전·판매 적법성을 보증하지 않습니다. `publication_allowed`와 `legal_or_safety_approval`은 항상 false입니다.

## 로컬 검증

- `python -B -m unittest discover -s tests -p test_gallery_review.py`
- `python -B -m unittest discover -s tests -p test_daiso_daily_beauty_to_shopify.py`
- `python -B -m unittest discover -s scripts -p test_localize_detail_images.py`

마지막 회귀에는 저장소에 잠긴 Shopify 이미지 처리 의존성이 필요합니다. 실제 Shopify 호출 없이 mock과 합성 파일만 사용합니다.
