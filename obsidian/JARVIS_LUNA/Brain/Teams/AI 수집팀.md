---
title: "AI 수집팀"
type: team-status
status: generated-from-jarvis-data
updated_at: 2026-10-17T16:46:46.440574+00:00
team_id: "robotics"
team_status: "ok"
source_reported_at: "2026-10-11T13:35:28.740085+00:00"
analysis_completed_at: "2026-10-17T16:42:28.986955+00:00"
external_team_execution_verified: false
---

# AI 수집팀

상태 **ok** · 원본 보고 시각/표시 2026-10-11T13:35:28.740085+00:00

로컬 분석 완료: 2026-10-17T16:42:28.986955+00:00 (외부 팀 실행 증명 아님)

235건 · arxiv 75 / rss 160 · 새 자료 130건 · 영상 학습 7개

다음 작업: -

## 영상 학습 공유 검토 지시

상태: shared-review-directive · 외부 도구 실행·검증된 성과·사업 승인 아님. 검토 시각은 수집/출처 최신성 시각이 아닙니다.

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
