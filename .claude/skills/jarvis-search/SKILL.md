---
name: JARVIS Search
description: Research public sources, open original pages, preserve URLs and uncertainty, and produce evidence-backed JARVIS records. Use for YouTube, web, paper, or product research.
---

# JARVIS Search

## Instructions

1. Start with broad queries and then use variants expressing the same intent.
2. Open at least two relevant source pages when available; do not rely only on result snippets.
3. Preserve the original URL, title, publisher, collection time, evidence summary, and uncertainty.
4. If captions, API access, or a page is blocked, record the limitation and do not invent a transcript, command, or skill name.
5. Exclude records that lack a usable URL and source text or a sufficient public summary from the training corpus.
6. For Obsidian output, connect the record to its Source, Topic, and Index using valid wikilinks.

## User prompt examples

```text
/jarvis-search
Research this YouTube URL. Open the original page and at least one independent public source, preserve the evidence and collection time, and create a Markdown record. If the transcript is unavailable, state that limitation instead of guessing.
```

```text
이 스킬을 적용해 이 URL을 조사해 주세요. 검색 결과 요약만 복사하지 말고 원문을 열어 확인하고, 확인된 사실·근거 URL·불확실한 항목을 분리해 Markdown으로 작성해 주세요.
```

## Completion check

Confirm that every factual claim has a source, every blocked access is disclosed, and the resulting note contains valid Obsidian links and no fabricated details.
