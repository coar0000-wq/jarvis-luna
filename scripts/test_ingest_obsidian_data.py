"""Fixture-only dataset archive tests; no production data or vault writes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import obsidian_brain as brain
import ingest_obsidian_data as ingest


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='brain-ingest-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(['git', '-C', str(self.root), 'init', '-q'], check=True, capture_output=True)
        (self.root / '.git/info/exclude').write_text('/obsidian/JARVIS_LUNA/BrainRuntime/\n')

    def write(self, path, raw):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return target

    def index(self):
        return json.loads((self.root / ingest.INDEX).read_bytes())

    def test_archive_json_jsonl_csv_preserve_sources_and_clocks(self):
        fixtures = {
            'data/a.json': b'{"observed_at":"2000-01-01T00:00:00Z","items":[1]}\n',
            'data/knowledge/corpus.jsonl': b'{"collected_at":"2000-01-02","id":1}\n{"id":2}\n',
            'data/c.csv': b'name,observed_at\r\nthing,2000-01-03\r\n',
        }
        stamps = {}
        for name, raw in fixtures.items():
            source = self.write(name, raw)
            os.utime(source, ns=(946684800000000000, 946684800000000000))
            stamps[name] = source.stat().st_mtime_ns
        report = ingest.ingest(self.root)
        self.assertEqual(report['archived_file_count'], 3)
        self.assertEqual(report['parser_counts'], {'csv': 1, 'json': 1, 'jsonl': 1})
        self.assertTrue(report['input_read_from_vault'])
        self.assertTrue(report['output_stored'])
        self.assertFalse(report['business_approval'])
        self.assertFalse(report['downstream_direct_vault_consumption_verified'])
        index = self.index()
        self.assertEqual([e['source_path'] for e in index['entries']], sorted(fixtures))
        for item in index['entries']:
            raw = fixtures[item['source_path']]
            source = self.root / item['source_path']
            self.assertEqual(item['source_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(item['payload_id'], item['source_sha256'])
            self.assertEqual(item['source_mtime_ns'], stamps[item['source_path']])
            payload = self.root / brain.BRAIN / 'payloads' / item['payload_id'][:2] / (item['payload_id'] + '.bin')
            self.assertEqual(payload.read_bytes(), raw)
            self.assertEqual(source.read_bytes(), raw)
            self.assertEqual(source.stat().st_mtime_ns, stamps[item['source_path']])
            self.assertNotIn('value', item)
        self.assertEqual(index['entries'][0]['source_timestamps']['observed_at'], '2000-01-01T00:00:00Z')
        self.assertEqual(next(e['count'] for e in index['entries'] if e['parser'] == 'jsonl'), 2)

    def test_private_and_secret_content_are_rejected_with_safe_counts(self):
        self.write('data/good.json', b'{}')
        for name in ('data/manual/mocra_profile.json', 'data/operations/state.json',
                     'data/typesafe_ledger.json', 'data/safety_checkpoints/x.json'):
            self.write(name, b'{"password":"do-not-copy"}')
        self.write('data/nested.jsonl', b'{"nested":{"api_key":"do-not-copy"}}\n')
        self.write('data/leaky.csv', b'name,access_token\nx,do-not-copy\n')
        self.write('data/bad.jsonl', b'invalid\n')
        report = ingest.ingest(self.root)
        self.assertEqual(report['archived_file_count'], 1)
        self.assertGreaterEqual(report['path_excluded_count'], 4)
        self.assertEqual(report['source_rejected_count'], 3)
        self.assertEqual(report['source_rejected_codes']['excluded_credential_field'], 2)
        serialized = json.dumps(report) + json.dumps(self.index())
        self.assertNotIn('do-not-copy', serialized)
        self.assertFalse(report['private_coverage_claimed'])
        for payload in (self.root / brain.BRAIN / 'payloads').glob('*/*.bin'):
            self.assertNotIn(b'do-not-copy', payload.read_bytes())

    def test_size_blocked_not_truncated(self):
        self.write('data/good.json', b'{}')
        oversized = self.write('data/large.jsonl', b' ' * (brain.MAX_BYTES + 1))
        before = oversized.stat().st_mtime_ns
        report = ingest.ingest(self.root)
        self.assertEqual(report['source_rejected_codes'], {'byte_limit_exceeded': 1})
        self.assertEqual(report['archived_file_count'], 1)
        self.assertEqual(oversized.stat().st_size, brain.MAX_BYTES + 1)
        self.assertEqual(oversized.stat().st_mtime_ns, before)

    def test_own_index_excluded_no_recursive_growth(self):
        self.write('data/source.json', b'{}')
        ingest.ingest(self.root)
        second = ingest.ingest(self.root)
        self.assertEqual(second['archived_file_count'], 1)
        self.assertEqual(second['path_excluded_codes']['excluded_generated_dataset_index'], 1)
        self.assertNotIn(ingest.INDEX, [e['source_path'] for e in self.index()['entries']])

    def test_payload_tamper_aborts_without_replacing_previous_index(self):
        self.write('data/source.json', b'{"id":1}')
        ingest.ingest(self.root)
        before = (self.root / ingest.INDEX).read_bytes()
        item = self.index()['entries'][0]
        payload = self.root / brain.BRAIN / 'payloads' / item['payload_id'][:2] / (item['payload_id'] + '.bin')
        payload.write_bytes(b'{"tampered":true}')
        with self.assertRaisesRegex(brain.IntegrityError, 'vault_hash_mismatch'):
            ingest.ingest(self.root)
        self.assertEqual((self.root / ingest.INDEX).read_bytes(), before)

    def test_tamper_after_readback_before_index_abort(self):
        self.write('data/source.json', b'{}')
        original = brain.load_artifact
        def tamper(path, root):
            value = original(path, root)
            payload = root / brain.BRAIN / 'payloads' / value['payload_id'][:2] / (value['payload_id'] + '.bin')
            payload.write_bytes(b'changed')
            return value
        with patch.object(brain, 'load_artifact', side_effect=tamper):
            with self.assertRaises(brain.IntegrityError):
                ingest.ingest(self.root)
        self.assertFalse((self.root / ingest.INDEX).exists())

    def test_requires_actual_git_root_and_exclusion(self):
        self.write('data/source.json', b'{}')
        with self.assertRaisesRegex(brain.BrainError, 'actual_git_root_required'):
            ingest.ingest(self.root / 'data')
        (self.root / '.git/info/exclude').write_text('')
        with self.assertRaisesRegex(brain.BrainError, 'brain_git_exclusion_required_before_write'):
            ingest.ingest(self.root)
        self.assertFalse((self.root / ingest.INDEX).exists())
        self.assertFalse((self.root / brain.BRAIN).exists())

    def test_all_rejected_reports_counts_without_invented_index(self):
        self.write('data/manual/mocra_profile.json', b'{}')
        self.write('data/unsafe.jsonl', b'{"token":"do-not-copy"}\n')
        report = ingest.ingest(self.root)
        self.assertEqual(report['blocked'], 'no_genuine_dataset_inputs')
        self.assertEqual(report['source_rejected_codes'], {'excluded_credential_field': 1})
        self.assertGreaterEqual(report['path_excluded_count'], 1)
        self.assertFalse(report['input_read_from_vault'])
        self.assertFalse(report['output_stored'])
        self.assertFalse((self.root / ingest.INDEX).exists())

    def test_limit_counts_supported_files_not_unsupported_media(self):
        for number in range(3):
            self.write('data/a' + str(number) + '.png', b'not structured')
        self.write('data/b.json', b'{}')
        report = ingest.ingest(self.root, limit=1)
        self.assertFalse(report['scan_truncated'])
        self.assertEqual(report['archived_file_count'], 1)
        self.assertEqual(report['path_excluded_codes']['excluded_unsupported_format'], 3)

    def test_limit_reports_partial_coverage(self):
        self.write('data/a.json', b'{}')
        self.write('data/b.json', b'{}')
        report = ingest.ingest(self.root, limit=1)
        self.assertTrue(report['scan_truncated'])
        self.assertEqual(report['archived_file_count'], 1)
        self.assertTrue(self.index()['scan_truncated'])


if __name__ == '__main__':
    unittest.main()
