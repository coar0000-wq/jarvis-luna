# Actions 재현성과 운영 설명

## 지원 대상과 잠금

`requirements/requirements-*.txt`는 CPython 3.11, Linux x86_64, glibc 2.28 이상용 직접·간접 의존성 잠금이다. 버전과 실제 내려받은 wheel SHA-256을 모두 기록했다. 2026-10-03 PyPI 릴리스 메타데이터의 해시와 다운로드 파일 해시를 독립적으로 대조했고, 대상 플랫폼 wheel로 의존성을 해결했다. 소스 빌드나 Windows 설치용 범용 잠금은 아니다.

```sh
python -m pip install --require-hashes --only-binary=:all: -r requirements/requirements-verification.txt
```

`pip install --upgrade pip`, 버전 범위 설치, 설치 실패를 `|| true`로 숨기는 경로는 사용하지 않는다. `lock-manifest.json`에는 wheel 파일명·출처·Python 조건·해시·전이 의존성·프로필 및 실제 GitHub API에서 확인한 Action 태그의 커밋이 있다. CI 런타임을 3.11로 정렬해야 한다. 수동 전용 Legacy Obsidian은 표준 라이브러리만 쓰므로 기존 3.10 자체를 의존성 잠금이라고 주장하지 않는다.

| 프로필 | 대상 | 핵심 패키지 |
| --- | --- | --- |
| verification | preflight, 검증 Pages | PyYAML 6.0.3, pyflakes 3.4.0 |
| core | Core, 표준 라이브러리 수집·운영 공통 게이트 | verification + requests 2.34.2 |
| daiso | 다이소, 루트/카피 HTTP·HTML 수집 | core + beautifulsoup4 4.15.0, lxml 6.1.3 |
| deep | Deep Analysis의 실제 NumPy 모델 경로 | daiso + numpy 2.4.6 |
| knowledge | Real Knowledge Sync의 실제 NumPy 모델 경로 | deep과 동일한 폐쇄 집합 |
| browser | 고시 alt, 미국 리테일, Deep의 조건부 브라우저 | daiso + playwright 1.63.0 + pyee/greenlet |
| vision | 고시 이미지 수집 | daiso + Pillow 12.3.0 |
| pdf | INCI 정본 PDF 수집 | daiso + pypdf 6.19.0 |

모든 프로필은 공통 발행/품질 판정에 필요한 PyYAML을 포함한다. Core의 실제 세 수집 스크립트와 Deep의 현재 `train_real_knowledge.py`, `tune_real_knowledge_moe.py`, `team_router_moe.py`를 대조했다. 실제 학습은 NumPy이고 PyTorch를 사용하지 않는다. 과거 `requirements.txt`의 torch·matplotlib·google-generativeai 등 넓은 범위는 현재 자동화 프로필에 무조건 설치하지 않는다. 과거 파일은 삭제하지 않으며, 다른 수동 도구를 실행한다면 별도 잠금을 먼저 만들어야 한다.

NumPy 최신 2.5.3은 Python >=3.12이므로 3.11에 설치할 수 없다. cp311 Linux wheel이 확인된 2.4.6으로 고정했다. Playwright Python 버전은 다운로드되는 Chromium revision을 고정하지만 `playwright install --with-deps chromium`의 Ubuntu 시스템 패키지 저장소까지 잠그지는 않는다. Actions의 `ubuntu-latest`와 Python patch release가 바뀔 수 있으므로 OS/런타임 전체의 비트 단위 동일성을 주장하지 않는다.

## Action과 업데이트

활성 `.github/workflows/*.yml`, `*.yaml` 및 composite action의 공개 Action `uses`는 검증한 전체 커밋 SHA로 고정한다. 원래 태그는 주석으로 보존한다. `.disabled` 보관 파일은 GitHub가 실행하는 워크플로가 아니며 배포 경로나 활성 의존성 검사 대상으로 세지 않는다. 보관 파일에 발견된 `actions/setup-python@v5.2`는 실제 태그 조회에서 404였으므로 임의의 SHA를 만들지 않고 보관 사실을 남긴다.

Dependabot은 주간 Action/Python 잠금 변경 PR만 제안한다. 자동 병합하지 않는다. 패키지를 올릴 때 대상 Linux 3.11 wheel을 다시 해결·다운로드하고, PyPI SHA와 파일 해시를 대조하며, 모든 영향을 받는 프로필과 `lock-manifest.json`을 함께 갱신해야 한다. manifest가 오래된 상태면 회귀 검사가 실패하도록 한다. Action 업데이트도 실제 저장소 커밋과 릴리스 변경을 확인한 뒤 검증한다.

검사: `python scripts/test_dependency_pins.py`. 이 검사는 버전/해시 형식, 프로필과 manifest 일치, 전이 의존성 폐쇄, 활성 Action SHA, 해시 기반 설치, Dependabot 검토 경로를 오프라인에서 확인한다. 외부 네트워크가 바뀌어도 이 테스트는 PyPI나 GitHub를 재조회하지 않는다.

## 현재 실행 주기와 이름 연결

2026-10-03 저장소 설정과 대조한 UTC/KST 설명이다. GitHub cron은 UTC이며 정시 보장이 아니다. 큐·동시 실행 잠금·러너 지연으로 실제 시작은 늦어질 수 있다.

| 파일 | UTC cron | KST 기준 |
| --- | --- | --- |
| JARVIS-Core-Automation.yml | `43 1-23/2 * * *` | 매일 짝수 시 43분, 2시간마다 |
| JARVIS-Deep-Analysis.yml | `17 */2 * * *` | 매일 홀수 시 17분, 2시간마다 |
| daiso-real-collection.yml | `20 19 * * *` | 매일 다음 날짜 04:20 |
| gemini-web-collect.yml | `40 20 * * *` | 매일 다음 날짜 05:40 |
| gosi-alt.yml | `40 18 * * *` | 매일 다음 날짜 03:40 |
| gosi-vision.yml | `0 */6 * * *` | 매일 03:00, 09:00, 15:00, 21:00 |
| inci-dictionary.yml | `10 20 1 * *` | 매월 2일 05:10 |
| jarvis-real-knowledge.yml | `37 0,6,12,18 * * *` | 매일 03:37, 09:37, 15:37, 21:37 |
| root-collectors.yml | `41 2 * * *` | 매일 11:41 |
| serpapi-market.yml | `0 20 * * 1,4` | 화·금 05:00 |
| us-retail-collect.yml | `40 20 * * *` | 매일 다음 날짜 05:40 |

Core의 오래된 '매 10분' 주석과 YouTube '중단' 단계명은 실제 cron 및 Atom RSS 실행과 맞지 않았다. 실행 중인 실제 수집과 중단된 과거 방법을 구분해 정리한다. 제거된 가짜 다이소 생성 단계는 변경 이력으로 설명하고 실제 수집은 별도 일일 워크플로가 담당한다. 이름을 변경할 때 `pages-verified.yml`의 `workflow_run.workflows`는 파일명이 아니라 `name:` 문자열을 참조하므로 동시에 수정해야 한다. `GITHUB_TOKEN` 발행 후에는 일반 push가 다시 실행되지 않으므로 성공한 수집의 workflow_run 연결을 유지한다.

## 재현성의 범위

잠금만으로 실시간 외부 데이터나 학습 결과가 같아지지는 않는다. 동일 입력 스냅샷·정책·코드·의존성, 학습 seed, 허용 수치 오차 및 기존 모델 유지 정책을 함께 검증한다. 소스 조회 시각만 바뀐 파일을 새로운 내용으로 간주하지 않는다. 실제 성공 조회, 내용 변경, 캐시 사용과 실패는 수집 결과/품질 보고에서 따로 기록한다. HTTP 200이나 프로세스 exit 0만으로 정상 조회를 증명하지 않는다.

이번 잠금 검증은 패키지를 설치하거나 모델/API를 실행하지 않고 wheel 다운로드와 해시 검증만 수행했다. 실제 Linux CI의 설치·회귀 검사와 격리된 고정 입력 학습 검증을 통과하기 전에는 전체 모델 경로의 재현성을 완료했다고 보고하지 않는다.
