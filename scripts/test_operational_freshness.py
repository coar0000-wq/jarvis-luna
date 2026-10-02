#!/usr/bin/env python3
"""Deterministic offline fixtures. Run: python -B -m unittest discover -s scripts -p test_operational_freshness.py -v"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from operational_freshness import age_channels, assess_collection, assess_heartbeat

NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


def ago(hours):
    return (NOW - timedelta(hours=hours)).isoformat()


def run(status="ok", hours=1, ok=2, **extra):
    return dict(status=status, finished_at=ago(hours), ok=ok, **extra)


def channel(**extra):
    return dict(status="ok", trust="verified", reason="실제 원본 사유", collected_at=ago(1), **extra)


class ChannelTests(unittest.TestCase):
    def assess(self, record):
        return age_channels({"x": record}, NOW)["x"]

    def test_fresh(self):
        result = self.assess(channel())
        self.assertEqual((result["status"], result["trust"]), ("ok", "verified"))
        self.assertFalse(result["stale"])
        self.assertEqual(result["reason"], "실제 원본 사유")

    def test_stale_and_idempotent(self):
        record = channel()
        record["collected_at"] = ago(72)
        first = age_channels({"x": record}, NOW)
        self.assertEqual(first, age_channels(first, NOW))
        self.assertEqual(first["x"]["status"], "stale")
        self.assertEqual(first["x"]["trust"], "stale")
        self.assertEqual(first["x"]["reason"].count("이후 갱신 없음"), 1)

    def test_repeated_legacy_prefix_cleanup(self):
        record = channel()
        record["collected_at"] = ago(72)
        record["reason"] = " 2026-09-28 이후 갱신 없음 (5.0일). 2026-09-29 이후 갱신 없음 (4.0일). 원본"
        result = self.assess(record)
        self.assertEqual(result["source_reason"], "원본")
        self.assertEqual(result["reason"].count("이후 갱신 없음"), 1)
        self.assertEqual(result, self.assess(result))

    def test_legacy_prefix_removed_when_fresh(self):
        record = channel()
        record["reason"] = "2026-09-28 이후 갱신 없음 (5.0일). 원본"
        self.assertEqual(self.assess(record)["reason"], "원본")

    def test_stale_recovery(self):
        record = channel()
        record["collected_at"] = ago(72)
        aged = self.assess(record)
        aged["collected_at"] = ago(1)
        fresh = self.assess(aged)
        self.assertEqual((fresh["status"], fresh["trust"]), ("ok", "verified"))
        self.assertEqual(fresh["freshness_reason"], "")
        self.assertEqual(fresh["reason"], record["reason"])

    def test_invalid_recovery(self):
        record = channel()
        record.pop("collected_at")
        aged = self.assess(record)
        aged["collected_at"] = ago(1)
        fresh = self.assess(aged)
        self.assertEqual((fresh["status"], fresh["trust"]), ("ok", "verified"))

    def test_missing_invalid_future(self):
        for value in (None, "", "nonsense", "2026-10-03", ago(-1), [], {}):
            with self.subTest(value=value):
                record = channel()
                record["collected_at"] = value
                result = self.assess(record)
                self.assertEqual((result["status"], result["trust"]), ("unverified", "unverified"))
                self.assertIsNone(result["age_hours"])
                self.assertEqual(result["collected_at"], value)
                self.assertEqual(result, self.assess(result))

    def test_failure_status_preservation(self):
        for status in ("disabled", "error", "failed", "blocked"):
            for value in (None, "bad", ago(-1), ago(100)):
                with self.subTest(status=status, value=value):
                    record = channel()
                    record.update(status=status, trust="blocked", collected_at=value)
                    result = self.assess(record)
                    self.assertEqual(result["status"], status)
                    self.assertEqual(result["source_status"], status)
                    self.assertEqual(result["source_trust"], "blocked")
                    self.assertEqual(result, self.assess(result))

    def test_nonverified_stale_trust_preserved(self):
        record = channel()
        record.update(trust="manual", collected_at=ago(100))
        self.assertEqual(self.assess(record)["trust"], "manual")

    def test_threshold_and_future_skew(self):
        for hours, status in ((48, "ok"), (48.001, "stale"), (-5/60, "ok"), (-6/60, "unverified")):
            record = channel()
            record["collected_at"] = ago(hours)
            self.assertEqual(self.assess(record)["status"], status)
        record["collected_at"] = ago(-5/60)
        self.assertEqual(self.assess(record)["age_hours"], 0)

    def test_offsets_and_naive_are_utc(self):
        values = ("2026-10-03T20:00:00+09:00", "2026-10-03T11:00:00Z", "2026-10-03T11:00:00", datetime(2026, 10, 3, 11))
        for value in values:
            record = channel()
            record["collected_at"] = value
            self.assertEqual(self.assess(record)["age_hours"], 1)
        self.assertEqual(age_channels({"x": record}, NOW.replace(tzinfo=None))["x"]["age_hours"], 1)

    def test_input_deeply_unchanged(self):
        original = {"x": dict(channel(), nested={"rows": [1]}), "other": [1], "null": None}
        before = deepcopy(original)
        result = age_channels(original, NOW)
        result["x"]["nested"]["rows"].append(2)
        result["other"].append(2)
        self.assertEqual(original, before)

    def test_nonmapping_empty_and_no_fake_timestamp(self):
        self.assertIsNone(age_channels(None, NOW))
        self.assertEqual(age_channels({}, NOW), {})
        result = self.assess({"status": "ok"})
        self.assertNotIn("collected_at", result)


class CollectionTests(unittest.TestCase):
    def assess(self, doc):
        return assess_collection(doc, NOW)

    def test_recent_legacy_ok_success(self):
        result = self.assess({"last_run": run()})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["last_attempt_at"], ago(1))
        self.assertEqual(result["last_success_at"], ago(1))
        self.assertFalse(result["data_stale"])

    def test_explicit_last_attempt_authoritative(self):
        result = self.assess({"last_attempt": run("failed"), "last_run": run()})
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["is_failure"])

    def test_no_change_preserves_last_success(self):
        doc = {"last_attempt": run("no_change", ok=0), "last_run": run("no_change", ok=0), "last_success": run(hours=100)}
        before = deepcopy(doc)
        result = self.assess(doc)
        self.assertEqual(doc, before)
        self.assertEqual(result["status"], "warning")
        self.assertTrue(result["is_no_change"])
        self.assertTrue(result["data_stale"])
        self.assertFalse(result["attempt_stale"])
        self.assertEqual(result["last_success_at"], ago(100))
        self.assertEqual(result["success_age_hours"], 100)

    def test_no_change_without_success(self):
        result = self.assess({"last_run": run("no_change", ok=0)})
        self.assertEqual(result["status"], "warning")
        self.assertIsNone(result["last_success_at"])
        self.assertTrue(result["data_stale"])

    def test_ok_zero_is_no_change(self):
        result = self.assess({"last_run": run(ok=0)})
        self.assertEqual(result["status"], "warning")
        self.assertTrue(result["is_no_change"])
        self.assertIsNone(result["last_success_at"])

    def test_explicit_no_change_flag_not_success(self):
        result = self.assess({"last_run": run(is_no_change=True)})
        self.assertEqual(result["status"], "warning")
        self.assertIsNone(result["last_success_at"])

    def test_failure_even_stale_missing_future(self):
        for status in ("failed", "error"):
            for timestamp in (None, "invalid", ago(-10), ago(100)):
                doc = {"last_attempt": dict(run(status), finished_at=timestamp)}
                result = self.assess(doc)
                self.assertEqual(result["status"], "failed")
                self.assertTrue(result["is_failure"])
                self.assertFalse(result["is_no_change"])

    def test_stale_and_threshold(self):
        for hours, expected in ((36, "success"), (36.001, "degraded"), (100, "degraded")):
            result = self.assess({"last_run": run(hours=hours)})
            self.assertEqual(result["status"], expected)
            self.assertEqual(result["attempt_stale"], hours > 36)

    def test_stale_no_change_degraded_not_failure(self):
        result = self.assess({"last_run": run("no_change", hours=40, ok=0)})
        self.assertEqual(result["status"], "degraded")
        self.assertTrue(result["is_no_change"])
        self.assertFalse(result["is_failure"])

    def test_missing_invalid_future_attempt(self):
        for timestamp in (None, "bad", ago(-1), "2026-10-03"):
            result = self.assess({"last_run": dict(run(), finished_at=timestamp)})
            self.assertEqual(result["status"], "degraded")
            self.assertIsNone(result["last_attempt_at"])
            self.assertTrue(result["attempt_stale"])
        self.assertEqual(self.assess({})["status"], "degraded")

    def test_invalid_success_not_replaced(self):
        for success in (None, {}, run("no_change"), dict(run(), finished_at="bad"), dict(run(), finished_at=ago(-1))):
            result = self.assess({"last_attempt": run("no_change"), "last_run": run(), "last_success": success})
            self.assertIsNone(result["last_success_at"])
            self.assertTrue(result["data_stale"])

    def test_unknown_never_success(self):
        for status in (None, "unknown", "running", "success", "disabled"):
            result = self.assess({"last_run": run(status)})
            self.assertEqual(result["status"], "degraded")
            self.assertFalse(result["is_failure"])

    def test_invalid_ok_never_success_or_no_change(self):
        for ok in (None, "bad", True, -1, float("nan"), float("inf")):
            result = self.assess({"last_run": run(ok=ok)})
            self.assertEqual(result["status"], "degraded")
            self.assertFalse(result["is_no_change"])

    def test_finished_precedes_started(self):
        doc = {"last_run": dict(run(), started_at=ago(100))}
        self.assertEqual(self.assess(doc)["attempt_age_hours"], 1)
        doc["last_run"]["finished_at"] = "invalid"
        self.assertIsNone(self.assess(doc)["last_attempt_at"])

    def test_legacy_start_only(self):
        result = self.assess({"last_run": {"status": "ok", "ok": 3, "started_at": ago(1)}})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["last_success_at"], ago(1))

    def test_explicit_empty_attempt_does_not_fallback(self):
        result = self.assess({"last_attempt": {}, "last_run": run()})
        self.assertEqual(result["status"], "degraded")
        self.assertIsNone(result["last_attempt_at"])

    def test_future_skew_and_offset(self):
        for timestamp in (ago(-5/60), "2026-10-03T20:00:00+09:00", "2026-10-03T11:00:00"):
            result = self.assess({"last_run": dict(run(), finished_at=timestamp)})
            self.assertEqual(result["status"], "success")
            self.assertGreaterEqual(result["attempt_age_hours"], 0)

    def test_nonmapping_input(self):
        for value in (None, [], "bad"):
            self.assertEqual(self.assess(value)["status"], "degraded")


class HeartbeatTests(unittest.TestCase):
    def assess(self, doc):
        return assess_heartbeat(doc, NOW)

    def test_healthy_and_expected_times(self):
        for status in ("success", "ok"):
            result = self.assess({"status": status, "generated_at": ago(1)})
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["last_attempt_at"], ago(1))
            self.assertEqual(result["next_expected_at"], ago(-1))
            self.assertEqual(result["grace_deadline_at"], ago(-3.5))
            self.assertFalse(result["delayed"])
            self.assertFalse(result["is_failure"])

    def test_delayed_and_grace_boundary(self):
        for hours, status in ((4.5, "success"), (4.501, "warning"), (100, "warning")):
            result = self.assess({"status": "success", "generated_at": ago(hours)})
            self.assertEqual(result["status"], status)
            self.assertEqual(result["delayed"], hours > 4.5)

    def test_missing_invalid_future(self):
        for value in (None, "bad", ago(-1), "2026-10-03", []):
            result = self.assess({"status": "success", "generated_at": value})
            self.assertEqual(result["status"], "warning")
            self.assertTrue(result["delayed"])
            for key in ("last_attempt_at", "age_hours", "next_expected_at", "grace_deadline_at"):
                self.assertIsNone(result[key])

    def test_failed_even_without_valid_timestamp(self):
        for status in ("failed", "error"):
            for timestamp in (None, "bad", ago(100), ago(1), ago(-1)):
                result = self.assess({"status": status, "generated_at": timestamp})
                self.assertEqual(result["status"], "failed")
                self.assertTrue(result["is_failure"])

    def test_warning_unknown_disabled_not_healthy(self):
        for status in ("warning", "disabled", "unknown", None):
            result = self.assess({"status": status, "generated_at": ago(1)})
            self.assertEqual(result["status"], "warning")
            self.assertFalse(result["is_failure"])

    def test_derived_mtime_cannot_fake_execution(self):
        result = self.assess({"status": "success", "updated_at": ago(0), "mtime": ago(0), "last_success": ago(0)})
        self.assertEqual(result["status"], "warning")
        self.assertIsNone(result["last_attempt_at"])
        self.assertIsNone(result["next_expected_at"])

    def test_input_unchanged(self):
        doc = {"status": "success", "generated_at": ago(1), "nested": {"rows": [1]}}
        before = deepcopy(doc)
        self.assess(doc)
        self.assertEqual(doc, before)

    def test_offset_naive_and_skew(self):
        for timestamp in ("2026-10-03T20:00:00+09:00", "2026-10-03T11:00:00", ago(-5/60)):
            result = self.assess({"status": "success", "generated_at": timestamp})
            self.assertEqual(result["status"], "success")
            self.assertGreaterEqual(result["age_hours"], 0)

    def test_nonmapping(self):
        self.assertEqual(self.assess(None)["status"], "warning")


class PolicyTests(unittest.TestCase):
    def test_invalid_now_rejected(self):
        for function in (age_channels, assess_collection, assess_heartbeat):
            with self.assertRaises(ValueError):
                function({}, now="bad")

    def test_invalid_limits_rejected(self):
        cases = ((age_channels, "stale_hours"), (assess_collection, "stale_after_hours"), (assess_heartbeat, "interval_hours"), (assess_heartbeat, "grace_hours"))
        for function, key in cases:
            for value in (-1, float("nan"), float("inf"), "bad", True):
                with self.subTest(function=function.__name__, key=key, value=value):
                    with self.assertRaises(ValueError):
                        function({}, now=NOW, **{key: value})


if __name__ == "__main__":
    unittest.main()
