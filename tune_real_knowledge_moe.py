#!/usr/bin/env python3
"""Tune the real-data MoE without synthetic records.

The search is deterministic and uses a URL-hash validation split. Every candidate
trains the same expert/gating architecture on the real JSONL corpus. The best
validation candidate is saved separately so the current production weights remain
untouched unless --promote is explicitly supplied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from train_real_knowledge import build_features, label, load_records, softmax

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "data" / "knowledge" / "training_corpus.jsonl"
DEFAULT_MODEL = ROOT / "data" / "knowledge" / "real_knowledge_moe_tuned.npz"
DEFAULT_REPORT = ROOT / "data" / "knowledge" / "moe_tuning_report.json"


def parse_values(raw: str, cast):
    return tuple(cast(value.strip()) for value in raw.split(",") if value.strip())


def split_rows(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    # Stable, non-random split based only on each real record URL.
    validation = np.array([int(hashlib.sha256(row["url"].encode()).hexdigest()[:8], 16) % 5 == 0 for row in rows])
    if validation.sum() == 0 or validation.sum() == len(rows):
        validation[np.arange(0, len(rows), 5)] = True
    return ~validation, validation


def init_params(d: int, c: int, k: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    pattern = np.linspace(-1.0, 1.0, d, dtype=np.float64) if d else np.zeros(1)
    expert_w = np.stack([0.002 * (expert + 1) * pattern[:, None] * (np.arange(c)[None, :] + 1) for expert in range(k)])
    expert_b = np.zeros((k, c), dtype=np.float64)
    gate_w = np.zeros((d, k), dtype=np.float64)
    gate_b = np.linspace(-0.01, 0.01, k, dtype=np.float64)
    return expert_w, expert_b, gate_w, gate_b


def predict(X: np.ndarray, params: tuple[np.ndarray, ...], temperature: float) -> tuple[np.ndarray, np.ndarray]:
    expert_w, expert_b, gate_w, gate_b = params
    expert_logits = np.einsum("nd,kdc->nkc", X, expert_w) + expert_b[None, :, :]
    gate = softmax((X @ gate_w + gate_b[None, :]) / temperature)
    logits = np.einsum("nk,nkc->nc", gate, expert_logits)
    return logits, gate


def cross_entropy(y: np.ndarray, logits: np.ndarray) -> float:
    probs = softmax(logits)
    return float(-np.mean(np.sum(y * np.log(np.maximum(probs, 1e-12)), axis=1)))


def train(X: np.ndarray, y: np.ndarray, k: int, steps: int, lr: float, l2: float, temperature: float):
    n, d, c = X.shape[0], X.shape[1], y.shape[1]
    params = list(init_params(d, c, k))
    loss_history = []
    for step in range(steps):
        expert_w, expert_b, gate_w, gate_b = params
        logits, gate = predict(X, tuple(params), temperature)
        probs = softmax(logits)
        grad_logits = (probs - y) / max(n, 1)
        grad_expert_logits = gate[:, :, None] * grad_logits[:, None, :]
        grad_expert_w = np.einsum("nd,nkc->kdc", X, grad_expert_logits) + l2 * expert_w
        grad_expert_b = grad_expert_logits.sum(axis=0)
        expert_logits = np.einsum("nd,kdc->nkc", X, expert_w) + expert_b[None, :, :]
        expert_score = np.einsum("nc,nkc->nk", grad_logits, expert_logits)
        grad_gate_logits = gate * (expert_score - (gate * expert_score).sum(axis=1, keepdims=True)) / temperature
        grad_gate_w = X.T @ grad_gate_logits + l2 * gate_w
        grad_gate_b = grad_gate_logits.sum(axis=0)
        params[0] = expert_w - lr * grad_expert_w
        params[1] = expert_b - lr * grad_expert_b
        params[2] = gate_w - lr * grad_gate_w
        params[3] = gate_b - lr * grad_gate_b
        if step == 0 or (step + 1) % max(1, steps // 20) == 0 or step == steps - 1:
            current_logits, _ = predict(X, tuple(params), temperature)
            data_loss = cross_entropy(y, current_logits)
            weight_loss = 0.5 * l2 * (float(np.sum(params[0] ** 2)) + float(np.sum(params[2] ** 2)))
            loss_history.append({"step": step + 1, "data_loss": data_loss, "weight_loss": weight_loss, "total_loss": data_loss + weight_loss})
    return tuple(params), loss_history


def accuracy(X: np.ndarray, y: np.ndarray, params: tuple[np.ndarray, ...], temperature: float) -> float:
    logits, _ = predict(X, params, temperature)
    return float((np.argmax(logits, axis=1) == np.argmax(y, axis=1)).mean()) if len(X) else 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--promote", action="store_true", help="also replace production MoE files with the best candidate")
    parser.add_argument("--steps", type=int, default=250, help="gradient steps per candidate")
    parser.add_argument("--experts", default="3,4,5", help="comma-separated expert counts, e.g. 3")
    parser.add_argument("--learning-rates", default="0.7,1.2", help="comma-separated learning rates")
    parser.add_argument("--l2-values", default="0.0001", help="comma-separated L2 values")
    parser.add_argument("--temperatures", default="0.9,1.1", help="comma-separated gate temperatures")
    parser.add_argument("--model-out", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--report-out", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    rows = load_records()
    labels = [label(row) for row in rows]
    classes = sorted(set(labels))
    X, vocab = build_features(rows)
    y = np.zeros((len(rows), len(classes)), dtype=np.float64)
    for i, value in enumerate(labels):
        y[i, classes.index(value)] = 1.0
    train_mask, valid_mask = split_rows(rows)
    candidates = []
    expert_values = parse_values(args.experts, int)
    learning_rates = parse_values(args.learning_rates, float)
    l2_values = parse_values(args.l2_values, float)
    temperatures = parse_values(args.temperatures, float)
    for experts in expert_values:
        for lr in learning_rates:
            for l2 in l2_values:
                for temperature in temperatures:
                    params, loss_history = train(X[train_mask], y[train_mask], experts, args.steps, lr, l2, temperature)
                    train_acc = accuracy(X[train_mask], y[train_mask], params, temperature)
                    valid_acc = accuracy(X[valid_mask], y[valid_mask], params, temperature)
                    final_loss = loss_history[-1]
                    expert_w, expert_b, gate_w, gate_b = params
                    _, gate_train = predict(X[train_mask], params, temperature)
                    candidates.append({"experts": experts, "lr": lr, "l2": l2, "temperature": temperature, "train_accuracy": train_acc, "validation_accuracy": valid_acc, "initial_loss": loss_history[0]["total_loss"], "final_loss": final_loss["total_loss"], "best_loss": min(item["total_loss"] for item in loss_history), "expert_weight_l2": float(np.linalg.norm(expert_w)), "gate_weight_l2": float(np.linalg.norm(gate_w)), "gate_load_std": float(np.std(gate_train.mean(axis=0))), "loss_history": loss_history, "params": params})
    best = max(candidates, key=lambda item: (item["validation_accuracy"], item["train_accuracy"], -item["final_loss"], -item["experts"]))
    params = best.pop("params")
    expert_w, expert_b, gate_w, gate_b = params
    _, gate = predict(X, params, best["temperature"])
    args.model_out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.model_out, expert_weights=expert_w, expert_bias=expert_b, gate_weights=gate_w, gate_bias=gate_b, vocabulary=np.array(vocab), classes=np.array(classes), num_experts=np.array([best["experts"]]), top_k=np.array([min(2, best["experts"])]), tuning_temperature=np.array([best["temperature"]]))
    report = {"updated_at": datetime.now(timezone.utc).isoformat(), "real_records": len(rows), "train_records": int(train_mask.sum()), "validation_records": int(valid_mask.sum()), "steps_per_candidate": args.steps, "search_space": {"experts": expert_values, "learning_rates": learning_rates, "l2_values": l2_values, "temperatures": temperatures}, "candidates": len(candidates), "best": best, "mean_gate_load": gate.mean(axis=0).round(6).tolist(), "model_file": str(args.model_out.relative_to(ROOT)), "promoted": bool(args.promote), "note": "All candidates use only real records from training_corpus.jsonl; no synthetic data."}
    args.report_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.promote:
        for target in (ROOT / "data/knowledge/real_knowledge_moe.npz", ROOT / "data/knowledge/real_knowledge_router.npz"):
            target.write_bytes(args.model_out.read_bytes())
        status_path = ROOT / "data/knowledge/training_status.json"
        status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
        status.update({
            "updated_at": report["updated_at"],
            "training_performed": True,
            "weights_updated": True,
            "experts": best["experts"],
            "tuning_promoted": True,
            "tuning_steps": args.steps,
            "tuning_validation_accuracy": best["validation_accuracy"],
            "tuning_final_loss": best["final_loss"],
            "tuning_gate_load_std": best["gate_load_std"],
            "model_file": "data/knowledge/real_knowledge_moe.npz",
        })
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
