#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Product Master, gate, legal, marketing, Shopify exports의 조인 무결성 검사."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_signature  # noqa: E402


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    source = load(D / "daiso_real" / "products.json")
    master = load(D / "product_master.json")
    score = load(D / "daiso_real" / "shopify_demand_score.json")
    srec = load(D / "daiso_real" / "shopify_s_recommendations.json")
    gate = load(D / "listing_gate.json")
    legal = load(D / "legal_full.json")
    market = load(D / "market_team.json")
    action_queue = load(D / "shopify_action_queue.json")

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
    ready_ids = {k for k, x in gate_by.items() if x.get("ready")}
    require(export_ids == ready_ids, "Shopify products.csv가 gate ready 집합과 다름")
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
    allowed_states = {"WAITING_HUMAN_APPROVAL", "READY_TO_EXECUTE", "DRAFT_CREATED", "VERIFIED"}
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
        # 그룹에서 빠진 멤버가 있으면 승인 대상이 달라진다. 해시에 포함한다.
        excluded = list(action.get("excluded_members") or [])
        if excluded:
            payload["excluded_members"] = excluded
        expected_hash = digest(payload)
        require(action.get("payload_hash") == expected_hash, "Shopify Action payload hash 불일치")

        # 승인 증적은 실행 직전뿐 아니라 종료 상태에도 요구한다.
        # 예전에는 DRAFT_CREATED 에 shopify_ids 만 있으면 통과해서,
        # 공개 저장소에 그 두 값만 써넣으면 승인 없이 완료로 굳었다.
        if action.get("state") in {"READY_TO_EXECUTE", "DRAFT_CREATED", "VERIFIED"}:
            approval = draft_approvals.get(str(action.get("object_id")), {})
            require(approval.get("approved") is True
                    and approval.get("approved_payload_hash") == expected_hash
                    and approval.get("approved_by") and approval.get("approved_at"),
                    f"{action.get('state')} Action의 정확한 사람 승인 증적 누락")
        if action.get("state") in {"DRAFT_CREATED", "VERIFIED"}:
            require(bool(action.get("shopify_ids")), "완료 Action의 Shopify ID 증적 누락")
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

    for script in ("build_legal_full.py", "export_shopify_operational.py",
                   "build_shopify_action_queue.py"):
        require((ROOT / "scripts" / script).exists(), f"workflow 참조 스크립트 없음: {script}")

    print("COMMERCE_ARCHITECTURE_OK")
    print(f"master={len(products)} S={len(recs)} gate_ready={len(ready_ids)} "
          f"legal_complete={legal.get('complete', 0)} exports={len(export_products)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
