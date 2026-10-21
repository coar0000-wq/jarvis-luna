#!/usr/bin/env python3
"""Offline contract checks for the explicitly reviewed gallery workflow."""
from pathlib import Path
import subprocess
import json
import os
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / '.github/workflows/shopify-reviewed-gallery.yml'


class ReviewedGalleryWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PATH.read_text(encoding='utf-8')
        cls.doc = yaml.safe_load(cls.text)
        cls.steps = cls.doc['jobs']['gallery']['steps']

    def step(self, name):
        return next(s for s in self.steps if s.get('name') == name)

    def test_only_explicit_dispatch_with_safe_default(self):
        trigger = self.doc.get('on', self.doc.get(True))
        self.assertEqual(set(trigger), {'workflow_dispatch'})
        inputs = trigger['workflow_dispatch']['inputs']
        self.assertIs(inputs['apply_images']['default'], False)
        self.assertEqual(inputs['apply_images']['type'], 'boolean')
        self.assertTrue(inputs['review_ticket']['required'])

    def test_read_only_github_permissions_and_serialized_main(self):
        self.assertEqual(self.doc['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertEqual(self.doc['concurrency']['group'], 'daiso-daily-beauty-shopify')
        self.assertIs(self.doc['concurrency']['cancel-in-progress'], False)
        self.assertEqual(self.doc['jobs']['gallery']['if'], "github.ref == 'refs/heads/main'")
        self.assertLessEqual(self.doc['jobs']['gallery']['timeout-minutes'], 20)

    def test_actions_and_dependencies_are_pinned(self):
        for step in self.steps:
            if 'uses' in step:
                self.assertRegex(step['uses'], r'^[\w./-]+@[0-9a-f]{40}$')
        install = self.step('고정 검증 의존성')['run']
        self.assertIn('--require-hashes --only-binary=:all:', install)
        self.assertIn('requirements/requirements-verification.txt', install)

    def test_untrusted_inputs_are_not_shell_interpolated(self):
        for step in self.steps:
            self.assertNotIn('${{', step.get('run', ''))
        guard = self.step('입력 범위 확인')['run']
        self.assertIn("r'[A-Za-z0-9_-]{1,64}'", guard)
        self.assertIn("r'[0-9a-f]{64}'", guard)
        self.assertIn("data/manual/gallery_upload", guard)
        self.assertIn("scope.json", guard)
        self.assertIn("manifest.json", guard)

    def test_prepare_reads_without_apply(self):
        run = self.step('현재 상품 읽기 및 정확 계획 준비')['run']
        self.assertIn(' prepare ', run)
        self.assertIn('--read-live', run)
        self.assertNotIn('--apply', run)

    def test_apply_is_after_digest_and_durable_checkpoint(self):
        names = [s.get('name') for s in self.steps]
        guard = self.step('적용 계획 일치 확인')
        checkpoint = self.step('쓰기 전 계획과 기록 영속 보관')
        execute = self.step('검증된 누락 이미지 추가 후 재조회')
        self.assertLess(names.index(guard['name']), names.index(checkpoint['name']))
        self.assertLess(names.index(checkpoint['name']), names.index(execute['name']))
        for step in (guard, checkpoint, execute):
            self.assertEqual(step['if'], '${{ inputs.apply_images }}')
        self.assertIn('test "$EXPECTED" = "$ACTUAL"', guard['run'])
        self.assertEqual(checkpoint['with']['if-no-files-found'], 'error')
        self.assertIs(checkpoint['with']['overwrite'], False)
        self.assertGreaterEqual(checkpoint['with']['retention-days'], 30)
        self.assertEqual(checkpoint['with']['path'].split(),
                         ['out/gallery/plan.json', 'out/gallery/journal.json'])

    def test_execution_binds_artifact_run_and_code(self):
        step = self.step('검증된 누락 이미지 추가 후 재조회')
        for flag in ('--expected-plan-digest', '--artifact-id', '--artifact-digest',
                     '--repository', '--run-id', '--run-attempt', '--code-sha', '--workflow-path'):
            self.assertIn(flag, step['run'])
        self.assertIn('steps.checkpoint.outputs.artifact-id', step['env']['CHECKPOINT_ID'])
        self.assertIn('steps.checkpoint.outputs.artifact-digest', step['env']['CHECKPOINT_DIGEST'])
        self.assertEqual(step['env']['GITHUB_TOKEN'], '${{ github.token }}')

    def test_reports_preserved_even_on_unknown_write(self):
        step = self.step('결과와 미확인 상태 보관')
        self.assertEqual(step['if'], 'always()')
        self.assertEqual(step['with']['path'], 'out/gallery/')
        self.assertIn('github.run_id', step['with']['name'])
        self.assertIn('github.run_attempt', step['with']['name'])

    def test_tests_block_network_and_registered_in_preflight(self):
        run = self.step('오프라인 회귀 검사')['run']
        self.assertIn('socket.create_connection = blocked', run)
        self.assertIn('socket.socket.connect = blocked', run)
        preflight = (ROOT / '.github/workflows/preflight.yml').read_text(encoding='utf-8')
        for name in ('test_active_product_gallery_plan', 'test_apply_reviewed_product_gallery',
                     'test_reviewed_gallery_workflow'):
            self.assertIn(name, run)
            command = (f'python -B -m unittest discover -s scripts -p "{name}.py"'
                       if name == 'test_active_product_gallery_plan'
                       else f'python -B scripts/{name}.py')
            self.assertEqual(preflight.count(command), 1)

    def test_reconciliation_cannot_prepare_or_apply(self):
        restore = self.step('이전 미확인 실행 읽기 재조회')
        self.assertEqual(restore['if'], "${{ inputs.reconcile_artifact_id != '' }}")
        self.assertEqual(self.step('현재 상품 읽기 및 정확 계획 준비')['if'],
                         "${{ inputs.reconcile_artifact_id == '' }}")
        self.assertIn(' reconcile-artifact ', restore['run'])
        self.assertNotIn('--apply', restore['run'])
        for flag in ('--artifact-id', '--artifact-digest', '--repository',
                     '--expected-plan-digest', '--expected-shop', '--expected-product'):
            self.assertIn(flag, restore['run'])

    def test_input_guard_executes_safe_targets_and_rejects_write_restore_mix(self):
        guard = self.step('입력 범위 확인')['run']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ticket = root / 'data/manual/gallery_upload/review-123'
            ticket.mkdir(parents=True)
            (ticket / 'scope.json').write_text(json.dumps({'identity': {
                'shop': {'myshopifyDomain': 'example.myshopify.com'},
                'product_id': 'gid://shopify/Product/123'}}))
            (ticket / 'manifest.json').write_text('{}')
            env = dict(os.environ, REVIEW_TICKET='review-123', APPLY_IMAGES='false',
                       EXPECTED_PLAN_DIGEST='a' * 64, RECONCILE_ID='123',
                       RECONCILE_DIGEST='b' * 64, GITHUB_OUTPUT=str(root / 'outputs'))
            good = subprocess.run(['bash', '-e'], cwd=root, env=env, input=guard,
                                  text=True, capture_output=True)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertIn('expected_product=gid://shopify/Product/123', (root / 'outputs').read_text())
            for changes in ({'APPLY_IMAGES': 'true'}, {'RECONCILE_DIGEST': ''},
                            {'REVIEW_TICKET': '../outside'}, {'EXPECTED_PLAN_DIGEST': ''},
                            {'RECONCILE_ID': '123; false'}):
                bad = subprocess.run(['bash', '-e'], cwd=root, env=dict(env, **changes),
                                     input=guard, text=True, capture_output=True)
                self.assertNotEqual(bad.returncode, 0, changes)

    def test_failed_cli_pipeline_cannot_turn_green(self):
        for step in self.steps:
            if 'run' in step:
                self.assertEqual(step['run'].splitlines()[0], 'set -euo pipefail')
        for state in ('write_unknown', 'verification_pending', 'hold'):
            script = ('set -euo pipefail\n'
                      'python -c \'import sys; print("' + state + '"); sys.exit(2)\' | tee /dev/null\n')
            output = subprocess.run(['bash', '-e'], input=script, text=True, capture_output=True)
            self.assertEqual(output.returncode, 2, (state, output.stderr))

    def test_shell_scripts_parse_without_running(self):
        for step in self.steps:
            if 'run' in step:
                result = subprocess.run(['bash', '-n'], input=step['run'], text=True,
                                        capture_output=True, check=False)
                self.assertEqual(result.returncode, 0, (step.get('name'), result.stderr))


if __name__ == '__main__':
    unittest.main()
