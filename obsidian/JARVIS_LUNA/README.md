# JARVIS LUNA 볼트

이 폴더가 **Obsidian 볼트이자 Git 저장소의 일부**입니다. 별도의 복사나 동기화
과정이 없습니다. 여기에 쓴 노트가 곧 저장소의 파일이고, GitHub Actions가 만든
노트가 곧 이 볼트의 노트입니다.

## 여는 방법

Obsidian → 왼쪽 아래 볼트 아이콘 → **다른 폴더를 볼트로 열기** →
`C:\Users\Desktop\Claude\Projects\kms\jarvis-luna\obsidian\JARVIS_LUNA`

테마·그래프뷰 설정은 `.obsidian/`에 이미 들어 있어 열자마자 적용됩니다.
그래프뷰는 자료·주제·출처가 서로 다른 색으로 표시되도록 맞춰 두었습니다.

## 채워지는 방식

GitHub Actions의 `JARVIS Deep Analysis`가 30분마다 arXiv와 YouTube에서 자료를
수집해 `Knowledge/` 아래에 노트를 만들고 저장소에 커밋합니다.

    Knowledge/Records/    개별 자료 노트 (논문·영상 하나당 한 장)
    Knowledge/Topics/     주제 노트 (AI Research, Model Routing and MoE 등)
    Knowledge/Sources/    출처 노트 (arXiv, YouTube)
    Briefings/            직접 작성한 분석 노트
    JARVIS Graph Hub.md   전체 진입점

`Knowledge/` 아래 생성 폴더는 매 실행마다 다시 만들어집니다. **직접 쓴 노트는
`Briefings/`나 새로 만든 폴더에 두세요.** 생성 폴더에 두면 다음 실행에서
덮어씌워집니다.

## 자동 동기화

`automation/register_vault_sync.ps1`을 한 번 실행하면 30분마다 자동으로
`git pull`과 `git push`가 돌아갑니다. 새 노트가 알아서 들어오고, 내가 쓴 노트는
알아서 올라갑니다.

수동으로 돌리려면 `automation/vault_sync.bat`을 더블클릭하면 됩니다.
결과는 `automation/vault_sync.log`에 쌓입니다.

## 주의

`.obsidian/workspace.json`(창 배치)과 캐시는 Git에서 제외했습니다. PC마다 값이
달라 매번 충돌을 일으키기 때문입니다. 테마·그래프 설정은 공유됩니다.
