---
name: JARVIS Planning
description: Plan repository and knowledge-pipeline changes with explicit scope, dependencies, completion criteria, and verification gates. Use before multi-step implementation or automation.
---

# JARVIS Planning

## Instructions

1. Define the goal, scope, target repository, and definition of done.
2. Inspect the current state before editing: repository status, relevant index, source files, and existing automation.
3. Sequence work as source collection, structured record, Obsidian integration, link validation, runtime update, and publication when applicable.
4. Gate each phase on its verification result. Do not report work as complete when a required check failed.
5. Preserve existing notes and configuration. Do not delete or move files without explicit approval.
6. End with changed paths, commands run, results, and limitations.

## User prompt examples

```text
/jarvis-planning
Plan the requested JARVIS YouTube integration before editing. Inspect the current repository and Obsidian index, define the exact files to create, include a dangling-link gate, and show the plan before implementation.
```

```text
이 스킬을 적용해 주세요. 먼저 현재 저장소와 Obsidian 상태를 조사하고, 실제 수집 → Markdown → wikilink → 검증 → GitHub 반영 순서와 완료 기준을 제시한 뒤 실행해 주세요.
```

## Completion check

A plan is complete only when every required phase has a concrete artifact and a passed validation result, or the limitation is explicitly recorded.
