"""Adversarial pure-controller tests. All receipts are synthetic test fixtures."""
import copy
import json
import unittest
from datetime import datetime, timezone
import jarvis_operations as ops


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.state = ops.empty_state()

    def task(self, **kwargs):
        return ops.create_task(self.state, goal=kwargs.pop('goal', 'market snapshot report'),
                               team=kwargs.pop('team', 'market'), **kwargs)

    def verifying(self, task):
        for status in ('ROUTED', 'IN_PROGRESS', 'VERIFYING'):
            task = ops.transition(self.state, task['task_id'], status)
        return task

    def receipt(self, task):
        now = '2026-10-03T00:00:00+00:00'
        receipt = {'receipt_id': 'receipt_' + task['task_id'], 'task_id': task['task_id'],
                   'kind': task['kind'], 'level': task['level'], 'payload_hash': task['payload_hash'],
                   'action_hash': ops.digest({'task': task['task_id']}), 'idempotency_key': task['task_id'],
                   'status': 'VERIFIED', 'issuer': 'jarvis-execution-v1', 'root_owned': True,
                   'output_verified': True, 'output_evidence': [{'path': 'data/operations/reports/test.json',
                   'sha256': ops.digest({'test_output': task['task_id']}), 'captured_at': now}],
                   'source_evidence': [], 'started_at': now, 'ended_at': now}
        self.state['receipts'][receipt['receipt_id']] = copy.deepcopy(receipt)
        return receipt

    def complete(self, task):
        task = self.verifying(task)
        return ops.transition(self.state, task['task_id'], 'COMPLETED', receipt=self.receipt(task))

    def test_existing_teams_only(self):
        self.assertEqual(len(ops.TEAMS), 11)
        self.assertNotIn('secretary', ops.TEAMS)
        self.assertEqual(len(set(ops.TEAMS)), 11)

    def test_canonical_sorted_and_roundtrip(self):
        self.assertEqual(ops.canonical({'b': [2], 'a': '한글'}), '{"a":"한글","b":[2]}')
        self.assertEqual(ops.digest({'a': 1, 'b': 2}), ops.digest({'b': 2, 'a': 1}))
        self.assertNotEqual(ops.digest(True), ops.digest(1))

    def test_canonical_rejects_non_json(self):
        for value in (float('nan'), float('inf'), {1: 'x'}, {'x': {1}}, (1, 2)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ops.canonical(value)

    def test_utc_requires_aware(self):
        self.assertEqual(ops.utc('2026-10-03T09:00:00+09:00'), '2026-10-03T00:00:00+00:00')
        for value in (True, 0, datetime(2026, 10, 3), '2026-10-03', 'bad'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ops.utc(value)
        self.assertIsNotNone(datetime.fromisoformat(ops.utc()).utcoffset())

    def test_server_levels(self):
        self.assertEqual(ops.action_level('snapshot_report'), 2)
        self.assertEqual(ops.action_level('shopify_publish'), 4)
        for kind in ('exec', 'shell', 'snapshot_report;rm', True, [], None):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                ops.action_level(kind)
        with self.assertRaises(TypeError):
            ops.ACTION_LEVELS['shopify_publish'] = 1

    def test_route_known_report(self):
        route = ops.route_intent('market snapshot report')
        self.assertEqual(route['teams_required'], ['market'])
        self.assertFalse(route['approval_required'])
        self.assertEqual(route['method'], 'local_report')

    def test_unknown_not_authorized_by_forced_team(self):
        route = ops.route_intent('launch a missile', forced_teams=['market'])
        self.assertEqual(route['status'], 'BLOCKED')
        self.assertEqual(route['teams_required'], [])

    def test_route_publish_request_only(self):
        route = ops.route_intent('publish Shopify listing')
        self.assertEqual(route['method'], 'request_only')
        self.assertTrue(route['approval_required'])

    def test_forced_team_validation(self):
        for teams in (['new-agent'], [], 'market', [True]):
            with self.subTest(teams=teams), self.assertRaises(ValueError):
                ops.route_intent('report', teams)

    def test_depth_counter_cannot_be_lowered_to_bypass_bound(self):
        parent = self.task()
        child = self.task(parent_id=parent['task_id'], payload={'child': 1})
        self.state['tasks'][child['task_id']]['depth'] = 1
        with self.assertRaises(ValueError):
            self.task(parent_id=child['task_id'], payload={'grandchild': 1})
        with self.assertRaises(ValueError):
            ops.transition(self.state, child['task_id'], 'ROUTED')

    def test_handoff_goal_limit_does_not_accept_proposal(self):
        parent = self.complete(self.task(payload={'i': 0}))
        for i in range(1, 32):
            self.task(payload={'i': i})
        proposal = ops.propose_handoff(self.state, parent['task_id'], 'legal', 'bounded review')
        with self.assertRaises(ValueError):
            ops.accept_handoff(self.state, proposal['proposal_id'])
        self.assertEqual(self.state['handoffs'][proposal['proposal_id']]['status'], 'PROPOSED')
        self.assertEqual(len(self.state['tasks']), 32)

    def test_empty_state_keyed_tables(self):
        self.assertEqual(self.state['schema_version'], 1)
        self.assertEqual(self.state['sequence'], 0)
        for key in ('tasks', 'handoffs', 'events', 'receipts', 'decisions', 'watch'):
            self.assertEqual(self.state[key], {})

    def test_stable_ids_across_restart(self):
        a = self.task(payload={'b': 2, 'a': 1})
        state = json.loads(json.dumps(self.state))
        b = ops.create_task(state, goal='market snapshot report', team='market', payload={'a': 1, 'b': 2})
        self.assertEqual(a['task_id'], b['task_id'])
        self.assertEqual(state['sequence'], 1)
        self.assertEqual(a['ownership']['team_lead'], 'market')
        self.assertNotIn('agent_id', a['ownership'])

    def test_dedup_does_not_overwrite_progress(self):
        a = self.task()
        ops.transition(self.state, a['task_id'], 'ROUTED')
        b = self.task()
        self.assertEqual(b['state'], 'ROUTED')
        self.assertEqual(len(self.state['tasks']), 1)
        self.assertEqual(self.state['sequence'], 2)

    def test_returned_copies_and_input_copies(self):
        payload = {'x': [1]}
        task = self.task(payload=payload)
        payload['x'].append(2)
        task['payload']['x'].append(3)
        self.assertEqual(self.state['tasks'][task['task_id']]['payload'], {'x': [1]})

    def test_unknown_team_kind_and_bad_arguments(self):
        for kwargs in ({'team': 'new'}, {'kind': 'arbitrary'}, {'payload': True}, {'priority': True},
                       {'depends_on': True}, {'depends_on': [True]}, {'deadline': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.task(**kwargs)
        self.assertEqual(len(self.state['tasks']), 0)

    def test_numeric_bool_state_rejected(self):
        for key in ('schema_version', 'sequence'):
            state = ops.empty_state()
            state[key] = True
            with self.assertRaises(ValueError):
                ops.ready_tasks(state)

    def test_goal_bound_and_dedup_at_limit(self):
        first = self.task(payload={'i': 0})
        for i in range(1, 32):
            self.task(payload={'i': i})
        self.assertEqual(self.task(payload={'i': 0})['task_id'], first['task_id'])
        with self.assertRaises(ValueError):
            self.task(payload={'i': 32})
        self.assertEqual(len(self.state['tasks']), 32)

    def test_depth_bound(self):
        parent = self.task()
        for i in range(2, 7):
            parent = self.task(parent_id=parent['task_id'], payload={'depth': i})
        self.assertEqual(parent['depth'], 6)
        with self.assertRaises(ValueError):
            self.task(parent_id=parent['task_id'], payload={'depth': 7})

    def test_unknown_dependency_blocked(self):
        task = self.task(depends_on=['task_missing'])
        self.assertEqual(task['state'], 'BLOCKED')
        self.assertEqual(ops.ready_tasks(self.state), [])
        with self.assertRaises(ValueError):
            ops.transition(self.state, task['task_id'], 'COMPLETED', result='success')

    def test_pending_dependency_not_ready(self):
        parent = self.task()
        child = self.task(payload={'child': 1}, depends_on=[parent['task_id']])
        self.assertEqual([t['task_id'] for t in ops.ready_tasks(self.state)], [parent['task_id']])
        ops.transition(self.state, child['task_id'], 'ROUTED')
        with self.assertRaises(ValueError):
            ops.transition(self.state, child['task_id'], 'IN_PROGRESS')
        self.complete(parent)
        self.assertEqual([t['task_id'] for t in ops.ready_tasks(self.state)], [child['task_id']])

    def test_failed_dependency_blocks(self):
        parent = self.task()
        child = self.task(depends_on=[parent['task_id']], payload={'child': 1})
        ops.transition(self.state, parent['task_id'], 'ROUTED')
        ops.transition(self.state, parent['task_id'], 'IN_PROGRESS')
        ops.transition(self.state, parent['task_id'], 'FAILED', reason='source unavailable')
        self.assertEqual(ops.ready_tasks(self.state), [])
        self.assertEqual(self.state['tasks'][child['task_id']]['state'], 'BLOCKED')

    def test_later_unknown_dependency_not_hidden_by_pending(self):
        parent = self.task()
        child = self.task(depends_on=[parent['task_id'], 'zz_missing'], payload={'child': 2})
        self.assertEqual(child['state'], 'BLOCKED')

    def test_dependency_cycles_and_self_dependency_tampering(self):
        a = self.task(payload={'a': 1})
        b = self.task(payload={'b': 1}, depends_on=[a['task_id']])
        self.state['tasks'][a['task_id']]['depends_on'] = [b['task_id']]
        ready = ops.ready_tasks(self.state)
        self.assertEqual(ready, [])
        self.assertEqual(self.state['tasks'][b['task_id']]['state'], 'BLOCKED')
        with self.assertRaises(ValueError):
            ops.transition(self.state, a['task_id'], 'ROUTED')

    def test_unknown_and_invalid_states(self):
        task = self.task()
        for status in ('success', True, [], 'COMPLETED', 'IN_PROGRESS', 'CREATED'):
            with self.subTest(status=status), self.assertRaises(ValueError):
                ops.transition(self.state, task['task_id'], status)
        with self.assertRaises(ValueError):
            ops.transition(self.state, 'missing', 'ROUTED')

    def test_reason_required_and_terminal_no_retry(self):
        task = self.task()
        with self.assertRaises(ValueError):
            ops.transition(self.state, task['task_id'], 'CANCELLED')
        ops.transition(self.state, task['task_id'], 'CANCELLED', reason='operator cancellation')
        with self.assertRaises(ValueError):
            ops.transition(self.state, task['task_id'], 'ROUTED')

    def test_success_string_cannot_complete(self):
        task = self.verifying(self.task())
        with self.assertRaises(ValueError):
            ops.transition(self.state, task['task_id'], 'COMPLETED', result='VERIFIED', receipt={'status': 'VERIFIED'})
        self.assertEqual(self.state['tasks'][task['task_id']]['state'], 'VERIFYING')

    def test_unregistered_receipt_rejected(self):
        task = self.verifying(self.task())
        receipt = self.receipt(task)
        self.state['receipts'].clear()
        with self.assertRaises(ValueError):
            ops.transition(self.state, task['task_id'], 'COMPLETED', receipt=receipt)

    def test_receipt_binding_and_real_output_flags(self):
        task = self.verifying(self.task(payload={'product': 'p1'}))
        valid = self.receipt(task)
        changes = {'task_id': 'other', 'kind': 'shopify_publish', 'payload_hash': '0' * 64,
                   'status': 'success', 'issuer': 'caller', 'root_owned': False, 'output_verified': False,
                   'level': True, 'action_hash': 'missing', 'idempotency_key': '', 'output_evidence': [],
                   'started_at': 'bad', 'ended_at': '2026-10-02T00:00:00+00:00'}
        for key, value in changes.items():
            bad = copy.deepcopy(valid)
            bad[key] = value
            self.state['receipts'][valid['receipt_id']] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                ops.transition(self.state, task['task_id'], 'COMPLETED', receipt=bad)
        self.state['receipts'][valid['receipt_id']] = valid
        completed = ops.transition(self.state, task['task_id'], 'COMPLETED', result={'status': 'fake'}, receipt=valid)
        self.assertEqual(completed['state'], 'COMPLETED')
        self.assertNotIn('status', completed['result'])
        self.assertTrue(completed['result']['result_schema']['actual_execution'])

    def test_l1_read_snapshot_exact_team_source(self):
        for team in ops.TEAMS:
            with self.subTest(team=team):
                task = self.verifying(self.task(team=team, kind='read_snapshot'))
                receipt = self.receipt(task)
                receipt['output_evidence'][0]['path'] = ops.READ_SOURCES[team]
                self.state['receipts'][receipt['receipt_id']] = copy.deepcopy(receipt)
                completed = ops.transition(self.state, task['task_id'], 'COMPLETED', receipt=receipt)
                self.assertEqual(completed['state'], 'COMPLETED')
                self.assertEqual(completed['level'], 1)

    def test_l1_wrong_team_report_or_unknown_path_rejected(self):
        task = self.verifying(self.task(kind='read_snapshot', team='market'))
        valid = self.receipt(task)
        for path in ('data/legal_team.json', 'data/operations/reports/test.json',
                     'data/market_team.json/extra', 'data/unknown.json'):
            bad = copy.deepcopy(valid)
            bad['output_evidence'][0]['path'] = path
            self.state['receipts'][bad['receipt_id']] = copy.deepcopy(bad)
            with self.subTest(path=path), self.assertRaises(ValueError):
                ops.transition(self.state, task['task_id'], 'COMPLETED', receipt=bad)
        self.assertEqual(self.state['tasks'][task['task_id']]['state'], 'VERIFYING')

    def test_single_output_receipt_required(self):
        task = self.verifying(self.task())
        receipt = self.receipt(task)
        receipt['output_evidence'].append(copy.deepcopy(receipt['output_evidence'][0]))
        self.state['receipts'][receipt['receipt_id']] = copy.deepcopy(receipt)
        with self.assertRaises(ValueError):
            ops.transition(self.state, task['task_id'], 'COMPLETED', receipt=receipt)

    def test_report_cannot_claim_source_path_as_report_output(self):
        task = self.verifying(self.task())
        receipt = self.receipt(task)
        receipt['output_evidence'][0]['path'] = 'data/market_team.json'
        self.state['receipts'][receipt['receipt_id']] = copy.deepcopy(receipt)
        with self.assertRaises(ValueError):
            ops.transition(self.state, task['task_id'], 'COMPLETED', receipt=receipt)

    def test_output_path_hash_and_capture_scope(self):
        task = self.verifying(self.task())
        valid = self.receipt(task)
        for key, value in (('path', '../secret'), ('path', 'data/operations/reports/../secret'),
                           ('sha256', 'bad'), ('captured_at', None)):
            bad = copy.deepcopy(valid)
            bad['output_evidence'][0][key] = value
            self.state['receipts'][bad['receipt_id']] = bad
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                ops.transition(self.state, task['task_id'], 'COMPLETED', receipt=bad)

    def test_receipt_immutable_at_completion_and_after(self):
        task = self.verifying(self.task())
        receipt = self.receipt(task)
        modified = copy.deepcopy(receipt)
        modified['source_evidence'] = ['fabricated']
        with self.assertRaises(ValueError):
            ops.transition(self.state, task['task_id'], 'COMPLETED', receipt=modified)
        completed = ops.transition(self.state, task['task_id'], 'COMPLETED', receipt=receipt)
        self.state['receipts'][receipt['receipt_id']]['source_evidence'] = ['changed']
        self.assertEqual(ops.project_summary(self.state)['counts'], {'BLOCKED': 1})
        proposal = ops.propose_handoff(self.state, task['task_id'], 'legal', 'review')
        with self.assertRaises(ValueError):
            ops.accept_handoff(self.state, proposal['proposal_id'])

    def test_receipt_cannot_replay_for_another_task(self):
        first = self.complete(self.task())
        second = self.verifying(self.task(payload={'other': 1}))
        receipt = self.state['receipts'][first['receipt_id']]
        with self.assertRaises(ValueError):
            ops.transition(self.state, second['task_id'], 'COMPLETED', receipt=receipt)

    def test_l4_no_self_promotion_or_approval_bool(self):
        task = self.task(kind='shopify_publish', payload={'level': 1, 'approved': True})
        self.assertEqual(task['level'], 4)
        task = self.verifying(task)
        with self.assertRaises(ValueError):
            ops.transition(self.state, task['task_id'], 'EXECUTING', result={'approved': True})
        with self.assertRaises(ValueError):
            ops.transition(self.state, task['task_id'], 'COMPLETED', receipt=self.receipt(task))
        ops.transition(self.state, task['task_id'], 'WAITING_APPROVAL')
        with self.assertRaises(ValueError):
            ops.transition(self.state, task['task_id'], 'EXECUTING', result={'human': True})
        self.assertFalse(ops.project_summary(self.state)['actioncards'][0]['execution_enabled'])

    def test_privileged_local_repair_not_self_enabled(self):
        task = self.verifying(self.task(kind='repair_graph'))
        with self.assertRaises(ValueError):
            ops.transition(self.state, task['task_id'], 'EXECUTING')

    def test_handoff_no_execution_and_parent_evidence_required(self):
        parent = self.task()
        proposal = ops.propose_handoff(self.state, parent['task_id'], 'legal', 'regulatory review')
        self.assertEqual(len(self.state['tasks']), 1)
        with self.assertRaises(ValueError):
            ops.accept_handoff(self.state, proposal['proposal_id'])
        self.complete(parent)
        child = ops.accept_handoff(self.state, proposal['proposal_id'])
        self.assertEqual(child['team'], 'legal')
        self.assertEqual(child['parent_id'], parent['task_id'])
        self.assertEqual(child['depends_on'], [parent['task_id']])
        self.assertEqual(child['state'], 'CREATED')
        self.assertEqual(child['depth'], 2)

    def test_only_secretary_handoff_and_replay(self):
        parent = self.complete(self.task())
        proposal = ops.propose_handoff(self.state, parent['task_id'], 'legal', 'review')
        for actor in ('legal', 'market', 'admin', True):
            with self.subTest(actor=actor), self.assertRaises(ValueError):
                ops.accept_handoff(self.state, proposal['proposal_id'], actor=actor)
        child = ops.accept_handoff(self.state, proposal['proposal_id'])
        with self.assertRaises(ValueError):
            ops.accept_handoff(self.state, proposal['proposal_id'])
        repeated = ops.propose_handoff(self.state, parent['task_id'], 'legal', 'review')
        self.assertEqual(repeated['child_id'], child['task_id'])
        self.assertEqual(len(self.state['tasks']), 2)

    def test_cross_team_creation_rejected(self):
        parent = self.task()
        with self.assertRaises(ValueError):
            self.task(team='legal', parent_id=parent['task_id'])

    def test_handoff_same_team_unknown_and_cycle(self):
        parent = self.complete(self.task())
        for team in ('market', 'new-agent'):
            with self.assertRaises(ValueError):
                ops.propose_handoff(self.state, parent['task_id'], team, 'review')
        p = ops.propose_handoff(self.state, parent['task_id'], 'legal', 'review')
        child = self.complete(ops.accept_handoff(self.state, p['proposal_id']))
        back = ops.propose_handoff(self.state, child['task_id'], 'market', 'review back')
        with self.assertRaises(ValueError):
            ops.accept_handoff(self.state, back['proposal_id'])

    def test_handoff_tampering_rejected(self):
        parent = self.complete(self.task())
        p = ops.propose_handoff(self.state, parent['task_id'], 'legal', 'review')
        self.state['handoffs'][p['proposal_id']]['payload']['approved'] = True
        with self.assertRaises(ValueError):
            ops.accept_handoff(self.state, p['proposal_id'])

    def test_handoff_semantic_dedup_across_reasons(self):
        parent = self.complete(self.task())
        a = ops.propose_handoff(self.state, parent['task_id'], 'legal', 'reason A')
        b = ops.propose_handoff(self.state, parent['task_id'], 'legal', 'reason B')
        child_a = ops.accept_handoff(self.state, a['proposal_id'])
        child_b = ops.accept_handoff(self.state, b['proposal_id'])
        self.assertEqual(child_a['task_id'], child_b['task_id'])
        self.assertEqual(len(self.state['tasks']), 2)

    def test_handoff_depth_limit(self):
        parent = self.complete(self.task())
        for team in ('legal', 'pricing', 'listing', 'design', 'channels'):
            proposal = ops.propose_handoff(self.state, parent['task_id'], team, 'review')
            parent = self.complete(ops.accept_handoff(self.state, proposal['proposal_id']))
        proposal = ops.propose_handoff(self.state, parent['task_id'], 'graph', 'too deep')
        with self.assertRaises(ValueError):
            ops.accept_handoff(self.state, proposal['proposal_id'])
        self.assertEqual(self.state['handoffs'][proposal['proposal_id']]['status'], 'PROPOSED')

    def test_public_projection_excludes_private_fields(self):
        task = self.task(goal='report secret@email.example', kind='shopify_publish',
                         payload={'approver': 'Alice Private', 'billing': {'token': 'secret'}})
        self.state['decisions']['private'] = {'approver': 'Alice Private', 'billing': 'secret'}
        projection = ops.project_summary(self.state)
        text = ops.canonical(projection)
        for private in ('Alice', 'secret@email', 'billing', 'token', 'payload', 'approver'):
            self.assertNotIn(private, text)
        self.assertEqual(projection['actioncards'][0]['status'], 'REQUEST_ONLY')

    def test_fake_completed_status_not_projected_as_success(self):
        task = self.task()
        self.state['tasks'][task['task_id']]['state'] = 'COMPLETED'
        self.assertEqual(ops.project_summary(self.state)['counts'], {'BLOCKED': 1})
        child = self.task(depends_on=[task['task_id']], payload={'child': True})
        self.assertNotIn(child['task_id'], [t['task_id'] for t in ops.ready_tasks(self.state)])

    def test_tampered_level_payload_identity_rejected(self):
        task = self.task(kind='shopify_publish')
        self.state['tasks'][task['task_id']]['level'] = 1
        self.assertEqual(ops.ready_tasks(self.state), [])
        with self.assertRaises(ValueError):
            ops.transition(self.state, task['task_id'], 'ROUTED')

    def test_priority_ready_order(self):
        normal = self.task()
        urgent = self.task(payload={'u': 1}, priority='urgent')
        self.assertEqual([t['task_id'] for t in ops.ready_tasks(self.state)], [urgent['task_id'], normal['task_id']])

    def test_events_are_keyed_monotonic_preserved(self):
        task = self.task()
        original = copy.deepcopy(self.state['events'])
        ops.transition(self.state, task['task_id'], 'ROUTED')
        for key, value in original.items():
            self.assertEqual(self.state['events'][key], value)
        self.assertEqual(list(self.state['events']), ['event_000000000001', 'event_000000000002'])

    def test_sequence_collision_fails_before_mutation(self):
        self.task()
        self.state['sequence'] = 0
        before = copy.deepcopy(self.state)
        with self.assertRaises(ValueError):
            self.task(payload={'new': True})
        self.assertEqual(self.state, before)


if __name__ == '__main__':
    unittest.main()
