"""Offline regression tests for collector startup and truthful job outcomes."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import urllib.error

import collect_via_gemini as c


class CollectorTests(unittest.TestCase):
    def test_url_model_override_wins(self):
        with patch.dict(os.environ, {'GEMINI_URL_MODEL': ' explicit-url-model '}), patch.object(c, 'discover_model') as discover:
            self.assertEqual(c.pick_model('unused')[0], 'explicit-url-model')
            discover.assert_not_called()

    def test_blank_override_discovers_model(self):
        with patch.dict(os.environ, {'GEMINI_URL_MODEL': ' '}), patch.object(c, 'discover_model', return_value=('listed-model', 'listed')) as discover:
            self.assertEqual(c.pick_model('key')[0], 'listed-model')
            discover.assert_called_once_with('key')

    def test_listing_model_override_does_not_leak(self):
        models = {'models': [{'name': 'models/url-flash', 'supportedGenerationMethods': ['generateContent']}]}
        with patch.dict(os.environ, {'GEMINI_URL_MODEL': '', 'GEMINI_MODEL': 'listing-only'}), patch.object(c, 'http_json', return_value=models) as request:
            self.assertEqual(c.pick_model('synthetic')[0], 'url-flash')
            self.assertEqual(request.call_count, 1)

    def run_collector(self, key='test', responses=None, discovery_error=None):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'report.json'
            with patch.object(c, 'OUT', out), patch.object(c, 'ROOT', Path(folder)), patch.object(c, 'MODEL', ''), patch.dict(os.environ, {'GEMINI_API_KEY': key}), patch.object(c, 'pick_model', return_value=('test-model', 'test'), side_effect=discovery_error), patch.object(c, 'call', side_effect=responses) as call, patch.object(c.time, 'sleep'):
                code = c.main()
                report = json.loads(out.read_text())
            return code, report, call.call_count

    def test_missing_key_writes_current_failure_without_calls(self):
        code, report, calls = self.run_collector(key='')
        self.assertEqual((code, report['total'], calls), (1, 0, 0))
        self.assertTrue(all(x['status'] == 'failed' for x in report['channels'].values()))

    def test_discovery_error_writes_failure_without_exposing_secret(self):
        code, report, calls = self.run_collector(discovery_error=RuntimeError('url?key=secret'))
        self.assertEqual((code, calls), (1, 0))
        self.assertNotIn('secret', json.dumps(report))

    def test_partial_success_is_failure(self):
        row = [{'product': 'Product', 'brand': 'Brand', 'price_usd': 12}]
        code, report, calls = self.run_collector(responses=[(row, '', ''), ([], 'HTTP 403', '')])
        self.assertEqual((code, report['total'], calls), (1, 1, 2))

    def test_all_channels_success(self):
        row = [{'product': 'Product', 'brand': 'Brand', 'price_usd': 12}]
        code, report, calls = self.run_collector(responses=[(row, '', ''), (row, '', '')])
        self.assertEqual((code, report['total'], calls), (0, 2, 2))

    def test_failed_attempt_preserves_historical_success_separately(self):
        old = {'generated_at': '2026-09-13T00:00:00Z', 'channels': {
            'ulta_beauty': {'status': 'ok', 'products': [{'product': 'Old real product'}], 'count': 1}}}
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'report.json'
            out.write_text(json.dumps(old))
            with patch.object(c, 'OUT', out), patch.object(c, 'ROOT', Path(folder)), patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
                self.assertEqual(c.main(), 1)
                self.assertEqual(c.main(), 1)
            report = json.loads(out.read_text())
        self.assertEqual(report['channels']['ulta_beauty']['products'], [])
        self.assertEqual(report['last_successful_channels']['ulta_beauty']['observed_at'], old['generated_at'])
        self.assertEqual(report['last_successful_channels']['ulta_beauty']['products'][0]['product'], 'Old real product')

    def test_malformed_previous_channels_do_not_block_failure_report(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'report.json'
            out.write_text(json.dumps({'channels': ['malformed']}))
            with patch.object(c, 'OUT', out), patch.object(c, 'ROOT', Path(folder)), patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
                self.assertEqual(c.main(), 1)
            self.assertEqual(json.loads(out.read_text())['channels']['ulta_beauty']['status'], 'failed')

    def test_http_403_is_not_retried(self):
        error = urllib.error.HTTPError('https://provider.example', 403, 'Forbidden', {}, None)
        with patch.object(c.urllib.request, 'urlopen', side_effect=error) as request, patch.object(c.time, 'sleep') as sleep:
            rows, reason, status = c.call('synthetic', 'https://target.example')
        self.assertEqual(rows, [])
        self.assertIn('HTTP 403', reason)
        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()

    def test_blocked_url_metadata_cannot_publish_model_rows(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'steps': [
            {'type': 'url_context_result', 'result': [{'status': 'paywall'}]},
            {'type': 'model_output', 'content': [{'type': 'text', 'text': '[{"product": "Invented", "price_usd": 10}]'}]},
        ]}).encode()
        with patch.object(c.urllib.request, 'urlopen', return_value=response):
            rows, reason, status = c.call('synthetic', 'https://target.example')
        self.assertEqual(rows, [])
        self.assertIn('blocked', reason)

    def test_workflow_propagates_collection_failure_after_publication(self):
        workflow = (Path(c.__file__).resolve().parents[1] / '.github/workflows/gemini-web-collect.yml').read_text()
        self.assertIn('id: collect', workflow)
        self.assertIn("if: always() && steps.collect.outcome != 'success'", workflow)
        self.assertLess(workflow.index('uses: ./.github/actions/publish'), workflow.index('name: Fail when collection failed'))
        self.assertNotIn("steps.guard.outputs.ready", workflow)


if __name__ == '__main__':
    unittest.main()
