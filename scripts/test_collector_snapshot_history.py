#!/usr/bin/env python3
"""Rotating collector snapshot manifests: rotation allowed, everything else still blocked."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import collector_snapshot_history as csh  # noqa: E402
from scripts.publish_transaction import deletion_authorized  # noqa: E402

POLICY = json.loads((ROOT / "config/publish_policy.json").read_text(encoding="utf-8"))


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class CollectorSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.invalid")
        git(self.root, "config", "user.name", "t")
        (self.root / "config").mkdir()
        (self.root / "config/publish_policy.json").write_text(json.dumps(POLICY), encoding="utf-8")
        (self.root / "data").mkdir()
        self.rel = "data/amazon_new_products.json"
        self.old = {"count": 2, "products": [{"rank": 1, "url": "https://a/1"}, {"rank": 2, "url": "https://a/2"}]}
        (self.root / self.rel).write_text(json.dumps(self.old), encoding="utf-8")
        (self.root / "data/publish_deletions.json").write_text(json.dumps({"schema_version": 1, "deletions": []}), encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "base")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, doc):
        (self.root / self.rel).write_text(json.dumps(doc), encoding="utf-8")

    def test_rotated_ranking_is_authorized_by_exact_entry(self):
        self.write({"count": 2, "products": [{"rank": 1, "url": "https://a/1"}, {"rank": 2, "url": "https://a/3"}]})
        report = csh.update(self.root, [self.rel])
        self.assertIn("authorized 1", report[self.rel])
        manifest = json.loads((self.root / "data/publish_deletions.json").read_text(encoding="utf-8"))
        base = subprocess.run(["git", "-C", str(self.root), "show", "HEAD:" + self.rel], capture_output=True).stdout
        local = (self.root / self.rel).read_bytes()
        self.assertTrue(deletion_authorized(self.rel, base, ["https://a/2"], manifest, replacement=local))

    def test_field_removal_outside_rotating_list_is_blocked(self):
        self.write({"products": [{"rank": 1, "url": "https://a/1"}, {"rank": 2, "url": "https://a/2"}]})
        with self.assertRaises(ValueError):
            csh.update(self.root, [self.rel])

    def test_undeclared_file_is_blocked(self):
        with self.assertRaises(ValueError):
            csh.update(self.root, ["data/daiso_real/products.json"])

    def test_wildcard_scope_is_single_level(self):
        rel = "data/knowledge/real_sources.json"
        self.assertTrue(csh.rotating(rel, ("sources", "arxiv", "items")))
        self.assertFalse(csh.rotating(rel, ("sources", "arxiv", "provenance", "items")))
        self.assertFalse(csh.rotating(rel, ("sources",)))

    def test_unchanged_file_writes_nothing(self):
        before = (self.root / "data/publish_deletions.json").read_bytes()
        self.assertEqual(csh.update(self.root, [self.rel])[self.rel], "unchanged")
        self.assertEqual((self.root / "data/publish_deletions.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=1)
