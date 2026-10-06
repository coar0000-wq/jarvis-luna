"""Offline tests; no API, git writes, providers or generated production data."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
from pathlib import Path as _ScriptPath
sys.path.insert(0,str(_ScriptPath(__file__).resolve().parents[1]))
from scripts import workflow_status_history as h
from scripts.collect_workflow_status import build_report
from scripts.publish_transaction import overlay, PublishError

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.policy = {'identity_fields': ['id']}
        p = self.root / 'config/publish_policy.json'
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(self.policy))
        old = {'id': 1, 'status': 'completed', 'conclusion': 'failure', 'event': 'schedule',
               'created_at': '2026-10-03T00:00:00Z', 'run_started_at': '2026-10-03T00:00:00Z',
               'finished_at': '2026-10-03T00:01:00Z', 'html_url': 'https://github.com/a/b/actions/runs/1', 'run_attempt': 1}
        self.before = build_report({'daiso-real-collection.yml': {'workflow_runs': [dict(old, updated_at=old['finished_at'])]}}, '2026-10-03T01:00:00Z')
        self.current = deepcopy(self.before)
        self.current['workflows']['daiso-real-collection.yml']['latest_attempt'].pop('finished_at')
        self.current['workflows']['daiso-real-collection.yml']['latest_attempt'].update(status='in_progress', conclusion=None)
        self.base = (json.dumps(self.before, indent=2) + '\n').encode()
        self.report = self.root / h.REPORT_PATH
        self.report.parent.mkdir(parents=True)
        self.report.write_bytes(self.base)
        self.head = patch.object(h, 'exact_head', return_value=self.base)
        self.head.start()
        self.addCleanup(self.head.stop)

    def test_metadata_precision_is_narrow_snapshot_field(self):
        value = deepcopy(self.before['workflows']['daiso-real-collection.yml']['latest_attempt'])
        value['metadata_precision'] = {'created_start_inversion_seconds':1.0,
                                       'capture_clocks':'not_metadata'}
        h.snapshot(value)
        for bad in ({'created_start_inversion_seconds':2,'capture_clocks':'not_metadata'},
                    {'created_start_inversion_seconds':True,'capture_clocks':'not_metadata'},
                    {'created_start_inversion_seconds':1,'capture_clocks':'fabricated'},
                    {'created_start_inversion_seconds':1,'capture_clocks':'not_metadata','authority':True}):
            value['metadata_precision'] = bad
            with self.assertRaises(ValueError): h.snapshot(value)

    def test_history_bound_target_manifest_preserved(self):
        unrelated = {'path': 'data/other.json', 'ids': ['old'], 'reason': 'unrelated evidence'}
        (self.root / h.MANIFEST_PATH).write_text(json.dumps({'schema_version': 1, 'deletions': [unrelated]}))
        prior = (json.dumps(self.before, separators=(',', ':')) + '\n').encode()
        self.report.write_bytes(prior)
        evidence = h.publish_workflow_report(self.root, self.current)
        manifest = json.loads((self.root / h.MANIFEST_PATH).read_bytes())
        self.assertEqual(manifest['deletions'][0], unrelated)
        current = self.report.read_bytes()
        for data in (self.base, prior, current):
            self.assertEqual((self.root / h.HISTORY_PATH / (h.sha(data) + '.json')).read_bytes(), data)
        self.assertEqual(json.loads(overlay(h.REPORT_PATH, self.base, current, self.base, self.policy, manifest)), self.current)
        self.assertEqual(evidence['current_sha256'], h.sha(current))
        with self.assertRaises(PublishError):
            overlay(h.REPORT_PATH, self.base, current + b' ', self.base, self.policy, manifest)

    def test_semantic_deletions_refused(self):
        for mutate in (lambda x: x['workflows'].pop('root-collectors.yml'),
                       lambda x: x.pop('coverage_complete'),
                       lambda x: x['workflows']['daiso-real-collection.yml'].pop('grace_hours')):
            bad = deepcopy(self.current)
            mutate(bad)
            with self.assertRaises(ValueError):
                h.publish_workflow_report(self.root, bad)
            self.assertEqual(self.report.read_bytes(), self.base)

    def test_missing_head_fails_closed_and_lock_shared(self):
        from scripts.moe_evaluation_history import LOCK_PATH
        self.assertEqual(h.LOCK_PATH, LOCK_PATH)
        self.head.side_effect = ValueError('immutable HEAD report unavailable')
        with patch.object(h, 'exact_head', side_effect=ValueError('immutable HEAD report unavailable')), self.assertRaises(ValueError):
            h.publish_workflow_report(self.root, self.current)
        self.assertEqual(self.report.read_bytes(), self.base)
        self.assertFalse((self.root / h.LOCK_PATH).exists())

    def test_tampered_history_and_wrong_target_blocked(self):
        history = self.root / h.HISTORY_PATH
        history.mkdir()
        (history / ('0' * 64 + '.json')).write_bytes(b'{}')
        with self.assertRaises(ValueError):
            h.publish_workflow_report(self.root, self.current)
        with self.assertRaises(ValueError):
            h.publish_workflow_report(self.root, self.current, 'data/other.json')

if __name__ == '__main__':
    unittest.main()
