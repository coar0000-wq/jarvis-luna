"""Offline synthetic regressions; no recovered Admin snapshot is assumed."""
import copy
import json
import unittest
from shopify_readiness_audit import project

NOW = '2026-10-23T09:00:00Z'


def fact(value, **extra):
    return dict(value=value, source='synthetic_fixture', captured_at=NOW, **extra)


def fixture():
    return {'variants': [{'variant_id': 'fixture-1', 'facts': {key: fact(value) for key, value in {
        'cost_krw': 10000, 'packed_weight_g': 100, 'seller_shipping_krw': 5000,
        'customer_shipping_krw': 2000, 'other_known_costs_krw': 0,
        'merchandise_revenue_krw': 20000}.items()}}]}


class AuditTests(unittest.TestCase):
    def test_policy_floor_and_no_shipping_double_count(self):
        row = project(fixture(), now=NOW)['variants'][0]
        self.assertEqual(row['economics']['minimum_merchandise_price_krw'], 16368)
        self.assertEqual(row['economics']['modeled_contribution_krw'], 6560)
        self.assertIsNone(row['economics']['verified_actual_fee_rate'])
        self.assertIsNone(row['economics']['verified_actual_contribution_krw'])
        self.assertFalse(row['economics']['full_profit_verified'])

    def test_zero_and_missing_are_unknown(self):
        for key in ('cost_krw', 'packed_weight_g'):
            for value in (None, 0, '0', -1, True, 'NaN', '1e10000', '1e-10000'):
                with self.subTest(key=key, value=value):
                    data = fixture(); data['variants'][0]['facts'][key] = fact(value)
                    out = project(data, now=NOW)
                    self.assertIsNone(out['variants'][0]['economics']['minimum_merchandise_price_krw'])
                    json.dumps(out, allow_nan=False)

    def test_future_stale_sourceless_unusable(self):
        for override in ({'captured_at': '2026-10-24T00:00:00Z'},
                         {'captured_at': '2026-10-18T00:00:00Z'}, {'source': ''}):
            data = fixture(); data['variants'][0]['facts']['cost_krw'].update(override)
            self.assertIsNone(project(data, now=NOW)['variants'][0]['economics']['minimum_merchandise_price_krw'])

    def test_inventory_observations_never_assert_stockout(self):
        for tracked, expected in ((False, 'untracked_not_stockout'), (True, 'tracked_zero_quantity')):
            data = fixture(); data['variants'][0]['facts'].update(
                inventory_tracked=fact(tracked), inventory_quantity=fact(0), inventory_policy=fact('CONTINUE'))
            row = project(data, now=NOW)['variants'][0]
            self.assertEqual(row['inventory_observation'], expected)
            self.assertEqual(row['purchase_availability'], 'unknown')

    def test_native_admin_hold_claims_preserve_source_timestamp(self):
        data = fixture(); facts = data['variants'][0]['facts']
        facts.update(admin_status=fact('ACTIVE'), admin_price_unconverted=fact({'amount': '21.99', 'currencyCode': 'USD'}),
                     hold_reason=fact('DRAFT ONLY: synthetic. Zero prices are placeholders', source_updated_at='2026-10-18T12:28:34Z'))
        row = project(data, now=NOW)['variants'][0]
        for expected in ('admin_active_with_draft_only_hold_claim', 'admin_positive_price_with_zero_placeholder_hold_claim', 'hold_source_update_stale_review_required'):
            self.assertIn(expected, row['findings'])
        self.assertNotIn('hold_publication_mismatch_review_required', row['findings'])
        self.assertNotIn('published', row['facts'])
        self.assertEqual(row['facts']['hold_reason']['source_updated_at'], '2026-10-18T12:28:34Z')

    def test_cvr_requires_converted_sessions_same_cohort_and_period(self):
        for sessions, orders, converted, expected in ((0,0,0,None), (10,4,None,None), (10,20,2,.2), (10,0,11,None)):
            data = fixture(); data['analytics'] = fact(dict(human_sessions=sessions, human_orders=orders,
                human_converted_sessions=converted, bot_sessions=9, same_cohort=True, same_period=True))
            out = project(data, now=NOW)['analytics']
            self.assertEqual(out['human_conversion_rate'], expected)
            if sessions == 10 and orders == 20:
                self.assertEqual(out['orders_per_human_session'], 2)
        data['analytics']['value']['same_cohort'] = False
        self.assertIsNone(project(data, now=NOW)['analytics']['human_conversion_rate'])

    def test_authentication_claim_is_not_channel_proof(self):
        data = fixture(); data['channels'] = {'shopify_catalog': fact('eligible', authenticated=True)}
        out = project(data, now=NOW)
        self.assertEqual(out['channels']['shopify_catalog']['eligibility'], 'unknown')
        self.assertEqual(out['channels']['shopify_catalog']['reported_eligibility'], 'eligible')

    def test_input_unchanged_and_no_stage_promoted(self):
        data = fixture(); before = copy.deepcopy(data); out = project(data, now=NOW)
        self.assertEqual(data, before)
        self.assertTrue(all(not v['usable'] for v in out['variants'][0]['stages'].values()))
        self.assertFalse(out['guards']['publication_authorized'])

    def test_nonfinite_and_duplicate_ids_rejected(self):
        data = fixture(); data['variants'].append(copy.deepcopy(data['variants'][0]))
        with self.assertRaises(ValueError): project(data, now=NOW)
        data = fixture(); data['variants'][0]['facts']['cost_krw']['value'] = float('inf')
        with self.assertRaises(ValueError): project(data, now=NOW)


if __name__ == '__main__':
    unittest.main()
