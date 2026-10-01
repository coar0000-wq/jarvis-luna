#!/usr/bin/env python3
"""운영 분류기 재현, 메모리 정리, 동시 쓰기 가드 회귀 테스트. 네트워크 호출 없음."""
from __future__ import annotations

import json
import hashlib
import contextlib
import runpy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import expand_obsidian_graph as graph
import self_improve as si
import self_improve_support as support


def record(title):
    return {"title": title, "text": "", "source": "fixture"}


def topic_run(rows, policy=None):
    policy = policy or {"version": 0, "topics": {}}
    with patch.object(graph, "load_records", return_value=rows), \
         patch.object(si, "read_snapshot", return_value=(policy, "original_revision")), \
         patch.object(si, "save") as writer:
        result = si.topic_loop(dry=True)
    return result, writer


class ReplayTests(unittest.TestCase):
    def test_explicit_patterns_do_not_read_or_mutate_global_cache(self):
        cache = graph._LEARNED
        sentinel = [("unrelated", __import__("re").compile("signal"))]
        graph._LEARNED = sentinel
        try:
            with patch.object(graph, "learned_topic_patterns", side_effect=AssertionError("cache read")):
                self.assertEqual(graph.topic_names(record("signal"), learned_patterns=[]), ["미분류"])
                patterns = graph.compile_topic_patterns({"뷰티·스킨케어": ["signal"]})
                self.assertIn("뷰티·스킨케어", graph.topic_names(record("signal"), learned_patterns=patterns))
            self.assertIs(graph._LEARNED, sentinel)
        finally:
            graph._LEARNED = cache

    def test_shared_patterns_keep_word_boundaries(self):
        patterns = graph.compile_topic_patterns({"뷰티·스킨케어": ["SPF", "", 42]})
        for text in ("spf", "SPF 30", "spf-linked"):
            self.assertIn("뷰티·스킨케어", graph.topic_names(record(text), learned_patterns=patterns))
        for text in ("spfx", "asphalt"):
            self.assertNotIn("뷰티·스킨케어", graph.topic_names(record(text), learned_patterns=patterns))
        self.assertEqual(graph.compile_topic_patterns({"bad": "not a list"}), [])

    def test_shadow_gain_is_actual_classifier_gain_including_hyphens(self):
        rows = [record(f"beauty signal item{i}") for i in range(8)]
        rows += [record(f"signal observation{i}") for i in range(3)]
        rows += [record(f"signal-linked notice{i}") for i in range(3)]
        result, writer = topic_run(rows)
        self.assertEqual(result["uncategorized_before"], 6)
        self.assertEqual(result["uncategorized_after_shadow"], 0)
        self.assertEqual(result["decisions"][0]["newly_classified"], 6)
        self.assertEqual(result["evaluation"]["mode"], "production_classifier_replay")
        self.assertEqual(result["evaluation"]["evaluated_records"], len(rows))
        self.assertEqual(writer.call_args.kwargs["expected_revision"], "original_revision")

    def test_actual_boundary_collateral_rejects_unsafe_candidate(self):
        rows = [record(f"beauty signal item{i}") for i in range(8)]
        rows += [record(f"physics signal-linked item{i}") for i in range(2)]
        rows += [record(f"signal observation{i}") for i in range(3)]
        result, writer = topic_run(rows)
        self.assertEqual(result["adopted"], 0)
        self.assertEqual(result["uncategorized_after_shadow"], 3)
        writer.assert_not_called()

    def test_rollback_is_included_in_actual_shadow_result(self):
        rows = [record(f"beauty signal item{i}") for i in range(8)]
        rows += [record(f"signal observation{i}") for i in range(2)]
        policy = {"version": 1, "topics": {"AI 에이전트": ["signal"]}}
        result, writer = topic_run(rows, policy)
        self.assertEqual(result["uncategorized_before"], 0)
        self.assertEqual(result["uncategorized_after_shadow"], 2)
        self.assertEqual(result["status"], "rollback")
        self.assertEqual(policy["topics"], {"AI 에이전트": ["signal"]})
        self.assertEqual(writer.call_args.args[1]["topics"], {})

    def test_after_hash_matches_the_saved_rule_order(self):
        rows = [record(f"beauty signal item{i}") for i in range(8)]
        rows += [record(f"signal observation{i}") for i in range(3)]
        result, writer = topic_run(rows, {"version": 1, "topics": {"뷰티·스킨케어": ["zebra"]}})
        saved = writer.call_args.args[1]["topics"]
        expected = hashlib.sha256(json.dumps(saved, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(result["evaluation"]["after_policy_sha256"], expected)

    def test_replay_is_repeatable_and_leaves_cache_unchanged(self):
        cache = graph._LEARNED
        rows = [record(f"beauty signal item{i}") for i in range(8)]
        rows += [record(f"signal observation{i}") for i in range(3)]
        left, _ = topic_run(rows)
        right, _ = topic_run(rows)
        self.assertEqual(left["evaluation"], right["evaluation"])
        self.assertIs(graph._LEARNED, cache)


class MemoryTests(unittest.TestCase):
    AT = "2026-10-01T10:00:00+00:00"

    def test_recurring_errors_include_evidence_not_raw_error_text(self):
        history = {"runs": [
            {"at": "2026-09-30T10:00:00+00:00", "topics": {"status": "error", "error": "private text"}},
            {"at": "2026-10-01T09:00:00+00:00", "topics": {"status": "error"}},
        ]}
        result = support.consolidate_memory(history, [], self.AT)
        self.assertEqual(len(result["recurring_patterns"]), 1)
        item = result["recurring_patterns"][0]
        self.assertEqual(item["occurrences"], 2)
        self.assertEqual(len(item["evidence"]), 2)
        self.assertTrue(item["requires_human_approval"])
        self.assertFalse(result["automatic_policy_changes"])
        self.assertNotIn("private text", json.dumps(result))

    def test_duplicate_and_stale_events_do_not_become_recurring_memory(self):
        event = {"at": "2026-09-30T10:00:00+00:00", "loop": "topics", "action": "rollback", "keyword": "signal"}
        stale = {**event, "at": "2026-01-01T10:00:00+00:00"}
        result = support.consolidate_memory({}, [event, dict(event), stale], self.AT)
        self.assertEqual(result["unique_observations"], 1)
        self.assertEqual(result["ignored_stale_observations"], 1)
        self.assertEqual(result["recurring_patterns"], [])

    def test_rollbacks_for_different_topics_are_not_combined(self):
        ledger = [
            {"at": "2026-09-30T10:00:00+00:00", "loop": "topics", "action": "rollback", "topic": "A", "keyword": "signal"},
            {"at": "2026-10-01T09:00:00+00:00", "loop": "topics", "action": "rollback", "topic": "B", "keyword": "signal"},
        ]
        result = support.consolidate_memory({}, ledger, self.AT)
        self.assertEqual(result["unique_observations"], 2)
        self.assertEqual(result["recurring_patterns"], [])

    def test_future_unknown_and_unscoped_events_are_not_memory(self):
        ledger = [
            {"at": "2027-10-01T10:00:00+00:00", "loop": "topics", "action": "rollback", "keyword": "x"},
            {"at": "2026-09-30T10:00:00+00:00", "loop": "legal", "action": "rollback", "keyword": "x"},
            {"at": "not a date", "loop": "topics", "action": "rollback", "keyword": "x"},
        ]
        result = support.consolidate_memory({}, ledger, self.AT)
        self.assertEqual(result["unique_observations"], 0)

    def test_empty_memory_is_valid_and_deterministic(self):
        left = support.consolidate_memory({}, [], self.AT)
        right = support.consolidate_memory({}, [], self.AT)
        self.assertEqual(left, right)
        self.assertEqual(left["recurring_patterns"], [])


class WriteGuardTests(unittest.TestCase):
    def setup_paths(self):
        path, lock, tmp = MagicMock(), MagicMock(), MagicMock()
        path.name, path.suffix = "policy.json", ".json"
        path.with_suffix.side_effect = [lock, tmp]
        return path, lock, tmp

    def test_dry_run_never_touches_disk(self):
        path = MagicMock()
        support.guarded_save(path, {"ok": True}, True, expected_revision="old")
        self.assertEqual(path.mock_calls, [])

    def test_conflicting_revision_is_rejected_before_write(self):
        path, lock, tmp = self.setup_paths()
        with patch.object(support, "file_revision", return_value="changed"):
            with self.assertRaises(support.WriteConflict):
                support.guarded_save(path, {"ok": True}, False, expected_revision="original")
        tmp.write_text.assert_not_called()
        tmp.replace.assert_not_called()
        lock.unlink.assert_called_once_with(missing_ok=True)

    def test_lock_conflict_does_not_remove_other_writers_lock(self):
        path, lock, tmp = self.setup_paths()
        lock.open.side_effect = FileExistsError()
        with self.assertRaises(support.WriteConflict):
            support.guarded_save(path, {"ok": True}, False, expected_revision="original")
        lock.unlink.assert_not_called()
        tmp.write_text.assert_not_called()

    def test_matching_revision_writes_then_replaces_atomically(self):
        path, lock, tmp = self.setup_paths()
        with patch.object(support, "file_revision", return_value="original"):
            support.guarded_save(path, {"ok": True}, False, expected_revision="original")
        self.assertTrue(json.loads(tmp.write_text.call_args.args[0])["ok"])
        tmp.replace.assert_called_once_with(path)
        lock.unlink.assert_called_once_with(missing_ok=True)

    def test_snapshot_and_revision_use_same_raw_bytes(self):
        path = MagicMock()
        path.read_bytes.return_value = b'\xef\xbb\xbf{"version": 2}'
        value, revision = support.read_snapshot(path, {})
        self.assertEqual(value, {"version": 2})
        self.assertEqual(revision, support.file_revision(path))

    def test_missing_snapshot_has_explicit_missing_revision(self):
        path = MagicMock()
        path.read_bytes.side_effect = FileNotFoundError()
        self.assertEqual(support.read_snapshot(path, {}), ({}, "missing"))


@unittest.skipUnless(os.environ.get("SELF_IMPROVE_TEST_IO_DIR"), "optional sandbox IO fixture not configured")
class FileWriteGuardIntegration(unittest.TestCase):
    def test_existing_regressions_with_authorized_fixture_directories(self):
        # 일부 파일 샌드박스는 tempfile의 private-mode 새 폴더를 지원하지 않는다.
        # 호출자가 미리 준비한 허용 폴더만 쓴다. 기존 비즈니스 검증은 그대로 실행한다.
        import build_design_team as design
        base = Path(os.environ["SELF_IMPROVE_TEST_IO_DIR"])
        fixtures = [contextlib.nullcontext(str(base / name))
                    for name in ("legacy-sourcing", "legacy-design", "legacy-design-loop")]
        for name in ("legacy-sourcing", "legacy-design", "legacy-design-loop"):
            folder = base / name
            self.assertTrue(folder.is_dir(), "prepare authorized fixture folders before running")
            for previous_fixture in folder.iterdir():
                if previous_fixture.is_file():
                    previous_fixture.unlink()
        with patch("tempfile.TemporaryDirectory", side_effect=fixtures), \
             patch.object(graph, "_LEARNED", graph._LEARNED), \
             patch.object(design, "DESIGN_POLICY", design.DESIGN_POLICY), \
             patch.object(si, "DATA", si.DATA), \
             patch.object(si, "DESIGN_POLICY", si.DESIGN_POLICY):
            runpy.run_path(str(ROOT / "scripts" / "test_self_improve.py"))

    def test_real_file_roundtrip_and_stale_write_rejection(self):
        target = Path(os.environ["SELF_IMPROVE_TEST_IO_DIR"]) / "guard-fixture.json"
        target.unlink(missing_ok=True)
        before = support.file_revision(target)
        support.guarded_save(target, {"version": 1}, False, expected_revision=before)
        value, revision = support.read_snapshot(target, {})
        self.assertEqual(value, {"version": 1})
        with self.assertRaises(support.WriteConflict):
            support.guarded_save(target, {"version": 2}, False, expected_revision=before)
        self.assertEqual(support.read_snapshot(target, {})[0], {"version": 1})
        support.guarded_save(target, {"version": 2}, False, expected_revision=revision)
        self.assertEqual(support.read_snapshot(target, {})[0], {"version": 2})
        target.unlink()
        self.assertFalse(target.with_suffix(".json.lock").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
