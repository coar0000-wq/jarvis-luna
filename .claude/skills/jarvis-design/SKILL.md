---
name: JARVIS Design
description: Design readable, consistent, mobile-friendly JARVIS dashboards and Markdown outputs using real runtime data. Use when changing layout, hierarchy, responsive behavior, or presentation.
---

# JARVIS Design

## Instructions

1. Identify the audience, primary action, and information hierarchy before changing layout.
2. Use real runtime values for metrics and statuses; do not replace them with decorative hardcoded claims.
3. Preserve readability through contrast, spacing, typography, and responsive behavior. Remove redundant hero text or nested scrollbars on mobile when they obstruct content.
4. Keep Markdown notes consistent: metadata, summary, evidence, related Obsidian links, and sources.
5. After editing, inspect desktop and mobile layouts and verify that displayed values match the runtime JSON.

## User prompt examples

```text
/jarvis-design
Review index.html using data/dashboard_runtime.json as the source of truth. Improve mobile readability without changing business data. Remove redundant text only when it is duplicated, then verify the Live Briefing values and report the exact CSS/HTML changes.
```

```text
이 스킬을 적용해 대시보드의 Live Briefing을 모바일에서 읽기 쉽게 수정해 주세요. 정적 숫자를 만들지 말고 data/dashboard_runtime.json의 실제 값을 사용하며, 수정 후 데스크톱과 모바일 기준을 함께 검증해 주세요.
```

## Completion check

Confirm that content hierarchy is clearer, no runtime metric was fabricated, and the updated screen remains usable at narrow widths.
