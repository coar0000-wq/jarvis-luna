#!/usr/bin/env python3
"""Bounded, read-only GitHub Actions metadata monitor (Python stdlib only).

build_report accepts {workflow_filename: raw REST payload}, or an error envelope
{"error": "network_error"}. It never consults files, environment, or network.
collect_report performs at most one GET per monitored workflow, with no retries.
An injected fetch_json takes one URL and returns the decoded REST payload.

Times are validated source times, never filesystem mtimes. ``finished_at`` is
GitHub's ``updated_at`` on completed runs, not a promised exact execution end.
``age_hours`` measures latest attempt start/creation age; success age is separate.
``last_schedule_gap_hours`` uses actual run_started_at of distinct scheduled runs.
These are observation thresholds, not GitHub scheduling SLA guarantees.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

UTC = dt.timezone.utc
WORKFLOWS = {
    "JARVIS-Core-Automation.yml": (2, 4.5),
    "JARVIS-Deep-Analysis.yml": (2, 4.5),
    "jarvis-real-knowledge.yml": (6, 9),
    "daiso-real-collection.yml": (24, 36),
    "root-collectors.yml": (24, 36),
}
DEFAULT_REPOSITORY = "coar0000-wq/jarvis-luna"
REPOSITORY_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}\Z")
STATUSES = {"queued", "in_progress", "completed", "waiting", "pending", "requested"}
FAILURES = {"failure", "timed_out", "startup_failure", "action_required"}
CONCLUSIONS = FAILURES | {"success", "cancelled", "canceled", "neutral", "skipped", "stale"}
SAFE_ERRORS = {"network_error", "fetch_error", "invalid_json", "invalid_repository",
               "snapshot_missing", "snapshot_invalid", "response_too_large"}


def _iso(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _date(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _now(value):
    if value is None:
        return dt.datetime.now(UTC)
    parsed = _date(value) if isinstance(value, str) else value
    if not isinstance(parsed, dt.datetime) or parsed.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime or ISO timestamp")
    return parsed.astimezone(UTC)


def _error_code(value):
    if isinstance(value, str) and (value in SAFE_ERRORS or re.fullmatch(r"http_[1-5][0-9]{2}", value)):
        return value
    return "fetch_error"


def _run(raw, observed):
    """Whitelist source metadata, normalize dates, and report validation faults."""
    faults = []
    if not isinstance(raw, dict):
        return None, ["malformed_run"]
    run_id = raw.get("id")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        faults.append("invalid_id")
        run_id = None
    status = raw.get("status")
    if not isinstance(status, str) or status not in STATUSES:
        status = None
        faults.append("invalid_status")
    conclusion = raw.get("conclusion")
    if conclusion is not None and (not isinstance(conclusion, str) or conclusion not in CONCLUSIONS):
        conclusion = None
        faults.append("invalid_conclusion")
    if status == "completed" and conclusion is None:
        faults.append("missing_conclusion")
    if status != "completed" and conclusion is not None:
        faults.append("inconsistent_conclusion")
        conclusion = None
    event = raw.get("event")
    if not isinstance(event, str) or not re.fullmatch(r"[a-z_]{1,64}", event):
        event = None
        faults.append("invalid_event")
    dates = {}
    for key in ("created_at", "run_started_at", "updated_at"):
        source = raw.get(key)
        parsed = _date(source)
        if source is not None and parsed is None:
            faults.append("malformed_" + key)
        if parsed is not None and parsed > observed:
            faults.append("future_" + key)
            parsed = None
        dates[key] = parsed
    if dates["created_at"] is None:
        faults.append("missing_created_at")
    if status in {"in_progress", "completed"} and dates["run_started_at"] is None:
        faults.append("missing_run_started_at")
    if status == "completed" and dates["updated_at"] is None:
        faults.append("missing_finished_at")
    created, started, finished = (dates[k] for k in ("created_at", "run_started_at", "updated_at"))
    metadata_precision = None
    if created and started and started < created:
        inversion = (created - started).total_seconds()
        # Record/dispatch metadata have independent whole-second clocks. Preserve
        # their exact values; a bounded one-second inversion is not a capture.
        if created.microsecond == started.microsecond == 0 and inversion <= 1:
            metadata_precision = {'created_start_inversion_seconds': inversion,
                                  'capture_clocks': 'not_metadata'}
        else:
            faults.append("invalid_time_order")
    if status == "completed" and started and finished and finished < started:
        faults.append("invalid_time_order")
    url = raw.get("html_url")
    if not isinstance(url, str) or not re.fullmatch(
            r"https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+/actions/runs/[0-9]+(?:/attempts/[0-9]+)?", url):
        url = None
        faults.append("invalid_html_url")
    metadata = {"id": run_id, "status": status, "conclusion": conclusion, "event": event,
                "created_at": _iso(created) if created else None,
                "run_started_at": _iso(started) if started else None, "html_url": url}
    if metadata_precision is not None:
        metadata['metadata_precision'] = metadata_precision
    if status == "completed":
        metadata["finished_at"] = _iso(finished) if finished else None
    if isinstance(raw.get("run_attempt"), int) and not isinstance(raw["run_attempt"], bool) and raw["run_attempt"] > 0:
        metadata["run_attempt"] = raw["run_attempt"]
    return {"metadata": metadata, "created": created,
            "started": started if status in {"in_progress", "completed"} else None,
            "finished": finished if status == "completed" else None, "faults": faults}, faults


def _hours(observed, timestamp):
    return round((observed - timestamp).total_seconds() / 3600, 4) if timestamp else None


def _workflow(payload, interval, grace, observed):
    result = {"status": "warning", "reason": "unavailable", "expected_interval_hours": interval,
              "grace_hours": grace, "latest_attempt": None, "last_success": None,
              "last_attempt_at": None, "last_success_at": None, "age_hours": None,
              "last_success_age_hours": None, "last_schedule_gap_hours": None,
              "cadence_warning": None, "delayed": None, "queue_delay_minutes": None,
              "metadata_verified": False, "validation_warnings": []}
    if payload is None:
        result["reason"] = "missing_response"
        return result
    if isinstance(payload, dict) and "error" in payload:
        result["reason"] = _error_code(payload["error"])
        return result
    raw_runs = payload.get("workflow_runs") if isinstance(payload, dict) else payload
    if not isinstance(raw_runs, list):
        result["reason"] = "malformed_response"
        return result
    if not raw_runs:
        result["reason"] = "no_runs"
        return result
    runs, faults = [], []
    for raw in raw_runs:
        run, issues = _run(raw, observed)
        faults.extend(issues)
        if run:
            runs.append(run)
    result["validation_warnings"] = sorted(set(faults))
    if not runs:
        result["reason"] = "malformed_runs"
        return result
    # REST normally orders by creation. Actual rerun start can be newer than creation.
    earliest = dt.datetime.min.replace(tzinfo=UTC)
    runs.sort(key=lambda r: (max(r["created"] or earliest, r["started"] or earliest),
                             r["metadata"]["id"] or 0), reverse=True)
    latest = runs[0]
    metadata = latest["metadata"]
    result["latest_attempt"] = metadata
    anchor = latest["started"] or latest["created"]
    result["last_attempt_at"] = _iso(anchor) if anchor else None
    result["age_hours"] = _hours(observed, anchor)
    # Any unorderable entry could be the newest: do not claim checked coverage.
    orderable = all(r["created"] is not None for r in runs) and len(runs) == len(raw_runs)
    result["metadata_verified"] = not latest["faults"] and orderable
    successes = [r for r in runs if not r["faults"] and r["metadata"]["status"] == "completed"
                 and r["metadata"]["conclusion"] == "success"]
    if successes:
        success = max(successes, key=lambda r: r["finished"])
        result["last_success"] = success["metadata"]
        result["last_success_at"] = _iso(success["finished"])
        result["last_success_age_hours"] = _hours(observed, success["finished"])
    schedules = [r for r in runs if r["metadata"]["event"] == "schedule" and not r["faults"]]
    started_schedules = sorted((r for r in schedules if r["started"]), key=lambda r: r["started"], reverse=True)
    # Avoid duplicated records being mistaken for two actual scheduled executions.
    unique_starts, seen = [], set()
    for run in started_schedules:
        if run["metadata"]["id"] not in seen:
            unique_starts.append(run["started"])
            seen.add(run["metadata"]["id"])
    if len(unique_starts) >= 2:
        gap = (unique_starts[0] - unique_starts[1]).total_seconds() / 3600
        result["last_schedule_gap_hours"] = round(gap, 4)
        result["cadence_warning"] = gap > grace
    schedule_anchor = None
    if schedules:
        scheduled = max(schedules, key=lambda r: max(r["created"] or earliest, r["started"] or earliest))
        schedule_anchor = scheduled["started"] or scheduled["created"]
    freshness_anchor = schedule_anchor or anchor
    if metadata["status"] == "in_progress" and latest["started"]:
        freshness_anchor = max(freshness_anchor or earliest, latest["started"])
    if freshness_anchor:
        result["delayed"] = (observed - freshness_anchor).total_seconds() > grace * 3600
    if latest["started"] and latest["created"] and latest["started"] >= latest["created"]:
        result["queue_delay_minutes"] = round((latest["started"] - latest["created"]).total_seconds() / 60, 4)
    # Only verified latest metadata can establish an Action failure or success.
    if not result["metadata_verified"]:
        result["reason"] = "unverified_metadata"
    elif metadata["status"] == "completed" and metadata["conclusion"] in FAILURES:
        result["status"], result["reason"] = "failed", "latest_" + metadata["conclusion"]
    elif metadata["status"] != "completed":
        result["reason"] = "latest_" + metadata["status"]
    elif metadata["conclusion"] != "success":
        result["reason"] = "latest_" + metadata["conclusion"]
    elif faults:
        result["reason"] = "partial_unverified_metadata"
    elif result["delayed"]:
        result["reason"] = "scheduled_attempt_delayed"
    elif result["cadence_warning"]:
        result["reason"] = "schedule_gap_exceeds_grace"
    elif result["last_success_age_hours"] is None:
        result["reason"] = "no_verified_success"
    elif result["last_success_age_hours"] > grace:
        result["reason"] = "last_success_stale"
    else:
        result["status"], result["reason"] = "success", "latest_success_fresh"
    return result


def build_report(runs_by_filename, now=None):
    """Pure evaluation of supplied metadata; no API, environment or filesystem IO."""
    observed = _now(now)
    mapping = runs_by_filename if isinstance(runs_by_filename, dict) else {}
    workflows = {name: _workflow(mapping.get(name), interval, grace, observed)
                 for name, (interval, grace) in WORKFLOWS.items()}
    checked = sum(item["metadata_verified"] for item in workflows.values())
    failures = sum(item["status"] == "failed" for item in workflows.values())
    overall = "failed" if failures else ("warning" if any(item["status"] != "success" for item in workflows.values()) else "success")
    return {"schema_version": 1, "generated_at": _iso(observed), "observed_at": _iso(observed),
            "status": overall, "failed_actions": failures if checked == len(WORKFLOWS) else "unknown",
            "confirmed_failed_actions": failures, "checked_workflows": checked,
            "total_workflows": len(WORKFLOWS), "coverage_complete": checked == len(WORKFLOWS),
            "observation_source": "provided_metadata", "workflows": workflows}


def _fetch_json(url):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "jarvis-workflow-metadata-monitor"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers=headers, method="GET")
    # GitHub API redirects are not needed; reject them to avoid forwarding auth.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, hdrs, newurl):
            return None
    with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
        body = response.read(2 * 1024 * 1024 + 1)
        if len(body) > 2 * 1024 * 1024:
            return {"error": "response_too_large"}
        return json.loads(body)


def collect_report(repository=None, now=None, fetch_json=None):
    """At most five GETs, one per filename; no retries or paid/model API calls."""
    repo = repository if repository is not None else os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY)
    if not isinstance(repo, str) or not REPOSITORY_RE.fullmatch(repo) or repo.split("/")[-1] in {".", ".."}:
        return build_report({name: {"error": "invalid_repository"} for name in WORKFLOWS}, now)
    fetcher = fetch_json if fetch_json is not None else _fetch_json
    payloads = {}
    for name in WORKFLOWS:
        url = "https://api.github.com/repos/" + repo + "/actions/workflows/" + name + "/runs?per_page=10&branch=main"
        try:
            payloads[name] = fetcher(url)
        except urllib.error.HTTPError as error:
            payloads[name] = {"error": "http_" + str(error.code)}
        except (json.JSONDecodeError, UnicodeDecodeError):
            payloads[name] = {"error": "invalid_json"}
        except (urllib.error.URLError, TimeoutError, OSError):
            payloads[name] = {"error": "network_error"}
        except Exception:
            # Never propagate exception text: it can contain credentials or URLs.
            payloads[name] = {"error": "fetch_error"}
    report = build_report(payloads, now)
    report["repository"] = repo
    report["observation_source"] = "github_rest"
    return report


def snapshot_report(directory, now=None):
    """Read parent-captured responses only; no fallback network requests."""
    payloads = {}
    for name in WORKFLOWS:
        try:
            payloads[name] = json.loads((Path(directory) / (name + ".json")).read_text(encoding="utf-8"))
        except FileNotFoundError:
            payloads[name] = {"error": "snapshot_missing"}
        except (OSError, ValueError, UnicodeError):
            payloads[name] = {"error": "snapshot_invalid"}
    report = build_report(payloads, now)
    report["observation_source"] = "snapshot"
    return report


def collect_pipeline_evidence(root, report, *, fetch_json=None, fetch_artifact_bytes=None, now=None):
    """Four bounded metadata GETs plus one artifact; no retry or false recovery.

    Injected transports are fixture hooks, never file-declared authority.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.observe_daiso_pipeline import observe
    return observe(root, report=report, now=now, fetch_json=fetch_json,
                   fetch_artifact_bytes=fetch_artifact_bytes)


def daiso_pipeline_snapshot(root, now=None):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.daiso_pipeline_inputs import load_pipeline_inputs
    return load_pipeline_inputs(root, now=now)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=None)
    parser.add_argument("--snapshot-dir", type=Path, help="Offline: DIR/<workflow filename>.json")
    parser.add_argument("--output", type=Path, default=Path("data/agents/workflow_freshness.json"))
    args = parser.parse_args(argv)
    report = snapshot_report(args.snapshot_dir) if args.snapshot_dir is not None else collect_report(args.repository)
    if args.output.absolute() == Path("data/agents/workflow_freshness.json").absolute():
        # Also supports direct script execution without changing collection IO.
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from scripts.workflow_status_history import publish_workflow_report
        publish_workflow_report(Path.cwd(), report)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.snapshot_dir is None:
        collect_pipeline_evidence(Path.cwd(), report)
    print("Workflow metadata: " + report["status"] + "; checked " + str(report["checked_workflows"]) + "/" + str(report["total_workflows"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
