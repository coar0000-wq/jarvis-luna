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
    def test_watch_entity_events_batched_without_history_loss(self):
        from unittest.mock import patch
        state = runner.core.empty_state()
        events = [{'event_id':'watch_'+str(i).zfill(5), 'source_team':'sourcing',
                   'evidence':{'entity':str(i)}, 'kind':'ENTITY_CHANGED'} for i in range(307)]
        observed = {'state':{}, 'watchers':[], 'events':copy.deepcopy(events)}
        with patch.object(runner.recovery,'reconcile'):
            runner.apply_watch(state,observed,NOW.isoformat())
        self.assertEqual(len(state['tasks']),1)
        for event in events:
            self.assertEqual(state['events'][event['event_id']],event)
        batch = next(iter(state['event_batches'].values()))
        self.assertEqual(batch['event_ids'],sorted(e['event_id'] for e in events))
        key = next(iter(state['event_batches']))
        self.assertEqual(key,'event_batch_'+runner.core.digest(batch))
        self.assertEqual(next(iter(state['tasks'].values()))['payload']['source_event'],key)
        runner.validate_state(self.root,state)
        state['event_batches'][key]['event_ids'].pop()
        with self.assertRaisesRegex(ValueError,'batch/reference'):
            runner.validate_state(self.root,state)

    def test_watch_batches_rerun_and_single_event_keep_dedup(self):
        from unittest.mock import patch
        state = runner.core.empty_state()
        events = [{'event_id':'watch_'+str(i), 'source_team':'market',
                   'evidence':{'entity':str(i)}, 'kind':'ENTITY_CHANGED'} for i in range(2)]
        events.append({'event_id':'single','source_team':'legal','evidence':{},'kind':'ENTITY_CHANGED'})
        observed = {'state':{},'watchers':[],'events':events}
        with patch.object(runner.recovery,'reconcile'):
            runner.apply_watch(state,observed,NOW.isoformat())
            old = copy.deepcopy(state)
            runner.apply_watch(state,observed,NOW.isoformat())
        self.assertEqual(state,old)
        self.assertEqual(len(state['tasks']),2)
        self.assertTrue(any(t['payload']['source_event']=='single' for t in state['tasks'].values()))

    def test_state_serializer_compacts_only_layout(self):
        value = {'literal':'inside  whitespace\t\n 한글',
                 'history':[{'sequence':i,'evidence':{'x':i}} for i in range(137)]}
        runner.atomic(self.root,runner.STATE,value)
        raw = (self.root/runner.STATE).read_bytes()
        self.assertEqual(json.loads(raw),value)
        self.assertLess(len(raw),len(json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8')))
        self.assertEqual(raw,(json.dumps(value,ensure_ascii=False,sort_keys=True,
                         separators=(',',':'))+'\n').encode('utf-8'))

    def test_state_serializer_capacity_fails_without_mutation(self):
        self.put(runner.STATE,{'retained':'prior exact bytes'})
        before = (self.root/runner.STATE).read_bytes()
        with self.assertRaisesRegex(ValueError,'storage capacity'):
            runner.atomic(self.root,runner.STATE,{'oversized':'x'*(8*1024*1024)})
        self.assertEqual((self.root/runner.STATE).read_bytes(),before)

    def test_real_reports_existing_teams_and_handoff(self):
        board=runner.run(self.root,now=NOW)
        self.assertEqual(board['counts']['local_verified'],11)
        self.assertEqual(board['counts']['handoffs_accepted'],5)
        self.assertEqual(board['counts']['external_verified'],0)
        self.assertEqual({w['team'] for w in board['watchers']},set(runner.watch.SOURCE_MAPPINGS))
        self.assertEqual(len(board['watchers']),12)
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

    def test_explicit_goal_is_local_bounded_and_deduplicated(self):
        first = runner.run(self.root, now=NOW)
        before = self.load(runner.STATE)
        old_reports = {r['action']['target']:(self.root/r['action']['target']).read_bytes()
                       for r in before['receipts'].values()}
        second = runner.run(self.root, now=NOW, goal='Internal evidence and feedback review')
        after = self.load(runner.STATE)
        self.assertEqual(second['counts']['local_verified'], first['counts']['local_verified'] + 11)
        for table in ('tasks','handoffs','events','decisions','receipts'):
            for key, value in before[table].items():
                self.assertEqual(after[table][key], value)
        for target, raw in old_reports.items():
            self.assertEqual((self.root/target).read_bytes(), raw)
        ledger = (self.root/execution.ExecutionStore.filename).read_bytes()
        runner.run(self.root, now=NOW, goal='Internal evidence and feedback review')
        self.assertEqual(ledger, (self.root/execution.ExecutionStore.filename).read_bytes())
        self.assertTrue(all(t['kind'] == 'snapshot_report' for t in after['tasks'].values()))
        for goal in ('', ' ' * 3, 'x' * 501, 42):
            with self.assertRaises(ValueError): runner.run(self.root, now=NOW, goal=goal)

    def test_legacy_executing_missing_ledger_never_redispatches(self):
        from unittest.mock import patch
        runner.run(self.root, now=NOW, execute_local=False)
        state = self.load(runner.STATE)
        tid = next(t['task_id'] for t in state['tasks'].values()
                   if t.get('payload', {}).get('purpose') == 'saved_snapshot_review_only')
        for target in ('ROUTED','IN_PROGRESS','VERIFYING','EXECUTING'):
            runner.core.transition(state, tid, target)
        # Synthetic pre-audit state, never touching production history.
        for event in state['events'].values():
            event.pop('audit', None)
        state.pop('audit')
        self.put(runner.STATE, state)
        with patch.object(execution, 'execute') as dispatch:
            with self.assertRaises(ValueError): runner.run(self.root, now=NOW)
            dispatch.assert_not_called()
        final = self.load(runner.STATE)
        prep = next(iter(final['audit']['preparations'].values()))
        self.assertEqual(prep['observation'], 'restart_observation')
        self.assertIsNone(prep['decision_id'])
        self.assertEqual(final['tasks'][tid]['state'], 'BLOCKED')
        self.assertEqual(len(final['audit']['outcomes']), 1)
        for eid, event in state['events'].items():
            self.assertEqual(final['events'][eid], event)

if __name__=='__main__': unittest.main()
