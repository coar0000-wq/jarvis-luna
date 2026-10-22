"""Offline workflow boundaries and shell/Python guard checks."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/'.github/workflows/shopify-reviewed-draft-copy.yml'

class CopyWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=PATH.read_text();cls.doc=yaml.safe_load(cls.text);cls.steps=cls.doc['jobs']['copy']['steps']
    def step(self,name):return next(s for s in self.steps if s.get('name')==name)
    def test_manual_main_serialized_readonly_permissions(self):
        trigger=self.doc.get('on',self.doc.get(True));self.assertEqual(set(trigger),{'workflow_dispatch'})
        self.assertIs(trigger['workflow_dispatch']['inputs']['apply_copy']['default'],False)
        self.assertEqual(self.doc['permissions'],{'contents':'read','actions':'read'})
        self.assertEqual(self.doc['concurrency'],{'group':'daiso-daily-beauty-shopify','cancel-in-progress':False})
        self.assertEqual(self.doc['jobs']['copy']['if'],"github.ref == 'refs/heads/main'")
    def test_pinned_dependencies_and_actions(self):
        for s in self.steps:
            if 'uses' in s:self.assertRegex(s['uses'],r'^[\w./-]+@[0-9a-f]{40}$')
        self.assertIn('--require-hashes --only-binary=:all:',self.step('Install pinned verification dependencies')['run'])
    def test_no_shell_interpolation(self):
        for s in self.steps:self.assertNotIn('${{',s.get('run',''))
    def test_digest_checkpoint_before_write(self):
        names=[s.get('name') for s in self.steps]
        sequence=['Check requested plan digest before checkpoint','Persist immutable checkpoint before write','Apply exact copy once']
        self.assertEqual(sorted(names.index(s) for s in sequence),[names.index(s) for s in sequence])
        for name in sequence:self.assertEqual(self.step(name)['if'],'${{ inputs.apply_copy }}')
        c=self.step(sequence[1])['with'];self.assertIs(c['overwrite'],False);self.assertEqual(c['retention-days'],30)
        self.assertEqual(c['path'].split(),['out/draft-copy/plan.json','out/draft-copy/journal.json'])
    def test_prepare_no_apply_and_evidence_not_published(self):
        p=self.step('Prepare consistent live read-only plan')['run']
        self.assertIn('--read-live --fetch-sources',p);self.assertNotIn('--apply',p)
        self.assertIn('$RUNNER_TEMP/copy-evidence',p)
        for s in self.steps:
            if 'upload-artifact@' in s.get('uses',''):self.assertNotIn('copy-evidence',s['with']['path'])
    def test_recovery_read_only(self):
        r=self.step('Restore original checkpoint and reconcile without writing')
        self.assertIn('reconcile-artifact',r['run']);self.assertNotIn('--apply',r['run'])
        self.assertIn('reconciliation is read-only',self.step('Validate bounded inputs')['run'])
    def test_result_retention_even_on_failure(self):
        s=self.step('Preserve results including failures (no supplier image binaries)')
        self.assertEqual(s['if'],'always()');self.assertEqual(s['with']['path'],'out/draft-copy/*.json')
        self.assertEqual(s['with']['retention-days'],30)
    def test_network_blocked_tests_registered(self):
        s=self.step('Offline regression tests')['run']
        for value in ('socket.create_connection = blocked','socket.socket.connect = blocked',
                      'test_plan_draft_product_copy','test_apply_reviewed_draft_copy','test_reviewed_draft_copy_workflow'):
            self.assertIn(value,s)
    def test_shell_scripts_parse(self):
        for s in self.steps:
            if 'run' in s:
                r=subprocess.run(['bash','-n'],input=s['run'],text=True,capture_output=True)
                self.assertEqual(r.returncode,0,r.stderr)
    def test_invalid_dispatch_inputs_fail_before_remote(self):
        run=self.step('Validate bounded inputs')['run']
        for changes in ({'REVIEW_TICKET':'../evil'},{'APPLY_COPY':'true','RESTORE_ID':'1','RESTORE_DIGEST':'a'*64},
                        {'RESTORE_ID':'1','RESTORE_DIGEST':''},{'APPLY_COPY':'true','EXPECTED_DIGEST':''}):
            env=dict(os.environ,REVIEW_TICKET='missing-test-ticket',APPLY_COPY='false',EXPECTED_DIGEST='',
                     RESTORE_ID='',RESTORE_DIGEST='');env.update(changes)
            r=subprocess.run(['bash','-c',run],cwd=ROOT,env=env,capture_output=True,text=True)
            self.assertNotEqual(r.returncode,0)

if __name__=='__main__':unittest.main()
