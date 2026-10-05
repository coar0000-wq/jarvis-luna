"""Offline exact-byte, bounded spill and publication fixtures; no external calls."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import immutable_snapshot_store as store
from scripts import workflow_status_history as workflow
from scripts import moe_evaluation_history as moe
from scripts import diagnostic_evaluation_history as diagnostic
from scripts import gosi_observation_history as gosi
from scripts.publish_transaction import overlay, PublishError


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def exact(i):
    return (' {"fixture" : %d, "text":"보존"}\n\n' % i).encode('utf-8')


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.name = workflow.HISTORY_PATH

    def test_path_and_fd_ctime_domains_preserved_independently(self):
        raw=exact(7); self.seed([raw]); original=os.fstat
        def domain(fd):
            info=original(fd)
            values={k:getattr(info,k) for k in dir(info) if k.startswith('st_')}
            values['st_ctime_ns'] += 1
            return SimpleNamespace(**values)
        with patch.object(store.os,'fstat',side_effect=domain):
            self.assertEqual(store.load_snapshots(self.root,self.name),{sha(raw):raw})
        calls=[]
        def changed(fd):
            info=original(fd); calls.append(fd)
            values={k:getattr(info,k) for k in dir(info) if k.startswith('st_')}
            values['st_ctime_ns'] += len(calls)
            return SimpleNamespace(**values)
        with patch.object(store.os,'fstat',side_effect=changed),self.assertRaisesRegex(ValueError,'concurrent'):
            store.load_snapshots(self.root,self.name)

    def seed(self, values, prefix=None):
        directory = self.root / self.name
        if prefix is not None:
            directory /= prefix
        directory.mkdir(parents=True, exist_ok=True)
        for raw in values:
            (directory / (sha(raw) + '.json')).write_bytes(raw)
        return directory

    def test_legacy128_spills_and_preserves_every_exact_byte(self):
        legacy = {sha(exact(i)): exact(i) for i in range(128)}
        flat = self.seed(legacy.values())
        additions = {sha(exact(i)): exact(i) for i in range(128, 300)}
        names = store.retain_snapshots(self.root, self.name, additions)
        for digest, name in names.items():
            self.assertEqual(name, self.name + '/' + digest[:2] + '/' + digest + '.json')
        self.assertEqual(store.load_snapshots(self.root, self.name), dict(legacy, **additions))
        self.assertEqual(len([p for p in flat.iterdir() if p.is_file()]), 128)
        for digest, raw in legacy.items():
            self.assertEqual((flat / (digest + '.json')).read_bytes(), raw)
        before = {p.relative_to(self.root): p.read_bytes() for p in flat.rglob('*.json')}
        store.retain_snapshots(self.root, self.name, dict(legacy, **additions))
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in flat.rglob('*.json')})

    def test_pipeline_reader_loads_validated_flat_and_sharded_workflow_bytes(self):
        from scripts import daiso_pipeline_inputs as inputs
        values = {sha(exact(i)): exact(i) for i in range(140)}
        store.retain_snapshots(self.root, self.name, values)
        with patch.object(inputs, 'evaluate_pipeline_health', return_value={}) as evaluate, patch.object(inputs, 'assess_collection', return_value={}):
            health = inputs.load_pipeline_inputs(self.root, now='2026-10-03T12:00:00Z', workflow_report={})
        loaded = evaluate.call_args.kwargs['workflow_history']
        self.assertEqual(loaded, [json.loads(values[digest]) for digest in sorted(values)])
        self.assertEqual(len(loaded), 140)
        self.assertFalse(any('history' in error for error in health['input_errors']))
        digest = next(d for d in sorted(values) if (self.root / self.name / d[:2] / (d + '.json')).exists())
        (self.root / self.name / digest[:2] / (digest + '.json')).write_bytes(b'tampered')
        with patch.object(inputs, 'evaluate_pipeline_health', return_value={}) as evaluate, patch.object(inputs, 'assess_collection', return_value={}):
            health = inputs.load_pipeline_inputs(self.root, now='2026-10-03T12:00:00Z', workflow_report={})
        self.assertEqual(evaluate.call_args.kwargs['workflow_history'], [])
        self.assertTrue(any('tampered' in error for error in health['input_errors']))

    def test_hash_whitelist_and_size_bindings_fail_before_write(self):
        for name in ('data/agents/daiso_pipeline_history', '../escape', self.name + '/00'):
            with self.assertRaisesRegex(ValueError, 'whitelist'):
                store.retain_snapshots(self.root, name, {sha(b'{}'): b'{}'})
        for retained in ({'0' * 64: b'{}'}, {sha(b'{}').upper(): b'{}'}, {sha(b'{}'): '{}'}):
            with self.assertRaises(ValueError):
                store.retain_snapshots(self.root, self.name, retained)
        with patch.object(store, 'MAX_BYTES', 3), self.assertRaises(ValueError):
            store.retain_snapshots(self.root, self.name, {sha(b'1234'): b'1234'})
        self.assertFalse((self.root / self.name).exists())
        self.seed([b'1234'])
        with patch.object(store, 'MAX_BYTES', 3), self.assertRaisesRegex(ValueError, 'size'):
            store.load_snapshots(self.root, self.name)

    def test_tampered_history_cannot_admit_or_reformat(self):
        raw = exact(1)
        directory = self.seed([raw])
        target = directory / (sha(raw) + '.json')
        target.write_bytes(raw + b' ')
        with self.assertRaisesRegex(ValueError, 'tampered'):
            store.retain_snapshots(self.root, self.name, {sha(exact(2)): exact(2)})
        self.assertEqual(target.read_bytes(), raw + b' ')
        self.assertEqual(len(list(directory.iterdir())), 1)

    def test_wrong_shard_bad_filename_nested_directory_duplicate_fail(self):
        raw = exact(1)
        for case in ('shard', 'name', 'nested', 'duplicate'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                history = root / self.name
                history.mkdir(parents=True)
                if case == 'shard':
                    prefix = '00' if sha(raw)[:2] != '00' else '01'
                    (history / prefix).mkdir()
                    (history / prefix / (sha(raw) + '.json')).write_bytes(raw)
                elif case == 'name':
                    (history / (sha(raw).upper() + '.json')).write_bytes(raw)
                elif case == 'nested':
                    (history / '00' / '00').mkdir(parents=True)
                else:
                    (history / (sha(raw) + '.json')).write_bytes(raw)
                    (history / sha(raw)[:2]).mkdir()
                    (history / sha(raw)[:2] / (sha(raw) + '.json')).write_bytes(raw)
                with self.assertRaises(ValueError):
                    store.load_snapshots(root, self.name)

    def test_file_and_directory_symlink_reparse_guards(self):
        directory = self.seed([exact(1)])
        target = directory / (sha(exact(1)) + '.json')
        original = Path.lstat
        for denied in (directory, target):
            for kind in ('symlink', 'reparse'):
                def fake(p, *args, **kwargs):
                    info = original(p, *args, **kwargs)
                    if p == denied:
                        return SimpleNamespace(st_mode=stat.S_IFLNK if kind == 'symlink' else info.st_mode,
                                               st_file_attributes=0x400 if kind == 'reparse' else 0)
                    return info
                with self.subTest(denied=denied, kind=kind), patch.object(Path, 'lstat', fake), self.assertRaisesRegex(ValueError, 'symlink/reparse'):
                    store.load_snapshots(self.root, self.name)

    def test_hard_link_snapshot_rejected(self):
        directory = self.seed([exact(1)])
        target = directory / (sha(exact(1)) + '.json')
        os.link(target, self.root / 'linked-outside-history')
        with self.assertRaisesRegex(ValueError, 'non-linked'):
            store.load_snapshots(self.root, self.name)

    def test_full_shard_preflights_whole_batch_without_overflow_or_drop(self):
        self.seed(exact(i) for i in range(128))
        values = []
        i = 1000
        while len(values) < 129:
            raw = exact(i)
            if sha(raw).startswith('00'):
                values.append(raw)
            i += 1
        shard = self.seed(values[:128], '00')
        before = store.load_snapshots(self.root, self.name)
        other = exact(-1)
        self.assertNotEqual(sha(other)[:2], '00')
        with self.assertRaisesRegex(ValueError, 'capacity'):
            store.retain_snapshots(self.root, self.name, {sha(values[-1]): values[-1], sha(other): other})
        self.assertEqual(store.load_snapshots(self.root, self.name), before)
        self.assertEqual(len(list(shard.iterdir())), 128)
        self.assertEqual(len(before), 256)
        store.retain_snapshots(self.root, self.name, {sha(values[0]): values[0]})
        self.assertEqual(store.load_snapshots(self.root, self.name), before)
        (shard / (sha(values[-1]) + '.json')).write_bytes(values[-1])
        with self.assertRaisesRegex(ValueError, 'capacity'):
            store.load_snapshots(self.root, self.name)

    def test_overfull_legacy_flat_fails_without_migration(self):
        directory = self.seed(exact(i) for i in range(129))
        with self.assertRaisesRegex(ValueError, 'capacity'):
            store.retain_snapshots(self.root, self.name, {})
        self.assertEqual(len(list(directory.iterdir())), 129)
        self.assertTrue(all(p.is_file() for p in directory.iterdir()))
        self.assertEqual(store.MAX_ENTRIES, 128)
        self.assertEqual(store.MAX_SHARDS, 256)


class PublisherSpillTests(unittest.TestCase):
    def test_all_four_publishers_retain_head_prior_current_and_unrelated_manifest(self):
        fixtures = [
            (workflow, 'publish_workflow_report',
             {'schema_version': 1, 'workflows': {'fixture': {'latest_attempt': None, 'last_success': None, 'validation_warnings': ['old']}}},
             lambda doc: doc['workflows']['fixture'].update(validation_warnings=[])),
            (moe, 'publish_evaluation',
             {'mean_gate_load': [0.2, 0.8], 'search_space': {'experts': [2, 3]}, 'semantic': ['keep']},
             lambda doc: doc.update(mean_gate_load=[0.3, 0.7], search_space={'experts': [3]})),
            (diagnostic, 'publish_evaluation',
             {'reasons': ['old'], 'advice': {}, 'usage': {}, 'semantic': ['keep']},
             lambda doc: doc.update(reasons=[], advice=None, usage=None)),
            (gosi, 'publish_observation',
             {'items': {'1': {'product_id': '1', 'maker': 'keep', '텍스트_미수집': ['ingredients']}}, 'vision_deferred': ['old']},
             lambda doc: doc.update(vision_deferred=[])),
        ]
        for module, function, baseline, mutate in fixtures:
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                policy = {'identity_fields': ['id']}
                policy_path = root / 'config/publish_policy.json'
                policy_path.parent.mkdir()
                policy_path.write_bytes(json.dumps(policy).encode())
                report = root / module.REPORT_PATH
                report.parent.mkdir(parents=True, exist_ok=True)
                base = (json.dumps(baseline, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
                prior = (json.dumps(baseline, ensure_ascii=False, indent=4) + '\n\n').encode()
                report.write_bytes(prior)
                history = root / module.HISTORY_PATH
                history.mkdir(parents=True)
                legacy = {sha(exact(i)): exact(i) for i in range(128)}
                for digest, raw in legacy.items():
                    (history / (digest + '.json')).write_bytes(raw)
                unrelated = {'path': 'data/other.json', 'ids': ['retain'], 'note': {'unchanged': True}}
                manifest_path = root / module.MANIFEST_PATH
                manifest_path.write_bytes(json.dumps({'schema_version': 1, 'deletions': [unrelated], 'note': 'keep'}).encode())
                current = deepcopy(baseline)
                mutate(current)
                with patch.object(module, 'exact_head', return_value=base):
                    evidence = getattr(module, function)(root, current)
                raw_current = report.read_bytes()
                stored = store.load_snapshots(root, module.HISTORY_PATH)
                self.assertEqual(stored, dict(legacy, **{sha(raw): raw for raw in (base, prior, raw_current)}))
                self.assertEqual(len(stored), 131)
                for digest, raw in legacy.items():
                    self.assertEqual((history / (digest + '.json')).read_bytes(), raw)
                manifest = json.loads(manifest_path.read_bytes())
                self.assertEqual(manifest['deletions'][0], unrelated)
                self.assertEqual(manifest['note'], 'keep')
                self.assertEqual(manifest['deletions'][-1]['replacement_sha256'], sha(raw_current))
                self.assertEqual(evidence['current_sha256'], sha(raw_current))
                self.assertEqual(json.loads(overlay(module.REPORT_PATH, base, raw_current, base, policy, manifest)), current)
                with self.assertRaises(PublishError):
                    overlay(module.REPORT_PATH, base, raw_current + b' ', base, policy, manifest)
                self.assertEqual(module.LOCK_PATH, moe.LOCK_PATH)
                self.assertFalse((root / module.LOCK_PATH).exists())


if __name__ == '__main__':
    unittest.main()
