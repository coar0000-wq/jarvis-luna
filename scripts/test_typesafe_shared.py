"""Offline only: dummy key, mocked transport, isolated temporary ledgers."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import typesafe_shared as t


def payload(state=0):
    return {'state':{'x':state},'model':'jev-latest','question_version':'q1','model_policy_version':'m1',
            'questions':{'route':{'type':'choice','instructions':'Route','criteria':{'a':'A','b':'B'}},
                         'risk':{'type':'score','instructions':'Risk','criteria':['low','high']},
                         'yes':{'type':'noul','instructions':'Yes?'}}}

def response(p=None,k=None):
    return {'model':'jev-test-revision','usage':{'input_tokens':10,'output_tokens':3},
            'answers':{'route':{'choice':'a','confidence':.9},'risk':{'score':1,'confidence':.8},'yes':{'type':'noul','noul':.99}}}

class SharedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.path=self.root/'ledger.json'; self.proofpath=self.root/'proof.json'
        now=datetime.now(timezone.utc)
        self.proof={'key_sha256':hashlib.sha256(b'dummy-offline').hexdigest(),'org_id':'dummy-org',
                    'available_free_usd':5,'auto_recharge':False,'payment_method_on_file':False,
                    'verified_at':now.isoformat(),'expires_at':(now+timedelta(hours=1)).isoformat()}
        self.saveproof()
        env={k:v for k,v in os.environ.items() if not k.startswith('TYPESAFE_')}
        env.update(TYPESAFE_ENABLED='1',TYPESAFE_FREE_CREDITS_ONLY='1',TYPESAFE_API_KEY='dummy-offline',
                   TYPESAFE_ORG_ID='dummy-org',TYPESAFE_BILLING_PROOF_PATH=str(self.proofpath),
                   TYPESAFE_SHARED_LEDGER_PATH=str(self.path),PYTHONDONTWRITEBYTECODE='1')
        self.patch=patch.dict(os.environ,env,clear=True); self.patch.start(); self.addCleanup(self.patch.stop)
        self.calls=0
    def saveproof(self):
        self.proofpath.write_text(json.dumps(self.proof),encoding='utf-8')
    def request(self,p,k):
        self.calls+=1
        return response(p,k)
    def runone(self,p=None,fn=None):
        return t.evaluate_typed(payload() if p is None else p,request_fn=fn or self.request)
    def test_success_cache_and_timestamp(self):
        self.assertEqual(self.runone()['source'],'typesafe')
        p=payload(); p['state']['observed_at']='new observation'
        self.assertEqual(self.runone(p)['source'],'typesafe_cache')
        self.assertEqual(self.calls,1); self.assertEqual(t.ledger()['calls'],1)
        self.assertGreater(t.ledger()['charged_input_tokens'],2048)
    def test_state_questions_model_invalidate(self):
        first=self.runone(); self.assertEqual(first['source'],'typesafe',first)
        changed=self.runone(payload(1)); self.assertEqual(changed['source'],'typesafe',changed)
        p=payload(); p['questions']['route']['instructions']='Different'
        self.assertEqual(self.runone(p)['mode'],'immutable_version_changed')
        p['question_version']='q2'; revised=self.runone(p)
        self.assertEqual(revised['source'],'typesafe',revised)
        p['model']='jev-preview'; p['model_policy_version']='m2'
        model_changed=self.runone(p)
        self.assertEqual(model_changed['source'],'typesafe',model_changed); self.assertEqual(self.calls,4)
    def test_cache_expiry(self):
        self.runone(); s=json.loads(self.path.read_text()); next(iter(s['cache'].values()))['created_at']-=90000
        self.path.write_text(json.dumps(s)); self.runone(); self.assertEqual(self.calls,2)
    def test_pre_request_budget(self):
        os.environ['TYPESAFE_MAX_INPUT_TOKENS']='2048'
        self.assertEqual(self.runone()['mode'],'pre_request_budget_denied'); self.assertEqual(self.calls,0)
        self.assertTrue(t.ledger()['stopped'])
    def test_account_allowance(self):
        self.proof['available_free_usd']=.000001; self.saveproof()
        self.assertEqual(self.runone()['mode'],'account_budget_denied'); self.assertEqual(self.calls,0)
        os.environ['TYPESAFE_WORKFLOW_ID']='next-publishing-run'
        self.assertTrue(self.runone()['mode'].startswith('shared_stopped:'))
    def test_proof_fail_closed(self):
        for key,val in [('key_sha256','wrong'),('org_id','wrong'),('auto_recharge',True),('payment_method_on_file',True),
                        ('available_free_usd',float('nan')),('expires_at','2000-01-01T00:00:00Z')]:
            with self.subTest(key=key):
                old=self.proof[key]; self.proof[key]=val; self.saveproof()
                self.assertEqual(self.runone()['source'],'unavailable'); self.assertEqual(self.calls,0)
                self.proof[key]=old
        self.proofpath.unlink(); self.assertEqual(self.runone()['mode'],'proof_missing_or_invalid')
    def test_free_only_paid_override(self):
        os.environ['TYPESAFE_ALLOW_PAID']='1'; self.assertEqual(self.runone()['mode'],'paid_override_rejected')
        del os.environ['TYPESAFE_ALLOW_PAID']; del os.environ['TYPESAFE_FREE_CREDITS_ONLY']
        self.assertEqual(self.runone()['mode'],'free_only_required'); self.assertEqual(self.calls,0)
    def test_ambiguous_stop_propagation(self):
        def fail(p,k):
            raise TimeoutError('dummy only')
        self.assertEqual(self.runone(fn=fail)['mode'],'request_or_protocol_failure')
        self.assertTrue(self.runone(payload(1))['mode'].startswith('shared_stopped:'))
        self.assertEqual(self.calls,0); self.assertEqual(t.ledger()['calls'],1)
        self.assertGreater(t.ledger()['charged_input_tokens'],2048)
        os.environ['TYPESAFE_WORKFLOW_ID']='different-run'
        self.assertTrue(self.runone(payload(2))['mode'].startswith('shared_stopped:'))
        self.assertEqual(self.calls,0)
    def test_success_persistence_failure_keeps_charge_and_global_stop(self):
        original=t.write
        failed=False
        def fail_success_once(path,state):
            nonlocal failed
            if state.get('cache') and not failed:
                failed=True
                raise PermissionError(13,'injected offline persistence denial')
            return original(path,state)
        with patch.object(t,'write',side_effect=fail_success_once):
            result=self.runone()
        self.assertTrue(failed)
        self.assertEqual(result['mode'],'request_or_protocol_failure',result)
        charged=t.ledger()['charged_input_tokens']
        self.assertGreater(charged,2048)
        self.assertEqual(t.ledger()['calls'],1)
        self.assertEqual(t.ledger()['global_stopped'],'request_or_protocol_failure')
        stopped=self.runone(payload(1))
        self.assertEqual(stopped['mode'],'shared_stopped:request_or_protocol_failure',stopped)
        self.assertEqual(self.calls,1)
        self.assertEqual(t.ledger()['charged_input_tokens'],charged)

    def test_all_http_and_protocol_failures(self):
        mutations=[lambda b:b.update(_http={'status':500}),lambda b:b.update(error='bad'),
                   lambda b:b['answers']['route'].update(choice='invalid'),
                   lambda b:b['answers']['risk'].update(score=2),
                   lambda b:b['answers']['yes'].update(noul=-1),
                   lambda b:b['answers']['route'].update(confidence=float('nan')),
                   lambda b:b['usage'].update(input_tokens=-1),lambda b:b['usage'].update(output_tokens=float('inf')),
                   lambda b:b['answers'].pop('yes'),lambda b:b.update(model='jev-latest')]
        for i,mutate in enumerate(mutations):
            with self.subTest(i=i):
                os.environ['TYPESAFE_SHARED_LEDGER_PATH']=str(self.root/f'bad{i}.json')
                b=response(); mutate(b)
                self.assertEqual(self.runone(fn=lambda p,k:b)['source'],'unavailable')
                self.assertTrue(t.ledger()['stopped']); self.assertEqual(t.ledger()['calls'],1)
    def test_official_typed_noul_response(self):
        b=response()
        b['answers']['route']['type']='choice'
        b['answers']['risk']['type']='score'
        self.assertEqual(b['answers']['yes'],{'type':'noul','noul':.99})
        self.assertNotIn('confidence',b['answers']['yes'])
        r=self.runone(fn=lambda p,k:b)
        self.assertEqual(r['source'],'typesafe')
        self.assertEqual(r['answers']['yes']['noul'],.99)
    def test_guessed_probability_and_mismatched_answer_types_rejected(self):
        cases=[('yes',{'probability':.99}),
               ('yes',{'type':'choice','noul':.99}),
               ('route',{'type':'score','choice':'a','confidence':.9}),
               ('risk',{'type':'noul','score':1,'confidence':.9}),
               ('yes',{'type':'noul','noul':True}),
               ('yes',{'type':'noul','noul':float('nan')}),
               ('yes',{'type':'noul','noul':1.01})]
        for i,(key,row) in enumerate(cases):
            with self.subTest(i=i):
                os.environ['TYPESAFE_SHARED_LEDGER_PATH']=str(self.root/f'typed{i}.json')
                b=response(); b['answers'][key]=row
                self.assertEqual(self.runone(fn=lambda p,k:b)['source'],'unavailable')
                self.assertTrue(t.ledger()['global_stopped'])
    def test_reported_overshoot_charged(self):
        b=response(); b['usage']['input_tokens']=90000
        self.assertEqual(self.runone(fn=lambda p,k:b)['mode'],'reported_usage_overshoot')
        self.assertEqual(t.ledger()['charged_input_tokens'],90000)
    def test_fallback_and_disabled_wrapper(self):
        os.environ['TYPESAFE_ENABLED']='0'
        r=t.evaluate_typed(payload(),response()['answers'],request_fn=self.request)
        self.assertEqual(r['source'],'deterministic_local'); self.assertFalse(r['enforced'])
        import typesafe_decision_support as wrapper
        self.assertEqual(wrapper.evaluate({'grade':'S','shopify_score':90})['source'],'deterministic_local')
    def test_corrupt_ledger_no_dispatch(self):
        self.path.write_text('{}'); self.assertEqual(self.runone()['mode'],'ledger_corrupt'); self.assertEqual(self.calls,0)
    def child(self,state,fail=False):
        code="import sys; sys.path.insert(0,sys.argv[1]); from test_typesafe_shared import payload,response; import typesafe_shared as t; import json; print(json.dumps(t.evaluate_typed(payload(int(sys.argv[2])), request_fn=response)))"
        return subprocess.Popen([sys.executable,'-B','-c',code,str(Path(__file__).parent),str(state)],env=dict(os.environ),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    def test_concurrent_subprocess_reservations(self):
        os.environ['TYPESAFE_MAX_CALLS']='2'
        procs=[self.child(i) for i in range(5)]
        rows=[]
        for proc in procs:
            out,err=proc.communicate(timeout=30); self.assertEqual(proc.returncode,0,err); rows.append(json.loads(out))
        self.assertEqual(sum(r['source']=='typesafe' for r in rows),2)
        self.assertEqual(t.ledger()['calls'],2); self.assertTrue(t.ledger()['stopped'])
    def test_workflow_budget_exhaustion_does_not_poison_next_run(self):
        os.environ['TYPESAFE_MAX_CALLS']='1'
        os.environ['TYPESAFE_WORKFLOW_ID']='publishing-run-1'
        first=payload(); first['state']['team']='legal'
        first_result=self.runone(first)
        self.assertEqual(first_result['source'],'typesafe',first_result)
        cost=t.ledger()['account_estimated_cost_usd']
        # Another team is still the same run: never a per-team budget reset.
        second=payload(); second['state']['team']='marketing'
        self.assertEqual(self.runone(second)['mode'],'pre_request_budget_denied')
        self.assertEqual(t.ledger()['global_stopped'],'')
        self.assertEqual(t.ledger()['workflow_stopped'],'pre_request_budget_denied')
        self.assertTrue(self.runone(second)['mode'].startswith('workflow_stopped:'))
        os.environ['TYPESAFE_WORKFLOW_ID']='publishing-run-2'
        next_run=self.runone(second)
        self.assertEqual(next_run['source'],'typesafe',next_run)
        self.assertGreater(t.ledger()['account_estimated_cost_usd'],cost)
        self.assertEqual(t.ledger()['calls'],1)
        os.environ['TYPESAFE_WORKFLOW_ID']='publishing-run-1'
        self.assertTrue(self.runone(payload(42))['mode'].startswith('workflow_stopped:'))
    def test_sequential_process_cache_shared(self):
        for _ in range(2):
            proc=self.child(0); out,err=proc.communicate(timeout=30); self.assertEqual(proc.returncode,0,err)
        self.assertEqual(json.loads(out)['source'],'typesafe_cache'); self.assertEqual(t.ledger()['calls'],1)

if __name__=='__main__':
    unittest.main()
