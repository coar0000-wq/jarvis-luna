#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shopify 동기화 가드 (2026-09-29).

두 가지를 한다.

1) 막는다 (하나라도 어기면 exit 1)
   - shortlist 가 없거나 비어 있는데 export 가 있다
   - export 에 shortlist 밖 상품이 섞였다 (S등급 전체를 올리는 사고)
   - 판매 단위 수가 shortlist 상한을 넘는다
   - draft / 비공개 / 재고 0 / deny 가 아닌 행이 있다

2) 변경분만 고른다
   지난번 스토어에 반영된 내용(data/shopify_sync_state.json)과 이번 export 를
   판매 단위별로 비교해 create / update / unchanged / remove_proposed 로 나눈다.
   update 는 실제로 바뀐 필드를 적는다. 환율 때문에 생기는 작은 가격 흔들림
   (±$0.50 그리고 ±3% 이내)은 변경으로 보지 않는다. 매 회차 전 상품이
   '수정됨' 이 되면 업데이트가 의미를 잃기 때문이다.
   create·update 행만 data/shopify_exports/delta/ 에 4종 CSV 로 쓴다.

   shopify_sync_state.json 은 실제 스토어 반영(read-after-write 확인) 후에만
   실행기가 쓴다. 스토어가 없는 지금은 기준선이 비어 전부 create 로 나온다.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data"
EXPORT = D / "shopify_exports"
DELTA = EXPORT / "delta"
STATE = D / "shopify_sync_state.json"
SHORTLIST = D / "shopify_shortlist.json"
OUT = D / "shopify_sync_guard.json"
FILES = ("products.csv", "inventory.csv", "images.csv", "collections.csv")
MATERIAL = ("Title", "Body (HTML)", "Vendor", "Type", "Tags", "Option1 Name", "Option1 Value",
            "Variant SKU", "Variant Price", "Image Src", "Image Alt Text", "SEO Title", "SEO Description")
PRICE_ABS, PRICE_REL = 0.50, 0.03


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    if not path.exists():
        return [], []
    with path.open(encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def unit_fields(rows: list[dict]) -> dict:
    """판매 단위의 비교용 내용. 옵션(SKU) 순서로 정렬해 순서 차이를 없앤다."""
    return {row.get("Variant SKU") or row.get("pd_no"): {k: row.get(k, "") for k in MATERIAL}
            for row in sorted(rows, key=lambda r: str(r.get("Variant SKU") or ""))}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def price_changed(old: str, new: str) -> bool:
    try:
        a, b = float(old or 0), float(new or 0)
    except ValueError:
        return old != new
    if not a or not b:
        return a != b
    return abs(a - b) > PRICE_ABS and abs(a - b) / a > PRICE_REL


def diff(old: dict, new: dict) -> list[str]:
    changed = []
    for sku in sorted(set(old) | set(new)):
        if sku not in old:
            changed.append(f"{sku}: 옵션 추가")
            continue
        if sku not in new:
            changed.append(f"{sku}: 옵션 제거")
            continue
        for k in MATERIAL:
            a, b = old[sku].get(k, ""), new[sku].get(k, "")
            if a == b:
                continue
            if k == "Variant Price" and not price_changed(a, b):
                continue
            changed.append(f"{sku}: {k}")
    return changed


def main() -> int:
    shortlist = load(SHORTLIST, {}) or {}
    allowed = {str(x) for x in shortlist.get("active_pd_nos") or []}
    max_units = int((shortlist.get("rules") or {}).get("max_units") or 0)
    fields, products = read_csv(EXPORT / "products.csv")
    _, inventory = read_csv(EXPORT / "inventory.csv")
    violations = []

    if products and not allowed:
        violations.append("shortlist 가 없거나 비어 있는데 export 가 있다")
    outside = sorted({r.get("pd_no") for r in products} - allowed)
    if outside and allowed:
        violations.append(f"shortlist 밖 상품이 export 에 있다: {outside}")
    by_unit: dict[str, list[dict]] = {}
    for r in products:
        by_unit.setdefault(r.get("Handle") or r.get("pd_no"), []).append(r)
    if max_units and len(by_unit) > max_units:
        violations.append(f"판매 단위 {len(by_unit)}개 > 상한 {max_units}")
    unsafe = [r.get("pd_no") for r in products
              if not (r.get("Status") == "draft" and r.get("Published") == "FALSE"
                      and str(r.get("Variant Inventory Qty")) == "0" and r.get("Variant Inventory Policy") == "deny")]
    unsafe += [r.get("pd_no") for r in inventory if not (str(r.get("Available")) == "0" and r.get("Inventory Policy") == "deny")]
    if unsafe:
        violations.append(f"draft·비공개·재고0 안전값 위반: {sorted(set(unsafe))}")

    state = load(STATE, {}) or {}
    synced = state.get("units") or {}
    units, delta_handles = [], set()
    for handle, rows in sorted(by_unit.items()):
        fields_now = unit_fields(rows)
        base = synced.get(handle)
        if not base:
            action, changed = "create", ["새 상품"]
        else:
            changed = diff(base.get("fields") or {}, fields_now)
            action = "update" if changed else "unchanged"
        if action != "unchanged":
            delta_handles.add(handle)
        units.append({"handle": handle, "pd_nos": sorted(r.get("pd_no") for r in rows), "action": action,
                      "changed": changed[:20], "content_hash": digest(fields_now)})
    for handle, base in sorted(synced.items()):
        if handle not in by_unit:
            units.append({"handle": handle, "pd_nos": base.get("pd_nos", []), "action": "remove_proposed",
                          "changed": ["shortlist 에서 빠짐 · 스토어에서는 자동 삭제하지 않고 사람 확인 후 보관 처리"],
                          "content_hash": base.get("hash")})

    DELTA.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name in FILES:
        hdr, rows = read_csv(EXPORT / name)
        key = "Product Handle" if name == "collections.csv" else "Handle"
        keep = [r for r in rows if r.get(key) in delta_handles]
        counts[name] = len(keep)
        if not hdr:
            continue
        with (DELTA / name).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=hdr, lineterminator="\n")
            w.writeheader()
            w.writerows(keep)

    summary = {a: sum(1 for u in units if u["action"] == a) for a in ("create", "update", "unchanged", "remove_proposed")}
    doc = {
        "schema_version": 1,
        "generated_at": now(),
        "generator": "scripts/shopify_sync_guard.py",
        "ok": not violations,
        "violations": violations,
        "shortlist_status": shortlist.get("status"),
        "shortlist_units": shortlist.get("active_unit_count"),
        "baseline": {"file": "data/shopify_sync_state.json", "present": STATE.exists(),
                     "synced_units": len(synced), "synced_at": state.get("synced_at"),
                     "note": "실제 스토어 반영 후 실행기만 기록한다. 없으면 전부 create 다."},
        "mode": "incremental" if synced else "initial",
        "summary": summary,
        "delta_dir": "data/shopify_exports/delta",
        "delta_rows": counts,
        "price_rule": f"±${PRICE_ABS:.2f} 그리고 ±{PRICE_REL:.0%} 안의 가격 변화는 변경으로 보지 않는다",
        "units": units,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Shopify sync guard {'OK' if doc['ok'] else 'FAIL'} · {doc['mode']} · {summary} · delta {counts}")
    for v in violations:
        print(f"::error::{v}")
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
