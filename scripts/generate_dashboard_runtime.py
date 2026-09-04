#!/usr/bin/env python3
"""Generate a truthful, static-site-friendly runtime snapshot from real artifacts."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 기준 경로 설정
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "dashboard_runtime.json"
VAULT = ROOT / "obsidian" / "JARVIS_LUNA"
KNOWLEDGE = ROOT / "data" / "knowledge"
HISTORY = KNOWLEDGE / "cumulative_history.json"

# 한국 시간(KST)
KST = timezone(timedelta(hours=9))


def load_json(path: Path, default: any) -> any:
    """안전하게 JSON 파일을 로드합니다."""
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def iso_mtime(path: Path) -> str | None:
    """파일의 수정 시간을 KST ISO 8601 포맷으로 반환합니다."""
    try:
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime, KST).isoformat()
    except OSError:
        pass
    return None


def get_md_count(base: Path, *subdirs: str) -> int:
    """특정 하위 디렉토리 내부의 마크다운 파일 개수를 효율적으로 계산합니다."""
    target_dir = base.joinpath(*subdirs)
    if target_dir.exists() and target_dir.is_dir():
        return sum(1 for _ in target_dir.glob("*.md"))
    return 0


def graph_metrics() -> dict:
    """Obsidian Vault 내의 마크다운 노트 및 링크 연결 상태를 분석합니다."""
    notes = list(VAULT.rglob("*.md")) if VAULT.exists() else []
    links = 0
    targets: set[str] = set()

    link_pattern = re.compile(r"\[\[([^\]|#]+)")

    # 링크 대상을 폴더별로 나눠 담는다. 파이프라인이 만든 노트(Knowledge/)와
    # 사용자가 직접 넣은 노트(Personal/)는 성격이 달라 같은 기준으로 볼 수 없다.
    generated: set[str] = set()
    personal: set[str] = set()

    for note in notes:
        try:
            text = note.read_text(encoding="utf-8", errors="ignore")
            found = link_pattern.findall(text)
            links += len(found)
        except OSError:
            continue

        try:
            top = note.relative_to(VAULT).parts[0]
        except ValueError:
            top = ""
        bucket = personal if top == "Personal" else generated

        for target in found:
            normalized = target.strip().replace("\\", "/")
            normalized = normalized.rsplit("/", 1)[-1]
            if normalized.endswith(".md"):
                normalized = normalized[:-3]
            if normalized:
                # Obsidian 은 파일명을 대소문자 구분 없이 찾는다. 여기서 구분하면
                # Windows 가 기존 파일명 대소문자를 유지하는 탓에 멀쩡한 링크가
                # 끊어진 것으로 잡힌다. (ASML-reports... vs Asml-Reports...)
                targets.add(normalized)
                bucket.add(normalized.lower())

    stems = {p.stem.lower() for p in notes}
    dangling_generated = sorted(x for x in generated if x not in stems)
    dangling_personal = sorted(x for x in personal if x not in stems)
    valid_mtimes = [iso_mtime(p) for p in notes if iso_mtime(p) is not None]

    return {
        "notes": len(notes),
        "links": links,
        # 파이프라인 품질 지표는 생성분만 센다.
        "dangling_links": len(dangling_generated),
        "dangling_personal": len(dangling_personal),
        "dangling_personal_note": (
            "사용자가 직접 넣은 Personal 노트의 내부 링크. 원본 볼트에서 일부만"
            " 가져와 대상 노트가 없는 것으로, 파이프라인 오류가 아니다."
        ),
        "records": get_md_count(VAULT, "Knowledge", "Records"),
        "sources": get_md_count(VAULT, "Knowledge", "Sources"),
        "topics": get_md_count(VAULT, "Knowledge", "Topics"),
        "orgs": get_md_count(VAULT, "Knowledge", "Orgs"),
        "audit": "failed" if dangling_generated else "passed",
        "last_generated": max(valid_mtimes, default=None),
    }


def source_metrics() -> dict:
    """수집된 코퍼스 및 데이터 소스 메트릭을 로드합니다."""
    data = load_json(KNOWLEDGE / "real_sources.json", {})
    record_count = 0
    corpus_path = KNOWLEDGE / "training_corpus.jsonl"

    if corpus_path.exists():
        try:
            with corpus_path.open("r", encoding="utf-8", errors="ignore") as f:
                record_count = sum(1 for line in f if line.strip())
        except OSError:
            record_count = 0

    labels = {}
    if isinstance(data, dict):
        labels = data.get("source_counts") or data.get("counts") or {}

    return {
        "status": "completed" if corpus_path.exists() and record_count > 0 else "waiting",
        "record_count": record_count,
        "source_counts": labels,
        "updated_at": iso_mtime(KNOWLEDGE / "real_sources.json"),
    }


def training_metrics() -> dict:
    """MoE 모델의 최신 학습 상태 및 메트릭을 로드합니다."""
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


FIELDS = ("records", "notes", "links")


def cumulative_metrics(graph: dict, sources: dict) -> dict:
    """과거 실행 내역과 비교하여 누적 메트릭을 계산하고 저장합니다."""
    now = datetime.now(KST).isoformat()

    current = {
        "records": int(sources.get("record_count") or 0),
        "notes": int(graph.get("notes") or 0),
        "links": int(graph.get("links") or 0),
    }

    hist = load_json(HISTORY, None)

    if not isinstance(hist, dict) or "totals" not in hist:
        hist = {
            "schema_version": 1,
            "note": (
                "누적 집계는 이 파일이 처음 생성된 시점부터 시작합니다. "
                "그 이전 실행 기록이 없으므로 과거 수치는 추정하지 않습니다."
            ),
            "baseline": {**current, "recorded_at": now},
            "totals": dict(current),
            "last_snapshot": {**current, "recorded_at": now},
            "runs": [],
        }
        added = {k: 0 for k in FIELDS}
    else:
        prev = hist.get("last_snapshot") or {}
        added = {}

        for k in FIELDS:
            before = prev.get(k)
            before = current[k] if before is None else int(before)
            added[k] = max(0, current[k] - before)
            hist["totals"][k] = int(hist["totals"].get(k, 0)) + added[k]

        hist["last_snapshot"] = {**current, "recorded_at": now}

    hist["runs"] = (hist.get("runs", []) + [{"at": now, **current, "added": added}])[-90:]
    hist["updated_at"] = now

    try:
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY.open("w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError as e:
        print(f"Warning: 누적 히스토리 저장 실패 - {e}")

    return {
        "totals": {k: int(hist["totals"].get(k, 0)) for k in FIELDS},
        "prior_totals": {k: int(hist["totals"].get(k, 0)) - added[k] for k in FIELDS},
        "added_this_run": added,
        "current_snapshot": current,
        "since": hist["baseline"].get("recorded_at"),
        "runs_recorded": len(hist["runs"]),
    }


def main() -> None:
    graph = graph_metrics()
    sources = source_metrics()
    training = training_metrics()
    cumulative = cumulative_metrics(graph, sources)

    now = datetime.now(KST).isoformat()

    accuracy_display = (
        f'{training["accuracy"]:.2%}'
        if isinstance(training["accuracy"], (int, float))
        else str(training["accuracy"] or "N/A")
    )

    # 기존 dashboard_runtime.json에 있던 global_channels / exchange_rate 보존
    # (sync_channels.py가 나중에 덮어쓰지만, 중간 실패 시 데이터 소실 방지)
    prev = load_json(OUT, {})
    prev_global = prev.get("global_channels") if isinstance(prev, dict) else None
    prev_fx = prev.get("exchange_rate") if isinstance(prev, dict) else None
    prev_synced = prev.get("last_synced") if isinstance(prev, dict) else None

    payload = {
        "schema_version": 1,
        "generated_at": now,
        "truth_note": (
            "상태는 저장소에 존재하는 실제 산출물 기준이며, "
            "실행 기록이 없는 작업은 진행중으로 표시하지 않음."
        ),
        "pipeline": [
            {
                "id": "collect",
                "title": "실제 데이터 수집",
                "status": sources["status"],
                "detail": f'{sources["record_count"]}개 코퍼스 레코드',
            },
            {
                "id": "graph",
                "title": "Obsidian 그래프 반영·검증",
                "status": "completed" if graph["audit"] == "passed" else "failed",
                "detail": (
                    f'{graph["notes"]}개 노트 · '
                    f'{graph["links"]}개 링크 · '
                    f'끊어진 링크 {graph["dangling_links"]}개'
                    + (f' · 개인 노트 {graph["dangling_personal"]}개 별도'
                       if graph.get("dangling_personal") else '')
                ),
            },
            {
                "id": "dashboard",
                "title": "GitHub Pages 대시보드 데이터",
                "status": "generated",
                "detail": "dashboard_runtime.json 생성 완료",
            },
            {
                "id": "train",
                "title": "실제 데이터 MoE 학습",
                "status": training["status"],
                "detail": (
                    f'{training["records"]}건 · '
                    f'{training["experts"]} experts · '
                    f'정확도 {accuracy_display}'
                ),
            },
            {
                "id": "publish",
                "title": "저장소·Pages 반영",
                "status": (
                    "pending_workflow"
                    if training["status"] != "completed"
                    else "ready_for_pages"
                ),
                "detail": "GitHub Actions Pages 배포 워크플로에서 반영",
            },
        ],
        "sources": sources,
        "graph": graph,
        "training": training,
        "cumulative": cumulative,
    }

    # 이전 global_channels / 환율 데이터가 있으면 유지
    if isinstance(prev_global, dict) and prev_global:
        payload["global_channels"] = prev_global
    if isinstance(prev_fx, dict) and prev_fx:
        payload["exchange_rate"] = prev_fx
    if prev_synced:
        payload["last_synced"] = prev_synced

    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")

        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except OSError as e:
        print(f"Error: 런타임 스냅샷 데이터 생성 실패 - {e}")


if __name__ == "__main__":
    main()
