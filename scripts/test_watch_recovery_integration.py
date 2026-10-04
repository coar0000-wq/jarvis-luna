"""Actual locked operating loop and authoritative receipt boundary, offline fixtures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import jarvis_operations as core
import jarvis_execution as execution
import jarvis_watch as watch
import jarvis_recovery as recovery
import run_jarvis_operations as runner

NOW = '2026-10-04T07:10:00+00:00'
LATER = '2026-10-04T07:11:00+00:00'


class RecoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.put('data/google_trends_beauty.json', {'status':'failed','items':[]})
        state = core.empty_state()
        initial = watch.observe(self.root, now=NOW)
        state['watch'] = initial['state']
        recovery.reconcile(state, initial['watchers'], now=NOW)
        runner.atomic(self.root, runner.STATE, state)

    def put(self, relative, value):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value), encoding='utf-8')

    def market(self):
        self.put('data/google_trends_beauty.json', {'status':'ok','collected_at':NOW,
                 'items':[{'url':'https://example.test/a','keyword':'fixture','beauty':True}]})

    def state(self):
        return runner.read(self.root,runner.STATE)

    def episode(self, state):
        return next(e for e in state['source_recovery']['episodes'].values() if e['source_team']=='market')

    def test_real_recovery_receipt_completion_and_restart(self):
        self.market()
        board = runner.run(self.root,now=LATER)
        state = self.state()
        episode = self.episode(state)
        self.assertEqual(episode['status'],'RECOVERED')
        task = state['tasks'][episode['task_id']]
        self.assertEqual(task['state'],'COMPLETED')
        receipt = state['receipts'][episode['receipt_id']]
        self.assertTrue(execution.validate_receipt(self.root,receipt))
        self.assertEqual(receipt['source_recovery_evidence']['source_team'],'market')
        self.assertEqual(receipt['source_recovery_evidence']['captured_at'],NOW)
        self.assertEqual(board['counts']['external_verified'],0)
        self.assertFalse(board['business']['sales_allowed'])
        before = copy.deepcopy(state['source_recovery'])
        second = runner.run(self.root,now=LATER)
        self.assertEqual(before,self.state()['source_recovery'])
        self.assertEqual(second['counts']['source_recoveries_verified'],1)

    def test_source_fails_after_report_cannot_complete_recovery(self):
        self.market()
        actual_execute = execution.execute
        def race(root, task, *args, **kwargs):
            receipt = actual_execute(root,task,*args,**kwargs)
            if task.get('payload',{}).get('watcher_team') == 'market':
                self.put('data/google_trends_beauty.json', {'status':'failed','collected_at':NOW,
                         'items':[{'url':'https://example.test/a','beauty':True}]})
            return receipt
        with patch.object(execution,'execute',side_effect=race):
            board = runner.run(self.root,now=LATER)
        state = self.state()
        episode = self.episode(state)
        self.assertEqual(episode['status'],'ESCALATED')
        self.assertEqual(episode['attempts'],1)
        self.assertEqual(state['tasks'][episode['task_id']]['state'],'BLOCKED')
        self.assertIsNone(episode['receipt_id'])
        self.assertEqual(next(w for w in board['watchers'] if w['team']=='market')['status'],'BLOCKED')
        runner.validate_state(self.root,state)
        self.market()
        runner.run(self.root,now=LATER)
        self.assertEqual(self.episode(self.state())['status'],'ESCALATED')

    def test_report_proof_tamper_is_not_trusted(self):
        self.market()
        runner.run(self.root,now=LATER)
        state = self.state()
        e = self.episode(state)
        receipt = copy.deepcopy(state['receipts'][e['receipt_id']])
        receipt['source_recovery_evidence']['source_hash'] = 'f'*64
        self.assertFalse(execution.validate_receipt(self.root,receipt))

    def test_observe_only_assigns_without_fake_attempts_or_recovery(self):
        self.market()
        board = runner.run(self.root,now=LATER,execute_local=False)
        e = self.episode(self.state())
        self.assertEqual(e['status'],'READY_LOCAL_VERIFICATION')
        self.assertEqual(e['attempts'],0)
        self.assertIsNone(e['receipt_id'])
        self.assertEqual(board['counts']['source_recoveries_verified'],0)


if __name__ == '__main__':
    unittest.main()
