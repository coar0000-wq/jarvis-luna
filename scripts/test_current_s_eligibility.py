#!/usr/bin/env python3
"""Offline freshness regressions. Synthetic observations; no collected clock writes."""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import csv
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import current_s_eligibility as current
import build_daiso_candidate_comparison as comparison
import build_listing_gate as gate
import daiso_daily_beauty_to_shopify as daily
import gate_signature as signature
from daiso import score_shopify_demand as scorer
from daiso import export_shopify_s_csv as legacy_csv

NOW = datetime(2026, 10, 23, 6, 0, tzinfo=timezone.utc)
FRESH = (NOW - timedelta(hours=1)).isoformat()
OLD = (NOW - timedelta(days=10)).isoformat()


def product():
    return {'pd_no': 'fixture', 'name': '시카 수분 세럼 30 ml', 'bucket': '스킨케어',
            'site_category': '에센스/세럼/앰플', 'rating': 4.9, 'review_count': 5000,
            'price_krw': 3000, 'sold_out': False, 'collected_at': FRESH,
            'url': 'https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo=fixture',
            'image_url': 'https://example.test/synthetic.jpg', 'source': 'SYNTHETIC TEST ONLY'}


def dashboard():
    return {'global_channels': {'oliveyoung_us': [
        {'product': 'Centella hydrating serum', 'price_usd': 30, 'url': 'https://example.test/p/1'},
        {'product': 'Centella serum', 'price_usd': 30, 'url': 'https://example.test/p/2'}]},
        'global_channels_status': {'oliveyoung_us': {
            'status': 'ok', 'trust': 'verified', 'collected_at': FRESH}}}


def historical():
    return {**product(), 'grade': 'S', 'desk': 'skincare', 'shopify_score': 99,
            's_rule': 'ingredient+form', 'registerable': True,
            'current_s_eligibility': {'eligible': True}}


def put(root, name, value):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return p


class CurrentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.p, self.d, self.r = product(), dashboard(), historical()
        self.guard = patch.multiple(scorer, _SUN_EVIDENCE={}, DESK_MEMBER={},
                                    DESK_SITE_CATEGORIES={})
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def assess(self, clock=NOW):
        return current.assess_rows([self.r], [self.p], self.d, now=clock)['fixture']

    def test_fresh_source_qualifies_without_changing_history_or_observations(self):
        before = deepcopy((self.p, self.d, self.r))
        with patch.object(scorer, 'us_listings', side_effect=AssertionError('historical fallback used')):
            result = self.assess()
        self.assertTrue(result['eligible'])
        self.assertEqual(result['fresh_s_rule'], 'ingredient+form')
        self.assertEqual(result['product_collected_at'], FRESH)
        self.assertEqual(result['market_evidence'][0]['collected_at'], FRESH)
        self.assertEqual((self.p, self.d, self.r), before)

    def test_channels_require_explicit_status_trust_and_time(self):
        for status in (None, {}, [], {'oliveyoung_us': []},
                       {'oliveyoung_us': {'collected_at': FRESH}},
                       {'oliveyoung_us': {'status': 'ok', 'trust': 'verified'}},
                       {'oliveyoung_us': {'status': 'stale', 'source_status': 'ok', 'trust': 'verified', 'collected_at': FRESH}},
                       {'oliveyoung_us': {'status': 'empty', 'trust': 'verified', 'collected_at': FRESH}},
                       {'oliveyoung_us': {'status': 'ok', 'trust': 'unverified', 'collected_at': FRESH}},
                       {'oliveyoung_us': {'status': 'ok', 'trust': [], 'collected_at': FRESH}}):
            with self.subTest(status=status):
                self.d['global_channels_status'] = status
                self.assertFalse(self.assess()['eligible'])
                self.assertEqual(scorer.provenanced_channels(self.d, NOW), {})

    def test_invalid_stale_future_and_naive_market_times_block(self):
        for value in ('', 'invalid', None, OLD, '2026-10-23T05:00:00',
                      (NOW + timedelta(minutes=5, microseconds=1)).isoformat()):
            with self.subTest(value=value):
                self.d['global_channels_status']['oliveyoung_us']['collected_at'] = value
                self.assertFalse(self.assess()['eligible'])
        for value in ((NOW - timedelta(hours=48)).isoformat(),
                      (NOW + timedelta(minutes=5)).isoformat()):
            self.d['global_channels_status']['oliveyoung_us']['collected_at'] = value
            self.assertTrue(self.assess()['eligible'])
        self.d['global_channels_status']['oliveyoung_us']['collected_at'] = (NOW-timedelta(hours=48,microseconds=1)).isoformat()
        self.assertFalse(self.assess()['eligible'])

    def test_product_72h_boundaries_and_missing_source_timestamp(self):
        for value in ('', 'invalid', None, OLD, '2026-10-23T05:00:00',
                      (NOW + timedelta(minutes=5, microseconds=1)).isoformat()):
            with self.subTest(value=value):
                self.p['collected_at'] = value
                result = self.assess()
                self.assertFalse(result['eligible'])
                self.assertTrue(any(r.startswith('product_observation_') for r in result['reasons']))
                self.assertTrue(result['market_evidence'])
        for value in ((NOW - timedelta(hours=72)).isoformat(), (NOW + timedelta(minutes=5)).isoformat()):
            self.p['collected_at'] = value
            self.assertTrue(self.assess()['eligible'])
        self.p['collected_at'] = (NOW-timedelta(hours=72,microseconds=1)).isoformat()
        self.assertFalse(self.assess()['eligible'])

    def test_generated_and_failed_attempt_clocks_do_not_refresh_capture(self):
        self.p.update(collected_at=OLD, updated_at=NOW.isoformat(), last_attempt_at=NOW.isoformat(),
                      last_attempt_status='failed')
        self.d.update(generated_at=NOW.isoformat())
        self.d['global_channels_status']['oliveyoung_us'].update(
            collected_at=OLD, last_attempt_at=NOW.isoformat(), source_status='ok')
        before = deepcopy((self.p, self.d))
        result = self.assess()
        self.assertFalse(result['eligible'])
        self.assertIn('product_observation_stale', result['reasons'])
        self.assertIn('verified_current_market_evidence_missing', result['reasons'])
        self.assertEqual(before, (self.p, self.d))

    def test_product_source_and_unique_identity_required(self):
        for value in ('', 'http://example.test/1', 'https://', None,
                      'https://www.daisomall.co.kr/',
                      'https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo=wrong'):
            self.p['url'] = value
            self.assertFalse(self.assess()['eligible'])
        self.assertFalse(current.assess_rows([self.r], [product(), product()], dashboard(), now=NOW)['fixture']['eligible'])

    def test_per_item_https_url_required(self):
        for value in ('', 'http://example.test', 'https://', 'https://user@example.test/p', None,
                      'https://global.oliveyoung.com/'):
            with self.subTest(value=value):
                for row in self.d['global_channels']['oliveyoung_us']:
                    row['url'] = value
                self.assertFalse(self.assess()['eligible'])

    def test_independent_fresh_matching_channel_can_qualify(self):
        self.d['global_channels']['sokoglam_us'] = deepcopy(self.d['global_channels']['oliveyoung_us'])
        self.d['global_channels_status']['sokoglam_us'] = {'status': 'ok', 'trust': 'manual', 'collected_at': FRESH}
        self.d['global_channels_status']['oliveyoung_us']['collected_at'] = OLD
        result = self.assess()
        self.assertTrue(result['eligible'])
        self.assertEqual(result['fresh_global_match']['channel'], 'sokoglam_us')
        self.assertEqual([e['channel'] for e in result['market_evidence']], ['sokoglam_us'])
        self.assertIn('oliveyoung_us', result['excluded_market_sources'])

    def test_fresh_unrelated_channel_cannot_launder_stale_match(self):
        self.d['global_channels']['sokoglam_us'] = [
            {'product': 'Lipstick', 'price': 30, 'url': 'https://example.test/other'}]
        self.d['global_channels_status']['sokoglam_us'] = {'status': 'ok', 'trust': 'verified', 'collected_at': FRESH}
        self.d['global_channels_status']['oliveyoung_us']['collected_at'] = OLD
        result = self.assess()
        self.assertFalse(result['eligible'])
        self.assertIn('fresh_market_s_rules_not_met', result['reasons'])

    def test_historical_us_listings_cannot_supply_fresh_points(self):
        for row in self.d['global_channels']['oliveyoung_us']:
            row.pop('price_usd')
        with patch.object(scorer, 'us_listings', return_value=[{'name': 'centella serum', 'price': 100}]*20):
            result = self.assess()
        self.assertFalse(result['eligible'])
        self.assertEqual(result['fresh_us_market_hits'], 0)

    def test_category_desk_requires_two_fresh_hits(self):
        self.p.update(name='시카 바디워시 300 ml', bucket='바디케어', site_category='샤워/입욕')
        self.r.update(bucket='바디케어', desk='body')
        rows = self.d['global_channels']['oliveyoung_us']
        rows[0]['product'] = 'Centella shampoo'
        rows[1]['product'] = 'Centella shampoo'
        result = self.assess()
        self.assertTrue(result['eligible'])
        self.assertEqual(result['fresh_s_rule'], 'category_desk_us_evidence')
        rows.pop()
        self.assertFalse(self.assess()['eligible'])

    def test_malformed_product_fields_fail_closed(self):
        self.p['name'] = {'unexpected': 'shape'}
        self.assertFalse(self.assess()['eligible'])
        self.assertIn('current_scoring_inputs_invalid', self.assess()['reasons'])

    def test_conflicting_canonical_identities_fail_closed(self):
        rows = [dict(self.r, grade='A'), self.r]
        for ordered in (rows, list(reversed(rows))):
            result = current.assess_rows(ordered, [self.p], self.d, now=NOW)['fixture']
            self.assertFalse(result['eligible'])
            self.assertIn('canonical_identity_missing_or_ambiguous', result['reasons'])

    def test_soldout_and_non_s_never_become_eligible(self):
        self.p['sold_out'] = True
        self.assertFalse(self.assess()['eligible'])
        self.p['sold_out'] = False
        self.r['grade'] = 'A'
        self.assertFalse(self.assess()['eligible'])

    def test_comparison_and_scorer_share_exact_market_policy(self):
        self.assertEqual(comparison.market_universe(self.d, NOW), current.market_universe(self.d, NOW))
        self.assertEqual(scorer.provenanced_channels(self.d, NOW), self.d['global_channels'])


class ConsumerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.r, self.p, self.d = historical(), product(), dashboard()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(scorer, _SUN_EVIDENCE={}, DESK_MEMBER={}, DESK_SITE_CATEGORIES={}))
        self.stack.enter_context(patch.object(current, 'now_utc', side_effect=lambda value=None: value or NOW))
        self.write()

    def write(self):
        put(self.root, 'data/daiso_real/products.json', {'products': [self.p]})
        put(self.root, 'data/dashboard_runtime.json', self.d)
        put(self.root, 'data/daiso_real/shopify_demand_score.json', {'all_scored': [self.r]})
        put(self.root, 'data/daiso_real/shopify_s_recommendations.json', {'recommendations': [self.r]})

    def signature_paths(self):
        data = self.root / 'data'
        return patch.multiple(signature, DATA=data, **{
            name: data / rel for name, rel in {
                'PRODUCT_MASTER': 'product_master.json', 'GOSI': 'gosi.json',
                'LABELS': 'daiso_real/daiso_us_labels.json', 'PRICING': 'pricing_model.json',
                'LEGAL': 'legal_products.json', 'RECOMMENDATIONS': 'daiso_real/shopify_s_recommendations.json',
                'GATE': 'listing_gate.json'}.items()})

    def test_daily_rechecks_sources_ignoring_saved_eligible_true(self):
        with patch.object(daily, 'ROOT', self.root):
            self.assertEqual(len(daily.s_ranked(('skincare',), priority={})), 1)
            self.p['collected_at'] = OLD
            self.write()
            self.assertEqual(daily.s_ranked(('skincare',), priority={}), [])
        self.assertEqual(json.loads((self.root/'data/daiso_real/shopify_demand_score.json').read_text())['all_scored'][0]['grade'], 'S')

    def test_gate_signature_expires_with_unchanged_bytes(self):
        with self.signature_paths():
            signed = {'items': [{'pd_no': 'fixture', 'ready': True}],
                      'agent_input_signature': signature.agent_input_signature([self.r])}
            self.assertEqual(signature.stale_reason(signed), '')
            before = {p: p.read_bytes() for p in self.root.rglob('*.json')}
            with patch.object(current, 'now_utc', side_effect=lambda value=None: value or NOW+timedelta(hours=49)):
                self.assertIn('current_s_evidence', signature.stale_reason(signed))
                with self.assertRaises(RuntimeError):
                    signature.require_current(signed)
            self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.json')})

    def test_expired_ready_gate_blocks_operational_export_and_action_queue_without_writes(self):
        import export_shopify_operational as export
        import build_shopify_action_queue as queue
        with self.signature_paths():
            signed = {'items': [{'pd_no': 'fixture', 'ready': True}],
                      'agent_input_signature': signature.agent_input_signature([self.r])}
            put(self.root, 'data/listing_gate.json', signed)
            existing = self.root/'data/shopify_exports/products.csv'
            existing.parent.mkdir(parents=True)
            existing.write_text('original draft bytes', encoding='utf-8')
            before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            with patch.object(current, 'now_utc', side_effect=lambda value=None: value or NOW+timedelta(hours=49)), \
                 patch.multiple(export, D=self.root/'data', OUT=self.root/'data/shopify_exports'), \
                 patch.multiple(queue, D=self.root/'data', OUT=self.root/'data/shopify_action_queue.json'):
                for command in (export.main, queue.main):
                    with self.subTest(command=command.__module__), self.assertRaises(RuntimeError):
                        command()
            self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_import_csv_rechecks_actual_source_expiry(self):
        import build_shopify_import_csv as exporter
        source = put(self.root, 'data/shopify_listing_copy.json', {
            'items': [{'pd_no': 'fixture', 'copy_status': 'ok', 'copy': {'title': 'Fixture serum'}}]})
        report = self.root/'report.json'
        with self.signature_paths():
            signed = {'items': [{'pd_no': 'fixture', 'ready': True}],
                      'agent_input_signature': signature.agent_input_signature([self.r])}
            put(self.root, 'data/listing_gate.json', signed)
            before = source.read_bytes()
            with patch.object(current, 'now_utc', side_effect=lambda value=None: value or NOW+timedelta(hours=49)), \
                 patch.multiple(exporter, ROOT=self.root, COPY=source, PRICING=self.root/'missing-price.json',
                                STATUS=self.root/'missing-status.json', OUT=self.root/'out.csv', REPORT=report), \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(exporter.main(), 0)
            result = json.loads(report.read_text())
            self.assertEqual(result['rows'], 0)
            self.assertEqual(result['skipped'][0]['reason'], 'listing_gate_missing_or_stale')
            self.assertEqual(source.read_bytes(), before)

    def test_eligibility_changes_do_not_delete_historical_product_identities(self):
        from publish_transaction import removed_identities
        policy = json.loads((Path(__file__).resolve().parents[1]/'config/publish_policy.json').read_text())
        before = {'all_scored': [self.r], 'top_recommendations': [self.r]}
        after_row = dict(self.r, current_s_eligibility=current.assess_rows(
            [self.r], [self.p], self.d, now=NOW+timedelta(hours=100))['fixture'])
        after = {'all_scored': [after_row], 'top_recommendations': [after_row]}
        self.assertFalse(after_row['current_s_eligibility']['eligible'])
        self.assertEqual(removed_identities(before, after, policy), [])
        self.assertEqual(after_row['grade'], self.r['grade'])
        self.assertEqual(after_row['shopify_score'], self.r['shopify_score'])

    def test_new_signature_cannot_validate_already_stale_ready_gate(self):
        self.p['collected_at'] = OLD
        self.write()
        with self.signature_paths():
            signed = {'items': [{'pd_no': 'fixture', 'ready': True}],
                      'agent_input_signature': signature.agent_input_signature([self.r])}
            self.assertIn('current_s_evidence', signature.stale_reason(signed))
            signed['items'][0]['ready'] = False
            self.assertEqual(signature.stale_reason(signed), '')

    def test_fully_blocked_history_is_stable_across_expiry_and_runtime_refresh(self):
        self.r.update(registerable=False, agent_ready=False, public_ready=False)
        self.write()
        with self.signature_paths():
            signed = {'items': [{'pd_no': 'fixture', 'ready': False, 'agent_ready': False, 'public_ready': False}],
                      'agent_input_signature': signature.agent_input_signature([self.r])}
            self.assertEqual(signature.stale_reason(signed), '')
            with patch.object(current, 'now_utc', side_effect=lambda value=None: value or NOW+timedelta(hours=100)):
                self.assertEqual(signature.stale_reason(signed), '')
                signature.require_current(signed)
            self.d['global_channels_status']['oliveyoung_us']['collected_at'] = NOW.isoformat()
            put(self.root, 'data/dashboard_runtime.json', self.d)
            self.assertEqual(signature.stale_reason(signed), '')

    def legacy_blocked_gate(self):
        self.r.update(registerable=False, agent_ready=False, public_ready=False)
        self.write()
        legacy = signature.agent_input_signature([self.r])
        legacy['semantic_sources'].pop('masked/current_s_evidence', None)
        return {'items': [{'pd_no': 'fixture', 'ready': False, 'agent_ready': False,
                           'public_ready': False}], 'agent_input_signature': legacy}

    def test_legacy_fully_blocked_signature_needs_no_migration_or_source_rewrite(self):
        with self.signature_paths():
            signed = self.legacy_blocked_gate()
            before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            self.assertEqual(signature.agent_input_signature([self.r]), signed['agent_input_signature'])
            with patch.object(current, 'now_utc', side_effect=lambda value=None: value or NOW+timedelta(hours=100)):
                self.assertEqual(signature.stale_reason(signed), '')
                signature.require_current(signed)
            self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_legacy_blocked_signature_still_binds_other_source_changes(self):
        with self.signature_paths():
            signed = self.legacy_blocked_gate()
            put(self.root, 'data/legal_products.json', {'items': {'fixture': {'hard_block': True}}})
            self.assertIn('data/legal_products.json', signature.stale_reason(signed))

    def test_legacy_signature_without_ready_recommendations_never_authorizes_expired_ready_gate(self):
        with self.signature_paths():
            signed = self.legacy_blocked_gate()
            for flag in ('ready', 'agent_ready', 'public_ready'):
                with self.subTest(flag=flag):
                    signed['items'][0] = {'pd_no': 'fixture', flag: True}
                    with patch.object(current, 'now_utc', side_effect=lambda value=None: value or NOW+timedelta(hours=100)):
                        self.assertIn('current_s_evidence', signature.stale_reason(signed))
                        with self.assertRaises(RuntimeError):
                            signature.require_current(signed)

    def test_source_status_revocation_invalidates_signature(self):
        with self.signature_paths():
            signed = {'items': [{'pd_no': 'fixture', 'ready': True}],
                      'agent_input_signature': signature.agent_input_signature([self.r])}
            self.d['global_channels_status']['oliveyoung_us']['status'] = 'stale'
            self.write()
            self.assertIn('current_s_evidence', signature.stale_reason(signed))

    def test_legacy_csv_rechecks_saved_registerable_and_preserves_recommendations(self):
        out = self.root/'data/daiso_real/legacy.csv'
        with patch.multiple(legacy_csv, ROOT=self.root,
                            IN_S=self.root/'data/daiso_real/shopify_s_recommendations.json',
                            OUT_CSV=out, RUNTIME=self.root/'missing-runtime.json'), redirect_stdout(io.StringIO()):
            legacy_csv.main()
            with out.open() as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 1)
            self.p['collected_at'] = OLD
            self.write()
            before = (self.root/'data/daiso_real/shopify_s_recommendations.json').read_bytes()
            legacy_csv.main()
            with out.open() as stream:
                self.assertEqual(list(csv.DictReader(stream)), [])
            self.assertEqual((self.root/'data/daiso_real/shopify_s_recommendations.json').read_bytes(), before)

    def test_listing_gate_preserves_s_but_blocks_expired_registration(self):
        self.p['collected_at'] = OLD
        self.write()
        data = self.root/'data'
        paths = {name: data/rel for name, rel in {
            'RECOMMENDATIONS': 'daiso_real/shopify_s_recommendations.json', 'COPY': 'shopify_listing_copy.json',
            'PRICING': 'pricing_model.json', 'LEGAL': 'legal_products.json', 'LEGAL_FULL': 'legal_full.json',
            'LABELS': 'daiso_real/daiso_us_labels.json', 'GOSI': 'gosi.json', 'PRODUCT_MASTER': 'product_master.json',
            'OUTPUT': 'listing_gate.json', 'TYPESAFE_STORE': 'typesafe_advisory.json'}.items()}
        with self.signature_paths(), patch.multiple(gate, ROOT=self.root, DATA=data, **paths), \
                patch.object(gate.typesafe_decision_support, 'evaluate', return_value={'source': 'local', 'mode': 'local'}), \
                patch.object(gate.typesafe_decision_support, 'ledger', return_value={'calls': 0, 'call_log': []}), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(gate.main(), 0)
        result = json.loads(paths['OUTPUT'].read_text())['items'][0]
        self.assertFalse(result['ready'])
        self.assertFalse(result['agent_ready'])
        self.assertFalse(result['public_ready'])
        for key in ('blocked_by', 'agent_blocked_by', 'public_blocked_by'):
            self.assertIn(current.BLOCKER, result[key])
        recs = json.loads(paths['RECOMMENDATIONS'].read_text())['recommendations']
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]['grade'], 'S')
        self.assertFalse(recs[0]['registerable'])

    def test_scorer_retains_historical_s_scores_and_original_capture(self):
        self.p['collected_at'] = OLD
        self.d['global_channels_status']['oliveyoung_us'].update(status='stale', collected_at=OLD)
        self.write()
        before = (self.root/'data/daiso_real/products.json').read_bytes()
        historical_signals = scorer.extract_signals(scorer.historical_channels(self.d))
        listings = [{'name': 'centella hydrating serum', 'price': 30}]*2
        expected = scorer.score_one(self.p, historical_signals, market_listings=listings)
        scorer.assign_grades([expected])
        output = self.root/'data/daiso_real/score-out.json'
        with patch.multiple(scorer, PRODUCTS=self.root/'data/daiso_real/products.json',
                            DASHBOARD=self.root/'data/dashboard_runtime.json', PRODUCT_MASTER=self.root/'missing.json',
                            OUT=output, OUT_S=self.root/'data/daiso_real/recs-out.json',
                            OUT_REJECT=self.root/'data/daiso_real/reject-out.json', _US_CACHE=listings), redirect_stdout(io.StringIO()):
            self.assertEqual(scorer.main(), 0)
        row = json.loads(output.read_text())['all_scored'][0]
        self.assertEqual(row['grade'], expected['grade'])
        self.assertEqual(row['shopify_score'], expected['shopify_score'])
        self.assertEqual(row['grade'], 'S')
        self.assertFalse(row['current_s_eligibility']['eligible'])
        self.assertEqual(row['current_s_eligibility']['product_collected_at'], OLD)
        self.assertEqual((self.root/'data/daiso_real/products.json').read_bytes(), before)
        self.assertEqual(len(json.loads((self.root/'data/daiso_real/recs-out.json').read_text())['recommendations']), 1)


if __name__ == '__main__':
    unittest.main()
