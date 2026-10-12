"""Offline capacity fixtures only; no production history, provider or API calls."""
import io
import json
import unittest
from unittest.mock import patch
import zipfile

import operations_storage as storage
import restore_operations_safety as restore
import test_restore_operations_safety as fixtures


def stored_bundle(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, raw in files.items():
            archive.writestr(name.removeprefix('data/operations/'), raw)
    return output.getvalue()


class StorageTests(unittest.TestCase):
    def test_only_exact_state_path_has_32mb_allowance(self):
        self.assertEqual(storage.OPS_STATE_MAX_BYTES, 32 * 1024 * 1024)
        self.assertEqual(storage.operations_file_max_bytes(restore.STATE), storage.OPS_STATE_MAX_BYTES)
        for name in (restore.LEDGER, 'state.json', 'data/operations/reports/state.json',
                     '../data/operations/state.json', 'data/operations/./state.json',
                     'data/operations/state.json/', 'data/operations/STATE.json'):
            with self.subTest(name=name):
                self.assertEqual(storage.operations_file_max_bytes(name), restore.MAX_FILE_BYTES)

    def test_serialized_state_boundary_and_no_mutation(self):
        body = b' ' * storage.OPS_STATE_MAX_BYTES
        storage.require_operations_state_size(body)
        with self.assertRaisesRegex(ValueError, 'pruning/reset forbidden'):
            storage.require_operations_state_size(body + b' ')
        with self.assertRaises(TypeError):
            storage.require_operations_state_size('unserialized')

    def test_total_exception_cannot_enlarge_ordinary_budget(self):
        self.assertEqual(restore.MAX_TOTAL_BYTES, 40 * 1024 * 1024)
        self.assertEqual(restore.MAX_ARCHIVE_BYTES, 16 * 1024 * 1024)
        ordinary = b' ' * restore.MAX_FILE_BYTES
        with self.assertRaises(restore.Blocked):
            restore._validate_sizes({restore.STATE:b'{}', restore.LEDGER:ordinary,
                                    'data/operations/reports/one.json':ordinary})
        restore._validate_sizes({restore.STATE:b' ' * storage.OPS_STATE_MAX_BYTES,
                                 restore.LEDGER:ordinary})
        with self.assertRaises(restore.Blocked):
            restore._validate_sizes({restore.STATE:b' ' * storage.OPS_STATE_MAX_BYTES,
                                     restore.LEDGER:ordinary,
                                     'data/operations/reports/one.json':b' '})


class CapacityRestoreTests(fixtures.RestoreTests):
    # Inherit original authentication, claims/receipts, audit, interruption and
    # path-safety regressions; do not substitute validators.
    def large_state_files(self, files, size=9 * 1024 * 1024):
        raw = files[restore.STATE]
        return {**files, restore.STATE:raw + b' ' * (size - len(raw))}

    def test_authenticated_9mb_state_restores_exact_bytes(self):
        self.incoming = self.large_state_files(self.incoming)
        self.raw = stored_bundle(self.incoming)
        self.artifact['digest'] = 'sha256:' + restore._sha(self.raw)
        self.assertEqual(self.perform()['status'], 'authenticated_operations_safety_restored')
        self.assertEqual(restore.verify_current(self.root), self.incoming)
        self.assertEqual(json.loads(self.incoming[restore.STATE]), self.new)
        self.assertFalse((self.root / restore.PENDING).exists())

    def test_9mb_state_without_authentication_cannot_restore(self):
        incoming = self.large_state_files(self.incoming)
        self.raw = stored_bundle(incoming)
        with self.assertRaisesRegex(restore.Blocked, 'artifact_digest_mismatch'):
            self.perform()
        self.assertEqual(restore.verify_current(self.root), self.current)

    def test_9mb_ordinary_file_rejected_without_mutation(self):
        report = 'data/operations/reports/oversize.json'
        raw = b'{}' + b' ' * (9 * 1024 * 1024 - 2)
        self.raw = stored_bundle({**self.incoming, report:raw})
        self.artifact['digest'] = 'sha256:' + restore._sha(self.raw)
        with self.assertRaisesRegex(restore.Blocked, 'archive_entry_unsafe'):
            self.perform()
        self.assertEqual(restore.verify_current(self.root), self.current)
        self.write({report:raw})
        with self.assertRaises(restore.Blocked):
            restore._read(self.root, report)
        (self.root / report).unlink()
        self.assertEqual(restore.verify_current(self.root), self.current)

    def test_state_32mb_boundary_and_oversize_local_read(self):
        path = self.root / restore.STATE
        original = path.read_bytes()
        with path.open('r+b') as handle:
            handle.truncate(storage.OPS_STATE_MAX_BYTES)
        self.assertEqual(len(restore._read(self.root, restore.STATE)), storage.OPS_STATE_MAX_BYTES)
        with path.open('r+b') as handle:
            handle.truncate(storage.OPS_STATE_MAX_BYTES + 1)
        with self.assertRaises(restore.Blocked):
            restore._read(self.root, restore.STATE)
        self.assertEqual(path.stat().st_size, storage.OPS_STATE_MAX_BYTES + 1)
        path.write_bytes(original)
        self.assertEqual(restore.verify_current(self.root), self.current)

    def test_oversize_candidate_rejected_before_staging(self):
        candidate = self.large_state_files(self.incoming, storage.OPS_STATE_MAX_BYTES + 1)
        with patch.object(restore, '_stage') as stage:
            with self.assertRaises(restore.Blocked):
                restore._nonregression(self.current, candidate)
            stage.assert_not_called()
        self.assertEqual(restore.verify_current(self.root), self.current)
        self.assertFalse((self.root / restore.PENDING).exists())

    def test_state_allowance_does_not_bypass_path_safety(self):
        for relative in ('../data/operations/state.json', '/data/operations/state.json',
                         'data/operations/../operations/state.json',
                         'data\\operations\\state.json', 'C:/data/operations/state.json'):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                restore._read(self.root, relative)
        self.assertEqual(restore.verify_current(self.root), self.current)


if __name__ == '__main__':
    unittest.main()
