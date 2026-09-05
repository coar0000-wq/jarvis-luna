# 가짜 데이터 생성기 폐기 (2026-09-05)

난수로 지표를 지어내던 스크립트와 그 산출물을 전부 여기로 내렸다.
저장소 CLAUDE.md 의 `가짜 데이터 금지` 원칙에 따른 조치다.

## 왜 지금 발견됐나

배포 전 검증(preflight)이 WARN 으로 알려 주고 있었는데 FAIL 이 아니라서
넘어가고 있었다. 사용자가 "가짜는 무조건 폐기" 라고 지시해 전수 조사했다.

## 폐기한 생성기

### phase_26_progress_realtime.py  ← 가장 심각
`epoch = random.randint(30, 85)` 로 학습 진행도를 지어냈다.
**JARVIS-Core-Automation.yml 에서 10분마다 실행되고 있었다.**
산출물 data/phase_26_progress.json 은 대시보드가 읽지도 않는다.
워크플로 스텝과 요약 출력도 함께 제거했다.

### .github/workflows/update_activity_log.py
`random.choice(technologies)` 로 활동 로그를 지어내
activity_log.json / agi_metrics.json / projects.json 을 채웠다.

### phase30_autonomous_metalearning.py
`np.random.randint(15, 30)` 등으로 new_algorithms, drug_candidates,
optimization_techniques, novel_architectures 를 지어냈다.

### scripts/generate_metrics.py
`random.uniform` 으로 accuracy, response_time_ms, throughput,
automation_rate 를 매번 흔들었다.

### scripts/jarvis_automation_real.py
이름과 달리 `random.uniform` 으로 uptime_hours, api_response_time_ms,
data_accuracy, automation_rate 를 지어냈다.

### update_tasks.py
`random.randint(1, 3)` 만큼 작업 완료 수를 늘렸다.

### scripts/youtube_moe_analysis.py
`random.choice(training_data)` 에 잡음을 더해 학습 표본을 합성했다.

## 함께 내린 산출물

phase_26_progress.json / phase26_progress.json / phase30_results.json /
tasks.json / jarvis_work_detailed_log.json / agi_metrics.json /
activity_log.json / projects.json

전부 위 생성기가 만든 값이다. 라이브 대시보드(index.html)는 이 중
어느 것도 읽지 않는다. 확인하고 내렸다.

## 남겨 둔 난수 사용 (가짜가 아님)

- scripts/daiso/collect_daiso.py
  `time.sleep(DELAY + random.uniform(0, 2))` — 요청 간격 흔들기.
  robots.txt 의 Crawl-delay 를 지키면서 패턴을 피하는 정상 용도다.
- completed/phase26_moe_implementation.py 등 3종
  임베딩 초기화, 하이퍼파라미터 탐색 등 알고리즘 자체의 난수다.
  보고 지표를 지어내지 않는다. 워크플로에서 실행되지도 않는다.
