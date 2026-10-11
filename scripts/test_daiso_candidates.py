#!/usr/bin/env python3
"""Offline fixtures for continuous discovery with unchanged operating products."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

import daiso_candidate_store as store
import build_daiso_candidate_comparison as compare
import operational_freshness as freshness
import validate_daiso_collection as validator
from daiso import score_shopify_demand as scorer

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc)
FRESH = (NOW - timedelta(minutes=2)).isoformat()
OLD = (NOW - timedelta(days=5)).isoformat()
BASE = 'https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo='


def queue_row(pd_no='fixture-new', bucket='스킨케어', name='시카 수분 세럼 30 ml'):
    return {'pdNo': pd_no, 'url': BASE + pd_no, '예상버킷': bucket, '이름_list': name}


def observed(pd_no='fixture-new', name='시카 수분 세럼 30 ml'):
    return {'pd_no': pd_no, 'name': name, 'bucket': '스킨케어', 'url': BASE + pd_no,
            'price_krw': 3000, 'rating': 4.9, 'review_count': 5000,
            'collected_at': FRESH, 'source': 'fixture detail', 'sold_out': False}


def pool():
    return store.upsert_candidate(None, observed(), operating_ids={'operating'},
                                  execution_id='fixture:1:collect', now=NOW)[0]


class SelectionTests(unittest.TestCase):
    def select(self, rows=None, **kwargs):
        return store.select_discovery({'items': rows or [queue_row()]}, {'operating'}, now=NOW, **kwargs)

    def test_full_operating_quota_does_not_suppress_new_candidates(self):
        items, info = self.select()
        self.assertEqual(items, [('fixture-new', BASE + 'fixture-new')])
        self.assertTrue(info['operating_limit_unchanged'])
        self.assertTrue(info['legacy_visited_ignored'])

    def test_existing_operating_ids_are_never_candidates(self):
        items, _ = self.select([queue_row('operating')])
        self.assertEqual(items, [])

    def test_scope_unknown_legal_and_parked_are_skipped_before_requests(self):
        rows = [queue_row('unknown', ''), queue_row('oral', '구강용품'),
                queue_row('spf', name='SPF50 선크림'), queue_row('parked')]
        items, _ = self.select(rows, excluded_name=lambda n: '선크림' in n, excluded_ids={'parked'})
        self.assertEqual(items, [])

    def test_wrong_host_and_identity_are_rejected(self):
        a, b = queue_row('a'), queue_row('b')
        a['url'] = 'https://example.invalid/'
        b['url'] = BASE + 'not-b'
        self.assertEqual(self.select([a, b])[0], [])

    def test_category_round_robin_prevents_full_skin_bucket_dominating(self):
        rows = [queue_row('s1'), queue_row('s2'), queue_row('m1', '마스크팩'), queue_row('m2', '마스크팩')]
        ids = [p[0] for p in self.select(rows)[0]]
        self.assertEqual(set(ids[:2]), {'s1', 'm1'})
        self.assertEqual(set(ids[2:]), {'s2', 'm2'})

    def test_recent_candidates_skipped_stale_revalidated_after_unseen(self):
        p = pool()
        self.assertEqual(self.select(pool=p)[0], [])
        p['items']['fixture-new']['collected_at'] = OLD
        items, info = self.select([queue_row(), queue_row('unseen')], pool=p)
        self.assertEqual([x[0] for x in items], ['unseen', 'fixture-new'])
        self.assertEqual(info['revalidation_identities'], 1)

    def test_failure_cooldown_and_permanent_rejection(self):
        state = store.record_observation(None, 'fixture-new', 'failed', at=FRESH)
        self.assertEqual(self.select(state=state)[0], [])
        state['observations']['fixture-new']['at'] = OLD
        self.assertEqual(len(self.select(state=state)[0]), 1)
        state['observations']['fixture-new']['status'] = 'excluded'
        self.assertEqual(self.select(state=state)[0], [])

    def test_zero_skip_counts_preserve_schema_after_candidate_ages(self):
        p = pool()
        _, recent = self.select(pool=p)
        self.assertEqual(recent['skipped']['candidate_recently_verified'], 1)
        p['items']['fixture-new']['collected_at'] = OLD
        _, stale = self.select(pool=p)
        self.assertEqual(stale['skipped']['candidate_recently_verified'], 0)
        self.assertEqual(set(recent['skipped']), set(stale['skipped']))
        self.assertEqual(set(stale['skipped']), set(store.DISCOVERY_SKIP_REASONS))
        from publish_transaction import removed_identities
        self.assertEqual(removed_identities(recent['skipped'], stale['skipped'],
                                            {'identity_fields': []}), [])

    def test_missing_queue_keeps_zero_counter_schema(self):
        _, info = store.select_discovery({}, set(), now=NOW)
        self.assertEqual(info['skipped'], dict.fromkeys(store.DISCOVERY_SKIP_REASONS, 0))

    def test_selection_does_not_mutate_inputs(self):
        q = {'items': [queue_row()]}; before = deepcopy(q)
        store.select_discovery(q, set(), now=NOW)
        self.assertEqual(q, before)


class StoreTests(unittest.TestCase):
    def test_verified_candidate_is_separate_and_approval_only(self):
        p = pool(); r = p['items']['fixture-new']
        self.assertEqual(p['count'], 1)
        self.assertFalse(r['may_publish'])
        self.assertFalse(r['may_replace_operating_products'])
        self.assertTrue(r['approval_required'])
        self.assertEqual(r['collected_at'], FRESH)

    def test_operating_identity_cannot_enter_pool(self):
        with self.assertRaises(ValueError):
            store.upsert_candidate(None, observed(), operating_ids={'fixture-new'}, execution_id='x', now=NOW)

    def test_missing_price_time_url_and_outside_scope_fail_closed(self):
        cases = ({'price_krw': None}, {'price_krw': True}, {'collected_at': OLD},
                 {'collected_at': (NOW + timedelta(hours=1)).isoformat()},
                 {'url': 'https://example.invalid/'}, {'bucket': '구강용품'}, {'name': ''})
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                store.upsert_candidate(None, dict(observed(), **changes), operating_ids=set(), execution_id='x', now=NOW)

    def test_upsert_deduplicates_preserves_first_seen_and_drops_approvals(self):
        p = pool(); before = deepcopy(p)
        o = observed(); o['approved'] = True; o['registerable'] = True; o['canonical_product_id'] = 'forbidden'
        updated, is_new = store.upsert_candidate(p, o, operating_ids=set(), execution_id='next', now=NOW)
        self.assertFalse(is_new)
        self.assertEqual(len(updated['items']), 1)
        self.assertEqual(updated['items']['fixture-new']['first_seen_at'], p['items']['fixture-new']['first_seen_at'])
        self.assertNotIn('approved', updated['items']['fixture-new'])
        self.assertNotIn('registerable', updated['items']['fixture-new'])
        self.assertNotIn('canonical_product_id', updated['items']['fixture-new'])
        self.assertEqual(p, before)

    def test_malformed_pool_and_observation_history_not_silently_reset(self):
        for invalid in ({}, {'schema_version': 1, 'items': []}):
            with self.assertRaises(ValueError): store.pool_document(invalid)
        with self.assertRaises(ValueError): store.state_document({'schema_version': 1, 'observations': []})


class ComparisonTests(unittest.TestCase):
    def dashboard(self):
        return {'global_channels': {'oliveyoung_us': [{'product': 'Centella Hydrating Serum', 'price': 25,
                                                       'url': BASE + 'market-reference'}]},
                'global_channels_status': {'oliveyoung_us': {'status': 'ok', 'trust': 'verified', 'collected_at': FRESH}}}

    def test_market_excludes_stale_missing_timestamp_and_missing_item_urls(self):
        for kind in ('stale', 'missing_time', 'missing_url'):
            d = self.dashboard()
            if kind == 'stale': d['global_channels_status']['oliveyoung_us']['collected_at'] = OLD
            if kind == 'missing_time': d['global_channels_status']['oliveyoung_us'].pop('collected_at')
            if kind == 'missing_url': d['global_channels']['oliveyoung_us'][0].pop('url')
            self.assertEqual(compare.market_universe(d, NOW)[0], [], kind)

    def test_scoring_injected_market_never_reads_global_cache_or_source_files(self):
        with patch.object(scorer, 'us_listings', side_effect=AssertionError('unverified file read forbidden')):
            report = compare.build_comparison(pool(), {'products': [observed('operating')]}, self.dashboard(), now=NOW)
        self.assertEqual(report['candidate_count'], 1)
        self.assertFalse(report['may_publish'])
        self.assertFalse(report['may_replace_operating_products'])

    def test_no_market_evidence_never_creates_replacement(self):
        report = compare.build_comparison(pool(), {'products': [observed('operating')]}, {}, now=NOW)
        self.assertEqual(report['proposal_count'], 0)
        self.assertIn('verified_market_match_missing', report['items'][0]['comparison_blockers'])

    def test_same_category_form_and_score_gain_propose_but_never_execute(self):
        candidate = observed(); incumbent = observed('operating'); incumbent.update(rating=0, review_count=0)
        p = store.upsert_candidate(None, candidate, operating_ids={'operating'}, execution_id='x', now=NOW)[0]
        before = deepcopy(incumbent)
        report = compare.build_comparison(p, {'products': [incumbent]}, self.dashboard(), now=NOW)
        self.assertEqual(report['proposal_count'], 1)
        proposal = report['items'][0]['replacement_proposal']
        self.assertFalse(proposal['may_execute'])
        self.assertTrue(proposal['approval_required'])
        self.assertEqual(proposal['operating_count_delta'], 0)
        self.assertIn('payload_hash_approval', proposal['remaining_gates'])
        self.assertEqual(incumbent, before)

    def test_sold_out_and_old_candidates_never_proposed(self):
        for changes in ({'sold_out': True}, {'collected_at': OLD}):
            p = pool(); p['items']['fixture-new'].update(changes)
            report = compare.build_comparison(p, {'products': [observed('operating')]}, self.dashboard(), now=NOW)
            self.assertEqual(report['proposal_count'], 0)


class CurrentRunValidationTests(unittest.TestCase):
    def doc(self):
        p = pool()
        run = {'status': 'candidates_collected', 'requested': 1, 'ok': 0,
               'parse_failed': 0, 'http_error': 0, 'collector_completed': True,
               'collector_version': 2, 'execution_id': 'fixture:1:collect',
               'started_at': (NOW - timedelta(minutes=3)).isoformat(),
               'finished_at': (NOW - timedelta(minutes=1)).isoformat(),
               'discovery_enabled': True, 'operating_updates_enabled': False,
               'operating_before_sha256': 'fixture-hash', 'operating_after_sha256': 'fixture-hash',
               'candidate_pool_digest': store.canonical_digest(p),
               'candidate_ids': ['fixture-new'], 'candidates_new': 1, 'candidates_updated': 0}
        old = {'status': 'ok', 'requested': 1, 'ok': 1, 'parse_failed': 0, 'http_error': 0,
               'started_at': OLD, 'finished_at': OLD}
        return validator.record_attempt({'last_run': old}, run), p

    def validate(self, d, p):
        return validator.validate(d, outcome='success', execution_id='fixture:1:collect',
            started_after=(NOW - timedelta(minutes=4)).isoformat(), now=NOW,
            candidate_pool=p, operating_sha256='fixture-hash')

    def test_candidate_success_separate_from_operating_success(self):
        d, p = self.doc(); result = self.validate(d, p)
        self.assertEqual(result['mode'], 'candidates')
        self.assertEqual(result['publish_products'], 'false')
        self.assertEqual(d['last_success']['finished_at'], OLD)
        self.assertEqual(d['last_candidate_success'], d['last_attempt'])
        assessed = freshness.assess_collection(d, now=NOW)
        self.assertTrue(assessed['is_candidate_collection'])
        self.assertFalse(assessed['is_no_change'])
        self.assertEqual(assessed['last_success_at'], OLD)
        self.assertEqual(assessed['status'], 'success')

    def test_changed_operating_hash_or_candidate_digest_blocks(self):
        for change in ('operating_after_sha256', 'candidate_pool_digest'):
            d, p = self.doc(); d['last_run'][change] = 'bad'; d['last_attempt'] = deepcopy(d['last_run']); d['last_candidate_success'] = deepcopy(d['last_run'])
            self.assertEqual(self.validate(d, p)['mode'], 'failed')

    def test_missing_or_unsafe_pool_safety_flags_block(self):
        for changes in ({'may_publish': True}, {'may_replace_operating_products': True}, {'approval_required': False}):
            d, p = self.doc(); p.update(changes)
            d['last_run']['candidate_pool_digest'] = store.canonical_digest(store.pool_document(p))
            d['last_attempt'] = deepcopy(d['last_run']); d['last_candidate_success'] = deepcopy(d['last_run'])
            self.assertEqual(self.validate(d, p)['mode'], 'failed')

    def test_candidate_count_identity_or_provenance_mismatch_blocks(self):
        for change in ('id', 'provenance', 'time', 'unsafe'):
            d, p = self.doc()
            if change == 'id': d['last_run']['candidate_ids'] = []
            if change == 'provenance': p['items']['fixture-new']['observation']['execution_id'] = 'old'
            if change == 'time': p['items']['fixture-new']['collected_at'] = OLD
            if change == 'unsafe': p['items']['fixture-new']['may_publish'] = True
            d['last_run']['candidate_pool_digest'] = store.canonical_digest(p)
            d['last_attempt'] = deepcopy(d['last_run']); d['last_candidate_success'] = deepcopy(d['last_run'])
            self.assertEqual(self.validate(d, p)['mode'], 'failed', change)


class CollectorFixtures(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location('candidate_collector_fixture', ROOT / 'scripts/daiso/collect_daiso.py')
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        return m

    def run_fixture(self, fallback=False, fail=False, corrupt=False):
        m = self.module()
        with tempfile.TemporaryDirectory(dir=ROOT.parent, prefix='candidate-collector-') as temp:
            d = Path(temp); operating = d / 'products.json'
            original = json.dumps({'count': 1, 'products': [observed('operating')], 'updated_at': OLD}).encode('utf-8')
            operating.write_bytes(original)
            (d / 'queue.json').write_text(json.dumps({'items': [queue_row()], 'urls': [BASE + 'fixture-new']}), encoding='utf-8')
            # A prior quota discard in legacy visited must not suppress discovery.
            (d / 'state.json').write_text(json.dumps({'visited': ['fixture-new']}), encoding='utf-8')
            if corrupt: (d / 'pool.json').write_text('{bad', encoding='utf-8')
            paths = dict(OUT_DIR=d, PRODUCTS=operating, STATE=d/'state.json', QUEUE=d/'queue.json',
                         STATUS=d/'status.json', CANDIDATE_POOL=d/'pool.json', CANDIDATE_STATE=d/'observations.json',
                         MAX_ITEMS=1, DISCOVERY_ENABLED=True, OPERATING_UPDATES_ENABLED=False,
                         SEARCH_FALLBACK=fallback, SOURCING_POLICY=d/'no-policy.json',
                         BUCKET_TARGETS={'스킨케어': 1})
            details = observed(); details['collected_at'] = datetime.now(timezone.utc).isoformat()
            with patch.multiple(m, **paths), patch.object(m, 'product_urls_from_sitemap', return_value=[]), \
                 patch.object(m, 'fetch', return_value=(200, 'fixture detail', {})), \
                 patch.object(m, 'parse_product', return_value=None if fallback or fail else details), \
                 patch.object(m, 'classify_bucket', return_value='스킨케어'), \
                 patch.object(m, 'is_excluded', return_value=''), \
                 patch.object(m, 'discovery_exclusion', return_value=''), \
                 patch.object(m, 'search_daiso_product', return_value=(details, {})), \
                 patch.object(m, 'merge_search_fallback', return_value=details), \
                 patch.object(m.time, 'sleep', return_value=None):
                if corrupt:
                    with self.assertRaises(json.JSONDecodeError): m.main()
                    self.assertEqual(operating.read_bytes(), original)
                    return
                self.assertEqual(m.main(), 1 if fail else 0)
            self.assertEqual(operating.read_bytes(), original)
            doc = json.loads((d/'status.json').read_text(encoding='utf-8'))
            if fail:
                self.assertEqual(doc['last_run']['status'], 'failed')
                self.assertFalse((d/'pool.json').exists())
            else:
                self.assertEqual(doc['last_run']['status'], 'candidates_collected')
                self.assertEqual(doc['last_run']['candidates_new'], 1)
                self.assertEqual(doc['last_run']['ok'], 0)
                candidate = json.loads((d/'pool.json').read_text(encoding='utf-8'))['items']['fixture-new']
                self.assertFalse(candidate['may_publish'])
                self.assertEqual(candidate['observation']['execution_id'], doc['last_run']['execution_id'])
                self.assertNotIn('last_success', doc)

    def test_full_bucket_and_legacy_visited_detail_goes_to_candidate_only(self): self.run_fixture()
    def test_search_fallback_cannot_bypass_operating_limit(self): self.run_fixture(fallback=True)
    def test_parse_failure_not_fake_candidate_success(self): self.run_fixture(fail=True)
    def test_malformed_pool_stops_without_overwriting_product_or_history(self): self.run_fixture(corrupt=True)


class WorkflowTests(unittest.TestCase):
    def test_discovery_enabled_operating_updates_disabled_and_narrow_publish(self):
        doc = yaml.safe_load((ROOT/'.github/workflows/daiso-real-collection.yml').read_text(encoding='utf-8'))
        steps = doc['jobs']['collect']['steps']
        collector = next(s for s in steps if s.get('id') == 'collector')
        self.assertEqual(collector['env']['DAISO_DISCOVERY_ENABLED'], '1')
        self.assertEqual(collector['env']['DAISO_OPERATING_UPDATES_ENABLED'], '0')
        publication = next(s for s in steps if s.get('name') == '정상 무변경 관측 metadata 발행')
        self.assertIn("mode == 'candidates'", publication['if'])
        paths = publication['with']['paths'].split()
        for name in ('candidate_pool.json', 'candidate_observations.json', 'candidate_comparison.json'):
            self.assertIn('data/daiso_real/' + name, paths)
        for name in ('products.json', 'shopify_demand_score.json', 'shopify_s_recommendations.json'):
            self.assertNotIn('data/daiso_real/' + name, paths)
        self.assertNotIn('data/shopify_exports', paths)

    def test_candidate_tests_required_by_preflight_and_pages(self):
        for name in ('preflight.yml', 'pages-verified.yml'):
            text = (ROOT/'.github/workflows'/name).read_text(encoding='utf-8')
            self.assertIn('python scripts/test_daiso_candidates.py', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
