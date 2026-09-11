#!/usr/bin/env python3
"""products.json count ↔ collection_status.totals.products 정합."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "data" / "daiso_real" / "products.json"
COLL = ROOT / "data" / "daiso_real" / "collection_status.json"

def main() -> int:
    prod = json.loads(PROD.read_text(encoding="utf-8"))
    coll = json.loads(COLL.read_text(encoding="utf-8"))
    n = prod.get("count") or len(prod.get("products") or [])
    old = (coll.get("totals") or {}).get("products")
    coll.setdefault("totals", {})["products"] = n
    from collections import Counter
    buckets = Counter((p.get("bucket") or "?") for p in (prod.get("products") or []))
    coll["totals"]["by_bucket"] = dict(buckets)
    coll["totals_aligned_at"] = datetime.now(timezone.utc).isoformat()
    coll["totals_align_note"] = f"products.json count {n} 기준 정합 (이전 {old})"
    COLL.write_text(json.dumps(coll, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"aligned totals.products {old} -> {n}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
