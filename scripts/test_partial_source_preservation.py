"""Offline regressions for Deep 39315235823 and SerpApi 39340538828."""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import collect_institutions as inst
from scripts import collect_serpapi_youtube as yt
from scripts import collector_snapshot_history as guard
from scripts import generate_dashboard_runtime as runtime
from scripts import build_error_report as errors
POLICY = json.loads((ROOT / 'config/publish_policy.json').read_text())
OLD, NEW = '2026-10-03T01:00:00+00:00', '2026-10-20T01:00:00+00:00'


def item(source='openalex', org='Org', suffix='old', feed=''):
    return {'source': source, 'org': org, 'category': 'AI',
            'kind': '논문' if source == 'openalex' else '발표물',
            'url': 'https://example.test/' + suffix, 'title': suffix,
            'date': '2026-10-01', 'feed': feed}


def prior():
    return {'collected_at': OLD, 'total': 2, 'organizations': 1,
            'by_org': {'Org': 2}, 'by_category': {'AI': 2},
            'by_kind': {'논문': 1, '발표물': 1}, 'not_collected': {},
            'sources': {s: {'status': 'ok', 'count': 1, 'collected_at': OLD, 'failures': []}
                        for s in ('rss', 'openalex')},
            'items': [item(), item('rss', suffix='rss', feed='https://example.test/rss')]}


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch('urllib.request.urlopen', side_effect=AssertionError('NETWORK FORBIDDEN')).start()
        patch('time.sleep').start()

    def assert_guard(self, rel, previous, current):
        guard.allowed_removals(rel, previous, current, POLICY)

    def test_failed_papers_preserved_while_rss_refreshes(self):
        previous = prior()
        fresh = item('rss', suffix='new', feed='https://example.test/rss')
        failure = inst.failure('Org', 'https://api.openalex.org/works?secret=hidden',
                               exc=urllib.error.HTTPError('url', 403, 'secret text', None, None))
        out = inst.merge_attempt(previous, {'rss': ([fresh], []), 'openalex': ([], [failure])}, NEW)
        self.assertEqual(out['status'], 'partial')
        self.assertEqual((out['total'], out['fresh_count'], out['retained_count']), (2, 1, 1))
        paper = next(r for r in out['items'] if r['source'] == 'openalex')
        self.assertEqual(paper['url'], previous['items'][0]['url'])
        self.assertEqual(paper['collected_at'], OLD)
        self.assertEqual(out['collected_at'], OLD)
        self.assertEqual(out['sources']['openalex']['status'], 'failed')
        self.assertEqual(out['sources']['rss']['collected_at'], NEW)
        self.assertEqual(out['by_kind'], {'발표물': 1, '논문': 1})
        self.assert_guard('data/institution_sources.json', previous, out)
        repeated = inst.merge_attempt(out, {'rss': ([fresh], []), 'openalex': ([], [failure])}, NEW)
        self.assertEqual(repeated['items'], out['items'])
        self.assert_guard('data/institution_sources.json', out, repeated)
        recovered = inst.merge_attempt(out, {'openalex': ([item(suffix='recovered')], [])}, NEW)
        self.assertEqual(recovered['sources']['openalex']['status'], 'ok')
        self.assertEqual(recovered['sources']['openalex']['collected_at'], NEW)
        self.assertEqual(recovered['failure_count'], 0)
        self.assert_guard('data/institution_sources.json', out, recovered)

    def test_each_org_and_feed_has_independent_retention(self):
        a, b = item('rss', suffix='a', feed='https://example.test/a'), item('rss', suffix='b', feed='https://example.test/b')
        previous = {'collected_at': OLD, 'items': [a, b, item(org='Second')],
                    'sources': {s: {'status': 'ok', 'collected_at': OLD} for s in ('rss', 'openalex')}}
        fresh = {**a, 'url': 'https://example.test/new-a'}
        out = inst.merge_attempt(previous, {'rss': ([fresh], [inst.failure('Org', b['feed'], reason='empty')])}, NEW)
        self.assertEqual({r['url'] for r in out['items']}, {fresh['url'], b['url'], previous['items'][2]['url']})
        self.assertEqual(out['sources']['rss']['status'], 'partial')
        self.assertEqual(out['retained_count'], 2)
        self.assertEqual(out['collected_at'], OLD)

    def test_all_failures_do_not_refresh_clocks_or_return_success(self):
        path = self.root / 'inst.json'; path.write_text(json.dumps(prior()))
        bad = [inst.failure('Org', 'https://api.openalex.org/works', reason='empty')]
        with patch.object(inst, 'OUT', path), patch.object(sys, 'argv', ['collector', '--only=openalex']), \
                patch.object(inst, 'collect_openalex', return_value=([], bad)), patch.object(inst, 'collect_rss') as rss, \
                patch.object(inst, 'now', return_value=NEW), redirect_stdout(io.StringIO()):
            self.assertEqual(inst.main(), 1)
        rss.assert_not_called()
        out = json.loads(path.read_text())
        self.assertEqual(out['collected_at'], OLD)
        self.assertEqual(out['status'], 'failed')
        self.assertEqual(out['total'], 2)
        self.assertEqual(out['sources']['rss'], prior()['sources']['rss'])
        self.assert_guard('data/institution_sources.json', prior(), out)

    def test_partial_institution_exit_does_not_claim_full_collection_success(self):
        path = self.root / 'partial.json'; path.write_text(json.dumps(prior()))
        bad = [inst.failure('Org', 'https://api.openalex.org/works', reason='HTTPError')]
        fresh = item('rss', suffix='new', feed='https://example.test/rss')
        with patch.object(inst, 'OUT', path), patch.object(sys, 'argv', ['collector']), \
                patch.object(inst, 'collect_openalex', return_value=([], bad)), \
                patch.object(inst, 'collect_rss', return_value=([fresh], [])), \
                patch.object(inst, 'collect_sitemap', return_value=([], [])), \
                patch.object(inst, 'now', return_value=NEW), redirect_stdout(io.StringIO()):
            self.assertEqual(inst.main(), 1)
        out = json.loads(path.read_text())
        self.assertEqual(out['status'], 'partial')
        self.assertEqual(out['fresh_count'], 1)
        self.assertEqual(out['retained_count'], 1)
        self.assertEqual(out['sources']['openalex']['collected_at'], OLD)
        self.assert_guard('data/institution_sources.json', prior(), out)

    def test_http_diagnostics_are_sanitized_and_status_is_not_guessed(self):
        bad = inst.failure('Org', 'https://user:password@api.openalex.org/works?api_key=secret#fragment',
                           exc=urllib.error.HTTPError('url', 429, 'secret response', None, None))
        self.assertEqual(bad['http_status'], 429)
        self.assertEqual(bad['url'], 'https://api.openalex.org/works')
        self.assertEqual(bad['reason'], 'HTTPError: HTTP 429')
        self.assertNotIn('secret', json.dumps(bad))
        unknown = inst.failure('Org', 'https://api.openalex.org/works', exc=RuntimeError('secret'))
        self.assertIsNone(unknown['http_status'])
        self.assertEqual(unknown['reason'], 'RuntimeError')

    def test_real_published_snapshot_keeps_all_failed_openalex_papers(self):
        previous = json.loads((ROOT / 'data/institution_sources.json').read_text())
        papers = [r for r in previous['items'] if r['source'] == 'openalex']
        failures = [inst.failure(org, 'https://api.openalex.org/works', reason='HTTPError')
                    for org in dict.fromkeys(r['org'] for r in papers)]
        rss = [r for r in previous['items'] if r['source'] == 'rss']
        sitemap = [r for r in previous['items'] if r['source'] == 'sitemap']
        out = inst.merge_attempt(previous, {'rss': (rss, []), 'sitemap': (sitemap, []), 'openalex': ([], failures)}, NEW)
        self.assertEqual(out['by_kind']['논문'], len(papers))
        self.assertEqual(out['total'], len(previous['items']))
        self.assertEqual(out['sources']['openalex']['collected_at'], previous['sources']['openalex']['collected_at'])
        self.assert_guard('data/institution_sources.json', previous, out)

    def test_unknown_legacy_capture_is_never_invented(self):
        out = inst.merge_attempt({'items': [item()], 'sources': {}}, {'openalex': ([], [{'org': 'Org'}])}, NEW)
        self.assertIsNone(out['items'][0]['collected_at'])
        self.assertIsNone(out['collected_at'])
        self.assertIsNone(out['sources']['openalex']['collected_at'])

    def test_failed_pool_or_root_only_clock_is_not_capture_evidence(self):
        for sources in ({}, {'openalex': {'status': 'failed', 'collected_at': OLD}}):
            previous = {'collected_at': OLD, 'items': [item()], 'sources': sources}
            out = inst.merge_attempt(previous, {'openalex': ([], [{'org': 'Org'}])}, NEW)
            self.assertIsNone(out['items'][0]['collected_at'])
            self.assertIsNone(out['sources']['openalex']['collected_at'])
            self.assertIsNone(out['collected_at'])
            repeated = inst.merge_attempt(out, {'openalex': ([], [{'org': 'Org'}])}, NEW)
            self.assertIsNone(repeated['items'][0]['collected_at'])

    def test_youtube_workflow_reports_tolerated_failure_after_publication(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/serpapi-market.yml').read_text())
        steps = workflow['jobs']['collect']['steps']
        youtube = next(step for step in steps if step.get('id') == 'youtube')
        self.assertTrue(youtube['continue-on-error'])
        final = next(step for step in steps if step.get('name') == '앞 단계 실패 확인')
        self.assertIn('steps.youtube.outcome', final['run'])
        self.assertLess(next(i for i, step in enumerate(steps) if step.get('uses') == './.github/actions/publish'), steps.index(final))

    def test_partial_status_reaches_corpus_dashboard_and_error_report(self):
        doc = inst.merge_attempt(prior(), {'openalex': ([], [inst.failure('Org', 'https://api.openalex.org/works', reason='HTTP 403')])}, NEW)
        (self.root / 'data').mkdir(); (self.root / 'data/institution_sources.json').write_text(json.dumps(doc))
        spec = importlib.util.spec_from_file_location('partial_knowledge', ROOT / 'real_knowledge_sync.py')
        knowledge = importlib.util.module_from_spec(spec); spec.loader.exec_module(knowledge)
        with patch.object(knowledge, 'ROOT', self.root):
            source = knowledge.collect_institutions()
        self.assertEqual(source['status'], 'failed')
        self.assertTrue(all(r['collected_at'] == OLD for r in source['items']))
        with patch.object(runtime, 'ROOT', self.root):
            card = next(c for c in runtime.team_cards({}) if c['id'] == 'institutions')
        self.assertEqual(card['status'], 'warning')
        self.assertEqual(card['when'], OLD)
        self.assertIn('실패 1건', card['summary'])
        with patch.object(errors, 'DATA', self.root / 'data'), patch.object(errors, 'OUT', self.root / 'errors.json'), redirect_stdout(io.StringIO()):
            self.assertEqual(errors.main(), 0)
        report = json.loads((self.root / 'errors.json').read_text())
        self.assertTrue(any(r['item'] == 'openalex: Org' and r['reason'] == 'HTTP 403' for r in report['items']))

    def youtube_run(self, previous, queries, query_set, *, responses=None, key='test'):
        path, ledger = self.root / 'youtube.json', self.root / 'usage.json'
        path.write_text(json.dumps(previous))
        calls = responses if responses is not None else [({'video_results': [{'video_id': str(i), 'title': 'serum', 'link': f'https://youtube.com/watch?v={i}'}]}, 'ok') for i in range(len(queries))]
        with patch.object(yt, 'OUT', path), patch.object(yt, 'LEDGER', ledger), patch.object(yt, 'QUERIES', queries), \
                patch.object(yt, 'QUERY_SET', query_set), patch.dict(yt.os.environ, {'SERPAPI_KEY': key}), \
                patch.object(yt, 'call', side_effect=calls) as call, redirect_stdout(io.StringIO()):
            code = yt.main()
        return code, json.loads(path.read_text()), call.call_count

    def test_marketing_demand_rotation_keeps_query_identity_and_exact_history(self):
        previous = json.loads((ROOT / 'data/youtube_serpapi.json').read_text())
        code, demand, calls = self.youtube_run(previous, yt.DEMAND_QUERIES, 'demand')
        self.assertEqual(code, 0); self.assertEqual(calls, 5)
        self.assertTrue(set(previous['queries']).issubset(demand['queries']))
        self.assertEqual(demand['query_history'][0]['snapshot'], previous)
        self.assertEqual([r['query'] for r in demand['calls'] if r['current']], yt.DEMAND_QUERIES)
        self.assertEqual(demand['video_count'], len(demand['videos']))
        self.assert_guard('data/youtube_serpapi.json', previous, demand)
        _, marketing, _ = self.youtube_run(demand, yt.MARKETING_QUERIES, 'marketing')
        self.assertEqual(marketing['query_history'][:1], demand['query_history'])
        self.assertEqual(marketing['query_history'][-1]['snapshot'], {k: v for k, v in demand.items() if k != 'query_history'})
        self.assert_guard('data/youtube_serpapi.json', demand, marketing)
        for record in marketing['query_history']:
            encoded = json.dumps(record['snapshot'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            self.assertEqual(record['id'], hashlib.sha256(encoded.encode()).hexdigest())
        bad = deepcopy(marketing); bad['queries'].remove(previous['queries'][0])
        with self.assertRaises(ValueError):
            self.assert_guard('data/youtube_serpapi.json', marketing, bad)
        bad = deepcopy(marketing); bad['query_history'].pop(0)
        with self.assertRaises(ValueError):
            self.assert_guard('data/youtube_serpapi.json', marketing, bad)

    def test_youtube_partial_failure_and_no_key_have_truthful_current_results(self):
        previous = {'generated_at': OLD, 'queries': ['old'], 'query_set': 'legacy',
                    'videos': [{'url': 'https://example.test/old'}], 'video_count': 1,
                    'bucket_mentions': {'메이크업': 1}, 'ingredient_mentions': {'cica': 1},
                    'calls': [{'query': 'old', 'note': 'ok'}]}
        responses = [({'video_results': [{'video_id': 'new', 'title': 'serum', 'link': 'https://example.test/new'}]}, 'ok'), (None, 'HTTPError: HTTP 429')]
        code, partial, _ = self.youtube_run(previous, ['a', 'b'], 'demand', responses=responses)
        self.assertEqual(code, 1); self.assertEqual(partial['status'], 'partial')
        self.assertEqual(partial['failed_query_count'], 1)
        self.assertEqual(partial['bucket_mentions']['메이크업'], 0)
        self.assertEqual(partial['ingredient_mentions']['cica'], 0)
        self.assertEqual(next(c for c in partial['calls'] if c['query'] == 'old')['attempted_at'], OLD)
        self.assert_guard('data/youtube_serpapi.json', previous, partial)
        code, missing, calls = self.youtube_run(partial, ['a', 'b'], 'demand', key='')
        self.assertEqual((code, calls, missing['status'], missing['video_count']), (1, 0, 'no_key', 0))
        self.assertEqual(missing['query_history'][0]['snapshot'], previous)
        self.assert_guard('data/youtube_serpapi.json', partial, missing)
        _, recovered, _ = self.youtube_run(missing, ['a', 'b'], 'demand')
        self.assertEqual(recovered['status'], 'ok')
        self.assertEqual(recovered['reason'], '')
        self.assert_guard('data/youtube_serpapi.json', missing, recovered)

    def test_exact_snapshot_manifest_accepts_preservation_without_policy_change(self):
        from scripts.publish_transaction import deletion_authorized
        old_inst = prior()
        new_inst = inst.merge_attempt(old_inst, {
            'rss': ([item('rss', suffix='new', feed='https://example.test/rss')], []),
            'openalex': ([], [inst.failure('Org', 'https://api.openalex.org/works', reason='HTTPError')])}, NEW)
        old_yt = {'generated_at': OLD, 'queries': ['old query'], 'videos': [{'url': 'https://example.test/old'}],
                  'video_count': 1, 'calls': [{'query': 'old query', 'note': 'ok'}]}
        _, new_yt, _ = self.youtube_run(old_yt, ['new query'], 'demand')
        (self.root / 'config').mkdir(); (self.root / 'data').mkdir()
        (self.root / 'config/publish_policy.json').write_text(json.dumps(POLICY))
        for rel, old, new in [('data/institution_sources.json', old_inst, new_inst),
                              ('data/youtube_serpapi.json', old_yt, new_yt)]:
            base = json.dumps(old).encode()
            (self.root / rel).write_text(json.dumps(new))
            with patch.object(guard, 'head_bytes', return_value=base):
                result = guard.update(self.root, [rel])
            self.assertTrue(result[rel].startswith('authorized '))
            manifest = json.loads((self.root / guard.MANIFEST).read_text())
            entry = next(r for r in manifest['deletions'] if r['path'] == rel)
            self.assertTrue(deletion_authorized(rel, base, entry['ids'], manifest,
                                               replacement=(self.root / rel).read_bytes()))

    def test_corrupt_previous_snapshot_is_not_overwritten(self):
        for module in (inst, yt):
            path = self.root / 'bad.json'; path.write_text('{broken')
            with patch.object(module, 'OUT', path), patch.object(sys, 'argv', ['collector']):
                with self.assertRaises(json.JSONDecodeError): module.main()
            self.assertEqual(path.read_text(), '{broken')



class DiagnosticAccuracyTests(unittest.TestCase):
    def report(self, inputs):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, payload in inputs.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(payload))
            with patch.object(errors, 'DATA', root), patch.object(errors, 'OUT', root / 'out.json'), redirect_stdout(io.StringIO()):
                self.assertEqual(errors.main(), 0)
            return json.loads((root / 'out.json').read_text())

    def test_label_fields_have_distinct_evidence_guidance(self):
        fields = ['내용량', '전성분', '제품 정체 표시', '책임자 이름·주소', '새 필드']
        result = self.report({'legal_export_prep.json': {'사람이_채워야_하는_칸': fields}})
        rows = result['사람_대기']
        self.assertEqual(len(rows), len(fields))
        self.assertEqual(len({r['reason'] for r in rows}), len(fields))
        self.assertIn('수량과 단위', rows[0]['fix'])
        self.assertIn('전성분 원문', rows[1]['fix'])
        self.assertIn('제품명·용도', rows[2]['fix'])
        self.assertIn('제조사와 동일하다고 추정하지 않는다', rows[3]['fix'])
        self.assertIn('원본 근거', rows[4]['fix'])
        for row in rows[:3]:
            self.assertNotIn('MoCRA 책임자', row['reason'])

    def test_existing_hard_blocks_remain_and_guidance_is_not_clearance(self):
        blockers = list(errors.LEGAL_BLOCKER_GUIDANCE) + ['unknown_check']
        products = {key: {'name': key, 'hard_block': True,
                         'hard_block_reason': 'original ' + key,
                         'auto_blockers': [key]} for key in blockers}
        products['fallback'] = {'name': 'fallback', 'hard_block': True,
                                'hard_block_reason': 'manual reason'}
        products['checks_only'] = {'name': 'checks_only', 'hard_block': True,
                                   'auto_checks': {'actual_label_review': {'ok': False}}}
        products['pass'] = {'name': 'pass', 'hard_block': False}
        original = deepcopy(products)
        result = self.report({'legal_products.json': {'items': products}})
        rows = result['items']
        self.assertEqual(len(rows), len(products) - 1)
        self.assertTrue(all(r['kind'] == errors.BLOCKED for r in rows))
        self.assertTrue(all('차단 유지, 자동 승인 없음' in r['fix'] for r in rows))
        self.assertTrue(all('Drug Facts' not in r['fix'] for r in rows))
        self.assertEqual(products, original)
        by_name = {r['item']: r for r in rows}
        self.assertIn('unknown_check', by_name['unknown_check']['fix'])
        self.assertIn('actual_label_review', by_name['checks_only']['fix'])
        self.assertEqual(by_name['label_fields']['reason'], 'original label_fields')

    def test_legacy_store_wait_does_not_claim_absent_store(self):
        result = self.report({'brand_kit.json': {'사람이_해야_하는_것': [
            'Shopify 스토어 개설 (계정·도메인)', '정책 페이지의 회사명·주소·연락처 기입']}})
        self.assertEqual(len(result['사람_대기']), 2)
        store = result['사람_대기'][0]
        self.assertEqual(store['item'], 'Shopify 스토어 연결·기본 설정 상태 확인')
        self.assertIn('미개설로 단정하지 않음', store['reason'])
        self.assertEqual(store['kind'], errors.WAITING)

    def test_brand_generator_does_not_infer_account_creation_needed(self):
        from scripts import prepare_brand_kit as brand
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'brand.json'
            with patch.object(brand, 'OUT', out), patch.object(brand, 'load', return_value={}), redirect_stdout(io.StringIO()):
                self.assertEqual(brand.main(), 0)
            payload = json.loads(out.read_text())
        self.assertNotIn('Shopify 스토어 개설 (계정·도메인)', payload['사람이_해야_하는_것'])
        self.assertIn('Shopify 스토어 연결·기본 설정 상태 확인 (계정·도메인)', payload['사람이_해야_하는_것'])
        self.assertIn('완료 여부를 확인하지 않는다', payload['왜'])

if __name__ == '__main__':
    unittest.main()
