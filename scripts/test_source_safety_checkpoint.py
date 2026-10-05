"""Offline fixtures only: no repository data, network, providers or receipts."""
import copy
import json
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import source_safety_checkpoint as s
from source_procedure_state import SourceProcedureStore


class SafetyCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'source'
        self.target = self.base / 'target'
        self.root.mkdir()
        self.archive = self.base / 'safety.zip'
        self.lineage = dict(repository='owner/repository', run_id='123', run_attempt='2', commit='a' * 40)
        self.expected = {'expected_' + k: v for k, v in self.lineage.items()}
        self.stamp = '2026-01-01T00:00:00+00:00'
        self.ledger = {'policy': dict(s.observer.POLICY), 'total_http_attempts': 1,
                       'last_run_attempt_at': self.stamp, 'last_request_at': self.stamp,
                       'last_checked_at': self.stamp,
                       'request_history': [{'sequence': 1, 'reserved_at': self.stamp, 'kind': 'product', 'pd_no': '1000000'}]}
        self.row = {'pd_no': '1000000', 'canonical_product_id': 'CP000001', 'price_krw': 5000,
                    'price_unit': 'product', 'source': {'url': s.observer.BASE + s.observer.SEARCH + '?searchTerm=1000000',
                    'collected_at': self.stamp, 'capture_kind': 'successful_http_parse'},
                    'provenance': {'http_status': 200, 'parse_status': 'exact_pd_no_numeric_price', 'endpoint': s.observer.BASE + s.observer.SEARCH}}
        self.doc = {'schema_version': 2, 'policy': dict(s.observer.POLICY), 'products': [self.row],
                    'capture_history': [], 'retained_previous_products': [], 'observation_history': [],
                    'attempts': [], 'http_attempt_count': 1, 'status': 'complete', 'budget_checkpoint': self.budget()}
        self.save(self.root, s.CLAIM, self.ledger)
        self.save(self.root, s.OBSERVATIONS, self.doc)
        self.store = SourceProcedureStore(self.root / Path(s.PROCEDURE).parent)
        self.save(self.root, s.CHECKPOINT, self.store.fresh_init(trusted_caller=True))
        # Any accidental collector/network entry fails the test immediately.
        self.net = patch.object(s.observer, '_http_get', side_effect=AssertionError('network forbidden'))
        self.net.start()
        self.addCleanup(self.net.stop)

    def budget(self):
        return {**{k: self.ledger[k] for k in ('total_http_attempts', 'last_run_attempt_at', 'last_request_at', 'last_checked_at')},
                'policy_version': 2, 'request_history_sha256': s.observer._history_digest(self.ledger['request_history'])}

    def save(self, root, rel, value):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value), encoding='utf-8')

    def pack(self):
        return s.pack(self.root, self.archive, **self.lineage)

    def restore(self):
        return s.restore(self.target, self.archive, **self.expected)

    def copy_current(self):
        self.target.mkdir(exist_ok=True)
        for rel, body in s._snapshot(self.root).items():
            p = self.target / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(body)

    def rewrite(self, transform, rehash=False):
        with zipfile.ZipFile(self.archive) as archive:
            files = {n: archive.read(n) for n in archive.namelist()}
        transform(files)
        if rehash:
            manifest = json.loads(files[s.MANIFEST])
            payload = {k: v for k, v in files.items() if k != s.MANIFEST}
            manifest['files'] = {k: {'sha256': s._sha(v), 'size': len(v)} for k, v in payload.items()}
            files[s.MANIFEST] = json.dumps(manifest).encode()
        with zipfile.ZipFile(self.archive, 'w') as archive:
            for name, body in files.items():
                archive.writestr(name, body)

    def test_roundtrip_exact_bytes_sha_manifest_source_clocks(self):
        before = s._snapshot(self.root)
        self.assertEqual(self.pack()['status'], 'packed')
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(set(archive.namelist()), {*s.ALLOWLIST, s.MANIFEST})
            manifest = json.loads(archive.read(s.MANIFEST))
            self.assertNotIn('generated_at', manifest)
            self.assertEqual(manifest['source_clocks']['capture_clocks'], [self.stamp])
            for rel, body in before.items():
                self.assertEqual(manifest['files'][rel]['sha256'], s._sha(body))
        self.assertEqual(self.restore()['status'], 'restored')
        self.assertEqual(s._snapshot(self.target), before)
        self.assertFalse((self.target / s.PENDING).exists())
        self.assertEqual(self.restore()['status'], 'unchanged')

    def test_hash_tamper_blocked_before_writes(self):
        self.pack()
        self.rewrite(lambda files: files.__setitem__(s.OBSERVATIONS, files[s.OBSERVATIONS] + b' '))
        with self.assertRaises(s.Blocked): self.restore()
        self.assertFalse(self.target.exists())

    def test_wrong_each_lineage_field_blocked(self):
        self.pack()
        for key, value in [('expected_repository', 'other/repository'), ('expected_run_id', '124'), ('expected_run_attempt', '3'), ('expected_commit', 'b' * 40)]:
            args = {**self.expected, key: value}
            with self.subTest(key=key), self.assertRaises(s.Blocked):
                s.restore(self.target, self.archive, **args)
        self.assertFalse(self.target.exists())

    def test_archive_authentication_flags_not_trusted(self):
        self.pack()
        def edit(files):
            manifest = json.loads(files[s.MANIFEST]); manifest['authenticated'] = True
            files[s.MANIFEST] = json.dumps(manifest).encode()
        self.rewrite(edit)
        with self.assertRaises(s.Blocked): self.restore()

    def test_zip_slip_and_private_extra_blocked(self):
        for name in ('../escape', '/absolute', 'data\\daiso_real\\shortlist_observations.json', 'private/secrets.json'):
            self.pack()
            self.rewrite(lambda files: files.__setitem__(name, b'{}'))
            with self.subTest(name=name), self.assertRaises(s.Blocked): self.restore()
        self.assertFalse((self.base / 'escape').exists())

    def test_archive_duplicate_and_symlink_entries_blocked(self):
        self.pack()
        with zipfile.ZipFile(self.archive, 'a') as archive:
            archive.writestr(s.CLAIM, b'{}')
        with self.assertRaises(s.Blocked): self.restore()
        self.pack()
        with zipfile.ZipFile(self.archive) as archive:
            files = {n: archive.read(n) for n in archive.namelist()}
        with zipfile.ZipFile(self.archive, 'w') as archive:
            for name, body in files.items():
                info = zipfile.ZipInfo(name)
                if name == s.CLAIM:
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, body)
        with self.assertRaises(s.Blocked): self.restore()

    def test_source_and_destination_symlinks_blocked(self):
        self.pack()
        self.copy_current()
        p = self.target / s.CLAIM
        p.unlink()
        try:
            p.symlink_to(self.root / s.CLAIM)
        except OSError:
            self.skipTest('symlink privilege unavailable')
        with self.assertRaises(s.Blocked): self.restore()
        with self.assertRaises(s.Blocked): s.pack(self.target, self.base / 'bad.zip', **self.lineage)

    def test_size_bounds(self):
        with patch.object(s, 'MAX_FILE_BYTES', 32), self.assertRaises(s.Blocked): self.pack()
        self.pack()
        with patch.object(s, 'MAX_FILES', 4), self.assertRaises(s.Blocked): self.restore()
        with patch.object(s, 'MAX_TOTAL_BYTES', 32), self.assertRaises(s.Blocked): self.restore()

    def test_missing_observer_pair_and_procedure_pair(self):
        for rel in (s.CLAIM, s.OBSERVATIONS, s.PROCEDURE, s.CHECKPOINT):
            body = (self.root / rel).read_bytes()
            (self.root / rel).unlink()
            with self.subTest(rel=rel), self.assertRaises(s.Blocked): self.pack()
            (self.root / rel).write_bytes(body)

    def test_legacy_not_migrated(self):
        self.ledger.pop('policy')
        self.save(self.root, s.CLAIM, self.ledger)
        before = (self.root / s.CLAIM).read_bytes()
        with self.assertRaises(s.Blocked): self.pack()
        self.assertEqual((self.root / s.CLAIM).read_bytes(), before)

    def test_counter_rollback_and_history_proof_conflict(self):
        self.ledger['total_http_attempts'] = 0
        self.save(self.root, s.CLAIM, self.ledger)
        with self.assertRaises(ValueError): self.pack()
        self.ledger['total_http_attempts'] = 1
        self.ledger['request_history'][0]['kind'] = 'changed'
        self.save(self.root, s.CLAIM, self.ledger)
        with self.assertRaises(ValueError): self.pack()

    def test_rehashed_malicious_history_fails_semantic_validation(self):
        self.pack()
        def edit(files):
            ledger = json.loads(files[s.CLAIM]); ledger['request_history'][0]['sequence'] = 2
            files[s.CLAIM] = json.dumps(ledger).encode()
        self.rewrite(edit, rehash=True)
        with self.assertRaises(ValueError): self.restore()

    def test_current_ahead_refused_without_reset(self):
        self.pack(); self.copy_current()
        ledger = copy.deepcopy(self.ledger)
        ledger['total_http_attempts'] = 2
        ledger['request_history'].append({'sequence': 2, 'reserved_at': self.stamp, 'kind': 'product'})
        self.save(self.target, s.CLAIM, ledger)
        before = s._snapshot(self.target)
        with self.assertRaises(s.Blocked): self.restore()
        self.assertEqual(s._snapshot(self.target), before)

    def test_current_history_conflict_refused(self):
        self.pack(); self.copy_current()
        ledger = copy.deepcopy(self.ledger); ledger['request_history'][0]['kind'] = 'different'
        doc = copy.deepcopy(self.doc); doc['budget_checkpoint']['request_history_sha256'] = s.observer._history_digest(ledger['request_history'])
        self.save(self.target, s.CLAIM, ledger); self.save(self.target, s.OBSERVATIONS, doc)
        with self.assertRaises(s.Blocked): self.restore()

    def test_capture_and_observation_history_loss_refused(self):
        self.pack(); self.copy_current()
        doc = copy.deepcopy(self.doc)
        extra = copy.deepcopy(self.row); extra['price_krw'] = 4000
        doc['capture_history'] = [extra]
        self.save(self.target, s.OBSERVATIONS, doc)
        with self.assertRaises(s.Blocked): self.restore()
        doc['capture_history'] = []
        doc['observation_history'] = [{'attempts': [], 'status': 'complete', 'budget_checkpoint': self.budget()}]
        self.save(self.target, s.OBSERVATIONS, doc)
        with self.assertRaises(s.Blocked): self.restore()

    def test_claimed_preserved_and_expected_checkpoint_exact(self):
        binding = dict(source_team='design', failure_fingerprint='b' * 64, fixedprocedure_id='design_source_observe')
        self.store.claim(binding, 'invocation-one', now=self.stamp)
        self.save(self.root, s.CHECKPOINT, self.store.checkpoint())
        original = (self.root / s.PROCEDURE).read_bytes()
        self.pack(); self.restore()
        self.assertEqual((self.target / s.PROCEDURE).read_bytes(), original)
        state = json.loads(original)
        self.assertEqual(state['teams']['design']['episodes'][0]['attempts'][0]['status'], 'CLAIMED')
        wrong = self.store.checkpoint(); wrong['revision'] += 1
        self.save(self.root, s.CHECKPOINT, wrong)
        with self.assertRaises(s.Blocked): self.pack()

    def test_current_procedure_ahead_and_ambiguous_loss(self):
        self.pack(); self.copy_current()
        store = SourceProcedureStore(self.target / Path(s.PROCEDURE).parent)
        store._expected = json.loads((self.target / s.CHECKPOINT).read_bytes())
        store.claim(dict(source_team='design', failure_fingerprint='b' * 64, fixedprocedure_id='design_source_observe'), 'later', now=self.stamp)
        self.save(self.target, s.CHECKPOINT, store.checkpoint())
        with self.assertRaises(s.Blocked): self.restore()
        (self.target / s.PROCEDURE).unlink()
        with self.assertRaises(s.Blocked): self.restore()
        (self.target / s.CHECKPOINT).unlink()
        with self.assertRaises(s.Blocked): self.restore()

    def test_procedure_pair_optional_only_both_absent(self):
        (self.root / s.PROCEDURE).unlink(); (self.root / s.CHECKPOINT).unlink()
        self.pack(); self.restore()
        self.assertEqual(set(s._snapshot(self.target)), {s.CLAIM, s.OBSERVATIONS})

    def test_interrupted_pair_transaction_failclosed(self):
        self.pack()
        replace = os.replace
        def interrupted(src, dst):
            if Path(dst) == self.target / s.OBSERVATIONS:
                raise OSError('simulated crash after durable ledger')
            return replace(src, dst)
        with patch.object(s.os, 'replace', side_effect=interrupted), self.assertRaises(OSError): self.restore()
        self.assertTrue((self.target / s.CLAIM).exists())
        self.assertTrue((self.target / s.PENDING).exists())
        with self.assertRaises(s.Blocked): self.restore()
        with self.assertRaises(s.Blocked): s.pack(self.target, self.base / 'retry.zip', **self.lineage)

    def test_reparse_point_detection_without_windows_privilege(self):
        original = Path.lstat
        redirect = self.root / 'data/daiso_real'
        def reparse(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == redirect:
                return s.SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info
        with patch.object(Path, 'lstat', reparse), self.assertRaises(s.Blocked): self.pack()

    def test_descendant_restores_preserving_lifetime_and_captures(self):
        self.copy_current()
        self.ledger['total_http_attempts'] = 2
        self.ledger['request_history'].append({'sequence': 2, 'reserved_at': self.stamp, 'kind': 'product'})
        self.doc['budget_checkpoint'] = self.budget()
        self.doc['capture_history'] = [copy.deepcopy(self.row)]
        self.save(self.root, s.CLAIM, self.ledger)
        self.save(self.root, s.OBSERVATIONS, self.doc)
        self.pack(); self.restore()
        restored = json.loads((self.target / s.CLAIM).read_bytes())
        self.assertEqual(restored['total_http_attempts'], 2)
        self.assertEqual(restored['request_history'][0]['sequence'], 1)
        self.assertEqual(s._snapshot(self.root), s._snapshot(self.target))

    def test_descendant_procedure_history_and_pending_claim_retained(self):
        self.copy_current()
        self.store.claim(dict(source_team='design', failure_fingerprint='b' * 64, fixedprocedure_id='design_source_observe'), 'new-claim', now=self.stamp)
        self.save(self.root, s.CHECKPOINT, self.store.checkpoint())
        self.pack(); self.restore()
        state = json.loads((self.target / s.PROCEDURE).read_bytes())
        self.assertEqual(state['teams']['design']['lifetime'], 1)
        self.assertEqual(state['teams']['design']['episodes'][0]['attempts'][0]['status'], 'CLAIMED')

    def test_generated_at_never_substitutes_for_source_clock(self):
        self.doc['generated_at'] = '2099-01-01T00:00:00+00:00'
        self.save(self.root, s.OBSERVATIONS, self.doc)
        self.pack()
        self.doc['products'][0]['source'].pop('collected_at')
        self.save(self.root, s.OBSERVATIONS, self.doc)
        with self.assertRaises(s.Blocked): self.pack()

    def test_unallowlisted_files_never_read_or_changed(self):
        private = self.root / 'data/private/secrets.json'
        private.parent.mkdir(parents=True)
        private.write_bytes(b'not-json-private-sentinel')
        self.pack(); self.restore()
        self.assertEqual(private.read_bytes(), b'not-json-private-sentinel')
        self.assertFalse((self.target / 'data/private').exists())

    def test_path_traversal_and_nonfinite_duplicate_json(self):
        with self.assertRaises(s.Blocked): s.pack(self.root / '..' / 'source', self.archive, **self.lineage)
        for bad in (b'{"a": 1, "a": 2}', b'{"a": NaN}'):
            with self.assertRaises(s.Blocked): s._json(bad)


if __name__ == '__main__':
    unittest.main()
