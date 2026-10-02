#!/usr/bin/env python3
"""Offline fixtures for Daiso attempt/success and fail-closed validation."""
import copy
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from validate_daiso_collection import main, record_attempt, validate

NOW = datetime.now(timezone.utc)
START = (NOW - timedelta(minutes=10)).isoformat()
FINISH = (NOW - timedelta(minutes=1)).isoformat()
BOUNDARY = (NOW - timedelta(minutes=11)).isoformat()


def attempt(status="no_change", ok=0):
    return dict(status=status, requested=10, ok=ok, parse_failed=0, http_error=0,
                started_at=START, finished_at=FINISH, collector_completed=True,
                execution_id="fixture:1:collect", collector_version=2)


class ValidationTests(unittest.TestCase):
    def check(self, run=None, **kwargs):
        doc = record_attempt({}, run or attempt())
        return validate(doc, outcome=kwargs.get("outcome", "success"),
                        execution_id=kwargs.get("execution_id", "fixture:1:collect"),
                        started_after=kwargs.get("started_after", BOUNDARY), now=NOW)

    def test_no_change(self):
        self.assertEqual(self.check()["mode"], "no_change")
        self.assertEqual(self.check()["publish_products"], "false")

    def test_collected(self):
        self.assertEqual(self.check(attempt("ok", 1))["mode"], "collected")

    def test_empty_queue_no_change(self):
        r = attempt(); r["requested"] = 0
        self.assertEqual(self.check(r)["mode"], "no_change")

    def test_failed_outcome(self):
        self.assertEqual(self.check(outcome="failure")["mode"], "failed")

    def test_cancelled_outcome(self):
        self.assertEqual(self.check(outcome="cancelled")["mode"], "failed")

    def test_stale_identity(self):
        self.assertEqual(self.check(execution_id="another:run")["mode"], "failed")

    def test_stale_boundary(self):
        self.assertEqual(self.check(started_after=FINISH)["mode"], "failed")

    def test_future_finish(self):
        r = attempt(); r["finished_at"] = (NOW + timedelta(seconds=1)).isoformat()
        self.assertEqual(self.check(r)["mode"], "failed")

    def test_expired(self):
        r = attempt(); r.update(started_at=(NOW-timedelta(hours=9)).isoformat(), finished_at=(NOW-timedelta(hours=8)).isoformat())
        self.assertEqual(self.check(r, started_after=r["started_at"])["mode"], "failed")

    def test_reversed_times(self):
        r = attempt(); r["started_at"] = FINISH; r["finished_at"] = START
        self.assertEqual(self.check(r)["mode"], "failed")

    def test_malformed_timestamp(self):
        r = attempt(); r["finished_at"] = "broken"
        self.assertEqual(self.check(r)["mode"], "failed")

    def test_naive_timestamp(self):
        r = attempt(); r["finished_at"] = NOW.replace(tzinfo=None).isoformat()
        self.assertEqual(self.check(r)["mode"], "failed")

    def test_missing_timestamp(self):
        r = attempt(); del r["finished_at"]
        self.assertEqual(self.check(r)["mode"], "failed")

    def test_parse_failure(self):
        r = attempt(); r["parse_failed"] = 1
        self.assertEqual(self.check(r)["mode"], "failed")

    def test_network_failure_even_with_products(self):
        r = attempt("ok", 1); r["http_error"] = 1
        self.assertEqual(self.check(r)["mode"], "failed")

    def test_partial_parse_failure_is_hard_fail(self):
        r = attempt("ok", 1); r["parse_failed"] = 1
        self.assertEqual(self.check(r)["mode"], "failed")

    def test_unknown_status(self):
        self.assertEqual(self.check(attempt("unknown"))["mode"], "failed")

    def test_ok_zero(self):
        self.assertEqual(self.check(attempt("ok"))["mode"], "failed")

    def test_no_change_with_products(self):
        self.assertEqual(self.check(attempt("no_change", 1))["mode"], "failed")

    def test_incomplete(self):
        r = attempt(); r["collector_completed"] = False
        self.assertEqual(self.check(r)["mode"], "failed")

    def test_invalid_counts(self):
        for value in (-1, True, "0", None):
            with self.subTest(value=value):
                r = attempt(); r["http_error"] = value
                self.assertEqual(self.check(r)["mode"], "failed")

    def test_success_preserved_across_three_no_changes(self):
        previous = attempt("ok", 2)
        doc = {"last_run": previous}
        for _ in range(3):
            doc = record_attempt(doc, attempt())
            self.assertEqual(doc["last_success"], previous)
            self.assertEqual(doc["last_run"], doc["last_attempt"])

    def test_legacy_migration_and_new_success(self):
        legacy = attempt("ok", 2)
        for key in ("execution_id", "collector_completed", "collector_version"):
            del legacy[key]
        doc = record_attempt({"last_run": legacy}, attempt())
        self.assertEqual(doc["last_success"], legacy)
        fresh = attempt("ok", 3)
        self.assertEqual(record_attempt(doc, fresh)["last_success"], fresh)

    def test_failed_attempt_preserves_success(self):
        success = attempt("ok", 1)
        doc = record_attempt({"last_run": success}, attempt("stopped"))
        self.assertEqual(doc["last_success"], success)

    def test_missing_success_is_not_fabricated(self):
        self.assertNotIn("last_success", record_attempt({}, attempt()))

    def test_mismatched_attempt(self):
        doc = record_attempt({}, attempt()); doc["last_attempt"]["status"] = "failed"
        self.assertEqual(validate(doc, outcome="success", execution_id="fixture:1:collect", started_after=BOUNDARY, now=NOW)["mode"], "failed")

    def test_missing_and_malformed_cli(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            p = Path(directory)/"status.json"; out = Path(directory)/"outputs"
            args = ["--status", str(p), "--github-output", str(out), "--collector-outcome", "success", "--execution-id", "fixture:1:collect", "--started-after", BOUNDARY]
            self.assertEqual(main(args), 1)
            p.write_text("{bad", encoding="utf-8")
            self.assertEqual(main(args), 1)
            p.write_text(json.dumps(record_attempt({}, attempt())), encoding="utf-8")
            self.assertEqual(main(args), 0)
            self.assertIn("mode=no_change", out.read_text())

    def test_collector_no_change_preserves_product_bytes(self):
        module_path = Path(__file__).parent/"daiso"/"collect_daiso.py"
        spec = importlib.util.spec_from_file_location("fixture_empty_collector", module_path)
        collector = importlib.util.module_from_spec(spec); spec.loader.exec_module(collector)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            d = Path(directory)
            products = d/"products.json"
            original = b'{"products": [], "updated_at": "historical"}\n'
            products.write_bytes(original)
            patches = {"OUT_DIR": d, "PRODUCTS": products, "STATE": d/"state.json",
                       "QUEUE": d/"queue.json", "STATUS": d/"status.json"}
            with patch.multiple(collector, **patches), patch.object(collector, "product_urls_from_sitemap", return_value=[]), patch.object(collector, "fetch", side_effect=AssertionError("network forbidden")):
                self.assertEqual(collector.main(), 0)
                doc = json.loads((d/"status.json").read_text(encoding="utf-8"))
                self.assertEqual(doc["last_run"]["status"], "no_change")
                self.assertTrue(doc["last_run"]["collector_completed"])
                self.assertEqual(doc["last_run"], doc["last_attempt"])
                self.assertNotIn("last_success", doc)
                self.assertEqual(products.read_bytes(), original)

    def test_collector_exception_records_failed_attempt(self):
        module_path = Path(__file__).parent/"daiso"/"collect_daiso.py"
        spec = importlib.util.spec_from_file_location("fixture_failed_collector", module_path)
        collector = importlib.util.module_from_spec(spec); spec.loader.exec_module(collector)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            p = Path(directory)/"status.json"
            p.write_text(json.dumps({"last_run": attempt("ok", 1)}))
            with patch.object(collector, "STATUS", p), patch.object(collector, "product_urls_from_sitemap", side_effect=ValueError("fixture failure")):
                with self.assertRaises(ValueError):
                    collector.run_collector()
                doc = json.loads(p.read_text())
                self.assertEqual(doc["last_run"]["status"], "failed")
                self.assertFalse(doc["last_run"]["collector_completed"])
                self.assertEqual(doc["last_success"]["ok"], 1)
                self.assertEqual(doc["last_attempt"], doc["last_run"])

    def test_collector_network_failure_counted(self):
        module_path = Path(__file__).parent/"daiso"/"collect_daiso.py"
        spec = importlib.util.spec_from_file_location("fixture_collector", module_path)
        collector = importlib.util.module_from_spec(spec); spec.loader.exec_module(collector)
        with patch.object(collector.urllib.request, "urlopen", side_effect=OSError("offline fixture")):
            status, _, _ = collector.fetch(collector.SITEMAP)
        self.assertEqual(status, 0)
        self.assertEqual(collector.NETWORK_ERRORS, 1)
        self.assertGreaterEqual(collector.DELAY, 30)


if __name__ == "__main__":
    unittest.main()
