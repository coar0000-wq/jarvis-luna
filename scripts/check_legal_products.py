#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""상품별 법률 자동 점검.

상품은 자비스가 고른다. 이 스크립트는 그 상품을 미국에 팔아도 되는지
스스로 확인한다. 사람에게 상품 정보를 요구하지 않는다.

점검 4가지
  금지 표현      영문 카피에 미국에서 의약품 주장이 되는 문구가 있는지
  기능성 표기    고시에 미백·주름개선이 적혀 있으면 영문에 옮기면 안 된다
  선케어 OTC     SPF 표기가 있으면 미국에서 OTC 의약품이다
  라벨 필수항목  성분·용량·제조사·원산지가 고시에서 확보됐는지

pass 는 사람만 적는다. 여기서는 auto_checked 까지만 올린다.
규제 판정을 기계가 확정하면 판매에 오히려 해롭다.
"""
from __future__ import annotations
import json, re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "legal_products.json"


def load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def main() -> int:
    doc = load(OUT)
    if not doc:
        print("legal_products.json 을 읽지 못했다")
        return 1
    rules = load(DATA / "us_claim_rules.json") or {}
    banned = [t.lower() for g in (rules.get("banned") or {}).values() for t in g]
    gosi = ((load(DATA / "gosi.json") or {}).get("items") or {})
    copies = {str(i.get("pd_no")): (i.get("copy") or {})
              for i in ((load(DATA / "shopify_listing_copy.json") or {}).get("items") or [])}

    KR_FUNCTIONAL = ("미백", "주름개선", "기능성")
    flagged = 0
    for pd_no, row in (doc.get("items") or {}).items():
        g = gosi.get(pd_no) or {}
        c = copies.get(pd_no) or {}
        blob = " ".join(str(c.get(k) or "") for k in
                        ("title", "description_html", "seo_title",
                         "seo_description", "product_type")).lower()
        blob += " " + " ".join(str(t) for t in (c.get("tags") or []))
        hits = sorted({t for t in banned if t in blob})

        kr = str(g.get("functional") or "") + " " + str(g.get("name") or "")
        is_functional = any(k in kr for k in KR_FUNCTIONAL)
        name_all = f'{row.get("name","")} {g.get("volume","")} {g.get("name","")}'
        is_spf = bool(re.search(r"spf\s*\d+|선크림|선쿠션|sunscreen", name_all, re.I))
        label_fields = ("ingredients", "volume", "maker", "origin")
        label_ok = all(str(g.get(f) or "").strip() for f in label_fields)

        checks = {
            "banned_claim": {"ok": not hits, "detail": ", ".join(hits[:5]) or "없음"},
            "kr_functional": {
                "ok": True,
                "detail": ("한국 기능성 표기 있음 - 영문에 옮기지 말 것"
                           if is_functional else "해당 없음"),
                "note": "표기 자체는 문제가 아니다. 영문으로 번역하면 문제가 된다.",
            },
            "otc_sunscreen": {
                "ok": True,
                "detail": ("SPF 제품 - 미국에서 OTC 의약품. Drug Facts 라벨 필요"
                           if is_spf else "해당 없음"),
            },
            "label_fields": {
                "ok": label_ok,
                "detail": ("4항목 확보" if label_ok else
                           "미확보: " + ", ".join(
                               f for f in label_fields if not str(g.get(f) or "").strip())),
            },
        }
        blockers = [k for k, v in checks.items() if not v["ok"]]
        row["auto_checks"] = checks
        row["auto_blockers"] = blockers
        row["needs_attention"] = bool(hits) or is_functional or is_spf
        # 등록을 실제로 막을 것과 알려만 둘 것을 나눈다.
        # 한국 기능성 표기 자체는 막을 사유가 아니다. 영문 카피 생성 단계에서
        # 금지어를 아예 쓰지 않게 막고 있어서 여기서 또 막으면 이중이다.
        # SPF 는 미국에서 OTC 의약품이라 사람 확인 없이는 못 올린다.
        row["hard_block"] = bool(blockers) or is_spf or bool(hits)
        row["hard_block_reason"] = (
            ("자동 점검 미통과: " + ", ".join(blockers)) if blockers
            else "SPF 표기 - 미국 OTC 의약품이라 라벨 요건이 별도" if is_spf
            else "금지 표현 발견" if hits else ""
        )
        row["auto_checked_at"] = datetime.now(timezone.utc).isoformat()
        if row.get("status") == "pending":
            row["status"] = "auto_checked" if not blockers else "pending"
        if row["needs_attention"]:
            flagged += 1

    items = doc.get("items") or {}
    doc["auto_summary"] = {
        "checked": len(items),
        "clean": sum(1 for r in items.values() if not r.get("auto_blockers")),
        "needs_attention": flagged,
        "pass": sum(1 for r in items.values() if r.get("status") == "pass"),
    }
    doc["auto_checked_at"] = datetime.now(timezone.utc).isoformat()
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = doc["auto_summary"]
    print(f"점검 {s['checked']}건 · 통과 {s['clean']} · 주의 {s['needs_attention']} · 사람 PASS {s['pass']}")
    for k, r in items.items():
        if r.get("needs_attention"):
            det = [v["detail"] for v in (r.get("auto_checks") or {}).values()
                   if v.get("detail") not in ("없음", "해당 없음", "4항목 확보")]
            print(f"  주의 {k}  {str(r.get('name'))[:24]}  {' / '.join(det)[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
