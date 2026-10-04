"""Feedback tests use temporary fixtures only: no network, models or repo data."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_feedback import build, evaluate_feedback

NOW = '2026-02-02T00:00:00+00:00'


def prediction():
    return {'metric': 'sale_event', 'unit': 'probability', 'entity_id': 'product:123',
            'cohort': 'launch-2026-01', 'horizon_seconds': 30 * 86400,
            'window_start': '2026-01-01T00:00:00Z', 'window_end': '2026-01-31T00:00:00Z',
            'kind': 'probability', 'value': .78}


def observation():
    return dict(prediction(), kind='binary', value=1, status='VERIFIED',
                observed_at='2026-02-01T00:00:00Z',
                evidence=[{'source': 'actual-order-export', 'path': 'outcome.json', 'sha256': 'a' * 64}])


class FeedbackTests(unittest.TestCase):
    def evaluate(self, p=None, o=None, now=NOW):
        return evaluate_feedback(prediction() if p is None else p, observation() if o is None else o, now=now)

    def test_brier_not_count(self):
        result = self.evaluate()
        self.assertEqual(result['status'], 'evaluated')
        self.assertAlmostEqual(result['score']['value'], .0484)
        self.assertEqual(result['score']['metric'], 'brier')
        self.assertIsNone(result['confidence'])
        self.assertFalse(result['training_allowed'])
        self.assertFalse(result['promotion_allowed'])
        self.assertEqual(self.evaluate(o=dict(observation(), kind='numeric', value=42))['status'], 'not_comparable')
        self.assertEqual(self.evaluate(o=dict(observation(), unit='count', value=42))['reason'], 'unit_mismatch')

    def test_missing_outcomes_are_not_zero(self):
        for o in (None, {}, {'value': None}, dict(observation(), value=None)):
            result = evaluate_feedback(prediction(), o, now=NOW)
            self.assertEqual(result['status'], 'awaiting_evidence')
            self.assertIsNone(result['score'])
            self.assertNotIn('observed', result)
        self.assertEqual(self.evaluate(o=dict(observation(), value=0))['score']['value'], .78 ** 2)

    def test_dimension_mismatches(self):
        for field, value in [('metric', 'gross_revenue'), ('unit', 'USD'), ('entity_id', 'product:456'),
                             ('cohort', 'other-30-day-cohort'), ('horizon_seconds', 29 * 86400)]:
            with self.subTest(field=field):
                self.assertEqual(self.evaluate(o=dict(observation(), **{field: value}))['status'], 'not_comparable')
        self.assertEqual(self.evaluate(o=dict(observation(), window_start='2026-01-02T00:00:00Z', window_end='2026-02-01T00:00:00Z'))['reason'], 'window_mismatch')

    def test_missing_dimensions(self):
        for field in ('metric', 'unit', 'cohort', 'entity_id', 'horizon_seconds', 'window_start', 'window_end', 'observed_at'):
            with self.subTest(field=field):
                o = observation()
                del o[field]
                self.assertNotEqual(self.evaluate(o=o)['status'], 'evaluated')

    def test_timezone_and_window(self):
        o = dict(observation(), window_start='2026-01-01T09:00:00+09:00', window_end='2026-01-31T09:00:00+09:00')
        self.assertEqual(self.evaluate(o=o)['status'], 'evaluated')
        for field in ('window_start', 'window_end', 'observed_at'):
            self.assertEqual(self.evaluate(o=dict(observation(), **{field: '2026-01-31T00:00:00'}))['status'], 'not_comparable')
        self.assertEqual(self.evaluate(now='2026-01-30T00:00:00Z')['reason'], 'horizon_not_elapsed')
        self.assertEqual(self.evaluate(o=dict(observation(), observed_at='2026-01-30T00:00:00Z'))['reason'], 'observation_time_invalid')
        self.assertEqual(self.evaluate(o=dict(observation(), observed_at='2026-02-03T00:00:00Z'))['reason'], 'observation_time_invalid')
        self.assertEqual(self.evaluate(o=dict(observation(), horizon_seconds=1))['reason'], 'horizon_mismatch')
        p, o = prediction(), observation()
        p['horizon_seconds'] = o['horizon_seconds'] = 1
        self.assertEqual(self.evaluate(p, o)['reason'], 'horizon_window_mismatch')
        o = dict(observation(), window_end='2025-01-01T00:00:00Z')
        self.assertEqual(self.evaluate(o=o)['reason'], 'invalid_window')

    def test_invalid_numeric_values(self):
        for value in (True, False, float('nan'), float('inf'), float('-inf'), '0.78'):
            for side in ('prediction', 'observation'):
                with self.subTest(value=value, side=side):
                    p, o = prediction(), observation()
                    (p if side == 'prediction' else o)['value'] = value
                    self.assertEqual(self.evaluate(p, o)['status'], 'not_comparable')
        for horizon in (True, float('nan'), float('inf'), -1, 0):
            self.assertEqual(self.evaluate(o=dict(observation(), horizon_seconds=horizon))['reason'], 'invalid_horizon')
        for value in (-.01, 1.01):
            self.assertEqual(self.evaluate(p=dict(prediction(), value=value))['status'], 'not_comparable')

    def test_unverified_and_fake_independence(self):
        for o in (dict(observation(), status='PROPOSED'), dict(observation(), evidence=[]),
                  dict(observation(), evidence=[{'source': 'display-log', 'sha256': 'invalid'}])):
            self.assertEqual(self.evaluate(o=o)['status'], 'awaiting_evidence')
        o = observation()
        o['evidence'] *= 20
        for e in o['evidence']:
            e['independent'] = True
        self.assertIsNone(self.evaluate(o=o)['confidence'])
        p = dict(prediction(), confidence=.4)
        self.assertEqual(self.evaluate(p, o)['confidence'], .4)

    def test_numeric_same_units_only(self):
        p = dict(prediction(), kind='numeric', unit='count', value=40)
        o = dict(observation(), kind='numeric', unit='count', value=42)
        self.assertEqual(self.evaluate(p, o)['score'], {'metric': 'signed_error', 'value': 2})
        self.assertEqual(self.evaluate(p, dict(o, unit='USD'))['status'], 'not_comparable')


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'data/operations/reports/report.json'
        self.output.parent.mkdir(parents=True)
        self.output.write_text('{"actual":"report"}')
        payload = {'canonical_id': 'SKU:existing', 'topic': 'legal'}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        self.state = {'tasks': {'t': {'id': 't', 'kind': 'snapshot_report', 'payload': payload, 'payload_hash': digest, 'state': 'COMPLETED'}},
                      'actions': {'a': {'id': 'a', 'task_id': 't'}},
                      'handoffs': {'h': {'task_id': 't', 'reason': 'source evidence', 'child_task_id': 'child'}},
                      'decisions': {'d': {'task_id': 't', 'action_id': 'a', 'reason': 'audit explanation', 'prediction': prediction(),
                                           'evidence': [{'source': 'actual-document'}]}},
                      'receipts': {'r': {'receipt_id': 'r', 'task_id': 't', 'action_id': 'a', 'kind': 'snapshot_report',
                                        'issuer': 'jarvis-execution-v1', 'root_owned': True, 'output_verified': True,
                                        'status': 'VERIFIED', 'payload_hash': digest,
                                        'output_evidence': [{'path': 'data/operations/reports/report.json', 'sha256': hashlib.sha256(self.output.read_bytes()).hexdigest()}]}}}

    def result(self):
        return build(self.state, self.root, now=NOW)

    def test_graph_is_relationships_not_log(self):
        self.state['tasks']['child'] = {'id': 'child', 'payload': {}, 'parent_id': 't', 'depends_on': ['t']}
        result = self.result()
        nodes = {n['id']: n for n in result['knowledge_graph']['nodes']}
        self.assertIn('entity:SKU:existing', nodes)
        self.assertTrue(nodes['task:t']['completed'])
        self.assertFalse(nodes['task:child']['completed'])
        self.assertTrue(result['decisions'][0]['completed'])
        self.assertEqual(result['decisions'][0]['reason'], 'audit explanation')
        self.assertIsNone(result['decisions'][0]['confidence'])
        relations = {e['relation'] for e in result['knowledge_graph']['edges']}
        self.assertTrue({'verifies', 'concerns_entity', 'depends_on', 'child_of', 'routes_to'} <= relations)
        for edge in result['knowledge_graph']['edges']:
            self.assertTrue(edge['evidence'])
            self.assertIn(edge['source'], nodes)
            self.assertIn(edge['target'], nodes)

    def test_proposals_and_legacy_display_are_not_completed(self):
        self.state['receipts'] = {}
        self.assertFalse(self.result()['decisions'][0]['completed'])
        self.state['receipts'] = [{'status': 'VERIFIED'}]
        self.assertFalse(self.result()['decisions'][0]['completed'])
        self.assertEqual(self.result()['feedback'][0]['status'], 'awaiting_evidence')

    def test_receipt_hash_and_provenance_fail_closed(self):
        receipt = self.state['receipts']['r']
        for field, value in [('payload_hash', '0' * 64), ('task_id', 'wrong'), ('issuer', 'old-display'),
                             ('root_owned', False), ('output_verified', False), ('kind', 'shopify_publish'), ('status', 'PROPOSED')]:
            with self.subTest(field=field):
                old = receipt[field]
                receipt[field] = value
                self.assertFalse(self.result()['decisions'][0]['completed'])
                receipt[field] = old
        self.output.write_text('tampered')
        self.assertFalse(self.result()['decisions'][0]['completed'])
        node = next(n for n in self.result()['knowledge_graph']['nodes'] if n['id'] == 'receipt:r')
        self.assertEqual(node['verification_reason'], 'receipt_output_hash_mismatch')

    def test_receipt_envelope_hash(self):
        receipt = self.state['receipts']['r']
        receipt['receipt_hash'] = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        self.assertTrue(self.result()['decisions'][0]['completed'])
        receipt['receipt_hash'] = '0' * 64
        self.assertFalse(self.result()['decisions'][0]['completed'])
        node = next(n for n in self.result()['knowledge_graph']['nodes'] if n['id'] == 'receipt:r')
        self.assertEqual(node['verification_reason'], 'receipt_hash_mismatch')

    def test_unsafe_missing_output(self):
        evidence = self.state['receipts']['r']['output_evidence'][0]
        for filename in ('../outside.json', str(self.output), 'data/operations/reports/missing.json'):
            evidence['path'] = filename
            self.assertFalse(self.result()['decisions'][0]['completed'])
        self.state['receipts']['r']['output_evidence'] = []
        self.assertFalse(self.result()['decisions'][0]['completed'])

    def test_pure_stable_no_write_network_or_model(self):
        original = copy.deepcopy(self.state)
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch('socket.socket', side_effect=AssertionError('network forbidden')), patch.object(Path, 'write_text', side_effect=AssertionError('write forbidden')):
            first, second = self.result(), self.result()
        self.assertEqual(first, second)
        self.assertEqual(self.state, original)
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        first['knowledge_graph']['nodes'][0]['data']['mutated'] = True
        self.assertEqual(self.state, original)

    def test_real_observation_source_hash(self):
        o = observation()
        source = self.root / 'outcome.json'
        source.write_text(json.dumps(o))
        o['evidence'][0]['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        self.assertEqual(build(self.state, self.root, observations={'d': o}, now=NOW)['feedback'][0]['status'], 'evaluated')
        source.write_text(json.dumps(dict(o, value=42)))
        o['evidence'][0]['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        result = build(self.state, self.root, observations={'d': o}, now=NOW)['feedback'][0]
        self.assertEqual(result['status'], 'awaiting_evidence')
        self.assertIsNone(result['score'])


if __name__ == '__main__':
    unittest.main()
