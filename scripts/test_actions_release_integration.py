#!/usr/bin/env python3
"""Release security invariants, no network and no production mutations."""
import ast
from pathlib import Path
import unittest
import yaml
ROOT = Path(__file__).resolve().parents[1]

class ReleaseIntegrationTests(unittest.TestCase):
    def load(self, name):
        return yaml.safe_load((ROOT / '.github/workflows' / name).read_text(encoding='utf-8'))

    def test_common_action_has_only_safe_transaction(self):
        doc = yaml.safe_load((ROOT / '.github/actions/publish/action.yml').read_text(encoding='utf-8'))
        self.assertEqual(len(doc['runs']['steps']), 1)
        step = doc['runs']['steps'][0]
        self.assertIn('scripts/publish_transaction.py', step['run'])
        self.assertIn('set -euo pipefail', step['run'])
        self.assertEqual(step['env']['TYPESAFE_ENABLED'], '0')
        self.assertEqual(step['env']['GEMINI_FALLBACK_ENABLED'], '0')
        for expression in ('inputs.paths', 'inputs.message'):
            self.assertIn(expression, str(step['env']))
            self.assertNotIn(expression, step['run'])
        for unsafe in ('--ours', 'git add -A', 'git reset --hard', 'git clean', '--force'):
            self.assertNotIn(unsafe, step['run'])

    def test_active_pages_only_one_deployer(self):
        owners = []
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            doc = yaml.safe_load(path.read_text(encoding='utf-8'))
            if (doc.get('permissions') or {}).get('pages') == 'write':
                owners.append(path.name)
            for job in doc.get('jobs', {}).values():
                if (job.get('permissions') or {}).get('pages') == 'write':
                    self.assertEqual(path.name, 'pages-verified.yml')
                for step in job.get('steps', []):
                    if 'deploy-pages@' in step.get('uses', ''):
                        self.assertEqual(path.name, 'pages-verified.yml')
        self.assertEqual(owners, ['pages-verified.yml'])

    def test_required_new_checks_exist_and_preflight_runs_them(self):
        body = (ROOT / '.github/workflows/preflight.yml').read_text(encoding='utf-8')
        for name in ('test_collector_result.py', 'test_release_quality.py', 'test_publish_transaction.py',
                     'test_public_site.py', 'test_dependency_pins.py', 'test_actions_release_integration.py',
                     'test_product_change_ledger.py', 'test_publish_graph_contract.py'):
            self.assertTrue((ROOT / 'scripts' / name).is_file(), name)
            self.assertIn('python scripts/' + name, body, name)

    def test_core_no_synthetic_generators(self):
        doc = self.load('JARVIS-Core-Automation.yml')
        runs = '\n'.join(step.get('run', '') for step in doc['jobs']['core-automation']['steps'])
        self.assertNotIn('python scripts/google_search_data_collection.py', runs)
        self.assertNotIn('python scripts/obsidian_realtime_sync.py', runs)
        text = (ROOT / '.github/workflows/JARVIS-Core-Automation.yml').read_text(encoding='utf-8')
        self.assertIn('check_release_quality.py', text)
        self.assertIn('collector_result.py', text)

    def test_scheduled_model_evaluation_does_not_overwrite_prior_weights_first(self):
        for name in ('JARVIS-Deep-Analysis.yml','jarvis-real-knowledge.yml'):
            text=(ROOT/'.github/workflows'/name).read_text(encoding='utf-8')
            self.assertNotIn('python train_real_knowledge.py',text)
            self.assertIn('tune_real_knowledge_moe.py',text);self.assertIn('--promote',text)
        text=(ROOT/'.github/workflows/jarvis-real-knowledge.yml').read_text(encoding='utf-8')
        self.assertNotIn('tune step soft-failed',text);self.assertNotIn('import numpy, pandas',text)
        tree=ast.parse((ROOT/'tune_real_knowledge_moe.py').read_text(encoding='utf-8'))
        assignments=[n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='promote' for t in n.targets)]
        self.assertTrue(any(isinstance(n.value,ast.BoolOp) and isinstance(n.value.op,ast.And)
                            and any(isinstance(v,ast.Name) and v.id=='effective' for v in n.value.values) for n in assignments))
        guarded=[n for n in ast.walk(tree) if isinstance(n,ast.If) and isinstance(n.test,ast.Name) and n.test.id=='promote']
        self.assertTrue(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='write_bytes'
                            for block in guarded for n in ast.walk(block)))

    def test_frontend_never_assumes_missing_execution_evidence_is_success(self):
        text = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="pipeline-health"', text)
        self.assertIn('d.pipeline_health', text)
        self.assertIn('현재 회차 증적 미기록(정상으로 추정하지 않음)', text)
        self.assertIn('일부 실패·기존 데이터 사용', text)

if __name__ == '__main__':
    unittest.main(verbosity=2)
