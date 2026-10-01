#!/usr/bin/env python3
"""자기개선 전용 파일 저장 가드와 근거 기반 운영 메모리. 외부 호출 없음."""
from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

WINDOW_DAYS = 14
LOOPS = frozenset({"topics", "sourcing", "design"})


class WriteConflict(RuntimeError):
    """다른 작업의 변경을 덮어쓰지 않고 이번 쓰기를 중단한다."""


def file_revision(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return "missing"


def read_snapshot(path: Path, default):
    """파싱한 내용과 비교할 해시를 반드시 같은 읽기에서 얻는다."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return default, "missing"
    digest = hashlib.sha256(raw).hexdigest()
    try:
        return json.loads(raw.decode("utf-8-sig")), digest
    except (UnicodeError, ValueError):
        return default, digest


def guarded_save(path: Path, value, dry: bool, *, expected_revision: str | None = None) -> None:
    if dry:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    tmp = path.with_suffix(path.suffix + "." + uuid.uuid4().hex + ".tmp")
    owned = False
    try:
        try:
            with lock.open("x", encoding="utf-8") as handle:
                owned = True
                handle.write(datetime.now(timezone.utc).isoformat())
        except FileExistsError as exc:
            raise WriteConflict(f"{path.name}: another writer holds the lock") from exc
        if expected_revision is not None and file_revision(path) != expected_revision:
            raise WriteConflict(f"{path.name}: source changed; re-read and evaluate again")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    finally:
        if owned:
            tmp.unlink(missing_ok=True)
            lock.unlink(missing_ok=True)


def _timestamp(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(timezone.utc) if result.tzinfo else None


def consolidate_memory(history: dict, ledger: list, at: str) -> dict:
    """여러 실행의 동일 사건을 묶는다. 관찰 요약만 만들고 정책은 변경하지 않는다.

    자유 형식 오류·고객 자료·비밀 값은 메모리로 복사하지 않는다.
    기간이 지난 관찰은 현재 문제로 재서술하지 않는다.
    """
    end = _timestamp(at)
    if end is None:
        raise ValueError("a timezone-aware observation time is required")
    start = end - timedelta(days=WINDOW_DAYS)
    groups = defaultdict(dict)
    ignored_stale = 0

    def add(loop, action, subject, observed_at, source):
        nonlocal ignored_stale
        timestamp = _timestamp(observed_at)
        if not isinstance(loop, str) or loop not in LOOPS or timestamp is None or timestamp > end:
            return
        if timestamp < start:
            ignored_stale += 1
            return
        # 정책의 짧은 구조화 식별자만 허용한다. 원문·오류 메시지는 제외한다.
        if not isinstance(subject, str) or len(subject) > 100:
            return
        key = (loop, action, subject)
        evidence_id = (timestamp.isoformat(), source)
        groups[key][evidence_id] = {"observed_at": timestamp.isoformat(), "source": source}

    for run in (history.get("runs") or []) if isinstance(history, dict) else []:
        if not isinstance(run, dict):
            continue
        for loop in LOOPS:
            result = run.get(loop)
            if isinstance(result, dict) and result.get("status") == "error":
                add(loop, "error", "loop_execution", run.get("at"), "data/self_improve/history.json")
    for event in ledger if isinstance(ledger, list) else []:
        if not isinstance(event, dict) or event.get("action") != "rollback":
            continue
        subject = event.get("keyword") or event.get("feed") or "policy"
        if not isinstance(subject, str):
            continue
        if event.get("loop") == "topics" and isinstance(event.get("topic"), str):
            subject = event["topic"] + ":" + subject
        add(event.get("loop"), "rollback", subject, event.get("at"), "data/self_improve/ledger.json")

    patterns = []
    for (loop, action, subject), evidence in sorted(groups.items()):
        observed = sorted(evidence.values(), key=lambda e: e["observed_at"])
        if len(observed) < 2:
            continue
        identity = json.dumps([loop, action, subject], ensure_ascii=False).encode()
        patterns.append({
            "id": hashlib.sha256(identity).hexdigest()[:16],
            "loop": loop, "kind": action, "subject": subject,
            "occurrences": len(observed),
            "first_observed_at": observed[0]["observed_at"],
            "last_observed_at": observed[-1]["observed_at"],
            "evidence": observed[-5:],
            "review_proposal": "replay the recorded failure before considering another policy change",
            "requires_human_approval": True,
        })
    return {
        "schema_version": 1,
        "generated_at": at,
        "generator": "scripts/self_improve_support.py",
        "scope": "self_improve operational observations only",
        "mode": "deterministic_out_of_band_consolidation",
        "window_days": WINDOW_DAYS,
        "unique_observations": sum(len(e) for e in groups.values()),
        "ignored_stale_observations": ignored_stale,
        "recurring_patterns": patterns,
        "automatic_policy_changes": False,
        "input_sha256": hashlib.sha256(json.dumps({"history": history, "ledger": ledger},
            ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
    }
