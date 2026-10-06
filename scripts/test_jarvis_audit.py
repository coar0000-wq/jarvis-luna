"""Adversarial audit tests. Synthetic TEMP roots only, no providers."""
import copy
import json
import tempfile
import unittest
from unittest.mock import patch
import jarvis_audit as audit
import jarvis_operations as core
import jarvis_execution as execution
import test_jarvis_operating_integration as integration
NOW = integration.NOW
import run_jarvis_operations as runner


class AuditUnit(unittest.TestCase):
    def state(self):
        state = core.empty_state()
        task = core.create_task(state, goal='snapshot review', team='sourcing', kind='snapshot_report',
                                payload={'private':'person@example.com'}, evidence={'secret':'never public'})
        return state, task['task_id']

    def test_legacy_ids_and_events_exact(self):
        state, tid = self.state()
        for event in state['events'].values():
            event.pop('audit')
        state.pop('audit')
        before = copy.deepcopy(state)
        prep = audit.prepare(state, tid, now=NOW)
        self.assertEqual(state['tasks'], before['tasks'])
        for eid, old in before['events'].items():
            self.assertEqual(state['events'][eid], old)
        self.assertEqual(audit.project_summary(state)['counts']['legacy'], len(before['events']))
        self.assertEqual(prep['approval_state'], 'not_required_local')

    def test_restart_dedupe_and_honesty(self):
        state, tid = self.state()
        for target in ('ROUTED','IN_PROGRESS','VERIFYING','EXECUTING'):
            core.transition(state, tid, target)
        prep = audit.prepare(state, tid, now=NOW)
        before = copy.deepcopy(state)
        self.assertEqual(prep['observation'], 'restart_observation')
        self.assertIsNone(prep['decision_id'])
        self.assertEqual(audit.prepare(state, tid), prep)
        self.assertEqual(state, before)

    def test_failed_receipt_private_only_and_dedup(self):
        state, tid = self.state()
        prep = audit.prepare(state, tid, now=NOW)
        receipt = {'status':'BLOCKED','proof':'untrusted','output_verified':True}
        with tempfile.TemporaryDirectory() as root:
            record = audit.outcome(state, prep, root=root, receipt=receipt, now=NOW)
            before = copy.deepcopy(state)
            self.assertEqual(record, audit.outcome(state, prep, root=root, receipt=receipt))
        self.assertEqual(state, before)
        self.assertFalse(record['result']['actual_execution'])
        self.assertEqual(record['result']['receipt'], receipt)
        self.assertEqual(state['receipts'], {})
        self.assertNotIn('actions', state)
        self.assertEqual(state['decisions'][prep['decision_id']]['status'], 'PROPOSED')
        summary = audit.project_summary(state)
        self.assertEqual(summary['counts']['failure'], 1)
        self.assertEqual(set(summary), {'mode','external_authority','counts'})
        self.assertNotIn('person', json.dumps(summary))
        self.assertNotIn('secret', json.dumps(summary))
        self.assertNotIn('proof', json.dumps(summary))

    def test_chain_payload_and_record_tamper_failclosed(self):
        state, tid = self.state()
        prep = audit.prepare(state, tid, now=NOW)
        for target in ('chain','payload','record','decision','missing'):
            altered = copy.deepcopy(state)
            if target == 'chain':
                next(iter(altered['events'].values()))['audit']['reason'] = 'forged'
            elif target == 'payload':
                altered['audit']['payloads'][prep['action_hash']]['payload']['private'] = 'changed'
            elif target == 'record':
                altered['audit']['preparations'][prep['preparation_id']]['approval_state'] = 'HUMAN_APPROVED'
            elif target == 'decision':
                altered['decisions'][prep['decision_id']]['reason'] = 'forged reason'
            else:
                altered['audit']['payloads'].clear()
            with self.assertRaises(ValueError):
                audit.validate(altered)

    def test_event_metadata_is_copied_and_detail_unchanged(self):
        state, tid = self.state()
        detail = {'proposal_id':'proposal', 'child_id':'child'}
        metadata = {'reason':'new reason', 'evidence_ref':'private'}
        event = core._event(state, 'HANDOFF_ACCEPTED', tid, detail, audit=metadata, at=NOW)
        detail['child_id'] = 'mutated'
        metadata['reason'] = 'mutated'
        event['audit']['reason'] = 'mutated return'
        saved = state['events'][event['event_id']]
        self.assertEqual(saved['detail'], {'proposal_id':'proposal','child_id':'child'})
        self.assertEqual(saved['audit']['reason'], 'new reason')
        self.assertEqual(saved['at'], NOW.isoformat())
        audit.validate(state)

    def test_bounds_no_approval_or_registry_expansion(self):
        registry = execution.canonical(execution.REGISTRY)
        policy = execution.POLICY_HASH
        for kind, descriptor in execution.REGISTRY.items():
            if not descriptor['enabled']:
                self.assertEqual(audit.approval_state({'kind':kind,'approved':True}), 'unavailable')
        for bad in (float('nan'), {'a':float('inf')}, 'x' * (audit.MAX_BYTES + 1)):
            with self.assertRaises(ValueError): audit.bounded(bad)
        self.assertEqual(execution.canonical(execution.REGISTRY), registry)
        self.assertEqual(execution.POLICY_HASH, policy)
        self.assertEqual(len(core.TEAMS), 11)


class AuditIntegration(integration.OperatingIntegration):
    def test_persisted_decision_precedes_executing_and_exact_handoff(self):
        original = runner.atomic
        observed = []
        def persist(root, relative, value):
            if relative == runner.STATE:
                for task in value['tasks'].values():
                    if task['state'] == 'EXECUTING':
                        prep = next(p for p in value['audit']['preparations'].values() if p['task_id'] == task['task_id'])
                        self.assertIn(prep['decision_id'], value['decisions'])
                        events = list(value['events'].values())
                        pe = next(e for e in events if e['kind'] == 'TASK_AUDIT_PREPARED' and e['task_id'] == task['task_id'])
                        te = next(e for e in events if e['task_id'] == task['task_id'] and e['kind'] == 'TASK_TRANSITION' and e['detail']['to'] == 'EXECUTING')
                        self.assertLess(pe['sequence'], te['sequence'])
                        observed.append(task['task_id'])
            return original(root, relative, value)
        with patch.object(runner, 'atomic', side_effect=persist):
            runner.run(self.root, now=NOW)
        self.assertTrue(observed)
        state = self.load(runner.STATE)
        for event in state['events'].values():
            if event['kind'] == 'HANDOFF_ACCEPTED':
                self.assertEqual(set(event['detail']), {'proposal_id','child_id'})
        self.assertEqual(audit.project_summary(state)['counts']['outcomes'], 11)

    def test_exception_persisted_and_rethrown(self):
        with patch.object(execution, 'execute', side_effect=OSError('synthetic private error')):
            with self.assertRaises(OSError): runner.run(self.root, now=NOW)
        state = self.load(runner.STATE)
        record = next(iter(state['audit']['outcomes'].values()))
        self.assertEqual(record['result']['status'], 'ERROR')
        self.assertFalse(record['result']['actual_execution'])
        self.assertFalse(state['receipts'])
        self.assertEqual(audit.project_summary(state)['counts']['failure'], 1)

    def test_blocked_raw_receipt_not_trusted(self):
        receipt = {'status':'BLOCKED','reason':'synthetic failure','output_verified':True}
        with patch.object(execution, 'execute', return_value=receipt):
            runner.run(self.root, now=NOW)
        state = self.load(runner.STATE)
        self.assertFalse(state['receipts'])
        self.assertNotIn('actions', state)
        self.assertTrue(state['audit']['outcomes'])
        self.assertTrue(all(d['status'] == 'PROPOSED' for d in state['decisions'].values()))


if __name__ == '__main__':
    unittest.main()
