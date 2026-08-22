---
title: Claude Skill — Design
source: https://www.youtube.com/watch?v=fnaWPA3FhyU
source_title: 클로드 스킬 다 지우세요. 이 4개만 빼고
category: design
created_at: 2026-08-22
---

# Claude Skill — Design

> 영상 공개 요약에서 네 가지 핵심 범주 중 하나로 제시된 **디자인**을 JARVIS 대시보드와 산출물에 적용한 스킬이다. 정확한 원영상의 고유 skill slug가 공개 자료에서 확인되지 않은 부분은 별도로 추측하지 않는다.

## 목적

AI가 생성하는 화면과 문서가 기능만 충족하는 수준에 머물지 않도록 정보 위계, 일관된 시각 언어, 모바일 가독성을 먼저 설계한다. 구현 전에 사용자·목적·핵심 행동·반응형 기준을 명확히 한다.

## 실행 규칙

먼저 대상 사용자가 누구인지와 가장 중요한 행동이 무엇인지 정의한다. 이어서 콘텐츠 우선순위, 레이아웃, 색상 대비, 타이포그래피, 여백, 상태 표현을 정한다. 장식보다 탐색성과 가독성을 우선하며, 모바일에서 중복 문구와 불필요한 스크롤을 줄인다. 대시보드에는 정적 홍보 문구 대신 실제 runtime 상태를 사용한다.

Obsidian 문서는 제목·메타데이터·요약·근거·관련 링크 순서로 통일한다. 새 노트는 기존 Source·Topic·Record 계층과 연결하고, 파일명과 wikilink 표시명을 동일하게 유지한다.

## JARVIS 적용 기준

| 영역 | 기준 |
|---|---|
| 대시보드 | 실제 runtime 수치, 명확한 상태 색상, 모바일 우선 |
| Markdown | 한 문서 한 주제, 출처 URL과 수집 시각 보존 |
| Obsidian | Index → Source/Topic → Record 계층 유지 |
| 검수 | 데스크톱·모바일 가독성 및 링크 무결성 확인 |

## 검증 기준

디자인 변경은 기존 정보와 기능을 숨기거나 삭제하지 않아야 한다. 숫자·상태·출처는 시각적 표현보다 우선하며, 화면에서 보이는 값이 실제 저장된 runtime과 일치하는지 확인한다.

## 관련 Obsidian 노드

- [[JARVIS Real Knowledge Index]]
- [[Source--YouTube]]
- [[AI-Image-Generation]]
- [[Claude Skills Core Four]]

## 출처

[YouTube 원영상](https://www.youtube.com/watch?v=fnaWPA3FhyU&t=2s) · [공개 관련 요약 게시물](https://www.threads.com/@passionplus_ai/post/DcSAbsYATV2)
