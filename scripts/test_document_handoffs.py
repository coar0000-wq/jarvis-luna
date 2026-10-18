import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
import build_team_feeds as feeds
import document_handoffs as h

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import collector_snapshot_history as snapshots  # noqa: E402


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

    def build_feed(self):
        target = self.root / 'data/team_feeds.json'
        with patch.multiple(feeds, ROOT=self.root, DATA=self.root / 'data', OUT=target), \
                patch.object(feeds, 'load', return_value=None), \
                patch.object(feeds, 'collect_fda', return_value=([], [])), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(feeds.main(), 0)
        return json.loads(target.read_text(encoding='utf8'))

    def test_feed_rebuild_retains_canonical_review_date_and_passes_guard(self):
        target = self.root / 'data/team_feeds.json'
        # A stale generated marker must not override the reviewed source date.
        target.write_text(json.dumps({'document_handoffs_reviewed_at': '2000-01-01'}), encoding='utf8')
        first = self.build_feed()
        self.assertEqual(first['document_handoffs_reviewed_at'], self.doc['reviewed_at'])
        self.assertEqual(first['teams']['listing'][0]['date'], self.doc['reviewed_at'])
        second = self.build_feed()
        policy = json.loads((ROOT / 'config/publish_policy.json').read_text(encoding='utf8'))
        self.assertEqual(snapshots.allowed_removals('data/team_feeds.json', first, second, policy), [])
        del second['document_handoffs_reviewed_at']
        with self.assertRaisesRegex(ValueError, 'document_handoffs_reviewed_at'):
            snapshots.allowed_removals('data/team_feeds.json', first, second, policy)

    def test_feed_without_handoffs_never_fabricates_review_date(self):
        self.manifest.unlink()
        self.assertNotIn('document_handoffs_reviewed_at', self.build_feed())

    def test_invalid_review_dates_fail_before_feed_write(self):
        target = self.root / 'data/team_feeds.json'
        original = b'{"document_handoffs_reviewed_at":"2026-10-18"}\n'
        target.write_bytes(original)
        for reviewed_at in (None, '', '2026-02-30', '20261018', '2026-10-18T00:00:00Z', 20261018):
            with self.subTest(reviewed_at=reviewed_at):
                self.doc['reviewed_at'] = reviewed_at
                self.save()
                with self.assertRaisesRegex(ValueError, 'review date'):
                    self.build_feed()
                self.assertEqual(target.read_bytes(), original)

    def test_tampered_source_fails_before_feed_write(self):
        target = self.root / 'data/team_feeds.json'
        original = b'{"document_handoffs_reviewed_at":"2026-10-18"}\n'
        target.write_bytes(original)
        self.source.write_text('modified', encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.build_feed()
        self.assertEqual(target.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
