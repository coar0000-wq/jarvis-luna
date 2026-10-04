#!/usr/bin/env python3
"""One private observed/cached advisory batch. No canonical decisions are changed.

Only allowlisted counts/status/freshness and evidence-presence summaries leave
this process. No notes, URLs, addresses, paths or scraped bodies are included.
The complete relevant allowlisted inputs and question schema determine the cache.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from .build_team_learning import TEAMS
except ImportError:
    from build_team_learning import TEAMS

ROOT = Path(__file__).resolve().parents[1]
ROLES = (*TEAMS, "secretary")
QUESTION_VERSION = "jarvis-teams-v1"
MODEL_POLICY_VERSION = "jarvis-jev-alias-v1"
MODEL = "jev-latest"
PRICE = .042 / 1_000_000
STATUSES = {"success", "warning", "error", "blocked", "empty", "pending", "ready",
            "ok", "failed", "stale", "unknown", "active", "review", "학습 중",
            "영상 없음", "영상 수집됨 · 자막 검토 대기", "정체", "진행", "대기", "완료"}
KINDS = {"auto_remediable", "revalidate_only", "external_wait", "approval_required",
         "human_review", "human_required", "source_check", "none"}
FRESH_COUNTS = ("success_age_hours", "attempt_age_hours", "candidate_success_age_hours",
                "age_hours", "candidates_new", "candidates_updated")
FRESH_FLAGS = ("data_stale", "attempt_stale", "is_failure", "delayed", "is_no_change",
               "is_candidate_collection")
SOURCE_DATES = ("last_success_at", "last_attempt_at", "last_candidate_success_at",
                "captured_at", "last_capture_at", "last_genuine_capture_at")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def load(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def date(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
    except ValueError:
        return None


def category(value, allowed):
    return value if isinstance(value, str) and value in allowed else "unknown"


def mapping(value):
    return value if isinstance(value, dict) else {}


def rows(value):
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []


def team_rows(doc):
    value = doc.get("teams")
    if isinstance(value, dict):
        return {k: mapping(v) for k, v in value.items() if k in ROLES}
    return {r.get("id"): r for r in rows(value) if r.get("id") in ROLES}


def freshness(raw):
    raw = mapping(raw)
    out = {}
    if raw:
        out["status"] = category(raw.get("status"), STATUSES)
    for key in FRESH_COUNTS:
        if number(raw.get(key)):
            out[key] = raw[key]
    for key in FRESH_FLAGS:
        if isinstance(raw.get(key), bool):
            out[key] = raw[key]
    for key in SOURCE_DATES:
        value = date(raw.get(key))
        if value:
            # The shared adapter removes captured_at, so preserve source meaning.
            out["source_capture_at" if key == "captured_at" else key] = value
    return out


def learning(raw):
    raw = mapping(raw)
    if not raw:
        return {}
    out = {"status": category(raw.get("status"), STATUSES)}
    for key in ("insights", "videos_available"):
        if number(raw.get(key)):
            out[key] = raw[key]
    out["pending_count"] = len(rows(raw.get("review_pending")))
    if date(raw.get("last_review")):
        out["last_review"] = raw["last_review"]
    items = rows(raw.get("items"))
    confidence = Counter(category(r.get("confidence"), {"high", "medium", "low"}) for r in items)
    evidence = [mapping(r.get("evidence")) for r in items]
    # Presence is reported cached evidence, never independent verification.
    out["evidence"] = {"items": len(items), "confidence": dict(sorted(confidence.items())),
                       "with_locator": sum(bool(e.get("url")) and bool(e.get("timestamp")) for e in evidence),
                       "with_summary": sum(bool(e.get("summary")) for e in evidence)}
    return out


def improvement(raw):
    raw = mapping(raw)
    if not raw:
        return {}
    out = {"status": category(raw.get("status"), STATUSES),
           "state": category(raw.get("state"), STATUSES),
           "blocker_kind": category(raw.get("open_kind"), KINDS),
           "has_open_action": bool(raw.get("open_action"))}
    if number(raw.get("streak")):
        out["streak"] = raw["streak"]
    if isinstance(raw.get("stale"), bool):
        out["stale"] = raw["stale"]
    if date(raw.get("since")):
        out["since"] = raw["since"]
    return out


def audit(raw):
    if not raw:
        return {}
    out = {}
    for key in ("products_total", "live_channels", "total_channels"):
        if number(raw.get(key)):
            out[key] = raw[key]
    if isinstance(raw.get("severity"), bool):
        out["severity"] = raw["severity"]
    for key in ("empty_or_failed", "stale_or_manual", "failure_types"):
        if isinstance(raw.get(key), list):
            out[key + "_count"] = len(raw[key])
    last = mapping(raw.get("last_run"))
    for key in ("requested", "ok", "parse_failed"):
        if number(last.get(key)):
            out[key] = last[key]
    if date(last.get("finished_at")):
        out["last_run_finished_at"] = last["finished_at"]
    return out


def build_payload(root=ROOT):
    data = Path(root) / "data"
    dashboard = load(data / "dashboard_runtime.json")
    cards = team_rows(dashboard)
    cards["secretary"] = mapping(dashboard.get("secretary"))
    learned = team_rows(load(data / "team_learning.json"))
    improved = team_rows(load(data / "team_improvement.json"))
    audits = {k: audit(load(data / "agents" / (k + ".json")))
              for k in ("collector_audit", "signal_audit")}
    teams = {}
    material = {}
    for role in ROLES:
        card = cards.get(role, {})
        info = {"card_present": bool(card), "status": category(card.get("status"), STATUSES),
                "action_kind": category(card.get("action_kind"), KINDS),
                "waiting_kind": category(card.get("waiting_kind"), KINDS),
                "has_action": bool(card.get("action")), "has_waiting": bool(card.get("waiting"))}
        for key in ("collection_freshness", "heartbeat"):
            compact = freshness(card.get(key))
            if compact:
                info[key] = compact
        info["learning"] = learning(learned.get(role) or card.get("youtube_learning"))
        info["improvement"] = improvement(improved.get(role))
        if role == "secretary":
            steps = rows(card.get("steps"))
            info["steps"] = {"count": len(steps), "dated": sum(bool(date(r.get("갱신"))) for r in steps),
                             "source_dates": sorted(date(r.get("갱신")) for r in steps if date(r.get("갱신"))),
                             "source_ages_hours": sorted(r["몇시간전"] for r in steps if number(r.get("몇시간전")))}
        teams[role] = info
        # Keep complete decision-material text local, represented only by a digest.
        # Explicit field selection excludes personal notes, credential fields and
        # generation clocks. A changed evidence locator/text invalidates the cache
        # even when the transmitted bounded presence/count summary is unchanged.
        raw_learning = mapping(learned.get(role) or card.get("youtube_learning"))
        raw_improvement = mapping(improved.get(role))
        material[role] = {
            "safe_summary": info,
            "card_material": {k: card.get(k) for k in ("status", "action_kind", "waiting_kind", "summary", "action", "waiting")},
            "learning_material": [{"confidence": r.get("confidence"),
                                   "evidence": {k: mapping(r.get("evidence")).get(k)
                                                for k in ("url", "timestamp", "summary")}}
                                  for r in rows(raw_learning.get("items"))],
            "improvement_material": {k: raw_improvement.get(k) for k in ("state", "status", "open_kind", "open_action")},
        }
    questions = {}
    for role in ROLES:
        questions[role + "_quality"] = {"type": "score", "instructions": "Rate " + role + " evidence.",
                                         "criteria": ["insufficient", "review", "usable", "strong"]}
        questions[role + "_next_action"] = {"type": "choice", "instructions": "Route " + role + ".",
                                             "criteria": {"local": "Sufficient", "source_check": "Missing/stale", "human_review": "Blocked/uncertain"}}
    state = {"scope": "observed_cached_not_independently_verified", "approval": False,
             "rule": "Missing/unknown evidence=review, not approval. All roles advisory only.",
             "teams": teams, "audits": audits}
    # Never serialize material to output or send it: only its one-way digest.
    state["material_inputs_sha256"] = digest({"teams": material, "audits": audits})
    payload = {"state": state, "model": MODEL, "question_version": QUESTION_VERSION,
               "model_policy_version": MODEL_POLICY_VERSION, "questions": questions}
    size = canonical(payload)
    if len(size) > 12000 or len(size.encode("utf-8")) >= 15000:
        # Preserve complete input digest while explicitly bounding the summary.
        state["summary_bounded"] = True
        for info in teams.values():
            for key in ("collection_freshness", "heartbeat"):
                if key in info:
                    info[key] = {k: v for k, v in info[key].items() if k in
                                 {"status", "data_stale", "is_failure", "success_age_hours", "last_success_at", "source_capture_at"}}
            if "steps" in info:
                info["steps"] = {k: v for k, v in info["steps"].items() if k in {"count", "dated"}}
        size = canonical(payload)
    if len(size) > 12000 or len(size.encode("utf-8")) >= 15000:
        raise ValueError("team_batch_input_limit_exceeded")
    return payload


def fallback(payload):
    answers = {}
    for role, info in payload["state"]["teams"].items():
        fresh = info.get("collection_freshness", {})
        heartbeat = info.get("heartbeat", {})
        imp = info.get("improvement", {})
        evidence = info.get("learning", {}).get("evidence", {})
        blocked = (info["has_waiting"] or info["waiting_kind"] in {"approval_required", "human_review", "human_required", "external_wait"}
                   or info["status"] in {"error", "blocked", "failed"}
                   or imp.get("blocker_kind") in {"approval_required", "human_review", "human_required", "external_wait"})
        stale = bool(fresh.get("data_stale") or fresh.get("is_failure") or heartbeat.get("delayed") or imp.get("stale"))
        known = (info["card_present"] and info["status"] in {"success", "ok", "ready", "active"}
                 and fresh.get("status") == "success" and "last_success_at" in fresh
                 and fresh.get("data_stale") is False and evidence.get("with_locator", 0) > 0
                 and evidence.get("with_summary", 0) > 0 and not stale and not blocked)
        score, action = (2, "local") if known else (1, "human_review" if blocked else "source_check")
        answers[role + "_quality"] = {"score": score, "confidence": 0.0}
        answers[role + "_next_action"] = {"choice": action, "confidence": 0.0}
    return answers


def estimate(payload):
    wire = {k: v for k, v in payload.items() if k not in {"question_version", "model_policy_version"}}
    reserved = len(canonical(wire).encode("utf-8")) + 2048
    return {"dry_run": True, "calls_reserved": 1, "teams": len(ROLES), "questions": len(payload["questions"]),
            "input_chars": len(canonical(payload)), "input_bytes": len(canonical(payload).encode("utf-8")),
            "reserved_input_tokens": reserved, "estimated_cost_usd": reserved * PRICE,
            "context_schema_sha256": digest(payload), "network_called": False, "output_mutated": False}


def evaluate(payload, adapter=None):
    if adapter is None:
        try:
            from .typesafe_decision_support import evaluate_typed
        except ImportError:
            from typesafe_decision_support import evaluate_typed
        adapter = evaluate_typed
    local = fallback(payload)
    try:
        result = adapter(payload, fallback_answers=local)
    except Exception:
        result = {"source": "deterministic_local", "mode": "adapter_exception", "answers": local}
    if not isinstance(result, dict):
        result = {"source": "deterministic_local", "mode": "invalid_adapter_result", "answers": local}
    source = result.get("source")
    answers = result.get("answers")
    remote = source in {"typesafe", "typesafe_cache"}
    try:
        try:
            from .typesafe_shared import validate_answers
        except ImportError:
            from typesafe_shared import validate_answers
        validate_answers(answers, payload["questions"])
    except Exception:
        answers, remote = local, False
    if not remote:
        source, answers = "deterministic_local", local
    mode = result.get("mode", "local_advisory")
    if not remote and isinstance(mode, str) and ("typesafe_advisory" in mode or "typesafe_cached" in mode):
        mode = "invalid_remote_result_local_advisory"
    teams = {role: {"quality": answers[role + "_quality"], "next_action": answers[role + "_next_action"],
                    "source": source, "mode": mode, "approval": False, "enforced": False} for role in ROLES}
    return {"schema_version": 1, "visibility": "private", "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": source, "mode": mode, "enforced": False, "approval": False,
            "question_version": QUESTION_VERSION, "model_policy_version": MODEL_POLICY_VERSION,
            "requested_model": MODEL, "model": result.get("model") if remote else None,
            "context_schema_sha256": digest(payload), "material_inputs_sha256": payload["state"]["material_inputs_sha256"],
            "scope": payload["state"]["scope"], "teams": teams, "answers": answers,
            "usage": result.get("usage") if remote else None, "paid_api_called": bool(remote and source == "typesafe")}


def write_private(output, value):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=output.name + ".", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        os.chmod(temp, 0o600)
        os.replace(temp, output)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main(argv=None, *, root=ROOT, adapter=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    payload = build_payload(root)
    if args.dry_run:
        print(canonical(estimate(payload)))
        return 0
    output = args.output or Path(root) / "data" / "typesafe_team_advisory.json"
    data_root = (Path(root) / "data").resolve()
    if output.resolve().is_relative_to(data_root) and output.resolve() != data_root / "typesafe_team_advisory.json":
        parser.error("--output must not overwrite canonical data; use a temporary output outside data")
    result = evaluate(payload, adapter)
    write_private(output, result)
    print(canonical({"source": result["source"], "mode": result["mode"], "teams": len(result["teams"]), "enforced": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
