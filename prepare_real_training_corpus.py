#!/usr/bin/env python3
"""Prepare a transparent training corpus from real collected source records.

This script never fabricates samples and never claims model training occurred.
It produces JSONL suitable for a downstream trainer and a status manifest that
separates data preparation from weight updates.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data" / "knowledge" / "real_sources.json"
OUT = ROOT / "data" / "knowledge" / "training_corpus.jsonl"
STATUS = ROOT / "data" / "knowledge" / "training_status.json"


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"Missing real source file: {SOURCE}")
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    records = []
    for source_name, source in payload.get("sources", {}).items():
        if source.get("status") != "ok":
            continue
        for item in source.get("items", []):
            title = str(item.get("title", "")).strip()
            body = str(item.get("summary", item.get("snippet", ""))).strip()
            url = str(item.get("url", "")).strip()
            if not title or not url:
                continue
            records.append({
                "source": source_name,
                "title": title,
                "text": f"{title}\n{body}".strip(),
                "url": url,
                "collected_at": payload.get("collected_at"),
            })
    with OUT.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    status = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "real_records": len(records),
        "source_status": {name: value.get("status") for name, value in payload.get("sources", {}).items()},
        "training_performed": False,
        "weights_updated": False,
        "note": "This is a real-data corpus preparation step. A model trainer must explicitly consume this JSONL before claiming weight updates.",
        "corpus": str(OUT.relative_to(ROOT)),
    }
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
