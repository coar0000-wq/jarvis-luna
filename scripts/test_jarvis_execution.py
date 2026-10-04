"""Offline adversarial tests. All mutations are isolated temp fixtures."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jarvis_execution as ex


NOW = '2026-10-03T12:00:00+00:00'
FUTURE = '2026-10-03T13:00:00+00:00'


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = {}
        self.saved = []
        self.task = {'id': 't-one', 'team': 'legal', 'kind': 'snapshot_report', 'payload': {}}
        source = self.root / ex.SOURCES['legal']
        source.parent.mkdir(parents=True)
        source.write_text(json.dumps({'captured_at': NOW, 'salesAllowed': False, 'blockers': ['RP label missing']}))

    def persist(self, value):
        self.saved.append(copy.deepcopy(value))

    def run_task(self, task=None, **kwargs):
        return ex.execute(self.root, task or self.task, self.ledger, now=NOW, persist=self.persist, **kwargs)

    def approval(self):
        task = {**self.task, 'expires_at': FUTURE, 'nonce': 'dummy-nonce'}
        action = ex.make_action(task)
        claims = ex._plain(action)
        claims.update(human_verified=True, revoked=False, replayed=False, approval_id='dummy-human')
        return task, action, claims

    def test_actual_report_hash_scope_and_metadata(self):
        original = (self.root / ex.SOURCES['legal']).read_bytes()
        receipt = self.run_task()
        self.assertEqual(receipt['status'], 'VERIFIED')
        self.assertEqual(receipt['outputs'], receipt['output_evidence'])
        self.assertEqual(receipt['issuer'], 'jarvis-execution-v1')
        self.assertTrue(ex.validate_receipt(self.root, receipt, self.ledger))
        output = receipt['output_evidence'][0]
        report = json.loads((self.root / output['path']).read_text())
        self.assertIsNone(report['confidence'])
        self.assertFalse(report['business_clearance'])
        self.assertEqual(report['sources'][0]['freshness'], 'fresh')
        self.assertEqual(original, (self.root / ex.SOURCES['legal']).read_bytes())
        self.assertEqual(self.saved[0]['claims']['t-one']['status'], 'CLAIMED')
        self.assertEqual(receipt['payload_hash'], ex.digest(self.task['payload']))

    def test_registry_and_action_deep_immutable(self):
        with self.assertRaises(TypeError):
            ex.REGISTRY['snapshot_report']['level'] = 4
        action = ex.make_action({**self.task, 'payload': {'canonical_members': ['abc']}})
        with self.assertRaises(TypeError):
            action['payload']['x'] = 3
        with self.assertRaises(TypeError):
            action['canonical_members'][0] = 'mutated'

    def test_no_persistence_no_dispatch(self):
        receipt = ex.execute(self.root, self.task, {})
        self.assertEqual(receipt['status'], 'BLOCKED')
        self.assertFalse((self.root / 'data/operations').exists())

    def test_forged_approved_boolean_rejected(self):
        self.assertEqual(self.run_task(approval={'approved': True})['status'], 'BLOCKED')
        _, action, _ = self.approval()
        with self.assertRaises(ValueError):
            ex.verify_approval(action, {'approved': True}, verifier=lambda a, p: True, now=NOW)

    def test_trusted_complete_claims_only(self):
        _, action, claims = self.approval()
        result = ex.verify_approval(action, {}, verifier=lambda a, p: claims, now=NOW)
        self.assertEqual(result['approval_id'], 'dummy-human')
        with self.assertRaises(ValueError):
            ex.verify_approval(action, claims, now=NOW)

    def test_target_payload_and_binding_mutations(self):
        _, action, claims = self.approval()
        for key, value in [('target', 'other'), ('payload', {'x': 4}), ('policy_hash', 'bad'),
                           ('canonical_members', ['another']), ('preconditions', {'etag': 'changed'}),
                           ('evidence_version', 'changed')]:
            with self.subTest(key=key):
                tampered = ex._plain(action)
                tampered[key] = value
                with self.assertRaises(ValueError):
                    ex.verify_approval(tampered, {}, verifier=lambda a, p: claims, now=NOW)
                tampered['action_hash'] = ex.digest({k: v for k, v in tampered.items() if k != 'action_hash'})
                with self.assertRaises(ValueError):
                    ex.verify_approval(tampered, {}, verifier=lambda a, p: claims, now=NOW)

    def test_missing_nonce_expiry_and_revocation_replay(self):
        _, action, claims = self.approval()
        for key, value in [('nonce', None), ('expires_at', None), ('expires_at', NOW),
                           ('revoked', True), ('replayed', True), ('human_verified', False)]:
            invalid = {**claims, key: value}
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                ex.verify_approval(action, {}, verifier=lambda a, p: invalid, now=NOW)
        for key in ('nonce', 'expires_at', 'revoked', 'replayed'):
            invalid = dict(claims)
            del invalid[key]
            with self.assertRaises(ValueError):
                ex.verify_approval(action, {}, verifier=lambda a, p: invalid, now=NOW)

    def test_path_traversals(self):
        for target in ('../outside.json', '/tmp/report.json', 'data/operations/reports/../stock.json',
                       'data/operations/reports/a/b.json', 'data/operations/reports\\x.json',
                       'C:/report.json', 'data/products.json', 'data/operations/reports/.execution-ledger.json'):
            with self.subTest(target=target):
                receipt = self.run_task({**self.task, 'target': target})
                self.assertEqual(receipt['status'], 'BLOCKED')
        self.assertFalse(self.ledger['claims'])

    def test_symlink_escape(self):
        outside = self.root / 'outside'
        outside.mkdir()
        op = self.root / 'data/operations'
        op.mkdir()
        try:
            (op / 'reports').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('platform does not permit test symlinks')
        self.assertEqual(self.run_task()['status'], 'BLOCKED')
        self.assertFalse(list(outside.iterdir()))

    def test_symlink_guard_without_os_privilege(self):
        original = Path.is_symlink
        def pretend_link(p):
            return p.name == 'reports' or original(p)
        with patch.object(Path, 'is_symlink', pretend_link):
            self.assertEqual(self.run_task()['status'], 'BLOCKED')
        self.assertFalse((self.root / 'data/operations').exists())

    def test_duplicate_returns_prior_without_dispatch(self):
        first = self.run_task()
        with patch.object(ex, '_snapshot', side_effect=AssertionError('duplicate dispatch')):
            second = self.run_task()
        self.assertEqual(first, second)
        self.assertEqual(len(self.saved), 2)

    def test_changed_payload_invalidates_key_global_stop(self):
        first = self.run_task()
        second = self.run_task({**self.task, 'payload': {'x': 'changed'}})
        self.assertEqual(second['status'], 'RECONCILIATION_REQUIRED')
        self.assertTrue(self.ledger['global_stop'])
        self.assertFalse(ex.validate_receipt(self.root, first, self.ledger))
        self.assertEqual(self.run_task({**self.task, 'id': 'new'})['status'], 'RECONCILIATION_REQUIRED')

    def test_changed_output_blocks_replay(self):
        first = self.run_task()
        (self.root / first['target']).write_text('{}')
        self.assertFalse(ex.validate_receipt(self.root, first, self.ledger))
        self.assertEqual(self.run_task()['status'], 'RECONCILIATION_REQUIRED')

    def test_crash_after_claim_never_replays_even_different_key(self):
        class Crash(BaseException):
            pass
        with patch.object(ex, '_snapshot', side_effect=Crash):
            with self.assertRaises(Crash):
                self.run_task()
        self.assertEqual(self.saved[-1]['claims']['t-one']['status'], 'CLAIMED')
        self.ledger = copy.deepcopy(self.saved[-1])
        with patch.object(ex, '_snapshot', side_effect=AssertionError('redispatched')):
            self.assertEqual(self.run_task({**self.task, 'id': 'different'})['status'], 'RECONCILIATION_REQUIRED')
        self.assertTrue(self.ledger['global_stop'])
        self.assertIn('t-one', self.ledger['action_stops'])

    def test_failed_claim_persistence_never_dispatches(self):
        with patch.object(ex, '_snapshot', side_effect=AssertionError('dispatch without persistence')):
            receipt = ex.execute(self.root, self.task, self.ledger,
                                 persist=lambda _: (_ for _ in ()).throw(OSError('disk unavailable')))
        self.assertEqual(receipt['status'], 'RECONCILIATION_REQUIRED')
        self.assertFalse((self.root / 'data/operations').exists())

    def test_ambiguous_receipt_commit_no_retry(self):
        saves = []
        def persist(data):
            saves.append(copy.deepcopy(data))
            if len(saves) > 1:
                raise OSError('fsync failed')
        receipt = ex.execute(self.root, self.task, self.ledger, persist=persist, now=NOW)
        self.assertEqual(receipt['status'], 'RECONCILIATION_REQUIRED')
        self.assertTrue(self.ledger['global_stop'])
        self.assertEqual(len(list((self.root / 'data/operations/reports').glob('*.json'))), 1)

    def test_l4_and_l3_disabled_arbitrary_adapter_never_called(self):
        def bad_adapter(*args):
            raise AssertionError('adapter must never run')
        for kind, policy in ex.REGISTRY.items():
            if policy['level'] >= 3:
                task = {**self.task, 'kind': kind, 'level': 1, 'target': 'fake'}
                self.assertEqual(self.run_task(task, adapter=bad_adapter)['status'], 'BLOCKED')
                self.assertEqual(self.run_task(task)['status'], 'BLOCKED')
        self.assertEqual(self.run_task(adapter=bad_adapter)['status'], 'BLOCKED')

    def test_unknown_kind_and_team_blocked(self):
        self.assertEqual(self.run_task({**self.task, 'kind': 'run_shell'})['status'], 'BLOCKED')
        self.assertEqual(self.run_task({**self.task, 'team': 'new_agent'})['status'], 'BLOCKED')

    def test_stale_missing_unknown_confidence(self):
        source = self.root / ex.SOURCES['legal']
        source.write_text(json.dumps({'captured_at': '2020-01-01T00:00:00Z'}))
        receipt = self.run_task({**self.task, 'payload': {'teams': ['legal', 'market']}})
        self.assertEqual(receipt['status'], 'VERIFIED')
        self.assertEqual(receipt['source_evidence'][0]['freshness'], 'stale')
        self.assertIn('source_missing', receipt['source_evidence'][1]['blockers'])
        self.assertIsNone(receipt['confidence'])
        self.assertFalse(receipt['business_clearance'])

    def test_source_clock_not_fabricated(self):
        (self.root / ex.SOURCES['legal']).write_text(json.dumps({'generated_at': NOW, 'updated_at': NOW, 'team': {'updated_at': NOW}}))
        receipt = self.run_task()
        evidence = receipt['source_evidence'][0]
        self.assertIsNone(evidence['captured_at'])
        self.assertEqual(evidence['freshness'], 'unknown')

    def test_store_persistence_and_receipt_validation(self):
        store = ex.ExecutionStore(self.root)
        receipt = ex.execute(self.root, self.task, store, now=NOW)
        self.assertEqual(receipt['status'], 'VERIFIED')
        self.assertTrue(ex.validate_receipt(self.root, receipt))
        self.assertEqual(receipt, ex.execute(self.root, self.task, store, now=NOW))
        self.assertFalse((self.root / store.lockname).exists())

    def test_store_stale_lock_is_global_stop(self):
        lock = self.root / ex.ExecutionStore.lockname
        lock.parent.mkdir(parents=True)
        lock.write_text('previous process')
        self.assertEqual(ex.execute(self.root, self.task, ex.ExecutionStore(self.root))['status'], 'RECONCILIATION_REQUIRED')

    def test_forged_receipt_flags_not_authority(self):
        receipt = self.run_task()
        self.assertFalse(ex.validate_receipt(self.root, receipt, {}))
        forged = {**receipt, 'payload_hash': 'forged', 'verified': True}
        forged['receipt_hash'] = ex.digest({k: v for k, v in forged.items() if k != 'receipt_hash'})
        self.assertFalse(ex.validate_receipt(self.root, forged, self.ledger))

    def test_idempotent_local_read_retry_only_once(self):
        task = {**self.task, 'kind': 'read_snapshot'}
        original = Path.read_bytes
        calls = []
        def interrupted_once(p):
            calls.append(p)
            if len(calls) == 1:
                raise InterruptedError()
            return original(p)
        with patch.object(Path, 'read_bytes', interrupted_once):
            receipt = self.run_task(task)
        self.assertEqual(receipt['status'], 'VERIFIED')
        self.assertTrue(ex.validate_receipt(self.root, receipt, self.ledger))
        self.assertEqual(len(calls), 3)  # two read attempts plus output hash revalidation

    def test_write_never_retried(self):
        with patch.object(ex, '_atomic', side_effect=InterruptedError()) as call:
            self.assertEqual(self.run_task()['status'], 'RECONCILIATION_REQUIRED')
            self.assertEqual(call.call_count, 1)

    def test_auth_quota_never_retried(self):
        for status in (401, 402, 403, 429):
            self.ledger = {}
            with patch.object(Path, 'read_bytes', side_effect=OSError(str(status))) as call:
                self.assertEqual(self.run_task({**self.task, 'kind': 'read_snapshot'})['status'], 'RECONCILIATION_REQUIRED')
                self.assertEqual(call.call_count, 1)

    def test_no_network_or_subprocess(self):
        with patch('socket.socket', side_effect=AssertionError('network forbidden')), \
             patch('subprocess.Popen', side_effect=AssertionError('process forbidden')):
            self.assertEqual(self.run_task()['status'], 'VERIFIED')

    def test_nan_rejected(self):
        self.assertEqual(self.run_task({**self.task, 'payload': {'price': float('nan')}})['status'], 'BLOCKED')


if __name__ == '__main__':
    unittest.main()
