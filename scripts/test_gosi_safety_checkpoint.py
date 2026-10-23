"""Offline Git/ZIP/HTTP-metadata fixtures only. No provider or remote writes."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import gosi_safety_checkpoint as s


class GosiCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gosi-checkpoint-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'checkout'
        self.root.mkdir()
        self.env = patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.doc = {'items': {'1000000': {'product_id': '1000000', 'maker': 'Original supplier',
            'field_observations': {'maker': {'source': 'https://fixture.invalid',
                'sha256': 'a' * 64, 'byte_count': 7, 'received_at': '2026-01-01T00:00:00+00:00',
                'verified': False}}}}, 'provider_stops': [], 'provider_stop_history': []}
        self.save(self.root, s.h.REPORT_PATH, self.doc)
        self.save(self.root, s.h.MANIFEST_PATH, {'schema_version': 1,
            'deletions': [{'path': 'data/unrelated.json', 'reason': 'leave unchanged'}]})
        self.save(self.root, 'config/publish_policy.json', {'identity_fields': ['product_id']})
        self.git(self.root, 'init', '-q')
        self.git(self.root, 'config', 'user.name', 'Offline Fixture')
        self.git(self.root, 'config', 'user.email', 'fixture@example.invalid')
        self.git(self.root, 'add', '.')
        self.git(self.root, 'commit', '-qm', 'fixture baseline')
        self.commit = s._head(self.root)
        self.producer = self.clone('producer')
        self.lineage = s._lineage(s.REPOSITORY, '11', '1', self.commit)
        self.archive = self.base / 'gosi-safety.zip'
        self.stamp = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        self.old = (self.root / s.h.REPORT_PATH).read_bytes()

    def git(self, root, *args):
        return subprocess.run(['git', '-C', str(root), *args], check=True,
                              capture_output=True).stdout

    def clone(self, name):
        path = self.base / name
        subprocess.run(['git', 'clone', '--no-hardlinks', '-q', str(self.root), str(path)],
                       check=True, capture_output=True)
        self.git(path, 'config', 'user.name', 'Offline Fixture')
        self.git(path, 'config', 'user.email', 'fixture@example.invalid')
        return path

    def save(self, root, name, value):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

    def advance(self, *, stop=None):
        doc = deepcopy(self.doc)
        row = doc['items']['1000000']
        evidence = {'source': 'https://fixture.invalid/exact', 'sha256': s.h.sha(b'raw bytes'),
            'byte_count': 9, 'received_at': self.stamp, 'verified': False,
            'source_received_at': self.stamp, 'product_identity_verified': False,
            'human_verified': False, 'capture_scope': 'rendered_alt_partial_page'}
        s.h.observe_field(row, 'ingredients', 'Water, Glycerin', evidence)
        s.h.attempt(row, self.stamp, 'rendered_alt', 'fields_added')
        if stop:
            doc['provider_stops'] = [stop]
        s.h.publish_observation(self.producer, doc)
        return doc

    def bundle(self, *, stop=None):
        doc = self.advance(stop=stop)
        s.pack(self.producer, self.archive, **self.lineage)
        raw = self.archive.read_bytes()
        return doc, raw, s._archive(raw, self.lineage)

    def stop(self, provider='daiso', code=403, stamp=None):
        return {'provider': provider, 'code': code,
            'category': 'quota' if code == 429 else 'auth', 'stopped_at': stamp or self.stamp}

    def outer(self, raw):
        result = io.BytesIO()
        with zipfile.ZipFile(result, 'w') as archive:
            archive.writestr('gosi-safety.zip', raw)
        return result.getvalue()

    def metadata(self, raw, *, run_id=11, attempt=1):
        outer = self.outer(raw)
        run = {'id': run_id, 'run_attempt': attempt, 'path': '.github/workflows/JARVIS-Deep-Analysis.yml',
            'head_branch': 'main', 'head_repository': {'full_name': s.REPOSITORY},
            'head_sha': self.commit, 'status': 'completed', 'conclusion': 'failure'}
        artifact = {'id': 71, 'name': f'gosi-safety-{run_id}-{attempt}', 'expired': False,
            'workflow_run': {'id': run_id, 'head_sha': self.commit, 'head_branch': 'main'},
            'archive_download_url': s.BASE + 'artifacts/71/zip', 'digest': 'sha256:' + s.h.sha(outer)}
        def fetch(url):
            if url.endswith('/runs/99/attempts/2'):
                return dict(run, id=99, run_attempt=2, status='in_progress')
            if url.endswith('/runs/99/attempts/1'):
                return dict(run, id=99, run_attempt=1, status='completed')
            if '/runs?' in url:
                rows = [deepcopy(run)] if '/JARVIS-Deep-Analysis.yml/' in url else []
                return {'total_count': len(rows), 'workflow_runs': rows}
            if url.endswith('/jobs?per_page=100'):
                return {'total_count': 1, 'jobs': [{'completed_at': self.stamp}]}
            if '/artifacts?' in url:
                return {'total_count': 1, 'artifacts': [deepcopy(artifact)]}
            match = __import__('re').search(r'/runs/([0-9]+)/attempts/([0-9]+)$', url)
            if match:
                return dict(run, id=int(match[1]), run_attempt=int(match[2]), status='completed')
            raise AssertionError('Unexpected GitHub metadata request: ' + url)
        return fetch, outer, run, artifact

    def restore(self, raw, **kwargs):
        fetch, outer, _, _ = self.metadata(raw)
        return s.restore_latest(self.root, fetch_json=kwargs.get('fetch', fetch),
            fetch_bytes=lambda _: outer, current_run_id='99', current_attempt='1')

    def test_roundtrip_preserves_exact_source_receipts_and_original_history(self):
        expected, raw, incoming = self.bundle()
        self.assertEqual(self.restore(raw)['status'], 'authenticated_gosi_restored')
        restored = json.loads((self.root / s.h.REPORT_PATH).read_bytes())
        self.assertEqual(restored, expected)
        self.assertEqual((self.root / s.h.REPORT_PATH).read_bytes(), incoming[s.h.REPORT_PATH])
        self.assertIn(self.old, s._history(s._snapshot(self.root)).values())
        self.assertEqual(restored['items']['1000000']['field_observations']['maker'],
                         self.doc['items']['1000000']['field_observations']['maker'])
        self.assertFalse((self.root / s.h.CONTINUITY_PENDING).exists())

    def test_failed_publication_previous_run_restores_stop_for_all_providers(self):
        for provider, code in [('daiso', 401), ('daiso', 403), ('daiso', 429),
                               ('gemini', 429), ('groq', 403)]:
            with self.subTest(provider=provider, code=code):
                source = self.clone(f'source-{provider}-{code}')
                target = self.clone(f'target-{provider}-{code}')
                doc = deepcopy(self.doc)
                doc['provider_stops'] = [self.stop(provider, code)]
                s.h.publish_observation(source, doc)
                path = self.base / f'{provider}-{code}.zip'
                s.pack(source, path, **self.lineage)
                incoming = s._archive(path.read_bytes(), self.lineage)
                s.restore_files(target, incoming, lineage=self.lineage, run_id='99', run_attempt='1')
                current = json.loads((target / s.h.REPORT_PATH).read_bytes())
                with self.assertRaises(s.h.ProviderStop):
                    s.h.assert_not_stopped(current, {provider})
                self.assertEqual(current['provider_stops'][0]['stopped_at'], self.stamp)

    def test_expiry_uses_original_stop_clock_not_restore_clock(self):
        stamp = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        _, raw, _ = self.bundle(stop=self.stop(stamp=stamp))
        self.restore(raw)
        doc = json.loads((self.root / s.h.REPORT_PATH).read_bytes())
        self.assertEqual(doc['provider_stops'][0]['stopped_at'], stamp)
        s.h.assert_not_stopped(doc, {'daiso'})
        self.assertEqual(doc['provider_stop_history'][0]['stopped_at'], stamp)

    def test_delayed_supervisor_keeps_observed_stop_clock(self):
        doc = deepcopy(self.doc)
        s.h.persist_stop(doc, s.h.ProviderStop('daiso', 429, 'quota'), stopped_at=self.stamp)
        self.assertEqual(doc['provider_stops'][0]['stopped_at'], self.stamp)
        with self.assertRaises(ValueError):
            s.h.persist_stop(doc, s.h.ProviderStop('daiso', 403), stopped_at='2026-01-01')

    def test_unrelated_publication_manifest_entries_unchanged(self):
        original = json.loads((self.root / s.h.MANIFEST_PATH).read_bytes())['deletions'][0]
        _, raw, _ = self.bundle(stop=self.stop())
        self.restore(raw)
        entries = json.loads((self.root / s.h.MANIFEST_PATH).read_bytes())['deletions']
        self.assertIn(original, entries)
        self.assertNotIn(s.h.MANIFEST_PATH, s._archive(raw, self.lineage))

    def test_newer_exact_head_kept_without_rolling_back_fields(self):
        _, raw, incoming = self.bundle()
        self.restore(raw)
        doc = json.loads((self.root / s.h.REPORT_PATH).read_bytes())
        s.h.observe_field(doc['items']['1000000'], 'expiry', '2028-01', {'received_at': self.stamp})
        s.h.publish_observation(self.root, doc)
        self.git(self.root, 'add', 'data')
        self.git(self.root, 'commit', '-qm', 'newer authenticated HEAD fixture')
        before = (self.root / s.h.REPORT_PATH).read_bytes()
        result = s.restore_files(self.root, incoming, lineage=self.lineage, run_id='99', run_attempt='2')
        self.assertEqual(result, 'artifact_already_preserved_in_exact_head')
        self.assertEqual((self.root / s.h.REPORT_PATH).read_bytes(), before)

    def test_dirty_document_cannot_claim_ahead_of_artifact(self):
        _, raw, _ = self.bundle()
        self.save(self.root, s.h.REPORT_PATH, {**self.doc, 'unvouched': True})
        with self.assertRaisesRegex(s.Blocked, 'current_not_exact_head'):
            self.restore(raw)
        self.assertFalse((self.root / s.h.CONTINUITY_PROOF).exists())

    def test_missing_tracked_history_rejected(self):
        s.h.publish_observation(self.root, self.doc)
        self.git(self.root, 'add', 'data')
        self.git(self.root, 'commit', '-qm', 'trusted history')
        history = next((self.root / s.h.HISTORY_PATH).glob('*.json'))
        history.unlink()
        with self.assertRaisesRegex(s.Blocked, 'head_history_missing'):
            s._exact_head(self.root, s._snapshot(self.root))

    def test_active_stop_loss_rejected_even_with_diagnostic_replacement_policy(self):
        _, _, incoming = self.bundle(stop=self.stop())
        current = deepcopy(incoming)
        doc = json.loads(incoming[s.h.REPORT_PATH])
        doc['provider_stops'] = []
        incoming[s.h.HISTORY_PATH + '/' + s.h.sha(current[s.h.REPORT_PATH]) + '.json'] = current[s.h.REPORT_PATH]
        incoming[s.h.REPORT_PATH] = s._bytes(doc)
        with self.assertRaisesRegex(s.Blocked, 'active_provider_stop_loss'):
            s._nonregression(self.root, current, incoming)

    def test_source_clock_and_history_loss_rejected(self):
        _, _, incoming = self.bundle()
        missing = {s.h.REPORT_PATH: incoming[s.h.REPORT_PATH]}
        with self.assertRaisesRegex(s.Blocked, 'prior_gosi_bytes_missing'):
            s._nonregression(self.root, s._snapshot(self.root), missing)
        doc = json.loads(incoming[s.h.REPORT_PATH])
        doc['items']['1000000']['field_observations']['maker']['received_at'] = self.stamp
        incoming[s.h.REPORT_PATH] = s._bytes(doc)
        with self.assertRaises(ValueError):
            s._nonregression(self.root, s._snapshot(self.root), incoming)

    def test_injected_publication_failure_leaves_pending_and_blocks_collectors(self):
        _, _, incoming = self.bundle(stop=self.stop())
        with patch.object(s.h, 'publish_observation', side_effect=OSError('offline injected failure')):
            with self.assertRaises(OSError):
                s.restore_files(self.root, incoming, lineage=self.lineage, run_id='99', run_attempt='1')
        self.assertTrue((self.root / s.h.CONTINUITY_PENDING).exists())
        self.assertEqual((self.root / s.h.REPORT_PATH).read_bytes(), self.old)
        with self.assertRaises(ValueError):
            s.h.require_continuity(self.root)
        with self.assertRaises(ValueError):
            s.restore_files(self.root, incoming, lineage=self.lineage, run_id='99', run_attempt='1')

    def test_lock_conflict_is_not_cleared(self):
        self.advance()
        (self.producer / s.h.LOCK_PATH).write_text('other owner')
        with self.assertRaises(FileExistsError):
            s.pack(self.producer, self.archive, **self.lineage)
        self.assertEqual((self.producer / s.h.LOCK_PATH).read_text(), 'other owner')

    def test_runtime_pending_packs_forensics_but_never_clean_checkpoint(self):
        self.advance()
        (self.producer / s.h.COLLECTION_PENDING).write_text('unacknowledged STOP')
        result = s.pack(self.producer, self.archive, **self.lineage)
        self.assertEqual(result['status'], 'packed_recovery_required')
        with self.assertRaisesRegex(s.Blocked, 'recovery_required_checkpoint'):
            s._archive(self.archive.read_bytes(), self.lineage)

    def test_pending_stop_journal_and_stale_lock_preserved_without_restore(self):
        temp_root = self.base / 'runtime'
        journal = temp_root / 'gosi-runtime-fixture' / 'journal'
        journal.mkdir(parents=True)
        header = {'run_id': '11:1', 'nonce': 'a' * 32, 'baseline_sha256': s.h.sha(self.old)}
        stop = {'sequence': 1, 'kind': 'stop', 'payload': {'code': 403, 'observed_at': self.stamp}}
        self.save(journal, 'header.json', header)
        (journal / 'baseline.json').write_bytes(self.old)
        self.save(journal, '000001.json', stop)
        expected = (journal / '000001.json').read_bytes()
        self.save(self.producer, s.h.COLLECTION_PENDING,
            {'baseline_sha256': s.h.sha(self.old), 'journal_dir': str(journal), 'selected': ['1000000']})
        (self.producer / s.h.LOCK_PATH).write_text('stale publication owner')
        with patch.dict(os.environ, {'RUNNER_TEMP': str(temp_root)}):
            result = s.pack(self.producer, self.archive, **self.lineage)
        self.assertEqual(result['status'], 'packed_recovery_required')
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(archive.read('recovery/journal/000001.json'), expected)
            manifest = json.loads(archive.read(s.MANIFEST))
            self.assertEqual(manifest['canonical_sha256'], s.h.sha(self.old))
            self.assertEqual(manifest['state'], 'recovery_required')
            self.assertEqual(archive.read('recovery/publication-lock'), b'stale publication owner')
        with self.assertRaisesRegex(s.Blocked, 'recovery_required_checkpoint'):
            self.restore(self.archive.read_bytes())
        self.assertEqual((self.root / s.h.REPORT_PATH).read_bytes(), self.old)
        self.assertFalse((self.root / s.h.CONTINUITY_PROOF).exists())

    def test_first_activation_does_not_invent_verified_baseline(self):
        _, raw, _ = self.bundle()
        fetch, outer, _, _ = self.metadata(raw)
        def first(url):
            if '/runs?' in url:
                return {'total_count': 0, 'workflow_runs': []}
            if '/artifacts?' in url:
                return {'total_count': 0, 'artifacts': []}
            return fetch(url)
        with self.assertRaisesRegex(s.Blocked, 'activation_baseline_unverified'):
            s.restore_latest(self.root, fetch_json=first, fetch_bytes=lambda _: outer,
                             current_run_id='99', current_attempt='1')
        self.assertFalse((self.root / s.h.CONTINUITY_PROOF).exists())
        self.assertEqual((self.root / s.h.REPORT_PATH).read_bytes(), self.old)

    def test_old_code_run_created_before_activation_rerun_today_is_not_ignored(self):
        self.advance()
        s._proof(self.producer, s._snapshot(self.producer), run_id='11', run_attempt='1', source={},
                 coverage={'8': [1, 0, self.commit]})
        s.pack(self.producer, self.archive, **self.lineage)
        raw = self.archive.read_bytes()
        fetch, _, seed, _ = self.metadata(raw)
        old = dict(seed, id=8, run_attempt=2, created_at='2020-01-01T00:00:00Z')
        requested = []
        def old_code(url):
            requested.append(url)
            self.assertNotIn('created=', url)
            if '/JARVIS-Deep-Analysis.yml/runs?' in url:
                return {'total_count': 2, 'workflow_runs': [seed, old]}
            if '/runs/8/artifacts?' in url:
                return {'total_count': 0, 'artifacts': []}
            if '/runs/8/attempts/2/jobs?' in url:
                return {'total_count': 1, 'jobs': [{'completed_at': datetime.now(timezone.utc).isoformat()}]}
            return fetch(url)
        self.assertNotEqual(s._git(self.root, 'cat-file', '-e', self.commit + ':' + s.HELPER).returncode, 0)
        with self.assertRaisesRegex(s.Blocked, 'latest_gosi_artifact_missing'):
            self.restore(raw, fetch=old_code)
        self.assertTrue(any('runs/8/attempts/2/jobs' in x for x in requested))
        self.assertFalse(any('runs/8/attempts/1' in x for x in requested))
        self.assertFalse((self.root / s.h.CONTINUITY_PROOF).exists())

    def test_forensic_marker_cannot_read_a_journal_outside_runtime_scope(self):
        secret = self.base / 'private'
        secret.mkdir()
        (secret / 'baseline.json').write_text('PRIVATE_SHOULD_NOT_BE_ARCHIVED')
        self.save(self.producer, s.h.COLLECTION_PENDING, {'journal_dir': str(secret)})
        result = s.pack(self.producer, self.archive, **self.lineage)
        self.assertEqual(result['status'], 'packed_recovery_required')
        with zipfile.ZipFile(self.archive) as archive:
            self.assertNotIn('recovery/journal/baseline.json', archive.namelist())
            self.assertNotIn(b'PRIVATE_SHOULD_NOT_BE_ARCHIVED', b''.join(archive.read(n) for n in archive.namelist()))

    def test_archive_lineage_each_field_and_extra_file_rejected_before_write(self):
        _, raw, _ = self.bundle()
        for key, value in [('repository', 'other/repository'), ('run_id', '12'),
                           ('run_attempt', '2'), ('commit', 'a' * 40)]:
            with self.subTest(key=key), self.assertRaisesRegex(s.Blocked, 'archive_lineage_mismatch'):
                s._archive(raw, {**self.lineage, key: value})
        target = io.BytesIO(raw)
        with zipfile.ZipFile(target, 'a') as archive:
            archive.writestr('../secret', b'not allowed')
        with self.assertRaisesRegex(s.Blocked, 'archive_path_denied'):
            s._archive(target.getvalue(), self.lineage)
        self.assertEqual((self.root / s.h.REPORT_PATH).read_bytes(), self.old)

    def test_archive_tamper_duplicate_and_size_caps(self):
        _, raw, _ = self.bundle()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files = {x: archive.read(x) for x in archive.namelist()}
        files[s.h.REPORT_PATH] += b' '
        altered = io.BytesIO()
        with zipfile.ZipFile(altered, 'w') as archive:
            for name, body in files.items():
                archive.writestr(name, body)
        with self.assertRaisesRegex(s.Blocked, 'archive_manifest_mismatch'):
            s._archive(altered.getvalue(), self.lineage)
        with patch.object(s, 'MAX_FILE_BYTES', 1), self.assertRaises(s.Blocked):
            s._archive(raw, self.lineage)
        with self.assertRaises(s.Blocked):
            s._json(b'{"a":1,"a":2}')

    def test_authenticated_digest_and_run_metadata_required(self):
        _, raw, _ = self.bundle()
        for change in ('digest', 'head_sha', 'branch', 'expired', 'url'):
            fetch, outer, _, artifact = self.metadata(raw)
            if change == 'digest': artifact['digest'] = 'sha256:' + '0' * 64
            elif change == 'head_sha': artifact['workflow_run']['head_sha'] = '0' * 40
            elif change == 'branch': artifact['workflow_run']['head_branch'] = 'other'
            elif change == 'expired': artifact['expired'] = True
            else: artifact['archive_download_url'] = 'https://other.invalid/archive'
            with self.subTest(change=change), self.assertRaises(s.Blocked):
                s.restore_latest(self.clone('metadata-' + change), fetch_json=fetch, fetch_bytes=lambda _: outer,
                                 current_run_id='99', current_attempt='1')
        self.assertFalse((self.root / s.h.CONTINUITY_PROOF).exists())

    def test_missing_latest_artifact_cannot_fall_back_to_old_success(self):
        _, raw, _ = self.bundle()
        fetch, _, run, _ = self.metadata(raw)
        newer = dict(run, id=12)
        def missing(url):
            if '/JARVIS-Deep-Analysis.yml/runs?' in url:
                return {'total_count': 2, 'workflow_runs': [newer, run]}
            if '/runs/12/artifacts?' in url:
                return {'total_count': 0, 'artifacts': []}
            if '/runs/12/attempts/1/jobs?' in url:
                return {'total_count': 1, 'jobs': [{'completed_at': datetime.now(timezone.utc).isoformat()}]}
            return fetch(url)
        with self.assertRaisesRegex(s.Blocked, 'latest_gosi_artifact_missing'):
            self.restore(raw, fetch=missing)

    def test_previous_attempt_of_current_run_is_not_ignored(self):
        doc = self.advance(stop=self.stop())
        lineage = s._lineage(s.REPOSITORY, '99', '1', self.commit)
        s.pack(self.producer, self.archive, **lineage)
        raw = self.archive.read_bytes()
        fetch, outer, run, _ = self.metadata(raw, run_id=99, attempt=1)
        run.update(run_attempt=2, status='in_progress')
        result = s.restore_latest(self.root, fetch_json=fetch, fetch_bytes=lambda _: outer,
                                  current_run_id='99', current_attempt='2')
        self.assertEqual(result['source_run_attempt'], 1)
        self.assertEqual(json.loads((self.root / s.h.REPORT_PATH).read_bytes()), doc)

    def test_recent_rerun_of_older_id_takes_precedence(self):
        self.advance(stop=self.stop())
        lineage = s._lineage(s.REPOSITORY, '8', '2', self.commit)
        s._proof(self.producer, s._snapshot(self.producer), run_id='8', run_attempt='2', source={},
                 coverage={'12': [1, 0, self.commit]})
        s.pack(self.producer, self.archive, **lineage)
        raw = self.archive.read_bytes()
        fetch, outer, run, _ = self.metadata(raw, run_id=8, attempt=2)
        other = dict(run, id=12, run_attempt=1)
        clocks = {'runs/8/attempts/1/jobs': datetime.now(timezone.utc) - timedelta(minutes=4),
                  'runs/12/attempts/1/jobs': datetime.now(timezone.utc) - timedelta(minutes=3),
                  'runs/8/attempts/2/jobs': datetime.now(timezone.utc) - timedelta(minutes=2)}
        def ordered(url):
            if '/JARVIS-Deep-Analysis.yml/runs?' in url:
                return {'total_count': 2, 'workflow_runs': [other, run]}
            for suffix, when in clocks.items():
                if suffix in url:
                    return {'total_count': 1, 'jobs': [{'completed_at': when.isoformat()}]}
            return fetch(url)
        result = s.restore_latest(self.root, fetch_json=ordered, fetch_bytes=lambda _: outer,
                                  current_run_id='99', current_attempt='1')
        self.assertEqual((result['source_run_id'], result['source_run_attempt']), (8, 2))

    def test_divergent_exact_head_facts_require_reconciliation(self):
        _, _, incoming = self.bundle()
        doc = deepcopy(self.doc)
        doc['items']['1000000']['maker'] = 'Conflicting HEAD supplier'
        self.save(self.root, s.h.REPORT_PATH, doc)
        self.git(self.root, 'add', s.h.REPORT_PATH)
        self.git(self.root, 'commit', '-qm', 'divergent fixture')
        before = (self.root / s.h.REPORT_PATH).read_bytes()
        with self.assertRaises(ValueError):
            s.restore_files(self.root, incoming, lineage=self.lineage, run_id='99', run_attempt='1')
        self.assertEqual((self.root / s.h.REPORT_PATH).read_bytes(), before)

    def test_incomplete_run_history_and_jobs_fail_closed(self):
        _, raw, _ = self.bundle()
        fetch, _, _, _ = self.metadata(raw)
        for kind in ('runs', 'jobs'):
            def broken(url):
                value = fetch(url)
                if kind == 'runs' and '/runs?' in url:
                    value['total_count'] = s.MAX_RUNS + 1
                if kind == 'jobs' and '/jobs?' in url:
                    value['total_count'] = 2
                return value
            with self.subTest(kind=kind), self.assertRaises(s.Blocked):
                s.restore_latest(self.clone('incomplete-' + kind), fetch_json=broken, fetch_bytes=lambda _: self.outer(raw),
                                 current_run_id='99', current_attempt='1')

    def test_network_error_no_verified_proof_or_data_changes(self):
        with self.assertRaises(OSError):
            s.restore_latest(self.root, fetch_json=lambda _: (_ for _ in ()).throw(OSError('offline')),
                             current_run_id='99', current_attempt='1')
        self.assertFalse((self.root / s.h.CONTINUITY_PROOF).exists())
        self.assertEqual((self.root / s.h.REPORT_PATH).read_bytes(), self.old)

    def test_actions_guard_is_run_bound_and_local_guard_is_read_only(self):
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*'))
        s.h.require_continuity(self.root)
        self.assertEqual(sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*')), before)
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': s.REPOSITORY,
                                    'GITHUB_RUN_ID': '99', 'GITHUB_RUN_ATTEMPT': '2',
                                    'GITHUB_SHA': self.commit}):
            with self.assertRaises(ValueError):
                s.h.require_continuity(self.root)
            s._proof(self.root, s._snapshot(self.root), run_id='99', run_attempt='2', source={})
            s.h.require_continuity(self.root)
            with patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '3'}), self.assertRaises(ValueError):
                s.h.require_continuity(self.root)
            with patch.dict(os.environ, {'GITHUB_SHA': '0' * 40}), self.assertRaises(ValueError):
                s.h.require_continuity(self.root)

    def test_shared_collector_entrypoints_stop_before_network(self):
        from scripts import collect_daiso_gosi as collect
        from scripts import extract_gosi_vision as vision
        (self.root / s.h.CONTINUITY_PENDING).write_text('interrupted')
        with patch.object(collect, 'ROOT', self.root), patch.object(collect, 'GOSI', self.root / s.h.REPORT_PATH), \
                patch.object(collect, 'collect_one') as request:
            self.assertEqual(collect.main(), 1)
            request.assert_not_called()
        with patch.object(vision, 'ROOT', self.root), patch.object(vision, 'read_table') as request:
            with self.assertRaises(ValueError):
                vision.main()
            request.assert_not_called()

    def test_queued_successor_without_jobs_is_not_a_predecessor(self):
        _, raw, _ = self.bundle()
        fetch, outer, run, _ = self.metadata(raw)
        successor = dict(run, id=101, status='queued', conclusion=None, head_sha='a' * 40)
        def queued(url):
            if '/JARVIS-Deep-Analysis.yml/runs?' in url:
                return {'total_count': 2, 'workflow_runs': [successor, run]}
            if '/runs/101/' in url and '/jobs?' in url:
                return {'total_count': 0, 'jobs': []}
            return fetch(url)
        result = s.restore_latest(self.root, fetch_json=queued, fetch_bytes=lambda _: outer,
                                  current_run_id='99', current_attempt='1')
        self.assertEqual(result['source_run_id'], 11)

    def test_active_attempt_with_a_job_is_a_hold(self):
        _, raw, _ = self.bundle()
        fetch, _, run, _ = self.metadata(raw)
        active = dict(run, id=12, status='in_progress', conclusion=None)
        def running(url):
            if '/JARVIS-Deep-Analysis.yml/runs?' in url:
                return {'total_count': 2, 'workflow_runs': [run, active]}
            return fetch(url)
        with self.assertRaisesRegex(s.Blocked, 'prior_source_run_still_active'):
            self.restore(raw, fetch=running)
        self.assertTrue((self.root / s.h.CONTINUITY_PENDING).exists())

    def test_discovery_calls_are_bounded_and_capacity_is_not_absent_history(self):
        _, raw, _ = self.bundle()
        fetch, _, run, _ = self.metadata(raw)
        calls = []
        def counted(url):
            calls.append(url)
            if '/JARVIS-Deep-Analysis.yml/runs?' in url:
                return {'total_count': 2, 'workflow_runs': [run, dict(run, id=12)]}
            return fetch(url)
        with patch.object(s, 'MAX_DETAIL_CALLS', 0), self.assertRaisesRegex(s.Blocked, 'attempt_detail_budget_exhausted'):
            self.restore(raw, fetch=counted)
        self.assertEqual(sum('/workflows/' in x for x in calls), 3)
        self.assertEqual(sum('/jobs?' in x for x in calls), 1)  # authenticated seed only
        self.assertFalse((self.root / s.h.CONTINUITY_PROOF).exists())

    def test_restore_timeout_before_api_can_pack_forensics_without_verified_proof(self):
        def offline(_):
            self.assertTrue((self.root / s.h.CONTINUITY_PENDING).is_file())
            raise TimeoutError('injected restore interruption')
        with self.assertRaises(TimeoutError):
            s.restore_latest(self.root, fetch_json=offline, current_run_id='99', current_attempt='1')
        lineage = s._lineage(s.REPOSITORY, '99', '1', self.commit)
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': s.REPOSITORY,
                'GITHUB_RUN_ID': '99', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': self.commit}):
            result = s.pack(self.root, self.archive, **lineage)
        self.assertEqual(result['status'], 'packed_recovery_required')
        self.assertFalse((self.root / s.h.CONTINUITY_PROOF).exists())

    def test_event_and_data_only_checkout_bindings_roundtrip(self):
        self.advance()
        self.git(self.producer, 'add', 'data')
        self.git(self.producer, 'commit', '-qm', 'queued data-only publication')
        tip = s._head(self.producer)
        self.git(self.root, 'fetch', '-q', str(self.producer), 'HEAD')
        self.git(self.root, 'checkout', '-q', '--detach', tip)
        document = json.loads((self.producer / s.h.REPORT_PATH).read_bytes())
        document['provider_stops'] = [self.stop()]
        s.h.publish_observation(self.producer, document)
        s.pack(self.producer, self.archive, **self.lineage)
        raw = self.archive.read_bytes()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            manifest = json.loads(archive.read(s.MANIFEST))
        self.assertEqual(manifest['lineage']['commit'], self.commit)
        self.assertEqual(manifest['checkout_commit'], tip)
        self.assertEqual(self.restore(raw)['status'], 'authenticated_gosi_restored')
        proof = json.loads((self.root / s.h.CONTINUITY_PROOF).read_bytes())
        self.assertEqual((proof['event_sha'], proof['head']), (self.commit, tip))
        self.assertEqual(json.loads((self.root / s.h.REPORT_PATH).read_bytes()), document)

    def test_checkout_producer_policy_change_and_nonancestor_rejected(self):
        self.save(self.producer, 'config/new-policy.json', {'changed': True})
        self.git(self.producer, 'add', 'config')
        self.git(self.producer, 'commit', '-qm', 'producer policy changed')
        with self.assertRaisesRegex(s.Blocked, 'checkout_producer_policy_changed'):
            s.pack(self.producer, self.archive, **self.lineage)
        with self.assertRaisesRegex(s.Blocked, 'checkout_not_event_descendant'):
            s._checkout_binding(self.producer, 'f' * 40, s._head(self.producer))

    def test_committed_history_over_payload_cap_uses_exact_git_base_and_small_delta(self):
        # Existing bytes exceed the wire limit without increasing it or pruning.
        history = self.root / s.h.HISTORY_PATH
        history.mkdir(parents=True)
        originals = {}
        for index in range(35):
            doc = dict(self.doc, retained_padding='A' * (1024 * 1024), fixture_sequence=index)
            raw = s._bytes(doc)
            path = history / (s.h.sha(raw) + '.json')
            path.write_bytes(raw)
            originals[path.relative_to(self.root).as_posix()] = s.h.sha(raw)
        self.doc = doc
        self.save(self.root, s.h.REPORT_PATH, self.doc)
        self.git(self.root, 'add', 'data')
        self.git(self.root, 'commit', '-qm', 'large immutable authenticated base')
        self.commit = s._head(self.root)
        self.lineage = s._lineage(s.REPOSITORY, '11', '1', self.commit)
        self.producer = self.clone('large-producer')
        self.old = (self.root / s.h.REPORT_PATH).read_bytes()
        expected = self.advance(stop=self.stop())
        result = s.pack(self.producer, self.archive, **self.lineage)
        self.assertEqual(result['base_file_count'], 35)
        with zipfile.ZipFile(self.archive) as archive:
            self.assertLess(sum(x.file_size for x in archive.infolist()), s.MAX_TOTAL_BYTES)
            self.assertTrue(set(originals).isdisjoint(archive.namelist()))
        incoming = s._archive(self.archive.read_bytes(), self.lineage, root=self.root)
        s.restore_files(self.root, incoming, lineage=self.lineage, run_id='99', run_attempt='1')
        self.assertEqual(json.loads((self.root / s.h.REPORT_PATH).read_bytes()), expected)
        for name, digest in originals.items():
            self.assertEqual(s.h.sha((self.root / name).read_bytes()), digest)
        # The next published base starts a fresh bounded delta, retaining all history.
        self.git(self.root, 'add', 'data')
        self.git(self.root, 'commit', '-qm', 'publish exact delta without pruning')
        next_lineage = s._lineage(s.REPOSITORY, '99', '1', self.commit)
        s.pack(self.root, self.base / 'next.zip', **next_lineage)
        self.assertTrue(s.collection_admission(self.root, reserve_bytes=4 * len(self.old)))
        self.assertFalse(s.collection_admission(self.root, reserve_bytes=s.MAX_TOTAL_BYTES))

    def test_base_inventory_tamper_and_missing_base_bytes_fail_closed(self):
        s.h.publish_observation(self.root, self.doc)
        self.git(self.root, 'add', 'data')
        self.git(self.root, 'commit', '-qm', 'authenticated base history')
        self.commit = s._head(self.root)
        self.lineage = s._lineage(s.REPOSITORY, '11', '1', self.commit)
        source = self.clone('base-source')
        s.pack(source, self.archive, **self.lineage)
        with zipfile.ZipFile(self.archive) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(files[s.MANIFEST])
        manifest['base']['inventory_sha256'] = '0' * 64
        files[s.MANIFEST] = s._bytes(manifest)
        bad = io.BytesIO()
        with zipfile.ZipFile(bad, 'w') as archive:
            for name, raw in files.items():
                archive.writestr(name, raw)
        with self.assertRaisesRegex(s.Blocked, 'base_inventory_mismatch'):
            s._archive(bad.getvalue(), self.lineage, root=self.root)
        incoming = s._archive(self.archive.read_bytes(), self.lineage, root=self.root)
        next((self.root / s.h.HISTORY_PATH).glob('*.json')).unlink()
        with self.assertRaisesRegex(s.Blocked, 'head_history_missing'):
            s.restore_files(self.root, incoming, lineage=self.lineage, run_id='99', run_attempt='1')

    def test_authenticated_coverage_skips_500_old_job_queries_with_complete_pagination(self):
        self.advance()
        covered = {str(i): [1, 0, self.commit] for i in range(1000, 1500)}
        s._proof(self.producer, s._snapshot(self.producer), run_id='11', run_attempt='1',
                 source={}, coverage=covered)
        s.pack(self.producer, self.archive, **self.lineage)
        raw = self.archive.read_bytes()
        fetch, outer, seed, _ = self.metadata(raw)
        rows = [dict(seed, id=i) for i in reversed(range(1000, 1500))] + [seed]
        calls = []
        def many(url):
            calls.append(url)
            if '/JARVIS-Deep-Analysis.yml/runs?' in url:
                page = int(url.rsplit('page=', 1)[1])
                return {'total_count': len(rows), 'workflow_runs': rows[(page - 1) * 100:page * 100]}
            return fetch(url)
        with patch.object(s, 'MAX_DETAIL_CALLS', 0):
            result = s.restore_latest(self.root, fetch_json=many, fetch_bytes=lambda _: outer,
                                      current_run_id='99', current_attempt='1')
        self.assertEqual(result['source_run_id'], 11)
        self.assertEqual(sum('/workflows/' in x for x in calls), 16)
        self.assertEqual(sum('/jobs?' in x for x in calls), 1)
        proof = json.loads((self.root / s.h.CONTINUITY_PROOF).read_bytes())
        self.assertEqual(len(proof['coverage']), 501)

    def test_coverage_deletion_attempt_regression_and_metadata_rebinding_fail_closed(self):
        self.advance()
        s._proof(self.producer, s._snapshot(self.producer), run_id='11', run_attempt='1',
                 source={}, coverage={'7': [2, 0, self.commit]})
        s.pack(self.producer, self.archive, **self.lineage)
        raw = self.archive.read_bytes()
        for kind in ('missing', 'attempt', 'commit'):
            fetch, outer, seed, _ = self.metadata(raw)
            previous = dict(seed, id=7, run_attempt=2)
            if kind == 'attempt': previous['run_attempt'] = 1
            if kind == 'commit': previous['head_sha'] = 'f' * 40
            rows = [seed] if kind == 'missing' else [previous, seed]
            def altered(url):
                if '/JARVIS-Deep-Analysis.yml/runs?' in url:
                    return {'total_count': len(rows), 'workflow_runs': rows}
                return fetch(url)
            with self.subTest(kind=kind), self.assertRaisesRegex(s.Blocked, 'covered_history_missing_or_regressed'):
                s.restore_latest(self.clone('coverage-' + kind), fetch_json=altered, fetch_bytes=lambda _: outer,
                                  current_run_id='99', current_attempt='1')

    def test_seed_cannot_absorb_unknown_failed_precheckpoint_execution(self):
        _, raw, _ = self.bundle()
        fetch, _, seed, _ = self.metadata(raw)
        previous = dict(seed, id=7)
        def unknown(url):
            if '/JARVIS-Deep-Analysis.yml/runs?' in url:
                return {'total_count': 2, 'workflow_runs': [seed, previous]}
            if '/runs/7/attempts/1/jobs?' in url:
                return {'total_count': 1, 'jobs': [{'completed_at': '2020-01-01T00:00:00Z'}]}
            return fetch(url)
        with self.assertRaisesRegex(s.Blocked, 'uncovered_precheckpoint_execution'):
            self.restore(raw, fetch=unknown)
        self.assertFalse((self.root / s.h.CONTINUITY_PROOF).exists())

    def test_coverage_producer_binding_cannot_be_changed_inside_authenticated_archive(self):
        _, raw, _ = self.bundle()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(files[s.MANIFEST])
        manifest['coverage']['11'][0] = 2
        files[s.MANIFEST] = s._bytes(manifest)
        altered = io.BytesIO()
        with zipfile.ZipFile(altered, 'w') as archive:
            for name, body in files.items():
                archive.writestr(name, body)
        with self.assertRaisesRegex(s.Blocked, 'coverage_producer_binding_invalid'):
            self.restore(altered.getvalue())

    def test_later_checkpoint_must_retain_authenticated_coverage_and_latest_stop(self):
        self.advance()
        s._proof(self.producer, s._snapshot(self.producer), run_id='11', run_attempt='1',
                 source={}, coverage={'7': [1, 0, self.commit]})
        s.pack(self.producer, self.archive, **self.lineage)
        old_raw = self.archive.read_bytes()
        for retain in (False, True):
            doc = json.loads((self.producer / s.h.REPORT_PATH).read_bytes())
            doc['provider_stops'] = [self.stop()]
            s.h.publish_observation(self.producer, doc)
            covered = {'7': [1, 0, self.commit], '11': [1, 0, self.commit]} if retain else {}
            s._proof(self.producer, s._snapshot(self.producer), run_id='12', run_attempt='1',
                     source={}, coverage=covered)
            next_lineage = s._lineage(s.REPOSITORY, '12', '1', self.commit)
            s.pack(self.producer, self.archive, **next_lineage)
            new_raw = self.archive.read_bytes()
            fetch, old_outer, seed, _ = self.metadata(old_raw)
            new_outer = self.outer(new_raw)
            new_run = dict(seed, id=12)
            artifact = {'id': 72, 'name': 'gosi-safety-12-1', 'expired': False,
                'workflow_run': {'id': 12, 'head_sha': self.commit, 'head_branch': 'main'},
                'archive_download_url': s.BASE + 'artifacts/72/zip', 'digest': 'sha256:' + s.h.sha(new_outer)}
            def latest(url):
                if '/JARVIS-Deep-Analysis.yml/runs?' in url:
                    return {'total_count': 3, 'workflow_runs': [new_run, dict(seed, id=7), seed]}
                if '/runs/12/attempts/1/jobs?' in url:
                    return {'total_count': 1, 'jobs': [{'completed_at': datetime.now(timezone.utc).isoformat()}]}
                if '/runs/12/artifacts?' in url:
                    return {'total_count': 1, 'artifacts': [artifact]}
                return fetch(url)
            target = self.clone('coverage-retain-' + str(retain))
            kwargs = dict(fetch_json=latest, fetch_bytes=lambda url: new_outer if '/72/' in url else old_outer,
                          current_run_id='99', current_attempt='1')
            if retain:
                result = s.restore_latest(target, **kwargs)
                self.assertEqual(result['source_run_id'], 12)
                self.assertEqual(json.loads((target / s.h.REPORT_PATH).read_bytes())['provider_stops'], doc['provider_stops'])
            else:
                with self.assertRaisesRegex(s.Blocked, 'checkpoint_coverage_regressed'):
                    s.restore_latest(target, **kwargs)

    def test_missing_duplicate_and_short_pages_fail_closed(self):
        _, raw, _ = self.bundle()
        fetch, _, seed, _ = self.metadata(raw)
        for kind in ('missing', 'duplicate', 'short'):
            def pages(url):
                if '/JARVIS-Deep-Analysis.yml/runs?' in url:
                    page = int(url.rsplit('page=', 1)[1])
                    if kind == 'duplicate':
                        return {'total_count': 2, 'workflow_runs': [seed, seed]}
                    if page == 1:
                        return {'total_count': 101, 'workflow_runs': [dict(seed, id=i) for i in range(1000, 1100)]}
                    return {'total_count': 101, 'workflow_runs': []}
                return fetch(url)
            with self.subTest(kind=kind), self.assertRaises(s.Blocked):
                s.restore_latest(self.clone('pages-' + kind), fetch_json=pages,
                                 fetch_bytes=lambda _: self.outer(raw), current_run_id='99', current_attempt='1')

    def test_attempt_and_updated_at_races_during_listing_block_before_write(self):
        _, raw, _ = self.bundle()
        for kind in ('attempt', 'updated_at', 'added_run'):
            fetch, outer, seed, _ = self.metadata(raw)
            listings = 0
            def racing(url):
                nonlocal listings
                if '/JARVIS-Deep-Analysis.yml/runs?' in url:
                    listings += 1
                    row = deepcopy(seed)
                    rows = [row]
                    if listings == 2:
                        if kind == 'attempt': row['run_attempt'] = 2
                        elif kind == 'updated_at': row['updated_at'] = datetime.now(timezone.utc).isoformat()
                        else: rows.append(dict(row, id=123, status='queued'))
                    return {'total_count': len(rows), 'workflow_runs': rows}
                return fetch(url)
            target = self.clone('racing-' + kind)
            with self.subTest(kind=kind), self.assertRaisesRegex(s.Blocked, 'run_history_changed_during_restore'):
                s.restore_latest(target, fetch_json=racing, fetch_bytes=lambda _: outer,
                                 current_run_id='99', current_attempt='1')
            self.assertEqual((target / s.h.REPORT_PATH).read_bytes(), self.old)
            self.assertTrue((target / s.h.CONTINUITY_PENDING).exists())
            self.assertFalse((target / s.h.CONTINUITY_PROOF).exists())

    def test_seed_duplicate_or_changed_artifact_binding_fails_closed(self):
        _, raw, _ = self.bundle()
        for kind in ('duplicate', 'changed'):
            fetch, outer, _, artifact = self.metadata(raw)
            def ambiguous(url):
                if '/runs/11/artifacts?' in url:
                    rows = [deepcopy(artifact), deepcopy(artifact)] if kind == 'duplicate' else [dict(artifact, id=72)]
                    return {'total_count': len(rows), 'artifacts': rows}
                return fetch(url)
            target = self.clone('seed-binding-' + kind)
            with self.subTest(kind=kind), self.assertRaisesRegex(s.Blocked, 'coverage_seed_artifact_ambiguous_or_changed'):
                s.restore_latest(target, fetch_json=ambiguous, fetch_bytes=lambda _: outer,
                                 current_run_id='99', current_attempt='1')
            self.assertFalse((target / s.h.CONTINUITY_PROOF).exists())

    def test_standalone_setup_shells_bound_hangs_before_later_installation(self):
        import shutil
        import signal
        import sys
        import time
        if not shutil.which('timeout'):
            self.skipTest('GNU timeout is required for Ubuntu workflow fixture')
        checkout = Path(__file__).resolve().parents[1]
        for filename, name in [('gosi-alt.yml', '브라우저 설치'), ('gosi-vision.yml', 'Install dependencies')]:
            value = (checkout / '.github/workflows' / filename).read_text()
            step = value.split('      - name: ' + name + '\n', 1)[1].split('\n      - ', 1)[0]
            self.assertIn('timeout-minutes: 5', step)
            self.assertIn('timeout --signal=TERM --kill-after=5s 280s', step)
            body = '\n'.join(line[10:] for line in step.split('        run: |\n', 1)[1].splitlines())
            body = body.replace('--kill-after=5s 280s', '--kill-after=0.2s 0.2s')
            binaries = self.base / ('setup-bin-' + filename)
            binaries.mkdir()
            started, later = self.base / ('setup-' + filename), self.base / ('later-' + filename)
            child = self.base / ('child-' + filename)
            program = binaries / 'python'
            program.write_text('#!' + sys.executable + "\n"
                'import os, signal, time\n'
                'signal.signal(signal.SIGTERM, signal.SIG_DFL)\n'
                'pid = os.fork()\n'
                'if pid == 0:\n'
                ' signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
                ' open(os.environ["CHILD"], "w").write(str(os.getpid()))\n'
                ' while True: time.sleep(1)\n'
                'open(os.environ["STARTED"], "w").write(str(os.getpid()))\n'
                'while True: time.sleep(1)\n')
            (binaries / 'playwright').write_text('#!/bin/sh\ntouch "$LATER"\n')
            for executable in binaries.iterdir(): executable.chmod(0o755)
            env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH'],
                       STARTED=str(started), LATER=str(later), CHILD=str(child))
            start = time.monotonic()
            try:
                result = subprocess.run(['bash', '-e', '-c', body], cwd=self.base, env=env,
                                        capture_output=True, timeout=3)
                self.assertIn(result.returncode, (124, 137, -9))
                self.assertLess(time.monotonic() - start, 2)
                self.assertTrue(started.exists())
                self.assertTrue(child.exists())
                process = Path('/proc') / child.read_text().strip()
                self.assertTrue(not process.exists() or process.joinpath('stat').read_text().split()[2] == 'Z')
                self.assertFalse(later.exists())
            finally:
                # If this regression fails, terminate only this fixture child.
                if child.exists():
                    pid = int(child.read_text())
                    command = Path('/proc') / str(pid) / 'cmdline'
                    try:
                        if str(program).encode() in command.read_bytes():
                            os.kill(pid, signal.SIGKILL)
                    except (FileNotFoundError, ProcessLookupError):
                        pass

    def test_standalone_product_input_is_one_quoted_environment_argument(self):
        import sys
        checkout = Path(__file__).resolve().parents[1]
        value = (checkout / '.github/workflows/gosi-alt.yml').read_text()
        step = value.split('      - name: alt 에서 고시 꺼내기\n', 1)[1].split('\n      - ', 1)[0]
        self.assertIn('PD_NO: ${{ inputs.pd_no }}', step)
        body = '\n'.join(line[10:] for line in step.split('        run: |\n', 1)[1].splitlines())
        self.assertNotIn('${{', body)
        binaries = self.base / 'input-bin'
        binaries.mkdir()
        program = binaries / 'python'
        program.write_text('#!' + sys.executable + '\nimport json,os,sys\nopen(os.environ["ARG_LOG"],"w").write(json.dumps(sys.argv[1:]))\n')
        program.chmod(0o755)
        log, injected = self.base / 'arguments.json', self.base / 'should-not-exist'
        malicious = '1234567"; touch ' + str(injected) + '; #'
        env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH'], PD_NO=malicious, ARG_LOG=str(log))
        subprocess.run(['bash', '-e', '-c', body], cwd=self.base, env=env, check=True, capture_output=True, timeout=3)
        self.assertEqual(json.loads(log.read_bytes()), ['-u', 'scripts/daiso/collect_gosi_alt.py', malicious])
        self.assertFalse(injected.exists())

    def test_standalone_workflows_restore_and_preserve_before_publication(self):
        checkout = Path(__file__).resolve().parents[1]
        for name, collector in [('gosi-alt.yml', '      - name: alt 에서 고시 꺼내기'),
                                ('gosi-vision.yml', '      - name: Collect DAISO GOSI images')]:
            value = (checkout / '.github/workflows' / name).read_text()
            with self.subTest(workflow=name):
                self.assertIn('  actions: read', value)
                self.assertLess(value.index('id: gosi_safety'), value.index(collector))
                self.assertLess(value.index('gosi-safety-${{ github.run_id }}'), value.index('uses: ./.github/actions/publish'))
                self.assertIn("steps.gosi_checkpoint.outcome == 'success'", value)
                self.assertIn('if-no-files-found: error', value)


if __name__ == '__main__':
    unittest.main()
