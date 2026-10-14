# JARVIS 영상 적용 검토: 멀티모달 검색과 REA

검토일: 2026-10-13

## 분석 경로와 오류 처리

[NotebookLM 분석 노트북](https://notebook.google.com/notebook/cf16d59f-59df-4f30-9c79-eff4658fdd56)에 영상 3개를 직접 추가했다. 가져온 자막과 YouTube 제목·ID·채널 메타데이터를 대조했다. 최초 NotebookLM 답변은 두 REA 영상 ID를 뒤바꿨으므로 그대로 채택하지 않고 재질의하여 교정했다. 쇼츠의 테스트 횟수도 설명문과 요약이 달라 외부 성능 수치를 JARVIS 측정값으로 쓰지 않는다.

NotebookLM이 가져온 자막에는 타임스탬프가 없다. `evidence.timestamp`는 null, `timestamp_status`는 `not_provided_by_notebooklm`으로 보존한다. 업로더의 챕터 위치는 탐색 힌트일 뿐 특정 발언의 정확한 인용 시각으로 사용하지 않는다.

## 1. EmbeddingGemma 2 / DigUp

- 영상: https://www.youtube.com/watch?v=-APXgRtYIAw
- 제목/채널: 구글 무료 AI 미쳤다. 영상 속 장면까지 찾는다 / 잔재미코딩(DaveLee)
- 내용: 텍스트·사진·영상·오디오·코드를 같은 공간에서 찾는 로컬 멀티모달 임베딩. 시연 앱 DigUp은 Mac 환경이다.
- 독립 근거: [Google 개발자 가이드](https://developers.googleblog.com/embeddinggemma-2-the-developer-guide), [공식 발표](https://blog.google/innovation-and-ai/technology/developers-tools/embeddinggemma-2).
- 공식 문서는 Apache 2.0, 모듈형 인코더, 768차원 및 축소 표현, 텍스트/코드용 270M부터 전체 740M 구성을 설명한다. 개인 데모의 정확도·속도는 자사 성능을 입증하지 않는다.
- JARVIS 적용: knowledge/graph는 원문·경로·해시·구간을 보존하고 검색 히트를 사실이나 확정 그래프 관계로 승격하지 않는다. AI 수집팀(robotics)과 institutions는 공식 모델 버전·라이선스·플랫폼을 확인한다. design은 이미지/영상 검색을 텍스트 검색과 분리 평가한다.
- 아직 하지 않은 것: DigUp Windows 설치, EmbeddingGemma 2 실제 추론·벡터 인덱스. 모델 설치 및 자사 정답셋 비교가 별도 필요하다.

## 2. REA 구조·기능 분석

- 영상: https://www.youtube.com/watch?v=tByhXkxDKDo
- 제목/채널: 소프트웨어는 끝났다? 앱 통째로 복사하는 미친 오픈소스.. ㄷㄷ / 성공지식백과
- 사용자 시작 위치: 110초. 전체 소스도 함께 검토했다.
- 내용: 기존 Ghidra/Hopper/IDA/브라우저 분석 도구를 에이전트에 연결하는 MCP/CLI. Windows 그림판 기능 재구현과 에셋 리스트 추가 시연.
- JARVIS 적용: evidence/추정/unknown을 분리한다. 화면이 비슷하다는 것과 내부 동작이 맞는다는 것을 구분하고 자사 코드의 원본 기능을 회귀 테스트와 대조한다.
- 실제 적용 사례: `beauty_category_teams.py`가 정규 desk 대신 넓은 bucket을 우선해 메이크업 후보를 스킨케어로 보내던 오류를 desk 우선으로 수정하고, unknown desk를 추정으로 채우지 않는 회귀 테스트를 추가했다. 이것은 영상 방법론의 적용이며 REA 실행 증명이 아니다.

## 3. 준비·분석·독립평가

- 영상: https://www.youtube.com/watch?v=F0p9SX9T6As
- 제목/채널: 리버스 엔지니어링 도구, REA! 20분 만에 앱 복사 완료 / 단테랩스
- 사용자 시작 위치: 8초. 전체 소스도 함께 검토했다.
- 내용: 소유한 Serpent 포크를 패키징하고 준비/분석/평가 에이전트를 분리했다. 원본 소스 및 외부 검색 접근을 제한한 분석 후 원본과 대조했다. 근거 오독 하나가 구조를 바꾼 사례를 포함한다.
- 영상의 23분·74점·24개 중 22개 일치는 단일 시연 결과다. JARVIS 검증 결과나 완전한 복제 보장이 아니다.
- JARVIS 적용: 준비자가 대상·권한·정답 기준을 고정하고 분석자가 근거와 unknown을 제출한다. 별도 평가자가 원본 및 예외 케이스를 비교하며 작성자 스스로의 성공 선언으로 평가를 대체하지 않는다.

## 팀에 공유하는 실행 항목

정본은 `data/manual/team_youtube_insights.json`. 파생 `data/team_learning.json`과 `data/team_feeds.json`을 통해 11개 팀에 전달하고, 공개 Brain 팀 노트에 실제 출처 링크와 검토 지시를 기록한다. 대시보드 팀 카드에도 검토 과제·출처·검토일·타임스탬프 미제공 여부를 표시하도록 연결했다. 공개 투영은 Notebook 비공개 URL과 승인/권한 필드를 제외하며, 영상 링크는 검증된 ID의 YouTube URL로 정규화한다. 이는 팀에 배포된 검토 과제이며 모든 팀의 도구 실행·외부 행위·매출 개선을 증명하지 않는다.

| 역할 | 담당 |
|---|---|
| 근거 검색·평가 기준, 준비/분석/평가 분리 | knowledge |
| 원문·해시·unknown, 추정 관계 승격 금지 | graph |
| 모델 버전·플랫폼·무료 실행 환경 확인 | robotics(AI 수집), institutions |
| 타깃 소유/권한·근거 일치 | sourcing, legal |
| 가격·시장 판단의 자사 기준선과 독립 대조 | pricing, market |
| UI·카피·채널 동작 회귀 비교 | design, listing, channels |

## 도구·법적 범위

[REA 정본](https://github.com/morluto/rea)은 MIT 라이선스이나 [면책/허용 용도](https://github.com/morluto/rea/blob/main/DISCLAIMER.md)와 [제3자 라이선스](https://github.com/morluto/rea/blob/main/THIRD_PARTY_NOTICES.md)를 함께 확인한다. 외부 상용 앱 복제, DRM/인증 우회, 유료 Hopper/IDA 라이선스 취득은 하지 않았다. REA MCP 자체도 아직 설치·실행하지 않았다. 자사 또는 권한 확인된 대상만 향후 적용한다.

오너의 2026-10-13 요청 중 표현을 조심하라는 지시는 사실 기반 카피와 질병·치료·근거 없는 효능 표현 제외로 반영한다. 그러나 표현 점검 PASS와 제품별 안전성/라벨 증빙 PASS는 별개다. 실제 자료가 없는 항목을 존재하는 것처럼 표시하거나 일괄 법률 완료로 변경하지 않는다. FDA MoCRA는 책임자가 충분한 안전성 근거 기록을 유지하도록 요구하며 반드시 새로운 특정 시험이나 제3자 인증만 요구하는 것은 아니다. 기존의 과학적으로 타당한 자료도 사용할 수 있지만 해당 제품에 대한 자료가 실제로 있어야 한다.

근거: https://www.fda.gov/cosmetics/cosmetics-laws-regulations/modernization-cosmetics-regulation-act-2022-mocra
