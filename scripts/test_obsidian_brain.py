"""Local-only regression tests; fixtures never use the production vault."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import obsidian_brain as brain


class BrainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='brain-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # OS temp may itself be beneath a real Git checkout on this machine.
        # Real fixture repos exercise exclusion without waiving ancestor Git.
        subprocess.run(['git', '-C', str(self.root), 'init', '-q'], check=True,
                       capture_output=True)
        (self.root / '.git/info/exclude').write_text('/obsidian/JARVIS_LUNA/BrainRuntime/\n')
        self.source = self.write('data/input.json', b'{"observed_at":"2020-01-02T03:04:05Z","items":[1]}\n')
        self.labels = dict(task='test-task', team='test-team', operation='analysis')

    def write(self, relative, raw):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return target

    def nodes(self):
        return [json.loads(p.read_bytes()) for p in (self.root / brain.BRAIN / 'nodes').glob('*/*.json')]

    def node(self, identifier):
        return json.loads((self.root / brain.BRAIN / 'nodes' / identifier[:2] / (identifier + '.json')).read_bytes())

    def test_end_to_end_exact_bytes_timestamp_and_lineage(self):
        original = self.source.read_bytes()
        mtime = self.source.stat().st_mtime_ns
        with brain.execution(self.root, **self.labels) as run:
            value = brain.load_json(self.source, self.root, {})
            out = self.write('data/result.json', json.dumps({'count': len(value['items'])}).encode())
            report = brain.record_output(out, self.root, **self.labels)
            self.assertTrue(report['input_read_from_vault'])
            self.assertTrue(report['output_stored'])
            self.assertFalse(report['business_approval'])
            self.assertEqual(report['consumed_source_ids'], sorted(run.consumed))
        artifact = next(n for n in self.nodes() if n.get('role') == 'input')
        self.assertEqual(artifact['sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(artifact['source_path'], 'data/input.json')
        self.assertEqual(artifact['source_mtime_ns'], mtime)
        self.assertEqual(artifact['source_timestamps'], {'observed_at': '2020-01-02T03:04:05Z'})
        self.assertNotEqual(artifact['write_at'], artifact['source_timestamps']['observed_at'])
        self.assertEqual((self.root / artifact['payload_path']).read_bytes(), original)
        execution = self.node(report['execution_id'])
        self.assertEqual([r['target'] for r in execution['relations'] if r['type'] == 'consumed'], report['consumed_source_ids'])
        self.assertEqual(self.node(report['decision_id'])['decision_kind'], 'analysis_evidence_only')
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(self.source.stat().st_mtime_ns, mtime)

    def test_returned_decode_uses_vault_readback(self):
        seen = []
        real = brain._verified
        def spy(root, relative, digest):
            seen.append(Path(relative).as_posix())
            return real(root, relative, digest)
        with patch.object(brain, '_verified', side_effect=spy):
            self.assertEqual(brain.load_json(self.source, self.root, {})['items'], [1])
        self.assertGreaterEqual(sum('/payloads/' in p for p in seen), 2)

    def test_hash_mismatch_never_default_or_overwrite(self):
        brain.load_json(self.source, self.root, {})
        payload = next((self.root / brain.BRAIN / 'payloads').glob('*/*.bin'))
        payload.write_bytes(b'{"tampered":true}')
        with self.assertRaisesRegex(brain.IntegrityError, 'vault_hash_mismatch'):
            brain.load_json(self.source, self.root, {'fallback': True})
        self.assertEqual(payload.read_bytes(), b'{"tampered":true}')

    def test_output_rechecks_consumed_payload_integrity(self):
        with brain.execution(self.root, **self.labels) as run:
            brain.load_json(self.source, self.root, {})
            payload = next((self.root / brain.BRAIN / 'payloads').glob('*/*.bin'))
            payload.write_bytes(b'{"changed":true}')
            out = self.write('data/out.json', b'{}')
            with self.assertRaisesRegex(brain.IntegrityError, 'vault_hash_mismatch'):
                brain.record_output(out, self.root, **self.labels)
            self.assertFalse(run.proof()['output_stored'])
            self.assertFalse(any(n['type'] == 'execution' for n in self.nodes()))

    def test_multiple_consumed_versions_exactly_preserved(self):
        with brain.execution(self.root, **self.labels):
            brain.load_json(self.source, self.root, {})
            self.source.write_bytes(b'{"items":[2]}')
            brain.load_json(self.source, self.root, {})
            out = self.write('data/out.json', b'{}')
            result = brain.record_output(out, self.root, **self.labels)
            self.assertEqual(len(result['consumed_source_ids']), 2)
            inputs = [self.node(i) for i in result['consumed_source_ids']]
            self.assertEqual(len({i['sha256'] for i in inputs}), 2)

    def test_duplicate_read_cache_keeps_one_id_and_reverifies(self):
        with brain.execution(self.root, **self.labels) as run:
            first = brain.load_artifact(self.source, self.root)
            with patch.object(brain, '_snapshot', side_effect=AssertionError('no repeat snapshot')):
                second = brain.load_artifact(self.source, self.root)
            self.assertEqual(first['artifact_id'], second['artifact_id'])
            self.assertEqual(len(run.consumed), 1)
            self.assertEqual(len([n for n in self.nodes() if n.get('role') == 'input']), 1)
            payload = self.root / brain.BRAIN / 'payloads' / first['payload_id'][:2] / (first['payload_id'] + '.bin')
            payload.write_bytes(b'tampered')
            with self.assertRaisesRegex(brain.IntegrityError, 'vault_hash_mismatch'):
                brain.load_artifact(self.source, self.root)

    def test_cached_node_tamper_and_fresh_source_change(self):
        with brain.execution(self.root, **self.labels) as run:
            first = brain.load_artifact(self.source, self.root)
            self.source.write_bytes(b'{"id":2}')
            changed = brain.load_artifact(self.source, self.root)
            self.assertNotEqual(first['artifact_id'], changed['artifact_id'])
            self.assertEqual(len(run.consumed), 2)
            node = self.root / brain.BRAIN / 'nodes' / changed['artifact_id'][:2] / (changed['artifact_id'] + '.json')
            node.write_bytes(b'{}')
            with self.assertRaisesRegex(brain.IntegrityError, 'vault_hash_mismatch'):
                brain.load_json(self.source, self.root, {'not_allowed': True})

    def test_graph_links_resolve_explicit_typed_edges_and_workspace(self):
        with brain.execution(self.root, **self.labels):
            loaded = brain.load_artifact(self.source, self.root)
            out = self.write('data/out.json', b'{}')
            report = brain.record_output(out, self.root, **self.labels)
        workspace = hashlib.sha256(os.path.normcase(str(self.root.resolve())).encode()).hexdigest()
        self.assertEqual(self.node(loaded['artifact_id'])['source_workspace_id'], workspace)
        self.assertNotIn(str(self.root), json.dumps(self.nodes()))
        for identifier in (loaded['artifact_id'], report['execution_id'], report['decision_id'],
                           report['output_artifact_ids'][0]):
            node = self.node(identifier)
            note = self.root / brain.BRAIN / 'notes' / identifier[:2] / (identifier + '.md')
            self.assertEqual(note.read_bytes(), brain._note_bytes(identifier, node, self.root))
            for relation in node['relations']:
                target = relation['target']
                category, suffix = ('payloads', '.bin') if relation['target_type'] == 'payload' else ('notes', '')
                link = 'BrainRuntime/' + category + '/' + target[:2] + '/' + target + suffix
                self.assertIn(relation['type'] + ': [[' + link + ']]', note.read_text())
                target_path = self.root / 'obsidian/JARVIS_LUNA' / (link if suffix else link + '.md')
                self.assertTrue(target_path.is_file())

    def test_structured_input_artifact_formats_readback(self):
        fixtures = [('json', b'[{"observed_at":"2001-02-03"}]', 1),
                    ('jsonl', b'{"observed_at":"2001-02-03"}\n{"id":2}\n', 2),
                    ('csv', b'name,observed_at\nthing,2001-02-03\n', 1)]
        for suffix, raw, count in fixtures:
            with self.subTest(parser=suffix):
                source = self.write('data/format.' + suffix, raw)
                stamp = source.stat().st_mtime_ns
                loaded = brain.load_artifact(source, self.root)
                self.assertEqual(loaded['parser'], suffix)
                self.assertEqual(loaded['count'], count)
                self.assertTrue(loaded['input_read_from_vault'])
                self.assertEqual(loaded['source_sha256'], hashlib.sha256(raw).hexdigest())
                self.assertEqual(loaded['payload_id'], loaded['source_sha256'])
                artifact = self.node(loaded['artifact_id'])
                self.assertEqual((self.root / artifact['payload_path']).read_bytes(), raw)
                self.assertEqual(source.read_bytes(), raw)
                self.assertEqual(source.stat().st_mtime_ns, stamp)
                self.assertIn('2001-02-03', json.dumps(loaded['value']))

    def test_structured_input_secrets_and_parse_failures_never_archive(self):
        fixtures = [('jsonl', b'{"access_token":"do-not-copy"}\n', brain.PathExcluded),
                    ('csv', b'name,password\nx,do-not-copy\n', brain.PathExcluded),
                    ('jsonl', b'{broken}\n', brain.ArtifactParseError)]
        for suffix, raw, error in fixtures:
            with self.subTest(parser=suffix):
                source = self.write('data/reject.' + suffix, raw)
                with self.assertRaises(error):
                    brain.load_artifact(source, self.root)
        self.assertFalse((self.root / brain.BRAIN).exists())

    def test_no_fabricated_observation_timestamp(self):
        source = self.write('data/plain.json', b'{"items":[]}')
        brain.load_json(source, self.root, {})
        self.assertEqual(self.nodes()[0]['source_timestamps'], {})
        self.assertNotIn('observed_at', self.nodes()[0])

    def test_missing_invalid_not_consumed(self):
        with brain.execution(self.root, **self.labels) as run:
            sentinel = object()
            self.assertIs(brain.load_json('data/missing.json', self.root, sentinel), sentinel)
            invalid = self.write('data/invalid.json', b'not json')
            self.assertIs(brain.load_json(invalid, self.root, sentinel), sentinel)
            self.assertFalse(run.proof()['input_read_from_vault'])
            self.assertEqual(run.defaults, ['source_missing', 'source_invalid_json'])
            out = self.write('data/out.json', b'{}')
            with self.assertRaisesRegex(brain.BrainError, 'genuine_consumed_source_required'):
                brain.record_output(out, self.root, **self.labels)
        self.assertFalse((self.root / brain.BRAIN).exists())

    def test_private_unsupported_paths_report_excluded(self):
        paths = ['data/manual/mocra_profile.json', 'data/safety_checkpoints/state.json',
                 'data/typesafe_ledger.json', 'config/auth.json', 'data/secrets.json',
                 'obsidian/JARVIS_LUNA/original.json', 'data/raw.txt', '../outside.json']
        with brain.execution(self.root, **self.labels) as run:
            for p in paths:
                with self.subTest(path=p), self.assertRaises(brain.PathExcluded):
                    brain.load_json(p, self.root, {})
            self.assertEqual(len(run.excluded), len(paths))
        self.assertFalse((self.root / brain.BRAIN).exists())

    def test_secret_fields_nested_and_recognized_tokens_not_copied(self):
        for raw in (b'{"nested":{"api_key":"do-not-copy"}}',
                    b'{"description":"ghp_1234567890123456789012345"}'):
            source = self.write('data/input.json', raw)
            with self.assertRaises(brain.PathExcluded) as captured:
                brain.load_json(source, self.root, {})
            self.assertNotIn('do-not-copy', str(captured.exception))
        self.assertFalse((self.root / brain.BRAIN).exists())

    def test_context_required_and_no_previous_run_leak(self):
        out = self.write('data/out.json', b'{}')
        with self.assertRaisesRegex(brain.BrainError, 'matching_execution_context_required'):
            brain.record_output(out, self.root, **self.labels)
        with brain.execution(self.root, **self.labels):
            brain.load_json(self.source, self.root, {})
        with brain.execution(self.root, **self.labels):
            with self.assertRaisesRegex(brain.BrainError, 'genuine_consumed_source_required'):
                brain.record_output(out, self.root, **self.labels)

    def test_only_consumed_inputs_linked_and_scoped_labels(self):
        self.write('data/unread.json', b'{"unused":1}')
        out = self.write('data/out.json', b'{}')
        with brain.execution(self.root, **self.labels) as run:
            brain.load_json(self.source, self.root, {})
            with self.assertRaisesRegex(brain.BrainError, 'matching_execution_context_required'):
                brain.record_output(out, self.root, 'wrong', 'test-team', 'analysis')
            result = brain.record_output(out, self.root, **self.labels)
            self.assertEqual(len(result['consumed_source_ids']), 1)
        self.assertFalse(any(n.get('source_path') == 'data/unread.json' for n in self.nodes()))

    def test_csv_jsonl_output_and_secret_rejection(self):
        with brain.execution(self.root, **self.labels):
            brain.load_json(self.source, self.root, {})
            for name, raw in [('out.csv', b'name,count\nthing,1\n'), ('out.jsonl', b'{"count":1}\n')]:
                out = self.write('data/' + name, raw)
                self.assertTrue(brain.record_output(out, self.root, **self.labels)['output_stored'])
            for name, raw in [('private.csv', b'name,api_key\nx,secret\n'), ('private.jsonl', b'{"token":"secret"}\n')]:
                out = self.write('data/' + name, raw)
                with self.assertRaises(brain.PathExcluded):
                    brain.record_output(out, self.root, **self.labels)

    def test_public_context_and_exclusion_interface(self):
        self.assertIsNone(brain.current_execution(self.root))
        with brain.execution(self.root, **self.labels) as run:
            self.assertIs(brain.current_execution(self.root), run)
            self.assertFalse(brain.note_exclusion(self.source, self.root))
            self.assertTrue(brain.note_exclusion('data/manual/mocra_profile.json', self.root))
            self.assertTrue(brain.note_exclusion('data/operations/state.json', self.root))
            self.assertTrue(brain.note_exclusion('data/typesafe_ledger.json', self.root))
            self.assertEqual(len(run.excluded), 3)
            secret = self.write('data/nested.json', b'{"token":"never-copy"}')
            self.assertFalse(brain.note_exclusion(secret, self.root))
            with self.assertRaises(brain.PathExcluded):
                brain.load_json(secret, self.root, {})
            alias = self.root / 'data/manual/private.json'
            alias.parent.mkdir(exist_ok=True)
            os.link(self.source, alias)
            with self.assertRaises(brain.PathExcluded):
                brain.note_exclusion(alias, self.root)
        self.assertIsNone(brain.current_execution(self.root))

    def test_hardlinked_source_rejected(self):
        alias = self.root / 'data/alias.json'
        os.link(self.source, alias)
        with self.assertRaises(brain.PathExcluded):
            brain.load_json(alias, self.root, {})

    def test_size_bound(self):
        with patch.object(brain, 'MAX_BYTES', 8):
            with self.assertRaisesRegex(brain.BrainError, 'byte_limit_exceeded'):
                brain.load_json(self.source, self.root, {})
        self.assertFalse((self.root / brain.BRAIN).exists())

    def test_test_namespace_explicit_and_reset(self):
        # Simulate absent Git only for this fixture test. Production never
        # accepts an env flag or ignores an actual discovered repository.
        absent = subprocess.CompletedProcess(['git'], 128, b'', b'')
        with patch.object(brain, '_git', return_value=absent), tempfile.TemporaryDirectory(prefix='brain-unscoped-') as directory:
            root = Path(directory)
            source = root / 'data/in.json'
            source.parent.mkdir()
            source.write_bytes(b'{}')
            with self.assertRaisesRegex(brain.BrainError, 'git_repository_or_explicit_test_namespace_required'):
                brain.load_json(source, root, {})
            with brain.test_namespace(root):
                self.assertEqual(brain.load_json(source, root, None), {})
            with self.assertRaises(brain.BrainError):
                brain.load_json(source, root, {})

    def test_scan_metadata_only_no_cold_notes_or_hash(self):
        self.write('data/manual/mocra_profile.json', b'{}')
        self.write('data/row.csv', b'name\nx\n')
        self.write('obsidian/JARVIS_LUNA/old.md', b'original note')
        with patch.object(brain, '_sha', side_effect=AssertionError('no cold hashing')):
            result = brain.scan_public_data(self.root)
        self.assertEqual({r['source_path'] for r in result['entries']}, {'data/input.json', 'data/row.csv'})
        self.assertTrue(all(not r['consumed'] for r in result['entries']))
        self.assertGreaterEqual(result['excluded_count'], 1)
        self.assertFalse((self.root / brain.BRAIN).exists())
        self.assertTrue(brain.scan_public_data(self.root, limit=1)['truncated'])

    def test_bounded_hash_filenames(self):
        brain.load_json(self.source, self.root, {})
        for category in ('payloads', 'nodes', 'notes'):
            for p in (self.root / brain.BRAIN / category).glob('*/*'):
                self.assertRegex(p.stem, r'^[0-9a-f]{64}$')
                self.assertEqual(p.parent.name, p.stem[:2])
                if category == 'notes':
                    node = self.node(p.stem)
                    self.assertEqual(p.read_bytes(), brain._note_bytes(p.stem, node, self.root))
                else:
                    self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), p.stem)


class NamespaceLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='brain-namespace-lease-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(['git', '-C', str(self.root), 'init', '-q'], check=True, capture_output=True)
        self.exclude = self.root / '.git/info/exclude'
        self.exclude.write_text('/obsidian/JARVIS_LUNA/BrainRuntime/\n')
        (self.root / 'data').mkdir()
        self.source = self.root / 'data/input.json'
        self.source.write_bytes(b'{"id":1}')
        self.labels = dict(task='lease-test', team='local', operation='analysis')

    def change_source(self):
        raw = b'{"id":2}'
        self.source.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        return self.root / brain.BRAIN / 'payloads' / digest[:2] / (digest + '.bin')

    def test_stable_namespace_reuses_verdict_only_within_invocation(self):
        real = brain._git
        with patch.object(brain, '_git', wraps=real) as calls:
            with brain.execution(self.root, **self.labels) as run:
                brain.load_artifact(self.source, self.root)
                self.assertIsNotNone(run.namespace_cache)
                before = calls.call_count
                for number in range(2, 6):
                    self.source.write_bytes(json.dumps({'id': number}).encode())
                    brain.load_artifact(self.source, self.root)
                self.assertEqual(calls.call_count, before)
            after = calls.call_count
            self.assertGreater(after, before)  # Forced full exit audit.
            with brain.execution(self.root, **self.labels):
                brain.load_artifact(self.source, self.root)
                self.assertGreater(calls.call_count, after)  # No global cache.

    def test_info_exclude_mutation_fails_before_new_payload(self):
        with self.assertRaisesRegex(brain.BrainError, 'brain_git_exclusion_required_before_write'):
            with brain.execution(self.root, **self.labels):
                brain.load_artifact(self.source, self.root)
                self.exclude.write_text('')
                payload = self.change_source()
                brain.load_artifact(self.source, self.root)
        self.assertFalse(payload.exists())

    def test_root_gitignore_mutation_fails_before_new_payload(self):
        self.exclude.write_text('')
        ignore = self.root / '.gitignore'
        ignore.write_text('/obsidian/JARVIS_LUNA/BrainRuntime/\n')
        with self.assertRaisesRegex(brain.BrainError, 'brain_git_exclusion_required_before_write'):
            with brain.execution(self.root, **self.labels):
                brain.load_artifact(self.source, self.root)
                ignore.write_text('')
                payload = self.change_source()
                brain.load_artifact(self.source, self.root)
        self.assertFalse(payload.exists())

    def test_private_index_stage_invalidates_lease_without_force(self):
        with self.assertRaisesRegex(brain.BrainError, 'brain_must_be_untracked_and_git_excluded'):
            with brain.execution(self.root, **self.labels):
                brain.load_artifact(self.source, self.root)
                self.exclude.write_text('')
                subprocess.run(['git', '-C', str(self.root), 'add', '--', brain.BRAIN.as_posix()],
                               check=True, capture_output=True)
                self.exclude.write_text('/obsidian/JARVIS_LUNA/BrainRuntime/\n')
                payload = self.change_source()
                brain.load_artifact(self.source, self.root)
        self.assertFalse(payload.exists())

    def test_transient_lock_waits_then_full_checks_before_new_payload(self):
        with brain.execution(self.root, **self.labels) as run:
            brain.load_artifact(self.source, self.root)
            payload = self.change_source()
            original = brain._policy_fingerprint
            events = []
            def transient(paths):
                if not events:
                    events.append('lock_observed')
                    raise brain.BrainError('git_policy_transition_in_progress')
                return original(paths)
            def wait(seconds):
                self.assertFalse(payload.exists())
                events.append('wait_without_write')
            with patch.object(brain, '_policy_fingerprint', side_effect=transient), \
                    patch.object(brain.time, 'sleep', side_effect=wait) as sleeps, \
                    patch.object(brain, '_full_exclusion', wraps=brain._full_exclusion) as full:
                brain.load_artifact(self.source, self.root)
                self.assertGreaterEqual(full.call_count, 2)
                self.assertEqual(sleeps.call_count, 1)
            self.assertTrue(payload.exists())
            self.assertIsNotNone(run.namespace_cache)
            self.assertEqual(events, ['lock_observed', 'wait_without_write'])

    def test_git_read_checks_explicitly_disable_optional_refresh_locks(self):
        result = subprocess.CompletedProcess(['git'], 0, b'', b'')
        with patch.dict(os.environ, {'GIT_OPTIONAL_LOCKS': '1', 'GIT_INDEX_FILE': 'untrusted'}), \
                patch.object(brain.subprocess, 'run', return_value=result) as run:
            brain._git(self.root, 'rev-parse', '--show-toplevel')
        environment = run.call_args.kwargs['env']
        self.assertEqual(environment['GIT_OPTIONAL_LOCKS'], '0')
        self.assertNotIn('GIT_INDEX_FILE', environment)

    def test_index_transition_lock_fails_closed(self):
        with self.assertRaisesRegex(brain.BrainError, 'git_policy_transition_in_progress'):
            with brain.execution(self.root, **self.labels):
                brain.load_artifact(self.source, self.root)
                (self.root / '.git/index.lock').write_bytes(b'in-flight')
                payload = self.change_source()
                brain.load_artifact(self.source, self.root)
        self.assertFalse(payload.exists())
        self.assertEqual((self.root / '.git/index.lock').read_bytes(), b'in-flight')

    def test_final_audit_and_output_force_git_checks(self):
        real = brain._git
        with patch.object(brain, '_git', wraps=real) as calls:
            with brain.execution(self.root, **self.labels):
                brain.load_artifact(self.source, self.root)
                before = calls.call_count
                brain.audit(self.root)
                self.assertGreater(calls.call_count, before)
                before = calls.call_count
                output = self.root / 'data/output.json'
                output.write_bytes(b'{}')
                brain.record_output(output, self.root, **self.labels)
                self.assertGreater(calls.call_count, before)


class GitExclusionTests(unittest.TestCase):
    def git(self, root, *args):
        result = subprocess.run(['git', '-C', str(root), *args], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        return result

    def test_real_repo_requires_full_exclusion_and_denies_test_override(self):
        with tempfile.TemporaryDirectory(prefix='brain-git-') as directory:
            root = Path(directory)
            self.git(root, 'init', '-q')
            source = root / 'data/in.json'
            source.parent.mkdir()
            source.write_bytes(b'{}')
            with self.assertRaisesRegex(brain.BrainError, 'brain_git_exclusion_required_before_write'):
                brain.load_json(source, root, {})
            self.assertFalse((root / brain.BRAIN).exists())
            with self.assertRaisesRegex(brain.BrainError, 'test_namespace_cannot_waive_git_repository'):
                with brain.test_namespace(root):
                    pass
            exclusion = root / '.git/info/exclude'
            with exclusion.open('a', encoding='utf-8') as handle:
                handle.write('\n/obsidian/JARVIS_LUNA/BrainRuntime/\n')
            self.assertEqual(brain.load_json(source, root, None), {})
            self.assertTrue(brain.audit(root)['git_exclusion_verified'])
            # Model a legacy tracked runtime namespace without a force action.
            exclusion.write_text('')
            self.git(root, 'add', '--', brain.BRAIN.as_posix())
            exclusion.write_text('/obsidian/JARVIS_LUNA/BrainRuntime/\n')
            with self.assertRaisesRegex(brain.BrainError, 'brain_must_be_untracked_and_git_excluded'):
                brain.load_json(source, root, {})

    def test_partial_payload_ignore_insufficient(self):
        with tempfile.TemporaryDirectory(prefix='brain-git-') as directory:
            root = Path(directory)
            self.git(root, 'init', '-q')
            (root / '.git/info/exclude').write_text('/obsidian/JARVIS_LUNA/BrainRuntime/payloads/\n')
            with self.assertRaisesRegex(brain.BrainError, 'brain_git_exclusion_required_before_write'):
                brain.audit(root)


if __name__ == '__main__':
    unittest.main()
