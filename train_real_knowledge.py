#!/usr/bin/env python3
"""Train a small, auditable text classifier on real collected records only.

This is a real-data training step for source/topic routing. It is not an image
foundation-model trainer; it produces a lightweight classifier that can route
Shopify, AI, and image-generation knowledge records for downstream workflows.
No random synthetic samples are created.
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
MODEL = ROOT / "data" / "knowledge" / "real_knowledge_router.npz"
STATUS = ROOT / "data" / "knowledge" / "training_status.json"
TOKEN_RE = re.compile(r"[\w가-힣]{2,}", re.UNICODE)


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


def main() -> int:
    rows = load_records()
    labels = [label(row) for row in rows]
    vocab = sorted({token for row in rows for token in TOKEN_RE.findall(row["text"].lower())})
    if not vocab:
        raise SystemExit("No usable tokens in real corpus; refusing to train.")
    index = {token: i for i, token in enumerate(vocab)}
    X = np.zeros((len(rows), len(vocab)), dtype=np.float64)
    for r, row in enumerate(rows):
        for token in TOKEN_RE.findall(row["text"].lower()):
            X[r, index[token]] += 1.0
    X /= np.maximum(X.sum(axis=1, keepdims=True), 1.0)
    classes = sorted(set(labels))
    y = np.zeros((len(rows), len(classes)), dtype=np.float64)
    for i, value in enumerate(labels):
        y[i, classes.index(value)] = 1.0
    # Deterministic full-batch gradient descent. No synthetic samples or random split.
    weights = np.zeros((len(vocab), len(classes)), dtype=np.float64)
    bias = np.zeros(len(classes), dtype=np.float64)
    for _ in range(250):
        logits = X @ weights + bias
        logits -= logits.max(axis=1, keepdims=True)
        probs = np.exp(logits)
        probs /= probs.sum(axis=1, keepdims=True)
        grad = (probs - y) / len(rows)
        weights -= 0.8 * (X.T @ grad + 1e-4 * weights)
        bias -= 0.8 * grad.sum(axis=0)
    predictions = np.argmax(X @ weights + bias, axis=1)
    truth = np.argmax(y, axis=1)
    accuracy = float((predictions == truth).mean())
    digest = hashlib.sha256(CORPUS.read_bytes()).hexdigest()
    np.savez_compressed(MODEL, weights=weights, bias=bias, vocabulary=np.array(vocab), classes=np.array(classes))
    status = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "real_records": len(rows),
        "source_labels": {value: labels.count(value) for value in classes},
        "corpus_sha256": digest,
        "training_performed": True,
        "weights_updated": True,
        "model_type": "real-data bag-of-words linear router",
        "model_file": str(MODEL.relative_to(ROOT)),
        "training_accuracy_on_corpus": accuracy,
        "note": "This model routes collected knowledge records. It is not an image foundation model and does not claim image-weight training.",
    }
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
