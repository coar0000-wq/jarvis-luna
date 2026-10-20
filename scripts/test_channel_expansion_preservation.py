"""Cumulative channel reviews survive health refreshes without a guard waiver."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import channel_expansion_agent as agent
from scripts.publish_transaction import PublishError, overlay, removed_identities

CATALOG_REL = "data/channel_expansion/channel_candidates.json"
STAMP = "2026-10-19T14:40:00+00:00"


class ChannelCatalogPreservationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.catalog = self.root / CATALOG_REL
        self.report = self.root / "data/agents/channel_expansion.json"
        self.catalog.parent.mkdir(parents=True)
        self.policy = json.loads((ROOT / "config/publish_policy.json").read_text())

    def tearDown(self):
        self.tmp.cleanup()

    def generate(self, value=None, raw=None, *, missing=False, reachable=False):
        if not missing:
            self.catalog.write_bytes(raw if raw is not None else self.encode(value))
        with patch.multiple(agent, ROOT=self.root, OUT_DIR=self.catalog.parent,
                            CATALOG=self.catalog, REPORT=self.report), \
                patch.object(agent, "now", return_value=STAMP), \
                patch.object(agent, "test_url", return_value={
                    "reachable": reachable, "status_code": 200 if reachable else 503,
                }) as probe, redirect_stdout(io.StringIO()):
            self.last_probe = probe
            agent.main()
        return json.loads(self.catalog.read_bytes()), probe

    @staticmethod
    def encode(value):
        return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()

    def test_current_catalog_reviews_and_all_existing_identities_survive(self):
        # Exercise the real historical records in the checkout without probing
        # external sources or modifying production data.
        old = json.loads((ROOT / CATALOG_REL).read_bytes())
        reviewed = [row for row in old["candidates"] if row.get("reviewed_at")]
        new, probe = self.generate(old)
        producer_fields = {"schema_version", "generated_at", "discovery_mode",
                           "candidate_count", "verified_count", "candidates",
                           "next_expansion_queries"}
        for key, value in old.items():
            if key not in producer_fields:
                self.assertEqual(new[key], value)
        for row in reviewed:
            self.assertIn(row, new["candidates"])
            self.assertNotIn(row["url"], [call.args[0] for call in probe.call_args_list])
        self.assertEqual(removed_identities(old, new, self.policy, where=CATALOG_REL), [])
        self.assertEqual(probe.call_count, len(agent.SEEDS))
        raw, output = self.encode(old), self.catalog.read_bytes()
        self.assertEqual(json.loads(overlay(CATALOG_REL, raw, output, raw,
                                           self.policy, {})), new)

    def test_nested_metadata_and_unseeded_review_remain_exact_across_runs(self):
        reviewed = {"url": "https://reviewed.example/", "name": "Reviewed source",
                    "status": "review_required", "enabled": False,
                    "connector_registered": False, "reachable": None,
                    "reviewed_at": "2026-10-18T15:34:54+00:00",
                    "restrictions": {"reuse": False, "paths": ["/sitemap.xml"]}}
        old = {"schema_version": 1, "candidates": [reviewed],
               "catalog_reviewed_at": "2026-10-18T15:34:54+00:00",
               "review_metadata": {"reviewer": "owner", "history": [{"id": "review-1"}]}}
        new, _ = self.generate(old)
        again, _ = self.generate(new, reachable=True)
        self.assertEqual(again["catalog_reviewed_at"], old["catalog_reviewed_at"])
        self.assertEqual(again["review_metadata"], old["review_metadata"])
        self.assertIn(reviewed, again["candidates"])
        self.assertEqual(again["candidate_count"], len(agent.SEEDS) + 1)
        self.assertEqual(again["verified_count"], len(agent.SEEDS))
        self.assertEqual(again["generated_at"], STAMP)
        self.assertEqual(again["discovery_mode"], "seed_catalog_plus_health_probe")
        self.assertEqual(again["next_expansion_queries"], agent.KEYWORDS)

    def test_owned_health_values_refresh_without_removing_candidate_extensions(self):
        row = {**agent.SEEDS[0], "reachable": True, "status_code": 200,
               "status": "candidate", "checked_at": "old",
               "extension": {"notes": ["keep this"]}}
        new, _ = self.generate({"schema_version": 1, "candidates": [row]})
        current = next(r for r in new["candidates"] if r["url"] == row["url"])
        self.assertEqual(current["extension"], row["extension"])
        self.assertIs(current["reachable"], False)
        self.assertEqual(current["status_code"], 503)
        self.assertEqual(current["status"], "unverified")
        self.assertEqual(current["checked_at"], STAMP)

    def test_new_catalog_initializes_normally(self):
        new, _ = self.generate(missing=True, reachable=True)
        self.assertEqual(new["candidate_count"], len(agent.SEEDS))
        self.assertEqual(new["verified_count"], len(agent.SEEDS))
        self.assertEqual(json.loads(self.report.read_bytes())["safety"], {
            "auto_activation": False, "shopify_write": False,
            "ads_write": False, "secrets_write": False})

    def test_malformed_catalog_fails_before_any_probe_or_overwrite(self):
        invalid = [b'{broken', b'null', b'[]', b'{}', b'{"candidates": null}',
                   b'{"candidates": {}}', b'{"candidates": [null]}',
                   b'{"candidates": [{}]}', b'{"candidates": [{"url": 12}]}',
                   b'{"candidates": [{"url": "  "}]}']
        for raw in invalid:
            with self.subTest(raw=raw):
                self.report.parent.mkdir(parents=True, exist_ok=True)
                self.report.write_bytes(b'{"previous": true}\n')
                with self.assertRaises((ValueError, TypeError)):
                    self.generate(raw=raw)
                self.assertEqual(self.catalog.read_bytes(), raw)
                self.assertEqual(self.report.read_bytes(), b'{"previous": true}\n')
                self.last_probe.assert_not_called()

    def test_colliding_urls_fail_instead_of_dropping_historical_rows(self):
        for url in ["https://example.com/", "https://EXAMPLE.com"]:
            old = {"candidates": [{"url": "https://example.com/", "id": "first"},
                                  {"url": url, "id": "second"}]}
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "colliding"):
                self.generate(old)
            self.assertEqual(json.loads(self.catalog.read_bytes()), old)

    def test_removal_guard_still_rejects_review_metadata_or_candidate_loss(self):
        old = {"candidates": [{"url": "https://reviewed.example/"}],
               "catalog_reviewed_at": "old", "metadata": {"review": "keep"}}
        for key in ("catalog_reviewed_at", "metadata", "candidates"):
            new = deepcopy(old)
            if key == "candidates":
                new[key] = []
            else:
                del new[key]
            with self.subTest(key=key), self.assertRaisesRegex(PublishError, "removal requires"):
                overlay(CATALOG_REL, self.encode(old), self.encode(new), self.encode(old),
                        self.policy, {})


if __name__ == "__main__":
    unittest.main()
