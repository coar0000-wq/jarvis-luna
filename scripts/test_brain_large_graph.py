"""Bounded derived-graph storage without weakening ordinary source limits."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import obsidian_brain as brain
import run_jarvis_operations as runner


class DerivedGraphLimits(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root / '.gitignore').write_text('/obsidian/JARVIS_LUNA/BrainRuntime/\n', encoding='utf-8')
        (self.root / 'data/operations').mkdir(parents=True)
        self.labels = dict(task='limit-test', team='operations', operation='local-analysis')
        self.raw = json.dumps({'nodes': [{'value': 'x' * 5000}], 'edges': []}).encode()
        self.graph = self.root / 'data/operations/knowledge_graph.json'
        self.graph.write_bytes(self.raw)
        self.small = patch.object(brain, 'MAX_BYTES', 4096)
        self.large = patch.object(brain, 'MAX_DERIVED_GRAPH_BYTES', 8192)
        self.small.start(); self.large.start()
        self.addCleanup(self.small.stop); self.addCleanup(self.large.stop)

    def test_only_exact_derived_graph_path_has_larger_bound(self):
        self.assertEqual(brain.source_byte_limit('data/operations/knowledge_graph.json'), 8192)
        for relative in ('data/operations/other.json', 'data/other/knowledge_graph.json',
                         'data/operations/knowledge_graph.json.backup', 'data/dashboard_runtime.json'):
            self.assertEqual(brain.source_byte_limit(relative), 4096)

    def test_large_graph_readback_and_output_use_exact_bytes(self):
        with brain.execution(self.root, **self.labels):
            loaded = brain.load_artifact(self.graph, self.root)
            self.assertEqual(loaded['source_sha256'], hashlib.sha256(self.raw).hexdigest())
            self.assertEqual(loaded['size_bytes'], len(self.raw))
            self.assertEqual(loaded['value'], json.loads(self.raw))
            proof = brain.record_output(self.graph, self.root, **self.labels)
            self.assertTrue(proof['input_read_from_vault'])
            self.assertTrue(proof['output_stored'])
            self.assertEqual(self.graph.read_bytes(), self.raw)

    def test_ordinary_oversized_source_is_rejected_before_snapshot(self):
        ordinary = self.root / 'data/ordinary.json'
        ordinary.write_bytes(self.raw)
        with brain.execution(self.root, **self.labels):
            with self.assertRaisesRegex(brain.BrainError, 'byte_limit_exceeded'):
                brain.load_artifact(ordinary, self.root)
        self.assertFalse((self.root / brain.BRAIN / 'payloads').exists())

    def test_graph_larger_than_specific_bound_is_rejected(self):
        self.graph.write_bytes(json.dumps({'nodes': ['x' * 9000]}).encode())
        with brain.execution(self.root, **self.labels):
            with self.assertRaisesRegex(brain.BrainError, 'byte_limit_exceeded'):
                brain.load_artifact(self.graph, self.root)
        self.assertFalse((self.root / brain.BRAIN / 'payloads').exists())

    def test_large_payload_tampering_still_fails_closed(self):
        with brain.execution(self.root, **self.labels):
            loaded = brain.load_artifact(self.graph, self.root)
            digest = loaded['payload_id']
            payload = self.root / brain.BRAIN / 'payloads' / digest[:2] / (digest + '.bin')
            payload.write_bytes(payload.read_bytes() + b' ')
            with self.assertRaises(brain.IntegrityError):
                brain.load_artifact(self.graph, self.root)

    def test_compact_graph_crosses_layout_limit_without_losing_any_data(self):
        graph = {'nodes': [{'id': str(i), 'data': {'value': '한글  \t\n'}}
                           for i in range(120)], 'edges': []}
        before = json.loads(json.dumps(graph))
        pretty = (json.dumps(graph, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
        compact = runner.serialized_output(runner.GRAPH, graph)
        self.assertGreater(len(pretty), brain.MAX_DERIVED_GRAPH_BYTES)
        self.assertLessEqual(len(compact), brain.MAX_DERIVED_GRAPH_BYTES)
        source = self.root / 'data/source.json'
        source.write_bytes(b'{"genuine_source":true}\n')
        with brain.execution(self.root, **self.labels) as run:
            brain.load_artifact(source, self.root)
            runner.atomic(self.root, runner.GRAPH, graph)
            loaded = brain.load_artifact(self.graph, self.root)
            self.assertEqual(loaded['value'], before)
            self.assertEqual(loaded['source_sha256'], hashlib.sha256(compact).hexdigest())
            self.assertTrue(run.proof()['output_stored'])
        self.assertEqual(graph, before)
        self.assertEqual(self.graph.read_bytes(), compact)
        self.assertEqual(source.read_bytes(), b'{"genuine_source":true}\n')

    def test_graph_exact_limit_and_multibyte_oversize_leave_old_bytes(self):
        graph = {'nodes': [{'literal': '한글  \t\n'}], 'edges': []}
        compact = runner.serialized_output(runner.GRAPH, graph)
        self.assertGreater(len(compact), len(compact.decode('utf-8')))
        with patch.object(brain, 'MAX_DERIVED_GRAPH_BYTES', len(compact)):
            runner.atomic(self.root, runner.GRAPH, graph)
            self.assertEqual(self.graph.read_bytes(), compact)
        for bound in (len(compact) - 1, len(compact.decode('utf-8'))):
            with self.subTest(bound=bound), patch.object(brain, 'MAX_DERIVED_GRAPH_BYTES', bound):
                with self.assertRaisesRegex(brain.BrainError, '^byte_limit_exceeded$'):
                    runner.atomic(self.root, runner.GRAPH, graph)
            self.assertEqual(self.graph.read_bytes(), compact)
            self.assertFalse(list(self.graph.parent.glob('.operations-*')))

    def test_graph_oversize_rejected_before_directory_or_vault_mutation(self):
        root = self.root / 'new-root'
        with self.assertRaisesRegex(brain.BrainError, '^byte_limit_exceeded$'):
            runner.atomic(root, runner.GRAPH, {'nodes': ['x' * 8192], 'edges': []})
        self.assertFalse(root.exists())
        self.assertFalse((self.root / brain.BRAIN / 'payloads').exists())

    def test_invalid_graph_json_leaves_old_bytes(self):
        for invalid in (float('nan'), float('inf'), set()):
            with self.subTest(invalid=invalid), self.assertRaises((ValueError, TypeError)):
                runner.atomic(self.root, runner.GRAPH, {'nodes': [invalid]})
            self.assertEqual(self.graph.read_bytes(), self.raw)

    def test_other_outputs_keep_layout_and_original_bound(self):
        value = {'nodes': [{'value': 'inside  whitespace\t\n 한글'}], 'edges': []}
        pretty = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
        for relative in ('data/operations/other.json', 'data/operations/reports/knowledge_graph.json',
                         'data/dashboard_runtime.json'):
            with self.subTest(relative=relative):
                self.assertEqual(runner.serialized_output(relative, value), pretty)
                with self.assertRaisesRegex(brain.BrainError, '^byte_limit_exceeded$'):
                    runner.atomic(self.root, relative, {'large': 'x' * brain.MAX_BYTES})
                self.assertFalse((self.root / relative).exists())


if __name__ == '__main__':
    unittest.main()
