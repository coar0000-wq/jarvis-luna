#!/usr/bin/env python3
"""build_product_master.py

pd_no  = 다이소 원천 키 (수집·URL·재크롤)
canonical_product_id (CP) = 소싱·마케팅·리스팅 공통 키

어디에 두나
  스크립트:  scripts/build_product_master.py
  산출물:    data/product_master.json
  레지스트리(동일 파일 내 pd_no_to_cp): 재실행 시 CP 불변

워크플로
  다이소 수집 후 → 본 스크립트 → score_shopify_demand / build_market_team 이
  product_master.pd_no_to_cp 로 CP를 주입

Usage:
  python scripts/build_product_master.py
  python scripts/build_product_master.py --root .
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

KST = timezone(timedelta(hours=9))


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def slugify(name: str, pd_no: str) -> str:
    s = (name or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if len(s) < 3:
        return f"daiso-{pd_no}"
    return s[:60]


def build_master(root: Path) -> dict:
    products_path = root / "data" / "daiso_real" / "products.json"
    s_path = root / "data" / "daiso_real" / "shopify_s_recommendations.json"
    master_path = root / "data" / "product_master.json"

    prods_doc = load_json(products_path) or {}
    items = list(prods_doc.get("products") or [])
    s_doc = load_json(s_path) or {}
    s_map = {
        str(r.get("pd_no")): r
        for r in (s_doc.get("recommendations") or [])
        if r.get("pd_no")
    }

    # 기존 레지스트리 유지 → CP 번호 불변
    prev = load_json(master_path) or {}
    registry: dict[str, str] = dict(prev.get("pd_no_to_cp") or {})

    def ensure_cp(pd_no: str) -> str:
        if pd_no in registry:
            return registry[pd_no]
        # 다음 번호 = 기존 max + 1
        max_n = 0
        for cp in registry.values():
            m = re.fullmatch(r"CP(\d{5})", str(cp))
            if m:
                max_n = max(max_n, int(m.group(1)))
        n = max_n + 1
        cp = f"CP{n:05d}"
        registry[pd_no] = cp
        return cp

    # 신규 pd_no는 정렬 순으로 발급해 첫 빌드 안정성 확보
    items_sorted = sorted(items, key=lambda x: str(x.get("pd_no") or ""))
    products_out: list[dict] = []

    for p in items_sorted:
        pd = str(p.get("pd_no") or "").strip()
        if not pd:
            continue
        cp = ensure_cp(pd)
        sr = s_map.get(pd) or {}
        name = p.get("name") or ""
        products_out.append(
            {
                "canonical_product_id": cp,
                "pd_no": pd,
                "source": "daiso",
                "slug": slugify(name, pd),
                "name_ko": name,
                "brand": p.get("brand") or "",
                "brand_norm": (p.get("brand") or "").strip(),
                "bucket": p.get("bucket") or p.get("site_category") or "",
                "price_krw": p.get("price_krw"),
                "rating": p.get("rating"),
                "review_count": p.get("review_count"),
                "url": p.get("url") or "",
                "image_url": p.get("image_url") or "",
                "status": "active",
                "grade": sr.get("grade"),
                "shopify_score": sr.get("shopify_score"),
                "registerable": sr.get("registerable") if sr else None,
                "teams": {
                    "sourcing": True,
                    "marketing": bool(sr),
                    "listing": bool(sr.get("registerable")),
                },
            }
        )

    # 레지스트리 키 정렬 (가독성)
    registry_sorted = dict(sorted(registry.items(), key=lambda kv: kv[1]))

    master = {
        "generated_at": datetime.now(KST).isoformat(),
        "id_scheme": "CP + 5-digit, 1:1 with daiso pd_no; registry never renumbers",
        "source_products": "data/daiso_real/products.json",
        "count": len(products_out),
        "s_grade_count": sum(1 for x in products_out if x.get("grade") == "S"),
        "registry_note": "pd_no_to_cp is the source of truth. Do not delete entries.",
        "pd_no_to_cp": registry_sorted,
        "products": products_out,
    }
    save_json(master_path, master)
    return master


def inject_cp_into_s(root: Path, registry: dict[str, str]) -> int:
    """shopify_s_recommendations.json 에 canonical_product_id 주입."""
    s_path = root / "data" / "daiso_real" / "shopify_s_recommendations.json"
    s_doc = load_json(s_path)
    if not s_doc:
        return 0
    n = 0
    for r in s_doc.get("recommendations") or []:
        pd = str(r.get("pd_no") or "")
        cp = registry.get(pd)
        if cp:
            r["canonical_product_id"] = cp
            n += 1
    save_json(s_path, s_doc)
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument(
        "--inject-s",
        action="store_true",
        help="S recommendations JSON에도 CP 필드를 넣습니다",
    )
    args = ap.parse_args()
    root = args.root.resolve()
    master = build_master(root)
    print(
        f"OK product_master.json count={master['count']} "
        f"S={master['s_grade_count']}"
    )
    if args.inject_s:
        n = inject_cp_into_s(root, master["pd_no_to_cp"])
        print(f"OK injected CP into S recommendations: {n}")


if __name__ == "__main__":
    main()
