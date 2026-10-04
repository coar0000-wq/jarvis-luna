"""Offline producer evidence tests. No training, network, or git commits."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import moe_evaluation_history as evidence
from scripts.publish_transaction import overlay, PublishError, removed_identities

ROOT = Path(__file__).resolve().parents[1]


class EvaluationPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.policy = json.loads((ROOT / 'config/publish_policy.json').read_bytes())
        p = self.root / 'config/publish_policy.json'
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(self.policy), encoding='utf-8')
        result = subprocess.run(['git', '-C', str(ROOT), 'show', 'HEAD:' + evidence.REPORT_PATH], capture_output=True, check=True)
        self.base = result.stdout
        self.current = json.loads(self.base)
        self.current['mean_gate_load'] = [0.2, 0.3, 0.5]
        self.current['search_space']['experts'] = [4]
        self.current['effective'] = False
        self.report = self.root / evidence.REPORT_PATH
        self.report.parent.mkdir(parents=True)
        self.report.write_bytes(self.base)
        self.head = patch.object(evidence, 'exact_head', return_value=self.base)
        self.head.start()
        self.addCleanup(self.head.stop)

    def publish(self):
        return evidence.publish_evaluation(self.root, self.current)

    def manifest(self):
        return json.loads((self.root / evidence.MANIFEST_PATH).read_bytes())

    def test_correct_exact_evidence_passes_actual_guard_current_unchanged(self):
        result = self.publish()
        value = overlay(evidence.REPORT_PATH, self.base, self.report.read_bytes(), self.base, self.policy, self.manifest())
        self.assertEqual(json.loads(value), self.current)
        self.assertEqual(json.loads(value)['mean_gate_load'], [0.2, 0.3, 0.5])
        self.assertEqual(json.loads(value)['search_space']['experts'], [4])
        self.assertEqual(result['baseline_sha256'], evidence.sha(self.base))
        ids = removed_identities(json.loads(self.base), self.current, self.policy, where=evidence.REPORT_PATH)
        self.assertEqual(set(result['removed_ids']), set(ids))

    def test_bound_replacement_hash_rejects_later_outside_edit(self):
        self.publish()
        self.assertEqual(self.manifest()['deletions'][0]['replacement_sha256'], evidence.sha(self.report.read_bytes()))
        later = deepcopy(self.current)
        later['unexpected_after_evidence'] = True
        with self.assertRaises(PublishError):
            overlay(evidence.REPORT_PATH, self.base, json.dumps(later).encode(), self.base, self.policy, self.manifest())
        for variant in ['missing', 'wrong']:
            manifest = self.manifest()
            if variant == 'missing':
                del manifest['deletions'][0]['replacement_sha256']
            else:
                manifest['deletions'][0]['replacement_sha256'] = '0' * 64
            with self.subTest(variant=variant), self.assertRaises(PublishError):
                overlay(evidence.REPORT_PATH, self.base, self.report.read_bytes(), self.base, self.policy, manifest)

    def test_noncooperative_report_manifest_head_races_fail_closed(self):
        original = evidence.atomic_write
        for target in ['report', 'manifest', 'head']:
            triggered = []
            changed = b'{"concurrent":true}\n'
            def write(root, name, data, **kwargs):
                original(root, name, data, **kwargs)
                if kwargs.get('immutable') and not triggered:
                    triggered.append(True)
                    if target == 'report':
                        self.report.write_bytes(changed)
                    elif target == 'manifest':
                        (self.root / evidence.MANIFEST_PATH).write_bytes(changed)
                    else:
                        evidence.exact_head.return_value = changed
            with self.subTest(target=target), patch.object(evidence, 'atomic_write', side_effect=write), self.assertRaisesRegex(ValueError, 'concurrent'):
                self.publish()
            self.assertEqual(self.report.read_bytes(), changed if target == 'report' else self.base)
            self.report.write_bytes(self.base)
            (self.root / evidence.MANIFEST_PATH).unlink(missing_ok=True)
            evidence.exact_head.return_value = self.base

    def test_absent_wrong_base_wrong_ids_blocked(self):
        self.publish()
        policy = self.policy
        bad = [None, {'schema_version': 1, 'deletions': []}]
        wrong = self.manifest()
        wrong['deletions'][0]['base_sha256'] = '0' * 64
        bad.append(wrong)
        wrong = self.manifest()
        wrong['deletions'][0]['ids'] = ['not-an-actual-removal']
        bad.append(wrong)
        for manifest in bad:
            with self.subTest(manifest=manifest), self.assertRaises(PublishError):
                overlay(evidence.REPORT_PATH, self.base, self.report.read_bytes(), self.base, policy, manifest)

    def test_real_and_deep_expert_search_spaces_remain_exact(self):
        for experts in ([3], [3, 4]):
            with self.subTest(experts=experts):
                self.current['search_space']['experts'] = experts
                self.publish()
                value = overlay(evidence.REPORT_PATH, self.base, self.report.read_bytes(), self.base, self.policy, self.manifest())
                self.assertEqual(json.loads(value)['search_space']['experts'], experts)
                self.assertEqual(json.loads(value)['mean_gate_load'], self.current['mean_gate_load'])

    def test_baseline_current_and_cumulative_histories_immutable(self):
        cumulative = self.report.parent / 'cumulative_history.json'
        cumulative.write_bytes(b'{"real_events":[1]}\n')
        self.publish()
        first = self.report.read_bytes()
        self.current['mean_gate_load'] = [0.4, 0.2, 0.4]
        self.publish()
        history = self.root / evidence.HISTORY_PATH
        for value in [self.base, first, self.report.read_bytes()]:
            self.assertEqual((history / (evidence.sha(value) + '.json')).read_bytes(), value)
        self.assertEqual(cumulative.read_bytes(), b'{"real_events":[1]}\n')
        target = history / (evidence.sha(self.base) + '.json')
        target.write_bytes(b'tampered')
        before = self.report.read_bytes()
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.report.read_bytes(), before)

    def test_unrelated_manifest_records_preserved(self):
        unrelated = {'path': 'data/other.json', 'base_sha256': 'a'*64, 'ids': ['real-id'], 'reason': 'actual change', 'policy_ref': 'other-rule', 'extra': {'truth': False}}
        document = {'schema_version': 1, 'deletions': [unrelated], 'note': 'retain'}
        p = self.root / evidence.MANIFEST_PATH
        p.write_text(json.dumps(document), encoding='utf-8')
        self.publish()
        self.assertEqual(self.manifest()['deletions'][0], unrelated)
        self.assertEqual(self.manifest()['note'], 'retain')

    def test_unexpected_field_or_identity_removal_fails_even_same_numeric_id(self):
        for change in ('field', 'identity'):
            before = json.loads(self.base)
            after = deepcopy(self.current)
            if change == 'field':
                del after['note']
            else:
                before['observations'] = [{'id': '3', 'fact': 'real'}]
                after['observations'] = []
            with self.subTest(change=change), self.assertRaises(ValueError):
                evidence.replacement_ids(before, after, self.policy)
        del self.current['note']
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.report.read_bytes(), self.base)

    def test_concurrent_evaluation_publisher_conflict(self):
        self.publish()
        remote = json.loads(self.base)
        remote['mean_gate_load'] = [0.1, 0.1, 0.8]
        remote['effective'] = True
        with self.assertRaises(PublishError):
            overlay(evidence.REPORT_PATH, self.base, self.report.read_bytes(), json.dumps(remote).encode(), self.policy, self.manifest())

    def test_symlink_history_denied(self):
        outside = self.root / 'outside'
        outside.mkdir()
        history = self.root / evidence.HISTORY_PATH
        try:
            history.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Windows symlink privilege unavailable')
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.report.read_bytes(), self.base)
        self.assertEqual(list(outside.iterdir()), [])

    def test_reparse_point_guard_mocked(self):
        original = Path.lstat
        def fake(p, *args, **kwargs):
            result = original(p, *args, **kwargs)
            if p == self.report.parent:
                from types import SimpleNamespace
                return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
            return result
        with patch.object(Path, 'lstat', fake), self.assertRaises(ValueError):
            self.publish()

    def test_policy_reparse_point_denied_before_read(self):
        original = Path.lstat
        def fake(p, *args, **kwargs):
            result = original(p, *args, **kwargs)
            if p == self.root / 'config/publish_policy.json':
                from types import SimpleNamespace
                return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
            return result
        with patch.object(Path, 'lstat', fake), self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.report.read_bytes(), self.base)
        self.assertFalse((self.root / evidence.MANIFEST_PATH).exists())

    def test_overflow_fail_closed_without_pruning(self):
        history = self.root / evidence.HISTORY_PATH
        history.mkdir()
        for i in range(128):
            value = json.dumps({'retained_evaluation': i}).encode()
            (history / (evidence.sha(value) + '.json')).write_bytes(value)
        with self.assertRaisesRegex(ValueError, 'capacity'):
            self.publish()
        self.assertEqual(len(list(history.iterdir())), 128)
        self.assertEqual(self.report.read_bytes(), self.base)
        self.assertFalse((self.root / evidence.MANIFEST_PATH).exists())

    def test_immutable_write_and_concurrent_producer_lock_fail_closed(self):
        name = evidence.HISTORY_PATH + '/immutable.json'
        evidence.atomic_write(self.root, name, b'original', immutable=True)
        with self.assertRaises(ValueError):
            evidence.atomic_write(self.root, name, b'changed', immutable=True)
        self.assertEqual((self.root/name).read_bytes(), b'original')
        (self.root / evidence.LOCK_PATH).write_bytes(b'')
        with self.assertRaises(FileExistsError):
            self.publish()
        self.assertEqual(self.report.read_bytes(), self.base)


if __name__ == '__main__':
    unittest.main()
