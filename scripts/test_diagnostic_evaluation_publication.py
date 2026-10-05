"""Offline synthetic diagnostics; mocked HEAD, real publisher guard, no models."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import diagnostic_evaluation_history as evidence
from scripts import gemini_escalation as producer
from scripts import moe_evaluation_history as moe
from scripts.publish_transaction import overlay, PublishError, removed_identities


def baseline():
    return {'schema_version': 1, 'generated_at': '2026-01-01T00:00:00Z',
            'generator': 'scripts/gemini_escalation.py', 'policy': 'fixture',
            'enabled': True, 'free_tier_only': True, 'model': 'fixture',
            'max_calls_per_run': 1, 'max_output_tokens': 700,
            'advisory_only': True, 'paid_api_called': False,
            'canonical_gate_changed': False, 'external_action_executed': False,
            'call_count': 1, 'called': True, 'reasons': ['old-diagnostic'],
            'advice': {'diagnosis': 'fixture', 'checks': [{'id': 'old', 'fact': 1}]},
            'usage': {'tokens': 1}, 'error': '', 'policy_schema_version': 1,
            'status': 'advisory_ready'}


class DiagnosticPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT.parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = json.loads((ROOT / 'config/publish_policy.json').read_bytes())
        p = self.root / 'config/publish_policy.json'
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(self.policy), encoding='utf-8')
        self.old = baseline()
        self.base = (json.dumps(self.old, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
        self.current = deepcopy(self.old)
        self.current.update(advice=None, usage=None, reasons=[], called=False, call_count=0, status='not_needed')
        self.report = self.root / evidence.REPORT_PATH
        self.report.parent.mkdir(parents=True)
        self.report.write_bytes(self.base)
        head = patch.object(evidence, 'exact_head', return_value=self.base)
        head.start()
        self.addCleanup(head.stop)
        network = patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden'))
        network.start()
        self.addCleanup(network.stop)

    def publish(self):
        return evidence.publish_evaluation(self.root, self.current)

    def manifest(self):
        return json.loads((self.root / evidence.MANIFEST_PATH).read_bytes())

    def guarded(self, manifest, remote=None):
        return overlay(evidence.REPORT_PATH, self.base, self.report.read_bytes(),
                       self.base if remote is None else remote, self.policy, manifest)

    def test_correct_evidence_preserves_truthful_none_and_reasons(self):
        result = self.publish()
        self.assertEqual(json.loads(self.guarded(self.manifest())), self.current)
        self.assertIsNone(json.loads(self.report.read_bytes())['advice'])
        ids = removed_identities(self.old, self.current, self.policy, where=evidence.REPORT_PATH)
        self.assertEqual(result['removed_ids'], sorted(set(ids)))
        record = self.manifest()['deletions'][0]
        self.assertEqual(record['base_sha256'], evidence.sha(self.base))
        self.assertEqual(record['ids'], ['old-diagnostic'])
        self.assertFalse(record['delete_file'])

    def test_absent_wronghash_wrongids_deny(self):
        self.publish()
        wronghash = self.manifest()
        wronghash['deletions'][0]['base_sha256'] = '0' * 64
        wrongids = self.manifest()
        wrongids['deletions'][0]['ids'] = ['unrelated']
        for manifest in [None, {}, wronghash, wrongids]:
            with self.subTest(manifest=manifest), self.assertRaises(PublishError):
                self.guarded(manifest)

    def test_nested_diagnostic_removals_authorized_exactly(self):
        self.current['advice'] = {'checks': []}
        self.current['usage'] = {}
        result = self.publish()
        self.assertEqual(set(result['removed_ids']), {'old-diagnostic', 'old', 'diagnosis', 'tokens'})
        self.assertEqual(json.loads(self.guarded(self.manifest())), self.current)

    def test_exact_head_prior_current_cumulative_history_retained(self):
        prior = (json.dumps(self.old, indent=4) + '\n\n').encode()
        self.report.write_bytes(prior)
        cumulative = self.root / 'data/knowledge/cumulative_history.json'
        cumulative.parent.mkdir(parents=True)
        cumulative.write_bytes(b'{"events":[1]}\n')
        self.publish()
        first = self.report.read_bytes()
        self.current['reasons'] = ['new-diagnostic']
        self.publish()
        for value in [self.base, prior, first, self.report.read_bytes()]:
            self.assertEqual((self.root / evidence.HISTORY_PATH / (evidence.sha(value) + '.json')).read_bytes(), value)
        self.assertEqual(cumulative.read_bytes(), b'{"events":[1]}\n')
        history = self.root / evidence.HISTORY_PATH / (evidence.sha(self.base) + '.json')
        history.write_bytes(b'tampered')
        before = self.report.read_bytes()
        with self.assertRaisesRegex(ValueError, 'tampered'):
            self.publish()
        self.assertEqual(self.report.read_bytes(), before)

    def test_unrelated_manifest_records_and_metadata_retained(self):
        records = [{'path': 'data/other.json', 'ids': ['real'], 'note': {'keep': True}},
                   {'path': evidence.REPORT_PATH, 'policy_ref': 'other-policy', 'ids': ['other']}]
        p = self.root / evidence.MANIFEST_PATH
        p.write_text(json.dumps({'schema_version': 1, 'deletions': records, 'note': 'keep'}), encoding='utf-8')
        self.publish()
        self.publish()
        self.assertEqual(self.manifest()['deletions'][:2], records)
        self.assertEqual(len(self.manifest()['deletions']), 3)
        self.assertEqual(self.manifest()['note'], 'keep')

    def test_outside_field_identity_and_container_removals_deny(self):
        for change in ['root', 'allowed_root', 'nested', 'identity', 'container', 'collision']:
            old, current = baseline(), deepcopy(self.current)
            if change == 'root':
                del current['generator']
            elif change == 'allowed_root':
                del current['advice']
            elif change == 'nested':
                old['source'] = {'fact': True}
                current['source'] = {}
            elif change == 'identity':
                old['source'] = [{'id': 'real', 'fact': True}]
                current['source'] = []
            elif change == 'container':
                old['source'] = {'fact': True}
                current['source'] = None
            else:
                old['source'] = [{'id': 'old-diagnostic'}]
                current['source'] = []
            with self.subTest(change=change), self.assertRaises(ValueError):
                evidence.replacement_ids(old, current, self.policy)
        del self.current['generator']
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.report.read_bytes(), self.base)
        self.assertFalse((self.root / evidence.MANIFEST_PATH).exists())

    def test_flat_capacity_spills_without_pruning_or_reformatting(self):
        from scripts.immutable_snapshot_store import load_snapshots
        history = self.root / evidence.HISTORY_PATH
        history.mkdir()
        retained = {}
        for i in range(128):
            value = json.dumps({'fixture': i}).encode()
            retained[evidence.sha(value)] = value
            (history / (evidence.sha(value) + '.json')).write_bytes(value)
        self.publish()
        actual = load_snapshots(self.root, evidence.HISTORY_PATH)
        self.assertEqual({h:actual[h] for h in retained}, retained)
        self.assertEqual(len(list(history.glob('*.json'))), 128)
        self.assertGreater(len(actual), 128)
        self.assertEqual(json.loads(self.report.read_bytes()), self.current)
        self.assertTrue((self.root / evidence.MANIFEST_PATH).exists())

    def test_symlink_and_reparse_mocked_guards(self):
        original = Path.lstat
        targets = [self.report.parent, self.root / 'config/publish_policy.json']
        for target in targets:
            for kind in ['symlink', 'reparse']:
                def fake(p, *args, **kwargs):
                    result = original(p, *args, **kwargs)
                    if p == target:
                        return SimpleNamespace(st_mode=stat.S_IFLNK if kind == 'symlink' else result.st_mode,
                                               st_file_attributes=0x400 if kind == 'reparse' else 0)
                    return result
                with self.subTest(target=target, kind=kind), patch.object(Path, 'lstat', fake), self.assertRaises(ValueError):
                    self.publish()
        self.assertEqual(self.report.read_bytes(), self.base)

    def test_concurrent_report_manifest_and_head_change_denied(self):
        original = evidence.atomic_write
        for target in ['report', 'manifest', 'head']:
            changed = b'{"concurrent":true}\n'
            triggered = []
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

    def test_actual_guard_rejects_concurrent_changed_report(self):
        self.publish()
        remote = deepcopy(self.old)
        remote.update(status='other', reasons=['remote-diagnostic'], advice={'diagnosis': 'competing'})
        with self.assertRaises(PublishError):
            self.guarded(self.manifest(), json.dumps(remote).encode())

    def test_lock_immutable_write_and_noncanonical_deny(self):
        name = evidence.HISTORY_PATH + '/immutable.json'
        evidence.atomic_write(self.root, name, b'original', immutable=True)
        with self.assertRaises(ValueError):
            evidence.atomic_write(self.root, name, b'changed', immutable=True)
        with self.assertRaises(ValueError):
            evidence.publish_evaluation(self.root, self.current, 'data/other.json')
        (self.root / evidence.LOCK_PATH).write_bytes(b'')
        with self.assertRaises(FileExistsError):
            self.publish()

    def test_missing_head_is_error_not_production_fallback(self):
        with patch.object(evidence, 'exact_head', side_effect=ValueError('immutable HEAD report unavailable')), self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.report.read_bytes(), self.base)
        self.assertFalse((self.root / evidence.MANIFEST_PATH).exists())

    def test_exact_replacement_hash_blocks_later_edit_and_id_collision(self):
        self.old['advice']['generator'] = 'nested diagnostic'
        self.base = (json.dumps(self.old) + '\n').encode()
        evidence.exact_head.return_value = self.base
        self.report.write_bytes(self.base)
        self.current['advice'] = deepcopy(self.old['advice'])
        del self.current['advice']['generator']
        self.publish()
        manifest = self.manifest()
        self.assertIn('generator', manifest['deletions'][0]['ids'])
        self.assertEqual(manifest['deletions'][0]['replacement_sha256'], evidence.sha(self.report.read_bytes()))
        edited = json.loads(self.report.read_bytes())
        del edited['generator']
        with self.assertRaises(PublishError):
            overlay(evidence.REPORT_PATH, self.base, json.dumps(edited).encode(), self.base, self.policy, manifest)
        for variant in ['missing', 'wrong']:
            broken = deepcopy(manifest)
            if variant == 'missing':
                del broken['deletions'][0]['replacement_sha256']
            else:
                broken['deletions'][0]['replacement_sha256'] = '0' * 64
            with self.subTest(variant=variant), self.assertRaises(PublishError):
                self.guarded(broken)

    def test_bound_snapshot_cannot_authorize_different_merged_report(self):
        self.publish()
        remote = deepcopy(self.old)
        remote['error'] = 'concurrent diagnostic change'
        with self.assertRaisesRegex(PublishError, 'snapshot'):
            self.guarded(self.manifest(), json.dumps(remote).encode())

    def test_shared_manifest_lock_blocks_overlapping_moe_and_diagnostic_writers(self):
        moe_base = (json.dumps({'mean_gate_load': [0.4, 0.6], 'search_space': {'experts': [2, 3]}, 'effective': False}) + '\n').encode()
        moe_current = {'mean_gate_load': [0.2, 0.3, 0.5], 'search_space': {'experts': [3]}, 'effective': False}
        moe_report = self.root / moe.REPORT_PATH
        moe_report.parent.mkdir(parents=True, exist_ok=True)
        moe_report.write_bytes(moe_base)
        unrelated = {'path': 'data/other.json', 'ids': ['real'], 'note': 'retain'}
        self.assertEqual(evidence.LOCK_PATH, moe.LOCK_PATH)
        with patch.object(moe, 'exact_head', return_value=moe_base):
            for first in ['diagnostic', 'moe']:
                triggered = []
                (self.root / evidence.MANIFEST_PATH).write_text(json.dumps({'schema_version': 1, 'deletions': [unrelated]}), encoding='utf-8')
                module = evidence if first == 'diagnostic' else moe
                original = module.atomic_write
                def write(root, name, value, **kwargs):
                    if name == evidence.MANIFEST_PATH and not triggered:
                        triggered.append(True)
                        with self.assertRaises(FileExistsError):
                            if first == 'diagnostic':
                                moe.publish_evaluation(self.root, moe_current)
                            else:
                                self.publish()
                    return original(root, name, value, **kwargs)
                with self.subTest(first=first), patch.object(module, 'atomic_write', side_effect=write):
                    if first == 'diagnostic':
                        self.publish()
                    else:
                        moe.publish_evaluation(self.root, moe_current)
                if first == 'diagnostic':
                    moe.publish_evaluation(self.root, moe_current)
                else:
                    self.publish()
                records = self.manifest()['deletions']
                self.assertTrue(triggered)
                self.assertIn(unrelated, records)
                self.assertEqual({row['path'] for row in records}, {'data/other.json', evidence.REPORT_PATH, moe.REPORT_PATH})
                self.assertEqual(json.loads(self.guarded(self.manifest())), self.current)
                self.assertEqual(json.loads(overlay(moe.REPORT_PATH, moe_base, moe_report.read_bytes(), moe_base, self.policy, self.manifest())), moe_current)
                self.assertFalse((self.root / evidence.LOCK_PATH).exists())

    def test_direct_cli_saves_disabled_fixture_without_provider_calls(self):
        scripts = self.root / 'scripts'
        scripts.mkdir()
        for name in ['gemini_escalation.py', 'diagnostic_evaluation_history.py', 'moe_evaluation_history.py', 'publish_transaction.py', 'immutable_snapshot_store.py']:
            shutil.copyfile(ROOT / 'scripts' / name, scripts / name)
        (scripts / '__init__.py').write_text('', encoding='utf-8')
        hooks = self.root / 'empty-hooks'
        hooks.mkdir()
        git_env = {key: value for key, value in os.environ.items() if key.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'}}
        git_env['GIT_CONFIG_NOSYSTEM'] = '1'
        git_env['GIT_CONFIG_GLOBAL'] = os.devnull
        for args in [['init', '--quiet'], ['add', evidence.REPORT_PATH], ['-c', 'user.name=OfflineFixture', '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=' + str(hooks), 'commit', '--quiet', '-m', 'offline diagnostic fixture']]:
            subprocess.run(['git', '-C', str(self.root), *args], env=git_env, capture_output=True, check=True)
        env = dict(git_env, PYTHONUTF8='1', TYPESAFE_ENABLED='0', GEMINI_FALLBACK_ENABLED='0', GEMINI_FREE_TIER_ONLY='1')
        result = subprocess.run([sys.executable, '-E', '-X', 'utf8', '-B', 'scripts/gemini_escalation.py'], cwd=self.root, env=env, capture_output=True, check=True)
        self.assertIn(b'GEMINI_ESCALATION_SKIP disabled', result.stdout)
        actual = json.loads(self.report.read_bytes())
        self.assertEqual(actual['status'], 'disabled')
        self.assertFalse(actual['called'])
        self.assertEqual(actual['call_count'], 0)
        self.assertIsNone(actual['advice'])
        self.assertEqual(json.loads(self.guarded(self.manifest())), actual)

    def test_save_routes_to_helper_and_fixture_requires_explicit_patch(self):
        with patch.object(producer, 'ROOT', self.root), patch.object(producer, 'OUT', self.report):
            producer.save(self.current)
        self.assertEqual(json.loads(self.guarded(self.manifest())), self.current)
        # A no-Git/no-committed-report fixture must deliberately patch the helper.
        with patch.object(evidence, 'publish_evaluation') as helper, patch.object(producer, 'ROOT', self.root), patch.object(producer, 'OUT', self.report):
            producer.save(self.current)
        helper.assert_called_once_with(self.root, self.current, evidence.REPORT_PATH)


if __name__ == '__main__':
    unittest.main()
