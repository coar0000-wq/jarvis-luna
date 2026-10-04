#!/usr/bin/env python3
"""Offline-only shortlist observer regressions. No repository data or HTTP reads."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from daiso import observe_shortlist as obs


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data/daiso_real").mkdir(parents=True)
        self.pds = [str(1000000 + i) for i in range(356)]
        self.cps = [f"CP{i + 1:06d}" for i in range(356)]
        registry = dict(zip(self.pds, self.cps))
        registry["1999999"] = "CP000357"
        self.save("data/product_master.json", {"active_product_count": 356, "registry_count": 357, "pd_no_to_cp": registry, "products": [{"pd_no": pd, "canonical_product_id": cp} for pd, cp in zip(self.pds, self.cps)]})
        self.save("data/daiso_real/products.json", {"products": [{"pd_no": pd} for pd in self.pds]})
        self.save("data/daiso_real/candidate_pool.json", {"private_fixture": "unchanged"})
        self.shortlist(2)
        self.sleep = patch.object(obs.time, "sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)
        self.addCleanup(self.tmp.cleanup)

    def save(self, rel, value):
        (self.root / rel).write_text(json.dumps(value), encoding="utf-8")

    def shortlist(self, count):
        self.save("data/shopify_shortlist.json", {"active_pd_nos": self.pds[:count], "units": [{"status": "active", "pd_nos": self.pds[:count], "canonical_product_ids": self.cps[:count]}]})

    def http(self, url):
        if url.endswith("robots.txt"):
            return 200, b"User-agent: *\nAllow: /\nCrawl-delay: 30\n"
        pd = url.split("searchTerm=")[1]
        return 200, json.dumps({"items": [{"pdNo": pd, "sellAmt": 5000}]}).encode()

    def run_observe(self, http=None, **kwargs):
        with patch.object(obs, "_http_get", side_effect=http or self.http) as mocked:
            result = obs.observe(self.root, **kwargs)
        return result, mocked

    def test_success_invariance_and_schema(self):
        before = obs._hashes(self.root)
        result, network = self.run_observe()
        self.assertEqual(network.call_count, 3)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["expected_ids"], self.cps[:2])
        self.assertEqual(result["input_hashes_before"], result["input_hashes_after"])
        self.assertEqual(before, obs._hashes(self.root))
        self.assertFalse(result["operating_catalog_mutated"])
        for row in result["products"]:
            self.assertEqual(row["price_unit"], "product")
            self.assertEqual(row["source"]["capture_kind"], "successful_http_parse")
            self.assertEqual(row["provenance"]["http_status"], 200)
            self.assertNotIn("generated_at", row)
        self.assertEqual(set(p.name for p in (self.root / "data/daiso_real").iterdir()), {"products.json", "candidate_pool.json", "shortlist_observations.json", ".shortlist_observation_claim.json"})

    def test_failure_preserves_original_clock_and_price(self):
        result, _ = self.run_observe()
        old = result["products"]
        def failed(url):
            return self.http(url) if url.endswith("robots.txt") else (500, b"")
        failed_result, network = self.run_observe(failed, force=True)
        self.assertEqual(failed_result["status"], "partial")
        self.assertFalse(failed_result["complete"])
        self.assertEqual(failed_result["products"], old)
        self.assertEqual(network.call_count, 5)
        self.assertEqual(failed_result["new_success_ids"], [])

    def test_exact_identity_and_direct_price(self):
        cases = [b'{"pdNo":"999","sellAmt":5000}', b'{"pdNo":"1000000","nested":{"price":5000}}', b'<html>1000000 price 5000</html>', b'{"pdNo":"1000000","price":true}', b'{"pdNo":"1000000","price":"5,000"}', b'{"pdNo":"1000000","price":-5}', b'{"pdNo":"1000000","price":5000,"goodsNo":"999"}', b'[{"pdNo":"1000000","price":5000},{"pdNo":"1000000","price":5000}]', b'{"pdNo":"1000000","price":5000,"sellAmt":3000}']
        for body in cases:
            with self.subTest(body=body):
                self.assertIsNone(obs._parse(body, "1000000"))
        self.assertEqual(obs._parse(b'{"pdNo":"1000000","sellAmt":"5000"}', "1000000"), (5000, "sellAmt"))

    def test_robots_unknown_and_denied(self):
        for body in [b"unknown", b"User-agent: *\nDisallow: /", b"<html>User-agent: *</html>"]:
            with self.subTest(body=body):
                result, network = self.run_observe(lambda url: (200, body), force=True)
                self.assertEqual(network.call_count, 1)
                self.assertEqual(result["products"], [])
                self.assertEqual(result["status"], "blocked")

    def test_rate_limit_no_retry_or_next_product(self):
        def rate(url):
            return self.http(url) if url.endswith("robots.txt") else (429, b"quota")
        result, network = self.run_observe(rate)
        self.assertEqual(network.call_count, 2)
        self.assertEqual(result["http_attempt_count"], 2)
        self.assertEqual(result["status"], "blocked")

    def test_auth_no_retry(self):
        result, network = self.run_observe(lambda url: self.http(url) if url.endswith("robots.txt") else (403, b"forbidden"))
        self.assertEqual(network.call_count, 2)
        self.assertFalse(result["complete"])

    def test_partial_then_cooldown(self):
        def partial(url):
            if url.endswith("searchTerm=" + self.pds[1]):
                return 200, b"{}"
            return self.http(url)
        result, _ = self.run_observe(partial)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["new_success_ids"], self.cps[:1])
        again, network = self.run_observe()
        self.assertEqual(network.call_count, 0)
        self.assertEqual(again["status"], "partial")
        self.assertEqual(again["products"], result["products"])

    def test_cache_and_max_age(self):
        result, _ = self.run_observe()
        again, network = self.run_observe()
        self.assertEqual(network.call_count, 0)
        self.assertEqual(again["status"], "cached")
        self.assertTrue(again["complete"])
        old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        for row in result["products"]:
            row["source"]["collected_at"] = old
        result["budget_checkpoint"]["last_run_attempt_at"] = old
        result["budget_checkpoint"]["last_request_at"] = old
        self.save(obs.OUTPUT, result)
        ledger = json.loads((self.root / obs.LEDGER).read_text())
        ledger["last_request_at"] = old
        ledger["last_run_attempt_at"] = old
        self.save(obs.LEDGER, ledger)
        refreshed, network = self.run_observe()
        self.assertEqual(network.call_count, 3)
        self.assertEqual(refreshed["status"], "complete")

    def test_count_limits_unknown_duplicate_noncanonical(self):
        for count in [0, 11]:
            self.shortlist(count)
            with patch.object(obs, "_http_get") as network, self.assertRaises(obs.Blocked):
                obs.observe(self.root)
            network.assert_not_called()
        for ids in [[self.pds[0], self.pds[0]], ["999"], ["../evil"], [self.pds[0], 1000001]]:
            self.save("data/shopify_shortlist.json", {"active_pd_nos": ids})
            with self.assertRaises(obs.Blocked):
                obs.observe(self.root)
        self.shortlist(2)
        doc = json.loads((self.root / "data/shopify_shortlist.json").read_text())
        doc["units"][0]["canonical_product_ids"][0] = "CP999999"
        self.save("data/shopify_shortlist.json", doc)
        with self.assertRaises(obs.Blocked):
            obs.observe(self.root)

    def test_count_and_hash_change_block_write(self):
        def mutating(url):
            self.save("data/daiso_real/candidate_pool.json", {"changed": True})
            return self.http(url)
        with patch.object(obs, "_http_get", side_effect=mutating), self.assertRaises(obs.Blocked):
            obs.observe(self.root)
        self.assertFalse((self.root / obs.OUTPUT).exists())
        master = json.loads((self.root / "data/product_master.json").read_text())
        master["registry_count"] = 356
        self.save("data/product_master.json", master)
        with self.assertRaises(obs.Blocked):
            obs.observe(self.root)

    def test_symlink_and_traversal_rejected(self):
        with self.assertRaises(obs.Blocked):
            obs.observe(self.root / ".." / self.root.name)
        target = self.root / obs.OUTPUT
        try:
            target.symlink_to(self.root / "data/product_master.json")
        except OSError:
            self.skipTest("OS denies creating symlinks")
        with self.assertRaises(obs.Blocked):
            obs.observe(self.root)

    def test_no_adapter_and_fixed_urls(self):
        with self.assertRaises(TypeError):
            obs.observe(self.root, transport=self.http)
        for url in ["https://evil.test/robots.txt", "http://www.daisomall.co.kr/robots.txt", obs.BASE + "/cart", obs.BASE + obs.SEARCH + "?searchTerm=1&x=2", "https://user@www.daisomall.co.kr/robots.txt"]:
            with self.assertRaises(obs.Blocked):
                obs._url_ok(url)

    def test_windows_junction_rejected_offline(self):
        from types import SimpleNamespace
        original = Path.lstat
        def junction(p, *args, **kwargs):
            if p == self.root / "data/daiso_real":
                return SimpleNamespace(st_mode=0o40755, st_file_attributes=0x400)
            return original(p, *args, **kwargs)
        with patch.object(Path, "lstat", junction), patch.object(obs, "_http_get") as network, self.assertRaises(obs.Blocked):
            obs.observe(self.root)
        network.assert_not_called()

    def test_duplicate_keys_nonfinite_and_quota_no_capture(self):
        for body in [b'{"pdNo":"1000000","pdNo":"999","price":5000}', b'{"pdNo":"1000000","price":NaN}', b'{"pdNo":"1000000","price":Infinity}']:
            self.assertIsNone(obs._parse(body, "1000000"))
        def quota(url):
            return self.http(url) if url.endswith("robots.txt") else (200, b'{"pdNo":"1000000","price":5000,"error":"quota"}')
        result, network = self.run_observe(quota)
        self.assertEqual(network.call_count, 2)
        self.assertEqual(result["products"], [])

    def test_crawl_delay_and_original_clock_after_parse(self):
        def delayed(url):
            return (200, b"User-agent: *\nAllow: /\nCrawl-delay: 31.5\n") if url.endswith("robots.txt") else self.http(url)
        result, _ = self.run_observe(delayed)
        self.assertTrue(all(r["provenance"]["crawl_delay_seconds"] == 31.5 for r in result["products"]))
        self.assertTrue(obs.time.sleep.called)
        for row in result["products"]:
            event = next(a for a in result["attempts"] if a.get("pd_no") == row["pd_no"] and a.get("http_status") == 200)
            self.assertGreaterEqual(obs._epoch(row["source"]["collected_at"]), obs._epoch(event["attempted_at"]))

    def test_fixed_hash_allowlist_never_reads_or_enumerates_private_files(self):
        manual = self.root / "data/manual"
        manual.mkdir()
        (manual / "identity_contact_credentials.json").write_text('{"private":"fixture"}')
        original = Path.read_bytes
        reads = []
        def guarded(p):
            self.assertNotIn("manual", p.parts)
            reads.append(p.relative_to(self.root).as_posix())
            return original(p)
        with patch.object(Path, "read_bytes", guarded), patch.object(Path, "rglob", side_effect=AssertionError("directory enumeration forbidden")), patch.object(Path, "iterdir", side_effect=AssertionError("directory enumeration forbidden")):
            result, _ = self.run_observe()
        self.assertEqual(set(result["input_hashes_before"]), set(obs.INPUTS))
        self.assertEqual(result["input_hashes_before"]["data/legal_full.json"], "missing")
        self.assertTrue(all(rel in obs.INPUTS or rel in {obs.OUTPUT, obs.LEDGER} for rel in reads))

    def test_missing_ledger_with_history_fails_closed(self):
        self.run_observe()
        (self.root / obs.LEDGER).unlink()
        with patch.object(obs, "_http_get") as network, self.assertRaises(obs.Blocked):
            obs.observe(self.root, force=True)
        network.assert_not_called()
        self.assertFalse((self.root / obs.LEDGER).exists())

    def test_malformed_ledger_counters_and_clocks_fail_closed(self):
        self.run_observe()
        ledger = json.loads((self.root / obs.LEDGER).read_text())
        changes = [{"total_http_attempts": 0}, {"total_http_attempts": -1}, {"total_http_attempts": True}, {"total_http_attempts": "3"}, {"last_request_at": "bad"}, {"last_run_attempt_at": None}, {"last_request_at": "2999-01-01T00:00:00+00:00"}, {"last_run_attempt_at": "2026-01-01T00:00:00"}]
        for change in changes:
            with self.subTest(change=change):
                self.save(obs.LEDGER, dict(ledger, **change))
                with patch.object(obs, "_http_get") as network, self.assertRaises(obs.Blocked):
                    obs.observe(self.root, force=True)
                network.assert_not_called()
        self.save(obs.LEDGER, {})
        with self.assertRaises(obs.Blocked):
            obs.observe(self.root)

    def test_partial_cooldown_then_ledger_rollback_denied(self):
        def partial(url):
            return (200, b"{}") if url.endswith("searchTerm=" + self.pds[1]) else self.http(url)
        original, _ = self.run_observe(partial)
        cached, network = self.run_observe()
        self.assertEqual(network.call_count, 0)
        self.assertEqual(cached["http_attempt_count"], 0)
        self.assertEqual(cached["budget_checkpoint"], original["budget_checkpoint"])
        ledger = json.loads((self.root / obs.LEDGER).read_text())
        old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        for counter in (1, ledger["total_http_attempts"]):
            rolled = dict(ledger, total_http_attempts=counter, last_run_attempt_at=old, last_request_at=old)
            self.save(obs.LEDGER, rolled)
            with patch.object(obs, "_http_get") as network, self.assertRaises(obs.Blocked):
                obs.observe(self.root)
            network.assert_not_called()
            self.assertEqual(json.loads((self.root / obs.OUTPUT).read_text()), cached)

    def test_legacy_seven_attempts_migrate_without_new_reads_or_capture_changes(self):
        self.shortlist(6)
        original, _ = self.run_observe()
        self.assertEqual(original["http_attempt_count"], 7)
        del original["budget_checkpoint"]
        self.save(obs.OUTPUT, original)
        migrated, network = self.run_observe()
        network.assert_not_called()
        self.assertEqual(migrated["products"], original["products"])
        self.assertEqual(migrated["budget_checkpoint"]["total_http_attempts"], 7)
        next_cached, network = self.run_observe()
        network.assert_not_called()
        self.assertEqual(next_cached["budget_checkpoint"], migrated["budget_checkpoint"])

    def test_both_history_files_deleted_denied_by_fixed_watch_state(self):
        self.run_observe()
        (self.root / obs.OUTPUT).unlink()
        (self.root / obs.LEDGER).unlink()
        (self.root / "data/operations").mkdir()
        for team in ("sourcing", "pricing"):
            self.save("data/operations/state.json", {"watch": {"sources": {team: {"records": {"CP000001": {"source": obs.OUTPUT, "capture_kind": "successful_http_parse"}}}}}})
            with patch.object(obs, "_http_get") as network, self.assertRaises(obs.Blocked):
                obs.observe(self.root, force=True)
            network.assert_not_called()
        self.assertFalse((self.root / obs.OUTPUT).exists())
        self.assertFalse((self.root / obs.LEDGER).exists())

    def test_robots_retry_bounds(self):
        result, network = self.run_observe(lambda url: (503, b""))
        self.assertEqual(network.call_count, 2)
        self.assertEqual(result["status"], "blocked")
        result, network = self.run_observe(lambda url: (429, b""), force=True)
        self.assertEqual(network.call_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
