"""Offline complete graph snapshot publication and deletion guard adversaries."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import collector_snapshot_history as collector
from scripts import operations_graph_publication as graph
from scripts import operations_graph_storage as storage
from scripts import publish_transaction as pub

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / 'config/publish_policy.json').read_bytes())


def body(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def logical():
    return {'nodes': [{'id': 'task:a', 'data': {'literal': '한글  \t\n'}},
                      {'id': 'receipt:r', 'receipt_status': 'VERIFIED',
                       'data': {'receipt_hash': 'a' * 64}}],
            'edges': [{'id': 'relation:a', 'source': 'receipt:r', 'target': 'task:a',
                       'relation': 'verifies'}], 'metadata': {'retained': True}}


def write(root, files):
    for name, raw in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


class GraphPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='graph-publication-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.root = self.folder / 'repo'
        pub.git(self.folder, 'init', '-b', 'main', str(self.root))
        pub.git(self.root, 'config', 'user.name', 'Offline fixture')
        pub.git(self.root, 'config', 'user.email', 'fixture@example.invalid')
        self.base = {graph.GRAPH: body(logical())}
        write(self.root, {**self.base, 'config/publish_policy.json': body(POLICY),
            graph.MANIFEST: body({'schema_version': 1, 'deletions': []})})
        self.commit()

    def commit(self):
        pub.git(self.root, 'add', '-A')
        pub.git(self.root, 'commit', '-m', 'offline fixture')

    def migrate(self, value=None):
        files = {**self.base, **storage.prepare_operations_graph(value or logical(), force=True)}
        write(self.root, files)
        return files

    def guard(self, candidate, manifest=None):
        return graph.SnapshotGuard(self.base, candidate, POLICY, manifest or {})

    def capture(self, candidate, manifest=None, paths=None):
        delta = {name: (self.base.get(name), raw) for name, raw in candidate.items()
                 if raw != self.base.get(name) and (paths is None or name in paths)}
        if manifest is not None:
            raw = body(manifest)
            previous = pub.at_ref(self.root, 'HEAD', graph.MANIFEST)
            write(self.root, {graph.MANIFEST: raw})
            delta[graph.MANIFEST] = (previous, raw)
        return graph.SnapshotGuard.capture(self.root, 'HEAD', delta, POLICY, manifest or {})

    def test_lossless_migration_has_no_logical_removal(self):
        files = self.migrate()
        self.assertEqual(graph.validate_snapshot(files), logical())
        self.assertEqual(graph.removal_ids(self.base, files, POLICY), [])
        guard = self.capture(files)
        self.assertTrue(guard.active)
        self.assertEqual(graph.snapshot(self.root), files)
        self.assertEqual(collector.update(self.root, [graph.GRAPH])[graph.GRAPH], 'no_removals')

    def test_storage_manifest_and_member_cannot_use_individual_overlay(self):
        files = self.migrate()
        for name, raw in files.items():
            with self.subTest(name=name), self.assertRaises(pub.PublishError):
                pub.overlay(name, self.base.get(name), raw, self.base.get(name), POLICY, {})

    def test_missing_omitted_and_tampered_members_fail_closed(self):
        files = self.migrate()
        member = next(name for name in files if name != graph.GRAPH)
        with self.assertRaisesRegex(ValueError, 'omitted'):
            self.capture(files, paths={graph.GRAPH})
        missing = dict(files); del missing[member]
        with self.assertRaises((ValueError, KeyError)):
            graph.validate_snapshot(missing)
        changed = dict(files); changed[member] += b' '
        with self.assertRaises(ValueError):
            graph.validate_snapshot(changed)
        (self.root / member).write_bytes(changed[member])
        with self.assertRaises(ValueError):
            graph.snapshot(self.root)

    def test_all_old_members_and_orphans_are_retained(self):
        files = self.migrate()
        new_value = logical(); new_value['nodes'].append({'id': 'task:b'})
        next_files = {**files, **storage.prepare_operations_graph(new_value, force=True)}
        graph.continuation(files, next_files)
        old_member = next(name for name in files if name != graph.GRAPH and name not in storage.graph_members(next_files[graph.GRAPH]))
        removed = dict(next_files); del removed[old_member]
        with self.assertRaisesRegex(ValueError, 'removed or changed'):
            graph.continuation(files, removed)
        write(self.root, next_files)
        self.assertEqual(graph.snapshot(self.root), next_files)

    def test_manifest_downgrade_rejected_even_with_all_members_retained(self):
        files = self.migrate()
        downgraded = dict(files); downgraded[graph.GRAPH] = self.base[graph.GRAPH]
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            graph.continuation(files, downgraded)

    def test_logical_node_removal_needs_existing_exact_reason_contract(self):
        changed = logical(); changed['nodes'].pop(); changed['edges'] = []
        files = self.migrate(changed)
        with self.assertRaisesRegex(ValueError, 'reason manifest'):
            self.capture(files)
        report = collector.update(self.root, [graph.GRAPH])
        self.assertIn('authorized', report[graph.GRAPH])
        manifest = json.loads((self.root / graph.MANIFEST).read_bytes())
        entry = next(r for r in manifest['deletions'] if r['path'] == graph.GRAPH)
        self.assertEqual(entry['ids'], ['receipt:r', 'relation:a'])
        self.assertEqual(entry['replacement_sha256'], hashlib.sha256(files[graph.GRAPH]).hexdigest())
        guard = self.capture(files, manifest)
        self.assertTrue(guard.active)
        stale = deepcopy(manifest); del stale['deletions'][0]['replacement_sha256']
        with self.assertRaisesRegex(ValueError, 'reason manifest'):
            graph.verify_removals(self.base, files, POLICY, stale)

    def test_root_field_removal_is_not_a_storage_rotation(self):
        changed = logical(); del changed['metadata']['retained']
        files = self.migrate(changed)
        with self.assertRaisesRegex(ValueError, 'outside rotating'):
            self.capture(files)
        with self.assertRaisesRegex(ValueError, 'outside rotating'):
            collector.update(self.root, [graph.GRAPH])

    def test_exact_binding_and_reason_must_belong_to_same_record(self):
        changed = logical(); changed['nodes'].pop(); changed['edges'] = []
        files = self.migrate(changed)
        collector.update(self.root, [graph.GRAPH])
        manifest = json.loads((self.root / graph.MANIFEST).read_bytes())
        exact = deepcopy(next(r for r in manifest['deletions'] if r['path'] == graph.GRAPH))
        legacy = deepcopy(exact)
        del legacy['replacement_sha256']
        exact['reason'] = ''
        for entries in ([exact, legacy], [legacy, exact]):
            with self.subTest(order=entries[0] is exact), self.assertRaisesRegex(ValueError, 'reason manifest'):
                graph.verify_removals(self.base, files, POLICY, {'deletions': entries})

    def test_concurrent_graph_changes_require_reconciliation(self):
        files = self.migrate()
        guard = self.capture(files)
        remote_value = logical(); remote_value['nodes'].append({'id': 'remote:new'})
        remote = {graph.GRAPH: body(remote_value)}
        other = self.folder / 'other'; write(other, remote)
        with self.assertRaisesRegex(ValueError, 'concurrent'):
            guard.install(other)
        self.assertEqual(graph.snapshot(other), remote)

    def test_unchanged_candidate_follows_complete_remote(self):
        files = self.migrate()
        guard = graph.SnapshotGuard(self.base, self.base, POLICY, {})
        remote, chosen = guard.install(self.root)
        self.assertEqual(remote, files)
        self.assertEqual(chosen, files)

    def test_member_first_overlay_and_final_regeneration_validate(self):
        files = self.migrate()
        guard = self.capture(files)
        other = self.folder / 'other'
        pub.git(self.folder, 'clone', str(self.root), str(other))
        remote, installed = guard.install(other)
        self.assertEqual(remote, self.base)
        self.assertEqual(installed, files)
        self.assertEqual(graph.snapshot(other), files)
        regenerated = logical(); regenerated['nodes'].append({'id': 'final:new'})
        final = {**files, **storage.prepare_operations_graph(regenerated, force=True)}
        write(other, final)
        self.assertEqual(guard.verify_final(other, remote, installed), final)
        self.assertEqual(graph.validate_snapshot(final), regenerated)

    def test_collector_checks_members_even_when_manifest_is_unchanged(self):
        files = self.migrate()
        self.commit()
        member = next(name for name in files if name != graph.GRAPH)
        (self.root / member).write_bytes(files[member] + b' ')
        with self.assertRaises(ValueError):
            collector.update(self.root, [graph.GRAPH])

    def test_missing_manifest_cannot_hide_retained_chunks(self):
        files = self.migrate()
        del files[graph.GRAPH]
        with self.assertRaisesRegex(ValueError, 'manifest missing'):
            graph.validate_snapshot(files)
        (self.root / graph.GRAPH).unlink()
        with self.assertRaisesRegex(ValueError, 'manifest missing'):
            collector.update(self.root, [graph.GRAPH])

    def test_failed_overlay_keeps_previous_manifest_readable(self):
        files = self.migrate()
        other = self.folder / 'other'; write(other, self.base)
        with patch.object(graph.os, 'replace', side_effect=OSError('interrupted before pointer swap')):
            with self.assertRaises(OSError):
                graph._install(other, files)
        retained = graph.snapshot(other)
        self.assertEqual(retained[graph.GRAPH], self.base[graph.GRAPH])
        self.assertEqual(graph.validate_snapshot(retained), logical())
        self.assertGreater(len(retained), 1)  # Valid staged orphans survive.
        graph._install(other, files)
        self.assertEqual(graph.snapshot(other), files)
        self.assertFalse(list((other / 'data/operations').glob('.graph-publication-*')))

    def test_regeneration_cannot_remove_retained_chunks(self):
        files = self.migrate()
        guard = self.capture(files)
        new_value = logical(); new_value['nodes'].append({'id': 'next:new'})
        new_files = storage.prepare_operations_graph(new_value, force=True)
        for name in files:
            if name not in new_files and name != graph.GRAPH:
                (self.root / name).unlink()
        write(self.root, new_files)
        with self.assertRaisesRegex(ValueError, 'removed or changed'):
            guard.verify_final(self.root, self.base, files)

    def test_member_symlink_and_retained_capacity_rejected(self):
        files = self.migrate()
        with patch.object(storage, 'GRAPH_AGGREGATE_MAX_BYTES', sum(map(len, files.values())) - 1):
            with self.assertRaisesRegex(ValueError, 'capacity'):
                graph.snapshot(self.root)
        member = next(name for name in files if name != graph.GRAPH)
        path = self.root / member
        target = self.folder / 'target'; target.write_bytes(path.read_bytes())
        path.unlink(); path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'link'):
            graph.snapshot(self.root)

    def transaction(self, cls=None):
        class OfflineTransaction(pub.Transaction):
            def regenerate_and_validate(self, work, *args):
                pass
            def stage(self, work):
                self.final_graph = graph.snapshot(work)
                return super().stage(work)
        pub.git(self.root, 'remote', 'add', 'origin', str(self.root))
        return (cls or OfflineTransaction)(self.root, 'data/operations/ data/publish_deletions.json',
                                          'offline graph fixture', dry_run=True, audit=False)

    def test_transaction_migrates_as_complete_snapshot_without_generic_overlay(self):
        files = self.migrate()
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false', 'RUNNER_TEMP': str(self.folder)}):
            transaction = self.transaction()
            with patch.object(pub, 'overlay', wraps=pub.overlay) as overlay:
                result = transaction.run()
        self.assertEqual(result['status'], 'dry_run_validated')
        self.assertEqual(transaction.final_graph, files)
        self.assertFalse(any(graph.owns(call.args[0]) for call in overlay.call_args_list))

    def test_transaction_first_final_migration_activates_guard(self):
        class MigrateAtFinal(pub.Transaction):
            def regenerate_and_validate(self, work, *args):
                write(work, storage.prepare_operations_graph(logical(), force=True))
            def stage(self, work):
                self.final_graph = graph.snapshot(work)
                return super().stage(work)
        write(self.root, {'data/operations/board.json': b'{"run":1}\n'})
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false', 'RUNNER_TEMP': str(self.folder)}):
            transaction = self.transaction(MigrateAtFinal)
            result = transaction.run()
        self.assertEqual(result['status'], 'dry_run_validated')
        self.assertTrue(transaction.graph_guard.active)
        self.assertEqual(graph.validate_snapshot(transaction.final_graph), logical())

    def test_transaction_final_member_tamper_blocks(self):
        self.migrate()
        class TamperAtFinal(pub.Transaction):
            def regenerate_and_validate(self, work, *args):
                files = graph.snapshot(work)
                name = next(name for name in files if name != graph.GRAPH)
                (work / name).write_bytes(files[name] + b' ')
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false', 'RUNNER_TEMP': str(self.folder)}):
            transaction = self.transaction(TamperAtFinal)
            with self.assertRaisesRegex(pub.PublishError, 'graph snapshot invalid'):
                transaction.run()

    def test_git_snapshot_rejects_tampering_before_logical_use(self):
        files = self.migrate()
        self.commit()
        self.assertEqual(graph.git_snapshot(self.root, 'HEAD'), files)
        member = next(name for name in files if name != graph.GRAPH)
        (self.root / member).write_bytes(files[member] + b' ')
        self.commit()
        with self.assertRaises(ValueError):
            graph.git_snapshot(self.root, 'HEAD')

    def capture_transaction(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}):
            return pub.Transaction(self.root, 'data/operations/ data/publish_deletions.json',
                                   'offline bounded capture', dry_run=True, audit=False)

    def test_capture_checks_local_root_and_member_sizes_before_payload_io(self):
        files = self.migrate()
        member = next(name for name in files if name != graph.GRAPH)
        for name in (graph.GRAPH, member):
            with self.subTest(name=name):
                with (self.root / name).open('wb') as stream:
                    stream.truncate(graph.file_limit(name) + 1)
                with patch.object(graph, 'read_file') as disk_read, \
                        patch.object(graph, 'read_git_blob') as git_read:
                    with self.assertRaisesRegex(pub.PublishError, 'oversized'):
                        self.capture_transaction()
                    disk_read.assert_not_called()
                    git_read.assert_not_called()
                (self.root / name).write_bytes(files[name])

    def test_capture_checks_local_namespace_count_and_aggregate_before_io(self):
        files = self.migrate()
        for constant, limit in (('GRAPH_MAX_MEMBERS', 1),
                                ('GRAPH_AGGREGATE_MAX_BYTES', sum(map(len, files.values())) - 1)):
            with self.subTest(constant=constant), patch.object(storage, constant, limit), \
                    patch.object(graph, 'read_file') as disk_read, \
                    patch.object(graph, 'read_git_blob') as git_read:
                with self.assertRaisesRegex(pub.PublishError, 'capacity'):
                    self.capture_transaction()
                disk_read.assert_not_called()
                git_read.assert_not_called()

    def test_capture_checks_old_git_root_and_member_sizes_before_blob_io(self):
        files = self.migrate()
        member = next(name for name in files if name != graph.GRAPH)
        for name in (graph.GRAPH, member):
            with self.subTest(name=name):
                with (self.root / name).open('wb') as stream:
                    stream.truncate(graph.file_limit(name) + 1)
                self.commit()
                (self.root / name).write_bytes(files[name])
                with patch.object(graph, 'read_file') as disk_read, \
                        patch.object(graph, 'read_git_blob') as git_read:
                    with self.assertRaisesRegex(pub.PublishError, 'capacity'):
                        self.capture_transaction()
                    with self.assertRaisesRegex(pub.PublishError, 'capacity'):
                        pub.at_ref(self.root, 'HEAD', name)
                    disk_read.assert_not_called()
                    git_read.assert_not_called()
                self.commit()

    def test_at_ref_checks_entire_git_count_and_aggregate_before_blob_io(self):
        files = self.migrate()
        self.commit()
        for constant, limit in (('GRAPH_MAX_MEMBERS', 1),
                                ('GRAPH_AGGREGATE_MAX_BYTES', sum(map(len, files.values())) - 1)):
            with self.subTest(constant=constant), patch.object(storage, constant, limit), \
                    patch.object(graph, 'read_git_blob') as git_read:
                with self.assertRaisesRegex(pub.PublishError, 'capacity'):
                    pub.at_ref(self.root, 'HEAD', graph.GRAPH)
                git_read.assert_not_called()

    def test_capture_never_uses_unbounded_graph_path_read_bytes(self):
        files = self.migrate()
        original = Path.read_bytes
        def read(path):
            relative = path.relative_to(self.root).as_posix()
            if graph.owns(relative):
                raise AssertionError('unbounded graph Path.read_bytes')
            return original(path)
        with patch.object(Path, 'read_bytes', read):
            transaction = self.capture_transaction()
            self.assertEqual(transaction.operations_snapshot(self.root), files)
        for name, raw in files.items():
            self.assertEqual(transaction.delta[name], (self.base.get(name), raw))

    def test_non_operations_snapshot_checks_graph_bounds_before_payload_io(self):
        files = self.migrate()
        member = next(name for name in files if name != graph.GRAPH)
        with (self.root / member).open('wb') as stream:
            stream.truncate(graph.file_limit(member) + 1)
        transaction = pub.Transaction.__new__(pub.Transaction)
        with patch.object(graph, 'read_file') as disk_read, patch.object(Path, 'read_bytes') as unbounded:
            with self.assertRaisesRegex(pub.PublishError, 'oversized'):
                transaction.operations_snapshot(self.root)
            disk_read.assert_not_called()
            unbounded.assert_not_called()

    def test_capture_rejects_member_changed_after_inventory_before_open(self):
        files = self.migrate()
        member = next(name for name in files if name != graph.GRAPH)
        original_inventory, original_open = graph.disk_inventory, graph.os.open
        def inventory(root):
            result = original_inventory(root)
            (self.root / member).write_bytes(files[member] + b' ')
            return result
        def guarded_open(path, *args, **kwargs):
            if Path(path) == self.root / member:
                raise AssertionError('changed graph member opened')
            return original_open(path, *args, **kwargs)
        with patch.object(graph, 'disk_inventory', inventory), patch.object(graph.os, 'open', guarded_open):
            with self.assertRaisesRegex(pub.PublishError, 'changed during read'):
                self.capture_transaction()


if __name__ == '__main__':
    unittest.main()
