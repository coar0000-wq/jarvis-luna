#!/usr/bin/env python3
"""Offline continuity fixtures. Never reads repository data or makes HTTP calls."""
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_shortlist_observations import ObserverTests, obs


class ContinuityTests(unittest.TestCase):
    setUp = ObserverTests.setUp
    save = ObserverTests.save
    shortlist = ObserverTests.shortlist
    http = ObserverTests.http
    run_observe = ObserverTests.run_observe

    def load(self, name):
        return json.loads((self.root / name).read_text())

    def test_long_crawl_deadline(self):
        self.shortlist(6)
        start = self.mono
        def slow(url):
            return (200, b"User-agent: *\nAllow: /\nCrawl-delay: 300\n") if url.endswith("robots.txt") else self.http(url)
        result, network = self.run_observe(slow)
        self.assertEqual(network.call_count, 3)
        self.assertEqual(len(result["products"]), 2)
        self.assertEqual(self.mono - start, 600)
        self.assertTrue(any(a.get("reason") == "run_deadline_admission" for a in result["attempts"]))
        self.assertLessEqual(self.mono - start + obs.POLICY["safety_margin_seconds"], 720)

    def test_deadline_admission_before_sleep_and_network(self):
        def huge(url):
            return (200, b"User-agent: *\nAllow: /\nCrawl-delay: 10000\n") if url.endswith("robots.txt") else self.http(url)
        start = self.mono
        result, network = self.run_observe(huge, force=True)
        self.assertEqual(network.call_count, 1)
        self.assertEqual(self.mono, start)
        self.assertEqual(result["products"], [])

    def test_deadline_after_receive(self):
        def expensive(url):
            self.advance(650)
            return self.http(url)
        result, network = self.run_observe(expensive)
        self.assertEqual(network.call_count, 1)
        self.assertEqual(result["http_attempt_count"], 1)

    def test_force_run_cap_reservations_and_input_invariance(self):
        self.shortlist(10)
        before = obs._hashes(self.root)
        def failed(url):
            ledger = self.load(obs.LEDGER)
            doc = self.load(obs.OUTPUT)
            self.assertEqual(ledger["total_http_attempts"], doc["budget_checkpoint"]["total_http_attempts"])
            self.assertEqual(ledger["total_http_attempts"], len(ledger["request_history"]))
            return self.http(url) if url.endswith("robots.txt") else (503, b"")
        result, network = self.run_observe(failed, force=True)
        self.assertEqual(network.call_count, 12)
        self.assertEqual(result["http_attempt_count"], 12)
        self.assertTrue(any(a.get("reason") == "per_run_http_cap" for a in result["attempts"]))
        self.assertEqual(before, obs._hashes(self.root))
        self.assertEqual(len(before), 14)

    def test_force_rolling_cap_window_release_monotonic_lifetime(self):
        ledger = self.load(obs.LEDGER)
        stamp = datetime.fromtimestamp(self.wall - 1, timezone.utc).isoformat()
        ledger.update(total_http_attempts=24, last_run_attempt_at=stamp, last_request_at=stamp, last_checked_at=stamp,
                      request_history=[{"sequence": i, "reserved_at": stamp, "kind": "fixture"} for i in range(1, 25)])
        self.save(obs.LEDGER, ledger)
        first, network = self.run_observe(force=True)
        network.assert_not_called()
        self.assertEqual(first["budget_checkpoint"]["total_http_attempts"], 24)
        self.advance(86400)
        second, network = self.run_observe(force=True)
        self.assertEqual(network.call_count, 3)
        self.assertEqual(second["budget_checkpoint"]["total_http_attempts"], 27)
        self.assertEqual(self.load(obs.LEDGER)["request_history"][:24], ledger["request_history"])

    def test_partial_member_two_hour_retry_and_force_cooldown(self):
        def partial(url):
            return (200, b"{}") if url.endswith("searchTerm=" + self.pds[1]) else self.http(url)
        first, _ = self.run_observe(partial)
        second, network = self.run_observe(force=True)
        network.assert_not_called()
        self.assertEqual(first["products"], second["products"])
        self.advance(obs.COOLDOWN)
        third, network = self.run_observe()
        self.assertEqual(network.call_count, 2)
        self.assertEqual(third["new_success_ids"], self.cps[1:2])
        self.assertEqual(third["products"][0], first["products"][0])

    def test_ttl_boundary_force_freshness_and_capture_history(self):
        first, _ = self.run_observe()
        captured = obs._epoch(first["products"][0]["source"]["collected_at"])
        self.advance(captured + obs.FRESH_TTL - 1 - self.wall)
        fresh, network = self.run_observe(force=True)
        network.assert_not_called()
        self.assertEqual(fresh["products"], first["products"])
        self.advance(1)
        expired, network = self.run_observe(force=True)
        self.assertEqual(network.call_count, 2)
        self.assertEqual(expired["new_success_ids"], self.cps[:1])
        self.assertIn(first["products"][0], expired["capture_history"])

    def test_force_cannot_release_auth_quota_halt(self):
        _, network = self.run_observe(lambda u: self.http(u) if u.endswith("robots.txt") else (429, b"quota"))
        self.assertEqual(network.call_count, 2)
        self.advance(2 * 86400)
        again, network = self.run_observe(force=True)
        network.assert_not_called()
        self.assertFalse(again["complete"])

    def test_force_cannot_release_robots_halt(self):
        _, network = self.run_observe(lambda u: (503, b""))
        self.assertEqual(network.call_count, 1)
        self.advance(2 * 86400)
        _, network = self.run_observe(force=True)
        network.assert_not_called()

    def test_hardkill_retains_received_capture_and_reserved_inflight(self):
        def killed(url):
            if url.endswith("searchTerm=" + self.pds[1]):
                raise KeyboardInterrupt("fixture kill")
            return self.http(url)
        with patch.object(obs, "_http_get", side_effect=killed), self.assertRaises(KeyboardInterrupt):
            obs.observe(self.root)
        partial = self.load(obs.OUTPUT)
        self.assertEqual(len(partial["products"]), 1)
        self.assertFalse(partial["complete"])
        self.assertEqual(partial["budget_checkpoint"]["total_http_attempts"], 3)
        self.assertEqual(self.load(obs.LEDGER)["total_http_attempts"], 3)
        self.advance(obs.COOLDOWN)
        result, network = self.run_observe()
        self.assertEqual(network.call_count, 2)
        self.assertEqual(result["products"][0], partial["products"][0])
        self.assertEqual(result["budget_checkpoint"]["total_http_attempts"], 5)

    def test_rollback_future_capture_and_history_mutation(self):
        self.run_observe()
        output = self.load(obs.OUTPUT)
        ledger = self.load(obs.LEDGER)
        self.wall -= 1
        with patch.object(obs, "_http_get") as network, self.assertRaises(obs.Blocked):
            obs.observe(self.root, force=True)
        network.assert_not_called()
        self.wall += 1
        future = json.loads(json.dumps(output))
        future["products"][0]["source"]["collected_at"] = "2999-01-01T00:00:00+00:00"
        self.save(obs.OUTPUT, future)
        with patch.object(obs, "_http_get") as network, self.assertRaises(obs.Blocked):
            obs.observe(self.root, force=True)
        network.assert_not_called()
        self.save(obs.OUTPUT, output)
        ledger["request_history"][0]["kind"] = "changed"
        self.save(obs.LEDGER, ledger)
        with patch.object(obs, "_http_get") as network, self.assertRaises(obs.Blocked):
            obs.observe(self.root, force=True)
        network.assert_not_called()

    def test_missing_ledger_without_history_cannot_bootstrap(self):
        (self.root / obs.LEDGER).unlink()
        with patch.object(obs, "_http_get") as network, self.assertRaises(obs.Blocked):
            obs.observe(self.root, force=True)
        network.assert_not_called()
        self.assertFalse((self.root / obs.LEDGER).exists())

    def test_matching_nonseven_legacy_checkpoint_preserves_clocks(self):
        first, _ = self.run_observe()
        ledger = self.load(obs.LEDGER)
        clocks = {k: ledger[k] for k in ("last_run_attempt_at", "last_request_at")}
        for key in ("policy", "request_history", "last_checked_at", "member_attempts"):
            ledger.pop(key, None)
        first["budget_checkpoint"] = {k: first["budget_checkpoint"][k] for k in ("total_http_attempts", "last_run_attempt_at", "last_request_at")}
        self.save(obs.LEDGER, ledger)
        self.save(obs.OUTPUT, first)
        migrated, network = self.run_observe()
        network.assert_not_called()
        self.assertEqual(migrated["products"], first["products"])
        self.assertEqual(migrated["budget_checkpoint"]["total_http_attempts"], 3)
        final = self.load(obs.LEDGER)
        self.assertEqual({k: final[k] for k in clocks}, clocks)
        self.assertEqual(len(final["request_history"]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
