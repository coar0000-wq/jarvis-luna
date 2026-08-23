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


def load_existing() -> dict:
    """이미 쌓인 코퍼스를 URL 기준으로 읽어들인다."""
    existing: dict = {}
    if not OUT.exists():
        return existing
    for line in OUT.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = str(rec.get("url", "")).strip()
        if url:
            existing[url] = rec
    return existing


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"Missing real source file: {SOURCE}")
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    collected_at = payload.get("collected_at")

    # 코퍼스는 누적한다. 매 실행마다 덮어쓰면 30분 주기로 수집해도
    # 레코드 수가 늘지 않는다. URL을 키로 중복만 제거한다.
    records = load_existing()
    before = len(records)
    added = 0

    for source_name, source in payload.get("sources", {}).items():
        if source.get("status") != "ok":
            continue
        for item in source.get("items", []):
            title = str(item.get("title", "")).strip()
            body = str(item.get("summary", item.get("snippet", ""))).strip()
            url = str(item.get("url", "")).strip()
            if not title or not url:
                continue
            prev = records.get(url)
            records[url] = {
                "source": source_name,
                "title": title,
                "text": f"{title}\n{body}".strip(),
                "url": url,
                "first_seen_at": (prev or {}).get("first_seen_at")
                                 or (prev or {}).get("collected_at") or collected_at,
                "collected_at": collected_at,
            }
            if prev is None:
                added += 1

    ordered = sorted(records.values(),
                     key=lambda r: (r.get("first_seen_at") or "", r.get("url") or ""))
    with OUT.open("w", encoding="utf-8") as handle:
        for record in ordered:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    status = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "real_records": len(ordered),
        "records_before": before,
        "records_added": added,
        "source_status": {name: value.get("status") for name, value in payload.get("sources", {}).items()},
        "training_performed": False,
        "weights_updated": False,
        "note": "실제 수집 데이터 누적 코퍼스. URL 기준 중복 제거하며 기존 레코드는 보존한다. 가중치 갱신은 학습기가 별도로 수행한다.",
        "corpus": str(OUT.relative_to(ROOT)),
    }
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
