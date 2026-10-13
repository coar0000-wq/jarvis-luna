"""Operations receipts bind original bytes, not a JSON reserialization."""
import unittest
from publish_transaction import overlay, PublishError


class OperationsBytesTests(unittest.TestCase):
    policy = {'identity_fields': ['id']}
    report = 'data/operations/reports/abc123.json'
    ledger = 'data/operations/reports/.execution-ledger.json'

    def apply(self, name, base, local, remote):
        return overlay(name, base, local, remote, self.policy, {})

    def test_new_restored_report_keeps_exact_bytes(self):
        raw = b'{"task_id":"abc","sources":[]}\n'
        self.assertEqual(self.apply(self.report, None, raw, None), raw)

    def test_ledger_keeps_exact_bytes(self):
        base = b'{"claims":{}}'
        raw = b'{"claims":{"a":{"status":"VERIFIED"}}}\n'
        self.assertEqual(self.apply(self.ledger, base, raw, base), raw)
        self.assertEqual(self.apply(self.ledger, base, raw, raw), raw)

    def test_concurrent_ledger_changes_require_reconciliation(self):
        with self.assertRaises(PublishError):
            self.apply(self.ledger, b'{}', b'{"claims":{"a":1}}', b'{"claims":{"b":2}}')

    def test_unchanged_local_keeps_remote_exact_bytes(self):
        remote = b'{"claims":{"a":1}}\n'
        self.assertEqual(self.apply(self.ledger, b'{}', b'{}', remote), remote)

    def test_remote_deletion_is_not_undone(self):
        with self.assertRaises(PublishError):
            self.apply(self.report, b'{}', b'{"id":"new"}', None)

    def test_ledger_field_removal_still_needs_reason(self):
        with self.assertRaises(PublishError):
            self.apply(self.ledger, b'{"claims":{"a":1}}', b'{"claims":{}}', b'{"claims":{"a":1}}')

    def test_other_json_still_uses_normal_projection(self):
        raw = b'{"value":1}'
        self.assertNotEqual(self.apply('data/example.json', None, raw, None), raw)


if __name__ == '__main__':
    unittest.main()
