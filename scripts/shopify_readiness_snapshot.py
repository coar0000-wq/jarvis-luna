"""Read-only Admin snapshot adapter; private evidence is never auto-published."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from shopify_readiness_audit import project, _time
from apply_reviewed_product_gallery import API_VERSION, MAX_PAGES, https_request, strict_json, json_bytes

SHOP_ID = 'gid://shopify/Shop/82748997889'
SHOP_DOMAIN = 'rb3zh1-i1.myshopify.com'
CONFIGURED_HOSTS = frozenset({SHOP_DOMAIN, 'coarfamily.myshopify.com'})


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def normalize(snapshot, *, source):
    """Retain native observations. No FX, packed-weight or public inference."""
    require(isinstance(snapshot, dict) and isinstance(snapshot.get('shop'), dict), 'shop_missing')
    require(snapshot['shop'].get('id') == SHOP_ID, 'shop_identity_mismatch')
    require((snapshot['shop'].get('myshopifyDomain') == SHOP_DOMAIN), 'shop_domain_mismatch')
    require(isinstance(source, str) and source.strip(), 'source_required')
    require(isinstance(snapshot.get('products'), list), 'products_missing')
    require(snapshot.get('complete') is True, 'complete_snapshot_required')
    stamp = snapshot.get('captured_at')
    sha = hashlib.sha256(json.dumps(snapshot, sort_keys=True, allow_nan=False).encode()).hexdigest()
    rows, ids, products = [], set(), set()
    for product in snapshot['products']:
        pid = product.get('id')
        require(isinstance(pid, str) and re.fullmatch(r'gid://shopify/Product/[1-9]\d*', pid)
                and pid not in products, 'product_identity_invalid')
        products.add(pid)
        require(isinstance(product.get('variants'), list), 'variants_missing')
        for variant in product['variants']:
            vid = variant.get('id')
            require(isinstance(vid, str) and re.fullmatch(r'gid://shopify/ProductVariant/[1-9]\d*', vid)
                    and vid not in ids, 'variant_identity_invalid')
            ids.add(vid)
            item = variant.get('inventoryItem') or {}
            def fact(value, field):
                return {'value': deepcopy(value), 'source': source, 'source_sha256': sha,
                        'captured_at': (snapshot.get('variant_captured_at') or {}).get(vid, stamp),
                        'product_id': pid, 'variant_id': vid, 'source_field': field,
                        'verification': 'snapshot_observation_only'}
            facts = {
                'inventory_tracked': fact(item.get('tracked'), 'inventoryItem.tracked'),
                'inventory_quantity': fact(variant.get('inventoryQuantity'), 'inventoryQuantity'),
                'inventory_policy': fact(variant.get('inventoryPolicy'), 'inventoryPolicy'),
                'admin_unit_cost_raw': fact(item.get('unitCost'), 'inventoryItem.unitCost'),
                'admin_weight_raw': fact((item.get('measurement') or {}).get('weight'), 'inventoryItem.measurement.weight'),
                'admin_price_unconverted': fact({'amount': variant.get('price'),
                    'currencyCode': snapshot['shop'].get('currencyCode')}, 'price/shop.currencyCode'),
                'hold_reason': fact((product.get('hold') or {}).get('value'), 'hold.value'),
                'admin_online_store_url': fact(product.get('onlineStoreUrl'), 'onlineStoreUrl'),
                'admin_status': fact(product.get('status'), 'status')}
            facts['hold_reason']['source_updated_at'] = (product.get('hold') or {}).get('updatedAt')
            rows.append({'variant_id': vid, 'facts': facts})
    return {'variants': rows}


def audit(snapshot, *, source, now):
    report = project(normalize(snapshot, source=source), now=now)
    report['capture_context'] = {k: deepcopy(snapshot.get(k)) for k in
        ('scope_verification', 'api_version', 'captured_at', 'complete', 'field_errors')}
    report['capture_context']['integration'] = 'local_read_only_adapter_not_scheduled'
    return report


def inspect_readiness(*, configured_host, token, root, now=None, client_factory=None):
    """Private memory-only report; callers must redact before publishing."""
    from current_s_eligibility import assess_current
    client = (client_factory or ReadOnlyClient)(configured_host=configured_host,
        transport_host=configured_host, token=token)
    snapshot = client.collect()
    clock = now or datetime.now(timezone.utc).isoformat()
    report = audit(snapshot, source='authenticated_admin_readiness_snapshot', now=clock)
    path = Path(root) / 'data/daiso_real/shopify_s_recommendations.json'
    try:
        doc = strict_json(path.read_bytes())
        rows = doc.get('recommendations') if isinstance(doc, dict) else None
    except (OSError, ValueError, UnicodeError):
        rows = None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        report['current_s_evidence'] = {'status': 'unknown', 'reason': 'canonical_rows_missing_or_invalid', 'assessments': None}
    else:
        report['current_s_evidence'] = {'status': 'assessed' if rows else 'no_canonical_rows',
            'source': str(path), 'contract': 'current_s_eligibility.assess_current',
            'assessments': assess_current(rows, root, now=clock)}
    report['capture_context']['integration'] = 'existing_aeo_inspection_read_only'
    return report


BINDING_QUERY = '''query ReadinessBinding {
  shop { id myshopifyDomain currencyCode }
  currentAppInstallation { accessScopes { handle } }
}'''
PRODUCTS_QUERY = '''query ReadinessProducts($after: String) {
  products(first: 50, after: $after) {
    nodes { id title status updatedAt onlineStoreUrl
      hold: metafield(namespace: "custom", key: "publication_review_hold") { value updatedAt }
    }
    pageInfo { hasNextPage endCursor }
  }
}'''
VARIANTS_QUERY = '''query ReadinessVariants($id: ID!, $after: String) {
  product(id: $id) { id updatedAt
    variants(first: 50, after: $after) {
      nodes { id price inventoryQuantity inventoryPolicy
        inventoryItem { tracked unitCost { amount currencyCode }
          measurement { weight { value unit } }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}'''


class ReadOnlyClient:
    """Dedicated fixed-query client. No mutation/client inheritance or redirects."""
    def __init__(self, *, configured_host, transport_host, token):
        require(configured_host in CONFIGURED_HOSTS and transport_host == configured_host, 'configured_host_mismatch')
        require(isinstance(token, str) and token and '\r' not in token and '\n' not in token, 'token_required')
        self.host, self._token = configured_host, token
        self._bound = False
        self.read_evidence, self.field_errors = [], []
        self.variant_captured_at = {}

    def _transport(self, query, variables):
        # Enforce read-only at the last network boundary too, not just _query.
        require(query in (BINDING_QUERY, PRODUCTS_QUERY, VARIANTS_QUERY), 'query_not_allowlisted')
        require(query == BINDING_QUERY or self._bound, 'binding_required_before_catalog')
        status, headers, raw = https_request(
            'https://' + self.host + '/admin/api/' + API_VERSION + '/graphql.json',
            hosts={self.host}, method='POST', body=json_bytes({'query': query, 'variables': variables}),
            headers={'X-Shopify-Access-Token': self._token, 'Content-Type': 'application/json'})
        require(status == 200, 'shopify_http_error')
        require(headers.get('x-shopify-api-version') == API_VERSION, 'api_version_unverified')
        return strict_json(raw)

    def _query(self, query, variables):
        require(query in (BINDING_QUERY, PRODUCTS_QUERY, VARIANTS_QUERY), 'query_not_allowlisted')
        require(isinstance(variables, dict), 'variables_required')
        if query == BINDING_QUERY:
            require(variables == {}, 'binding_variables_invalid')
        else:
            require(self._bound, 'binding_required_before_catalog')
            expected = {'after'} if query == PRODUCTS_QUERY else {'id', 'after'}
            require(set(variables) == expected, 'variables_invalid')
            cursor = variables['after']
            require(cursor is None or (isinstance(cursor, str) and 0 < len(cursor) <= 4096), 'cursor_invalid')
            if query == VARIANTS_QUERY:
                require(isinstance(variables['id'], str) and re.fullmatch(r'gid://shopify/Product/[1-9]\d*', variables['id']), 'product_id_invalid')
        started = datetime.now(timezone.utc).isoformat()
        response = self._transport(query, variables)
        stamp = datetime.now(timezone.utc).isoformat()
        require(isinstance(response, dict) and isinstance(response.get('data'), dict), 'data_missing')
        data = deepcopy(response['data'])
        errors = response.get('errors') or []
        require(isinstance(errors, list), 'errors_invalid')
        for error in errors:
            path = error.get('path') if isinstance(error, dict) else None
            code = (error.get('extensions') or {}).get('code') if isinstance(error, dict) else None
            # Only permission-denied optional cost/weight fields become unknown.
            require(query == VARIANTS_QUERY and code == 'ACCESS_DENIED' and isinstance(path, list)
                    and len(path) >= 6 and path[:3] == ['product', 'variants', 'nodes']
                    and type(path[3]) is int and path[3] >= 0 and path[4] == 'inventoryItem'
                    and path[5] in ('unitCost', 'measurement'), 'required_graphql_field_failed')
            nodes = ((data.get('product') or {}).get('variants') or {}).get('nodes')
            require(isinstance(nodes, list) and path[3] < len(nodes), 'error_path_invalid')
            item = nodes[path[3]].get('inventoryItem')
            if isinstance(item, dict):
                item[path[5]] = None
            self.field_errors.append({'field': path[5], 'reason': 'access_denied_unknown'})
        self.read_evidence.append({'query': query, 'variables': deepcopy(variables),
            'started_at': started, 'captured_at': stamp, 'api_version': API_VERSION,
            'response_sha256': hashlib.sha256(json_bytes(response)).hexdigest(), 'response': response})
        return data, stamp

    @staticmethod
    def _page(connection):
        require(isinstance(connection, dict) and isinstance(connection.get('nodes'), list), 'connection_missing')
        info = connection.get('pageInfo')
        require(isinstance(info, dict) and type(info.get('hasNextPage')) is bool, 'page_info_missing')
        require(all(isinstance(n, dict) for n in connection['nodes']), 'node_invalid')
        cursor = info.get('endCursor')
        if info['hasNextPage']:
            require(isinstance(cursor, str) and cursor, 'next_cursor_missing')
        return connection['nodes'], info['hasNextPage'], cursor

    def _products(self):
        rows, ids, cursors, after = [], set(), set(), None
        for _ in range(MAX_PAGES):
            data, _stamp = self._query(PRODUCTS_QUERY, {'after': after})
            nodes, more, cursor = self._page(data.get('products'))
            for node in nodes:
                pid = node.get('id')
                require(isinstance(pid, str) and re.fullmatch(r'gid://shopify/Product/[1-9]\d*', pid)
                        and pid not in ids, 'product_identity_invalid')
                require(_time(node.get('updatedAt')) is not None, 'product_updated_at_missing')
                ids.add(pid); rows.append(node)
            if not more:
                return rows
            require(cursor not in cursors, 'repeated_product_cursor')
            cursors.add(cursor); after = cursor
        raise ValueError('product_page_cap')

    def _variants(self, pid, global_ids, expected_updated_at):
        rows, cursors, after = [], set(), None
        for _ in range(MAX_PAGES):
            data, stamp = self._query(VARIANTS_QUERY, {'id': pid, 'after': after})
            product = data.get('product')
            require(isinstance(product, dict) and product.get('id') == pid, 'variant_product_mismatch')
            require(product.get('updatedAt') == expected_updated_at, 'product_changed_during_variant_read')
            nodes, more, cursor = self._page(product.get('variants'))
            for node in nodes:
                vid = node.get('id')
                require(isinstance(vid, str) and re.fullmatch(r'gid://shopify/ProductVariant/[1-9]\d*', vid)
                        and vid not in global_ids, 'variant_identity_invalid')
                global_ids.add(vid); rows.append(node); self.variant_captured_at[vid] = stamp
            if not more:
                return rows
            require(cursor not in cursors, 'repeated_variant_cursor')
            cursors.add(cursor); after = cursor
        raise ValueError('variant_page_cap')

    def collect(self):
        require(not self._bound, 'client_single_use')
        binding, _stamp = self._query(BINDING_QUERY, {})
        shop = binding.get('shop')
        require(isinstance(shop, dict) and shop.get('id') == SHOP_ID
                and shop.get('myshopifyDomain') == SHOP_DOMAIN, 'shop_binding_mismatch')
        scopes = (binding.get('currentAppInstallation') or {}).get('accessScopes')
        require(isinstance(scopes, list) and all(isinstance(s, dict) and isinstance(s.get('handle'), str) for s in scopes), 'scope_verification_missing')
        handles = {s['handle'] for s in scopes}
        require(bool(handles & {'read_products', 'write_products'}) and bool(handles & {'read_inventory', 'write_inventory'}), 'read_scopes_missing')
        self._bound = True
        metadata = self._products()
        products, ids = [], set()
        for row in metadata:
            product = deepcopy(row); product['variants'] = self._variants(row['id'], ids, row['updatedAt']); products.append(product)
        require(self._products() == metadata, 'catalog_changed_during_read')
        return {'shop': shop, 'products': products, 'complete': True,
                'captured_at': datetime.now(timezone.utc).isoformat(), 'api_version': API_VERSION,
                'variant_captured_at': self.variant_captured_at, 'field_errors': self.field_errors,
                'scope_verification': 'authenticated_current_app_scopes', 'read_evidence': self.read_evidence}
