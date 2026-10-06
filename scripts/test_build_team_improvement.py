"""Offline regression fixtures for the diagnostic writer and runtime projection.

Every input lives in a temporary root. No production data, providers, network,
credentials, subprocesses, or repository data files are accessed.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import build_team_improvement as builder
import team_improvement_evidence as evidence


CAP = 8 * 1024 * 1024
RUNTIME_CLOCK = '2026-10-03T10:00:00+00:00'
PREVIOUS_CLOCK = '2026-10-02T10:00:00+00:00'
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is not None else NOW.replace(tzinfo=None)


class BuildTeamImprovementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='team-improvement-offline-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.runtime_path = self.data / 'dashboard_runtime.json'
        self.out_path = self.data / 'team_improvement.json'
        globals_patch = mock.patch.multiple(
            builder, ROOT=self.root, DATA=self.data,
            RUNTIME=self.runtime_path, OUT=self.out_path, datetime=FixedDatetime)
        globals_patch.start()
        self.addCleanup(globals_patch.stop)
        self.runtime = {
            'generated_at': RUNTIME_CLOCK,
            'updated_at': '2026-10-03T09:59:00+00:00',
            'captured_at': '2026-10-01T08:00:00+00:00',
            'source_capture_at': '2026-09-30T08:00:00+00:00',
            'sources': {'synthetic': {
                'generated_at': '2026-09-29T08:00:00+00:00',
                'captured_at': '2026-09-28T08:00:00+00:00'}},
            'teams': [
                {'id': tid, 'name': tid, 'action': '', 'action_kind': '',
                 'status': 'synthetic', 'summary': 'offline fixture',
                 'generated_at': '2026-09-27T08:00:00+00:00',
                 'captured_at': '2026-09-26T08:00:00+00:00'}
                for tid in evidence.TEAM_IDS
            ],
            'team_improvement_evidence': {'stale_fixture': True},
        }
        self.write_json(self.runtime_path, self.runtime)

    @staticmethod
    def write_json(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False) + '\n', encoding='utf-8')

    @staticmethod
    def read_json(path):
        return json.loads(path.read_text(encoding='utf-8'))

    def run_builder(self):
        with redirect_stdout(io.StringIO()):
            return builder.main()

    def snapshot_files(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def assert_rejected_without_mutation(self, exception=ValueError):
        before = self.snapshot_files()
        with mock.patch.object(evidence, 'build', wraps=evidence.build) as project:
            with self.assertRaises(exception):
                self.run_builder()
            project.assert_not_called()
        self.assertEqual(self.snapshot_files(), before)

    def previous(self, history=None, runtime_at=PREVIOUS_CLOCK):
        return {
            'generated_at': PREVIOUS_CLOCK, 'runtime_at': runtime_at,
            'teams': {}, 'history': [] if history is None else history,
        }

    def test_prior_137_rows_retained_exactly_and_one_current_row_appended(self):
        history = [
            {'at': '2026-01-01T00:00:00+00:00', 'runtime_at': f'round-{n}',
             'teams': 11, 'fixture_marker': n,
             'extra': {'unicode': 'retained \uac00', 'values': [n, None, False]}}
            for n in range(137)
        ]
        before = copy.deepcopy(history)
        self.write_json(self.out_path, self.previous(history))
        self.assertEqual(self.run_builder(), 0)
        result = self.read_json(self.out_path)
        self.assertEqual(len(result['history']), 138)
        self.assertEqual(result['history'][:-1], before)
        self.assertEqual(result['history'][-1]['runtime_at'], RUNTIME_CLOCK)
        self.assertEqual(result['history'][-1]['teams'], 11)
        self.assertEqual(result['runtime_at'], RUNTIME_CLOCK)

    def test_same_runtime_preserves_all_history_and_streak_on_repeated_runs(self):
        self.runtime['teams'][0].update(action='revalidate synthetic fixture',
                                        action_kind='revalidate_only')
        self.write_json(self.runtime_path, self.runtime)
        prior = self.previous(
            [{'runtime_at': f'round-{n}', 'marker': n} for n in range(123)],
            runtime_at=RUNTIME_CLOCK)
        prior['teams']['sourcing'] = {
            'open_action': 'revalidate synthetic fixture',
            'open_kind': 'revalidate_only', 'streak': 7,
            'since': '2026-09-20T00:00:00+00:00'}
        self.write_json(self.out_path, prior)
        for _ in range(3):
            self.assertEqual(self.run_builder(), 0)
            result = self.read_json(self.out_path)
            self.assertEqual(result['history'], prior['history'])
            self.assertEqual(result['teams']['sourcing']['streak'], 7)
            self.assertEqual(result['teams']['sourcing']['since'],
                             prior['teams']['sourcing']['since'])
            self.assertTrue(result['teams']['sourcing']['stale'])

    def test_new_runtime_bumps_streak_once_then_rerun_adds_no_row(self):
        self.runtime['teams'][0].update(action='revalidate synthetic fixture',
                                        action_kind='revalidate_only')
        self.write_json(self.runtime_path, self.runtime)
        prior = self.previous([{'runtime_at': PREVIOUS_CLOCK}])
        prior['teams']['sourcing'] = {
            'open_action': 'revalidate synthetic fixture',
            'open_kind': 'revalidate_only', 'streak': 2,
            'since': PREVIOUS_CLOCK}
        self.write_json(self.out_path, prior)
        self.assertEqual(self.run_builder(), 0)
        first = self.read_json(self.out_path)
        self.assertEqual(first['teams']['sourcing']['streak'], 3)
        self.assertEqual(len(first['history']), 2)
        self.assertEqual(self.run_builder(), 0)
        second = self.read_json(self.out_path)
        self.assertEqual(second['history'], first['history'])
        self.assertEqual(second['teams']['sourcing']['streak'], 3)

    def test_projection_reads_just_written_diagnostic_and_binds_current_hash(self):
        self.write_json(self.out_path, self.previous())
        old_hash = hashlib.sha256(self.out_path.read_bytes()).hexdigest()
        original_build = evidence.build
        observed = []

        def inspect_current(root, **kwargs):
            current_bytes = self.out_path.read_bytes()
            current = json.loads(current_bytes)
            self.assertEqual(current['runtime_at'], RUNTIME_CLOCK)
            self.assertEqual(current['generated_at'], NOW.isoformat())
            self.assertEqual(len(current['history']), 1)
            observed.append(hashlib.sha256(current_bytes).hexdigest())
            return original_build(root, **kwargs)

        with mock.patch.object(evidence, 'build', side_effect=inspect_current) as project:
            self.assertEqual(self.run_builder(), 0)
            project.assert_called_once_with(self.root, now=NOW.isoformat())
        projection = self.read_json(self.runtime_path)['team_improvement_evidence']
        source = projection['diagnostic_monitoring']['source']
        self.assertIsNotNone(source)
        current_hash = hashlib.sha256(self.out_path.read_bytes()).hexdigest()
        self.assertNotEqual(current_hash, old_hash)
        self.assertEqual(observed, [current_hash])
        self.assertEqual(source['sha256'], current_hash)
        self.assertEqual(source['path'], 'data/team_improvement.json')
        self.assertEqual(source['generated_at'], NOW.isoformat())
        self.assertEqual(source['metadata_clock_field'], 'generated_at')
        self.assertEqual(source['metadata_clock_at'], NOW.isoformat())
        self.assertIsNone(source['captured_at'])
        self.assertIsNone(source['evaluated_at'])
        self.assertFalse(source['capture_clock_verified'])
        self.assertTrue(source['fresh'])
        self.assertEqual(projection['summary']['verified_gains'], 0)
        self.assertFalse(projection['summary']['authority'])
        for team in projection['teams'].values():
            diagnostic = [row for row in team['evidence']
                          if row['path'] == 'data/team_improvement.json']
            self.assertEqual(len(diagnostic), 1)
            self.assertEqual(diagnostic[0]['sha256'], current_hash)

    def test_runtime_capture_generated_clocks_and_all_other_fields_preserved(self):
        before = copy.deepcopy(self.runtime)
        self.assertEqual(self.run_builder(), 0)
        after = self.read_json(self.runtime_path)
        projection = after.pop('team_improvement_evidence')
        before.pop('team_improvement_evidence')
        self.assertEqual(after, before)
        self.assertEqual(projection['generated_at'], NOW.isoformat())
        self.assertNotEqual(after['generated_at'], projection['generated_at'])

    def test_missing_diagnostic_starts_new_history_without_production_inputs(self):
        self.assertFalse(self.out_path.exists())
        self.assertEqual(self.run_builder(), 0)
        result = self.read_json(self.out_path)
        self.assertEqual(len(result['history']), 1)
        self.assertEqual(set(result['teams']), set(evidence.TEAM_IDS))
        self.assertEqual(set(self.snapshot_files()),
                         {'data/dashboard_runtime.json', 'data/team_improvement.json'})

    def test_malformed_existing_json_never_resets_or_mutates_files(self):
        for path in (self.runtime_path, self.out_path):
            for raw in (b'{broken', b'{"history":', b'\xff\xfe'):
                with self.subTest(path=path.name, raw=raw):
                    self.write_json(self.runtime_path, self.runtime)
                    self.write_json(self.out_path, self.previous())
                    path.write_bytes(raw)
                    self.assert_rejected_without_mutation((ValueError, UnicodeError))

    def test_existing_non_object_json_rejected_without_mutation(self):
        for path in (self.runtime_path, self.out_path):
            for value in ([], None, True, 17, 'not an object'):
                with self.subTest(path=path.name, value=value):
                    self.write_json(self.runtime_path, self.runtime)
                    self.write_json(self.out_path, self.previous())
                    self.write_json(path, value)
                    self.assert_rejected_without_mutation()

    def test_non_list_history_rejected_without_reset(self):
        for history in ({'old_round': 1}, 'old_round', 1):
            with self.subTest(history=history):
                self.write_json(self.out_path, self.previous(history))
                self.assert_rejected_without_mutation()

    def test_oversized_runtime_read_fails_closed_without_mutation(self):
        self.write_json(self.out_path, self.previous())
        raw = json.dumps(self.runtime).encode('utf-8')
        self.runtime_path.write_bytes(raw + b' ' * (CAP + 1 - len(raw)))
        self.assertEqual(self.runtime_path.stat().st_size, CAP + 1)
        self.assert_rejected_without_mutation()

    def test_oversized_existing_diagnostic_read_fails_closed_without_mutation(self):
        raw = json.dumps(self.previous()).encode('utf-8')
        self.out_path.write_bytes(raw + b' ' * (CAP + 1 - len(raw)))
        self.assertEqual(self.out_path.stat().st_size, CAP + 1)
        self.assert_rejected_without_mutation()

    def test_exact_8mib_load_boundary_is_accepted_not_reset(self):
        value = {'history': [{'marker': 'retained'}]}
        raw = json.dumps(value).encode('utf-8')
        self.out_path.write_bytes(raw + b' ' * (CAP - len(raw)))
        self.assertEqual(builder.load(self.out_path, {'wrong': 'fallback'}), value)
        self.assertEqual(self.out_path.stat().st_size, CAP)

    def test_diagnostic_write_cap_preserves_history_and_runtime_ascii_and_utf8(self):
        for char in ('x', '\uac00'):
            with self.subTest(char=char):
                # Input is below the byte cap; current diagnostic cards plus
                # pretty-printing push the complete serialized output above it.
                count = (CAP - 1024) // len(char.encode('utf-8'))
                prior = self.previous([{'fixture_padding': char * count}])
                self.write_json(self.out_path, prior)
                self.assertLess(self.out_path.stat().st_size, CAP)
                self.assert_rejected_without_mutation()


if __name__ == '__main__':
    unittest.main()
