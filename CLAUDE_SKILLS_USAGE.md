# JARVIS Claude Skills 실제 사용 가이드

## 중요한 경로 차이

`obsidian/JARVIS_LUNA/Knowledge/Records/`의 문서는 지식 그래프용 기록입니다. Claude Code가 자동으로 스킬로 인식하는 실행용 문서는 프로젝트 루트의 `.claude/skills/<skill-name>/SKILL.md`에 있어야 합니다. 이 저장소에는 네 가지 실행용 패키지를 추가했습니다.

| 호출 이름 | 실제 파일 |
|---|---|
| `/jarvis-token-saving` | `.claude/skills/jarvis-token-saving/SKILL.md` |
| `/jarvis-design` | `.claude/skills/jarvis-design/SKILL.md` |
| `/jarvis-planning` | `.claude/skills/jarvis-planning/SKILL.md` |
| `/jarvis-search` | `.claude/skills/jarvis-search/SKILL.md` |

Claude Code는 프로젝트 스킬을 세션 시작 시 발견하고, 사용자가 `/skill-name`으로 직접 호출하거나 요청 내용과 `description`이 맞을 때 자동으로 사용할 수 있습니다. 프로젝트 루트에서 `claude`를 시작해야 해당 `.claude/skills/`가 검색됩니다.

## Claude Code 시작

```bash
cd /path/to/jarvis-luna
claude
```

Windows PowerShell에서는 다음처럼 실행합니다.

```powershell
Set-Location "$env:USERPROFILE\Desktop\jarvis-luna"
claude
```

## 실제 적용 예시 1: 조사부터 Obsidian 반영까지

```text
/jarvis-planning
이 YouTube URL을 JARVIS에 추가한다. 먼저 현재 저장소와 Obsidian Index를 조사하고, 실제 원문 확인 → Markdown 기록 → Source/Topic/Index wikilink → dangling-link 검증 → GitHub 저장 순서를 계획해라. 각 단계의 완료 기준을 먼저 보여줘.
```

계획이 승인되면 다음처럼 실행한다.

```text
/jarvis-search
https://www.youtube.com/watch?v=VIDEO_ID 를 조사해라. 원영상과 독립적인 공개 출처를 확인하고, 확인된 제목·요약·출처 URL·수집 시각·불확실성을 Markdown으로 저장해라. 자막이나 원문에 접근할 수 없으면 추측하지 말고 limitation에 기록해라.
```

```text
/jarvis-token-saving
방금 만든 기록만 대상으로 작업해라. 전체 Obsidian 볼트를 읽지 말고 Index와 새 파일부터 확인해라. 중복 파일을 다시 읽지 말고, 필요한 검증은 결정론적 스크립트로 실행해라.
```

```text
/jarvis-design
새 기록과 대시보드 표시를 모바일에서 읽기 쉽게 정리해라. 정적 숫자는 만들지 말고 data/dashboard_runtime.json의 실제 값을 사용해라. 수정 후 표시 값과 runtime 값을 비교해라.
```

## 실제 적용 예시 2: 한 번의 Claude 대화에서 직접 사용

Claude chat에 파일을 첨부할 수 있다면 먼저 네 개의 Obsidian 기록 파일 또는 이 가이드와 관련 실행용 `SKILL.md`를 첨부한다. 이어서 다음 프롬프트를 사용한다.

```text
첨부한 네 가지 규칙을 적용해 주세요. 이 작업은 실제 공개 출처만 사용해야 합니다.

1. Planning 규칙으로 작업 범위와 완료 기준을 먼저 제시하세요.
2. Search 규칙으로 원문과 출처를 확인하세요.
3. Token Saving 규칙으로 필요한 파일만 읽으세요.
4. Design 규칙으로 결과 Markdown의 구조와 가독성을 정리하세요.
5. 확인하지 못한 내용은 사실처럼 쓰지 말고 불확실성으로 표시하세요.
6. 최종 결과에는 생성·수정 파일과 검증 결과를 표로 보고하세요.
```

Claude chat에서 로컬 파일을 자동으로 읽지 못하는 경우에는 `@파일경로` 기능을 지원하는 환경에서 파일을 명시하거나, 파일 내용을 대화에 첨부해야 한다. 단순히 GitHub URL을 프롬프트에 적는 것만으로는 Claude가 해당 파일을 자동으로 읽는다고 보장할 수 없다.

## 확인 명령

Claude Code에서 스킬 검색과 직접 호출을 확인한다.

```text
/help
/jarvis-search
```

작업 후 저장소에서 다음을 실행한다.

```bash
python scripts/validate_dashboard_runtime.py
python /home/ubuntu/skills/jarvis-knowledge-moe-obsidian/scripts/audit_pipeline.py .
```

스킬 파일이 보이지 않으면 Claude Code를 저장소 루트에서 다시 시작하고, 파일명이 정확히 `.claude/skills/<name>/SKILL.md`인지 확인한다. `SKILL.md`의 YAML frontmatter에는 반드시 `name`과 `description`이 있어야 하며, `description`은 언제 사용할지를 명확히 설명해야 한다.

## 출처

[Claude Code Skills 공식 문서](https://code.claude.com/docs/en/skills)

[Claude Code `.claude` 디렉터리 공식 문서](https://code.claude.com/docs/en/claude-directory)

[Claude custom skills 공식 도움말](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills)
