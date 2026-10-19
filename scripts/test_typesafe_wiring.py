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
            self.assertNotIn('TYPESAFE_BILLING_PROOF_PATH',env)
            self.assertNotIn('runner.',str(env))
            self.assertEqual(bootstrap_step['env']['TYPESAFE_BILLING_PROOF_PATH'],'${{ runner.temp }}/typesafe-billing-proof.json')
            self.assertIn('GITHUB_ENV',bootstrap_step['run'])
            self.assertLess(bootstrap_step['run'].index('GITHUB_ENV'),bootstrap_step['run'].index('setup_typesafe_shared.py'))
            run='\n'.join(s.get('run','') for s in steps)
            self.assertEqual(run.count('python scripts/evaluate_team_typesafe.py'),1)
            self.assertLess(run.index('evaluate_team_typesafe.py'),run.index('build_listing_gate.py'))
            receipt=next(s for s in steps if 'typesafe-budget-receipt-' in s.get('with',{}).get('name',''))
            self.assertEqual(receipt['if'],'always()')
            self.assertEqual(receipt['with']['retention-days'],21)
            self.assertEqual(receipt['with']['path'],'${{ env.TYPESAFE_SHARED_LEDGER_PATH }}')
        keys=('TYPESAFE_ORG_ID','TYPESAFE_BILLING_PROOF_JSON','TYPESAFE_SHARED_LEDGER_PATH','TYPESAFE_WORKFLOW_ID')
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

    def test_jev_114_text_pin_and_new_ledger_binding(self):
        import typesafe_decision_support as listing
        import evaluate_team_typesafe as team
        self.assertEqual(team.MODEL, 'jev-1.14.0')
        self.assertEqual(listing.MODEL, 'jev-1.14.0')
        self.assertEqual(team.MODEL_POLICY_VERSION, 'jarvis-jev-1.14-text-v1')
        for name in ('JARVIS-Deep-Analysis.yml', 'shopify-listing-copy.yml'):
            doc = yaml.safe_load((WF/name).read_text(encoding='utf-8'))
            env = next(iter(doc['jobs'].values()))['env']
            self.assertEqual(env['TYPESAFE_MODEL'], team.MODEL)
            self.assertEqual(env['TYPESAFE_MODEL_POLICY_VERSION'], team.MODEL_POLICY_VERSION)
        captured = {}
        def adapter(payload, **kwargs):
            captured.update(payload)
            return {'source': 'deterministic_local', 'mode': 'offline_test'}
        with patch.dict(os.environ, {}, clear=True), patch.object(listing, 'evaluate_typed', adapter):
            listing.evaluate({'name': '한국어 확인: 근거가 없으면 사람 검토', 'public_blocked_by': ['legal']})
        self.assertEqual(captured['model'], team.MODEL)
        self.assertEqual(captured['model_policy_version'], team.MODEL_POLICY_VERSION)
        self.assertEqual(set(q['type'] for q in captured['questions'].values()), {'choice', 'score'})

    def test_jev_114_transport_has_no_experimental_opt_ins(self):
        import typesafe_decision_support as listing
        import typesafe_shared as shared
        from unittest.mock import MagicMock
        p = {'model': 'jev-1.14.0', 'state': {'text': '근거 없음: 보류'},
             'question_version': 'offline-korean-v1', 'model_policy_version': 'jarvis-jev-1.14-text-v1',
             'questions': {'present': {'type': 'noul', 'instructions': '근거가 있는가?'}}}
        valid = {'model': 'jev-1.14.0', 'usage': {'input_tokens': 5, 'output_tokens': 1},
                 'answers': {'present': {'noul': 0.0}}}
        shared.validate_response(valid, p)
        with self.assertRaisesRegex(shared.SafetyStop, 'response_model_mismatch'):
            shared.validate_response({**valid, 'model': 'jev-1.13.0'}, p)
        with self.assertRaisesRegex(shared.SafetyStop, 'unsupported_type'):
            shared.validate_payload({**p, 'questions': {'box': {'type': 'box', 'instructions': 'Find'}}})
        with self.assertRaisesRegex(shared.SafetyStop, 'invalid_payload_contract'):
            shared.validate_payload({**p, 'assets': {'image': 'https://example.invalid/image'}})
        reply = MagicMock(); reply.read.return_value = json.dumps(valid).encode(); reply.status = 200
        reply.headers = {}; reply.__enter__.return_value = reply
        with patch.object(listing.urllib.request, 'urlopen', return_value=reply) as call:
            listing._request({k:v for k,v in p.items() if k not in {'question_version','model_policy_version'}}, 'offline-dummy')
        request = call.call_args.args[0]
        self.assertFalse(any('danger-zone' in k.lower() for k in request.headers))
        self.assertEqual(json.loads(request.data)['state']['text'], '근거 없음: 보류')
        self.assertNotIn('assets', json.loads(request.data))

    def test_jev_release_shared_with_all_existing_roles_without_runtime_claim(self):
        import evaluate_team_typesafe as team
        import build_team_learning as learning
        doc = json.loads((ROOT/'data/manual/team_youtube_insights.json').read_text())
        item = next(x for x in doc['insights'] if x['id'] == 'JEV-20261019-114-TEXT')
        self.assertEqual(set(item['teams']), set(team.TEAMS))
        self.assertEqual(item['runtime_status'], 'not_called_for_this_update')
        self.assertFalse(item['evidence']['mapping_verified'])
        self.assertIsNone(item['evidence']['timestamp'])
        for role in team.TEAMS:
            self.assertIn(role, learning.brief(item, {})['teams'])
        briefings = json.loads((ROOT/'data/manual/team_briefings.json').read_text())
        entry = next(x for x in briefings['items'] if x['id'] == '2026-10-19-jev-1-14-text-upgrade')
        self.assertEqual(set(entry['team_actions']), set(team.TEAMS))

if __name__=='__main__':unittest.main(verbosity=2)
