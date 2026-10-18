# JARVIS LUNA 서브 에이전트 및 통신 아키텍처 설계 명세서 (v2)

## 1. 개요 및 도입 목적

JARVIS LUNA 운영 시스템은 `도윤` > `비서실장` > `기존 11팀장` > `전문 기능`으로 이어지는 계층적 지휘 체계와 L1~L4 단계별 권한 통제 게이트를 기반으로 구축되어 있습니다.

글로벌 커머스 채널(Amazon, TikTok Shop, Walmart, Sephora 등)의 다각화된 수집과 대용량 데이터 처리가 확대됨에 따라, 메인 판단 모델(Jev) 및 11팀장의 컨텍스트 윈도우 오염 및 토큰 비용 폭증을 방지하기 위해 **서브 에이전트(Sub-agents/Helpers) 분리 아키텍처**와 **표준 통신 규격(Team Handoff Protocols)**을 구현합니다.

---

## 2. 핵심 아키텍처 원칙

1. **오케스트레이터(Orchestrator)와 헬퍼(Helper)의 역할 분리**
   - **메인 에이전트 (Jev & 11팀장)**: 전체 비즈니스 맥락, 할 일 목록(Task Engine), 팀 간 작업 인계(Team Handoff), 최종 판단 보조 및 승인 요청만 담당합니다.
   - **서브 에이전트 (전문 기능 헬퍼)**: 각 개별 수집 채널 모니터링, 대용량 원시 데이터 분석, 파일 오프로딩, 복구 검증 등 토큰 소모가 큰 실무 작업을 개별 독립 메모리(Fresh Working Memory)상에서 실행합니다.

2. **컨텍스트 오염 방지 및 파일 오프로딩 (File Offloading)**
   - 서브 에이전트는 작업 처리 과정의 수백 개 쉘 명령어나 대용량 원시 데이터(HTML/JSON)를 메인 에이전트 대화창에 넣지 않습니다.
   - 원시 데이터는 파일 시스템에 저장하고, 작업 완료 후 **핵심 요약(Summary)** 및 **검증 영수증(Verification Receipt)**만을 메인 오케스트레이터에 제출합니다.

3. **L1~L4 권한 게이트 및 판단-실행 분리 엄수**
   - 서브 에이전트는 L1(읽기) 및 L2(로컬) 범위 내에서만 자율 작동합니다.
   - L3(조건부) 및 L4(사람 승인 및 외부 쓰기) 작업이 필요한 경우, 직접 실행하지 않고 초안(Draft)을 작성하여 `Approval Gate`로 라우팅한 후 **고정 실행기(Fixed Executor)**가 실행하도록 통제합니다.

---

## 3. 계층별 서브 에이전트 배치 구조

```
[ 도윤 / 비서실장 / Jev (판단 보조) ]
              │
              ▼
    [ 11팀장 (Orchestrator) ] ── (최소 컨텍스트 & Task Engine)
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
[Helper 1] [Helper 2] [Helper 3] ── (독립 워킹 메모리 & 서브 에이전트)
    │         │         │
    ▼         ▼         ▼
 [L1/L2]   [L1/L2]   [L1/L2]    ── (자율 수행: 소스 감시, 파일 오프로딩)
    │         │         │
    └─────────┼─────────┘
              ▼
    [ Approval Gate ]           ── (L3/L4 변경 및 외부 반영 통제)
              │
              ▼
   [ Fixed Executor ]           ── (사전 승인된 고정 실행기)
```

### 서브 에이전트 풀(Pool) 상세 명세

1. **`Watch-Event Helper` (L1 소스 감시 전담 헬퍼)**
   - **대상 채널**: TikTok Shop US, Amazon Best Sellers, Walmart Beauty, Sephora, OliveYoung US 등.
   - **동작**: 백그라운드에서 각 수집 채널을 개별 스케줄(Routine)에 따라 스캔하고, 원시 HTML/JSON 데이터는 파일 시스템에 오프로딩합니다.
   - **보고 조건**: S등급 후보 상품 발견 또는 채널 상태 이상 발생 시에만 메인 팀장에게 브리핑 요약을 제출합니다.

2. **`Audit-Recovery Helper` (L2 복구 및 영수증 검증 헬퍼)**
   - **대상**: 소스 관찰 차단, 네트워크 장애 시 담당 팀 복구 큐 추적.
   - **동작**: 2시간 쿨다운 및 최대 2회 재시도 규칙을 준수하며, 소스 재관찰 및 검증 영수증 일치 여부를 독자 검증합니다.
   - **보고 조건**: 실제 외부 검증 영수증 확인 결과를 불변 감사 기록(Audit Log)에 기록하고 완료 보고서를 인계합니다.

3. **`Draft-Generation Helper` (L3/L4 외부 반영 초안 헬퍼)**
   - **대상**: Shopify 상품 등록 원고, 마케팅 문구 및 외부 공유 리포트 작성.
   - **동작**: 프롬프트 인젝션 방지 및 보안 가이드라인에 맞춰 외부 반영 초안(Draft)을 작성합니다.
   - **보고 조건**: 작성된 초안을 `Approval Gate`로 라우팅하여 Jev 판단 검증 및 사람 승인을 대기하도록 설정합니다.

---

## 4. 메인-서브 에이전트 통신 규격 및 팀 간 인계 (Team Handoff)

### 4.1 통신 아키텍처 기본 원칙
1. **페이로드 파일 오프로딩**: 수집 원시 데이터는 파일 시스템 경로(`payload_file_path`)로 전달합니다.
2. **원자적 요약 보고**: 서브 에이전트는 완료 시 `summary`와 `verification_receipt`만을 오케스트레이터에 반환합니다.
3. **권한 승인 라우팅**: L4 작업 감지 시 `L4_APPROVAL_REQUIRED` 상태로 승인 게이트(`Approval Gate`)에 라우팅합니다.

### 4.2 JSON 메시지 통신 규격 (Machine-to-Machine)

#### 1) 작업 발주 메시지 (Main Agent ➔ Sub-Agent)
```json
{
  "$schema": "https://jarvis-luna.internal/schemas/task-dispatch.v1.json",
  "task_id": "TASK-20261017-TIKTOK-001",
  "parent_trace_id": "TRACE-990123-JEV",
  "timestamp": "2026-10-17T20:00:00Z",
  "orchestrator": {
    "team_id": "TEAM-03-MARKETING",
    "agent_role": "11팀장 (마케팅 조사 분석)"
  },
  "target_subagent": {
    "helper_type": "Watch-Event-Helper",
    "channel_target": "TikTok Shop US"
  },
  "authorization": {
    "allowed_level": "L1",
    "max_execution_sec": 300
  },
  "payload": {
    "instruction": "TikTok Shop US 뷰티 카테고리 실시간 베스트셀러 S등급 후보 상품 탐색 및 원시 데이터 수집",
    "context_files": [
      "/workspace/knowledge/specs/beauty_s_class_criteria.md"
    ],
    "output_file_path": "/workspace/scratch/raw_tiktok_20261017.json"
  }
}
```

#### 2) 작업 완료 및 결과 보고 메시지 (Sub-Agent ➔ Main Agent)
```json
{
  "$schema": "https://jarvis-luna.internal/schemas/task-report.v1.json",
  "task_id": "TASK-20261017-TIKTOK-001",
  "timestamp": "2026-10-17T20:03:15Z",
  "subagent": {
    "helper_id": "HELPER-WATCH-TIKTOK-04",
    "helper_type": "Watch-Event-Helper"
  },
  "status": "SUCCESS",
  "execution_summary": {
    "items_scanned": 150,
    "s_class_candidates_found": 2,
    "summary_text": "TikTok Shop US 뷰티 카테고리 150개 상품 스캔 완료. S등급 기준(평점 4.8+, 일 판매량 500+)을 충족하는 후보 2건 발견."
  },
  "offloaded_data": {
    "raw_result_file": "/workspace/scratch/raw_tiktok_20261017.json",
    "processed_summary_file": "/workspace/scratch/summary_tiktok_20261017.json"
  },
  "verification_receipt": {
    "receipt_id": "VR-20261017-88912",
    "source_hash": "sha256-e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "evidence_captured": true
  },
  "next_recommended_action": {
    "target_team": "TEAM-01-PRODUCT-DISCOVERY",
    "action_type": "QUALIFY_S_CLASS"
  }
}
```

#### 3) L4 외부 쓰기 초안 제출 메시지 (Sub-Agent ➔ Approval Gate)
```json
{
  "$schema": "https://jarvis-luna.internal/schemas/l4-draft-request.v1.json",
  "draft_id": "DRAFT-20261017-SHOPIFY-08",
  "timestamp": "2026-10-17T20:04:00Z",
  "origin_subagent": "Analysis-Verification-Helper",
  "target_action": "SHOPIFY_PRODUCT_CREATE",
  "gate_level_required": "L4",
  "auto_review_precheck": {
    "passed": true,
    "security_score": 0.98,
    "prompt_injection_detected": false
  },
  "proposed_execution_payload": {
    "executor_type": "Fixed-Shopify-API-Executor",
    "endpoint": "/admin/api/2026-10/products.json",
    "product_data": {
      "title": "[CoarFamily] Skin Care Sun Cream (S-Class)",
      "price": "24.99",
      "sku": "COAR-SUN-2026-01"
    }
  },
  "approval_status": "PENDING_HUMAN_APPROVAL"
}
```

### 4.3 마크다운 팀 간 인계 문서 템플릿 (Human & Agent Readable)

```markdown
# 🤝 [Team Handoff] 팀 간 작업 인계 보고서

- **Task ID**: `TASK-20261017-TIKTOK-001`
- **인계 일시**: `2026-10-17 20:04:00 (KST)`
- **발신 팀/에이전트**: 마케팅 조사 분석팀 (Watch-Helper-04)
- **수신 팀/에이전트**: 상품 발굴 전담팀 (Product-Discovery-Agent)
- **권한 승인 단계**: `L1 (수집 완료) ➔ L2 (로컬 검증 요청)`

---

### 1. 작업 개요 및 핵심 요약 (Summary)
- **수집 대상**: TikTok Shop US (뷰티 카테고리)
- **핵심 성과**: 스캔된 150개 상품 중 **S등급 적격 후보 2건** 발굴 완료.
- **오프로딩 파일 위치**: `/workspace/scratch/summary_tiktok_20261017.json`

---

### 2. 발굴 S등급 상품 후보 명단

| 상품명 | 일 판매량 | 평점 | 제안 판매가 | 검증 영수증 ID |
| :--- | :--- | :--- | :--- | :--- |
| Hydrating Cica Serum 50ml | 850건 | 4.9 | \$19.99 | `VR-20261017-88912` |
| Glow Daily Sunscreen SPF50+ | 620건 | 4.8 | \$22.50 | `VR-20261017-88913` |

---

### 3. 다음 팀 조치 사항 (Action Items)
- [ ] **상품 발굴팀**: 원가 대비 마진율 계산 및 다이소 Dropshipping 공급망 매칭 확인 (L2 로컬 실행)
- [ ] **Jev (판단 보조)**: S등급 적격성 검증 보고서 작성
- [ ] **비서실장/도윤**: L4 Shopify 최종 등록 승인 여부 결정

---

### 4. 검증 및 보안 서명 (Audit & Verification)
- **Source Hash**: `sha256-e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- **Auto-Review 검증**: `PASSED (Security Score: 0.98)`
- **불변 감사 기록 저장 완료**: `AUDIT-LOG-20261017-991`
```

---

## 5. L1~L4 권한 게이트 흐름 및 통제 요약

| 권한 단계 | 서브 에이전트 허용 역할 | 사람 / 메인 팀장 역할 | 고정 실행기 (Fixed Executor) 역할 |
| :--- | :--- | :--- | :--- |
| **L1 (읽기)** | 외부 소스 감시, 원시 데이터 수집 | 수집 대상 채널 지정 및 모니터링 | - |
| **L2 (로컬)** | 데이터 분석, 파일 가공, 영수증 생성 | 검증 영수증 수신 및 상태 확인 | - |
| **L3 (조건부)** | 복구 큐 자동 재시도, 내부 팀 인계 | 조건 초과 시 승인 요구 승격 관리 | 내부 데이터 큐 전달 |
| **L4 (외부 쓰기)** | **직접 실행 불가** (외부 초안 작성만 담당) | `Jev` 판단 보조 확인 후 최종 사람 승인 | **실제 외부 반영 명령 단독 실행** |

---

## 6. 컨텍스트 및 인프라 최적화 메커니즘

1. **동적 툴 발견 (Dynamic Tool Discovery)**
   - 수십 개 수집 채널 및 MCP 툴의 전체 스키마를 상시 프롬프트에 넣지 않고, 툴 이름 목록만 유지합니다.
   - 서브 에이전트가 실행 시점에 파일 시스템에서 해당 툴 명세를 동적으로 읽어와 호출함으로써 메모리를 보존합니다.

2. **Temporal 기반 내구성 있는 워크플로우 (Durable Workflow)**
   - 서브 에이전트 실행 중 메모리 초과나 샌드박스 재부팅이 발생하더라도, 처음부터 재실행하지 않고 중단된 단계부터 안전하게 재개(Retry)합니다.

3. **프롬프트 캐싱 및 백그라운드 컴팩션 (Compaction)**
   - 정적 가이드라인 및 툴 순서를 고정하여 캐시 할인을 극대화하고, 대화 이력의 사전 요약(Compaction)을 웜 캐시 유효 시간 내에 처리하여 토큰 비용을 최소화합니다.

---

## 7. 실행 및 도입 체크리스트

- [x] **구조 정의**: 메인 11팀장과 서브 에이전트 간 인계(Team Handoff) JSON 및 마크다운 데이터 규격 정의
- [x] **독립 메모리 확보**: 서브 에이전트 실행 환경의 워킹 메모리 분리 및 결과 요약 인터페이스 구축
- [ ] **게이트 연동**: 서브 에이전트 생성물이 L3/L4 단계에 진입할 때 고정 실행기(Fixed Executor) 호출 전 승인 게이트 필수 통과 검증
- [ ] **감사 기록**: 서브 에이전트의 모든 실행 및 영수증 확인 이력을 변경 불가능한 Audit Log에 저장
