"""Synthetic adapter/reader tests. Never presented as live observation replay."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import shopify_readiness_snapshot as adapter

NOW = '2026-10-23T09:00:00Z'


def snapshot():
    return {'shop': {'id': adapter.SHOP_ID, 'myshopifyDomain': adapter.SHOP_DOMAIN, 'currencyCode': 'USD'},
            'captured_at': NOW, 'complete': True, 'scope_verification': 'fixture_only',
            'products': [{'id': 'gid://shopify/Product/1', 'status': 'ACTIVE', 'updatedAt': NOW,
                'hold': {'value': 'DRAFT ONLY: fixture. Zero prices are placeholders', 'updatedAt': '2026-10-18T12:28:34Z'},
                'variants': [{'id': 'gid://shopify/ProductVariant/1', 'price': '21.99',
                    'inventoryPolicy': 'DENY', 'inventoryItem': {'unitCost': None, 'tracked': False,
                        'measurement': {'weight': {'value': 0, 'unit': 'KILOGRAMS'}}}}]}]}


class AdapterTests(unittest.TestCase):
    def test_native_values_stay_native_and_incomplete(self):
        raw = snapshot(); before = copy.deepcopy(raw)
        report = adapter.audit(raw, source='fixture', now=NOW); row = report['variants'][0]
        self.assertEqual(raw, before)
        self.assertEqual(row['facts']['admin_weight_raw']['value']['value'], 0)
        self.assertNotIn('packed_weight_g', row['facts'])
        self.assertNotIn('merchandise_revenue_krw', row['facts'])
        self.assertIsNone(row['economics']['minimum_merchandise_price_krw'])
        self.assertIsNone(row['economics']['verified_actual_fee_rate'])
        self.assertEqual(row['inventory_observation'], 'untracked_not_stockout')
        self.assertIn('admin_positive_price_with_zero_placeholder_hold_claim', row['findings'])
        self.assertIn('hold_source_update_stale_review_required', row['findings'])
        self.assertNotIn('published', row['facts'])

    def test_new_limited_snapshot_never_inherits_old_fields(self):
        raw = snapshot(); raw['shop'].pop('currencyCode')
        raw['products'][0].pop('hold'); raw['products'][0]['variants'][0].pop('inventoryItem')
        row = adapter.audit(raw, source='limited_fixture', now=NOW)['variants'][0]
        for field in ('hold_reason', 'inventory_tracked', 'admin_unit_cost_raw', 'admin_weight_raw'):
            self.assertIsNone(row['facts'][field]['value'])
        self.assertIsNone(row['facts']['admin_price_unconverted']['value']['currencyCode'])
        self.assertNotIn('admin_positive_price_with_zero_placeholder_hold_claim', row['findings'])

    def test_wrong_binding_duplicate_ids_block(self):
        for field, value in (('id','gid://shopify/Shop/9'), ('myshopifyDomain','other.myshopify.com')):
            raw = snapshot(); raw['shop'][field] = value
            with self.assertRaises(ValueError): adapter.normalize(raw, source='fixture')
        raw = snapshot(); raw['products'][0]['variants'] *= 2
        with self.assertRaises(ValueError): adapter.normalize(raw, source='fixture')

    def test_missing_current_s_is_unknown_and_shared_contract_is_reused(self):
        class FixtureClient:
            def __init__(self, **kwargs): pass
            def collect(self): return snapshot()
        with tempfile.TemporaryDirectory() as root:
            kwargs = dict(configured_host=adapter.SHOP_DOMAIN, token='fixture', root=root, now=NOW, client_factory=FixtureClient)
            report = adapter.inspect_readiness(**kwargs)
            self.assertEqual(report['current_s_evidence']['status'], 'unknown')
            self.assertIsNone(report['current_s_evidence']['assessments'])
            path = Path(root)/'data/daiso_real/shopify_s_recommendations.json'
            path.parent.mkdir(parents=True); path.write_text(json.dumps({'recommendations':[{'fixture':True}]}))
            with patch('current_s_eligibility.assess_current', return_value={'fixture':'assessment'}) as assess:
                report = adapter.inspect_readiness(**kwargs)
                assess.assert_called_once_with([{'fixture': True}], root, now=NOW)
            self.assertEqual(report['current_s_evidence']['assessments'], {'fixture':'assessment'})


def page(nodes, more=False, cursor=None):
    return {'nodes': nodes, 'pageInfo': {'hasNextPage': more, 'endCursor': cursor}}


def responses(scopes=('read_products', 'read_inventory')):
    raw = snapshot(); product = copy.deepcopy(raw['products'][0]); variants = product.pop('variants')
    return [{'data': {'shop': raw['shop'], 'currentAppInstallation': {'accessScopes': [{'handle': s} for s in scopes]}}},
            {'data': {'products': page([product])}},
            {'data': {'product': {'id': product['id'], 'updatedAt': NOW, 'variants': page(variants)}}},
            {'data': {'products': page([product])}}]


class ReaderTests(unittest.TestCase):
    def client(self):
        return adapter.ReadOnlyClient(configured_host=adapter.SHOP_DOMAIN, transport_host=adapter.SHOP_DOMAIN, token='fixture')

    def test_full_read_and_existing_write_scope_coverage(self):
        for scopes in (('read_products','read_inventory'), ('write_products','write_inventory')):
            client = self.client()
            with patch.object(client, '_transport', side_effect=responses(scopes)) as transport:
                out = client.collect()
            self.assertEqual(transport.call_count, 4)
            self.assertTrue(out['complete'])
            self.assertEqual(len(out['products'][0]['variants']), 1)
            self.assertNotIn('X-Shopify-Access-Token', json.dumps(out))
            with self.assertRaises(ValueError): client.collect()

    def test_scope_proof_and_exact_shop_required_before_catalog(self):
        for edit in ('scope', 'shop'):
            rows = responses()
            if edit == 'scope': rows[0]['data']['currentAppInstallation'] = None
            else: rows[0]['data']['shop']['id'] = 'gid://shopify/Shop/999'
            client = self.client()
            with patch.object(client, '_transport', side_effect=rows) as transport:
                with self.assertRaises(ValueError): client.collect()
                self.assertEqual(transport.call_count, 1)

    def test_only_allowlisted_queries_and_variables(self):
        client = self.client()
        with patch.object(client, '_transport') as transport:
            for query, variables in [('mutation { productDelete { id } }', {}), (adapter.PRODUCTS_QUERY, {'after': None}), (adapter.BINDING_QUERY, {'after': None})]:
                with self.assertRaises(ValueError): client._query(query, variables)
            transport.assert_not_called()
        with self.assertRaises(ValueError):
            adapter.ReadOnlyClient(configured_host=adapter.SHOP_DOMAIN, transport_host='other.myshopify.com', token='fixture')

    def test_transport_is_host_pinned_post_and_version_checked(self):
        client = self.client()
        with patch.object(adapter, 'https_request', return_value=(200, {'x-shopify-api-version': adapter.API_VERSION}, b'{"data":{}}')) as request:
            client._query(adapter.BINDING_QUERY, {})
        with patch.object(adapter, 'https_request') as blocked:
            with self.assertRaises(ValueError): client._transport('mutation { x }', {})
            blocked.assert_not_called()
        args, kwargs = request.call_args
        self.assertEqual(args[0], 'https://' + adapter.SHOP_DOMAIN + '/admin/api/' + adapter.API_VERSION + '/graphql.json')
        self.assertEqual(kwargs['hosts'], {adapter.SHOP_DOMAIN})
        self.assertEqual(kwargs['method'], 'POST')
        self.assertEqual(kwargs['headers']['X-Shopify-Access-Token'], 'fixture')
        for status, headers in ((302, {}), (200, {}), (200, {'x-shopify-api-version': 'old'})):
            with patch.object(adapter, 'https_request', return_value=(status, headers, b'{"data":{}}')):
                with self.assertRaises(ValueError): self.client()._query(adapter.BINDING_QUERY, {})

    def test_partial_optional_denial_is_unknown_not_zero(self):
        rows = responses(); rows[2]['errors'] = [{'path': ['product','variants','nodes',0,'inventoryItem','unitCost'], 'extensions': {'code':'ACCESS_DENIED'}}]
        rows[2]['data']['product']['variants']['nodes'][0]['inventoryItem']['unitCost'] = {'amount':'12','currencyCode':'USD'}
        client = self.client()
        with patch.object(client, '_transport', side_effect=rows): out = client.collect()
        self.assertIsNone(out['products'][0]['variants'][0]['inventoryItem']['unitCost'])
        self.assertEqual(out['field_errors'], [{'field':'unitCost','reason':'access_denied_unknown'}])
        rows = responses(); rows[2]['errors'] = [{'path':['product','variants'], 'extensions':{'code':'ACCESS_DENIED'}}]
        client = self.client()
        with patch.object(client, '_transport', side_effect=rows):
            with self.assertRaises(ValueError): client.collect()

    def test_duplicate_variant_repeated_cursor_and_page_cap_fail_closed(self):
        for case in ('duplicate', 'cursor', 'cap'):
            rows = responses(); conn = rows[2]['data']['product']['variants']
            if case == 'duplicate': conn['nodes'] *= 2
            else: conn['pageInfo'].update(hasNextPage=True, endCursor='same')
            client = self.client()
            if case == 'cursor': rows.insert(3, copy.deepcopy(rows[2])); rows[3]['data']['product']['variants']['nodes'] = []
            with patch.object(client, '_transport', side_effect=rows), patch.object(adapter, 'MAX_PAGES', 1 if case == 'cap' else 100):
                with self.assertRaises(ValueError): client.collect()

    def test_root_and_variant_pagination_are_complete(self):
        rows = responses(); first = rows[1]['data']['products']['nodes'][0]
        second = copy.deepcopy(first); second['id'] = 'gid://shopify/Product/2'
        v1 = rows[2]['data']['product']['variants']['nodes'][0]
        v2 = copy.deepcopy(v1); v2['id'] = 'gid://shopify/ProductVariant/2'
        v3 = copy.deepcopy(v1); v3['id'] = 'gid://shopify/ProductVariant/3'
        product_pages = [{'data': {'products': page([first], True, 'p2')}}, {'data': {'products': page([second])}}]
        variant_pages = [{'data': {'product': {'id': first['id'], 'updatedAt': NOW, 'variants': page([v1], True, 'v2')}}},
                         {'data': {'product': {'id': first['id'], 'updatedAt': NOW, 'variants': page([v2])}}},
                         {'data': {'product': {'id': second['id'], 'updatedAt': NOW, 'variants': page([v3])}}}]
        client = self.client()
        with patch.object(client, '_transport', side_effect=[rows[0]] + product_pages + variant_pages + product_pages) as transport:
            out = client.collect()
        self.assertEqual([len(p['variants']) for p in out['products']], [2,1])
        self.assertEqual(transport.call_count, 8)

    def test_configured_alias_transport_with_canonical_response(self):
        alias = 'coarfamily.myshopify.com'
        client = adapter.ReadOnlyClient(configured_host=alias, transport_host=alias, token='fixture')
        payloads = responses()
        http = [(200, {'x-shopify-api-version': adapter.API_VERSION}, json.dumps(p).encode()) for p in payloads]
        with patch.object(adapter, 'https_request', side_effect=http) as request:
            out = client.collect()
        self.assertEqual(out['shop']['myshopifyDomain'], adapter.SHOP_DOMAIN)
        for call in request.call_args_list:
            self.assertTrue(call.args[0].startswith('https://' + alias + '/'))
            self.assertEqual(call.kwargs['hosts'], {alias})

    def test_incomplete_snapshot_and_variant_phase_drift_block(self):
        for complete in (None, False, 'true', 1):
            raw = snapshot(); raw['complete'] = complete
            with self.assertRaises(ValueError): adapter.normalize(raw, source='fixture')
        rows = responses(); rows[2]['data']['product']['updatedAt'] = '2026-10-23T10:00:00Z'
        client = self.client()
        with patch.object(client, '_transport', side_effect=rows):
            with self.assertRaisesRegex(ValueError, 'product_changed'): client.collect()
        rows = responses(); rows[1]['data']['products']['nodes'][0].pop('updatedAt')
        client = self.client()
        with patch.object(client, '_transport', side_effect=rows):
            with self.assertRaisesRegex(ValueError, 'updated_at_missing'): client.collect()

    def test_root_drift_fails(self):
        rows = responses(); rows[-1] = copy.deepcopy(rows[-1]); rows[-1]['data']['products']['nodes'][0]['status'] = 'DRAFT'
        client = self.client()
        with patch.object(client, '_transport', side_effect=rows):
            with self.assertRaises(ValueError): client.collect()


if __name__ == '__main__':
    unittest.main()
