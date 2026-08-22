#!/usr/bin/env python3
"""Validate the dashboard runtime contract using only local real artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    repo = args.repo.resolve()
    path = repo / "data" / "dashboard_runtime.json"
    if not path.exists():
        raise SystemExit(f"[ERROR] Missing runtime: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[ERROR] Invalid JSON: {exc}")

    required = {"schema_version", "generated_at", "truth_note", "pipeline", "sources", "graph", "training"}
    missing = sorted(required - data.keys())
    if missing:
        raise SystemExit(f"[ERROR] Missing top-level keys: {', '.join(missing)}")
    if not isinstance(data["pipeline"], list) or not data["pipeline"]:
        raise SystemExit("[ERROR] pipeline must be a non-empty list")

    sources = data["sources"]
    graph = data["graph"]
    training = data["training"]
    records = int(sources.get("record_count", 0) or 0)
    notes = int(graph.get("notes", 0) or 0)
    links = int(graph.get("links", 0) or 0)
    dangling = int(graph.get("dangling_links", 1) or 0)
    experts = int(training.get("experts", 0) or 0)

    checks = {
        "real_records": records > 0,
        "connected_obsidian_graph": notes > 0 and links > 0,
        "dangling_links_zero": dangling == 0,
        "training_performed": training.get("training_performed") is True,
        "weights_updated": training.get("weights_updated") is True,
        "multi_expert_moe": experts >= 2,
    }
    failed = [name for name, passed in checks.items() if not passed]
    print(json.dumps({
        "file": str(path),
        "generated_at": data["generated_at"],
        "top_level_keys": sorted(data.keys()),
        "records": records,
        "notes": notes,
        "links": links,
        "dangling_links": dangling,
        "experts": experts,
        "model_type": training.get("model_type"),
        "checks": checks,
    }, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit("[ERROR] Failed checks: " + ", ".join(failed))
    print("[OK] dashboard_runtime.json structure and real-artifact checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
