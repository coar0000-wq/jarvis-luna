#!/usr/bin/env python3
"""shortlist 규칙과 sync guard 회귀 테스트. 네트워크 없음."""
from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_shopify_shortlist as sl  # noqa: E402
import shopify_sync_guard as guard  # noqa: E402

# 1) 형태 판정: 얼굴 제품과 립·아이 제품은 서로 근거가 되지 않는다
assert sl.forms_of("VT 슈퍼 히알론 슬리핑 마스크") != sl.forms_of("Smushy SOS Hydrating Lip Mask")
assert sl.forms_of("VT PDRN 광채 크림") != sl.forms_of("Lacto-PDRN 4% + B9 Eye Cream")
assert sl.forms_of("리들샷 앰플") == sl.forms_of("REJURAN Turnover Ampoule")

FIELDS = ["Handle", "Title", "Body (HTML)", "Vendor", "Type", "Tags", "Published", "Status", "Option1 Name",
          "Option1 Value", "Variant SKU", "Variant Price", "Variant Inventory Tracker", "Variant Inventory Qty",
          "Variant Inventory Policy", "Variant Requires Shipping", "Image Src", "Image Position", "Image Alt Text",
          "SEO Title", "SEO Description", "Canonical Product ID", "pd_no", "Legal Complete"]


def row(handle, pd, price="18.50", title="T"):
    r = {k: "" for k in FIELDS}
    r.update({"Handle": handle, "pd_no": pd, "Variant SKU": f"SKU{pd}", "Title": title, "Variant Price": price,
              "Status": "draft", "Published": "FALSE", "Variant Inventory Qty": "0", "Variant Inventory Policy": "deny"})
    return r


def write(dirp: Path, rows):
    dirp.mkdir(parents=True, exist_ok=True)
    with (dirp / "products.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    inv = ["Handle", "SKU", "Canonical Product ID", "pd_no", "Available", "Inventory Policy", "Reason"]
    with (dirp / "inventory.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=inv, lineterminator="\n")
        w.writeheader()
        w.writerows([{"Handle": r["Handle"], "SKU": r["Variant SKU"], "Canonical Product ID": "", "pd_no": r["pd_no"],
                      "Available": "0", "Inventory Policy": "deny", "Reason": ""} for r in rows])


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    guard.EXPORT, guard.DELTA = tmp / "exp", tmp / "exp" / "delta"
    guard.STATE, guard.SHORTLIST, guard.OUT = tmp / "state.json", tmp / "shortlist.json", tmp / "guard.json"
    guard.SHORTLIST.write_text(json.dumps({"status": "proposed", "active_pd_nos": ["1", "2"],
                                           "active_unit_count": 2, "rules": {"max_units": 5}}), encoding="utf-8")

    # 2) 기준선이 없으면 전부 create
    write(guard.EXPORT, [row("a", "1"), row("b", "2")])
    assert guard.main() == 0
    doc = json.loads(guard.OUT.read_text(encoding="utf-8"))
    assert doc["mode"] == "initial" and doc["summary"]["create"] == 2

    # 3) 기준선 이후: 환율 수준 가격 흔들림은 변경 아님, 제목 변경은 update, 빠진 단위는 remove_proposed
    base = {"units": {h: {"fields": guard.unit_fields([r]), "pd_nos": [r["pd_no"]]}
                      for h, r in (("a", row("a", "1")), ("b", row("b", "2")), ("c", row("c", "3")))}}
    guard.STATE.write_text(json.dumps(base), encoding="utf-8")
    write(guard.EXPORT, [row("a", "1", price="18.79"), row("b", "2", title="New title")])
    assert guard.main() == 0
    doc = json.loads(guard.OUT.read_text(encoding="utf-8"))
    acts = {u["handle"]: u["action"] for u in doc["units"]}
    assert acts == {"a": "unchanged", "b": "update", "c": "remove_proposed"}, acts
    with (guard.DELTA / "products.csv").open(encoding="utf-8") as f:
        assert [r["Handle"] for r in csv.DictReader(f)] == ["b"]

    # 4) 큰 가격 변화는 update
    write(guard.EXPORT, [row("a", "1", price="24.99"), row("b", "2", title="New title")])
    guard.main()
    doc = json.loads(guard.OUT.read_text(encoding="utf-8"))
    assert {u["handle"]: u["action"] for u in doc["units"]}["a"] == "update"

    # 5) shortlist 밖 상품이 섞이면 막는다
    write(guard.EXPORT, [row("a", "1"), row("z", "99")])
    assert guard.main() == 1
    assert "shortlist 밖" in json.loads(guard.OUT.read_text(encoding="utf-8"))["violations"][0]

    # 6) 공개·재고 안전값 위반도 막는다
    bad = row("a", "1")
    bad["Published"] = "TRUE"
    write(guard.EXPORT, [bad])
    assert guard.main() == 1

print("SHORTLIST_GUARD_OK")
