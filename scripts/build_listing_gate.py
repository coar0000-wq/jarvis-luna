#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""상품별 등록 가능 여부(listing_ready)를 한 곳에서 계산한다.

지금까지는 "이 상품 팔아도 되나" 의 답이 네 파일에 흩어져 있어
아무도 한 번에 답하지 못했다. 실제로 팀 카드 숫자가 세 번 어긋났다.

    listing_ready = copy_ok AND gosi_ok AND price_ok AND legal_ok

네 조건 모두 실제 파일에 근거한다. 추측하지 않는다.
근거를 못 읽으면 그 조건은 false 로 두고 사유를 남긴다.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "listing_gate.json"

GOSI_REQUIRED = ("ingredients", "volume", "maker", "origin")


def load(path: Path):
    """읽기에 실패하면 None. 부분적으로 읽힌 값을 쓰지 않는다.

    인코딩 오류까지 잡는다. 파일이 커서 한 번에 안 읽히는 환경이 있어
    몇 번 다시 시도하고, 그래도 안 되면 포기하고 사유를 남긴다.
    """
    for _ in range(3):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            time.sleep(0.5)
    return None


def main() -> int:
    score = load(DATA / "daiso_real" / "shopify_demand_score.json")
    if not score:
        print("shopify_demand_score.json 을 읽지 못해 중단한다")
        return 1
    copy = load(DATA / "shopify_listing_copy.json")
    weights = load(DATA / "weights.json")
    gosi = load(DATA / "gosi.json")
    legal = load(DATA / "legal_products.json")

    missing = [n for n, d in (("shopify_listing_copy.json", copy),
                              ("weights.json", weights),
                              ("gosi.json", gosi),
                              ("legal_products.json", legal)) if d is None]

    copies = {str(i.get("pd_no")) for i in (copy or {}).get("items", [])}
    measured = {k for k, v in ((weights or {}).get("measured") or {}).items()
                if isinstance(v, dict) and (v.get("gram") or 0) > 0}
    gosi_items = (gosi or {}).get("items") or {}
    legal_items = (legal or {}).get("items") or {}

    rows, counts = [], {"copy": 0, "gosi": 0, "price": 0, "legal": 0, "ready": 0}
    targets = sorted([x for x in score.get("all_scored") or [] if x.get("grade") == "S"],
                     key=lambda x: -(x.get("shopify_score") or 0))
    for x in targets:
        k = str(x.get("pd_no"))
        g = gosi_items.get(k) or {}
        checks = {
            "copy_ok": k in copies,
            # 필수 4항목이 모두 채워져야 인정한다. 하나라도 비면 미완성이다.
            "gosi_ok": all(str(g.get(f) or "").strip() for f in GOSI_REQUIRED),
            "price_ok": k in measured,
            # pass 는 사람만 적는다. 스크립트가 올리지 않는다.
            "legal_ok": str((legal_items.get(k) or {}).get("status") or "") == "pass",
        }
        ready = all(checks.values())
        for name, val in checks.items():
            if val:
                counts[name.replace("_ok", "")] += 1
        counts["ready"] += ready
        rows.append({
            "pd_no": k, "name": x.get("name"), "grade": x.get("grade"),
            "shopify_score": x.get("shopify_score"),
            **checks, "listing_ready": ready,
            "blocked_by": [n.replace("_ok", "") for n, v in checks.items() if not v],
        })

    total = len(rows)
    blockers = {}
    for r in rows:
        for b in r["blocked_by"]:
            blockers[b] = blockers.get(b, 0) + 1
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/build_listing_gate.py",
        "규칙": "listing_ready = copy_ok AND gosi_ok AND price_ok AND legal_ok",
        "근거": {
            "copy_ok": "shopify_listing_copy.json 의 items 에 pd_no 가 있음",
            "gosi_ok": f"gosi.json 의 {', '.join(GOSI_REQUIRED)} 가 모두 채워짐",
            "price_ok": "weights.json 의 gram 이 0 이 아님 (저울 실측)",
            "legal_ok": "legal_products.json 의 status 가 pass (사람만 변경)",
        },
        "target": "S등급",
        "total": total,
        "ready": counts["ready"],
        "counts": {k: v for k, v in counts.items() if k != "ready"},
        "blockers": dict(sorted(blockers.items(), key=lambda x: -x[1])),
        "unreadable": missing,
        "items": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"등록 가능 {counts['ready']}/{total}")
    for k in ("copy", "gosi", "price", "legal"):
        print(f"  {k:6s} {counts[k]}/{total}")
    if missing:
        print(f"  읽지 못한 파일: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
