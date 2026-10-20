"""Operations receipts bind original bytes, not a JSON reserialization."""
import unittest
import json
from publish_transaction import overlay, PublishError


class OperationsBytesTests(unittest.TestCase):
    policy = {'identity_fields': ['id'], 'metadata_timestamps': []}
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

    def test_compact_graph_keeps_exact_bytes_before_ingest(self):
        name = 'data/operations/knowledge_graph.json'
        base = b'{"nodes":[],"edges":[]}\n'
        raw = '{"edges":[],"nodes":[{"id":"n","literal":"한글  \\t\\n"}]}\n'.encode()
        for prior, remote in ((None, None), (base, base), (base, raw)):
            with self.subTest(prior=prior, remote=remote):
                self.assertEqual(self.apply(name, prior, raw, remote), raw)
        self.assertEqual(json.loads(raw)['nodes'][0]['literal'], '한글  \t\n')
        for other in ('data/other/knowledge_graph.json', 'data/operations/other.json'):
            self.assertNotEqual(self.apply(other, None, raw, None), raw)

    def test_graph_byte_preservation_cannot_bypass_deletions_or_conflicts(self):
        name = 'data/operations/knowledge_graph.json'
        base = b'{"nodes":[{"id":"n","value":0}],"edges":[]}'
        local = b'{"nodes":[{"id":"n","value":1}],"edges":[]}'
        remote = b'{"nodes":[{"id":"n","value":2}],"edges":[]}'
        with self.assertRaises(PublishError):
            self.apply(name, base, b'{"nodes":[],"edges":[]}', base)
        with self.assertRaises(PublishError):
            self.apply(name, base, local, None)
        with self.assertRaises(PublishError):
            self.apply(name, base, local, remote)

    def test_graph_still_requires_valid_json(self):
        with self.assertRaises(PublishError):
            self.apply('data/operations/knowledge_graph.json', None, b'{invalid', None)

    def test_concurrent_graph_additions_stay_compact_without_loss(self):
        name = 'data/operations/knowledge_graph.json'
        nodes = [{'id': str(i), 'data': {'literal': '한글  \t\n'}} for i in range(120)]
        base = {'nodes': nodes, 'edges': []}
        local = {'nodes': nodes + [{'id': 'local', 'value': 1}], 'edges': []}
        remote = {'nodes': nodes + [{'id': 'remote', 'value': 2}], 'edges': []}
        def compact(value):
            return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
        result = self.apply(name, compact(base), compact(local), compact(remote))
        merged = json.loads(result)
        expected = {row['id']: row for row in nodes + local['nodes'][-1:] + remote['nodes'][-1:]}
        self.assertEqual({row['id']: row for row in merged['nodes']}, expected)
        self.assertEqual(len(merged['nodes']), 122)
        self.assertEqual(merged['edges'], [])
        self.assertEqual(result, compact(merged))
        self.assertLess(len(result), 8192)
        self.assertGreater(len(json.dumps(merged, ensure_ascii=False, indent=2).encode()), 8192)


if __name__ == '__main__':
    unittest.main()
