---
title: "AI 수집팀"
type: team-status
status: generated-from-jarvis-data
updated_at: 2026-10-23T02:39:08.670202+00:00
team_id: "robotics"
team_status: "ok"
source_reported_at: "2026-10-22T09:36:14.282602+00:00"
analysis_completed_at: "2026-10-23T02:27:26.086028+00:00"
external_team_execution_verified: false
---

# AI 수집팀

상태 **ok** · 원본 보고 시각/표시 2026-10-22T09:36:14.282602+00:00

로컬 분석 완료: 2026-10-23T02:27:26.086028+00:00 (외부 팀 실행 증명 아님)

235건 · arxiv 75 / rss 160 · 새 자료 181건 · 영상 학습 10개

다음 작업: -

## 영상 학습 공유 검토 지시

상태: shared-review-directive · 외부 도구 실행·검증된 성과·사업 승인 아님. 검토 시각은 수집/출처 최신성 시각이 아닙니다.

- robotics 팀 · Shopify 대기자 명단: 앱·동의·옵션 재고 흐름의 승인 전 설계 (VID-20261019-FZe4IOLItpY-robotics)
  - 적용 검토 과제: 합성 데이터로 정상/중복/잘못된 이메일, 옵션 변경, 해지 후 발송 차단, 중복 이벤트, 재고 0 상태를 테스트할 계획을 작성한다. 실제 고객 발송은 별도 승인 대상이다. 상품 옵션 1개의 비공개 대기자/재입고 알림 명세를 만든다. 설치·결제·권한 부여·실고객 수집/발송·상품 활성화는 별도 승인 전 실행하지 않는다.
  - 근거: [외부 영상 원문](<https://www.youtube.com/watch?v=FZe4IOLItpY>) · 영상 ID: FZe4IOLItpY
  - 타임스탬프: UNKNOWN · 기준: 실제 제목·확장 설명·업로더 챕터 확인; 자막 본문과 개별 앱 설정 시연 미확인
  - 원본 검토 시각: 2026-10-19T09:49:00+00:00
  - 업로더 챕터 힌트 (자막 시각 아님): 업로더 챕터: 00:25 기능·가격·리뷰 비교; 00:58 대기 목록 설정

- robotics 팀 · Jev 비교 영상: 팀별 경계 사례 평가와 기존 텍스트 보조 판단 유지 (VID-20261019-RJJOVHZxyhc-robotics)
  - 적용 검토 과제: 허용된 오류/상태 집계로 로컬·출처 확인·사람 검토 경로를 점검한다. 원시 로그·코드·자격증명 전송이나 도구 권한 확대는 하지 않는다. 기존 jev-1.14.0 텍스트 보조 판단과 허용된 상태·신선도·근거 존재 집계만 사용한다. 이미지·Box·긴 문맥·새 API를 활성화하지 않고 무료 잔액·영수증·하드 게이트를 유지한다. 영상 비교는 자사 성능 증거가 아니다.
  - 근거: [외부 영상 원문](<https://www.youtube.com/watch?v=RJJOVHZxyhc>) · 영상 ID: RJJOVHZxyhc
  - 타임스탬프: UNKNOWN · 기준: 업로더 설명·챕터와 제작자 공개 결과·공식 문서를 확인; 자막 본문 미확인
  - 원본 검토 시각: 2026-10-19T09:49:00+00:00
  - 업로더 챕터 힌트 (자막 시각 아님): 업로더 챕터: 03:47 둘 다 틀린 한국어 리뷰; 05:36 알아 둘 점

- Jev 1.14 텍스트 판단 모델 고정 및 실험 기능 차단 (JEV-20261019-114-TEXT)
  - 적용 검토 과제: Jev 1.14.0 텍스트 판단 모델을 명시적으로 선택한다. 공식 문서 확인 시 jev-latest는 1.13.0, jev-preview는 1.14.0이었다. 다국어 개선은 공급자 발표이며 한국어 업무 정확도는 별도 실측이 필요하다. 이미지·Box·긴 문맥은 실험 기능이므로 비활성 유지한다. 무료 잔액 증명·기존 누적 한도·사람 승인 게이트를 유지하며 이번 변경에서 실호출은 하지 않았다.
  - 근거: [외부 영상 원문](<https://typesafe.ai/blog/jev-1-14>) · 영상 ID: HPPDQz349Mk
  - 타임스탬프: UNKNOWN · 기준: 공식 릴리스 및 모델 문서 확인; 영상 시각 미확인
  - 원본 검토 시각: 2026-10-19T01:18:00+00:00

- 조건부 필요 · 설치 보류 — 게임용 PC 한 대로 서버급 AI를 돌린다고? Strata로 배우는 로컬 AI 입문 (VID-20261017-D_ZfQzPEjOw)
  - 적용 검토 과제: 로컬 후보를 비교할 때 모델 버전·양자화·RAM·VRAM·입력 길이를 고정하고 품질과 전체 지연·전력·장비 비용을 함께 기록한다.
  - 근거: [외부 영상 원문](<https://www.youtube.com/watch?v=D_ZfQzPEjOw>) · 영상 ID: D_ZfQzPEjOw
  - 타임스탬프: 05:14-06:47 · 기준: downloaded timed captions; approximate ASR alignment
  - 원본 검토 시각: 2026-10-17

- 조건부 필요 · 학습 실행 보류 — [한영자막] 지능을 빌리는 건 그만: 특화 AI의 학습부터 배포까지 (VID-20261017-Eu4D795nMsQ)
  - 적용 검토 과제: 학습용 데이터와 독립 평가셋을 분리하고 실제 사례 30건 이상에서 정답·기존 출력·후보 출력·비용·시간을 같은 ID로 비교한다.
  - 근거: [외부 영상 원문](<https://www.youtube.com/watch?v=Eu4D795nMsQ>) · 영상 ID: Eu4D795nMsQ
  - 타임스탬프: 14:09-16:04 · 기준: downloaded timed captions; approximate ASR alignment
  - 원본 검토 시각: 2026-10-17

- 필요 · 재사용 작업 지침 적용 — 구글신기능 skill미쳤습니다.. gem쓰고 있다면 지금바로 갈아타세요 (VID-20261017-OMkUQyG1AFE)
  - 적용 검토 과제: 팀 작업마다 입력·출력·검증·실패 처리 규칙을 문서화하고 공통 사실 검증 지침 위에 디자인·비용 등 작업별 규칙을 조합한다.
  - 근거: [외부 영상 원문](<https://www.youtube.com/watch?v=OMkUQyG1AFE>) · 영상 ID: OMkUQyG1AFE
  - 타임스탬프: 11:40-16:40 · 기준: downloaded timed captions; approximate ASR alignment
  - 원본 검토 시각: 2026-10-17

- 필요 · 기존 Jev 유지 및 검증 보강 — Claude에 Jev를 붙여서 사용하는 방법과 실제 동작 방식 (with ELI5) #Jev #Jev사용법 #Claude (VID-20261017-pQRJUgrriBk)
  - 적용 검토 과제: 분류 입력·출력은 고유 ID로 묶고 누락 응답을 승인으로 취급하지 않는다. 기존 무료 한도·중단 규칙을 유지하며 실제 정답셋에서 누락·오판을 확인한다.
  - 근거: [외부 영상 원문](<https://www.youtube.com/watch?v=pQRJUgrriBk>) · 영상 ID: pQRJUgrriBk
  - 타임스탬프: 00:49-01:46 · 기준: downloaded timed captions; approximate ASR alignment
  - 원본 검토 시각: 2026-10-17

- 필요 · 검증 방법 적용 — 실행 파일만 줬더니 AI가 복원하고 검증까지? | REA 실습 (VID-20261017-zFujXrPKoGA)
  - 적용 검토 과제: 기능 변경 전후에 같은 입력과 경계·빈 값·오류 입력을 대조하고 근거·추정·미확인을 구분한다. 원본 동작을 추정만으로 대체하지 않는다.
  - 근거: [외부 영상 원문](<https://www.youtube.com/watch?v=zFujXrPKoGA>) · 영상 ID: zFujXrPKoGA
  - 타임스탬프: 06:32-07:51 · 기준: downloaded timed captions; approximate ASR alignment
  - 원본 검토 시각: 2026-10-17

- 멀티모달 근거 검색과 매체별 평가 (KNW-20261013-01)
  - 적용 검토 과제: 텍스트·사진·영상·오디오를 매체별로 구분하여 출처 경로·원문 링크·파일 해시·구간을 보존하고 Top-5 회수율과 지연을 자사 정답셋으로 비교한다. 임베딩 검색 결과를 검증된 사실이나 옵시디언 확정 관계로 바로 승격하지 않는다.
  - 근거: [외부 영상 원문](<https://www.youtube.com/watch?v=-APXgRtYIAw>) · 영상 ID: -APXgRtYIAw
  - 타임스탬프: UNKNOWN · 기준: unknown; uploader chapter is navigation only
  - 원본 검토 시각: 2026-10-13
  - 업로더 챕터 힌트 (자막 시각 아님): 전체 쇼츠

- 준비·분석·독립평가 분리와 오독 회귀 검사 (KNW-20261013-03)
  - 적용 검토 과제: 준비 단계가 타깃·권한·정답 기준을 고정하고 분석 단계가 근거와 unknown을 제출한 뒤 독립 평가 단계가 원본 및 예외 케이스를 대조한다. 도구 실행·전체 복제·성과 향상을 검증 없이 완료로 표시하지 않는다.
  - 근거: [외부 영상 원문](<https://www.youtube.com/watch?v=F0p9SX9T6As>) · 영상 ID: F0p9SX9T6As
  - 타임스탬프: UNKNOWN · 기준: unknown; uploader chapter is navigation only
  - 원본 검토 시각: 2026-10-13
  - 업로더 챕터 힌트 (자막 시각 아님): 07:17 실험 설계 / 14:37 채점표 / 17:14 기능 확장
