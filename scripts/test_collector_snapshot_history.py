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
    def test_label_diagnostics_rotate_without_waiving_source_label_protection(self):
        rel = "data/daiso_real/us_label_sync_report.json"
        old = {"current_s_count": 2, "items": {"old": {"missing_fields": ["manufacturer"]},
                                             "keep": {"missing_fields": ["ingredients_inci"]}}}
        new = {"current_s_count": 1, "items": {"keep": {"missing_fields": []}}}
        self.assertEqual(set(csh.allowed_removals(rel, old, new, POLICY)),
                         {"old", "ingredients_inci"})
        with self.assertRaises(ValueError):
            csh.allowed_removals(rel, old, {"items": {}}, POLICY)
        with self.assertRaises(ValueError):
            csh.allowed_removals("data/daiso_real/daiso_us_labels.json", old, new, POLICY)

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

    def test_daiso_candidate_ids_rotate_but_other_lists_stay_guarded(self):
        # 2026-10-16 회귀: 매 실행 바뀌는 candidate_ids 때문에 Daiso 수집 워크플로가 10-03 이후 계속 실패했다.
        rel = "data/daiso_real/collection_status.json"
        run = lambda ids, buckets: {"candidate_ids": ids, "prefetch_policy": {"eligible_buckets": buckets}}
        old = {s: run(["A", "B"], ["x", "y"]) for s in ("last_run", "last_attempt", "last_candidate_success")}
        new = {s: run(["B", "C"], ["x", "y"]) for s in old}
        self.assertEqual(sorted(csh.allowed_removals(rel, old, new, POLICY)), ["A", "A", "A"])
        # 2026-10-17: last_* 는 실행 1회 요약이라 다른 칸(버킷·제외 사유)도 통째로 바뀐다. 빠진 값은 매니페스트에 남는다.
        moved = {s: run(["A", "B"], ["x"]) for s in old}
        self.assertEqual(sorted(csh.allowed_removals(rel, old, moved, POLICY)), ["y", "y", "y"])
        # 누적 칸(totals 등)은 요약이 아니라서 계속 막는다.
        old_totals, bad = dict(old, totals={"products": 1, "ok": 2}), dict(new, totals={"ok": 2})
        with self.assertRaises(ValueError):
            csh.allowed_removals(rel, old_totals, bad, POLICY)

    def test_emptied_rotating_container_may_drop_but_other_fields_stay_guarded(self):
        # 2026-10-17: 실패 이력이 모두 해소돼 failed_workflow_history 칸이 통째로 빠지자 Core 발행이 막혔다.
        rel = "data/agents/daiso_pipeline_health.json"
        old = {"failed_workflow_history": [{"run": 1}], "status": "failed", "public_authority": False}
        self.assertEqual(csh.allowed_removals(rel, old, {"status": "success", "public_authority": False}, POLICY),
                         ["failed_workflow_history"])
        with self.assertRaises(ValueError):
            csh.allowed_removals(rel, old, {"failed_workflow_history": [], "status": "success"}, POLICY)

    def test_unchanged_file_writes_nothing(self):
        before = (self.root / "data/publish_deletions.json").read_bytes()
        self.assertEqual(csh.update(self.root, [self.rel])[self.rel], "unchanged")
        self.assertEqual((self.root / "data/publish_deletions.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=1)
