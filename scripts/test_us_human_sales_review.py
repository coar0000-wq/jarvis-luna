"""Offline synthetic contracts only; no store, customer, order or analytics data."""
import copy
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

import us_human_sales_review as review


SHOP = {'shop_gid': 'gid://shopify/Shop/1', 'canonical_domain': 'example.test'}
NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
OBSERVED = '2026-10-21T20:00:00+09:00'
PERIOD = {'start': '2026-10-20T00:00:00+09:00', 'end': '2026-10-21T00:00:00+09:00',
          'timezone': 'Asia/Seoul'}


def source_envelope(payload, **extra):
    raw = json.dumps(payload, sort_keys=True).encode()
    doc = {'schema_version': 1, 'shop': copy.deepcopy(SHOP), 'observed_at': OBSERVED,
           'source': {'kind': 'local_snapshot', 'ref': 'synthetic:original:aggregate',
                      'raw_sha256': hashlib.sha256(raw).hexdigest()},
           **extra}
    return doc, raw


def audit_fixture(sessions=10, converted=1):
    queries = {}
    for name, unit in review.METRICS.items():
        value = sessions if name == 'sessions' else converted
        queries[name] = {'status': 'ok', 'coverage': 'complete', 'unit': unit,
                         'shop': copy.deepcopy(SHOP), 'period': copy.deepcopy(PERIOD),
                         'rows': [{'country': 'US', 'traffic': 'human', 'value': value},
                                  {'country': 'US', 'traffic': 'bot', 'value': 500},
                                  {'country': 'KR', 'traffic': 'human', 'value': 700}]}
    return {'shop': copy.deepcopy(SHOP), 'observed_at': OBSERVED,
            'period': copy.deepcopy(PERIOD), 'queries': queries}


def product_fixture():
    return {'shop': copy.deepcopy(SHOP), 'observed_at': OBSERVED,
            'product': {'id': 'gid://shopify/Product/2', 'title': 'Example Capsule Cream',
                        'status': 'ACTIVE'}}


def audit(payload=None, **extra):
    payload = payload if payload is not None else audit_fixture()
    envelope, raw = source_envelope(payload, period=copy.deepcopy(PERIOD))
    envelope.update(extra)
    return review.audit_us_humans(envelope, raw, expected_shop=SHOP, now=NOW)


def wording(payload=None, **extra):
    payload = payload if payload is not None else product_fixture()
    envelope, raw = source_envelope(payload, product_gid='gid://shopify/Product/2',
                                    english_identity_reviewed=True)
    envelope.update(extra)
    return review.wording_review(envelope, raw, expected_shop=SHOP, now=NOW,
                                  banned_terms=['cure', 'whitening', 'free shipping'])


class SalesReviewTest(unittest.TestCase):
    def test_missing_inputs_are_unavailable_not_zero(self):
        result = review.build_review(now=NOW)
        self.assertIsNone(result['measurement']['conversion_rate'])
        self.assertIsNone(result['measurement']['metrics']['sessions']['value'])
        self.assertIsNone(result['copy_review']['wording'])
        self.assertFalse(result['verified'])

    def test_only_us_human_rows_and_session_conversion(self):
        result = audit()
        self.assertEqual(result['metrics']['sessions']['value'], 10)
        self.assertEqual(result['conversion_rate'], 0.1)
        self.assertFalse(result['provenance']['verified'])
        self.assertTrue(result['provenance']['source_bytes_matched'])
        self.assertEqual(result['provenance']['observed_at_kst'], OBSERVED)
        self.assertNotIn('synthetic:original', json.dumps(result))

    def test_zero_denominator_is_null_with_reason(self):
        result = audit(audit_fixture(0, 0))
        self.assertIsNone(result['conversion_rate'])
        self.assertEqual(result['conversion_rate_reason'], 'zero_us_human_sessions')

    def test_zero_conversions_with_positive_denominator_is_zero(self):
        self.assertEqual(audit(audit_fixture(10, 0))['conversion_rate'], 0)

    def test_product_views_failure_not_pageviews_or_zero(self):
        payload = audit_fixture()
        payload['queries']['product_views'] = {'status': 'error', 'value': 0}
        payload['queries']['pageviews']['rows'][0]['value'] = 45
        result = audit(payload)['metrics']
        self.assertEqual(result['pageviews']['value'], 45)
        self.assertIsNone(result['product_views']['value'])
        self.assertEqual(result['product_views']['status'], 'unavailable')

    def test_partial_country_response_cannot_infer_us_zero(self):
        for rows in ([{'country': 'KR', 'traffic': 'human', 'value': 700}],
                     [{'country': 'US', 'traffic': 'human', 'value': 0}]):
            payload = audit_fixture()
            payload['queries']['sessions'].update(coverage='partial', rows=rows)
            result = audit(payload)
            self.assertIsNone(result['metrics']['sessions']['value'])
            self.assertIsNone(result['conversion_rate'])
        payload['queries']['sessions'].update(coverage='complete', rows=[])
        self.assertIsNone(audit(payload)['metrics']['sessions']['value'])

    def test_unknown_or_bot_is_not_human(self):
        for traffic in ('bot', 'unknown'):
            payload = audit_fixture()
            payload['queries']['sessions']['rows'] = [{'country': 'US', 'traffic': traffic, 'value': 9}]
            self.assertIsNone(audit(payload)['metrics']['sessions']['value'])

    def test_funnel_count_exceeds_sessions_is_unavailable(self):
        result = audit(audit_fixture(10, 11))
        for field in ('add_to_cart_sessions', 'checkout_sessions', 'converted_sessions'):
            self.assertEqual(result['metrics'][field]['reason'], 'funnel_count_exceeds_sessions')
        self.assertIsNone(result['conversion_rate'])

    def test_orders_and_pageviews_cannot_be_substituted(self):
        for name, unit in [('converted_sessions', 'orders'), ('product_views', 'pageviews')]:
            payload = audit_fixture()
            payload['queries'][name]['unit'] = unit
            self.assertEqual(audit(payload)['metrics'][name]['reason'], 'metric_unit_mismatch')

    def test_malformed_counts_rows_duplicates_and_pii_fail_closed(self):
        for bad in (True, -1, '0', 1.5, float('nan')):
            payload = audit_fixture()
            payload['queries']['sessions']['rows'][0]['value'] = bad
            self.assertIsNone(audit(payload)['metrics']['sessions']['value'])
        for alteration in ('duplicate', 'pii', 'country'):
            payload = audit_fixture()
            rows = payload['queries']['sessions']['rows']
            if alteration == 'duplicate':
                rows.append(copy.deepcopy(rows[0]))
            elif alteration == 'pii':
                rows[0]['email'] = 'synthetic@example.test'
            else:
                rows[0]['country'] = 'United States'
            result = audit(payload)
            self.assertIsNone(result['metrics']['sessions']['value'])
            self.assertNotIn('synthetic@example.test', json.dumps(result))

    def test_shop_identity_timestamp_and_kst_contract(self):
        for shop in ({'shop_gid': 'gid://shopify/Shop/2', 'canonical_domain': 'example.test'},
                     {'shop_gid': 'gid://shopify/Shop/1', 'canonical_domain': 'other.test'},
                     {'shop_gid': '1', 'canonical_domain': 'example.test'},
                     {'shop_gid': 'gid://shopify/Shop/1', 'canonical_domain': 'https://example.test'}):
            self.assertEqual(audit(shop=shop)['status'], 'unavailable')
        for stamp in ('2026-10-21T20:00:00', '2027-01-01T00:00:00Z', 'nonsense'):
            self.assertEqual(audit(observed_at=stamp)['status'], 'unavailable')
        for period in ({**PERIOD, 'timezone': 'UTC'},
                       {**PERIOD, 'start': '2026-10-20T00:00:00Z'},
                       {**PERIOD, 'end': PERIOD['start']},
                       {**PERIOD, 'end': '2026-10-22T00:00:00+09:00'}):
            self.assertEqual(audit(period=period)['status'], 'unavailable')

    def test_timezone_conversion_overflow_is_unavailable_not_exception(self):
        payload = audit_fixture()
        payload['observed_at'] = '0001-01-01T00:00:00+23:59'
        result = audit(payload, observed_at=payload['observed_at'])
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['conversion_rate_reason'], 'invalid_timestamp_range')

    def test_missing_or_tampered_original_source_never_verified(self):
        envelope, raw = source_envelope(audit_fixture(), period=PERIOD)
        for changed_raw in (None, raw + b' ', b'{}'):
            result = review.audit_us_humans(envelope, changed_raw, expected_shop=SHOP, now=NOW)
            self.assertEqual(result['status'], 'unavailable')
            self.assertFalse(result['verified'])
        for source in ({}, {'ref': '', 'raw_sha256': 'a' * 64}):
            self.assertEqual(audit(source=source)['status'], 'unavailable')
        self.assertEqual(review.audit_us_humans(envelope, raw, now=NOW)['status'], 'unavailable')

    def test_tool_transcription_without_raw_never_becomes_verified(self):
        envelope, _ = source_envelope(audit_fixture(0, 0), period=PERIOD)
        envelope.update(source={'kind': 'source_transcription', 'ref': 'synthetic:tool-response'},
                        transcribed_payload=audit_fixture(0, 0), verified=True, complete=True)
        result = review.audit_us_humans(envelope, expected_shop=SHOP, now=NOW)
        self.assertEqual(result['provenance']['evidence_status'], 'source_transcription')
        self.assertFalse(result['provenance']['source_bytes_matched'])
        self.assertFalse(result['provenance']['verified'])
        self.assertIsNone(result['provenance']['source_sha256'])
        self.assertEqual(result['conversion_rate_reason'], 'zero_us_human_sessions')
        envelope['source']['raw_sha256'] = 'a' * 64
        self.assertEqual(review.audit_us_humans(envelope, expected_shop=SHOP, now=NOW)['status'], 'unavailable')

    def test_country_alias_conflicts_and_completion_flags_do_not_grant_coverage(self):
        for country in ('USA', 'United States', 'us'):
            payload = audit_fixture()
            payload['queries']['sessions']['rows'].append({'country': country, 'traffic': 'human', 'value': 0})
            self.assertIsNone(audit(payload)['metrics']['sessions']['value'])
        payload = audit_fixture()
        query = payload['queries']['sessions']
        query.update(complete=True, verified=True)
        del query['coverage']
        self.assertIsNone(audit(payload, complete=True, verified=True)['metrics']['sessions']['value'])

    def test_original_source_scope_must_match(self):
        for field, value in [('shop', {'shop_gid': 'gid://shopify/Shop/3', 'canonical_domain': 'example.test'}),
                             ('observed_at', '2026-10-20T20:00:00+09:00'),
                             ('period', {**PERIOD, 'timezone': 'UTC'})]:
            payload = audit_fixture()
            payload[field] = value
            self.assertEqual(audit(payload)['status'], 'unavailable')

    def test_period_extension_cannot_leak_customer_records(self):
        payload = audit_fixture()
        period = {**PERIOD, 'private_customer_record': {'email': 'private@example.test', 'order_id': 'secret'}}
        payload['period'] = copy.deepcopy(period)
        result = audit(payload, period=period)
        self.assertEqual(result['status'], 'unavailable')
        for value in ('private@example.test', 'order_id', 'secret', 'private_customer_record'):
            self.assertNotIn(value, json.dumps(result))
        self.assertNotIn('period', result)

    def test_each_query_scope_must_match_and_unknown_fields_fail_closed(self):
        for field, value in [('shop', {**SHOP, 'canonical_domain': 'other.test'}),
                             ('period', {**PERIOD, 'start': '2026-10-19T00:00:00+09:00'}),
                             ('private_customer_record', {'email': 'private@example.test'})]:
            payload = audit_fixture()
            payload['queries']['converted_sessions'][field] = value
            result = audit(payload)
            self.assertIsNone(result['conversion_rate'])
            self.assertIsNone(result['metrics']['converted_sessions']['value'])
            self.assertNotIn('private@example.test', json.dumps(result))
        for field in ('shop', 'period'):
            payload = audit_fixture()
            del payload['queries']['converted_sessions'][field]
            self.assertIsNone(audit(payload)['conversion_rate'])

    def test_active_product_remains_non_executable_review(self):
        result = wording(business_approval=True, publication_allowed=True, verified=True,
                         review_only=False, non_executable=False, eligible_for_shopify_import=True)
        self.assertEqual(result['status'], 'prepared_for_review')
        self.assertEqual(result['product_reference']['observed_status'], 'ACTIVE')
        for flag in ('non_executable', 'review_only'):
            self.assertTrue(result[flag])
        for flag in ('business_approval', 'publication_allowed', 'eligible_for_shopify_import', 'verified'):
            self.assertFalse(result[flag])
        self.assertNotIn('title', result)  # Not an importer row.
        self.assertEqual(result['wording']['search_phrases'], ['Example Capsule Cream'])

    def test_unreviewed_size_or_safety_fields_block_copy_instead_of_silent_omission(self):
        payload = product_fixture()
        for field, value in [('net_contents', '30 ml'), ('warnings', 'Stop use if irritation occurs.'),
                             ('conflicts', ['size_conflict']), ('holds', ['label_review_required']),
                             ('efficacy', 'cure'), ('shipping', 'free shipping')]:
            changed = copy.deepcopy(payload)
            changed['product'][field] = value
            result = wording(changed)
            self.assertIsNone(result['wording'])
            self.assertEqual(result['reason'], 'unreviewed_product_details_or_warnings')
        for field in ('conflicts', 'holds'):
            changed = copy.deepcopy(payload)
            changed[field] = ['unresolved_source_issue']
            self.assertIsNone(wording(changed)['wording'])
            self.assertIsNone(wording(**{field: ['unresolved_input_issue']})['wording'])

    def test_title_quantities_and_claims_need_separate_review(self):
        for title in ('Example Cream 60 ml', 'Example Cream 30g', 'Example Cream 2-pack',
                      'Example Cream 10%', 'Example Cream Pack of 6', 'Example Firming Cream',
                      'Example Hydrating Cream', 'Example Cream Free Shipping'):
            payload = product_fixture()
            payload['product']['title'] = title
            result = wording(payload)
            self.assertIsNone(result['wording'])
            self.assertEqual(result['reason'], 'title_quantity_or_claim_requires_review')
        payload['product'].update(title='Example Cream 60 ml', net_contents='30 ml',
                                  warnings='Do not use on broken skin.')
        self.assertIsNone(wording(payload)['wording'])

    def test_customer_copy_contains_no_internal_review_instructions(self):
        payload = product_fixture()
        result = wording(payload)
        text = json.dumps(result['wording'])
        for term in ('60 ml', 'cure', 'free shipping', 'Face Cream', 'before publication'):
            self.assertNotIn(term, text)
        self.assertEqual(result['wording']['ai_shopping_copy']['usage_scenario'], '')
        self.assertEqual(result['wording']['ai_shopping_copy']['not_recommended_conditions'], '')

    def test_english_product_identity_needs_explicit_review(self):
        for title in ('제품 Cream', '&#67;ream', '<b>Cream</b>', 'Whitening Cream', 'TODO Cream', 'A' * 71):
            payload = product_fixture()
            payload['product']['title'] = title
            self.assertIsNone(wording(payload)['wording'])
        self.assertIsNone(wording(english_identity_reviewed=False)['wording'])
        self.assertIsNone(wording(product_gid='gid://shopify/Product/9')['wording'])

    def test_absent_rules_and_unknown_status_fail_closed(self):
        payload = product_fixture()
        envelope, raw = source_envelope(payload, product_gid='gid://shopify/Product/2',
                                        english_identity_reviewed=True)
        result = review.wording_review(envelope, raw, expected_shop=SHOP, now=NOW)
        self.assertEqual(result['reason'], 'claim_rules_unavailable')
        payload['product']['status'] = 'UNKNOWN'
        self.assertIsNone(wording(payload)['wording'])

    def test_pure_deterministic_inputs_unchanged_and_network_forbidden(self):
        payload = product_fixture()
        envelope, raw = source_envelope(payload, product_gid='gid://shopify/Product/2',
                                        english_identity_reviewed=True)
        before = copy.deepcopy(envelope)
        with patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden')) as connect:
            first = review.build_review(product=envelope, product_source=raw, expected_shop=SHOP,
                                         now=NOW, banned_terms=['cure'])
            second = review.build_review(product=envelope, product_source=raw, expected_shop=SHOP,
                                          now=NOW, banned_terms=['cure'])
        self.assertEqual(first, second)
        self.assertEqual(envelope, before)
        connect.assert_not_called()

    def test_cli_missing_options_and_private_temp_output(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(review.main([]), 0)
        self.assertIsNone(json.loads(stdout.getvalue())['measurement']['conversion_rate'])
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            envelope, raw = source_envelope(audit_fixture(), period=PERIOD)
            (directory / 'input.json').write_text(json.dumps(envelope))
            (directory / 'source.json').write_bytes(raw)
            output = directory / 'review.json'
            argv = ['--audit', str(directory / 'input.json'), '--audit-source', str(directory / 'source.json'),
                    '--shop-gid', SHOP['shop_gid'], '--canonical-domain', SHOP['canonical_domain'],
                    '--output', str(output)]
            with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')) as connect:
                self.assertEqual(review.main(argv), 0)
            connect.assert_not_called()
            report = json.loads(output.read_text())
            self.assertEqual(report['measurement']['conversion_rate'], 0.1)
            self.assertEqual((directory / 'source.json').read_bytes(), raw)
            if os.name == 'posix':
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            original = output.read_bytes()
            with redirect_stderr(io.StringIO()):
                self.assertEqual(review.main(argv), 2)
            self.assertEqual(output.read_bytes(), original)

    def test_cli_rejects_checkout_output_and_duplicate_json_keys(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(review.main(['--output', str(review.ROOT / 'review.json')]), 2)
        with self.assertRaises(ValueError):
            review._decode(b'{"schema_version":1,"schema_version":2}')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'invalid.json'
            path.write_text('[]')
            with redirect_stderr(io.StringIO()):
                self.assertEqual(review.main(['--audit', str(path)]), 2)

    def test_cli_rejects_other_git_checkout_and_worktree_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for kind in ('directory', 'file'):
                checkout = root / kind
                checkout.mkdir()
                marker = checkout / '.git'
                marker.mkdir() if kind == 'directory' else marker.write_text('gitdir: synthetic')
                if kind == 'directory':
                    (marker / 'HEAD').write_text('ref: refs/heads/synthetic')
                output = checkout / 'review.json'
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(review.main(['--output', str(output)]), 2)
                self.assertFalse(output.exists())

    def test_empty_sandbox_git_guard_is_not_a_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.git').mkdir()
            self.assertFalse(review._git_checkout(root))
            self.assertEqual(review.main(['--output', str(root / 'review.json')]), 0)

    @unittest.skipUnless(os.name == 'posix', 'symlink policy test requires POSIX')
    def test_cli_rejects_dangling_loop_and_parent_symlinks_without_traceback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / 'target.json'
            dangling = root / 'dangling.json'
            dangling.symlink_to(target)
            loop1, loop2 = root / 'loop1', root / 'loop2'
            loop1.symlink_to(loop2)
            loop2.symlink_to(loop1)
            actual = root / 'actual'
            actual.mkdir()
            alias = root / 'alias'
            alias.symlink_to(actual, target_is_directory=True)
            for output in (dangling, loop1, alias / 'review.json'):
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    self.assertEqual(review.main(['--output', str(output)]), 2)
                self.assertNotIn('Traceback', stderr.getvalue())
                self.assertNotIn(str(root), stderr.getvalue())
            self.assertFalse(target.exists())
            self.assertFalse((actual / 'review.json').exists())
            (actual / 'source.json').write_text('{}')
            with redirect_stderr(io.StringIO()):
                self.assertEqual(review.main(['--audit', str(alias / 'source.json')]), 2)


if __name__ == '__main__':
    unittest.main()
