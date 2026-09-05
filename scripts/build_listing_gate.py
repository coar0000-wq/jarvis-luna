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
    pricing = load(DATA / "pricing_model.json")
    gosi = load(DATA / "gosi.json")
    legal = load(DATA / "legal_products.json")

    missing = [n for n, d in (("shopify_listing_copy.json", copy),
                              ("pricing_model.json", pricing),
                              ("gosi.json", gosi),
                              ("legal_products.json", legal)) if d is None]

    copies = {str(i.get("pd_no")) for i in (copy or {}).get("items", [])}
    # 저울 실측을 요구하지 않는다. 고시 용량과 우체국 요금표로 배송비가 나오고,
    # 가격 모델이 손익분기를 넘는 판매가를 실제로 산출했는지만 본다.
    priced = {str(o.get("pd_no")): o
              for o in (((pricing or {}).get("offers_by_product") or {}).get("single") or [])}
    gosi_items = (gosi or {}).get("items") or {}
    legal_items = (legal or {}).get("items") or {}

    rows, counts = [], {"copy": 0, "gosi": 0, "price": 0, "legal": 0, "ready": 0}
    targets = sorted([x for x in score.get("all_scored") or [] if x.get("grade") == "S"],
                     key=lambda x: -(x.get("shopify_score") or 0))
    for x in targets:
        k = str(x.get("pd_no"))
        g = gosi_items.get(k) or {}
        o = priced.get(k) or {}
        lg = legal_items.get(k) or {}
        checks = {
            "copy_ok": k in copies,
            # 필수 4항목이 모두 채워져야 인정한다. 하나라도 비면 미완성이다.
            "gosi_ok": all(str(g.get(f) or "").strip() for f in GOSI_REQUIRED),
            # 판매가가 손익분기를 넘고 마진이 남아야 한다.
            "price_ok": bool(o) and not o.get("register_blocked")
                        and (o.get("margin_pct") or 0) > 0,
            # 자동 점검이 깨끗하면 통과. 문제가 있을 때만 사람을 부른다.
            # 사람이 fail 을 적었으면 자동이 그걸 뒤집지 못한다.
            "legal_ok": (str(lg.get("status") or "") != "fail"
                         and not lg.get("hard_block")
                         and bool(lg.get("auto_checked_at"))),
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
            "price_note": o.get("block_reason") or "",
            "legal_note": lg.get("hard_block_reason") or "",
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
            "price_ok": "pricing_model.json 이 손익분기를 넘는 판매가를 산출함. "
                        "무게는 고시 용량 + 우체국 요금표로 계산하므로 저울은 불필요.",
            "legal_ok": "자동 점검이 전부 통과하고 사람이 fail 로 적지 않음. "
                        "SPF·금지표현·점검 미통과가 있으면 그때 사람이 본다.",
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
