#!/usr/bin/env python3
"""Fast-forward a queued producer checkout to the latest main when only data moved.

2026-10-18: producers share the main-publish queue. A run created while another producer was
publishing starts from the older commit (its event SHA). Core publishes operations records in its
own transaction, so a queued run either forked the operations ledger (report_lost_or_byte_conflict,
Deep 39031572551) or, with the stale-checkout guard, had to skip all work (Core 39086876086 queued
behind the hour-long Daiso collection). When every commit between the event SHA and main's tip is
data-only, the run is moved to that tip before any restore, so it works on the published state.
Any producer/policy code change (scripts/, config/, .github/, requirements/, root *.py ...) leaves
the checkout untouched: such a run must be re-run on the new code and the guards still block it.
The event SHA stays the run's lineage identity (artifacts, checkpoints); only HEAD advances.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=120)


def producer_changed(name: str, policy: dict) -> bool:
    from publish_transaction import producer_changed as changed  # noqa: PLC0415  same rule as publication
    return changed(name, policy)


def plan(event_sha: str, tip: str, changed: list[str], policy: dict) -> str:
    if tip == event_sha:
        return "fresh"
    if any(producer_changed(n, policy) for n in changed):
        return "producer_code_changed"
    return "fast_forward"


def main() -> int:
    event_sha = os.environ.get("GITHUB_SHA", "")
    head = git("rev-parse", "HEAD").stdout.strip()
    if not re.fullmatch("[0-9a-f]{40}", event_sha) or head != event_sha:
        print("FAST_FORWARD_SKIPPED checkout_not_event_sha")
        return 0
    if git("status", "--porcelain").stdout.strip():
        print("FAST_FORWARD_SKIPPED dirty_worktree")
        return 0
    if git("fetch", "--quiet", "--no-tags", "origin", "main").returncode:
        print("FAST_FORWARD_SKIPPED fetch_failed")
        return 0
    tip = git("rev-parse", "FETCH_HEAD").stdout.strip()
    if not re.fullmatch("[0-9a-f]{40}", tip) or git("merge-base", "--is-ancestor", event_sha, tip).returncode:
        print("FAST_FORWARD_SKIPPED tip_not_descendant")
        return 0
    policy = json.loads((ROOT / "config" / "publish_policy.json").read_text(encoding="utf-8"))
    changed = git("diff", "--name-only", event_sha, tip).stdout.split()
    decision = plan(event_sha, tip, changed, policy)
    if decision == "fast_forward":
        if git("checkout", "--quiet", "--detach", tip).returncode:
            print("FAST_FORWARD_SKIPPED checkout_failed")
            return 0
        print(f"FAST_FORWARD_OK {event_sha[:12]} -> {tip[:12]} data-only files={len(changed)}")
    else:
        print(f"FAST_FORWARD_{decision.upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
