"""Offline checks of shared team support wiring and canonical boundaries."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml
ROOT=Path(__file__).resolve().parents[1]
WF=ROOT/'.github/workflows'
spec=importlib.util.spec_from_file_location('setup_shared',ROOT/'scripts/setup_typesafe_shared.py')
bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)

class WiringTests(unittest.TestCase):
    def test_consumers_same_budget_main_only_and_scoped_secret(self):
        envs=[]
        for name in ('JARVIS-Deep-Analysis.yml','shopify-listing-copy.yml'):
            doc=yaml.safe_load((WF/name).read_text(encoding='utf-8'))
            self.assertEqual(doc['concurrency']['group'],'main-publish')
            self.assertFalse(doc['concurrency']['cancel-in-progress'])
            job=next(iter(doc['jobs'].values()));env=job['env'];envs.append(env)
            self.assertIn("github.ref == 'refs/heads/main'",env['TYPESAFE_ENABLED'])
            self.assertEqual(env['TYPESAFE_API_KEY'],'${{ secrets.TYPESAFE_SHARED_API_KEY }}')
            self.assertEqual(env['TYPESAFE_FREE_CREDITS_ONLY'],'1')
            self.assertNotIn('TYPESAFE_ALLOW_PAID',env)
            self.assertEqual(env['TYPESAFE_ACCOUNT_MAX_COST_USD'],'1.0')
            self.assertIn('github.run_attempt',env['TYPESAFE_WORKFLOW_ID'])
            self.assertEqual(doc['permissions']['actions'],'read')
            steps=job['steps'];bootstrap_step=next(s for s in steps if 'setup_typesafe_shared.py' in s.get('run',''))
            self.assertEqual(bootstrap_step['env']['GH_TOKEN'],'${{ github.token }}')
            run='\n'.join(s.get('run','') for s in steps)
            self.assertEqual(run.count('python scripts/evaluate_team_typesafe.py'),1)
            self.assertLess(run.index('evaluate_team_typesafe.py'),run.index('build_listing_gate.py'))
            receipt=next(s for s in steps if 'typesafe-budget-receipt-' in s.get('with',{}).get('name',''))
            self.assertEqual(receipt['if'],'always()')
            self.assertEqual(receipt['with']['retention-days'],21)
            self.assertEqual(receipt['with']['path'],'${{ env.TYPESAFE_SHARED_LEDGER_PATH }}')
        keys=('TYPESAFE_ORG_ID','TYPESAFE_BILLING_PROOF_JSON','TYPESAFE_BILLING_PROOF_PATH','TYPESAFE_SHARED_LEDGER_PATH','TYPESAFE_WORKFLOW_ID')
        for key in keys:self.assertEqual(envs[0][key],envs[1][key])

    def test_mandatory_tests_in_both_gates(self):
        for name in ('preflight.yml','pages-verified.yml'):
            text=(WF/name).read_text(encoding='utf-8')
            for suite in ('test_typesafe_shared.py','test_team_typesafe.py','test_typesafe_receipt.py','test_typesafe_wiring.py'):
                self.assertIn('python scripts/'+suite,text)

    def test_private_outputs_captured_not_derived(self):
        policy=json.loads((ROOT/'config/publish_policy.json').read_text(encoding='utf-8'))
        for name in ('data/typesafe_shared_state.json','data/typesafe_team_advisory.json'):
            self.assertIn(name,policy['generated_extra'])
            self.assertNotIn(name,policy['derived_paths'])
        publisher=(ROOT/'scripts/publish_transaction.py').read_text(encoding='utf-8')
        self.assertIn('data/typesafe_shared_state.json',publisher)
        self.assertIn('data/typesafe_team_advisory.json',publisher)
        self.assertIn('data/typesafe_shared_state.json.lock',(ROOT/'.gitignore').read_text(encoding='utf-8'))

    def test_receipt_failure_removes_proof_and_never_logs_secret(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'typesafe-billing-proof.json';target.write_text('stale')
            env={'RUNNER_TEMP':td,'TYPESAFE_BILLING_PROOF_PATH':str(target),'TYPESAFE_BILLING_PROOF_JSON':'{"fake":"dummy-secret-never-print"}','GITHUB_ACTIONS':'true'}
            with patch.dict(os.environ,env,clear=True),patch.object(bootstrap.subprocess,'run') as run,patch('builtins.print') as out:
                run.return_value.returncode=1
                self.assertEqual(bootstrap.main(),0)
                self.assertFalse(target.exists())
                self.assertNotIn('dummy-secret',str(out.call_args_list))
                self.assertEqual(run.call_count,1)

    def test_success_is_only_staging_not_key_authentication(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'typesafe-billing-proof.json'
            env={'RUNNER_TEMP':td,'TYPESAFE_BILLING_PROOF_PATH':str(target),'TYPESAFE_BILLING_PROOF_JSON':'{"operator_attestation":true}','GITHUB_ACTIONS':'true'}
            with patch.dict(os.environ,env,clear=True),patch.object(bootstrap.subprocess,'run') as run,patch('builtins.print'):
                run.return_value.returncode=0
                self.assertEqual(bootstrap.main(),0)
                self.assertTrue(target.exists())
                self.assertEqual(json.loads(target.read_text()),{'operator_attestation':True})

    def test_missing_invalid_duplicate_json_remove_stale(self):
        for raw in ('','[]','{"x":1,"x":2}','{"x":NaN}'):
            with self.subTest(raw=raw),tempfile.TemporaryDirectory() as td:
                target=Path(td)/'typesafe-billing-proof.json';target.write_text('stale')
                with patch.dict(os.environ,{'RUNNER_TEMP':td,'TYPESAFE_BILLING_PROOF_PATH':str(target),'TYPESAFE_BILLING_PROOF_JSON':raw},clear=True),patch('builtins.print'):
                    self.assertEqual(bootstrap.main(),0);self.assertFalse(target.exists())

    def test_dashboard_advisory_never_changes_gates(self):
        text=(ROOT/'scripts/generate_dashboard_runtime.py').read_text(encoding='utf-8')
        self.assertIn('card["jev_advisory"]',text)
        self.assertIn('secretary["jev_advisory"]',text)
        self.assertNotIn('typesafe_team_advisory.json',(ROOT/'scripts/build_listing_gate.py').read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main(verbosity=2)
