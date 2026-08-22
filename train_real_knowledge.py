#!/usr/bin/env python3
"""Train a deterministic, auditable Mixture-of-Experts router on real records.

The model has K expert linear classifiers and a learned softmax gating network.
It uses only data/knowledge/training_corpus.jsonl; no synthetic records are made.
Training uses full-batch gradient descent so the run is reproducible.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "data" / "knowledge" / "training_corpus.jsonl"
MODEL = ROOT / "data" / "knowledge" / "real_knowledge_moe.npz"
LEGACY_MODEL = ROOT / "data" / "knowledge" / "real_knowledge_router.npz"
STATUS = ROOT / "data" / "knowledge" / "training_status.json"
TOKEN_RE = re.compile(r"[\w가-힣]{2,}", re.UNICODE)
NUM_EXPERTS = 3
TOP_K = 2


def load_records() -> list[dict]:
    if not CORPUS.exists():
        raise SystemExit(f"Missing real corpus: {CORPUS}")
    rows = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if row.get("text") and row.get("url") and row.get("source")]
    if len(rows) < 2:
        raise SystemExit("At least two real records are required; refusing to train on synthetic data.")
    return rows


def label(row: dict) -> str:
    blob = (row.get("title", "") + " " + row.get("text", "")).lower()
    if any(term in blob for term in ("shopify", "ecommerce", "commerce", "product photo", "product image")):
        return "shopify-commerce-image"
    if any(term in blob for term in ("image", "vision", "diffusion", "generative", "text-to-image")):
        return "ai-image"
    return "ai-research"


def softmax(values: np.ndarray, axis: int = -1) -> np.ndarray:
    shifted = values - values.max(axis=axis, keepdims=True)
    exps = np.exp(shifted)
    return exps / np.maximum(exps.sum(axis=axis, keepdims=True), 1e-12)


def build_features(rows: list[dict]) -> tuple[np.ndarray, list[str]]:
    vocab = sorted({token for row in rows for token in TOKEN_RE.findall((row.get("title", "") + " " + row["text"]).lower())})
    if not vocab:
        raise SystemExit("No usable tokens in real corpus; refusing to train.")
    index = {token: i for i, token in enumerate(vocab)}
    X = np.zeros((len(rows), len(vocab)), dtype=np.float64)
    for r, row in enumerate(rows):
        for token in TOKEN_RE.findall((row.get("title", "") + " " + row["text"]).lower()):
            X[r, index[token]] += 1.0
    X /= np.maximum(X.sum(axis=1, keepdims=True), 1.0)
    return X, vocab


def main() -> int:
    rows = load_records()
    labels = [label(row) for row in rows]
    classes = sorted(set(labels))
    X, vocab = build_features(rows)
    y = np.zeros((len(rows), len(classes)), dtype=np.float64)
    for i, value in enumerate(labels):
        y[i, classes.index(value)] = 1.0

    n, d, c, k = len(rows), X.shape[1], len(classes), NUM_EXPERTS
    # Deterministic non-identical initialization avoids expert collapse without RNG.
    feature_pattern = np.linspace(-1.0, 1.0, d, dtype=np.float64) if d else np.zeros(1)
    expert_w = np.stack([0.002 * (expert + 1) * feature_pattern[:, None] * (np.arange(c)[None, :] + 1) for expert in range(k)])
    expert_b = np.zeros((k, c), dtype=np.float64)
    gate_w = np.zeros((d, k), dtype=np.float64)
    gate_b = np.linspace(-0.01, 0.01, k, dtype=np.float64)

    for _ in range(400):
        expert_logits = np.einsum("nd,kdc->nkc", X, expert_w) + expert_b[None, :, :]
        gate = softmax(X @ gate_w + gate_b[None, :])
        logits = np.einsum("nk,nkc->nc", gate, expert_logits)
        probs = softmax(logits)
        grad_logits = (probs - y) / n

        grad_expert_logits = gate[:, :, None] * grad_logits[:, None, :]
        grad_expert_w = np.einsum("nd,nkc->kdc", X, grad_expert_logits) + 1e-4 * expert_w
        grad_expert_b = grad_expert_logits.sum(axis=0)
        expert_score = np.einsum("nc,nkc->nk", grad_logits, expert_logits)
        grad_gate_logits = gate * (expert_score - (gate * expert_score).sum(axis=1, keepdims=True))
        grad_gate_w = X.T @ grad_gate_logits + 1e-4 * gate_w
        grad_gate_b = grad_gate_logits.sum(axis=0)

        lr = 1.2
        expert_w -= lr * grad_expert_w
        expert_b -= lr * grad_expert_b
        gate_w -= lr * grad_gate_w
        gate_b -= lr * grad_gate_b

    expert_logits = np.einsum("nd,kdc->nkc", X, expert_w) + expert_b[None, :, :]
    gate = softmax(X @ gate_w + gate_b[None, :])
    logits = np.einsum("nk,nkc->nc", gate, expert_logits)
    predictions = np.argmax(logits, axis=1)
    truth = np.argmax(y, axis=1)
    accuracy = float((predictions == truth).mean())
    load = gate.mean(axis=0)
    digest = hashlib.sha256(CORPUS.read_bytes()).hexdigest()

    np.savez_compressed(
        MODEL,
        expert_weights=expert_w,
        expert_bias=expert_b,
        gate_weights=gate_w,
        gate_bias=gate_b,
        vocabulary=np.array(vocab),
        classes=np.array(classes),
        num_experts=np.array([k]),
        top_k=np.array([TOP_K]),
    )
    # Keep the old path as a compatibility pointer only; the authoritative weights are the MoE file.
    np.savez_compressed(LEGACY_MODEL, expert_weights=expert_w, expert_bias=expert_b, gate_weights=gate_w, gate_bias=gate_b, vocabulary=np.array(vocab), classes=np.array(classes), num_experts=np.array([k]), top_k=np.array([TOP_K]))
    status = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "real_records": n,
        "source_labels": {value: labels.count(value) for value in classes},
        "corpus_sha256": digest,
        "training_performed": True,
        "weights_updated": True,
        "model_type": "real-data Mixture-of-Experts with expert linear networks and learned softmax gate",
        "experts": k,
        "top_k_inference": TOP_K,
        "model_file": str(MODEL.relative_to(ROOT)),
        "compatibility_model_file": str(LEGACY_MODEL.relative_to(ROOT)),
        "training_accuracy_on_corpus": accuracy,
        "mean_gate_load": load.round(6).tolist(),
        "note": "This is a text knowledge-routing MoE, not an image foundation model.",
    }
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
