#!/usr/bin/env python3
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml
import check_release_quality as q

ROOT = Path(__file__).resolve().parents[1]


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT.parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.docs = {
            'config/quality_policy.yml': {'schema_version':1,'max_fx_age_days':4},
            'data/daiso_real/products.json': {'count':1,'products':[{'pd_no':'1','name':'fixture','price_krw':1000,'url':'https://example.invalid/1'}]},
            'data/product_master.json': {'schema_version':3,'active_product_count':1,'pd_no_to_cp':{'1':'CP1'},'products':[{'pd_no':'1','canonical_product_id':'CP1','grade':'A','shopify_score':70}]},
            'data/daiso_real/shopify_demand_score.json': {'total_products':1,'grade_summary':{'A':1},'all_scored':[{'pd_no':'1','shopify_score':70,'grade':'A'}]},
            'data/pricing_model.json': {'exchange_rate':{'usd_to_krw':1300,'as_of':datetime.now(timezone.utc).date().isoformat(),'source':'https://example.invalid/fx'},'offers_by_product':{'single':[{'pd_no':'1','qty':1,'price_usd':10,'unit_price_usd':10,'landed_cost_total_usd':2,'fee_usd':1,'net_profit_usd':7,'margin_pct':70}],'bundle':[{'pd_no':'1','qty':2,'price_usd':20,'unit_price_usd':10,'landed_cost_total_usd':4,'fee_usd':2,'net_profit_usd':14,'margin_pct':70}]}},
            'data/dashboard_runtime.json': {'schema_version':1,'teams':[{'id':'sourcing','summary':'1개 상품'}]},
        }
        self.save()

    def save(self):
        for name, doc in self.docs.items():
            p = self.root/name; p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')

    def check(self, **kwargs):
        self.save()
        return q.check(self.root, architecture=False, **kwargs)

    def test_valid_snapshot_passes_candidate_and_final(self):
        for phase in ('candidate','final'):
            self.assertTrue(self.check(phase=phase)['publish_allowed'])

    def test_missing_and_malformed_master_fail_closed(self):
        for raw in (None, '{bad'):
            p = self.root/'data/product_master.json'
            if raw is None: p.unlink(missing_ok=True)
            else: p.write_text(raw)
            self.assertFalse(q.check(self.root, architecture=False)['publish_allowed'])
            self.save()

    def test_duplicate_id_and_join_mismatch_fail(self):
        self.docs['data/daiso_real/products.json']['products'].append(deepcopy(self.docs['data/daiso_real/products.json']['products'][0]))
        self.assertFalse(self.check()['publish_allowed'])

    def test_score_range_grade_count_and_master_value_fail(self):
        for field, value in (('shopify_score',101),('shopify_score',True),('grade','S')):
            old = deepcopy(self.docs)
            self.docs['data/daiso_real/shopify_demand_score.json']['all_scored'][0][field] = value
            self.assertFalse(self.check()['publish_allowed'])
            self.docs = old

    def test_wrong_cost_arithmetic_and_fx_fail(self):
        for change in ('profit','fx','future','stale'):
            old = deepcopy(self.docs)
            p = self.docs['data/pricing_model.json']
            if change == 'profit': p['offers_by_product']['single'][0]['net_profit_usd'] = 100
            if change == 'fx': p['exchange_rate']['usd_to_krw'] = 0
            if change == 'future': p['exchange_rate']['as_of'] = '2099-01-01'
            if change == 'stale': p['exchange_rate']['as_of'] = '2000-01-01'
            self.assertFalse(self.check()['publish_allowed'], change)
            self.docs = old

    def test_named_fx_provider_requires_matching_actual_input_endpoint_and_time(self):
        fx=self.docs['data/pricing_model.json']['exchange_rate'];fx['source']='ExchangeRate-API'
        cached=dict(fx,api_url='https://open.er-api.com/v6/latest/USD',ok=True,
                    fetched_at=datetime.now(timezone.utc).isoformat())
        self.docs['data/daiso_real/collection_status.json']={'fx':cached}
        self.assertTrue(self.check()['publish_allowed'])
        for key,value in [('usd_to_krw',999),('api_url','https://example.invalid/forged'),
                          ('ok',False),('fetched_at','2099-01-01T00:00:00+00:00')]:
            with self.subTest(key=key):
                self.docs['data/daiso_real/collection_status.json']['fx']=dict(cached,**{key:value})
                self.assertFalse(self.check()['publish_allowed'])
        self.docs['data/daiso_real/collection_status.json']['fx']=cached

    def test_runtime_count_mismatch_fails(self):
        self.docs['data/dashboard_runtime.json']['teams'][0]['summary'] = '0개 상품'
        self.assertFalse(self.check()['publish_allowed'])

    def test_candidate_identity_cannot_leak_operating(self):
        self.docs['data/daiso_real/candidate_pool.json'] = {'items':{'1':{}},'approval_required':True,'may_publish':False,'may_replace_operating_products':False}
        self.assertFalse(self.check()['publish_allowed'])

    def test_operating_removal_requires_verified_reason(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as old:
            p=Path(old)/'data/daiso_real/products.json';p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'products':[{'pd_no':'1'},{'pd_no':'2'}]}))
            self.assertFalse(self.check(baseline=old)['publish_allowed'])
            self.docs['data/daiso_real/product_change_reasons.json']={'changes':[{'pd_no':'2','action':'exclude','verified':True,'reason':'policy exclusion','source':'fixture-approved-policy'}]}
            self.assertFalse(self.check(baseline=old)['publish_allowed'])
            with patch.object(q, 'removal_evidence', return_value=(True, [])) as validator:
                self.assertTrue(self.check(baseline=old)['publish_allowed'])
                validator.assert_called_once_with(self.root, old, {'2'})

    def test_current_outcome_must_match_runtime(self):
        report=self.root/'results.json'
        doc={'schema_version':1,'execution_id':'test:1','status':'degraded','publish_allowed':True,'required_failures':[],'optional_failures':['youtube'],'evidence_errors':[]}
        report.write_text(json.dumps(doc))
        self.assertFalse(self.check(collector_report=report, execution_id='test:1')['publish_allowed'])
        self.docs['data/dashboard_runtime.json']['pipeline_health']={'execution_id':'test:1','status':'degraded','required_failure_count':0,'optional_failure_count':1,'evidence_error_count':0}
        result=self.check(collector_report=report, execution_id='test:1')
        self.assertTrue(result['publish_allowed'])
        self.assertEqual(result['status'],'warning')
        self.assertFalse(self.check(collector_report=report, execution_id='test:2')['publish_allowed'])


class WorkflowTests(unittest.TestCase):
    def test_core_synthetic_collectors_not_run(self):
        text=(ROOT/'.github/workflows/JARVIS-Core-Automation.yml').read_text(encoding='utf-8')
        self.assertNotIn('python scripts/google_search_data_collection.py',text)
        self.assertNotIn('python scripts/obsidian_realtime_sync.py',text)
        self.assertIn('--skip-reason',text)
        self.assertIn('--expected canonical_source:required',text)
        self.assertLess(text.index('Required candidate release quality'),text.index('uses: ./.github/actions/publish'))

    def test_deep_outcomes_gate_precedes_publish_no_post_publish_threshold(self):
        text=(ROOT/'.github/workflows/JARVIS-Deep-Analysis.yml').read_text(encoding='utf-8')
        self.assertLess(text.index('Aggregate actual Deep outcomes'),text.index('uses: ./.github/actions/publish'))
        self.assertNotIn('failed_steps.txt || true',text)
        self.assertNotIn('if [ "$count" -ge 5 ]',text)
        self.assertIn('--collector-report data/agents/deep_run_results.json',text)

    def test_workflows_parse_and_have_explicit_quality_conditions(self):
        for name in ('JARVIS-Core-Automation.yml','JARVIS-Deep-Analysis.yml'):
            doc=yaml.safe_load((ROOT/'.github/workflows'/name).read_text(encoding='utf-8'))
            steps=next(iter(doc['jobs'].values()))['steps']
            publication=next(s for s in steps if s.get('uses')=='./.github/actions/publish')
            self.assertIn("outcome == 'success'",publication['if'])


if __name__ == '__main__': unittest.main(verbosity=2)
