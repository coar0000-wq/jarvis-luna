---
name: JARVIS Token Saving
description: Reduce unnecessary context reads and model calls while preserving source evidence. Use when a task involves large repositories, long notes, repeated file inspection, or cost-sensitive analysis.
---

# JARVIS Token Saving

## Instructions

1. State the goal, scope, target path, and completion criteria before reading files.
2. Read the smallest useful index, status file, and recent diff first. Do not load an entire corpus or vault when an index is available.
3. Read each file at most once unless the file changed. Save long findings to a concise Markdown note for reuse.
4. Prefer deterministic checks for JSON structure, file existence, hashes, and wikilinks. Reserve semantic reasoning for interpretation.
5. Preserve original URLs, source text or summary, and collection time. Never fill missing evidence with sample or dummy data.
6. Before claiming completion, report changed files, verification commands, and any unresolved limitation.

## User prompt examples

Use this prompt in Claude Code:

```text
/jarvis-token-saving
Review the current JARVIS repository without loading the whole vault. Read the relevant index and recent changes first, identify only the files needed to update the YouTube record, and finish with a changed-file list plus validation evidence.
```

Use this prompt in Claude chat when the skill file is attached:

```text
이 파일의 규칙을 적용해 주세요. 전체 폴더를 한 번에 읽지 말고 인덱스와 최근 변경부터 확인한 뒤, 필요한 파일만 읽어 실제 근거를 보존하면서 작업해 주세요.
```

## Completion check

Confirm that no source evidence was discarded, no dummy record was introduced, and the final report includes the exact files and checks performed.
