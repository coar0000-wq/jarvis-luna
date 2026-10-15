# JARVIS 로컬 분석 도구 실제 설치

검증일: 2026-10-14 KST. 이 문서는 영상 검토와 실제 도구 실행을 구분한다.

## 실제 설치·실행 확인

- REA `6.4.0`, Ghidra `12.1.4`, Temurin full JDK `21.0.12.1+1`, Windows x64.
- 공식 Ghidra ZIP SHA256: `ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db`.
- 공식 JDK ZIP SHA256: `f9d6e191ab098c0d416e7d588a24420a8621cd2f4720dab2459b8b7b2d2d8b4e`.
- `rea doctor --provider ghidra`: 정상. 실제 Windows Job Object, private DACL, reparse-safe handle 검사 통과. 이 검사는 분석 엔진에 대한 일반 샌드박스 보장이 아니다.
- 실제 stdio MCP initialize, 도구170개·프롬프트6개, `binary_session` 검증 통과.
- 직접 작성한 1,536-byte PE64 DLL을 CLI와 MCP에서 실제 분석했다. 함수2개·문자열3개 확인, `jarvis_answer`에서 `MOV EAX, 0x2a; RET`와 `return 0x2a` 복구.
- MCP `open_binary`, `binary_overview`, `list_procedures`, `analyze_function`, `close_binary` 실제 성공. 원본 SHA256 `e5823f1dfdc6ad71d2523c25aa40832ccbdfbdfe82709de429d89c77033de49f` 전후 동일. 대상 DLL을 실행하지 않았다.
- Aside REA stdio 서버 설정을 추가했고 기존 Manus 설정을 그대로 보존했다. 위 호출은 실제 SDK→REA stdio 검증이며, 현재 대화의 동적 Aside 도구 목록 재연결을 따로 입증한 것은 아니다.
- Java heap512M, 저우선순위, 한 번에 한 분석 프로세스. 대형 대상은 별도 메모리 검증이 필요하다.

## EmbeddingGemma 2

- 별도 venv에 `sentence-transformers 6.1.0`, `transformers 5.19.0`, `torch 2.14.1` 설치 및 `pip check` 통과.
- 공개 Apache2.0 `google/embeddinggemma-2` revision `914f7f89142e33e77833254d9c9b90c3cef7303b` 고정.
- 1,488,915,288-byte checkpoint SHA256 `197a32965d4b1105faf060417baa899e193fb73cd401f42ec9295234d5553d79` 및 tokenizer LFS 해시 확인.
- 텍스트/코드270M 설정, CPU BF16, 오프라인, `trust_remote_code=False`. FP16은 사용하지 않는다.
- 실제 추론 검증 **4/4 통과**: 텍스트와 코드에서 각각768d·정규화256d를 생성하고 모든 벡터 유한값·단위 길이·정답top1을 확인했다. 실제 로드271,002,624 parameters, CPU AVX2 software BF16, peak RSS1,372,971,008 bytes, 테스트37.968초. 이는 작은 소유 fixture 실측이며 전체 지식 검색 품질/벤치마크를 입증하지 않는다.
- 256d 실제 top1 cosine: 텍스트0.8697633, 코드0.7554138. 별도 실사용 `search.py` CLI도 정답문서top1 및 종료코드0 확인. 명시적으로 선택한 JSON 문서만 읽고 자동 파일 탐색을 하지 않으며 기본256-token truncation 한계를 표시한다.
- 2026-10-15 추가 이미지 검증 **3/3 통과**: 직접 작성한 빨간 사각형·파란 원·초록 삼각형 PNG를 실제 이미지768d로 임베딩하고 텍스트 질의의 정답top1을 확인했다. 텍스트/이미지438,760,448 parameters, CPU FP32,57.8224초, peak RSS3,188,432,896bytes. 별도 로컬 `vision-evidence.json`에 원본 해시·행렬·유한값·정규화 검사와 실제 점수를 보존했다.
- 이 AVX2 CPU의 vision BF16 시도는 첫 이미지가 약5분 동안 완료되지 않아 소유한 프로세스만 중단했고, FP32 재시도1회에서 성공했다. 이미지에는1024-token context와 충분한 물리/commit 여유가 필요하다. 이는 단순 소유 fixture 검사이지 실제 상품 이미지 검색 정확도나 전체 지식 검색 성능 개선 증거가 아니다. 오디오·영상 추론은 검증하지 않았다.
- 첫 pip 실행이 상속된 플랫폼 `PIP_PREFIX`를 따라 공용 런타임에 설치된 환경변수 충돌이 있었다. 삭제/강제 롤백 없이 별도 venv로 다시 설치했고 두 환경의 의존성 검사를 통과했다. 후속 설치는 명시적 owned prefix만 사용한다.

## JARVIS 호출 경로

설치 바이너리·모델 캐시·머신별 `config.local.json`은 개인 PC의 영구 도구 디렉터리에 있고 Git에 올리지 않는다.

```powershell
$env:JARVIS_LOCAL_TOOLS_ROOT = '<영구 설치 디렉터리>'
./scripts/run_local_analysis_tools.ps1 -Mode doctor
./scripts/run_local_analysis_tools.ps1 -Mode inspect -Target '<소유하거나 분석 허가를 받은 DLL>' -AuthorizedTarget
./scripts/run_local_analysis_tools.ps1 -Mode function -Target '<허가받은 DLL>' -Procedure jarvis_answer -AuthorizedTarget
./scripts/run_local_analysis_tools.ps1 -Mode embedding-smoke
./scripts/run_local_analysis_tools.ps1 -Mode embedding-search -Documents '<선택한 [{id,text}] JSON>' -Query '<검색 질문>' -Dimension 256
```

이 연결은 로컬 JARVIS/Aside용이다. GitHub-hosted Actions에는 이 PC의 바이너리나 모델이 없으며, GitHub 팀 작업이 자동으로 이 엔진을 실행했다고 주장하지 않는다. 분석 결과는 파생 증거이고 원본 소스·실제 런타임 행동·법률 승인·판매 승인으로 승격하지 않는다.

## 설치하지 않은 항목

- **Hopper [blocked]**: 현재 호스트는 Windows이며 공식 Windows 네이티브 버전은 대기 상태. Linux 배포판도 설치되어 있지 않다. 데모를 무료 상업 운영 라이선스로 간주하지 않으며 OS·라이선스 변경이나 구매를 하지 않았다.
- **IDA [blocked]**: 기존 설치 및 사용 가능한 계정 단서를 찾지 못했다. IDA Free는 비상업용이고 SDK/IDAPython이 없어 상업용 JARVIS REA 연동으로 대체할 수 없다. 기존 상업용 라이선스·설치 경로와 정식 upstream MCP가 있어야 연동 가능하다. 라이선스 키를 공개하지 않는다.

## 카피 게시 가드

`shopify_import_report.json`의 이전 skipped 진단 행이 현재 후보8개로 교체되며 발생한 identity removal을 보고서 한 경로에만 허용한다. 정확한 기존/새 바이트 SHA256과 삭제 사유가 필수이고 hash 누락·변조·동시 변경·필드/빈 증거 삭제는 거부한다. `base_commit`은 과거 보고서 위치 기록이며 publisher가 독립 검증하는 것은 정확한 바이트 해시다. 제품·라벨·안전·owner-deleted1049275 제약은 그대로 유지한다. 추가로 `shopify_listing_copy.json`의 과거 초안10개를 현재 S8개로 정리할 때, 이전 공개 초안을 `draft_history`에 별도 해시와 `historical_not_approval=true`로 보존한다. 기존 history는 변경하지 않고 시간 갱신만으로 이력을 늘리지 않는다. 현재 항목은 정본 S·게이트와 일치해야 하며, 과거 초안은 CSV·등록 가능 개수에 포함하지 않는다.

2026-10-15 최신 정본 위에서 카피 교체7개·보고서15개·기존 로컬 카피14개·전체 publisher46개, 총82개 테스트 통과. 테스트 입력은 고정된 격리 fixture이고 현재 데이터 갱신 후에도 유지된다. 별도로 실제 최신 데이터를 복사한 격리 교체도 검증했고 원본 바이트는 그대로다. 실제 게시 검증용 `workflow_dispatch.offline_verification=true`는 TypeSafe·Gemini API를 비활성화하고 로컬 생성·안전 게이트·게시 검증은 유지한다. 평상시 자동화 동작은 바꾸지 않는다. 실제 카피 발행38721329955와 Pages38721669510은 성공했고, 현재8개·등록 가능0·CSV0행·과거10개 비승인 이력을 원격에서 확인했다. 교체 회귀 테스트22개는 `preflight.yml`에도 연결했다.

## 공식 근거

- https://github.com/morluto/rea/blob/main/docs/windows-ghidra-p0.md
- https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.1.4_build
- https://adoptium.net/temurin/releases?version=21
- https://developers.googleblog.com/embeddinggemma-2-the-developer-guide
- https://huggingface.co/google/embeddinggemma-2
- https://www.hopperapp.com/faq.html
- https://hex-rays.com/ida-free
