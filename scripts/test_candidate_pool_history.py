"""Offline synthetic candidate pool retention and authorization regression tests."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import candidate_pool_history as hist
from scripts import publish_transaction as pub
from scripts.immutable_snapshot_store import load_snapshots, MAX_BYTES

POLICY = {'identity_fields': ['pd_no', 'id'], 'metadata_timestamps': []}
AT = '2026-10-05T08:00:00+00:00'


def raw(value):
    return (json.dumps(value, indent=3) + '\n').encode()


def row(key, execution):
    return {'pd_no': key, 'name': key, 'approval_required': True, 'may_publish': False,
            'may_replace_operating_products': False, 'url': 'https://example.invalid/' + key,
            'collected_at': AT, 'evidence': {'price': 1000},
            'observation': {'execution_id': execution, 'method': 'daiso_detail',
                            'url': 'https://example.invalid/' + key, 'captured_at': AT}}


def fixture():
    base = {'schema_version': 1, 'items': {'1066897': row('1066897', 'old')}, 'count': 1,
            'approval_required': True, 'may_publish': False, 'may_replace_operating_products': False,
            'last_run': {'execution_id': 'old', 'at': AT, 'new': 1, 'updated': 0, 'collected_ids': ['1066897']}}
    current = deepcopy(base)
    ids = [str(2000000 + x) for x in range(83)]
    current['items'].update({key: row(key, 'new') for key in ids})
    current['count'] = 84
    current['last_run'] = {'execution_id': 'new', 'at': AT, 'new': 83, 'updated': 0, 'collected_ids': ids}
    return raw(base), raw(current)


class CandidateHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base, self.current = fixture()
        p = self.root / hist.POOL_PATH
        p.parent.mkdir(parents=True)
        p.write_bytes(self.current)
        self.h = patch.object(hist, 'head', return_value=b'fixed-head'); self.h.start(); self.addCleanup(self.h.stop)
        self.b = patch.object(hist, 'exact_head', return_value=self.base); self.b.start(); self.addCleanup(self.b.stop)

    def preserve(self):
        return hist.preserve_candidate_pool(self.root)

    def test_one_to_83_exact_retention_full_overlay(self):
        result = self.preserve()
        self.assertEqual(result['removed_ids'], ['1066897'])
        self.assertEqual((self.root / hist.POOL_PATH).read_bytes(), self.current)
        snapshots = load_snapshots(self.root, hist.HISTORY_PATH)
        self.assertEqual(snapshots, {hist.sha(self.base): self.base, hist.sha(self.current): self.current})
        manifest = json.loads((self.root / hist.MANIFEST_PATH).read_bytes())
        self.assertEqual(pub.overlay(hist.POOL_PATH, self.base, self.current, self.base, POLICY, manifest, candidate_history=snapshots), self.current)
        self.assertEqual(json.loads(self.current)['items']['1066897'], json.loads(self.base)['items']['1066897'])
        self.preserve()
        self.assertEqual((self.root / hist.POOL_PATH).read_bytes(), self.current)

    def test_no_archive_or_forged_manifest(self):
        self.preserve()
        manifest = json.loads((self.root / hist.MANIFEST_PATH).read_bytes())
        archives = load_snapshots(self.root, hist.HISTORY_PATH)
        for history, mutation in [(None, {}), ({}, {}), (archives, {'replacement_sha256': '0'*64}), (archives, {'policy_ref': 'invented'}), (archives, {'ids': ['1066897', 'extra']})]:
            changed = deepcopy(manifest); changed['deletions'][0].update(mutation)
            with self.assertRaises(pub.PublishError):
                pub.overlay(hist.POOL_PATH, self.base, self.current, self.base, POLICY, changed, candidate_history=history)
        del manifest['deletions'][0]['replacement_sha256']
        self.assertFalse(pub.deletion_authorized(hist.POOL_PATH, self.base, ['1066897'], manifest, replacement=self.current, candidate_history=archives))

    def test_items_flags_evidence_removals_failclosed(self):
        for mutation in ('item', 'flag', 'field', 'null', 'array'):
            current = json.loads(self.current)
            if mutation == 'item':
                del current['items']['1066897']; current['count'] -= 1
            elif mutation == 'flag':
                current['items']['1066897']['may_publish'] = True
            elif mutation == 'field':
                del current['items']['1066897']['evidence']['price']
            elif mutation == 'null':
                current['items']['1066897']['evidence']['price'] = None
            else:
                before = json.loads(self.base); before['semantic'] = ['keep']; current['semantic'] = []
                with self.assertRaises(ValueError): hist.replacement_ids(raw(before), raw(current))
                continue
            with self.assertRaises(ValueError): hist.replacement_ids(self.base, raw(current))
            with self.assertRaises(pub.PublishError): pub.overlay(hist.POOL_PATH, self.base, raw(current), self.base, POLICY, {})

    def test_malformed_metadata(self):
        for key, value in [('new', True), ('updated', -1), ('new', 82), ('collected_ids', ['1066897']), ('at', 'not-clock'), ('execution_id', 'forged')]:
            changed = json.loads(self.current); changed['last_run'][key] = value
            with self.assertRaises(ValueError): hist.replacement_ids(self.base, raw(changed))
        changed = json.loads(self.current); changed['last_run']['collected_ids'].append(changed['last_run']['collected_ids'][0])
        with self.assertRaises(ValueError): hist.replacement_ids(self.base, raw(changed))
        changed = json.loads(self.current); del changed['last_run']['at']
        with self.assertRaises(ValueError): hist.replacement_ids(self.base, raw(changed))

    def test_changed_head(self):
        with patch.object(hist, 'head', side_effect=[b'old', b'new']):
            with self.assertRaises(ValueError): self.preserve()
        self.assertFalse((self.root / hist.MANIFEST_PATH).exists())

    def test_concurrent_source_and_manifest(self):
        original = hist.retain_snapshots
        for name in (hist.POOL_PATH, hist.MANIFEST_PATH):
            (self.root / hist.POOL_PATH).write_bytes(self.current)
            (self.root / hist.MANIFEST_PATH).unlink(missing_ok=True)
            def race(*args, **kwargs):
                result = original(*args, **kwargs)
                (self.root / name).write_bytes(b'{}')
                return result
            with patch.object(hist, 'retain_snapshots', side_effect=race):
                with self.assertRaises(ValueError): self.preserve()

    def test_missing_source_lock_capacity_and_linked_source(self):
        source = self.root / hist.POOL_PATH
        source.unlink()
        with self.assertRaises(OSError): self.preserve()
        source.write_bytes(self.current)
        lock = self.root / hist.LOCK_PATH; lock.write_bytes(b'busy')
        with self.assertRaises(FileExistsError): self.preserve()
        lock.unlink()
        source.write_bytes(b' ' * (MAX_BYTES + 1))
        with self.assertRaises(ValueError): self.preserve()
        source.write_bytes(self.current)
        import os
        other = source.with_suffix('.link'); os.link(source, other)
        with self.assertRaises(ValueError): self.preserve()

    def test_immutable_conflicts_and_prior_identity(self):
        self.preserve()
        snapshots = load_snapshots(self.root, hist.HISTORY_PATH)
        path = next((self.root / hist.HISTORY_PATH).glob('*.json'))
        path.write_bytes(b'{}')
        with self.assertRaises(ValueError): self.preserve()
        for local, remote in [(None, self.base), (self.base, b' ' + self.base), (b'{}', self.base)]:
            name = hist.HISTORY_PATH + '/' + hist.sha(self.base) + '.json'
            with self.assertRaises(pub.PublishError): pub.overlay(name, self.base, local, remote, POLICY, {})
        prior = json.loads(self.base); prior['items']['lost'] = row('lost', 'earlier'); prior['count'] = 2
        with self.assertRaises(ValueError): hist.verify_evidence(self.base, self.current, ['1066897'], dict(snapshots, **{hist.sha(raw(prior)): raw(prior)}))


if __name__ == '__main__':
    unittest.main()
