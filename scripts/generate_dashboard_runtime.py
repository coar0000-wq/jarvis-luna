#!/usr/bin/env python3
"""Generate a truthful, static-site-friendly runtime snapshot from real artifacts."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "dashboard_runtime.json"
VAULT = ROOT / "obsidian" / "JARVIS_LUNA"
KNOWLEDGE = ROOT / "data" / "knowledge"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def iso_mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def graph_metrics() -> dict:
    notes = list(VAULT.rglob("*.md")) if VAULT.exists() else []
    links = 0
    targets: set[str] = set()
    for note in notes:
        text = note.read_text(encoding="utf-8", errors="ignore")
        found = re.findall(r"\[\[([^\]|#]+)", text)
        links += len(found)
        for target in found:
            normalized = target.strip().replace('\\\\', '/')
            normalized = normalized.rsplit('/', 1)[-1]
            if normalized.endswith('.md'):
                normalized = normalized[:-3]
            if normalized:
                targets.add(normalized)
    stems = {p.stem for p in notes}
    dangling = sorted(x for x in targets if x not in stems)
    return {
        "notes": len(notes),
        "links": links,
        "dangling_links": len(dangling),
        "records": len(list((VAULT / "Knowledge" / "Records").glob("*.md"))) if (VAULT / "Knowledge" / "Records").exists() else 0,
        "sources": len(list((VAULT / "Knowledge" / "Sources").glob("*.md"))) if (VAULT / "Knowledge" / "Sources").exists() else 0,
        "topics": len(list((VAULT / "Knowledge" / "Topics").glob("*.md"))) if (VAULT / "Knowledge" / "Topics").exists() else 0,
        "audit": "passed" if not dangling else "failed",
        "last_generated": max((iso_mtime(p) for p in notes), default=None),
    }


def source_metrics() -> dict:
    data = load_json(KNOWLEDGE / "real_sources.json", {})
    records = load_json(KNOWLEDGE / "training_corpus.jsonl", None)
    record_count = 0
    corpus_path = KNOWLEDGE / "training_corpus.jsonl"
    if corpus_path.exists():
        record_count = sum(1 for line in corpus_path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip())
    labels = {}
    if isinstance(data, dict):
        labels = data.get("source_counts") or data.get("counts") or {}
    return {
        "status": "completed" if corpus_path.exists() and record_count else "waiting",
        "record_count": record_count,
        "source_counts": labels,
        "updated_at": iso_mtime(KNOWLEDGE / "real_sources.json"),
    }


def training_metrics() -> dict:
    status = load_json(KNOWLEDGE / "training_status.json", {})
    trained = bool(status.get("training_performed") and status.get("weights_updated"))
    return {
        "status": "completed" if trained else "not_verified",
        "training_performed": bool(status.get("training_performed")),
        "weights_updated": bool(status.get("weights_updated")),
        "records": status.get("real_records", 0),
        "model_type": status.get("model_type", "확인 필요"),
        "experts": status.get("experts", 0),
        "accuracy": status.get("training_accuracy_on_corpus"),
        "validation_accuracy": status.get("tuning_validation_accuracy"),
        "final_loss": status.get("tuning_final_loss"),
        "gate_load_std": status.get("tuning_gate_load_std"),
        "tuning_promoted": bool(status.get("tuning_promoted")),
        "tuning_steps": status.get("tuning_steps"),
        "updated_at": status.get("updated_at") or iso_mtime(KNOWLEDGE / "training_status.json"),
    }


def main() -> None:
    graph = graph_metrics()
    sources = source_metrics()
    training = training_metrics()
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema_version": 1,
        "generated_at": now,
        "truth_note": "상태는 저장소에 존재하는 실제 산출물 기준이며, 실행 기록이 없는 작업은 진행중으로 표시하지 않음.",
        "pipeline": [
            {"id": "collect", "title": "실제 데이터 수집", "status": sources["status"], "detail": f'{sources["record_count"]}개 코퍼스 레코드'},
            {"id": "graph", "title": "Obsidian 그래프 반영·검증", "status": "completed" if graph["audit"] == "passed" else "failed", "detail": f'{graph["notes"]}개 노트 · {graph["links"]}개 링크 · 끊어진 링크 {graph["dangling_links"]}개'},
            {"id": "dashboard", "title": "GitHub Pages 대시보드 데이터", "status": "generated", "detail": "dashboard_runtime.json 생성 완료"},
            {"id": "train", "title": "실제 데이터 MoE 학습", "status": training["status"], "detail": f'{training["records"]}건 · {training["experts"]} experts · 정확도 {training["accuracy"]:.2%}' if isinstance(training["accuracy"], (int, float)) else f'{training["records"]}건'},
            {"id": "publish", "title": "저장소·Pages 반영", "status": "pending_workflow" if training["status"] != "completed" else "ready_for_pages", "detail": "GitHub Actions Pages 배포 워크플로에서 반영"},
        ],
        "sources": sources,
        "graph": graph,
        "training": training,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
