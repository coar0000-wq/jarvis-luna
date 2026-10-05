"""Offline temporary-directory tests; never touch repo data or receipts."""
import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import source_procedure_state as s


class ProcedureStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = s.SourceProcedureStore(self.temp.name)
        self.store.fresh_init(trusted_caller=True)
        self.now = datetime(2026, 10, 3, tzinfo=timezone.utc)
        self.binding = {'source_team':'design','failure_fingerprint':'a'*64,'fixedprocedure_id':'design_source_observe'}

    def claim(self, invocation='one', hours=0, binding=None):
        return self.store.claim(binding or self.binding, invocation, now=self.now+timedelta(hours=hours))

    def finish(self, result, hours=0, **kwargs):
        return self.store.finish(result['claim']['claim_id'], exit_code=kwargs.pop('exit_code', 0), now=self.now+timedelta(hours=hours), **kwargs)

    def restart(self):
        checkpoint = self.store.checkpoint()
        self.store = s.SourceProcedureStore(self.store.directory)
        self.store.load(expected=checkpoint)

    def test_restart_cooldown_and_force(self):
        self.finish(self.claim())
        self.restart()
        for force in (False, True):
            self.assertIn('cooldown', self.store.plan(self.binding, 'two', now=self.now+timedelta(seconds=7199), force=force)['reasons'])
        self.assertTrue(self.claim('two', 2)['allowed'])

    def test_crash_after_claim_reconciliation_no_replay(self):
        result = self.claim(); self.restart()
        cid = result['claim']['claim_id']
        self.assertIn('reconciliation_required', self.claim('two', 3)['reasons'])
        with self.assertRaises(ValueError): self.store.finish(cid, exit_code=0, now=self.now)
        out = self.store.reconcile(cid, trusted_caller=True, now=self.now)
        self.assertEqual(out['status'], 'RECONCILED')
        self.assertFalse(out['outcome']['source_healthy'])
        self.assertEqual(self.store.public_projection()['teams']['design']['lifetime'], 1)
        with self.assertRaises(ValueError): self.store.reconcile(cid, trusted_caller=True, now=self.now)

    def test_missing_malformed_checkpoint_hash_regression(self):
        old = self.store.checkpoint()
        self.finish(self.claim())
        new = self.store.checkpoint()
        with self.assertRaises(ValueError): s.SourceProcedureStore(self.temp.name).load(expected=old)
        bad = copy.deepcopy(new); bad['table_hash'] = '0'*64
        with self.assertRaises(ValueError): s.SourceProcedureStore(self.temp.name).load(expected=bad)
        file = Path(self.temp.name)/self.store.filename
        file.unlink()
        with self.assertRaises(ValueError): s.SourceProcedureStore(self.temp.name).load(expected=new)
        file.write_text('{bad', encoding='utf-8')
        with self.assertRaises(ValueError): s.SourceProcedureStore(self.temp.name).load(expected=new)

    def test_fresh_is_explicit_existing_cannot_reset(self):
        with self.assertRaises(ValueError): self.store.fresh_init(trusted_caller=True)
        with tempfile.TemporaryDirectory() as tmp:
            store = s.SourceProcedureStore(tmp)
            with self.assertRaises(ValueError): store.fresh_init()
            with self.assertRaises(ValueError): store.plan(self.binding, 'one', now=self.now)
            with self.assertRaises(ValueError): store.load(expected=None)

    def test_ceilings_unchanged_failure_history_changed_episode(self):
        self.finish(self.claim())
        self.assertIn('invocation_limit', self.claim('one', 2)['reasons'])
        self.finish(self.claim('two', 2), 2)
        self.assertIn('episode_limit', self.claim('three', 4)['reasons'])
        changed = {**self.binding,'failure_fingerprint':'b'*64}
        self.finish(self.claim('three', 4, changed), 4)
        projection = self.store.public_projection()['teams']['design']
        self.assertEqual(projection['episodes'], 2)
        self.assertEqual(projection['lifetime'], 3)
        self.restart()
        self.assertEqual(self.store.public_projection()['teams']['design']['episodes'], 2)

    def test_stable_fingerprint_rejects_generated_time(self):
        failure = {'source_identity':'design_owned_feed','source_hash':None,'blocker_codes':['BLOCKED','MISSING']}
        self.assertEqual(s.failure_fingerprint(failure), s.failure_fingerprint({**failure,'blocker_codes':['MISSING','BLOCKED','MISSING']}))
        with self.assertRaises(ValueError): s.failure_fingerprint({**failure,'generated_at':self.now.isoformat()})
        self.assertNotEqual(s.failure_fingerprint(failure), s.failure_fingerprint({**failure,'source_hash':'f'*64}))

    def test_lock_loss_never_deletes_replacement(self):
        lock = Path(self.temp.name)/self.store.lockname
        original = self.store._write
        def sabotage(table, owned):
            lock.write_bytes(b'replacement')
            original(table, owned)
        before = self.store.checkpoint()
        self.store._write = sabotage
        try:
            with self.assertRaises(ValueError): self.claim()
        finally:
            self.store._write = original
        self.assertEqual(lock.read_bytes(), b'replacement')
        self.assertEqual(self.store.checkpoint(), before)
        with self.assertRaises(FileExistsError): self.claim()

    def test_stale_lock_denies_without_deletion(self):
        lock = Path(self.temp.name)/self.store.lockname
        lock.write_bytes(b'crashed-owner')
        with self.assertRaises(FileExistsError): self.claim()
        self.assertEqual(lock.read_bytes(), b'crashed-owner')

    def test_lifetime_budget_and_stop_persist(self):
        original_store = self.store
        with tempfile.TemporaryDirectory() as tmp:
            self.store = s.SourceProcedureStore(tmp)
            self.store.fresh_init(trusted_caller=True, lifetime_budget=1)
            self.finish(self.claim())
            self.restart()
            self.assertIn('lifetime_budget', self.claim('two', 3, {**self.binding,'failure_fingerprint':'b'*64})['reasons'])
        self.store = original_store
        cid = self.claim()['claim']['claim_id']
        self.store.reconcile(cid, trusted_caller=True, stop=True, now=self.now)
        self.restart()
        self.assertIn('lifetime_stop', self.claim('two', 3)['reasons'])

    def test_exit_zero_not_health_output_hash_and_actual_proof(self):
        self.assertFalse(self.finish(self.claim(), output=b'ok')['outcome']['source_healthy'])
        proof = {'source_team':'design','source_hash':'f'*64,'captured_at':self.now.isoformat(),'observed_at':(self.now+timedelta(hours=2)).isoformat(),'observation_kind':'actual_source_capture','required_scope_complete':True}
        result = self.claim('two', 2)
        with self.assertRaises(ValueError): self.finish(result, 2, output=b'actual', source_proof=proof)
        finished = self.finish(result, 2, output=b'actual', source_proof=proof, validator=lambda a,p,b: b == b'actual')
        o = finished['outcome']
        self.assertTrue(o['source_healthy'])
        self.assertEqual(o['output_sha256'], hashlib.sha256(b'actual').hexdigest())
        self.assertFalse(o['receipt_verified']); self.assertFalse(o['authority'])
        self.restart()

    def test_proof_generated_at_and_missing_capture_rejected(self):
        result = self.claim()
        proof = {'source_team':'design','source_hash':'f'*64,'captured_at':None,'observed_at':self.now.isoformat(),'observation_kind':'actual_source_capture','required_scope_complete':True}
        for p in (proof, {**proof,'generated_at':self.now.isoformat()}):
            with self.assertRaises(ValueError): self.finish(result, source_proof=p, validator=lambda *args:True)

    def test_strict_ids_config_and_fields(self):
        for proc in ('http://evil', 'os.system', 'run_command', 'dashboard_revalidate'):
            with self.assertRaises(ValueError): self.claim(binding={**self.binding,'fixedprocedure_id':proc})
        with self.assertRaises(ValueError): self.claim(binding={**self.binding,'command':'echo hi'})
        config = copy.deepcopy(s.DEFAULT_CONFIG); config['design'] = ['os.system']
        with self.assertRaises(ValueError): s.SourceProcedureStore(self.temp.name, config)
        self.assertEqual(set(s.DEFAULT_CONFIG), set(s.TEAMS))
        self.assertEqual(set(i for ids in s.DEFAULT_CONFIG.values() for i in ids), set(s.FIXED_IDS))
        self.assertFalse(self.store.public_projection()['authority'])

    def test_counter_history_and_hash_tampering_fail_closed(self):
        self.finish(self.claim())
        checkpoint = self.store.checkpoint()
        file = Path(self.temp.name)/self.store.filename
        table = json.loads(file.read_text())
        table['teams']['design']['lifetime'] = 0
        s._seal(table); file.write_text(s.canonical(table))
        with self.assertRaises(ValueError): s.SourceProcedureStore(self.temp.name).load(expected=checkpoint)

    def test_history_overflow_denies_without_pruning(self):
        for i in range(128):
            binding = {**self.binding,'failure_fingerprint':s.digest({'episode':i})}
            self.finish(self.claim('inv'+str(i), i*2, binding), i*2)
        self.assertEqual(self.store.public_projection()['teams']['design']['episodes'], 128)
        denied = self.claim('overflow', 256, {**self.binding,'failure_fingerprint':'c'*64})
        self.assertIn('history_overflow', denied['reasons'])
        self.restart()
        self.assertEqual(self.store.public_projection()['teams']['design']['lifetime'], 128)


if __name__ == '__main__':
    unittest.main()
