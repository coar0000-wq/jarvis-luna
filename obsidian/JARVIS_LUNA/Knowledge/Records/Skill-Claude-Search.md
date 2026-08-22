---
title: Claude Skill — Search
source: https://www.youtube.com/watch?v=fnaWPA3FhyU
source_title: 클로드 스킬 다 지우세요. 이 4개만 빼고
category: search
created_at: 2026-08-22
---

# Claude Skill — Search

> 영상 공개 요약에서 네 가지 핵심 범주 중 하나로 제시된 **서칭**을 실제 자료 수집과 검증에 적용한 스킬이다. 공개 자료로 확인할 수 없는 고유 스킬명은 임의로 만들어내지 않는다.

## 목적

검색 결과의 제목이나 짧은 스니펫에 의존하지 않고, 원문을 열어 핵심 주장과 출처를 확인한 뒤 재사용 가능한 Markdown과 JSON으로 보존한다. YouTube·논문·검색 결과를 JARVIS 지식 그래프에 연결할 때 사용한다.

## 실행 규칙

먼저 넓은 검색어로 후보를 찾고, 같은 의도를 가진 변형 검색어로 교차 확인한다. 검색 결과에서 최소 두 개 이상의 관련 URL을 열어 본문 또는 설명을 읽는다. 원문 URL, 제목, 게시자, 수집 시각, 핵심 요약, 불확실성을 기록한다. 검색 스니펫만으로 고유 명칭이나 설치 명령을 단정하지 않는다.

YouTube 자막·본문에 접근할 수 없으면 공개 제목·설명·관련 게시물만 근거로 사용하고, 확인되지 않은 세부 내용은 문서에 명시한다. API 키나 로그인 세션이 필요한 자료는 키를 문서에 기록하지 않고 `not_configured` 또는 접근 제한으로 표시한다.

## JARVIS 출력 계약

| 필드 | 요구사항 |
|---|---|
| source_url | 원문 또는 원영상 URL |
| source_title | 실제 확인된 제목 |
| collected_at | 수집 시각 |
| summary | 원문 근거 기반 요약 |
| evidence | 확인한 본문·설명·관련 출처 |
| uncertainty | 접근 제한 또는 미확인 항목 |
| links | Obsidian Source·Topic·Index 연결 |

## 검증 기준

출처 URL과 본문 또는 충분한 설명이 없는 항목은 학습 코퍼스에 넣지 않는다. 서로 다른 출처의 내용이 충돌하면 양쪽을 기록하고 단일 결론으로 덮어쓰지 않는다. 최종 Markdown에는 원영상 링크와 관련 공개 자료 링크를 함께 둔다.

## 관련 Obsidian 노드

- [[JARVIS Real Knowledge Index]]
- [[Source--YouTube]]
- [[AI-Research]]
- [[Claude Skills Core Four]]

## 출처

[YouTube 원영상](https://www.youtube.com/watch?v=fnaWPA3FhyU&t=2s) · [공개 관련 요약 게시물](https://www.threads.com/@passionplus_ai/post/DcSAbsYATV2)
