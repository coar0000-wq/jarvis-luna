#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Product Master, gate, legal, marketing, Shopify exports의 조인 무결성 검사."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_signature  # noqa: E402
from operational_freshness import assess_collection  # noqa: E402


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate_retained_blocked_exports(root, export_dir):
    """No eligible drafts: only exact Git-retained bytes, never new clearance."""
    for name in ('products.csv','inventory.csv','images.csv','collections.csv'):
        target = Path(export_dir) / name
        require(not target.is_symlink() and target.is_file(), 'retained draft path invalid')
        rel = f'data/shopify_exports/{name}'
        baseline = subprocess.run(['git', 'rev-parse', f'HEAD:{rel}'],
                                  cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        current = subprocess.run(['git', 'hash-object', f'--path={rel}', str(target)],
                                 cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        require(baseline.returncode == 0 and current.returncode == 0
                and baseline.stdout.strip() == current.stdout.strip(),
                f'legally blocked draft changed or lacks committed baseline: {name}')


def digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_action_boundary(action, expected_payload):
    """Reconstructed source payload, not shallow queue approval flags."""
    expected_hash = digest(expected_payload)
    require(action.get("immutablePayload") == expected_payload, "immutablePayload/context mismatch")
    require(action.get("payload_hash") == expected_hash, "bound payload hash mismatch")
    require(action.get("state") == "WAITING_HUMAN_APPROVAL", "trusted verifier not configured")
    require(action.get("authenticated_authorization") is False, "unauthenticated authority")
    auth = action.get("authorization") or {}
    require(auth.get("status") == "unverified" and auth.get("verifier") == "not_configured"
          and auth.get("bound_payload_hash") == expected_hash, "authorization proof mismatch")
    require((action.get("execution") or {}).get("enabled") is False, "executor must stay disabled")
    require("approved_by" not in action and "approved_at" not in action, "private approver metadata")
    context = expected_payload["context"]
    configured = bool(context["target_shop"] and context["api_version"]
                      and isinstance(context["remote_preconditions"], dict)
                      and context["remote_preconditions"])
    require(action.get("target_configuration") ==
          ("configured" if configured else "unconfigured_blocked"), "target status mismatch")


def validate_sourcing_card(sourcing, *, observed_workflow_failure=False):
    """Statistics are notices; only evidenced failure/staleness is an action."""
    require(bool(sourcing.get("notice")), "소싱 실행 통계 notice 누락")
    action = str(sourcing.get("action") or "")
    evidence = sourcing.get("collection_freshness")
    if not isinstance(evidence, dict):
        require(not action or "발행되지 않음" in action,
                "정상 소싱 통계가 노란 조치로 분류됨")
        return
    for key in ("is_failure", "attempt_stale", "data_stale", "is_no_change"):
        require(type(evidence.get(key)) is bool, "소싱 최신성 증적 누락: " + key)
    issue = (evidence["is_failure"] or evidence["attempt_stale"]
             or evidence["data_stale"] or observed_workflow_failure)
    require(not action or issue, "정상 소싱 통계가 노란 조치로 분류됨")
    require(not issue or bool(action), "소싱 실패/최신성 조치 누락")
    if evidence["is_failure"]:
        require(sourcing.get("status") == "failed", "소싱 실패가 경고/정상으로 가려짐")
    elif evidence["is_no_change"]:
        require(sourcing.get("status") != "ok", "무변경 시도가 신규 수집 성공으로 가려짐")


def main() -> int:
    # 커머스 산출물을 갱신하는 개별 워크플로는 비서실장 runtime을 다시
    # 만들지 않는다. 그 실행들까지 운영 heartbeat 동기화를 강제하면
    # 정상적으로 채운 고시·라벨도 발행 직전에 막힌다. 최종 2시간 운영
    # 루프만 명시적으로 이 플래그를 켜 전체 runtime 정합성을 검사한다.
    require_ops_runtime = "--require-ops-runtime" in sys.argv[1:]

    source = load(D / "daiso_real" / "products.json")
    master = load(D / "product_master.json")
    score = load(D / "daiso_real" / "shopify_demand_score.json")
    srec = load(D / "daiso_real" / "shopify_s_recommendations.json")
    gate = load(D / "listing_gate.json")
    legal = load(D / "legal_full.json")
    market = load(D / "market_team.json")
    strategy = load(D / "shopify_marketing_strategy.json")
    insight_source = load(D / "manual" / "shopify_youtube_insights.json")
    action_queue = load(D / "shopify_action_queue.json")
    dashboard = load(D / "dashboard_runtime.json")
    chief = load(D / "agents" / "chief_of_staff.json")
    remediation = load(D / "agents" / "remediation_state.json")
    ops_plan = load(D / "agents" / "ops_plan.json")
    improvement = load(D / "team_improvement.json")
    error_report = load(D / "error_report.json")
    marketing_pipeline = load(D / "manual" / "multi_agent_marketing_pipeline.json")
    model_routing = load(D / "manual" / "model_routing_policy.json")
    gemini_escalation = load(D / "agents" / "gemini_escalation.json")

    # 게이트가 낡았으면 그 아래 조인은 전부 낡은 판정 위에 서 있다.
    # 이 검사가 없어서 예전에는 낡은 ready 로 만든 Action 도 OK 가 나왔다.
    require(not gate_signature.stale_reason(gate),
            gate_signature.stale_reason(gate) or "listing_gate 신선도 검사 실패")

    source_ids = {str(x["pd_no"]) for x in source.get("products") or []}
    registry = {str(k): str(v) for k, v in (master.get("pd_no_to_cp") or {}).items()}
    products = master.get("products") or []
    require(len(source_ids) == len(source.get("products") or []), "source pd_no 중복")
    require(len(registry) == len(set(registry.values())), "CP 중복")
    require({str(x["pd_no"]) for x in products} == source_ids, "Master 활성 상품 != source")
    require(all(registry[str(x["pd_no"])] == x.get("canonical_product_id") for x in products),
            "Master CP와 레지스트리 불일치")
    require(master.get("schema_version") == 3, "Product Master schema v3 필요")
    variant_groups = master.get("variant_groups") or []
    grouped_products = {}
    for product in products:
        variant = product.get("variant") or {}
        grouped_products.setdefault(str(variant.get("group_id") or ""), []).append(product)
    expected_groups = {gid: rows for gid, rows in grouped_products.items() if gid and len(rows) > 1}
    actual_groups = {str(x.get("group_id")): x for x in variant_groups}
    require(set(actual_groups) == set(expected_groups), "Variant 부모 Product 그룹 집합 불일치")
    for gid, group in actual_groups.items():
        members = expected_groups[gid]
        require(group.get("object_type") == "ProductVariantGroup", f"{gid} object_type 불일치")
        require(set(group.get("member_canonical_product_ids") or []) ==
                {x.get("canonical_product_id") for x in members}, f"{gid} Variant CP 관계 불일치")
        require(all((x.get("variant") or {}).get("relation", {}).get("target_group_id") == gid
                    for x in members), f"{gid} variant_of 관계 누락")

    scored = score.get("all_scored") or []
    require(all(x.get("canonical_product_id") == registry.get(str(x.get("pd_no"))) for x in scored),
            "점수 산출물 CP 불일치")
    recs = srec.get("recommendations") or []
    gate_rows = gate.get("items") or []
    rec_by = {str(x["pd_no"]): x for x in recs}
    gate_by = {str(x["pd_no"]): x for x in gate_rows}
    require(set(rec_by) == set(gate_by), "S 추천과 gate 상품 집합 불일치")
    require(all(bool(rec_by[k].get("registerable")) == bool(gate_by[k].get("ready")) for k in rec_by),
            "S registerable과 gate ready 불일치")
    require(all(bool(rec_by[k].get("public_ready")) == bool(gate_by[k].get("public_ready")) for k in rec_by),
            "S public_ready와 gate public_ready 불일치")
    require(all(rec_by[k].get("canonical_product_id") == registry.get(k) for k in rec_by),
            "S 추천 CP 불일치")
    require(all(bool(gate_by[k].get("agent_ready")) ==
                (len(gate_by[k].get("agent_blocked_by") or []) == 0) for k in gate_by),
            "agent_ready와 agent_blocked_by 불일치")
    require(all(bool(rec_by[k].get("agent_ready")) == bool(gate_by[k].get("agent_ready"))
                for k in rec_by), "S agent_ready와 gate 불일치")

    export_dir = D / "shopify_exports"
    with (export_dir / "products.csv").open(encoding="utf-8", newline="") as f:
        export_products = list(csv.DictReader(f))
    with (export_dir / "inventory.csv").open(encoding="utf-8", newline="") as f:
        inventory = list(csv.DictReader(f))
    export_ids = {x["pd_no"] for x in export_products}
    # 스토어 대상은 shortlist ∩ gate ready 다. S등급 전체를 내보내면 실패다 (2026-09-29).
    shortlist_doc = load(D / "shopify_shortlist.json")
    shortlist_ids = {str(x) for x in shortlist_doc.get("active_pd_nos") or []}
    require(bool(shortlist_ids), "Shopify shortlist 가 없거나 비어 있음")
    ready_ids = {k for k, x in gate_by.items() if x.get("ready") and k in shortlist_ids}
    if ready_ids:
        require(export_ids == ready_ids, "Shopify products.csv가 shortlist ∩ gate ready 집합과 다름")
    else:
        require(export_ids <= shortlist_ids, 'blocked retained export is outside selected scope')
        require(not (action_queue.get('draft_actions') or []), 'legal hold cannot propose new draft payloads')
        validate_retained_blocked_exports(ROOT, export_dir)
        print('SHOPIFY_EXPORTS_RETAINED_LEGAL_BLOCKED current_eligible=0 authority=false')
    guard = load(D / "shopify_sync_guard.json")
    require(guard.get("ok") is True, f"Shopify sync guard 위반: {guard.get('violations')}")
    require(all(x["Canonical Product ID"] == registry[x["pd_no"]] for x in export_products),
            "Shopify export CP 불일치")
    require(all(x["Status"] == "draft" and x["Published"] == "FALSE" for x in export_products),
            "Shopify export 공개 안전 기본값 위반")
    require(all(x["Available"] == "0" and x["Inventory Policy"] == "deny" for x in inventory),
            "Shopify inventory 안전 기본값 위반")

    draft_actions = action_queue.get("draft_actions") or []
    product_by_pd = {str(x.get("pd_no")): x for x in products}
    export_by_cp = {str(x.get("Canonical Product ID")): x for x in export_products}
    inventory_by_cp = {str(x.get("Canonical Product ID")): x for x in inventory}
    ready_groups = {}
    for pd in ready_ids:
        product = product_by_pd[pd]
        gid = str((product.get("variant") or {}).get("group_id") or
                  f"VG-{product.get('canonical_product_id')}")
        ready_groups.setdefault(gid, []).append(product)
    expected_refs = {}
    for gid, members in ready_groups.items():
        members = sorted(members, key=lambda p: str((p.get("variant") or {}).get("option_value") or ""))
        # 객체 종류는 온톨로지가 정한다. 이번 회차의 ready 수로 바뀌면
        # 같은 상품의 action_id 가 흔들려 이전 Draft 와 승인이 고아가 된다.
        if gid in actual_groups:
            ref = ("ProductVariantGroup", gid)
        else:
            require(len(members) == 1, f"Action 대상 Variant 부모 객체 누락: {gid}")
            ref = ("CanonicalProduct", str(members[0].get("canonical_product_id")))
        expected_refs[ref] = members
    actual_refs = {(str(x.get("object_type")), str(x.get("object_id"))) for x in draft_actions}
    require(len(draft_actions) == len(actual_refs), "Shopify Action ID/객체 참조 중복")
    require(actual_refs == set(expected_refs), "Shopify Action 큐와 ontology 객체 집합 불일치")

    approvals_path = D / "manual" / "shopify_action_approvals.json"
    approvals = load(approvals_path) if approvals_path.exists() else {}
    draft_approvals = approvals.get("drafts") or {} if isinstance(approvals, dict) else {}
    allowed_states = {"WAITING_HUMAN_APPROVAL"}
    context_path = D / "manual" / "shopify_execution_context.json"
    context_doc = load(context_path) if context_path.exists() else {}
    with (export_dir / "images.csv").open(encoding="utf-8", newline="") as f:
        image_payload_rows = list(csv.DictReader(f))
    with (export_dir / "collections.csv").open(encoding="utf-8", newline="") as f:
        collection_payload_rows = list(csv.DictReader(f))
    for action in draft_actions:
        ref = (str(action.get("object_type")), str(action.get("object_id")))
        members = expected_refs[ref]
        cps = [str(x.get("canonical_product_id")) for x in members]
        require(set(action.get("canonical_product_ids") or []) == set(cps),
                f"{action.get('action_id')} CP 구성원 불일치")
        require(action.get("action_id") == f"shopify:draft:{action.get('object_id')}",
                "Shopify Action 멱등 ID 규칙 위반")
        require(action.get("state") in allowed_states and action.get("approval_required") is True,
                "Shopify Action 상태/승인 정책 위반")
        require((action.get("safety") or {}).get("status") == "draft"
                and (action.get("safety") or {}).get("published") is False
                and (action.get("safety") or {}).get("inventory") == 0
                and (action.get("safety") or {}).get("inventory_policy") == "deny"
                and (action.get("execution") or {}).get("enabled") is False,
                "Shopify Action 안전 정책 위반")
        products_payload = [export_by_cp[cp] for cp in cps]
        inventory_payload = [inventory_by_cp[cp] for cp in cps]
        payload = {
            "shopify_group_key": action.get("shopify_group_key"),
            "products": products_payload,
            "inventory": inventory_payload,
            "safety": {"status": "draft", "published": False,
                       "inventory": 0, "inventory_policy": "deny"},
        }
        gid = str((members[0].get("variant") or {}).get("group_id") or
                  f"VG-{members[0].get('canonical_product_id')}")
        require(action.get("shopify_group_key") == gid, "group identity mismatch")
        ontology_members = ([str(m) for m in actual_groups[gid].get(
            "member_canonical_product_ids") or []] if gid in actual_groups else cps)
        excluded = [cp for cp in ontology_members if cp not in cps]
        require(action.get("excluded_members") == excluded, "excluded members mismatch")
        configured = (context_doc.get("actions") or {}).get(ref[1], {})
        if not isinstance(configured, dict):
            configured = {}
        context = {"target_shop": configured.get("target_shop"),
                   "operation": "CREATE_OR_UPDATE_SHOPIFY_DRAFT",
                   "api_version": configured.get("api_version"),
                   "remote_preconditions": configured.get("remote_preconditions")}
        payload.update({
            "schema_version": 2, "action_id": action.get("action_id"),
            "object_type": ref[0], "object_id": ref[1], "canonical_product_ids": cps,
            "pd_nos": [str(p.get("pd_no") or "") for p in members],
            "ontology_members": ontology_members, "excluded_members": excluded,
            "images": [r for r in image_payload_rows if r.get("Canonical Product ID") in cps],
            "collections": [r for r in collection_payload_rows if r.get("Product Handle") in
                            {p.get("Handle") for p in products_payload}],
            "context": context, "gate_input_signature": gate.get("agent_input_signature"),
            "gate_semantic_sha256": digest(gate_signature.semantic_document(gate)),
        })
        validate_action_boundary(action, payload)
    require(action_queue.get("public_blocked") is True, "공개 Action 기본 차단이 해제됨")
    require(not action_queue.get("public_actions"), "검증되지 않은 공개 Action이 생성됨")

    require(legal.get("schema_version") == 3, "legal_full schema v3 필요")
    require(set((legal.get("items") or {}).keys()) == set(rec_by), "legal_full S 범위 불일치")
    expected_public = sum(1 for k, row in gate_by.items()
                          if row.get("ready") and (legal.get("items") or {}).get(k, {}).get("complete"))
    require(gate.get("public_ready") == expected_public, "gate public_ready와 legal_full 불일치")
    raw_ingredients = [x.get("ingredients_inci_raw", "") for x in (legal.get("items") or {}).values()]
    require(all("ingredients_inci_raw" in x for x in (legal.get("items") or {}).values()),
            "legal_full INCI 원문 누락")
    if any("1,2-Hexanediol" in raw for raw in raw_ingredients):
        require(any("1,2-Hexanediol" in item for row in legal["items"].values()
                    for item in row.get("ingredients") or []), "숫자 쉼표 INCI가 분리됨")

    market_rows = market.get("s_grade_priority") or []
    require(len(market_rows) == len(rec_by), "marketing priority S 범위 불일치")
    require(all(x.get("canonical_product_id") == registry.get(str(x.get("pd_no"))) for x in market_rows),
            "marketing priority CP 누락/불일치")
    with (D / "marketing_priority.csv").open(encoding="utf-8", newline="") as f:
        marketing_csv = list(csv.DictReader(f))
    require(len(marketing_csv) == len(market_rows), "marketing_priority.csv 행 수 불일치")
    require(all(x.get("canonical_product_id") for x in marketing_csv), "marketing_priority.csv CP 누락")

    # 유튜브는 링크 수집으로 끝내지 않고 타임스탬프 근거→실험→S상품까지 연결한다.
    coverage = strategy.get("source_coverage") or {}
    quality = strategy.get("quality_gate") or {}
    insights = insight_source.get("insights") or []
    videos = insight_source.get("videos") or []
    require(quality.get("passed") is True, "Shopify YouTube 전략 품질 게이트 실패")
    require(coverage.get("videos") == len(videos) and coverage.get("insights") == len(insights),
            "Shopify YouTube 전략 소스 수 불일치")
    require(len(videos) > 0 and len(insights) > 0, "Shopify YouTube 전략 근거 비어 있음")
    require(all((x.get("evidence") or {}).get("timestamp") for x in insights),
            "Shopify YouTube 타임스탬프 근거 누락")
    strategy_products = strategy.get("product_playbooks") or []
    require({str(x.get("pd_no")) for x in strategy_products} == set(rec_by),
            "Shopify YouTube 전략 S상품 연결 불일치")
    experiments = strategy.get("execution_experiments") or []
    require(experiments and all(x.get("insight_ids") and x.get("kpis") for x in experiments),
            "Shopify 실행 실험의 근거/KPI 누락")
    require((strategy.get("cost_policy") or {}).get("paid_media") ==
            "blocked_until_explicit_user_approval", "유료 마케팅 기본 차단 정책 위반")
    require((market.get("shopify_strategy") or {}).get("status") == strategy.get("status"),
            "market_team 전략 요약과 정본 불일치")

    # Gemini 앱의 8단계 마케팅 설계는 방향 정본으로 쓰되, 구현되지 않은
    # 실시간 수집·시각물 생성·SNS 공개 게시를 완료처럼 보이지 않게 고정한다.
    stages = {str(x.get("id")): x for x in marketing_pipeline.get("stages") or []}
    require(len(stages) == 8, "Multi-Agent 마케팅 8단계 정본 누락")
    delivery = stages.get("channel_delivery") or {}
    global_policy = marketing_pipeline.get("global_policy") or {}
    require(delivery.get("implementation") == "blocked_safe_default"
            and delivery.get("execution_mode") == "human_approval_only"
            and delivery.get("auto_publish") is False
            and delivery.get("connector_status") == "disabled",
            "SNS·이커머스 외부 게시 안전 기본값 위반")
    require(global_policy.get("paid_api_allowed") is False
            and global_policy.get("paid_media_allowed") is False
            and global_policy.get("public_auto_publish_allowed") is False
            and global_policy.get("human_approval_required_for_external_write") is True
            and global_policy.get("read_after_write_required") is True,
            "Multi-Agent 마케팅 전역 비용·승인 정책 위반")
    require((stages.get("data_engine") or {}).get("implementation") ==
            "implemented_scheduled", "주기 수집을 실시간으로 오표기함")
    require((stages.get("design_media") or {}).get("implementation") ==
            "planning_and_reference_collection", "미디어 생성 구현 상태 오표기")

    # Jev는 빠른 구조화 판단, Gemini는 정말 필요한 열린 진단에만 1회 쓴다.
    # 어느 모델도 정본 게이트나 외부 쓰기 승인을 대신할 수 없다.
    escalation_policy = model_routing.get("gemini_escalation") or {}
    routing_gates = model_routing.get("hard_gates") or {}
    require(escalation_policy.get("enabled") is True
            and escalation_policy.get("free_tier_only") is True
            and int(escalation_policy.get("max_calls_per_run") or 0) == 1
            and escalation_policy.get("advisory_only") is True,
            "Gemini 조건부 에스컬레이션 정책 위반")
    require(routing_gates.get("may_execute_actions") is False
            and routing_gates.get("may_change_canonical_gate") is False
            and routing_gates.get("may_publish") is False
            and routing_gates.get("may_pay") is False
            and routing_gates.get("may_retry_on_401_402_403_429") is False,
            "모델 라우팅 하드 게이트 위반")
    require(int(gemini_escalation.get("call_count") or 0) <= 1
            and gemini_escalation.get("advisory_only") is True
            and gemini_escalation.get("paid_api_called") is False
            and gemini_escalation.get("canonical_gate_changed") is False
            and gemini_escalation.get("external_action_executed") is False,
            "Gemini 진단 산출물 안전 속성 위반")
    if gemini_escalation.get("called"):
        require(gemini_escalation.get("free_tier_only") is True
                and gemini_escalation.get("status") == "advisory_ready",
                "Gemini 실제 호출의 무료·advisory 증적 누락")

    for script in ("build_legal_full.py", "export_shopify_operational.py",
                    "gemini_escalation.py",
                   "build_shopify_action_queue.py"):
        require((ROOT / "scripts" / script).exists(), f"workflow 참조 스크립트 없음: {script}")

    # 노란색은 비서실장이 실제로 처리하는 항목에만 허용한다. 사용자 승인,
    # 외부 계정, 정상 실행 통계를 다시 '조치 필요'로 섞는 회귀를 막는다.
    classes = {"auto_remediable", "revalidate_only", "human_approval_required",
               "external_dependency", "informational"}
    teams = dashboard.get("teams") or []
    for team in teams:
        if team.get("action"):
            require(team.get("action_kind") in classes,
                    f'{team.get("id")} action 분류 누락')
        if team.get("waiting"):
            require(team.get("waiting_kind") in {
                "human_approval_required", "external_dependency"
            }, f'{team.get("id")} waiting 분류 오류')
    sourcing = next((x for x in teams if x.get("id") == "sourcing"), {})
    # 정상 수집 통계는 notice 로만 둔다. 단, 수집이 36시간 넘게 발행되지 않은
    # 경우는 실제 장애라 조치로 올린다 (2026-09-28, 9-21~27 미발행을 못 잡았다).
    collection_evidence = sourcing.get("collection_freshness")
    if isinstance(collection_evidence, dict):
        actual_collection = assess_collection(
            load(D / "daiso_real" / "collection_status.json"),
            now=dashboard.get("generated_at"))
        evidence_keys = ("status", "last_attempt_at", "last_success_at",
                         "last_attempt_status", "data_stale", "attempt_stale",
                         "is_no_change", "is_failure")
        require(all(collection_evidence.get(k) == actual_collection.get(k)
                    for k in evidence_keys),
                "소싱 최신성 증적이 실제 수집 기록과 불일치")
    freshness_doc = dashboard.get("automation_freshness") or {}
    daiso_workflow = ((freshness_doc.get("workflows") or {}).get("workflows") or {}).get("daiso-real-collection.yml") or {}
    observed_failure = (freshness_doc.get("workflow_observation_fresh") is True
                        and daiso_workflow.get("status") == "failed")
    validate_sourcing_card(sourcing, observed_workflow_failure=observed_failure)

    for decision in chief.get("decisions") or []:
        require(decision.get("remediation_class") in classes,
                f'비서실장 결정 분류 누락: {decision.get("action")}')
    disabled = ((chief.get("snapshot") or {}).get("channels") or {}).get(
        "disabled_expected") or []
    empty = ((chief.get("snapshot") or {}).get("channels") or {}).get("empty") or []
    disabled_names = {x.get("channel") for x in disabled}
    empty_names = {x.get("channel") for x in empty}
    require(not disabled_names.intersection(empty_names),
            "의도적 disabled 채널이 빈 채널 장애로 분류됨")
    require(remediation.get("schema_version") == 1,
            "지속 해결 장부 schema v1 필요")
    require(remediation.get("check_interval") == "2_hours",
            "비서실장 지속 재검증 주기 누락")
    if int((error_report.get("counts") or {}).get("고장") or 0) > 0:
        require("external_sources:TRACK_EXTERNAL_SOURCE_ERRORS" in
                (remediation.get("issues") or {}),
                "외부 소스 고장이 비서실장 장부에서 누락됨")

    # 최종 runtime 뒤에 무료 규칙 기반 운영 계획과 팀 개선 집계를 갱신한다.
    # 이 검사는 --require-ops-runtime을 준 최종 2시간 루프에서만 강제한다.
    # 고시/카피 등 개별 생산 워크플로는 현재 커머스 조인만 검증한다.
    if require_ops_runtime:
        require(ops_plan.get("generated_at") and (dashboard.get("agents_ops") or {}).get("at"),
                "최종 runtime에 비서실장 운영 heartbeat가 없음")
        require(improvement.get("runtime_at") == dashboard.get("generated_at"),
                "팀 개선 집계가 현재 dashboard runtime과 불일치")
        for team_id, state in (improvement.get("teams") or {}).items():
            if state.get("open_action"):
                require(state.get("open_kind") in classes,
                        f"{team_id} 팀 개선 분류 누락")

    print("COMMERCE_ARCHITECTURE_OK")
    print(f"master={len(products)} S={len(recs)} gate_ready={len(ready_ids)} "
          f"legal_complete={legal.get('complete', 0)} exports={len(export_products)} "
          f"youtube_videos={len(videos)} youtube_insights={len(insights)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
