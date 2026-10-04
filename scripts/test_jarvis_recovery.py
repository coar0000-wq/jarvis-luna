"""Offline recovery invariants. No real collectors/network/private artifacts."""
import copy
import json
import unittest
from unittest.mock import patch
import jarvis_operations as core
import jarvis_recovery as recovery

T0 = '2026-10-01T00:00:00+00:00'
T1 = '2026-10-01T00:01:00+00:00'
T2 = '2026-10-01T00:02:00+00:00'
T3 = '2026-10-01T00:03:00+00:00'


def watch(team='market', status='BLOCKED', stamp=T1, source=None):
    return {'source_team': team, 'source': source or recovery.SOURCES[team], 'status': status,
            'blockers': ['STALE_SOURCE_CAPTURE'] if status == 'BLOCKED' else [],
            'source_hash': 'a' * 64, 'captured_at': stamp, 'observed_at': stamp,
            'observation_kind': 'external_capture', 'coverage': {'complete': status != 'PARTIAL'}}


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        original_utc = core.utc
        clock = patch.object(core, 'utc', side_effect=lambda value=None: original_utc(T2 if value is None else value))
        clock.start()
        self.addCleanup(clock.stop)
        self.state = core.empty_state()
        recovery.reconcile(self.state, [watch()], now=T0)
        self.rid = next(iter(self.state['source_recovery']['episodes']))
        self.tid = self.episode()['task_id']

    def episode(self):
        return self.state['source_recovery']['episodes'][self.rid]

    def route(self, watcher=None):
        recovery.reconcile(self.state, [watcher or watch(status='BASELINE')], now=T1)

    def receipt(self, watcher=None, rid='receipt-actual-1', bound=True):
        task = self.state['tasks'][self.tid]
        result = {'receipt_id': rid, 'task_id': self.tid, 'kind': 'snapshot_report',
                  'payload_hash': task['payload_hash'], 'level': 2, 'status': 'VERIFIED',
                  'issuer': 'jarvis-execution-v1', 'root_owned': True, 'output_verified': True,
                  'action_hash': 'b' * 64, 'idempotency_key': rid,
                  'started_at': T0, 'ended_at': T2,
                  'output_evidence': [{'path': 'data/operations/reports/test.json',
                                       'sha256': 'c' * 64, 'captured_at': T2}]}
        if bound:
            w = watcher or watch(status='BASELINE')
            result['source_recovery_evidence'] = {'recovery_id': self.rid,
                **{k: w.get(k) for k in ('source_team', 'source', 'status', 'source_hash',
                                        'captured_at', 'observed_at', 'observation_kind', 'coverage')}}
        self.state['receipts'][rid] = copy.deepcopy(result)
        return result

    def complete(self, receipt):
        for status in ('IN_PROGRESS', 'VERIFYING'):
            core.transition(self.state, self.tid, status)
        core.transition(self.state, self.tid, 'COMPLETED', receipt=receipt)

    def test_dedup_immutable_payload_evidence(self):
        task = copy.deepcopy(self.state['tasks'][self.tid])
        w = watch(); w['blockers'] = ['SOURCE_CAPTURE_MISSING']; w['private'] = 'private@example.com'
        recovery.reconcile(self.state, [w], now=T1)
        self.assertEqual(len(self.state['tasks']), 1)
        self.assertEqual(self.episode()['episode'], 1)
        self.assertEqual(task['payload'], self.state['tasks'][self.tid]['payload'])
        self.assertEqual(task['evidence'], self.state['tasks'][self.tid]['evidence'])
        self.assertEqual(self.episode()['attempts'], 0)

    def test_blocked_never_completed_or_ready(self):
        self.assertEqual(core.ready_tasks(self.state), [])
        receipt = self.receipt()
        with self.assertRaises(ValueError):
            core.transition(self.state, self.tid, 'COMPLETED', receipt=receipt)
        with self.assertRaises(ValueError):
            recovery.verify_completed(self.state, self.rid, receipt, watch(status='BASELINE'))
        with self.assertRaises(ValueError):
            recovery.record_attempt(self.state, self.rid, receipt)
        self.assertEqual(self.episode()['attempts'], 0)

    def test_all_healthy_statuses_route_existing(self):
        for status in recovery.HEALTHY:
            state = copy.deepcopy(self.state)
            w = watch(status=status)
            recovery.reconcile(state, [w], now=T1)
            self.assertEqual(state['tasks'][self.tid]['state'], 'ROUTED')
            self.assertEqual(len(state['tasks']), 1)

    def test_completion_bound_and_replay_dedup(self):
        w = watch(status='BASELINE'); self.route(w)
        receipt = self.receipt(w); self.complete(receipt)
        recovery.verify_completed(self.state, self.rid, receipt, w)
        self.assertEqual(self.episode()['status'], 'RECOVERED')
        self.assertEqual(self.episode()['receipt_id'], receipt['receipt_id'])
        recovery.verify_completed(self.state, self.rid, receipt, w)
        self.assertEqual(self.episode()['attempts'], 1)

    def test_completed_diagnostic_not_source_recovery(self):
        self.route(); receipt = self.receipt(bound=False); self.complete(receipt)
        recovery.verify_completed(self.state, self.rid, receipt, watch(status='BASELINE'))
        self.assertEqual(self.episode()['status'], 'WAITING_SOURCE_RECOVERY')
        self.assertIsNone(self.episode()['receipt_id'])
        self.assertEqual(self.episode()['attempts'], 1)

    def test_wrong_current_hash_and_partial_not_success(self):
        self.route(); receipt = self.receipt(); self.complete(receipt)
        w = watch(status='BASELINE'); w['source_hash'] = 'd' * 64
        recovery.verify_completed(self.state, self.rid, receipt, w)
        self.assertNotEqual(self.episode()['status'], 'RECOVERED')
        recovery.verify_completed(self.state, self.rid, receipt, watch(status='PARTIAL'))
        self.assertEqual(self.episode()['attempts'], 1)
        self.assertEqual(self.episode()['status'], 'WAITING_SOURCE_RECOVERY')

    def test_stale_or_missing_evidence_not_routed(self):
        for change in ({'observed_at': None}, {'source_hash': 'fake'}, {'captured_at': '2020-01-01T00:00:00Z'},
                       {'observed_at': T0}, {'required_scope_complete': False}):
            state = copy.deepcopy(self.state)
            w = watch(status='BASELINE'); w.update(change)
            recovery.reconcile(state, [w], now=T1)
            self.assertEqual(state['tasks'][self.tid]['state'], 'BLOCKED')

    def test_restart_continuity(self):
        self.state = json.loads(json.dumps(self.state))
        recovery.reconcile(self.state, [watch()], now=T1)
        self.assertEqual(len(self.state['tasks']), 1)
        self.assertEqual(self.episode()['task_id'], self.tid)

    def test_regression_new_episode_no_reopen(self):
        self.route(); receipt = self.receipt(); self.complete(receipt)
        recovery.verify_completed(self.state, self.rid, receipt, watch(status='BASELINE'))
        old = copy.deepcopy(self.episode())
        recovery.reconcile(self.state, [watch()], now=T3)
        self.assertEqual(self.episode(), old)
        self.assertEqual(self.state['source_recovery']['counters']['market'], 2)
        self.assertEqual(len(self.state['tasks']), 2)

    def test_table_tamper_atomic(self):
        edits = [('owner', 'legal'), ('source', 'https://private.example'), ('episode', True),
                 ('attempts', 2), ('recovery_id', 'fake')]
        for key, value in edits:
            state = copy.deepcopy(self.state)
            state['source_recovery']['episodes'][self.rid][key] = value
            recovery._seal(state['source_recovery'])
            prior = copy.deepcopy(state)
            with self.assertRaises(ValueError):
                recovery.reconcile(state, [watch()], now=T1)
            self.assertEqual(state, prior)

    def test_lost_table_counter_hash_and_task_tamper(self):
        for mode in ('lost', 'counter', 'hash', 'payload'):
            state = copy.deepcopy(self.state)
            if mode == 'lost': del state['source_recovery']
            elif mode == 'counter':
                state['source_recovery']['counters']['market'] = 0
                recovery._seal(state['source_recovery'])
            elif mode == 'hash': state['source_recovery']['table_hash'] = 'e' * 64
            else: state['tasks'][self.tid]['payload']['source'] = 'edited'
            with self.assertRaises(ValueError): recovery.validate(state)

    def test_two_real_receipts_budget_no_fake_attempts(self):
        self.route()
        first = self.receipt(bound=False)
        recovery.record_attempt(self.state, self.rid, first)
        recovery.record_attempt(self.state, self.rid, first)
        self.assertEqual(self.episode()['attempts'], 1)
        second = self.receipt(rid='receipt-actual-2', bound=False)
        recovery.record_attempt(self.state, self.rid, second)
        self.assertEqual(self.episode()['status'], 'ESCALATED')
        self.assertEqual(self.episode()['attempts'], 2)
        third = self.receipt(rid='receipt-actual-3')
        with self.assertRaises(ValueError): recovery.record_attempt(self.state, self.rid, third)

    def test_race_escalation_held_across_healthy_observations(self):
        self.route()
        receipt = self.receipt()
        recovery.record_attempt(self.state, self.rid, receipt)
        core.transition(self.state, self.tid, 'BLOCKED', reason='SOURCE_VERIFICATION_CHANGED')
        recovery.escalate(self.state, self.rid, now=T2)
        w = watch(status='BASELINE', stamp=T3)
        recovery.reconcile(self.state, [w], now=T3)
        self.assertEqual(self.episode()['status'], 'ESCALATED')
        self.assertEqual(self.episode()['escalation_code'], 'SOURCE_VERIFICATION_CHANGED')
        self.assertEqual(self.episode()['attempts'], 1)
        self.assertEqual(self.state['tasks'][self.tid]['state'], 'BLOCKED')
        self.assertEqual(core.ready_tasks(self.state), [])
        recovery.validate(json.loads(json.dumps(self.state)))

    def test_escalation_requires_actual_attempt_and_safe_code(self):
        before = copy.deepcopy(self.state)
        with self.assertRaises(ValueError): recovery.escalate(self.state, self.rid, now=T1)
        with self.assertRaises(ValueError): recovery.escalate(self.state, self.rid, code='private@example.com', now=T1)
        self.assertEqual(self.state, before)
        self.route(); receipt = self.receipt(); recovery.record_attempt(self.state, self.rid, receipt)
        recovery.escalate(self.state, self.rid, now=T2)
        self.assertEqual(self.state['tasks'][self.tid]['state'], 'BLOCKED')

    def test_local_derived_no_fake_external_capture(self):
        w = watch(status='LOCAL_VERIFIED'); w['captured_at'] = None; w['observation_kind'] = 'local_derived_read'
        self.route(w); receipt = self.receipt(w); self.complete(receipt)
        recovery.verify_completed(self.state, self.rid, receipt, w)
        self.assertEqual(self.episode()['status'], 'RECOVERED')
        self.assertIsNone(self.episode()['recovered_evidence']['captured_at'])

    def test_secretary_owner_and_explicit_alternate(self):
        state = core.empty_state()
        recovery.reconcile(state, [watch('secretary'), watch('sourcing', source=recovery.ALTERNATE)], now=T0)
        rows = recovery.project(state)['episodes']
        self.assertEqual(next(r for r in rows if r['source_team'] == 'secretary')['owner'], 'graph')
        self.assertEqual(len(rows), 2)
        with self.assertRaises(ValueError):
            recovery.reconcile(state, [watch('sourcing', source='data/other.json')], now=T1)

    def test_fixed_source_transition_preserves_original_task(self):
        for team in ('sourcing', 'pricing'):
            self.state = core.empty_state()
            recovery.reconcile(self.state, [watch(team)], now=T0)
            self.rid = next(iter(self.state['source_recovery']['episodes']))
            self.tid = self.episode()['task_id']
            original_task = copy.deepcopy(self.state['tasks'][self.tid])
            original_hash = self.episode()['initial_evidence_hash']
            w = watch(team, status='BASELINE', source=recovery.ALTERNATE)
            recovery.reconcile(self.state, [w], now=T1)
            self.assertEqual(self.episode()['initial_source'], recovery.SOURCES[team])
            self.assertEqual(self.episode()['current_source'], recovery.ALTERNATE)
            self.assertEqual(self.episode()['initial_evidence_hash'], original_hash)
            self.assertEqual(self.state['tasks'][self.tid]['payload'], original_task['payload'])
            self.assertEqual(self.state['tasks'][self.tid]['evidence'], original_task['evidence'])
            self.assertEqual(len(self.state['tasks']), 1)
            receipt = self.receipt(w); self.complete(receipt)
            recovery.verify_completed(self.state, self.rid, receipt, w)
            self.assertEqual(self.episode()['status'], 'RECOVERED')
            self.assertEqual(self.episode()['recovered_evidence']['source'], recovery.ALTERNATE)
            edited = copy.deepcopy(self.state)
            edited['source_recovery']['episodes'][self.rid]['current_source'] = 'data/private.json'
            recovery._seal(edited['source_recovery'])
            with self.assertRaises(ValueError): recovery.validate(edited)

    def test_source_transition_rejected_for_other_team(self):
        before = copy.deepcopy(self.state)
        with self.assertRaises(ValueError):
            recovery.reconcile(self.state, [watch('market', status='BASELINE', source=recovery.ALTERNATE)], now=T1)
        self.assertEqual(self.state, before)

    def test_projection_safe_and_partial_waiting(self):
        w = watch(status='PARTIAL'); w['blockers'] = ['private@example.com']
        recovery.reconcile(self.state, [w], now=T1)
        text = json.dumps(recovery.project(self.state))
        self.assertNotIn('private@example.com', text)
        self.assertIn('SOURCE_UNAVAILABLE', text)
        self.assertEqual(self.episode()['status'], 'WAITING_SOURCE_RECOVERY')


if __name__ == '__main__':
    unittest.main()
