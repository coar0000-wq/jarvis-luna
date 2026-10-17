"""Offline contract checks for the non-producing manual revalidation workflow."""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / '.github/workflows/latest-code-revalidation.yml'


class RevalidationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = PATH.read_text(encoding='utf-8')
        self.doc = yaml.load(self.text, Loader=yaml.BaseLoader)

    def test_manual_main_only_with_read_permissions(self):
        self.assertEqual(set(self.doc['on']), {'workflow_dispatch'})
        self.assertEqual(self.doc['permissions'], {'contents': 'read', 'actions': 'read'})
        for job in self.doc['jobs'].values():
            self.assertEqual(job['if'], "github.ref == 'refs/heads/main'")

    def test_all_five_scopes_only_run_existing_fixture_tests(self):
        job = self.doc['jobs']['offline-regressions']
        rows = job['strategy']['matrix']['include']
        self.assertEqual({row['scope'] for row in rows}, {'core', 'deep', 'fx', 'daiso', 'serpapi'})
        for row in rows:
            for module in row['tests'].split():
                self.assertTrue(module.startswith('scripts/test_'), module)
                self.assertTrue((ROOT / module).is_file(), module)
        step = next(s for s in job['steps'] if s.get('name') == 'Run fixture-only regressions')
        self.assertIn('python -B "$test"', step['run'])

    def test_real_history_has_no_mock_continuity_or_override(self):
        history = self.doc['jobs']['authenticated-history']
        self.assertNotIn('env', history)
        calls = []
        for step in history['steps']:
            self.assertNotIn('JARVIS_SOURCE_CONTINUITY', step.get('env', {}))
            self.assertNotIn('JARVIS_OPERATIONS_CONTINUITY', step.get('env', {}))
            self.assertNotIn('--verify-current', step.get('run', ''))
            if step.get('id') in {'source', 'operations'}:
                calls.append(step['run'])
        self.assertEqual(calls, ['python -B scripts/restore_source_safety.py --root "$GITHUB_WORKSPACE"',
                                 'python -B scripts/restore_operations_safety.py --root "$GITHUB_WORKSPACE"'])
        final = history['steps'][-1]['run']
        self.assertIn('test "$SOURCE_OUTCOME" = success && test "$OPERATIONS_OUTCOME" = success', final)

    def test_no_provider_secrets_publish_or_snapshot_upload(self):
        self.assertEqual(self.doc['env'], {'TYPESAFE_ENABLED': '0', 'GEMINI_ENABLED': '0',
                                           'GEMINI_FALLBACK_ENABLED': '0'})
        for job in self.doc['jobs'].values():
            for step in job['steps']:
                executable = step.get('run', '')
                self.assertNotIn('secrets.', str(step))
                self.assertNotIn('git push', executable)
                self.assertNotIn('scripts/publish_transaction.py', executable)
                self.assertNotIn('scripts/run_jarvis_operations.py', executable)
                self.assertNotIn('upload-artifact', step.get('uses', ''))
                self.assertNotIn('./.github/actions/publish', step.get('uses', ''))


if __name__ == '__main__':
    unittest.main(verbosity=2)
