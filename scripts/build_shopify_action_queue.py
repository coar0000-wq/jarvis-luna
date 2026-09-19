#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ontology 기반 Shopify Draft Action 큐를 만든다.

외부 Shopify 쓰기는 수행하지 않는다. listing_gate.ready 상품을 Variant 그룹 단위의
멱등 Action으로 만들고, 정확한 payload hash에 대한 사람 승인 전에는 실행 대기로 둔다.
공개·양수 재고 Action은 public_ready, 법률 승인, 실재고 원천이 모두 생기기 전 생성하지 않는다.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_signature  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data"
OUT = D / "shopify_action_queue.json"
APPROVALS = D / "manual" / "shopify_action_approvals.json"
TERMINAL_STATES = {"DRAFT_CREATED", "VERIFIED"}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def load_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def approval_valid(approval: dict, payload_hash: str) -> bool:
    return bool(
        approval.get("approved") is True
        and approval.get("approved_payload_hash") == payload_hash
        and str(approval.get("approved_by") or "").strip()
        and str(approval.get("approved_at") or "").strip()
    )


def main() -> int:
    gate = load_json(D / "listing_gate.json", {}) or {}
    # 낡은 게이트 위에서 사람 승인을 받을 Action 을 만들지 않는다.
    gate_signature.require_current(gate)
    master = load_json(D / "product_master.json", {}) or {}
    previous = load_json(OUT, {}) or {}
    approvals = load_json(APPROVALS, {}) or {}
    master_by = {str(x.get("pd_no")): x for x in master.get("products") or []
                 if isinstance(x, dict)}
    ontology_groups = {str(x.get("group_id")): x for x in master.get("variant_groups") or []
                       if isinstance(x, dict)}
    previous_by = {str(x.get("action_id")): x for x in previous.get("draft_actions") or []
                   if isinstance(x, dict)}
    product_rows = load_csv(D / "shopify_exports" / "products.csv")
    inventory_rows = load_csv(D / "shopify_exports" / "inventory.csv")
    product_by_cp = {str(x.get("Canonical Product ID") or ""): x for x in product_rows}
    inventory_by_cp = {str(x.get("Canonical Product ID") or ""): x for x in inventory_rows}

    ready = [x for x in gate.get("items") or []
             if isinstance(x, dict) and x.get("ready")]
    grouped: dict[str, list[dict]] = {}
    for row in ready:
        pd_no = str(row.get("pd_no") or "")
        product = master_by.get(pd_no)
        if not product:
            raise RuntimeError(f"Action 큐 대상 {pd_no}가 Product Master에 없습니다")
        group_id = str((product.get("variant") or {}).get("group_id")
                       or f"VG-{product.get('canonical_product_id')}")
        grouped.setdefault(group_id, []).append(product)

    draft_approvals = approvals.get("drafts") or {} if isinstance(approvals, dict) else {}
    actions = []
    for group_id, members in sorted(grouped.items()):
        members = sorted(members, key=lambda p: str((p.get("variant") or {}).get("option_value") or ""))
        cps = [str(p.get("canonical_product_id") or "") for p in members]
        if any(not cp for cp in cps):
            raise RuntimeError(f"Variant 그룹 {group_id}에 CP가 없습니다")
        if any(cp not in product_by_cp or cp not in inventory_by_cp for cp in cps):
            raise RuntimeError(f"Variant 그룹 {group_id}의 Shopify Export 행이 누락되었습니다")

        products = [product_by_cp[cp] for cp in cps]
        inventory = [inventory_by_cp[cp] for cp in cps]
        safety_valid = all(
            row.get("Status") == "draft"
            and row.get("Published") == "FALSE"
            and row.get("Variant Inventory Qty") == "0"
            and row.get("Variant Inventory Policy") == "deny"
            for row in products
        ) and all(
            row.get("Available") == "0" and row.get("Inventory Policy") == "deny"
            for row in inventory
        )
        if not safety_valid:
            raise RuntimeError(f"Variant 그룹 {group_id}가 Draft 안전 정책을 위반했습니다")

        payload = {
            "shopify_group_key": group_id,
            "products": products,
            "inventory": inventory,
            "safety": {
                "status": "draft",
                "published": False,
                "inventory": 0,
                "inventory_policy": "deny",
            },
        }
        payload_hash = digest(payload)
        # 객체 정체성은 온톨로지가 정한다. 이번 회차에 몇 개가 ready 였는지로
        # 바뀌면 같은 상품이 어제는 그룹, 오늘은 단품이 된다. 그러면
        # action_id 가 바뀜어 이전 shopify_ids 와 승인이 고아가 되고,
        # 같은 핸들에 Draft 가 중복으로 생길 수 있다.
        if group_id in ontology_groups:
            object_type = "ProductVariantGroup"
            object_id = group_id
        elif len(members) > 1:
            raise RuntimeError(f"Action 대상 Variant 부모 객체가 없습니다: {group_id}")
        else:
            object_type = "CanonicalProduct"
            object_id = cps[0]

        # 그룹이면 이번에 빠진 멤버를 명시한다. 조용히 줄어든 채로
        # 승인받으면 사람은 전체를 승인했다고 믿게 된다.
        excluded_members = []
        if object_type == "ProductVariantGroup":
            ontology_members = [str(m) for m in
                                (ontology_groups[group_id].get("member_canonical_product_ids")
                                 or [])]
            present = set(cps)
            excluded_members = [m for m in ontology_members if m not in present]
            if excluded_members:
                payload["excluded_members"] = excluded_members
                payload_hash = digest(payload)

        action_id = f"shopify:draft:{object_id}"
        approval = draft_approvals.get(object_id, {}) if isinstance(draft_approvals, dict) else {}
        previous_action = previous_by.get(action_id, {})
        approved_now = approval_valid(
            approval if isinstance(approval, dict) else {}, payload_hash)
        # 이전 회차의 종료 상태를 그대로 이어받지 않는다.
        # 예전에는 payload_hash 만 같으면 승인 증적 없이 DRAFT_CREATED 가
        # 영구히 고정됐다. 산출물은 매 회차 공개 저장소에 다시 써지므로
        # 그 값을 근거로 삼으면 자기승인이 된다.
        if (previous_action.get("payload_hash") == payload_hash
                and previous_action.get("state") in TERMINAL_STATES
                and approved_now):
            state = previous_action["state"]
        elif approved_now:
            state = "READY_TO_EXECUTE"
        else:
            state = "WAITING_HUMAN_APPROVAL"

        actions.append({
            "action_id": action_id,
            "action_type": "CREATE_OR_UPDATE_SHOPIFY_DRAFT",
            "object_type": object_type,
            "object_id": object_id,
            "shopify_group_key": group_id,
            "canonical_product_ids": cps,
            "excluded_members": excluded_members,
            "pd_nos": [str(p.get("pd_no") or "") for p in members],
            "variant_count": len(members),
            "payload_hash": payload_hash,
            "state": state,
            "approval_required": True,
            "approved_by": approval.get("approved_by", "") if isinstance(approval, dict) else "",
            "approved_at": approval.get("approved_at", "") if isinstance(approval, dict) else "",
            "execution": {
                "enabled": False,
                "reason": "Shopify 쓰기 실행기는 별도 승인·자격증명·read-after-write 검증 후 연결",
            },
            "safety": payload["safety"],
            "shopify_ids": previous_action.get("shopify_ids", {}),
            "last_error": previous_action.get("last_error", ""),
        })

    states: dict[str, int] = {}
    for action in actions:
        states[action["state"]] = states.get(action["state"], 0) + 1
    public_ready = [x for x in gate.get("items") or []
                    if isinstance(x, dict) and x.get("public_ready")]
    output = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_gate_generated_at": gate.get("generated_at"),
        "ontology_source": "data/product_master.json",
        "approval_source": "data/manual/shopify_action_approvals.json",
        "policy": {
            "draft": "ready + exact payload hash human approval; draft/unpublished/inventory 0/deny only",
            "public": "public_ready + legal approval + verified physical inventory + separate publish approval",
            "idempotency": "action_id + payload_hash",
        },
        "draft_action_count": len(actions),
        "states": states,
        "public_ready_item_count": len(public_ready),
        "public_actions": [],
        "public_blocked": True,
        "public_block_reason": (
            "public_ready 상품 없음" if not public_ready else
            "공개 실행기 미연결: 법률 승인·실재고·별도 공개 승인 검증 필요"
        ),
        "draft_actions": actions,
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Shopify Action 큐 {len(actions)}개 · {states} · public_ready {len(public_ready)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
