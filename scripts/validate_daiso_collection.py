#!/usr/bin/env python3
"""Validate current-run collection evidence without refreshing timestamps."""
from __future__ import annotations
import argparse
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def timestamp(value):
    if not isinstance(value, str) or not value:
        raise ValueError("missing timestamp")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone required")
    return dt.astimezone(timezone.utc)


def count(run, key):
    value = run.get(key)
    if type(value) is not int or value < 0:
        raise ValueError("invalid/missing count: " + key)
    return value


def valid_success(run):
    try:
        return (isinstance(run, dict) and run.get("status") == "ok"
                and count(run, "ok") > 0
                and count(run, "requested") >= count(run, "ok")
                and count(run, "parse_failed") == 0
                and count(run, "http_error") == 0
                and timestamp(run.get("started_at")) <= timestamp(run.get("finished_at"))
                <= datetime.now(timezone.utc)
                and run.get("collector_completed", True) is True)
    except (TypeError, ValueError):
        return False


def record_attempt(document, attempt):
    """Preserve real success before overwriting legacy last_run."""
    doc = copy.deepcopy(document) if isinstance(document, dict) else {}
    if not valid_success(doc.get("last_success")):
        legacy = doc.get("last_run")
        if valid_success(legacy):
            doc["last_success"] = copy.deepcopy(legacy)
        else:
            doc.pop("last_success", None)
    doc["last_run"] = copy.deepcopy(attempt)
    doc["last_attempt"] = copy.deepcopy(attempt)
    if valid_success(attempt):
        doc["last_success"] = copy.deepcopy(attempt)
    return doc


def validate(document, *, outcome, execution_id, started_after, now=None, max_age_hours=6):
    now = now or datetime.now(timezone.utc)
    try:
        if outcome != "success":
            raise ValueError("collector step did not complete successfully: " + str(outcome))
        if not isinstance(document, dict):
            raise ValueError("collection status must be an object")
        run = document.get("last_run")
        if not isinstance(run, dict) or document.get("last_attempt") != run:
            raise ValueError("missing/mismatched latest attempt")
        if not execution_id or run.get("execution_id") != execution_id:
            raise ValueError("execution_id mismatch: stale file is not current evidence")
        if run.get("collector_completed") is not True or run.get("collector_version") != 2:
            raise ValueError("collector completion not explicitly recorded")
        started = timestamp(run.get("started_at"))
        finished = timestamp(run.get("finished_at"))
        boundary = timestamp(started_after)
        if not boundary <= started <= finished <= now:
            raise ValueError("stale, reversed or future timestamps")
        if (now - finished).total_seconds() > max_age_hours * 3600:
            raise ValueError("expired collection record")
        requested, ok, parsed, http = (count(run, key) for key in ("requested", "ok", "parse_failed", "http_error"))
        if ok > requested:
            raise ValueError("ok exceeds requested")
        if parsed or http:
            raise ValueError("parse/network failure: parse_failed=%s http_error=%s" % (parsed, http))
        status = run.get("status")
        if status == "ok" and ok > 0:
            if document.get("last_success") != run:
                raise ValueError("last_success does not match valid collection")
            mode = "collected"
        elif status == "no_change" and ok == 0:
            mode = "no_change"
        else:
            raise ValueError("failed/unknown/inconsistent collector status: " + str(status))
        return {"mode": mode, "collection_valid": "true", "publish_products": str(mode == "collected").lower(), "errors": []}
    except (ValueError, TypeError, OverflowError) as exc:
        return {"mode": "failed", "collection_valid": "false", "publish_products": "false", "errors": [str(exc)]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", default="data/daiso_real/collection_status.json")
    parser.add_argument("--collector-outcome", required=True)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--started-after", required=True)
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = parser.parse_args(argv)
    try:
        doc = json.loads(Path(args.status).read_text(encoding="utf-8"))
        result = validate(doc, outcome=args.collector_outcome, execution_id=args.execution_id, started_after=args.started_after)
    except (OSError, ValueError) as exc:
        result = {"mode": "failed", "collection_valid": "false", "publish_products": "false", "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as output:
            for key in ("mode", "collection_valid", "publish_products"):
                output.write(key + "=" + result[key] + "\n")
    for error in result["errors"]:
        print("::error::" + error.replace("\n", " "))
    if result["mode"] == "no_change":
        print("::warning::Collector completed normally without new products; last_success is unchanged.")
    return int(result["mode"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
