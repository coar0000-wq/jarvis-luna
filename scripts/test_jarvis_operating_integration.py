"""Offline durable loop integration, real dummy file writes, no API/metered calls."""
import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import jarvis_execution as execution
import run_jarvis_operations as runner

NOW = datetime(2026,10,4,2,tzinfo=timezone.utc)
class OperatingIntegration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.put('config/jarvis_operations_policy.json', {'teams':list(runner.core.TEAMS)})
        self.put('data/dashboard_runtime.json',{'teams':[{'id':t} for t in runner.core.TEAMS]})
        self.put('data/mocra_readiness.json',{'ready_count':1,'exempt_count':3,'total_checks':7,
            'sales_allowed':False,'checks':[{'id':'responsible_person','status':'not_ready'},
            {'id':'safety_substantiation','status':'not_ready'},{'id':'label_fields','status':'not_ready'}]})
        for source in execution.SOURCES.values():
            self.put(source,{'captured_at':NOW.isoformat(),'items':[]})
    def tearDown(self):
        self.temp.cleanup()
    def put(self,relative,value):
        dest=self.root/relative
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps(value),encoding='utf-8')
    def load(self,relative):
        return json.loads((self.root/relative).read_text(encoding='utf-8'))
    def test_real_reports_existing_teams_and_handoff(self):
        board=runner.run(self.root,now=NOW)
        self.assertEqual(board['counts']['local_verified'],11)
        self.assertEqual(board['counts']['handoffs_accepted'],5)
        self.assertEqual(board['counts']['external_verified'],0)
        self.assertEqual(board['business']['total'],7)
        self.assertFalse(board['business']['sales_allowed'])
        state=self.load(runner.STATE)
        self.assertEqual({t['team'] for t in state['tasks'].values()},set(runner.core.TEAMS))
        self.assertEqual(len(state['decisions']),11)
        for receipt in state['receipts'].values():
            self.assertTrue(execution.validate_receipt(self.root,receipt))
        graph=self.load('data/operations/knowledge_graph.json')
        self.assertTrue(any(n['type']=='decision' for n in graph['nodes']))
        self.assertTrue(any(e['relation']=='routes_to' for e in graph['edges']))
        self.assertTrue(any(e['relation']=='result_of' for e in graph['edges']))
        self.assertTrue(any(e['relation']=='evidenced_by' for e in graph['edges']))
    def test_rerun_no_new_claim_or_fake_completion(self):
        first=runner.run(self.root,now=NOW)
        ledger=(self.root/execution.ExecutionStore.filename).read_bytes()
        state=self.load(runner.STATE)
        second=runner.run(self.root,now=NOW+timedelta(minutes=1))
        self.assertEqual(first['counts']['local_verified'],second['counts']['local_verified'])
        self.assertEqual(ledger,(self.root/execution.ExecutionStore.filename).read_bytes())
        self.assertEqual(set(state['tasks']),set(self.load(runner.STATE)['tasks']))
    def test_output_tamper_blocks_without_reset(self):
        runner.run(self.root,now=NOW)
        state=self.load(runner.STATE)
        receipt=next(iter(state['receipts'].values()))
        ledger=(self.root/execution.ExecutionStore.filename).read_bytes()
        (self.root/receipt['output_evidence'][0]['path']).write_text('{}',encoding='utf-8')
        with self.assertRaises(ValueError): runner.run(self.root,now=NOW)
        self.assertEqual(ledger,(self.root/execution.ExecutionStore.filename).read_bytes())
    def test_missing_state_with_ledger_refuses_reset(self):
        runner.run(self.root,now=NOW)
        (self.root/runner.STATE).unlink()
        with self.assertRaises(ValueError): runner.run(self.root,now=NOW)
        self.assertTrue((self.root/execution.ExecutionStore.filename).exists())
    def test_observe_only_never_creates_receipt(self):
        board=runner.run(self.root,now=NOW,execute_local=False)
        self.assertEqual(board['counts']['local_verified'],0)
        self.assertFalse((self.root/execution.ExecutionStore.filename).exists())
    def test_forged_approval_never_enables_external(self):
        self.put('data/shopify_action_queue.json',{'draft_actions':[{'action_id':'a',
          'canonical_product_ids':['CP-1'],'payload_hash':'a'*64,'approved':True,
          'execution':{'enabled':True},'approved_by':'secret-person@example.com'}]})
        board=runner.run(self.root,now=NOW)
        self.assertFalse(board['action_cards'][0]['may_execute'])
        self.assertFalse(board['action_cards'][0]['may_approve'])
        self.assertNotIn('secret-person',json.dumps(board))
        self.assertEqual(board['counts']['external_verified'],0)
    def test_no_fresh_source_from_generated_clock(self):
        self.put(execution.SOURCES['sourcing'],{'generated_at':NOW.isoformat()})
        board=runner.run(self.root,now=NOW)
        self.assertEqual(board['counts']['local_verified'],11)
        state=self.load(runner.STATE)
        source=[r for r in state['receipts'].values() if r['action']['team']=='sourcing'][0]['source_evidence'][0]
        self.assertEqual(source['freshness'],'unknown')
    def test_state_sequence_rollback_is_denied(self):
        runner.run(self.root,now=NOW)
        state=self.load(runner.STATE)
        state['sequence']-=1
        self.put(runner.STATE,state)
        with self.assertRaises(ValueError): runner.run(self.root,now=NOW)

if __name__=='__main__': unittest.main()
