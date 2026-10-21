"""Offline immutable-history restore regressions. No providers or remote writes."""
import copy
import io
from pathlib import Path
from unittest.mock import patch
import unittest
import warnings
import zipfile

import jarvis_operations as core
import operations_storage as storage
import restore_operations_safety as restore
import test_restore_operations_safety as fixtures


def segmented(files, previous=None):
    previous = files if previous is None else previous
    state = storage.load_operations_state(files[restore.STATE], files.__getitem__)
    # Small fixtures must exercise real immutable JSON chunks as well as raw
    # migration chunks, instead of remaining entirely in the bounded hot tail.
    with patch.object(storage, 'OPS_SEGMENT_TARGET_BYTES', 256):
        changes = storage.prepare_operations_state(state, previous_body=previous[restore.STATE],
            read_member=previous.__getitem__, force=True)
    retained = {name: raw for name, raw in previous.items()
                if storage.is_operations_state_member(name)}
    return {**files, **retained, **changes}


class SegmentedRestoreTests(fixtures.RestoreTests):
    def member_names(self, files):
        return sorted(name for name in files if storage.is_operations_state_member(name))

    def test_v1_artifact_migration_preserves_exact_original_bytes(self):
        original = self.incoming[restore.STATE] + b' \n\t'
        incoming = segmented({**self.incoming, restore.STATE: original})
        self.assertEqual(storage.operations_migration_bytes(incoming[restore.STATE], incoming.__getitem__), original)
        self.assertTrue(self.member_names(incoming))
        self.assertTrue(any(name.endswith('.json') for name in self.member_names(incoming)))
        self.replace_archive(incoming)
        self.assertEqual(self.perform()['status'], 'authenticated_operations_safety_restored')
        self.assertEqual(restore.verify_current(self.root), incoming)
        state, _ = restore._validate_files(incoming)
        self.assertEqual(state, self.new)
        self.assertEqual(state['events'], self.new['events'])

    def test_segmented_to_segmented_extension_preserves_all_chunk_bytes(self):
        current = segmented(self.current)
        self.write(current)
        self.head = current
        incoming = segmented(self.incoming, current)
        restore._nonregression(current, incoming)
        self.replace_archive(incoming)
        self.perform()
        self.assertEqual(restore.verify_current(self.root), incoming)
        for name in self.member_names(current):
            self.assertEqual(incoming[name], current[name])
        self.assertEqual(storage.operations_migration_bytes(incoming[restore.STATE], incoming.__getitem__), self.current[restore.STATE])

    def test_migration_raw_chunks_are_bounded_and_reconstruct_large_original(self):
        raw = self.incoming[restore.STATE]
        original = raw + b' ' * (9 * 1024 * 1024 - len(raw))
        incoming = segmented({**self.incoming, restore.STATE: original})
        chunks = [name for name in self.member_names(incoming) if name.endswith('.bin')]
        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(len(incoming[name]) <= restore.MAX_FILE_BYTES for name in chunks))
        self.assertEqual(storage.operations_migration_bytes(incoming[restore.STATE], incoming.__getitem__), original)
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_STORED) as archive:
            for name, body in incoming.items():
                archive.writestr(name.removeprefix('data/operations/'), body)
        self.assertEqual(restore._archive(out.getvalue()), incoming)

    def test_same_logical_migration_cannot_reserialize_original_bytes(self):
        incoming = segmented({**self.current, restore.STATE: self.current[restore.STATE] + b' '})
        with self.assertRaisesRegex(ValueError, 'operations_migration_original_byte_conflict'):
            restore._nonregression(self.current, incoming)

    def test_migration_requires_original_snapshot_and_full_nonregression(self):
        changes = storage.prepare_operations_state(self.new, force=True)
        incoming = {**self.incoming, **changes}
        with self.assertRaisesRegex(ValueError, 'operations_migration_original_missing'):
            restore._nonregression(self.current, incoming)
        original = copy.deepcopy(self.old)
        original['prior_approval_history'] = {'immutable': True}
        source = {**self.current, restore.STATE: fixtures.body(original)}
        incoming = segmented(self.incoming, source)
        # Segment integrity alone cannot detect loss in non-segmented fields of
        # the migration source; unchanged full-history rules must still run.
        with self.assertRaisesRegex(ValueError, 'history_key_lost'):
            restore._nonregression(self.current, incoming)

    def test_migration_original_cannot_predate_legacy_baseline(self):
        later = copy.deepcopy(self.new)
        core.create_task(later, goal='later verified continuation', team='design')
        candidate = {**self.incoming, restore.STATE: fixtures.body(later)}
        incoming = segmented(candidate, self.current)
        # The final state extends this baseline, but its claimed migration
        # source is older than the baseline and cannot prove this migration.
        with self.assertRaises(ValueError):
            restore._nonregression(self.incoming, incoming)

    def test_segmented_downgrade_and_reference_rebinding_denied(self):
        current = segmented(self.current)
        members = {name: current[name] for name in self.member_names(current)}
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            restore._nonregression(current, {**self.incoming, **members})
        rebound = {**segmented(self.incoming), **members}
        with self.assertRaisesRegex(ValueError, 'reference prefix changed'):
            restore._nonregression(current, rebound)

    def test_rehydration_precedes_existing_full_validator(self):
        incoming = segmented(self.incoming)
        observed = []
        original = restore.runner.validate_state
        def validate(root, state):
            observed.append(copy.deepcopy(state))
            return original(root, state)
        with patch.object(restore.runner, 'validate_state', side_effect=validate):
            restore._validate_files(incoming)
        self.assertEqual(observed, [self.new])

    def test_missing_or_tampered_chunk_blocks_before_staging(self):
        incoming = segmented(self.incoming)
        for name in self.member_names(incoming):
            for kind in ('missing', 'tampered'):
                bad = dict(incoming)
                if kind == 'missing':
                    bad.pop(name)
                else:
                    bad[name] += b' '
                self.replace_archive(bad)
                with self.subTest(name=name, kind=kind), patch.object(restore, '_stage') as stage:
                    with self.assertRaises(ValueError):
                        self.perform()
                    stage.assert_not_called()
        self.assertEqual(restore.verify_current(self.root), self.current)

    def test_unknown_member_schema_scope_and_path_rejected(self):
        incoming = segmented(self.incoming)
        body = b'{}'
        for name in ('data/operations/state/arbitrary.json',
                     'data/operations/state/nested/member.json',
                     'data/operations/state/segment-' + restore._sha(body) + '.json',
                     'data/operations/state/segment-' + '0' * 64 + '.json'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                restore._archive(fixtures.bundle({**incoming, name: body}))

    def test_valid_orphans_preserved_but_never_loaded_as_logical_history(self):
        orphan_state = core.empty_state()
        core.create_task(orphan_state, goal='interrupted unrelated write', team='graph')
        orphan_files = segmented({restore.STATE: fixtures.body(orphan_state), restore.LEDGER: b'{}'})
        orphans = {name: orphan_files[name] for name in self.member_names(orphan_files)}
        current = {**segmented(self.current), **orphans}
        incoming = segmented(self.incoming, current)
        self.write(current)
        self.head = current
        self.replace_archive(incoming)
        self.perform()
        restored = restore.verify_current(self.root)
        self.assertEqual(restored, incoming)
        logical, _ = restore._validate_files(restored)
        self.assertEqual(logical, self.new)
        for name, raw in orphans.items():
            self.assertEqual(restored[name], raw)
        name = next(iter(orphans))
        with self.assertRaisesRegex(ValueError, 'state_member_lost_or_byte_conflict'):
            restore._nonregression(current, {k: v for k, v in incoming.items() if k != name})

    def test_filesystem_member_symlink_subdirectory_and_unscoped_file_rejected(self):
        incoming = segmented(self.incoming)
        self.write(incoming)
        history = self.root / storage.OPS_STATE_DIRECTORY
        for name, directory in (('unknown.json', False), ('nested', True)):
            path = history / name
            if directory:
                path.mkdir()
            else:
                path.write_bytes(b'{}')
            with self.subTest(name=name), self.assertRaises(ValueError):
                restore.verify_current(self.root)
            if directory:
                path.rmdir()
            else:
                path.unlink()
        member = self.member_names(incoming)[0]
        path = self.root / member
        path.unlink()
        path.symlink_to(self.root / restore.STATE)
        with self.assertRaises(ValueError):
            restore.verify_current(self.root)

    def test_archive_member_symlink_duplicate_and_oversize_rejected(self):
        incoming = segmented(self.incoming)
        member = self.member_names(incoming)[0]
        for kind in ('symlink', 'duplicate', 'oversize'):
            out = io.BytesIO()
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                with zipfile.ZipFile(out, 'w') as archive:
                    for name, raw in incoming.items():
                        entry = zipfile.ZipInfo(name.removeprefix('data/operations/'))
                        if name == member and kind == 'symlink':
                            entry.external_attr = 0o120777 << 16
                        if name == member and kind == 'oversize':
                            raw = b'x' * (restore.MAX_FILE_BYTES + 1)
                        archive.writestr(entry, raw)
                    if kind == 'duplicate':
                        archive.writestr(member.removeprefix('data/operations/'), incoming[member])
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                restore._archive(out.getvalue())

    def test_segments_and_reports_precede_ledger_then_manifest(self):
        incoming = segmented(self.incoming)
        # Reformat an empty ledger so both ledger and manifest must be written.
        incoming[restore.LEDGER] = b'{ }\n'
        self.replace_archive(incoming)
        order = []
        original = restore.os.replace
        def replace(source, target):
            order.append(Path(target).relative_to(self.root).as_posix())
            return original(source, target)
        with patch.object(restore.os, 'replace', side_effect=replace):
            self.perform()
        self.assertEqual(order[-2:], [restore.LEDGER, restore.STATE])
        self.assertTrue(all(name in order[:-2] for name in self.member_names(incoming)))

    def test_pre_marker_member_staging_keeps_old_manifest_readable(self):
        incoming = segmented(self.incoming)
        name = self.member_names(incoming)[0]
        temporary = restore._stage(self.root, name, incoming[name])
        try:
            self.assertEqual(temporary.parent, self.root / 'data/operations')
            self.assertEqual(restore.verify_current(self.root), self.current)
        finally:
            temporary.unlink(missing_ok=True)

    def test_segment_restore_interruption_preserves_pending_gate_and_original_state(self):
        incoming = segmented(self.incoming)
        self.replace_archive(incoming)
        original = restore.os.replace
        def interrupted(source, target):
            if Path(target) == self.root / restore.STATE:
                raise OSError('interrupted after immutable history installation')
            return original(source, target)
        with patch.object(restore.os, 'replace', side_effect=interrupted), self.assertRaises(OSError):
            self.perform()
        self.assertEqual((self.root / restore.STATE).read_bytes(), self.current[restore.STATE])
        for name in self.member_names(incoming):
            self.assertEqual((self.root / name).read_bytes(), incoming[name])
        self.assertTrue((self.root / restore.PENDING).exists())
        with self.assertRaisesRegex(ValueError, 'operations_restore_interrupted'):
            restore.verify_current(self.root)
        with self.assertRaisesRegex(ValueError, 'operations_restore_interrupted'):
            self.perform()

    def test_segmentation_never_expands_any_capacity_budget(self):
        self.assertEqual(storage.OPS_STATE_MAX_BYTES, 32 * 1024 * 1024)
        self.assertEqual(restore.MAX_FILE_BYTES, 8 * 1024 * 1024)
        self.assertEqual(restore.BASE_TOTAL_BYTES, 96 * 1024 * 1024)
        self.assertEqual(restore.MAX_TOTAL_BYTES, 120 * 1024 * 1024)
        self.assertEqual(restore.MAX_ARCHIVE_BYTES, 64 * 1024 * 1024)
        self.assertEqual(restore.MAX_FILES, 20000)
        member = 'data/operations/state/legacy-' + 'a' * 64 + '.bin'
        self.assertEqual(storage.operations_file_max_bytes(member), restore.MAX_FILE_BYTES)
        with patch.object(storage, 'OPS_STORAGE_MAX_MEMBERS', 2), self.assertRaises(ValueError):
            restore._validate_sizes({restore.STATE: b'{}', restore.LEDGER: b'{}',
                **{'data/operations/state/legacy-' + str(n) * 64 + '.bin': b'x' for n in range(3)}})
        with patch.object(restore, 'BASE_TOTAL_BYTES', 20), patch.object(restore, 'MAX_FILE_BYTES', 8):
            # A physical state manifest grants no logical-state/raw-copy exemption.
            restore._validate_sizes({restore.STATE: b'{}', member: b'x' * 8, restore.LEDGER: b'x' * 8})
            with self.assertRaises(ValueError):
                restore._validate_sizes({restore.STATE: b'{}', member: b'x' * 8,
                    restore.LEDGER: b'x' * 8, 'data/operations/reports/r.json': b'x' * 3})


if __name__ == '__main__':
    unittest.main()
