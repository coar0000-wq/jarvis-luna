"""Offline lossless storage and receipt-backed restart regressions."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import jarvis_execution as execution
import jarvis_operations as core
import operations_storage as storage
import run_jarvis_operations as runner


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()


def sample_state():
    state = core.empty_state()
    state['watch'] = {'evidence': 'unchanged cursor'}
    state['events'] = {f'watch_{i:04}': {'event_id': f'watch_{i:04}', 'kind': 'FIXTURE', 'evidence': 'x' * 700}
                       for i in range(24)}
    state['audit'] = {'schema_version': 1, 'mode': 'future_only', 'start_sequence': 1, 'head': None,
                      **{scope: {f'{scope}_{i}': {'fixture': '한글' * 160, 'number': i} for i in range(8)}
                         for scope in ('payloads', 'preparations', 'outcomes')}}
    return state


class Segments(unittest.TestCase):
    def setUp(self):
        self.limit = patch.object(storage, 'OPS_SEGMENT_TARGET_BYTES', 4096)
        self.limit.start()
        self.addCleanup(self.limit.stop)
        self.state = sample_state()
        # Preserve whitespace/encoding bytes exactly, not just equivalent JSON.
        self.raw = json.dumps(self.state, ensure_ascii=True, indent=3).encode() + b' \n\t'
        self.files = storage.prepare_operations_state(self.state, self.raw, {}.__getitem__, force=True)

    def test_full_roundtrip_original_bytes_and_all_scopes(self):
        self.assertEqual(storage.operations_state_from_files(self.files), self.state)
        self.assertEqual(storage.operations_migration_bytes(self.files[storage.OPS_STATE_PATH], self.files.__getitem__), self.raw)
        physical = json.loads(self.files[storage.OPS_STATE_PATH])
        self.assertEqual(physical['watch'], self.state['watch'])
        self.assertEqual({item['scope'] for item in physical[storage.STORAGE_KEY]['segments']}, set(storage.SCOPES))
        for path, raw in self.files.items():
            self.assertLessEqual(len(raw), storage.operations_file_max_bytes(path))
        self.assertEqual(storage.load_operations_state(self.raw), self.state)

    def test_identical_checkpoint_reuses_all_history_and_snapshot(self):
        delta = storage.prepare_operations_state(self.state, self.files[storage.OPS_STATE_PATH], self.files.__getitem__)
        self.assertEqual(delta, {storage.OPS_STATE_PATH: self.files[storage.OPS_STATE_PATH]})

    def test_small_tail_appends_do_not_create_checkpoint_files(self):
        files = dict(self.files)
        state = copy.deepcopy(self.state)
        old_paths = set(files) - {storage.OPS_STATE_PATH}
        for i in range(7):
            state['events'][f'new_{i}'] = {'small': i}
            delta = storage.prepare_operations_state(state, files[storage.OPS_STATE_PATH], files.__getitem__)
            self.assertEqual(set(delta), {storage.OPS_STATE_PATH})
            files.update(delta)
        self.assertEqual(set(files) - {storage.OPS_STATE_PATH}, old_paths)
        self.assertEqual(storage.operations_state_from_files(files), state)

    def test_tail_flush_preserves_descriptor_prefix_and_every_old_file(self):
        files = dict(self.files)
        state = copy.deepcopy(self.state)
        state['events']['000_new_before_all_old_hashes'] = {'payload': 'y' * 8000}
        delta = storage.prepare_operations_state(state, files[storage.OPS_STATE_PATH], files.__getitem__)
        self.assertLess(len(delta), 5)
        for name in delta:
            if name != storage.OPS_STATE_PATH:
                self.assertNotIn(name, files)
        merged = {**files, **delta}
        storage.validate_operations_storage_continuation(files[storage.OPS_STATE_PATH], merged[storage.OPS_STATE_PATH],
                                                         files.__getitem__, merged.__getitem__)
        self.assertEqual(storage.operations_state_from_files(merged), state)
        for name in files:
            if name != storage.OPS_STATE_PATH:
                self.assertEqual(merged[name], files[name])

    def test_missing_corrupt_unknown_scope_reordered_duplicate_and_bad_chunk_fail(self):
        body = self.files[storage.OPS_STATE_PATH]
        document = json.loads(body)
        segments = document[storage.STORAGE_KEY]['segments']
        self.assertGreater(len(segments), 2)
        for name in storage.operations_state_members(body):
            missing = dict(self.files)
            del missing[name]
            with self.subTest(missing=name), self.assertRaises(ValueError):
                storage.operations_state_from_files(missing)
            corrupt = {**self.files, name: self.files[name] + b' '}
            with self.subTest(corrupt=name), self.assertRaises(ValueError):
                storage.operations_state_from_files(corrupt)
        variants = []
        changed = copy.deepcopy(document)
        changed[storage.STORAGE_KEY]['segments'][0]['scope'] = 'tasks'
        variants.append(changed)
        changed = copy.deepcopy(document)
        changed[storage.STORAGE_KEY]['segments'][0:2] = changed[storage.STORAGE_KEY]['segments'][1::-1]
        variants.append(changed)
        changed = copy.deepcopy(document)
        first = json.loads(self.files[segments[0]['path']])
        changed['events'].update(first['records'])
        variants.append(changed)
        changed = copy.deepcopy(document)
        changed[storage.STORAGE_KEY]['migration']['sha256'] = '0' * 64
        variants.append(changed)
        for i, changed in enumerate(variants):
            with self.subTest(variant=i), self.assertRaises(ValueError):
                storage.operations_state_from_files({**self.files, storage.OPS_STATE_PATH: encoded(changed)})

    def test_immutable_tail_and_segment_edits_removals_and_type_changes_fail(self):
        for scope in storage.SCOPES:
            for mode in ('delete', 'edit'):
                state = copy.deepcopy(self.state)
                table = storage._table(state, scope)
                key = next(iter(table))
                if mode == 'delete':
                    del table[key]
                else:
                    table[key] = {'changed': True}
                with self.subTest(scope=scope, mode=mode), self.assertRaisesRegex(ValueError, 'immutable history'):
                    storage.prepare_operations_state(state, self.files[storage.OPS_STATE_PATH], self.files.__getitem__)
        state = copy.deepcopy(self.state)
        state['events']['typed'] = {'evidence': 1}
        files = {**self.files, **storage.prepare_operations_state(state, self.files[storage.OPS_STATE_PATH], self.files.__getitem__)}
        state['events']['typed']['evidence'] = True
        with self.assertRaisesRegex(ValueError, 'immutable history'):
            storage.prepare_operations_state(state, files[storage.OPS_STATE_PATH], files.__getitem__)

    def test_no_downgrade_or_resegmentation(self):
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            storage.validate_operations_storage_continuation(self.files[storage.OPS_STATE_PATH], encoded(self.state), self.files.__getitem__)
        different = storage.prepare_operations_state(self.state, None, force=True)
        with self.assertRaisesRegex(ValueError, 'reference prefix'):
            storage.validate_operations_storage_continuation(self.files[storage.OPS_STATE_PATH], different[storage.OPS_STATE_PATH],
                                                             self.files.__getitem__, different.__getitem__)

    def test_finite_member_logical_and_total_bounds(self):
        with patch.object(storage, 'OPS_LOGICAL_MAX_BYTES', 100):
            with self.assertRaisesRegex(ValueError, 'capacity'):
                storage.prepare_operations_state(self.state, self.raw, force=True)
        with patch.object(storage, 'OPS_STORAGE_MAX_MEMBERS', 1):
            with self.assertRaises(ValueError):
                storage.operations_state_from_files(self.files)
        with patch.object(storage, 'OPS_BASE_TOTAL_BYTES', 100):
            with self.assertRaisesRegex(ValueError, 'capacity'):
                storage.operations_state_from_files(self.files)
        for name in ('data/operations/state/../state.json', 'data/operations/state/arbitrary.json',
                     'data/operations/reports/segment-' + '0' * 64 + '.json'):
            self.assertFalse(storage.is_operations_state_member(name))

    def test_multichunk_legacy_raw_snapshot_exactness_and_order(self):
        raw = self.raw + b' ' * storage.OPS_MEMBER_MAX_BYTES
        files = storage.prepare_operations_state(self.state, raw, force=True)
        body = files[storage.OPS_STATE_PATH]
        self.assertEqual(storage.operations_migration_bytes(body, files.__getitem__), raw)
        doc = json.loads(body)
        chunks = doc[storage.STORAGE_KEY]['migration']['chunks']
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]['bytes'], storage.OPS_MEMBER_MAX_BYTES)
        chunks.reverse()
        with self.assertRaisesRegex(ValueError, 'order'):
            storage.operations_state_from_files({**files, storage.OPS_STATE_PATH: encoded(doc)})

    def test_strict_duplicate_json_and_nonfinite_legacy_input(self):
        for raw in (b'{"schema_version":1,"events":{},"events":{}}', b'{"bad":NaN}'):
            with self.assertRaises(ValueError):
                storage.load_operations_state(raw)


class RunnerStorage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / runner.STATE
        self.target.parent.mkdir(parents=True)
        self.state = sample_state()
        self.raw = json.dumps(self.state, indent=2).encode() + b' \n'
        self.target.write_bytes(self.raw)

    def test_interruption_before_manifest_swap_preserves_old_bytes_and_resumes(self):
        original = runner._atomic_bytes
        written = []
        def interrupted(root, relative, body, *, immutable=False):
            if relative == runner.STATE:
                raise OSError('injected before manifest replacement')
            original(root, relative, body, immutable=immutable)
            written.append(relative)
        with patch.object(storage, 'OPS_MIGRATION_THRESHOLD', 1), \
                patch.object(storage, 'OPS_SEGMENT_TARGET_BYTES', 4096), \
                patch.object(runner, '_atomic_bytes', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'injected'):
                runner.atomic(self.root, runner.STATE, self.state)
        self.assertTrue(written)
        self.assertEqual(self.target.read_bytes(), self.raw)
        self.assertEqual(runner.read(self.root, runner.STATE), self.state)
        old = {name: (self.root / name).read_bytes() for name in written}
        with patch.object(storage, 'OPS_MIGRATION_THRESHOLD', 1), patch.object(storage, 'OPS_SEGMENT_TARGET_BYTES', 4096):
            runner.atomic(self.root, runner.STATE, self.state)
            self.assertEqual(runner.read(self.root, runner.STATE), self.state)
        for name, raw in old.items():
            self.assertEqual((self.root / name).read_bytes(), raw)
        self.assertFalse(list((self.root / storage.OPS_STATE_DIRECTORY).glob('.operations-*')))

    def test_missing_state_with_retained_members_never_bootstraps(self):
        files = storage.prepare_operations_state(self.state, self.raw, force=True)
        for name, raw in files.items():
            if name != storage.OPS_STATE_PATH:
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
        self.target.unlink()
        for action in (lambda: runner.run(self.root, execute_local=False),
                       lambda: runner.atomic(self.root, runner.STATE, core.empty_state())):
            with self.assertRaisesRegex(ValueError, 'do not reset'):
                action()
        self.assertFalse(self.target.exists())
        self.assertFalse((self.root / execution.ExecutionStore.filename).exists())

    def test_total_preflight_failure_leaves_all_existing_files_unchanged(self):
        with patch.object(storage, 'OPS_MIGRATION_THRESHOLD', 1), patch.object(storage, 'OPS_BASE_TOTAL_BYTES', 100):
            with self.assertRaisesRegex(ValueError, 'capacity'):
                runner.atomic(self.root, runner.STATE, self.state)
        self.assertEqual(self.target.read_bytes(), self.raw)
        self.assertFalse((self.root / storage.OPS_STATE_DIRECTORY).exists())

    def test_unknown_or_tampered_orphan_rejected_without_manifest_change(self):
        directory = self.root / storage.OPS_STATE_DIRECTORY
        directory.mkdir()
        for path in (directory / 'unknown.json', directory / ('segment-' + '0' * 64 + '.json')):
            path.write_bytes(b'{}')
            with self.assertRaises(ValueError):
                runner.atomic(self.root, runner.STATE, self.state)
            self.assertEqual(self.target.read_bytes(), self.raw)
            path.unlink()

    def test_fsynced_member_temp_is_staged_outside_immutable_namespace(self):
        original = runner.tempfile.mkstemp
        staging = []
        def record(*args, **kwargs):
            staging.append(Path(kwargs['dir']))
            return original(*args, **kwargs)
        with patch.object(storage, 'OPS_MIGRATION_THRESHOLD', 1), \
                patch.object(storage, 'OPS_SEGMENT_TARGET_BYTES', 4096), \
                patch.object(runner.tempfile, 'mkstemp', side_effect=record):
            runner.atomic(self.root, runner.STATE, self.state)
        self.assertGreater(len(staging), 1)
        self.assertTrue(all(path == self.target.parent for path in staging))


class ReceiptRestart(unittest.TestCase):
    def test_segmented_executing_outcome_resumes_existing_receipt_without_redispatch(self):
        now = '2026-10-04T02:00:00+00:00'
        class Crash(BaseException):
            pass
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in execution.SOURCES.values():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(encoded({'captured_at': now, 'items': []}))
            path = root / runner.STATE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(encoded(core.empty_state()))
            original_atomic = runner.atomic
            stopped = []
            def crash_after_verified_outcome(root, relative, value):
                original_atomic(root, relative, value)
                if relative == runner.STATE:
                    for outcome in value.get('audit', {}).get('outcomes', {}).values():
                        task_id = outcome['task_id']
                        if outcome['result']['output_verified'] and value['tasks'][task_id]['state'] == 'EXECUTING':
                            stopped.append(task_id)
                            raise Crash()
            with patch.object(storage, 'OPS_MIGRATION_THRESHOLD', 1), \
                    patch.object(runner, 'atomic', side_effect=crash_after_verified_outcome):
                with self.assertRaises(Crash):
                    runner.run(root, now=now)
            self.assertEqual(len(stopped), 1)
            task_id = stopped[0]
            state = runner.read(root, runner.STATE)
            self.assertEqual(state['tasks'][task_id]['state'], 'EXECUTING')
            runner.validate_state(root, state)
            outcome = next(iter(state['audit']['outcomes'].values()))
            receipt = copy.deepcopy(outcome['result']['receipt'])
            original_execute = execution.execute
            calls = []
            def checked_execute(root, task, *args, **kwargs):
                calls.append(task['task_id'])
                self.assertNotEqual(task['task_id'], task_id, 'receipt-backed task was redispatched')
                return original_execute(root, task, *args, **kwargs)
            with patch.object(execution, 'execute', side_effect=checked_execute):
                runner.run(root, now=now)
            resumed = runner.read(root, runner.STATE)
            self.assertEqual(resumed['tasks'][task_id]['state'], 'COMPLETED')
            self.assertEqual(resumed['receipts'][receipt['receipt_id']], receipt)
            self.assertNotIn(task_id, calls)
            runner.validate_state(root, resumed)


if __name__ == '__main__':
    unittest.main()
