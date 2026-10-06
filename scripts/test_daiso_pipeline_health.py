from copy import deepcopy
import json
import unittest
import sys
from pathlib import Path as _ScriptPath
sys.path.insert(0,str(_ScriptPath(__file__).resolve().parents[1]))
from scripts import daiso_pipeline_health as h

NOW = '2026-10-03T03:00:00Z'

class HealthTests(unittest.TestCase):
    def setUp(self):
        self.failed = {'id': 10, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'failure', 'created_at': '2026-10-03T00:00:00Z', 'run_started_at': '2026-10-03T00:00:00Z', 'finished_at': '2026-10-03T01:00:00Z'}
        self.workflow = {'workflows': {h.WORKFLOW: {'latest_attempt': self.failed, 'metadata_verified': True}}}
        self.run = {'execution_id': '11:1:collect', 'status': 'ok', 'collector_version': 2, 'collector_completed': True, 'requested': 1, 'ok': 1, 'parse_failed': 0, 'http_error': 0, 'started_at': '2026-10-03T02:00:00Z', 'finished_at': '2026-10-03T02:10:00Z'}
        self.doc = {k: deepcopy(self.run) for k in ('last_run', 'last_attempt', 'last_success')}
        self.raw = json.dumps(self.doc).encode()
        self.receipt = {'source': 'github_actions', 'workflow': h.WORKFLOW, 'scope': 'operating_capture', 'run_id': 11, 'run_attempt': 1, 'job': 'collect', 'execution_id': '11:1:collect', 'started_at': '2026-10-03T02:00:00Z', 'finished_at': '2026-10-03T02:10:00Z', 'completed': True, 'outcome': 'success', 'source_sha256': h.sha(self.raw)}

    def evaluate(self, receipt=None, validate=True, **kwargs):
        r = receipt or self.receipt
        return h.evaluate(self.doc, self.workflow, now=NOW, collection_status_bytes=self.raw,
                          receipts=[r], validated_receipt_sha256=[h.receipt_sha256(r)] if validate else [], **kwargs)

    def test_github_second_precision_is_half_open_and_capped_at_now(self):
        bound = '2026-10-03T02:00:00Z'
        now = h.timestamp('2026-10-03T02:00:01Z')
        self.assertTrue(h.github_not_after('2026-10-03T02:00:00.999999Z', bound, now))
        self.assertFalse(h.github_not_after('2026-10-03T02:00:01Z', bound, now))
        self.assertFalse(h.github_not_after('2026-10-03T02:00:00.999999Z', bound, h.timestamp('2026-10-03T02:00:00.5Z')))
        self.assertFalse(h.github_not_after(bound, '2026-10-03T02:00:01Z', h.timestamp(bound)))
        self.assertFalse(h.github_not_after('2026-10-03T02:00:00.000001Z', '2026-10-03T02:00:00.000000Z', now))
        with self.assertRaises(ValueError):
            h.github_not_after(bound, None, now)

    def test_created_metadata_inversion_is_bounded_not_a_clock_rewrite(self):
        run = dict(self.failed, created_at='2026-10-03T00:00:01Z')
        before = deepcopy(run)
        start, end = h.run_window(run, h.timestamp(NOW))
        self.assertEqual(start, h.timestamp(run['run_started_at']))
        self.assertEqual(run, before)
        self.assertEqual(h.run_metadata_precision(run)['created_start_inversion_seconds'], 1)
        for patch in ({'created_at': '2026-10-03T00:00:02Z'},
                      {'created_at': '2026-10-03T00:00:01.000001Z'},
                      {'created_at': None}, {'finished_at': '2026-10-03T03:00:01Z'},
                      {'run_started_at': '2026-10-03T03:00:01Z'}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                h.run_window(dict(run, **patch), h.timestamp(NOW))

    def test_new_proved_collection_does_not_clear_full_failure(self):
        value = self.evaluate()
        self.assertEqual(value['scopes']['operating_capture']['status'], 'success')
        self.assertEqual(value['status'], 'failed')
        self.assertFalse(value['failed_workflow_history'][0]['superseded'])
        self.assertFalse(value['public_authority'])

    def test_unverified_mismatch_attempt_future_fail_closed(self):
        for patch in ({'run_attempt': 2}, {'run_id': 12}, {'finished_at': '2027-01-01T00:00:00Z'}, {'source_sha256': '0' * 64}):
            receipt = dict(self.receipt, **patch)
            self.assertEqual(self.evaluate(receipt)['scopes']['operating_capture']['status'], 'unverified')
        self.assertEqual(self.evaluate(validate=False)['scopes']['operating_capture']['status'], 'unverified')

    def test_latest_unverified_and_old_collection_refused(self):
        self.workflow['workflows'][h.WORKFLOW]['metadata_verified'] = False
        self.assertEqual(self.evaluate()['scopes']['operating_capture']['status'], 'unverified')
        self.workflow['workflows'][h.WORKFLOW]['metadata_verified'] = True
        self.workflow['workflows'][h.WORKFLOW]['latest_attempt']['finished_at'] = '2026-10-03T02:30:00Z'
        self.assertEqual(self.evaluate()['scopes']['operating_capture']['status'], 'unverified')

    def test_price_capture_never_recovers_workflow(self):
        price = {'scope': 'active_shopify_shortlist_only', 'complete': True, 'operating_catalog_mutated': False, 'expected_ids': ['CP1'], 'products': [{'canonical_product_id': 'CP1', 'price_krw': 3000, 'source': {'collected_at': '2026-10-03T02:00:00Z', 'capture_kind': 'successful_http_parse'}, 'provenance': {'http_status': 200, 'parse_status': 'exact_pd_no_numeric_price', 'response_sha256': 'a' * 64}}]}
        value = self.evaluate(shortlist_price=price)
        self.assertEqual(value['scopes']['shortlist_price']['status'], 'success')
        self.assertEqual(value['status'], 'failed')

    def test_only_genuinely_newer_same_scope_publication_receipt_supersedes(self):
        full = dict(self.receipt, collection_scope=h.DAILY_SCOPE, scope='overall_workflow', publication_completed=True, workflow_conclusion='success')
        value = self.evaluate(full, validated_failure_scopes={(10, 1): h.DAILY_SCOPE})
        self.assertEqual(value['status'], 'success')
        self.assertTrue(value['failed_workflow_history'][0]['superseded'])
        self.assertEqual(self.evaluate(full)['status'], 'failed')
        tiny = dict(full, collection_scope=dict(h.DAILY_SCOPE, requested=1))
        self.assertEqual(self.evaluate(tiny, validated_failure_scopes={(10, 1): h.DAILY_SCOPE})['status'], 'failed')
        for patch in ({'scope': 'shortlist_price'}, {'started_at': '2026-10-03T00:30:00Z'}, {'publication_completed': False}):
            self.assertEqual(self.evaluate(dict(full, **patch))['status'], 'failed')

if __name__ == '__main__':
    unittest.main()
