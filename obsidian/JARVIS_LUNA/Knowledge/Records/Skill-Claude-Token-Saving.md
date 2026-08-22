---
title: Claude Skill — Token Saving
source: https://www.youtube.com/watch?v=fnaWPA3FhyU
source_title: 클로드 스킬 다 지우세요. 이 4개만 빼고
category: token-saving
created_at: 2026-08-22
---

# Claude Skill — Token Saving

> 영상 공개 요약에서 네 가지 핵심 범주 중 하나로 제시된 **토큰 절약**을 JARVIS 작업 흐름에 적용한 스킬이다. 영상의 공개 자료에서 고유한 서드파티 skill slug는 확인되지 않았으므로, 아래 문서는 해당 범주를 재사용 가능한 JARVIS 스킬로 구현한 것이다.

## 목적

반복적인 파일 탐색과 불필요한 전문 모델 호출을 줄이고, 필요한 정보만 단계적으로 읽어 작업 품질을 유지한다. 큰 코퍼스나 Obsidian 볼트를 한 번에 컨텍스트에 넣지 않고 인덱스와 변경 파일을 우선 확인한다.

## 실행 규칙

먼저 사용자의 목표, 대상 경로, 완료 기준을 한 문단으로 정리한다. 다음으로 인덱스·상태 파일·최근 변경 목록을 읽고, 실제 작업에 필요한 파일만 선택한다. 동일 파일을 반복해서 읽지 않으며, 긴 결과는 요약 파일에 저장해 다음 단계에서 재사용한다. 외부 데이터는 원문 URL과 수집 시각을 보존하고, 샘플·더미 데이터로 빈틈을 채우지 않는다.

작업 중에는 값싼 결정론적 검사와 실제 변경을 분리한다. JSON 구조 확인, 파일 존재 여부, wikilink 대조는 스크립트로 먼저 실행하고, 의미 해석이 필요한 부분만 모델 판단에 맡긴다. 완료를 주장하기 전에 변경 목록, 검증 결과, 실패 항목을 함께 기록한다.

## JARVIS 적용 예시

```text
목표: 새 YouTube 지식 레코드를 Obsidian과 GitHub에 반영
1. 기존 Knowledge Index와 최근 Record만 읽는다.
2. 원문 JSON·Markdown을 생성한다.
3. 필요한 Source·Topic 링크만 추가한다.
4. dangling wikilink 검사를 실행한다.
5. runtime을 갱신하고 실제 수치를 확인한다.
```

## 검증 기준

토큰 절약은 정보 생략이 아니라 **필요한 정보의 지연 로딩과 중복 제거**를 뜻한다. 원문 URL·핵심 근거·검증 결과를 잃지 않아야 하며, 불확실한 내용은 추측으로 보완하지 않는다.

## 관련 Obsidian 노드

- [[JARVIS Real Knowledge Index]]
- [[Source--YouTube]]
- [[AI-Agents]]
- [[Claude Skills Core Four]]

## 출처

[YouTube 원영상](https://www.youtube.com/watch?v=fnaWPA3FhyU&t=2s) · [공개 관련 요약 게시물](https://www.threads.com/@passionplus_ai/post/DcSAbsYATV2)
