"""All observations use TemporaryDirectory dummy evidence; no repository outputs."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from jarvis_watch import observe, SOURCE_MAPPINGS, digest

NOW = '2026-10-03T10:00:00+00:00'
LATER = '2026-10-03T10:01:00+00:00'


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, relative, value):
        p = self.root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value), encoding='utf-8')

    def products(self, price=1000, capture=NOW, unit=None):
        row = {'canonical_product_id': 'cp_dummy', 'pd_no': 'dummy',
               'price_krw': price, 'grade': 'S', 'source': {'collected_at': capture},
               'responsible_person': {'email': 'dummy-private@example.test'}}
        if unit is not None:
            row['price_unit'] = unit
        doc = {'generated_at': NOW, 'products': [row]}
        self.put('data/product_master.json', doc)
        return doc

    def run_observe(self, previous=None, now=NOW, policy=None):
        return observe(self.root, previous, now=now, policy=policy)

    @staticmethod
    def watcher(result, team):
        return next(w for w in result['watchers'] if w['source_team'] == team)

    def test_twelve_functions_missing_blocked_not_no_change(self):
        out = self.run_observe()
        self.assertEqual(len(out['watchers']), 12)
        self.assertEqual(len({w['source_team'] for w in out['watchers']}), 12)
        self.assertTrue(all(w['status'] == 'BLOCKED' and not w['is_agent'] for w in out['watchers']))
        self.assertEqual(out['events'], [])
        self.assertTrue(all('orders' in w['unconnected'] for w in out['watchers']))

    def test_baseline_unchanged_and_no_input_mutation(self):
        self.products()
        first = self.run_observe()
        self.assertEqual(self.watcher(first, 'pricing')['status'], 'BASELINE')
        self.assertEqual(first['events'], [])
        prev = copy.deepcopy(first['state'])
        second = self.run_observe(first['state'])
        self.assertEqual(self.watcher(second, 'pricing')['status'], 'NO_CHANGE')
        self.assertEqual(first['state'], prev)

    def test_generator_clock_and_record_order_ignored(self):
        doc = self.products()
        first = self.run_observe()
        doc['generated_at'] = LATER
        doc['products'][0]['gate_generated_at'] = LATER
        self.put('data/product_master.json', doc)
        second = self.run_observe(first['state'], LATER)
        self.assertEqual(second['events'], [])
        self.assertEqual(self.watcher(second, 'pricing')['source_hash'], self.watcher(first, 'pricing')['source_hash'])

    def test_capture_preserved_hash_changes_but_no_fake_change(self):
        self.products()
        first = self.run_observe()
        self.products(capture=LATER)
        out = self.run_observe(first['state'], LATER)
        self.assertEqual(out['events'], [])
        self.assertNotEqual(self.watcher(out, 'pricing')['source_hash'], self.watcher(first, 'pricing')['source_hash'])
        self.assertEqual(out['state']['sources']['pricing']['records']['cp_dummy']['captured_at'], LATER)

    def test_real_measured_price_changed_dedup_stable_ids(self):
        self.products()
        first = self.run_observe()
        self.products(1100, LATER)
        out = self.run_observe(first['state'], LATER)
        prices = [e for e in out['events'] if e['type'] == 'PRICE_CHANGED']
        self.assertEqual(len(prices), 1)
        event = prices[0]
        self.assertEqual(event['source_entity_id'], 'cp_dummy')
        self.assertEqual(event['change']['before'], 1000)
        self.assertEqual(event['change']['after'], 1100)
        self.assertEqual(event['change']['unit'], 'product')
        self.assertEqual(len(event['evidence']['source_hash']), 64)
        replay = self.run_observe(first['state'], '2026-10-03T10:02:00+00:00')
        self.assertEqual(prices[0]['event_id'], next(e['event_id'] for e in replay['events'] if e['type'] == 'PRICE_CHANGED'))
        self.assertEqual(self.run_observe(out['state'], LATER)['events'], [])

    def test_units_not_comparable_no_price_event(self):
        self.products(unit='product')
        first = self.run_observe()
        self.products(2000, LATER, 'bundle')
        out = self.run_observe(first['state'], LATER)
        self.assertFalse(any(e['type'] == 'PRICE_CHANGED' for e in out['events']))

    def test_no_price_event_for_add_or_remove(self):
        doc = self.products()
        first = self.run_observe()
        added = copy.deepcopy(doc['products'][0])
        added['canonical_product_id'] = 'cp_second'
        doc['products'].append(added)
        self.put('data/product_master.json', doc)
        out = self.run_observe(first['state'])
        self.assertFalse(any(e['type'] == 'PRICE_CHANGED' for e in out['events']))
        self.assertTrue(any(e['change']['kind'] == 'added' for e in out['events']))

    def test_stale_missing_future_captures_never_unchanged(self):
        self.products()
        first = self.run_observe()
        for capture in (None, '2025-01-01T00:00:00+00:00', '2027-01-01T00:00:00+00:00', '2026-10-03'):
            with self.subTest(capture=capture):
                self.products(capture=capture)
                out = self.run_observe(first['state'])
                self.assertEqual(self.watcher(out, 'pricing')['status'], 'BLOCKED')
                self.assertEqual(out['events'], [])

    def test_recovery_is_baseline_not_fake_delta(self):
        self.products()
        first = self.run_observe()
        self.products(capture=None)
        blocked = self.run_observe(first['state'])
        self.products(2000)
        recovered = self.run_observe(blocked['state'])
        self.assertEqual(self.watcher(recovered, 'pricing')['status'], 'BASELINE')
        self.assertEqual(recovered['events'], [])

    def test_cooldown_pending_deadline_exception_and_dedup(self):
        self.products()
        first = self.run_observe()
        self.products(1100)
        second = self.run_observe(first['state'])
        self.products(1200, LATER)
        third = self.run_observe(second['state'], LATER)
        self.assertEqual(self.watcher(third, 'pricing')['status'], 'COOLDOWN')
        self.assertEqual(third['events'], [])
        policy = {'deadlines': {'pricing': LATER, 'sourcing': LATER}}
        fourth = self.run_observe(third['state'], LATER, policy)
        self.assertEqual(len(fourth['events']), 2)
        self.assertEqual(self.run_observe(fourth['state'], LATER, policy)['events'], [])

    def test_generated_offers_not_observed_prices(self):
        self.put('data/pricing_model.json', {'generated_at': NOW, 'offers': {'price_usd': 9}})
        out = self.run_observe()
        self.assertEqual(self.watcher(out, 'pricing')['status'], 'BLOCKED')
        self.assertEqual(out['events'], [])

    def test_private_fields_excluded_even_when_changed(self):
        doc = self.products()
        first = self.run_observe()
        doc['products'][0]['responsible_person']['email'] = 'another-private@example.test'
        self.put('data/product_master.json', doc)
        out = self.run_observe(first['state'])
        self.assertEqual(out['events'], [])
        self.assertNotIn('private', json.dumps(out))
        self.assertNotIn('responsible_person', json.dumps(out))

    def test_real_entity_added_generic_not_trend_or_tool(self):
        doc = {'collected_at': NOW, 'items': [{'url': 'https://public.example/a', 'kind': 'research'}]}
        self.put('data/institution_sources.json', doc)
        first = self.run_observe()
        doc['items'].append({'url': 'https://public.example/b', 'kind': 'research'})
        self.put('data/institution_sources.json', doc)
        out = self.run_observe(first['state'])
        self.assertEqual([e['type'] for e in out['events']], ['SOURCE_CHANGED'])
        self.assertEqual(out['events'][0]['source_entity_id'], 'url:' + digest('https://public.example/b'))

    def test_schema_policy_timestamp_and_cursor_rejected(self):
        for policy in ({'surprise': True}, {'cooldown_seconds': True}, {'max_age_seconds': float('nan')},
                       {'deadlines': {'unknown': NOW}}, {'deadlines': {'pricing': '2026-10-03'}}):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                self.run_observe(policy=policy)
        for previous in ({}, {'schema_version': True}, [], {'schema_version': 2}):
            with self.subTest(previous=previous), self.assertRaises(ValueError):
                self.run_observe(previous)
        with self.assertRaises(ValueError):
            self.run_observe(now='2026-10-03')

    def test_bad_json_duplicate_boolean_price_invalid(self):
        for price in (True, '1000', -1, float('nan')):
            with self.subTest(price=price):
                self.products(price)
                self.assertEqual(self.watcher(self.run_observe(), 'pricing')['status'], 'BLOCKED')
        doc = self.products()
        doc['products'].append(copy.deepcopy(doc['products'][0]))
        self.put('data/product_master.json', doc)
        self.assertEqual(self.watcher(self.run_observe(), 'sourcing')['status'], 'BLOCKED')
        (self.root / 'data/product_master.json').write_text('{bad', encoding='utf-8')
        self.assertEqual(self.watcher(self.run_observe(), 'pricing')['status'], 'BLOCKED')

    def test_cursor_hash_tamper_rejected(self):
        self.products()
        state = self.run_observe()['state']
        state['sources']['pricing']['records']['cp_dummy']['value']['amount'] = 999
        with self.assertRaises(ValueError):
            self.run_observe(state)

    def test_secretary_actual_nested_schema_and_source_capture(self):
        doc = {'generated_at': NOW, 'automation_freshness': {'workflows': {
            'observed_at': NOW, 'workflows': {'dummy.yml': {
                'status': 'success', 'latest_attempt': {'id': 1, 'conclusion': 'success'},
                'age_hours': 5}}}}}
        self.put('data/dashboard_runtime.json', doc)
        first = self.run_observe()
        self.assertEqual(self.watcher(first, 'secretary')['status'], 'BASELINE')
        doc['automation_freshness']['workflows']['workflows']['dummy.yml']['latest_attempt']['id'] = 2
        self.put('data/dashboard_runtime.json', doc)
        out = self.run_observe(first['state'])
        self.assertEqual(out['events'][0]['source_entity_id'], 'dummy.yml')
        self.assertEqual(out['events'][0]['type'], 'SOURCE_CHANGED')

    def test_pending_evidence_not_emitted_after_it_becomes_stale(self):
        self.products()
        first = self.run_observe()
        self.products(1100)
        second = self.run_observe(first['state'])
        self.products(1200, LATER)
        pending = self.run_observe(second['state'], LATER)
        future = '2026-10-06T10:00:00+00:00'
        self.products(1200, future)
        out = self.run_observe(pending['state'], future)
        self.assertEqual(out['events'], [])
        self.assertEqual(self.watcher(out, 'pricing')['pending_blocked'], 'STALE_OR_FUTURE_EVENT_EVIDENCE')

    def test_reported_source_failure_and_invalid_boolean_field_block(self):
        doc = {'status': 'failed', 'collected_at': NOW,
               'items': [{'url': 'https://public.example/a', 'beauty': True}]}
        self.put('data/google_trends_beauty.json', doc)
        self.assertEqual(self.watcher(self.run_observe(), 'market')['blockers'], ['SOURCE_REPORTED_FAILURE'])
        doc['status'] = 'success'
        doc['items'][0]['beauty'] = 'yes'
        self.put('data/google_trends_beauty.json', doc)
        self.assertEqual(self.watcher(self.run_observe(), 'market')['status'], 'BLOCKED')

    def test_url_query_values_not_exposed(self):
        self.put('data/institution_sources.json', {'collected_at': NOW, 'items': [
            {'url': 'https://public.example/a?email=dummy-private@example.test', 'kind': 'research'}]})
        out = self.run_observe()
        self.assertEqual(self.watcher(out, 'institutions')['status'], 'BASELINE')
        self.assertNotIn('dummy-private', json.dumps(out))

    def test_observe_no_disk_writes(self):
        self.products()
        before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        out = self.run_observe()
        self.run_observe(out['state'])
        after = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
