#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S등급 상품별 MoCRA/FPLA 준비 스키마를 실데이터만으로 만든다.

책임자 정보나 영문 사용법을 추정하지 않는다. 사람이 넣을 값은
`data/manual/legal_responsible_person.json`에서만 읽고, 없으면 빈칸과 blocker로
남긴다. 예전 legal_full.json의 예시 주소·전화번호는 운영 데이터로 재사용하지 않는다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data"
OUT = D / "legal_full.json"
PLACEHOLDER = re.compile(r"(B0X+|DS0+|123\s|555-|placeholder|TODO|TBD|실제\s*확인|미입력|확인\s*필요)", re.I)
REQUIRED = ("identity", "ingredients", "net_contents", "directions", "warnings", "responsible_person")
RP_FIELDS = ("name", "address", "email", "phone")


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def real(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and not PLACEHOLDER.search(text))


def rows_by_id(value: Any) -> dict[str, dict]:
    if isinstance(value, dict) and "items" in value:
        value = value.get("items")
    if isinstance(value, dict):
        return {str(v.get("pd_no") or v.get("product_id") or k): v
                for k, v in value.items() if isinstance(v, dict)}
    if isinstance(value, list):
        return {str(v.get("pd_no") or v.get("product_id")): v
                for v in value if isinstance(v, dict) and (v.get("pd_no") or v.get("product_id"))}
    return {}


def clean_rp(doc: Any) -> dict[str, str]:
    doc = doc if isinstance(doc, dict) else {}
    return {field: str(doc.get(field) or "").strip() if real(doc.get(field)) else ""
            for field in RP_FIELDS}


def split_inci(value: str) -> list[str]:
    """숫자 안의 쉼표(예: 1,2-Hexanediol)는 성분 구분자로 보지 않는다."""
    return [x.strip() for x in re.split(r"(?<!\d),(?!\d)", value or "") if x.strip()]


def main() -> int:
    master = load(D / "product_master.json", {}) or {}
    registry = master.get("pd_no_to_cp") or {} if isinstance(master, dict) else {}
    recs = load(D / "daiso_real" / "shopify_s_recommendations.json", {}) or {}
    gosi = rows_by_id(load(D / "gosi.json", {}))
    labels = rows_by_id(load(D / "daiso_real" / "daiso_us_labels.json", {}))
    legal = rows_by_id(load(D / "legal_products.json", {}))
    copies = rows_by_id(load(D / "shopify_listing_copy.json", {}))
    responsible = clean_rp(load(D / "manual" / "legal_responsible_person.json", {}))
    overrides_doc = load(D / "manual" / "legal_product_overrides.json", {}) or {}
    overrides = overrides_doc.get("items", overrides_doc) if isinstance(overrides_doc, dict) else {}
    previous = load(OUT, {}) or {}
    previous_items = previous.get("items") or {} if isinstance(previous, dict) else {}

    items: dict[str, dict] = {}
    for rec in recs.get("recommendations") or []:
        if not isinstance(rec, dict):
            continue
        pd_no = str(rec.get("pd_no") or "")
        if not pd_no:
            continue
        kr = gosi.get(pd_no, {})
        us = labels.get(pd_no, {})
        check = legal.get(pd_no, {})
        copy = (copies.get(pd_no, {}).get("copy") or {})
        cp = rec.get("canonical_product_id") or registry.get(pd_no)
        override = {}
        if isinstance(overrides, dict):
            override = overrides.get(str(cp)) or overrides.get(pd_no) or {}
        override = override if isinstance(override, dict) else {}

        identity_raw = override.get("identity") or copy.get("title")
        identity = identity_raw if real(identity_raw) else ""
        inci = us.get("ingredients_inci") if real(us.get("ingredients_inci")) else ""
        ingredients = split_inci(str(inci))
        net_raw = override.get("net_contents") or us.get("net_contents")
        net = net_raw if real(net_raw) else ""
        directions_raw = override.get("directions") or us.get("directions_en")
        directions = directions_raw if real(directions_raw) else ""
        warnings_raw = override.get("warnings") or us.get("warnings_en")
        warnings = warnings_raw if real(warnings_raw) else ""
        item_rp = responsible.copy()
        item_rp.update({k: v for k, v in clean_rp(override.get("responsible_person", {})).items() if v})

        blockers = []
        if not identity:
            blockers.append("identity")
        if not ingredients:
            blockers.append("ingredients")
        if not net:
            blockers.append("net_contents")
        if not directions:
            blockers.append("directions")
        if not warnings:
            blockers.append("warnings")
        missing_rp = [f for f in RP_FIELDS if not item_rp.get(f)]
        if missing_rp:
            blockers.extend(f"responsible_person.{f}" for f in missing_rp)
        if check.get("hard_block"):
            blockers.append("legal_hard_block")

        generated = {
            "canonical_product_id": cp,
            "pd_no": pd_no,
            "name_ko": rec.get("name") or kr.get("name") or "",
            "identity": identity,
            "ingredients": ingredients,
            "ingredients_inci_raw": inci,
            "net_contents": net,
            "directions": directions,
            "warnings": warnings,
            "responsible_person": item_rp,
            "manufacturer": us.get("manufacturer") if real(us.get("manufacturer")) else "",
            "country_of_origin": us.get("country_of_origin") if real(us.get("country_of_origin")) else "",
            "sources": {
                "identity": "manual_override" if override.get("identity") else "shopify_listing_copy.json" if identity else "human_required",
                "ingredients": "daiso_us_labels.json" if ingredients else "human_required",
                "net_contents": "manual_override" if override.get("net_contents") else "daiso_us_labels.json" if net else "human_required",
                "directions": "manual_override" if override.get("directions") else "daiso_us_labels.json" if directions else "human_translation_required",
                "warnings": "manual_override" if override.get("warnings") else "daiso_us_labels.json" if warnings else "human_translation_required",
                "responsible_person": "manual_verified" if not missing_rp else "human_required",
            },
            "auto_legal_status": check.get("status", "missing"),
            "hard_block": bool(check.get("hard_block")),
            "hard_block_reason": check.get("hard_block_reason", ""),
            "complete": not blockers,
            "blockers": blockers,
        }
        # 생성기가 모르는 확장 필드는 다음 실행에도 보존한다.
        prior = previous_items.get(pd_no, {}) if isinstance(previous_items, dict) else {}
        preserved = {k: v for k, v in prior.items() if k not in generated}
        preserved.update(generated)
        items[pd_no] = preserved

    complete = sum(1 for x in items.values() if x["complete"])
    payload = {
        "schema_version": 3,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/build_legal_full.py",
        "scope": "현재 S등급 상품별 미국 화장품 라벨/MoCRA 공개 준비 상태",
        "truth_policy": "미확인 값은 빈칸으로 두며 예시 주소·전화·성분을 사용하지 않는다",
        "required_fields": list(REQUIRED),
        "responsible_person_required_fields": list(RP_FIELDS),
        "total": len(items),
        "complete": complete,
        "blocked": len(items) - complete,
        "responsible_person": responsible,
        "manual_product_overrides": "data/manual/legal_product_overrides.json",
        "extensions": previous.get("extensions", {}) if isinstance(previous, dict) else {},
        "items": items,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"legal_full.json {len(items)}건 · complete {complete} · blocked {len(items)-complete}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
