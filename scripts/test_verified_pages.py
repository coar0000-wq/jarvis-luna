#!/usr/bin/env python3
"""Offline invariants for the only allowed Pages deployment path."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github' / 'workflows'


def load_workflow(path):
    doc = yaml.safe_load(path.read_text(encoding='utf-8'))
    # PyYAML's YAML 1.1 treats the GitHub Actions 'on' key as boolean True.
    return doc, doc.get('on', doc.get(True, {}))


class VerifiedPagesTests(unittest.TestCase):
    def setUp(self):
        self.doc, self.trigger = load_workflow(WORKFLOWS / 'pages-verified.yml')
        self.job = self.doc['jobs']['verified-deploy']
        self.steps = self.job['steps']

    def step(self, name):
        return next(s for s in self.steps if s.get('name') == name)

    def test_only_completed_main_workflows_trigger(self):
        self.assertEqual(set(self.trigger), {'workflow_run', 'workflow_dispatch'})
        trigger = self.trigger['workflow_run']
        self.assertEqual(trigger['types'], ['completed'])
        self.assertEqual(trigger['branches'], ['main'])

    def test_every_publisher_can_wake_the_verifier(self):
        covered = set(self.trigger['workflow_run']['workflows'])
        self.assertIn('배포 전 검증', covered)
        for file in WORKFLOWS.glob('*.yml'):
            text = file.read_text(encoding='utf-8')
            if 'uses: ./.github/actions/publish' in text:
                doc, _ = load_workflow(file)
                self.assertIn(doc['name'], covered, file.name)

    def test_upstream_success_same_repository_and_main_are_required(self):
        condition = self.job['if']
        for required in ["conclusion == 'success'", "head_branch == 'main'",
                         'head_repository.full_name == github.repository',
                         "event != 'pull_request'"]:
            self.assertIn(required, condition)

    def test_least_privilege_permissions(self):
        self.assertEqual(self.doc['permissions'],
                         {'contents': 'read', 'actions': 'read', 'pages': 'write', 'id-token': 'write'})
        self.assertEqual(self.doc['concurrency']['group'], 'pages')

    def test_current_main_not_publisher_start_sha_is_checked_out(self):
        checkout = self.step('Checkout current published main')
        self.assertEqual(checkout['with']['ref'], 'main')
        self.assertNotIn('head_sha', str(checkout))

    def test_verification_cannot_be_continued_or_masked(self):
        gate = self.step('Validate the exact deployment snapshot')
        self.assertFalse(gate.get('continue-on-error', False))
        self.assertNotIn('if', gate)
        body = gate['run']
        self.assertNotIn('| tee', body)
        self.assertIn('rc=$?', body)
        self.assertIn('[ "$rc" != 0 ] && [ "$rc" != 2 ]', body)
        self.assertIn('exit 1', body)
        self.assertEqual(gate['env']['TYPESAFE_ENABLED'], '0')
        self.assertEqual(gate['env']['GEMINI_FALLBACK_ENABLED'], '0')
        self.assertNotIn('secrets.', str(gate))

    def test_all_repair_tests_exist_and_are_deployment_requirements(self):
        body = self.step('Validate the exact deployment snapshot')['run']
        required = ['test_preflight_workflow.py', 'test_daiso_collection_validation.py',
                    'test_listing_copy_local.py', 'test_operational_freshness.py',
                    'test_workflow_status.py', 'test_verified_pages.py',
                    'test_operational_integration.py']
        for file in required:
            self.assertTrue((ROOT / 'scripts' / file).is_file(), file)
            self.assertIn('python scripts/' + file, body)
        self.assertIn('python scripts/build_artifact_graph.py --check', body)

    def test_stale_checkout_is_rejected_before_upload(self):
        rejection = self.step('Reject an obsolete checkout')
        self.assertIn('git fetch origin main', rejection['run'])
        self.assertIn('git rev-parse HEAD', rejection['run'])
        self.assertIn('git rev-parse FETCH_HEAD', rejection['run'])
        self.assertIn('exit 1', rejection['run'])
        names = [s.get('name') for s in self.steps]
        self.assertLess(names.index('Validate the exact deployment snapshot'),
                        names.index('Reject an obsolete checkout'))
        self.assertLess(names.index('Reject an obsolete checkout'), names.index('Upload verified site'))

    def test_manual_recovery_and_bounded_current_main_revalidation(self):
        self.assertIn("github.ref == 'refs/heads/main'", self.job['if'])
        body = self.step('Validate the exact deployment snapshot')['run']
        self.assertIn('for attempt in 1 2 3', body)
        self.assertIn('git reset --hard FETCH_HEAD', body)
        self.assertIn('python scripts/build_public_site.py --output dist', body)
        self.assertIn('python scripts/check_public_site.py --root dist', body)
        self.assertIn('python scripts/test_public_site.py', body)

    def test_duplicate_requires_authenticated_verified_run_and_matching_site_metadata(self):
        body = self.step('Skip an already verified identical deployment')['run']
        self.assertIn("'Authorization': 'Bearer '", body)
        self.assertIn("r.get('conclusion') == 'success'", body)
        self.assertIn("previous.get('site_hash') == local['site_hash']", body)
        self.assertIn('except Exception:', body)
        self.assertIn('skipped = False', body)

    def test_upload_and_deploy_never_bypass_a_failed_gate(self):
        for name in ['Configure Pages', 'Upload verified site', 'Deploy verified site']:
            step = self.step(name)
            self.assertFalse(step.get('continue-on-error', False))
            self.assertEqual(step['if'], "steps.duplicate.outputs.skip != 'true'")
        self.assertTrue(self.step('Upload verified site')['uses'].startswith('actions/upload-pages-artifact@'))
        self.assertEqual(self.step('Upload verified site')['with']['path'], 'dist')
        self.assertTrue(self.step('Deploy verified site')['uses'].startswith('actions/deploy-pages@'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
