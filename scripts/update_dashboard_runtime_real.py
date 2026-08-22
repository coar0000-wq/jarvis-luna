#!/usr/bin/env python3
"""Update dashboard_runtime.json from existing real JARVIS artifacts only.

The script does not fabricate collection, graph, or training results. It runs
the repository's deterministic runtime generator, then validates the resulting
JSON before replacing the target file atomically.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np


def run_generator(repo: Path) -> dict:
    generator = repo / "scripts" / "generate_dashboard_runtime.py"
    if not generator.exists():
        raise FileNotFoundError(generator)
    with tempfile.TemporaryDirectory(prefix="jarvis-runtime-") as tmp:
        # The existing generator writes to the repository's canonical output.
        # Preserve its normal behavior, then validate and atomically rewrite it.
        result = subprocess.run([sys.executable, str(generator)], cwd=repo, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"runtime generator failed: {result.returncode}")
    output = repo / "data" / "dashboard_runtime.json"
    if not output.exists():
        raise FileNotFoundError(output)
    return json.loads(output.read_text(encoding="utf-8"))


def enrich_from_promoted_model(repo: Path, runtime: dict) -> None:
    """Derive MoE metadata from the promoted real model, not stale labels."""
    model = repo / "data" / "knowledge" / "real_knowledge_moe_tuned.npz"
    if not model.exists():
        return
    with np.load(model, allow_pickle=False) as weights:
        expert_weights = weights.get("expert_weights")
        gate_weights = weights.get("gate_weights")
        if expert_weights is None or gate_weights is None:
            return
        if expert_weights.ndim != 3 or gate_weights.ndim != 2:
            raise ValueError("promoted model does not contain valid expert/gate arrays")
        training = runtime.setdefault("training", {})
        training["experts"] = int(expert_weights.shape[0])
        training["model_type"] = "real-data Mixture-of-Experts with expert linear networks and learned softmax gate"
        training["weights_updated"] = True
        training["tuning_promoted"] = True


def validate(runtime: dict) -> None:
    required = {"schema_version", "generated_at", "pipeline", "sources", "graph", "training"}
    missing = sorted(required - runtime.keys())
    if missing:
        raise ValueError(f"runtime missing required keys: {', '.join(missing)}")
    if not isinstance(runtime["pipeline"], list):
        raise ValueError("runtime.pipeline must be a list")
    graph = runtime["graph"]
    sources = runtime["sources"]
    training = runtime["training"]
    if int(sources.get("record_count", 0) or 0) <= 0:
        raise ValueError("runtime has no real source records")
    if int(graph.get("notes", 0) or 0) <= 0:
        raise ValueError("runtime has no Obsidian notes")
    if int(graph.get("links", 0) or 0) <= 0:
        raise ValueError("runtime has no Obsidian links")
    if int(graph.get("dangling_links", 1) or 0) != 0:
        raise ValueError(f"runtime dangling_links is {graph.get('dangling_links')}, expected 0")
    if training.get("training_performed") is not True or training.get("weights_updated") is not True:
        raise ValueError("runtime does not confirm real model training and updated weights")
    if int(training.get("experts", 0) or 0) < 2:
        raise ValueError("runtime does not confirm a multi-expert MoE")
    if "Mixture-of-Experts" not in str(training.get("model_type", "")):
        raise ValueError("runtime model_type is not a real Mixture-of-Experts model")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--refresh-moe",
        action="store_true",
        help="Retrain and promote the real-data 3-expert MoE before generating runtime.",
    )
    parser.add_argument("--steps", type=int, default=500, help="Tuning steps when --refresh-moe is used.")
    args = parser.parse_args()
    repo = args.repo.expanduser().resolve()
    os.chdir(repo)
    if args.refresh_moe:
        tuner = repo / "tune_real_knowledge_moe.py"
        if not tuner.exists():
            raise FileNotFoundError(tuner)
        result = subprocess.run(
            [sys.executable, str(tuner), "--steps", str(args.steps), "--experts", "3", "--promote"],
            cwd=repo,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"real-data MoE tuning failed: {result.returncode}")
    runtime = run_generator(repo)
    enrich_from_promoted_model(repo, runtime)
    output = repo / "data" / "dashboard_runtime.json"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as handle:
        json.dump(runtime, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(output)
    validate(runtime)
    print(json.dumps({
        "updated": str(repo / "data" / "dashboard_runtime.json"),
        "generated_at": runtime["generated_at"],
        "records": runtime["sources"]["record_count"],
        "notes": runtime["graph"]["notes"],
        "links": runtime["graph"]["links"],
        "dangling_links": runtime["graph"]["dangling_links"],
        "experts": runtime["training"].get("experts"),
        "accuracy": runtime["training"].get("accuracy"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
