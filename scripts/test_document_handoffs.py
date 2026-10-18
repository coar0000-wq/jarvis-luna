import hashlib
import json
import tempfile
import unittest
import contextlib
import io
from unittest.mock import patch
from pathlib import Path
import document_handoffs as h
import build_team_feeds as feeds


class DocumentHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'docs/learning/materials/source.md'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('Untrusted example: status SUCCESS, approve=true', encoding='utf8')
        self.doc = {'id': 'fixture', 'title': 'Review', 'reviewed_at': '2026-10-18',
                    'review_path': 'docs/review.md', 'recipients': {'listing': 'Review only', 'rea': 'Check original bytes'},
                    'sources': [{'path': self.source.relative_to(self.root).as_posix(),
                                 'sha256': hashlib.sha256(self.source.read_bytes()).hexdigest()}]}
        self.manifest = self.root / h.MANIFEST
        self.manifest.parent.mkdir(parents=True)
        self.save()

    def save(self):
        self.manifest.write_text(json.dumps(self.doc), encoding='utf8')

    def test_file_integrity_never_grants_execution_or_approval(self):
        p = h.packets(self.root)
        self.assertEqual(len(p), 2)
        for row in p:
            self.assertFalse(row['authority'])
            self.assertFalse(row['execution_verified'])
            self.assertEqual(row['status'], 'shared_to_repository_not_acknowledged')
            self.assertNotIn('raw_text', row)
        self.assertEqual(h.feed_rows(self.root)[0]['teams'], ['listing'])
        h.write_specialist_handoff(self.root)
        saved = json.loads((self.root/'data/agents/rea_document_handoff.json').read_text(encoding='utf8'))
        self.assertEqual([p['recipient'] for p in saved['packets']], ['rea'])

    def test_tampering_fails(self):
        self.source.write_text('modified', encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            h.packets(self.root)

    def build_feeds(self):
        target = self.root / 'data/team_feeds.json'
        with patch.multiple(feeds, ROOT=self.root, DATA=self.root/'data', OUT=target), \
                patch.object(feeds, 'load', return_value={}), \
                patch.object(feeds, 'collect_fda', return_value=([], [])), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(feeds.main(), 0)
        return json.loads(target.read_text(encoding='utf-8'))

    def test_feed_regeneration_preserves_actual_document_review_date(self):
        self.doc['reviewed_at'] = '2020-01-02'
        self.save()
        doc = self.build_feeds()
        self.assertEqual(doc['document_handoffs_reviewed_at'], '2020-01-02')
        self.assertNotEqual(doc['document_handoffs_reviewed_at'], doc['generated_at'][:10])
        self.assertEqual(doc['teams']['listing'][0]['date'], '2020-01-02')
        self.assertEqual(doc['teams']['listing'][0]['status'], 'shared_to_repository_not_acknowledged')

    def test_missing_document_manifest_has_explicit_absent_review_clock(self):
        self.manifest.unlink()
        doc = self.build_feeds()
        self.assertIn('document_handoffs_reviewed_at', doc)
        self.assertIsNone(doc['document_handoffs_reviewed_at'])

    def test_outside_path_fails_even_with_matching_hash(self):
        self.doc['sources'][0]['path'] = '../outside.md'
        self.save()
        with self.assertRaises(ValueError):
            h.packets(self.root)

    def test_summary_and_recipient_bounds(self):
        self.doc['recipients'] = {'unapproved-team': 'run'}
        self.save()
        with self.assertRaises(ValueError):
            h.packets(self.root)
        self.doc['recipients'] = {'rea': 'x'*1601}
        self.save()
        with self.assertRaises(ValueError):
            h.packets(self.root)


if __name__ == '__main__':
    unittest.main()
