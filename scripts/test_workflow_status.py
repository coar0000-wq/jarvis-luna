#!/usr/bin/env python3
"""Offline-only unittest fixtures for the workflow monitor. No live API calls."""
import copy
import datetime as dt
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import collect_workflow_status as monitor

NOW = dt.datetime(2026, 10, 3, 12, tzinfo=dt.timezone.utc)
CORE = "JARVIS-Core-Automation.yml"


def stamp(hours=0):
    return (NOW - dt.timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def run(run_id=10, hours=1, status="completed", conclusion="success", event="schedule", **overrides):
    value = {"id": run_id, "status": status, "conclusion": conclusion if status == "completed" else None,
             "event": event, "created_at": stamp(hours + 0.1),
             "run_started_at": stamp(hours) if status in ("completed", "in_progress") else None,
             "updated_at": stamp(hours - 0.1),
             "html_url": "https://github.com/coar0000-wq/jarvis-luna/actions/runs/" + str(run_id)}
    value.update(overrides)
    return value


def payloads(*core_runs):
    values = {name: {"total_count": 1, "workflow_runs": [run()]} for name in monitor.WORKFLOWS}
    if core_runs:
        values[CORE] = {"total_count": len(core_runs), "workflow_runs": list(core_runs)}
    return values


def report(*runs):
    return monitor.build_report(payloads(*runs), NOW)


def workflow(*runs):
    return report(*runs)["workflows"][CORE]


class WorkflowStatusTests(unittest.TestCase):
    def test_one_second_metadata_inversion_is_explicit_not_capture(self):
        started = NOW - dt.timedelta(hours=1)
        source = run(created_at=(started+dt.timedelta(seconds=1)).isoformat(),
                     run_started_at=started.isoformat())
        value, faults = monitor._run(source, NOW)
        self.assertNotIn('invalid_time_order', faults)
        self.assertEqual(value['metadata']['metadata_precision']['created_start_inversion_seconds'], 1)
        self.assertEqual(value['metadata']['created_at'], monitor._iso(started+dt.timedelta(seconds=1)))
        self.assertEqual(value['metadata']['run_started_at'], monitor._iso(started))
        source['created_at'] = (started+dt.timedelta(seconds=2)).isoformat()
        self.assertIn('invalid_time_order', monitor._run(source,NOW)[1])
        source['created_at'] = (started+dt.timedelta(microseconds=500000)).isoformat()
        self.assertIn('invalid_time_order', monitor._run(source,NOW)[1])

    def test_fresh_success_all_five(self):
        result = report()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["failed_actions"], 0)
        self.assertEqual(result["checked_workflows"], 5)
        self.assertTrue(result["coverage_complete"])
        self.assertEqual(result["observed_at"], stamp())

    def test_current_queued_is_warning_not_previous_success(self):
        item = workflow(run(20, 0.1, "queued"), run(10, 1))
        self.assertEqual(item["status"], "warning")
        self.assertEqual(item["reason"], "latest_queued")
        self.assertEqual(item["last_success"]["id"], 10)
        self.assertNotIn("finished_at", item["latest_attempt"])
        self.assertIsNone(item["queue_delay_minutes"])

    def test_current_running_with_old_success_is_warning(self):
        item = workflow(run(20, 0.1, "in_progress"), run(10, 30))
        self.assertEqual(item["reason"], "latest_in_progress")
        self.assertFalse(item["delayed"])
        self.assertGreater(item["last_success_age_hours"], 4.5)

    def test_started_now_overrides_old_schedule_delay(self):
        item = workflow(run(20, 0.1, "in_progress", event="workflow_dispatch"), run(10, 30))
        self.assertFalse(item["delayed"])
        self.assertEqual(item["status"], "warning")

    def test_old_latest_failure_still_explicit_failed(self):
        result = report(run(20, 30, conclusion="failure"), run(10, 40))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_actions"], 1)
        self.assertEqual(result["workflows"][CORE]["reason"], "latest_failure")

    def test_timed_out_latest_failed(self):
        self.assertEqual(workflow(run(conclusion="timed_out"))["status"], "failed")

    def test_cancellation_warning_not_failed(self):
        result = report(run(conclusion="cancelled"))
        self.assertEqual(result["failed_actions"], 0)
        self.assertEqual(result["workflows"][CORE]["reason"], "latest_cancelled")

    def test_actual_schedule_gap_warns_when_latest_fresh(self):
        item = workflow(run(20, 1), run(10, 8))
        self.assertEqual(item["status"], "warning")
        self.assertEqual(item["reason"], "schedule_gap_exceeds_grace")
        self.assertEqual(item["last_schedule_gap_hours"], 7)
        self.assertTrue(item["cadence_warning"])
        self.assertFalse(item["delayed"])

    def test_gap_uses_starts_not_creation_and_ignores_manual(self):
        item = workflow(run(30, 0.2, event="workflow_dispatch"),
                        run(20, 1, created_at=stamp(10)), run(10, 3, created_at=stamp(11)))
        self.assertEqual(item["last_schedule_gap_hours"], 2)
        self.assertFalse(item["cadence_warning"])
        self.assertEqual(item["queue_delay_minutes"], 6)

    def test_queued_source_started_field_is_not_actual_schedule_start(self):
        item = workflow(run(30, 0.2, "queued", run_started_at=stamp(0.2)), run(20, 1), run(10, 3))
        self.assertEqual(item["last_schedule_gap_hours"], 2)
        self.assertIsNone(item["queue_delay_minutes"])

    def test_queued_long_delay(self):
        item = workflow(run(20, 8, "queued"), run(10, 10))
        self.assertTrue(item["delayed"])
        self.assertEqual(item["reason"], "latest_queued")

    def test_stale_completed_success_is_warning(self):
        item = workflow(run(hours=8))
        self.assertEqual(item["status"], "warning")
        self.assertTrue(item["delayed"])
        self.assertEqual(item["reason"], "scheduled_attempt_delayed")

    def test_interval_and_grace_exact(self):
        for name, pair in monitor.WORKFLOWS.items():
            item = report()["workflows"][name]
            self.assertEqual((item["expected_interval_hours"], item["grace_hours"]), pair)
        self.assertFalse(workflow(run(hours=4.5))["delayed"])

    def test_timezone_normalized_without_mutating_input(self):
        values = payloads()
        values[CORE]["workflow_runs"][0].update(created_at="2026-10-03T19:54:00+09:00",
                                                run_started_at="2026-10-03T20:00:00+09:00",
                                                updated_at="2026-10-03T20:06:00+09:00")
        original = copy.deepcopy(values)
        result = monitor.build_report(values, "2026-10-03T21:00:00+09:00")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["workflows"][CORE]["last_attempt_at"], "2026-10-03T11:00:00Z")
        self.assertEqual(values, original)

    def test_future_metadata_never_becomes_success(self):
        item = workflow(run(created_at=stamp(-2), run_started_at=stamp(-1), updated_at=stamp(-0.5)))
        self.assertEqual(item["status"], "warning")
        self.assertEqual(item["reason"], "unverified_metadata")
        self.assertIsNone(item["last_success_at"])
        self.assertIsNone(item["age_hours"])

    def test_missing_start_or_finish_not_success(self):
        for overrides in ({"run_started_at": None}, {"updated_at": None}, {"created_at": None}):
            with self.subTest(overrides=overrides):
                item = workflow(run(**overrides))
                self.assertEqual(item["status"], "warning")
                self.assertIsNone(item["last_success"])

    def test_malformed_and_naive_dates_warn(self):
        for value in ("not-date", "2026-10-03T11:00:00", [], 123):
            item = workflow(run(created_at=value))
            self.assertEqual(item["status"], "warning")
            self.assertFalse(item["metadata_verified"])

    def test_malformed_types_do_not_crash(self):
        for overrides in ({"status": []}, {"conclusion": {}}, {"id": True}, {"event": []},
                          {"html_url": "https://evil.test/token?secret=abc"}):
            item = workflow(run(**overrides))
            self.assertEqual(item["status"], "warning")
        values = payloads()
        values[CORE] = {"workflow_runs": [None, []]}
        self.assertEqual(monitor.build_report(values, NOW)["status"], "warning")

    def test_no_query_data_is_unknown_not_zero_errors(self):
        for values in ({}, {name: {"workflow_runs": []} for name in monitor.WORKFLOWS},
                       {name: {"message": "Not Found"} for name in monitor.WORKFLOWS}):
            result = monitor.build_report(values, NOW)
            self.assertEqual(result["failed_actions"], "unknown")
            self.assertEqual(result["status"], "warning")
            self.assertEqual(result["checked_workflows"], 0)

    def test_partial_failure_retains_known_failure_and_unknown_coverage(self):
        values = payloads(run(conclusion="failure"))
        values["root-collectors.yml"] = {"error": "network_error"}
        result = monitor.build_report(values, NOW)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_actions"], "unknown")
        self.assertEqual(result["confirmed_failed_actions"], 1)
        self.assertEqual(result["checked_workflows"], 4)

    def test_injected_fetch_exactly_five_urls(self):
        urls = []
        def fake(url):
            urls.append(url)
            return {"workflow_runs": [run()]}
        result = monitor.collect_report("owner/repo", NOW, fake)
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(urls), 5)
        self.assertEqual(set(urls), {"https://api.github.com/repos/owner/repo/actions/workflows/" + name + "/runs?per_page=10&branch=main" for name in monitor.WORKFLOWS})

    def test_errors_sanitized_no_token_and_no_retry(self):
        for exc, expected in [(RuntimeError("SECRET_TOKEN https://evil.test"), "fetch_error"),
                              (urllib.error.URLError("SECRET_TOKEN"), "network_error"),
                              (TimeoutError("SECRET_TOKEN"), "network_error"),
                              (urllib.error.HTTPError("secret", 403, "SECRET_TOKEN", {}, None), "http_403"),
                              (json.JSONDecodeError("SECRET_TOKEN", "secret", 0), "invalid_json")]:
            calls = []
            def fake(url):
                calls.append(url)
                raise exc
            result = monitor.collect_report("owner/repo", NOW, fake)
            self.assertEqual(len(calls), 5)
            self.assertEqual(result["failed_actions"], "unknown")
            self.assertNotIn("SECRET_TOKEN", json.dumps(result))
            self.assertEqual(result["workflows"][CORE]["reason"], expected)

    def test_supplied_error_text_redacted(self):
        result = monitor.build_report({name: {"error": "SECRET_TOKEN"} for name in monitor.WORKFLOWS}, NOW)
        self.assertNotIn("SECRET_TOKEN", json.dumps(result))
        self.assertEqual(result["workflows"][CORE]["reason"], "fetch_error")

    def test_malicious_repository_rejected_without_fetch(self):
        for repo in ("../repo", "owner/../repo", "owner/repo?token=SECRET_TOKEN", "owner/repo#x",
                     "owner/repo/extra", "owner/%2e%2e", "https://github.com/o/r", "owner/..", "owner/r\n", None):
            if repo is None:
                continue
            with self.subTest(repo=repo):
                calls = []
                result = monitor.collect_report(repo, NOW, lambda url: calls.append(url))
                self.assertEqual(calls, [])
                self.assertEqual(result["status"], "warning")
                self.assertEqual(result["failed_actions"], "unknown")
                self.assertNotIn("SECRET_TOKEN", json.dumps(result))

    def test_environment_repository_and_default(self):
        for environ, repo in (({}, monitor.DEFAULT_REPOSITORY), ({"GITHUB_REPOSITORY": "test/example"}, "test/example")):
            with patch.dict(os.environ, environ, clear=True):
                result = monitor.collect_report(now=NOW, fetch_json=lambda url: {"workflow_runs": [run()]})
                self.assertEqual(result["repository"], repo)

    def test_request_get_timeout_and_auth_only_if_present(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, bound): return b'{"workflow_runs": []}'
        for token in (None, "SECRET_TOKEN"):
            env = {} if token is None else {"GITHUB_TOKEN": token}
            with patch.dict(os.environ, env, clear=True), patch.object(monitor.urllib.request, "build_opener") as opener:
                opener.return_value.open.return_value = Response()
                result = monitor.collect_report("owner/repo", NOW)
                self.assertEqual(opener.return_value.open.call_count, 5)
                for call in opener.return_value.open.call_args_list:
                    request = call.args[0]
                    self.assertEqual(request.get_method(), "GET")
                    self.assertEqual(call.kwargs["timeout"], 20)
                    self.assertEqual(request.get_header("Authorization"), "Bearer SECRET_TOKEN" if token else None)
                self.assertNotIn("SECRET_TOKEN", json.dumps(result))

    def test_snapshot_dir_reads_exact_names_no_network(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, payload in payloads().items():
                (Path(directory) / (name + ".json")).write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(monitor, "_fetch_json", side_effect=AssertionError("no network")):
                result = monitor.snapshot_report(directory, NOW)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["observation_source"], "snapshot")

    def test_snapshot_missing_invalid_never_falls_back_to_network(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / (CORE + ".json")).write_text("not-json", encoding="utf-8")
            with patch.object(monitor, "_fetch_json", side_effect=AssertionError("no network")):
                result = monitor.snapshot_report(directory, NOW)
            self.assertEqual(result["failed_actions"], "unknown")
            self.assertEqual(result["workflows"][CORE]["reason"], "snapshot_invalid")
            self.assertEqual(result["workflows"]["root-collectors.yml"]["reason"], "snapshot_missing")

    def test_cli_output_snapshot_mode_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report" / "result.json"
            with patch.object(monitor, "_fetch_json", side_effect=AssertionError("no network")), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(monitor.main(["--snapshot-dir", directory, "--output", str(output)]), 0)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "warning")
            self.assertEqual(result["failed_actions"], "unknown")

    def test_no_filesystem_or_environment_in_pure_builder(self):
        values = payloads()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "SECRET_TOKEN", "GITHUB_REPOSITORY": "evil/repo"}), patch.object(Path, "read_text", side_effect=AssertionError("IO forbidden")):
            result = monitor.build_report(values, NOW)
        self.assertEqual(result["status"], "success")
        self.assertNotIn("SECRET_TOKEN", json.dumps(result))

    def test_naive_now_is_rejected(self):
        with self.assertRaises(ValueError):
            monitor.build_report(payloads(), dt.datetime(2026, 10, 3, 12))


if __name__ == "__main__":
    unittest.main(verbosity=2)
