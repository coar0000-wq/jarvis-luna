"""Offline real-schema adapters, no repository outputs or network."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import jarvis_watch as watch

NOW = '2026-10-04T07:10:00+00:00'
LATER = '2026-10-04T07:11:00+00:00'


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value), encoding='utf-8')

    def observed(self, previous=None, now=NOW):
        return watch.observe(self.root, previous, now=now)

    def row(self, result, team):
        return next(v for v in result['watchers'] if v['source_team'] == team)

    def robotics(self, a=NOW, b=NOW):
        return {'generated_at': LATER, 'sources': {
            'arxiv': {'status': 'ok', 'items': [{'url': 'https://example.test/a', 'title': 'A', 'collected_at': a}]},
            'rss': {'status': 'ok', 'items': [{'url': 'https://example.test/b', 'title': 'B', 'collected_at': b}]}}}

    def listing_inputs(self):
        legal = {'items': {'1': {'canonical_product_id': 'CP000001', 'pd_no': '1', 'complete': False}}}
        recs = {'recommendations': []}
        self.put('data/legal_full.json', legal)
        self.put('data/daiso_real/shopify_s_recommendations.json', recs)
        paths = ('data/product_master.json','data/gosi.json','data/daiso_real/daiso_us_labels.json',
                 'data/pricing_model.json','data/legal_products.json','data/daiso_real/shopify_s_recommendations.json',
                 'data/shopify_listing_copy.json','data/shopify_shortlist.json','data/legal_full.json',
                 'data/mocra_readiness.json','data/manual/legal_rp_status.json','data/manual/mocra_business.json',
                 'data/manual/official_label_text.json','data/manual/mocra_adverse_event_sop.md')
        hashes = {}
        for relative in paths:
            try:
                document = json.loads((self.root / relative).read_text())
                evidence = {'status': 'present', 'document': watch._semantic_gate(document)}
            except (OSError, ValueError):
                evidence = {'status': 'missing_or_unreadable'}
            hashes[relative] = watch.digest(evidence)
        gate = {'items': [{'canonical_product_id': 'CP000001','pd_no': '1','ready': False}],
                'agent_input_signature': {'schema_version': 2, 'semantic_sources': hashes,
                                          'recommendations_sha256': watch.digest([])}}
        self.put('data/listing_gate.json', gate)
        return gate, legal

    def shortlist(self):
        self.put('data/shopify_shortlist.json', {'active_pd_nos': ['1','2']})
        self.put('data/product_master.json', {'products': [
            {'pd_no':'1','canonical_product_id':'CP000001'},
            {'pd_no':'2','canonical_product_id':'CP000002'}]})
        rows = [{'pd_no': str(n), 'canonical_product_id': 'CP00000'+str(n), 'price_krw': n*1000,
                 'source': {'collected_at': NOW,'capture_kind':'successful_http_parse'},
                 'provenance': {'http_status':200,'parse_status':'exact_pd_no_numeric_price',
                                'robots_checked':True,'response_sha256':'a'*64}} for n in (1,2)]
        doc = {'schema_version':1,'scope':'active_shopify_shortlist_only','operating_catalog_mutated':False,
               'expected_ids':['CP000001','CP000002'],'status':'complete','complete':True,'products':rows}
        self.put(watch.SHORTLIST_OBSERVATIONS, doc)
        return doc

    def test_institution_org_association_identity(self):
        self.put('data/institution_sources.json', {'collected_at':NOW,'items':[
            {'org':'A','url':'https://example.test/work'}, {'org':'B','url':'https://example.test/work'}]})
        w = self.row(self.observed(),'institutions')
        self.assertEqual(w['status'],'BASELINE')
        self.assertEqual(len(w['source_entity_ids']),2)
        self.assertTrue(all(v.startswith('org-url:') for v in w['source_entity_ids']))

    def test_institution_provider_failure_is_partial_even_with_fresh_records(self):
        import jarvis_operations as core
        import jarvis_recovery as recovery
        doc = {'sources': {'sitemap': {'status':'ok','collected_at':NOW,
                    'failures':[{'org':'ASML','reason':'No dated matching records'}]}},
               'items':[{'org':'Other','source':'sitemap','url':'https://example.test/work'}]}
        self.put('data/institution_sources.json', doc)
        w = self.row(self.observed(),'institutions')
        self.assertEqual(w['status'],'PARTIAL')
        self.assertEqual(w['coverage']['fresh_records'],1)
        self.assertEqual(w['coverage']['failed_sources'],1)
        state = core.empty_state()
        recovery.reconcile(state,[w],now=NOW)
        episode = next(iter(state['source_recovery']['episodes'].values()))
        self.assertEqual(episode['status'],'WAITING_SOURCE_RECOVERY')
        self.assertEqual(episode['attempts'],0)

    def test_institution_failed_provider_retained_without_false_removal(self):
        doc = {'sources': {'sitemap': {'status':'ok','collected_at':NOW,'failures':[]}},
               'items':[{'org':o,'source':'sitemap','url':'https://example.test/'+o}
                        for o in ('ASML','Other')]}
        self.put('data/institution_sources.json',doc)
        first = self.observed()
        doc['sources']['sitemap']['failures'] = [{'org':'ASML'}]
        doc['items'] = doc['items'][1:]
        self.put('data/institution_sources.json',doc)
        partial = self.observed(first['state'],LATER)
        self.assertEqual(self.row(partial,'institutions')['status'],'PARTIAL')
        self.assertEqual(len(partial['state']['sources']['institutions']['records']),2)
        self.assertFalse([e for e in partial['events'] if e['source_team']=='institutions'])
        doc['sources']['sitemap']['failures'] = []
        doc['items'].append({'org':'ASML','source':'sitemap','url':'https://example.test/ASML'})
        self.put('data/institution_sources.json',doc)
        recovered = self.observed(partial['state'],LATER)
        self.assertEqual(self.row(recovered,'institutions')['status'],'NO_CHANGE')
        self.assertFalse([e for e in recovered['events'] if e['source_team']=='institutions'])

    def test_institution_failed_retained_rows_never_refresh_capture(self):
        self.put('data/institution_sources.json',{
            'sources': {'sitemap': {'status':'ok','collected_at':LATER,'failures':[{'org':'ASML'}]}},
            'items':[{'org':'ASML','source':'sitemap','url':'https://example.test/a'},
                     {'org':'Other','source':'sitemap','url':'https://example.test/b'}]})
        w = self.row(self.observed(now=LATER),'institutions')
        self.assertEqual(w['status'],'PARTIAL')
        self.assertEqual(w['coverage']['fresh_records'],1)
        self.assertEqual(w['coverage']['failed_sources'],1)
        self.assertEqual(w['coverage']['missing_records'],1)

    def test_real_duplicate_same_org_blocks(self):
        item = {'org':'A','url':'https://example.test/work'}
        self.put('data/institution_sources.json', {'collected_at':NOW,'items':[item,item]})
        self.assertEqual(self.row(self.observed(),'institutions')['blockers'],['DUPLICATE_SOURCE_ENTITY_ID'])

    def test_nested_items_are_observed_not_aggregate_summary(self):
        doc = self.robotics()
        self.put('data/robotics_sources.json',doc)
        first = self.observed()
        self.assertEqual(len(first['state']['sources']['robotics']['records']),2)
        doc['sources']['arxiv']['items'][0].update(title='Changed',collected_at=LATER)
        self.put('data/robotics_sources.json',doc)
        out = self.observed(first['state'],LATER)
        self.assertEqual(len(out['events']),1)
        self.assertEqual(out['events'][0]['source_team'],'robotics')

    def test_generated_only_robotics_never_capture(self):
        self.put('data/robotics_sources.json',self.robotics(None,None))
        self.assertEqual(self.row(self.observed(),'robotics')['status'],'BLOCKED')

    def test_knowledge_aggregate_clock_not_item_capture(self):
        self.put('data/knowledge/real_sources.json',{'sources':{'arxiv':{
            'collected_at':NOW,'items':[{'url':'https://example.test/work'}]}}})
        self.assertEqual(self.row(self.observed(),'knowledge')['status'],'BLOCKED')

    def test_registered_catalog_is_not_fresh_source(self):
        self.put('data/knowledge/real_sources.json',{'sources':{
            'organic_skincare':{'source':'organic_skincare_catalog','items':[
                {'url':'https://example.test/brand','product_id':'1','collected_at':NOW},
                {'url':'https://example.test/brand','product_id':'2','collected_at':NOW}]},
            'google':{'items':[{'url':'https://example.test/news','collected_at':NOW}]}}})
        w = self.row(self.observed(),'knowledge')
        self.assertEqual(w['status'],'BASELINE')
        self.assertEqual(w['coverage']['catalog_only'],2)
        self.assertEqual(w['coverage']['fresh_records'],1)

    def test_same_work_across_queries_has_routing_identity_not_duplicate(self):
        self.put('data/knowledge/real_sources.json',{'sources':{'google':{'items':[
            {'url':'https://example.test/work','query':'A','collected_at':NOW},
            {'url':'https://example.test/work','query':'B','collected_at':NOW}]}}})
        self.assertEqual(self.row(self.observed(),'knowledge')['status'],'BASELINE')

    def test_partial_missing_is_not_removed_and_keeps_cursor(self):
        doc = self.robotics()
        self.put('data/robotics_sources.json',doc)
        first = self.observed()
        doc['sources']['rss']['items'][0]['collected_at'] = None
        self.put('data/robotics_sources.json',doc)
        out = self.observed(first['state'])
        self.assertEqual(self.row(out,'robotics')['status'],'PARTIAL')
        self.assertEqual(out['events'],[])
        self.assertEqual(len(out['state']['sources']['robotics']['records']),2)

    def test_failed_empty_pool_is_not_a_removal_or_readdition(self):
        doc = self.robotics()
        self.put('data/robotics_sources.json', doc)
        first = self.observed()
        doc['sources']['arxiv'] = {'status':'failed','items':[]}
        self.put('data/robotics_sources.json', doc)
        partial = self.observed(first['state'])
        self.assertEqual(partial['events'], [])
        self.assertEqual(len(partial['state']['sources']['robotics']['records']), 2)
        self.put('data/robotics_sources.json', self.robotics())
        self.assertEqual(self.observed(partial['state'])['events'], [])

    def test_unidentified_unobserved_imports_are_partial_not_duplicated_entities(self):
        self.put('data/knowledge/real_sources.json', {'sources':{
            'google':{'items':[{'url':'https://example.test/a','collected_at':NOW}]},
            'us_beauty':{'items':[{'url':'','title':'unobserved A'},{'url':'','title':'unobserved B'}]}}})
        w = self.row(self.observed(), 'knowledge')
        self.assertEqual(w['status'], 'PARTIAL')
        self.assertEqual(w['coverage']['fresh_records'], 1)
        self.assertEqual(w['coverage']['missing_records'], 2)

    def test_partial_fresh_real_change_only(self):
        doc = self.robotics()
        self.put('data/robotics_sources.json',doc)
        first = self.observed()
        doc['sources']['rss']['items'][0]['collected_at'] = None
        doc['sources']['arxiv']['items'][0].update(title='Changed',collected_at=LATER)
        self.put('data/robotics_sources.json',doc)
        out = self.observed(first['state'],LATER)
        self.assertEqual(len(out['events']),1)
        self.assertEqual(out['events'][0]['change']['kind'],'updated')

    def test_any_future_row_denies_source(self):
        self.put('data/robotics_sources.json',self.robotics(NOW,'2027-01-01T00:00:00+00:00'))
        self.assertEqual(self.row(self.observed(),'robotics')['blockers'],['SOURCE_CAPTURE_IN_FUTURE'])

    def test_failed_probe_retained_clock_not_new_source_event(self):
        doc = {'candidates':[{'key':'x','url':'https://example.test/x','verdict':'ok','collected_at':NOW,'probe_status':'ok'},
                             {'key':'y','url':'https://example.test/y','verdict':'ok','collected_at':NOW,'probe_status':'ok'}]}
        self.put('data/channel_candidates.json',doc)
        first = self.observed()
        doc['candidates'][0].update(probe_status='failed',verdict='blocked')
        self.put('data/channel_candidates.json',doc)
        out = self.observed(first['state'])
        self.assertEqual(self.row(out,'channels')['status'],'PARTIAL')
        self.assertEqual(out['events'],[])

    def test_failed_nested_provider_is_partial_not_recovered(self):
        doc = self.robotics()
        doc['sources']['rss']['source_results'] = {'feed':{'status':'failed','last_attempt':{'status':'failed'}}}
        self.put('data/robotics_sources.json',doc)
        self.assertEqual(self.row(self.observed(),'robotics')['status'],'PARTIAL')

    def test_local_derived_clock_is_not_external_capture(self):
        self.listing_inputs()
        for team in ('listing','legal'):
            w = self.row(self.observed(),team)
            self.assertEqual(w['status'],'LOCAL_VERIFIED')
            self.assertIsNone(w['captured_at'])
            self.assertEqual(w['observed_at'],NOW)
            self.assertEqual(w['observation_kind'],'local_derived_read')

    def test_local_dependency_tamper_blocks(self):
        _, legal = self.listing_inputs()
        legal['items']['1']['complete'] = True
        self.put('data/legal_full.json',legal)
        for team in ('listing','legal'):
            self.assertEqual(self.row(self.observed(),team)['blockers'],['DERIVED_DEPENDENCY_SIGNATURE_MISSING_OR_STALE'])

    def test_shortlist_observation_scope_and_prices(self):
        self.shortlist()
        out = self.observed()
        for team in ('sourcing','pricing'):
            w = self.row(out,team)
            self.assertEqual(w['status'],'BASELINE')
            self.assertEqual(w['scope'],'active_shopify_shortlist_only')
            self.assertEqual(w['coverage']['fresh_records'],2)

    def test_retained_fresh_prices_after_failed_attempt_not_healthy(self):
        doc = self.shortlist()
        doc.update(status='partial',complete=False,failed_ids=['CP000001'])
        self.put(watch.SHORTLIST_OBSERVATIONS,doc)
        for team in ('sourcing','pricing'):
            self.assertEqual(self.row(self.observed(),team)['status'],'PARTIAL')

    def test_shortlist_missing_expected_member_is_partial(self):
        doc = self.shortlist()
        doc['products'].pop()
        self.put(watch.SHORTLIST_OBSERVATIONS,doc)
        self.assertEqual(self.row(self.observed(),'pricing')['status'],'PARTIAL')

    def test_unknown_scope_or_provenance_is_blocked(self):
        for edit in ('scope','proof','id'):
            doc = self.shortlist()
            if edit == 'scope': doc['expected_ids'] = ['CP000001']
            if edit == 'proof': doc['products'][0]['provenance']['robots_checked'] = False
            if edit == 'id': doc['products'][0]['pd_no'] = '999'
            self.put(watch.SHORTLIST_OBSERVATIONS,doc)
            self.assertEqual(self.row(self.observed(),'pricing')['status'],'BLOCKED')

    def test_root_safe_source_rejects_escape(self):
        with self.assertRaises(ValueError):
            watch._safe_source(self.root,'../outside.json')


if __name__ == '__main__':
    unittest.main()
