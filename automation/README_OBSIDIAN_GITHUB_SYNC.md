# Obsidian ↔ GitHub 실제 동기화

이 자동화는 Obsidian 볼트 전체가 아니라 볼트 안의 `JARVIS_LUNA` 전용 폴더만 GitHub 저장소의 `obsidian/JARVIS_LUNA` 폴더와 양방향 동기화합니다. 따라서 개인 노트나 다른 볼트 폴더는 읽거나 변경하지 않습니다.

## 처음 한 번 설정하기

Windows에서 이 저장소를 원하는 폴더에 내려받고, `automation` 폴더를 엽니다. `obsidian_sync_config.example.json` 파일을 복사하여 이름을 `obsidian_sync_config.json`으로 바꾼 뒤, `vault_path`에 실제 Obsidian 볼트의 전체 경로를 입력합니다.

```json
{
  "vault_path": "C:\\Users\\사용자이름\\Documents\\Obsidian\\내볼트",
  "workspace_subfolder": "JARVIS_LUNA",
  "remote_name": "origin",
  "branch": "main"
}
```

`workspace_subfolder`는 기본값인 `JARVIS_LUNA`로 유지합니다. 첫 실행 시 해당 폴더와 `JARVIS Dashboard Sync.md` 안내 노트가 볼트 안에 자동 생성됩니다.

## 첫 동기화 확인

명령 프롬프트에서 저장소의 `automation` 폴더로 이동한 뒤 아래 명령으로 실제 변경 없이 점검합니다.

```bat
py -3 obsidian_github_sync.py --config obsidian_sync_config.json --dry-run
```

문제가 없으면 아래 파일을 더블클릭해 한 번 동기화합니다.

```text
run_obsidian_sync.bat
```

동기화 로그는 `automation/logs/obsidian_sync.log`에 기록됩니다. 개인 볼트 경로와 로그는 `.gitignore`로 보호되므로 GitHub에 업로드되지 않습니다.

## 5분 자동 실행 등록

PowerShell을 열고 저장소의 `automation` 폴더에서 다음 명령을 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\register_obsidian_sync_task.ps1
```

이후 Windows 작업 스케줄러가 5분마다 `run_obsidian_sync.bat`을 실행합니다. 작업 이름은 `JARVIS LUNA Obsidian GitHub Sync`입니다.

## 동기화 규칙과 충돌 처리

GitHub에서 바뀐 파일은 Obsidian 전용 폴더로 내려받고, Obsidian 전용 폴더에서 바뀐 파일은 GitHub로 커밋·푸시합니다. 양쪽에서 같은 파일이 동시에 바뀌면 Obsidian의 현재 파일을 보존하고 GitHub 버전은 같은 폴더에 `github-conflict-날짜시간` 파일명으로 남깁니다. 충돌 사본은 사용자가 비교 후 정리하면 됩니다.

> 주의: 자동화가 실행되기 전에 저장소의 다른 파일을 수정해 둔 경우, 의도치 않은 커밋을 막기 위해 동기화를 중단합니다. 먼저 기존 변경을 커밋하거나 정리한 뒤 다시 실행하세요.

## 대시보드 상태

성공적인 동기화는 `data/obsidian_sync_status.json`을 GitHub에 반영합니다. GitHub Pages 대시보드는 이 파일을 기준으로 Obsidian 상태를 녹색으로 바꿀 수 있습니다. 현재는 실제 볼트 경로가 설정되기 전이므로 붉은 `연동 미설정` 상태가 정상입니다.

## 기존 GitHub Actions 동기화 워크플로

기존의 `obsidian_sync.yml` 워크플로는 사용자의 컴퓨터에 있는 Obsidian 볼트에 접근할 수 없으므로 수동 실행 전용으로 전환했습니다. 실제 자동 동기화는 반드시 사용자의 Windows 컴퓨터에서 `run_obsidian_sync.bat`과 작업 스케줄러를 통해 실행됩니다.
