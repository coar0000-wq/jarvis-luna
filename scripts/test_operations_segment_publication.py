"""Offline snapshot/collector publication adversaries, only local Git remotes."""
from copy import deepcopy
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import jarvis_operations as core
import jarvis_watch as watch
from scripts import collector_snapshot_history as collector
from scripts import operations_publication as operations
from scripts import operations_storage as storage
from scripts import publish_transaction as pub
from scripts import restore_operations_safety as safety

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / 'config/publish_policy.json').read_bytes())


def body(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def write(root, files):
    for name, raw in files.items():
        path = Path(root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


def advance(files, goal='second task'):
    state = storage.operations_state_from_files(files)
    core.create_task(state, goal=goal, team='market', payload={})
    return {**files, **storage.prepare_operations_state(state, files[operations.STATE], files.__getitem__, force=True)}


class OfflineTransaction(pub.Transaction):
    def regenerate_and_validate(self, work, *args):
        pass


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='operations-segment-publication-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.root = self.folder / 'local'
        self.remote = self.folder / 'remote.git'
        self.other = self.folder / 'other'
        self.environment = patch.dict(os.environ, {'GITHUB_ACTIONS': 'false', 'RUNNER_TEMP': str(self.folder)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        pub.git(self.folder, 'init', '--bare', str(self.remote))
        pub.git(self.folder, 'init', '-b', 'main', str(self.root))
        pub.git(self.root, 'config', 'user.name', 'Offline fixture')
        pub.git(self.root, 'config', 'user.email', 'fixture@example.invalid')
        state = core.empty_state()
        core.create_task(state, goal='initial task', team='legal', payload={})
        self.base = {operations.STATE: body(state), safety.LEDGER: b'{ }\n',
                     'data/operations/reports/original.json': b'{ "original": true }\n'}
        write(self.root, {**self.base, 'config/publish_policy.json': body(POLICY),
                         'data/publish_deletions.json': body({'schema_version': 1, 'deletions': []}),
                         'data/unrelated.json': b'{"untouched":true}\n'})
        self.commit(self.root)
        pub.git(self.root, 'remote', 'add', 'origin', str(self.remote))
        pub.git(self.root, 'push', '-u', 'origin', 'main')
        pub.git(self.folder, 'clone', '-b', 'main', str(self.remote), str(self.other))
        pub.git(self.other, 'config', 'user.name', 'Offline fixture')
        pub.git(self.other, 'config', 'user.email', 'fixture@example.invalid')

    def commit(self, root):
        pub.git(root, 'add', '-A')
        pub.git(root, 'commit', '-m', 'offline fixture')

    def migrate(self, source=None, state=None):
        source = self.base if source is None else source
        logical = storage.operations_state_from_files(source) if state is None else state
        self.candidate = {**source, **storage.prepare_operations_state(logical, source[operations.STATE], source.__getitem__, force=True)}
        write(self.root, self.candidate)
        return self.candidate

    def transaction(self, cls=OfflineTransaction, paths='data/operations/ data/publish_deletions.json'):
        return cls(self.root, paths, 'offline operations fixture', audit=False)

    def tip(self):
        return pub.git(self.remote, 'rev-parse', 'main').stdout.strip()

    def test_exact_migration_publishes_whole_snapshot_without_json_overlay(self):
        expected = self.migrate()
        before_unrelated = (self.root / 'data/unrelated.json').read_bytes()
        transaction = self.transaction()
        with patch.object(pub, 'overlay', wraps=pub.overlay) as overlay:
            result = transaction.run()
        self.assertEqual(result['status'], 'published')
        self.assertFalse(any(operations.owns(call.args[0]) for call in overlay.call_args_list))
        self.assertEqual(operations.git_snapshot(self.remote, 'main'), expected)
        self.assertEqual(pub.at_ref(self.remote, 'main', 'data/unrelated.json'), before_unrelated)
        self.assertEqual(storage.operations_migration_bytes(expected[operations.STATE], expected.__getitem__), self.base[operations.STATE])

    def test_daiso_publication_paths_preserve_complete_operations_snapshot(self):
        import yaml
        workflow = yaml.load((ROOT / '.github/workflows/daiso-real-collection.yml').read_text(),
                             Loader=yaml.BaseLoader)
        publishers = [step for step in workflow['jobs']['collect']['steps']
                      if step.get('uses') == './.github/actions/publish']
        self.assertEqual(len(publishers), 2)
        for step in publishers:
            paths = step['with']['paths'].split()
            self.assertIn('data/operations', paths)
            self.assertIn('data/publish_deletions.json', paths)
            for name in (operations.STATE, operations.HISTORY + 'segment-example.json',
                         safety.LEDGER, operations.REPORTS + 'new.json',
                         'data/operations/knowledge_graph.json',
                         'data/operations/knowledge_graph/segment-example.json'):
                self.assertTrue(pub.path_allowed(name, paths), (step['name'], name))
        no_change = next(step for step in publishers if "'no_change'" in step['if'])
        self.assertIn("'candidates'", no_change['if'])
        for name in ('data/daiso_real/products.json', 'data/product_master.json',
                     'data/shopify_exports/products.csv', 'data/shopify_action_queue.json'):
            self.assertFalse(pub.path_allowed(name, no_change['with']['paths'].split()), name)

        # Exercise the real workflow's operations selection, not a guard bypass.
        # Restored/migrated state and new reports must travel as one snapshot.
        expected = self.migrate()
        report = operations.REPORTS + 'restored-new.json'
        expected[report] = b'{ "retained": true }\n'
        write(self.root, {report: expected[report]})
        paths = [name for name in no_change['with']['paths'].split()
                 if name.startswith('data/operations') or name == operations.MANIFEST]
        tx = self.transaction(paths=' '.join(paths))
        self.assertTrue(tx.operations_guard.active)
        self.assertEqual(tx.run()['status'], 'published')
        self.assertEqual(operations.git_snapshot(self.remote, 'main'), expected)

    def test_missing_or_tampered_chunk_blocks_before_publish(self):
        expected = self.migrate()
        member = next(name for name in expected if name.startswith(operations.HISTORY))
        before = self.tip()
        path = self.root / member
        for raw in (None, expected[member] + b' '):
            if raw is None:
                path.unlink()
            else:
                path.write_bytes(raw)
            with self.subTest(raw=raw is None), self.assertRaises(pub.PublishError):
                self.transaction()
            self.assertEqual(self.tip(), before)
            path.write_bytes(expected[member])

    def test_segment_members_are_byte_exact_and_tamper_is_rejected(self):
        with patch.object(storage, 'OPS_SEGMENT_TARGET_BYTES', 256):
            expected = self.migrate()
        segment = next(name for name in expected if '/segment-' in name)
        original = expected[segment]
        (self.root / segment).write_bytes(original + b' ')
        with self.assertRaises(pub.PublishError):
            self.transaction()
        (self.root / segment).write_bytes(original)
        self.assertEqual(self.transaction().run()['status'], 'published')
        self.assertEqual(pub.at_ref(self.remote, 'main', segment), original)

    def test_history_or_report_omitted_from_paths_blocks(self):
        expected = self.migrate()
        new_report = 'data/operations/reports/new.json'
        write(self.root, {new_report: b'{ "new": true }\n'})
        for paths in ('data/operations/state.json',
                      'data/operations/state.json data/operations/state/ data/publish_deletions.json'):
            with self.subTest(paths=paths), self.assertRaisesRegex(pub.PublishError, 'omitted'):
                self.transaction(paths=paths)

    def test_valid_orphan_is_preserved_exactly_and_omission_blocks(self):
        self.migrate()
        raw = b'raw interrupted prior chunk\r\n'
        orphan = operations.HISTORY + 'legacy-' + hashlib.sha256(raw).hexdigest() + '.bin'
        write(self.root, {orphan: raw})
        with self.assertRaisesRegex(pub.PublishError, 'omitted'):
            self.transaction(paths='data/operations/state.json')
        self.assertEqual(self.transaction().run()['status'], 'published')
        self.assertEqual(pub.at_ref(self.remote, 'main', orphan), raw)

    def test_history_deletion_is_not_authorized_by_generic_manifest(self):
        expected = self.migrate()
        self.commit(self.root)
        member = next(name for name in expected if name.startswith(operations.HISTORY))
        (self.root / member).unlink()
        write(self.root, {operations.MANIFEST: body({'schema_version': 1, 'deletions': [{
            'path': member, 'base_sha256': pub.sha(expected[member]), 'delete_file': True,
            'reason': 'generic deletion waiver must not apply', 'policy_ref': 'config/test'}]})})
        with self.assertRaises(pub.PublishError):
            self.transaction()

    def test_reformatted_migration_original_with_same_logical_state_blocks(self):
        source = dict(self.base, **{operations.STATE: json.dumps(json.loads(self.base[operations.STATE])).encode()})
        self.migrate(source)
        with self.assertRaisesRegex(pub.PublishError, 'original_byte_conflict'):
            self.transaction()

    def test_independent_remote_operations_changes_fail_closed(self):
        self.migrate()
        tx = self.transaction()
        remote = advance(self.base, 'independent remote task')
        write(self.other, remote)
        self.commit(self.other)
        pub.git(self.other, 'push', 'origin', 'main')
        before = self.tip()
        with self.assertRaisesRegex(pub.PublishError, 'concurrent operations snapshot'):
            tx.run()
        self.assertEqual(self.tip(), before)

    def test_final_regeneration_history_tamper_or_deletion_blocks(self):
        expected = self.migrate()
        member = next(name for name in expected if name.startswith(operations.HISTORY))
        for mode in ('tamper', 'delete', 'report', 'logical'):
            class BadGenerator(OfflineTransaction):
                def regenerate_and_validate(self, work, *args):
                    if mode == 'tamper':
                        (work / member).write_bytes(b'tampered')
                    elif mode == 'delete':
                        (work / member).unlink()
                    elif mode == 'report':
                        (work / 'data/operations/reports/original.json').write_bytes(b'{"original":true}\n')
                    else:
                        files = operations.snapshot(work)
                        logical = storage.operations_state_from_files(files)
                        logical['tasks'].clear()
                        write(work, storage.prepare_operations_state(logical, files[operations.STATE], files.__getitem__))
            before = self.tip()
            with self.subTest(mode=mode), self.assertRaises(pub.PublishError):
                self.transaction(BadGenerator).run()
            self.assertEqual(self.tip(), before)

    def test_first_migration_during_final_generation_activates_guard(self):
        write(self.root, {'data/source.json': b'{"new":true}\n'})
        class MigratingGenerator(OfflineTransaction):
            def regenerate_and_validate(self, work, *args):
                files = operations.snapshot(work)
                logical = storage.operations_state_from_files(files)
                generated = storage.prepare_operations_state(logical, files[operations.STATE], files.__getitem__, force=True)
                write(work, generated)
                self.expected = {**files, **generated}
        tx = self.transaction(MigratingGenerator, paths='data/source.json')
        self.assertFalse(tx.operations_guard.active)
        self.assertEqual(tx.run()['status'], 'published')
        self.assertTrue(tx.operations_guard.active)
        self.assertEqual(operations.git_snapshot(self.remote, 'main'), tx.expected)

    def test_first_final_migration_cannot_destroy_legacy_report(self):
        write(self.root, {'data/source.json': b'{"new":true}\n'})
        class BadMigration(OfflineTransaction):
            def regenerate_and_validate(self, work, *args):
                files = operations.snapshot(work)
                logical = storage.operations_state_from_files(files)
                write(work, storage.prepare_operations_state(logical, files[operations.STATE], files.__getitem__, force=True))
                (work / 'data/operations/reports/original.json').unlink()
        before = self.tip()
        with self.assertRaises(pub.PublishError):
            self.transaction(BadMigration, paths='data/source.json').run()
        self.assertEqual(self.tip(), before)

    def test_remote_first_migration_activates_guard_for_unchanged_local_operations(self):
        write(self.root, {'data/source.json': b'{"new":true}\n'})
        tx = self.transaction(paths='data/source.json')
        self.assertFalse(tx.operations_guard.active)
        logical = storage.operations_state_from_files(self.base)
        remote = {**self.base, **storage.prepare_operations_state(logical, self.base[operations.STATE], self.base.__getitem__, force=True)}
        write(self.other, remote)
        self.commit(self.other)
        pub.git(self.other, 'push', 'origin', 'main')
        self.assertEqual(tx.run()['status'], 'published')
        self.assertTrue(tx.operations_guard.active)
        self.assertEqual(operations.git_snapshot(self.remote, 'main'), remote)

    def test_dormant_capture_enforces_limits_before_reading_bytes(self):
        with patch.object(storage, 'OPS_SNAPSHOT_MAX_FILES', 1), self.assertRaises(ValueError):
            operations.raw_snapshot(self.root)
        with patch.object(storage, 'operations_snapshot_max_bytes', return_value=1), self.assertRaises(ValueError):
            operations.raw_snapshot(self.root)
        path = self.root / operations.STATE
        with path.open('wb') as stream:
            stream.truncate(storage.OPS_STATE_MAX_BYTES + 1)
        with self.assertRaises(ValueError):
            operations.raw_snapshot(self.root)

    def test_dormant_capture_rejects_ancestor_symlinks(self):
        outside = self.folder / 'symlink-fixture'
        (outside / 'data').mkdir(parents=True)
        (outside / 'data/operations').symlink_to(self.root / 'data/operations', target_is_directory=True)
        with self.assertRaises(ValueError):
            operations.raw_snapshot(outside)

    def test_segmented_overlay_is_never_available_as_generic_merge(self):
        expected = self.migrate()
        for name, raw in expected.items():
            if name == operations.STATE or name.startswith(operations.HISTORY):
                with self.subTest(name=name), self.assertRaises(pub.PublishError):
                    pub.overlay(name, self.base.get(name), raw, self.base.get(name), POLICY, {})

    def test_invalid_unknown_history_member_triggers_full_guard(self):
        write(self.root, {operations.HISTORY + 'unknown.json': b'{}'})
        with self.assertRaises(pub.PublishError):
            self.transaction()

    def test_missing_or_corrupt_state_cannot_hide_segmented_history(self):
        self.migrate()
        for raw in (None, b'{broken'):
            path = self.root / operations.STATE
            if raw is None:
                path.unlink()
            else:
                path.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(pub.PublishError):
                self.transaction()

    def test_collector_checks_history_even_with_unchanged_state_bytes(self):
        expected = self.migrate()
        self.commit(self.root)
        member = next(name for name in expected if name.startswith(operations.HISTORY))
        (self.root / member).write_bytes(expected[member] + b' ')
        with self.assertRaises(ValueError):
            collector.update(self.root, [operations.STATE])
        with patch.object(collector, 'ROOT', self.root), patch.object(collector.sys, 'argv', ['collector_snapshot_history.py', '--all-declared']), redirect_stdout(io.StringIO()):
            self.assertEqual(collector.main(), 1)

    def test_collector_hydrates_migration_and_never_rotates_events(self):
        expected = self.migrate()
        self.assertEqual(collector.update(self.root, [operations.STATE])[operations.STATE], 'no_removals')
        logical = storage.operations_state_from_files(expected)
        key = next(iter(logical['events']))
        del logical['events'][key]
        with self.assertRaises(ValueError):
            collector.allowed_removals(operations.STATE, storage.operations_state_from_files(self.base), logical, POLICY)
        self.assertFalse(any(pattern.split('/')[0] in ('events', 'audit') for pattern in collector.ROTATING[operations.STATE]))

    def test_final_rotation_manifest_tracks_regeneration_and_preserves_unrelated_rows(self):
        state = storage.operations_state_from_files(self.base)
        state['watch'] = watch._cursor(None)
        records = {key: {'value': {'canonical_product_id': key, 'amount': 1, 'currency': 'KRW', 'unit': 'one'},
                         'captured_at': '2026-10-21T00:00:00Z'} for key in ('old', 'keep')}
        state['watch']['sources']['pricing'] = {
            'source': watch.SOURCE_MAPPINGS['pricing'][0], 'status': 'VALID', 'records': records,
            'semantic_hash': watch.digest({key: row['value'] for key, row in records.items()})}
        self.base[operations.STATE] = body(state)
        write(self.root, self.base)
        self.commit(self.root)
        pub.git(self.root, 'push', 'origin', 'main')
        current = deepcopy(state)
        del current['watch']['sources']['pricing']['records']['old']
        current['watch']['sources']['pricing']['semantic_hash'] = watch.digest({'keep': records['keep']['value']})
        expected = self.migrate(state=current)
        collector.update(self.root, [operations.STATE])
        manifest = json.loads((self.root / operations.MANIFEST).read_bytes())
        unrelated = {'path': 'data/unrelated.json', 'policy_ref': 'unrelated policy', 'keep': 'exact row'}
        manifest['deletions'].append(unrelated)
        write(self.root, {operations.MANIFEST: body(manifest)})
        class AdvancingGenerator(OfflineTransaction):
            def regenerate_and_validate(self, work, *args):
                write(work, advance(operations.snapshot(work), 'regenerated task'))
        self.assertEqual(self.transaction(AdvancingGenerator).run()['status'], 'published')
        final = operations.git_snapshot(self.remote, 'main')
        result = json.loads(pub.at_ref(self.remote, 'main', operations.MANIFEST))
        self.assertIn(unrelated, result['deletions'])
        entry = next(row for row in result['deletions'] if row['path'] == operations.STATE)
        self.assertEqual(entry['base_sha256'], pub.sha(self.base[operations.STATE]))
        self.assertEqual(entry['replacement_sha256'], pub.sha(final[operations.STATE]))
        self.assertNotEqual(entry['replacement_sha256'], pub.sha(expected[operations.STATE]))
        self.assertEqual(entry['ids'], ['old'])

    def test_collector_watch_manifest_binds_raw_base_and_replacement(self):
        state = storage.operations_state_from_files(self.base)
        state['watch'] = watch._cursor(None)
        records = {key: {'value': {'canonical_product_id': key, 'amount': 1, 'currency': 'KRW', 'unit': 'one'},
                         'captured_at': '2026-10-21T00:00:00Z'} for key in ('old', 'keep')}
        source = {'source': watch.SOURCE_MAPPINGS['pricing'][0], 'status': 'VALID', 'records': records,
                  'semantic_hash': watch.digest({key: row['value'] for key, row in records.items()})}
        state['watch']['sources']['pricing'] = source
        self.base[operations.STATE] = body(state)
        write(self.root, self.base)
        self.commit(self.root)
        current = deepcopy(state)
        del current['watch']['sources']['pricing']['records']['old']
        current['watch']['sources']['pricing']['semantic_hash'] = watch.digest({'keep': records['keep']['value']})
        expected = self.migrate(state=current)
        report = collector.update(self.root, [operations.STATE])
        self.assertIn('authorized', report[operations.STATE])
        manifest = json.loads((self.root / operations.MANIFEST).read_bytes())
        entry = manifest['deletions'][0]
        self.assertEqual(entry['ids'], ['old'])
        self.assertEqual(entry['base_sha256'], pub.sha(self.base[operations.STATE]))
        self.assertEqual(entry['replacement_sha256'], pub.sha(expected[operations.STATE]))
        self.assertIsNotNone(self.transaction().operations_guard)
        with self.assertRaisesRegex(pub.PublishError, 'manifest omitted'):
            self.transaction(paths='data/operations/')
        entry['replacement_sha256'] = '0' * 64
        write(self.root, {operations.MANIFEST: body(manifest)})
        with self.assertRaises(pub.PublishError):
            self.transaction()


if __name__ == '__main__':
    unittest.main()
