"""Lossless graph composites retain bounded vault proofs and atomic publication."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import obsidian_brain as brain
import operations_graph_storage as storage
import run_jarvis_operations as runner


class SegmentedGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='segmented-graph-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root / '.gitignore').write_text('/obsidian/JARVIS_LUNA/BrainRuntime/\n')
        self.labels = dict(task='segmented-graph', team='operations', operation='local-analysis')
        self.value = {'nodes': [{'id': 'task:' + str(i), 'data': {'literal': '한글  \t\n' * 8}}
                                for i in range(30)],
                      'edges': [{'id': 'relation:' + str(i), 'source': 'task:' + str(i),
                                 'target': 'task:0', 'evidence': ['retained']} for i in range(30)],
                      'generated_at': '2026-01-02T03:04:05Z'}
        self.files = storage.prepare_operations_graph(self.value, force=True)
        self.write(self.files)
        self.source = self.root / 'data/source.json'
        self.source.write_bytes(b'{"genuine_input":true}\n')
        self.graph = self.root / storage.GRAPH_PATH
        self.members = list(storage.graph_members(self.files[storage.GRAPH_PATH]))

    def write(self, files):
        for name, raw in files.items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)

    def node(self, identifier):
        return json.loads((self.root / brain.BRAIN / 'nodes' / identifier[:2] /
                           (identifier + '.json')).read_bytes())

    def test_logical_input_readback_binds_every_original_member(self):
        seen = []
        original = brain._verified
        def spy(root, path, digest):
            seen.append(digest)
            return original(root, path, digest)
        with brain.execution(self.root, **self.labels) as run, patch.object(brain, '_verified', side_effect=spy):
            loaded = brain.load_artifact(self.graph, self.root)
            self.assertEqual(loaded['value'], self.value)
            self.assertEqual(loaded['count'], len(self.value))
            self.assertEqual(loaded['source_timestamps'], {'generated_at': self.value['generated_at']})
            self.assertEqual(self.node(loaded['artifact_id'])['source_timestamps'],
                             loaded['source_timestamps'])
            self.assertEqual(loaded['source_sha256'], hashlib.sha256(self.files[storage.GRAPH_PATH]).hexdigest())
            self.assertEqual(len(run.consumed), 1 + len(self.members))
            self.assertEqual(brain.verify_consumed(self.root), 1 + len(self.members))
            for raw in self.files.values():
                self.assertIn(hashlib.sha256(raw).hexdigest(), seen)
            self.assertEqual({self.node(i)['source_path'] for i in run.consumed}, set(self.files))
        self.assertEqual(runner.read(self.root, runner.GRAPH), self.value)

    def test_logical_output_proof_binds_all_members_without_consuming_them(self):
        with brain.execution(self.root, **self.labels) as run:
            brain.load_artifact(self.source, self.root)
            proof = brain.record_output(self.graph, self.root, **self.labels)
            self.assertEqual(len(run.consumed), 1)
            self.assertEqual(len(proof['output_artifact_ids']), 1 + len(self.members))
            generated = [r for r in self.node(proof['execution_id'])['relations'] if r['type'] == 'generated']
            self.assertEqual(len(generated), 1 + len(self.members))
            self.assertEqual({self.node(i)['source_path'] for i in run.outputs}, set(self.files))
            root_node = next(self.node(i) for i in run.outputs
                             if self.node(i)['source_path'] == storage.GRAPH_PATH)
            self.assertEqual(root_node['source_timestamps'],
                             {'generated_at': self.value['generated_at']})

    def test_atomic_output_keeps_segmented_form_and_preserves_all_old_bytes(self):
        changed = deepcopy(self.value)
        changed['nodes'].insert(0, {'id': 'new', 'data': {'literal': 'new record'}})
        with brain.execution(self.root, **self.labels) as run:
            brain.load_artifact(self.source, self.root)
            runner.atomic(self.root, runner.GRAPH, changed)
            self.assertEqual(brain.load_json(self.graph, self.root, None), changed)
            self.assertTrue(run.proof()['output_stored'])
        self.assertTrue(storage.is_graph_manifest(self.graph.read_bytes()))
        for member in self.members:
            self.assertEqual((self.root / member).read_bytes(), self.files[member])

    def test_missing_corrupt_and_hardlinked_member_never_default(self):
        member = self.root / self.members[0]
        original = member.read_bytes()
        member.unlink()
        with self.assertRaises(brain.IntegrityError):
            brain.load_json(self.graph, self.root, {'silent_fallback': True})
        member.write_bytes(original + b' ')
        with self.assertRaises(brain.IntegrityError):
            brain.load_json(self.graph, self.root, {})
        member.write_bytes(original)
        import os
        os.link(member, self.root / 'linked-copy')
        with self.assertRaises(brain.PathExcluded):
            brain.load_json(self.graph, self.root, {})

    def test_vault_member_tamper_is_detected_on_input_and_output(self):
        with brain.execution(self.root, **self.labels) as run:
            brain.load_artifact(self.graph, self.root)
            digest = hashlib.sha256(self.files[self.members[0]]).hexdigest()
            payload = self.root / brain.BRAIN / 'payloads' / digest[:2] / (digest + '.bin')
            payload.write_bytes(payload.read_bytes() + b' ')
            with self.assertRaises(brain.IntegrityError):
                brain.load_json(self.graph, self.root, {})
            with self.assertRaises(brain.IntegrityError):
                brain.record_output(self.graph, self.root, **self.labels)
            self.assertFalse(run.outputs)

    def test_logical_digest_and_metadata_tamper_fail_closed(self):
        meta = json.loads(self.graph.read_bytes())
        meta[storage.STORAGE_KEY]['logical_sha256'] = '0' * 64
        self.graph.write_text(json.dumps(meta))
        with self.assertRaises(brain.IntegrityError):
            brain.load_json(self.graph, self.root, {})
        with brain.execution(self.root, **self.labels) as run:
            brain.load_artifact(self.source, self.root)
            with self.assertRaises(brain.IntegrityError):
                brain.record_output(self.graph, self.root, **self.labels)
            self.assertFalse(run.outputs)

    def test_concurrent_manifest_change_fails_closed(self):
        original = brain._load_artifact
        def load(path, root, extensions):
            result = original(path, root, extensions)
            if str(path).endswith(self.members[0]):
                self.graph.write_bytes(self.graph.read_bytes() + b' ')
            return result
        with patch.object(brain, '_load_artifact', side_effect=load):
            with self.assertRaisesRegex(brain.IntegrityError, 'changed_during_read'):
                brain.load_json(self.graph, self.root, {})

    def test_private_secret_in_member_cannot_enter_vault(self):
        graph = deepcopy(self.value)
        graph['nodes'][0]['data']['api_key'] = 'secret value'
        secret_files = storage.prepare_operations_graph(graph, force=True)
        self.write(secret_files)
        with self.assertRaises(brain.PathExcluded):
            brain.load_json(self.graph, self.root, {})

    def test_scan_indexes_only_logical_root_not_orphan_or_live_segments(self):
        self.write({storage.GRAPH_DIRECTORY + '/orphan.json': b'{}'})
        result = brain.scan_public_data(self.root)
        names = [entry['source_path'] for entry in result['entries']]
        self.assertEqual(names, [storage.GRAPH_PATH, 'data/source.json'])
        self.assertEqual(result['excluded_codes']['excluded_graph_storage_members'], 1)
        self.assertFalse(result['truncated'])

    def test_bad_orphan_and_retained_capacity_leave_manifest_unchanged(self):
        previous = self.graph.read_bytes()
        invalid = self.root / storage.GRAPH_DIRECTORY / 'unrecognized.json'
        invalid.write_bytes(b'{}')
        with self.assertRaises(ValueError):
            runner.atomic(self.root, runner.GRAPH, self.value)
        self.assertEqual(self.graph.read_bytes(), previous)
        invalid.unlink()
        with patch.object(storage, 'GRAPH_AGGREGATE_MAX_BYTES', sum(map(len, self.files.values())) - 1):
            with self.assertRaises(ValueError):
                runner.atomic(self.root, runner.GRAPH, self.value)
        self.assertEqual(self.graph.read_bytes(), previous)

    def test_unchanged_checkpoint_adds_no_members_or_manifest_changes(self):
        before = {name: (self.root / name).read_bytes() for name in self.files}
        runner.atomic(self.root, runner.GRAPH, self.value)
        self.assertEqual({name: (self.root / name).read_bytes() for name in self.files}, before)
        self.assertEqual(len(list((self.root / storage.GRAPH_DIRECTORY).iterdir())), len(self.members))

    def test_invalid_member_never_enters_vault(self):
        member = self.root / self.members[0]
        invalid = member.read_bytes() + b' '
        member.write_bytes(invalid)
        digest = hashlib.sha256(invalid).hexdigest()
        with self.assertRaises(brain.IntegrityError):
            brain.load_json(self.graph, self.root, {})
        self.assertFalse((self.root / brain.BRAIN / 'payloads' / digest[:2] / (digest + '.bin')).exists())

    def test_interrupted_member_write_keeps_old_manifest_readable(self):
        changed = deepcopy(self.value)
        changed['nodes'].append({'id': 'appended', 'data': 'preserved'})
        previous = self.graph.read_bytes()
        original = runner._atomic_bytes
        def interrupt(root, name, raw, **kwargs):
            if name == runner.GRAPH:
                raise OSError('simulated interruption before pointer replacement')
            return original(root, name, raw, **kwargs)
        with patch.object(runner, '_atomic_bytes', side_effect=interrupt):
            with self.assertRaises(OSError):
                runner.atomic(self.root, runner.GRAPH, changed)
        self.assertEqual(self.graph.read_bytes(), previous)
        self.assertEqual(runner.read(self.root, runner.GRAPH), self.value)
        runner.atomic(self.root, runner.GRAPH, changed)
        self.assertEqual(runner.read(self.root, runner.GRAPH), changed)

    def test_only_exact_graph_root_expands_composite(self):
        other = self.root / 'data/ordinary.json'
        other.write_bytes(self.graph.read_bytes())
        loaded = brain.load_json(other, self.root, None)
        self.assertIn(storage.STORAGE_KEY, loaded)
        self.assertNotIn('nodes', loaded)


if __name__ == '__main__':
    unittest.main()
