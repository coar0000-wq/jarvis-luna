"""Offline knowledge capture provenance regression tests."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('knowledge_capture', ROOT / 'real_knowledge_sync.py')
k = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k)
OLD = '2026-01-01T01:02:03+00:00'
NEW = '2026-10-03T01:02:03+00:00'

class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'data').mkdir()
        self.addCleanup(patch.stopall)
        patch.object(k, 'ROOT', self.root).start()
        patch.object(k, 'DATA_DIR', self.root / 'data' / 'knowledge').start()
        self.clock = patch.object(k, '_capture_time', return_value=NEW).start()
        patch.object(k, 'fetch', side_effect=AssertionError('offline only')).start()

    def artifact(self, name, doc):
        (self.root / 'data' / name).write_text(json.dumps(doc), encoding='utf-8')

    def test_openalex_response_parse_success(self):
        doc = {'results': [{'id': 'W1', 'title': 'Paper', 'primary_location': {'landing_page_url': 'https://arxiv.org/abs/1'}}]}
        with patch.object(k, 'fetch', return_value=json.dumps(doc).encode()):
            out = k.collect_arxiv()
        row = out['items'][0]
        self.assertEqual(row['collected_at'], NEW)
        self.assertEqual(row['id'], 'W1')
        self.assertEqual(row['source_pool'], 'openalex')
        self.assertTrue(row['provenance']['parse_succeeded'])
        self.assertTrue(row['provenance']['response_url'].startswith(k.OPENALEX))

    def test_failed_fetch_parse_and_schema_never_stamp(self):
        for fn in (k.collect_arxiv, k.collect_google):
            for failure in (OSError('offline'), b'invalid', b'{}'):
                self.clock.reset_mock()
                kwargs = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure}
                with patch.object(k, 'fetch', **kwargs):
                    out = fn()
                self.assertEqual(out['status'], 'failed')
                self.assertEqual(out['items'], [])
                self.assertNotIn('collected_at', out)
                self.assertEqual(out['provenance']['captures'], [])
                self.clock.assert_not_called()

    def test_google_partial_success_dates_only_success(self):
        xml = b'<rss><channel><item><title>Article</title><link>https://example.test/a</link></item></channel></rss>'
        with patch.object(k, 'fetch', side_effect=[xml, OSError('offline'), b'bad']):
            out = k.collect_google()
        self.assertEqual(len(out['items']), 1)
        self.assertEqual(len(out['provenance']['captures']), 1)
        self.assertEqual(out['items'][0]['collected_at'], NEW)
        self.assertEqual(out['items'][0]['source_pool'], 'google_news')
        self.assertTrue(out['reason'])
        self.clock.assert_called_once()

    def test_robotics_no_generated_clock_alias(self):
        self.artifact('robotics_sources.json', {'generated_at': NEW, 'updated': NEW,
            'sources': {'arxiv': {'items': [{'title': 'Old', 'collected_at': OLD, 'id': 'R1'}, {'title': 'Unknown', 'generated_at': NEW}]},
                        'rss': {'items': [{'title': 'Captured', 'captured_at': OLD}]}}})
        out = k.collect_robotics()
        self.assertEqual(out['items'][0]['collected_at'], OLD)
        self.assertEqual(out['items'][0]['id'], 'R1')
        self.assertNotIn('collected_at', out['items'][1])
        self.assertEqual(out['items'][2]['captured_at'], OLD)
        self.assertEqual(out['capture_summary']['state'], 'partial')
        self.assertNotIn('collected_at', out)
        self.clock.assert_not_called()

    def test_institutions_exact_pool_and_retained_clocks(self):
        self.artifact('institution_sources.json', {'collected_at': NEW, 'generated_at': NEW,
            'sources': {'rss': {'status': 'ok', 'collected_at': NEW}, 'sitemap': {'status': 'failed', 'collected_at': NEW}},
            'items': [{'title': 'Pool', 'source': 'rss', 'org': 'Org', 'url': 'u'},
                      {'title': 'Retained', 'source': 'rss', 'collected_at': OLD},
                      {'title': 'Missing', 'source': 'sitemap'}, {'title': 'Root only', 'source': 'openalex'}]})
        out = k.collect_institutions()
        self.assertEqual(out['items'][0]['collected_at'], NEW)
        self.assertEqual(out['items'][0]['provenance']['timestamp_scope'], 'source_pool')
        self.assertEqual(out['items'][0]['org'], 'Org')
        self.assertEqual(out['items'][1]['collected_at'], OLD)
        for row in out['items'][2:]:
            self.assertNotIn('collected_at', row)
        self.clock.assert_not_called()

    def test_retail_no_channel_or_assembly_clock_alias(self):
        self.artifact('dashboard_runtime.json', {'updated': NEW,
            'global_channels_status': {'Store': {'collected_at': NEW}},
            'global_channels': {'Store': [{'product': 'Old', 'collected_at': OLD, 'product_id': 'P1', 'url': 'u'},
                                        {'product': 'Unknown'}, {'product': 'Captured', 'captured_at': OLD}]}})
        out = k.collect_us_beauty()
        self.assertEqual(out['items'][0]['collected_at'], OLD)
        self.assertEqual(out['items'][0]['product_id'], 'P1')
        self.assertEqual(out['items'][0]['source_pool'], 'Store')
        self.assertNotIn('collected_at', out['items'][1])
        self.assertEqual(out['items'][2]['captured_at'], OLD)
        self.clock.assert_not_called()

    def test_mixed_clock_source_not_stamped(self):
        out = k._capture_summary({'items': [{'collected_at': OLD}, {'captured_at': NEW}]})
        self.assertEqual(out['capture_summary']['state'], 'mixed')
        self.assertNotIn('collected_at', out)

    def test_catalog_not_external_capture(self):
        out = k.collect_organic_skincare()
        self.assertEqual(len(out['items']), len(k.ORGANIC_SKINCARE_CATALOG))
        self.assertFalse(out['provenance']['external_capture'])
        for row, original in zip(out['items'], k.ORGANIC_SKINCARE_CATALOG):
            self.assertNotIn('collected_at', row)
            self.assertNotIn('captured_at', row)
            self.assertEqual(row['evidence_type'], 'catalog_registration')
            self.assertEqual(row['product_id'], original['product_id'])
            self.assertEqual(row['url'], original['url'])
            self.assertIn('registered_at', row)
        self.assertIn('assembled_at', out)
        payload = json.loads((k.DATA_DIR / 'organic_skincare_products.json').read_text())
        self.assertIn('generated_at', payload)
        self.assertNotIn('collected_at', payload['items'][0])
        k.fetch.assert_not_called()

if __name__ == '__main__':
    unittest.main()
