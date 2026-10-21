#!/usr/bin/env python3
"""One-product, append-only gallery executor. No import-time I/O; dry-run default.

This is evidence consistency, not authentication of rights or sales approval.
The old DRAFT-only gate is untouched. Partial reviewed assets may be appended;
gallery_complete/publication_allowed/legal_or_safety_approval remain false.

Actions contract: prepare -> upload plan.json+journal.json with retention >=30d
-> execute once in that same workflow_dispatch run/attempt. The caller must use
the importer's concurrency group and must never overwrite a started journal.
The executor verifies the checkpoint independently through GitHub's read API.
Any older checkpoint for the operation forces reconciliation, never a retry.
Local fsync alone is NOT a claim of persistence across Actions runners.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import tempfile
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import zipfile

import gallery_review
import plan_active_product_gallery
from plan_active_product_gallery import fingerprint, pixel_equal, digest

MAX_BYTES = 32 * 1024 * 1024
MAX_PAGES = 100
SOURCE_HOSTS = frozenset({'cdn.shopify.com', 'raw.githubusercontent.com'})
GID = re.compile(r'gid://shopify/([A-Za-z]+)/[0-9]+')
SHA256 = re.compile(r'[0-9a-f]{64}')
SHA1 = re.compile(r'[0-9a-f]{40}')
SHOP = re.compile(r'[a-z0-9][a-z0-9-]*\.myshopify\.com')
REPOSITORY = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
QUANTITIES = ('available', 'on_hand', 'committed', 'reserved', 'damaged',
              'safety_stock', 'quality_control', 'incoming')
API_VERSION = '2026-10'

# Field names checked with Shopify graphql_schema on 2026-10-21. The validation
# tool returned "validation skipped", NOT a successful schema validation.
BASE_QUERY = '''query GalleryIdentity($id:ID!){shop{id myshopifyDomain}
 product(id:$id){id handle title tags status updatedAt totalInventory publishedAt
 options{id name position values}}}'''
MEDIA_QUERY = '''query GalleryMedia($id:ID!,$after:String){product(id:$id){id
 media(first:100,after:$after){nodes{id alt status mediaContentType
 ... on MediaImage{image{url width height}}} pageInfo{hasNextPage endCursor}}}}'''
VARIANTS_QUERY = '''query GalleryVariants($id:ID!,$after:String){product(id:$id){id
 variants(first:100,after:$after){nodes{id sku selectedOptions{name value} price
 compareAtPrice inventoryQuantity inventoryPolicy inventoryItem{id tracked}}
 pageInfo{hasNextPage endCursor}}}}'''
VARIANT_MEDIA_QUERY = '''query GalleryVariantMedia($id:ID!,$after:String){node(id:$id){
 ... on ProductVariant{id media(first:100,after:$after){nodes{id}
 pageInfo{hasNextPage endCursor}}}}}'''
INVENTORY_QUERY = '''query GalleryInventory($id:ID!,$after:String){node(id:$id){
 ... on InventoryItem{id inventoryLevels(first:100,after:$after){nodes{id location{id}
 quantities(names:["available","on_hand","committed","reserved","damaged",
 "safety_stock","quality_control","incoming"]){name quantity}}
 pageInfo{hasNextPage endCursor}}}}}'''
PUBLICATIONS_QUERY = '''query GalleryPublications($id:ID!,$after:String){product(id:$id){id
 resourcePublications(first:100,after:$after,onlyPublished:false){nodes{
 publication{id} isPublished publishDate} pageInfo{hasNextPage endCursor}}}}'''
APPEND_MUTATION = '''mutation AppendReviewedGallery($product:ProductUpdateInput!,
 $media:[CreateMediaInput!]!){productUpdate(product:$product,media:$media){
 product{id} userErrors{field message}}}'''


class Hold(ValueError):
    """Fail closed before writing, or require read-only reconciliation."""


class PriorCheckpoint(Hold):
    def __init__(self, artifact):
        super().__init__('prior_operation_checkpoint_reconcile_only')
        self.artifact = artifact


def require(condition, reason):
    if not condition:
        raise Hold(reason)


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(result.tzinfo is not None, 'timestamp_timezone_required')
        return result
    except (ValueError, TypeError, AttributeError):
        raise Hold('timestamp_invalid') from None


def valid_gid(value, kind):
    return isinstance(value, str) and re.fullmatch(r'gid://shopify/' + kind + r'/[0-9]+', value)


def read_json(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= MAX_BYTES,
            'json_file_missing_unsafe_or_oversized')
    try:
        return strict_json(path.read_bytes())
    except (ValueError, UnicodeError):
        raise Hold('json_invalid') from None


def strict_json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    def invalid_constant(value):
        raise Hold('nonfinite_json_number')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode()


def atomic_json(path, value):
    """Atomic local checkpoint, followed by fsync. Not cross-run durability."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.is_symlink(), 'journal_symlink_forbidden')
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(json_bytes(value))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def journal_lock(path):
    # GitHub's concurrency group handles runners; this handles local processes.
    import fcntl
    lock = Path(str(path) + '.lock')
    require(not lock.is_symlink(), 'journal_lock_symlink_forbidden')
    with lock.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Hold('operation_already_running') from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def safe_url(url, hosts):
    require(isinstance(url, str) and len(url) <= 4096 and not any(c.isspace() for c in url),
            'source_url_invalid')
    try:
        parsed = urlsplit(url)
        require(parsed.scheme == 'https' and parsed.hostname in hosts and
                parsed.port in (None, 443) and not parsed.username and not parsed.password
                and not parsed.fragment and '\\' not in url, 'source_url_not_allowed')
    except ValueError:
        raise Hold('source_url_invalid') from None
    return parsed


def asset_url(url, allowed):
    require(isinstance(allowed, list) and allowed and all(h in SOURCE_HOSTS for h in allowed)
            and len(set(allowed)) == len(allowed), 'source_allowlist_invalid')
    parsed = safe_url(url, set(allowed))
    if parsed.hostname == 'raw.githubusercontent.com':
        segments = parsed.path.split('/')
        require(len(segments) >= 5 and segments[0] == '' and not parsed.query
                and SHA1.fullmatch(segments[3]) is not None
                and all(segment not in {'.', '..'} and
                        re.fullmatch(r'[A-Za-z0-9_.-]+', segment) is not None
                        for segment in segments[1:]), 'source_commit_url_required')
    else:
        try:
            query = parse_qs(parsed.query, strict_parsing=True)
        except ValueError:
            raise Hold('source_cdn_query_invalid') from None
        require(set(query).issubset({'v'}) and all(len(v) == 1 and v[0].isdigit()
                for v in query.values()) and parsed.path.startswith('/s/files/'),
                'source_cdn_url_untransformed_required')
    return url


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Resolve once, reject every non-global result, pin connection IP and TLS SNI.

    No proxy environment, redirects, cookies, automatic retry or second DNS lookup.
    """
    def connect(self):
        addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        require(bool(addresses), 'dns_empty')
        for row in addresses:
            address = ipaddress.ip_address(row[4][0])
            require(address.is_global and not address.is_multicast and not address.is_reserved,
                    'non_public_network_destination')
        family, socktype, protocol, _, sockaddr = addresses[0]
        sock = socket.socket(family, socktype, protocol)
        try:
            sock.settimeout(self.timeout)
            sock.connect(sockaddr)
            self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def https_request(url, *, hosts, method='GET', body=None, headers=None):
    parsed = safe_url(url, hosts)
    connection = PinnedHTTPSConnection(parsed.hostname, timeout=30)
    request_headers = {'User-Agent': 'JarvisReviewedGallery/1.0', 'Accept-Encoding': 'identity'}
    request_headers.update(headers or {})
    try:
        connection.request(method, parsed.path + ('?' + parsed.query if parsed.query else ''),
                           body=body, headers=request_headers)
        response = connection.getresponse()
        result_headers = {k.lower(): v for k, v in response.getheaders()}
        require(result_headers.get('content-encoding', 'identity') == 'identity', 'encoded_body_refused')
        length = result_headers.get('content-length')
        require(length is None or (length.isdigit() and int(length) <= MAX_BYTES), 'response_too_large')
        data = response.read(MAX_BYTES + 1)
        require(len(data) <= MAX_BYTES, 'response_too_large')
        require(length is None or int(length) == len(data), 'response_truncated')
        return response.status, result_headers, data
    finally:
        connection.close()


def fetch_asset(url, hosts):
    status, headers, data = https_request(url, hosts=hosts)
    require(status == 200 and data, 'asset_http_error_or_redirect')
    require(headers.get('content-type', '').split(';')[0].lower() in
            {'image/png', 'image/jpeg', 'image/webp', 'application/octet-stream'}, 'asset_content_type_invalid')
    return data


def bytes_fingerprint(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_BYTES, 'asset_bytes_invalid')
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'image'
        path.write_bytes(raw)
        result = fingerprint('image', directory)
    require(result is not None, 'asset_image_unverified')
    return result


class ShopifyClient:
    """Dedicated transport; existing client credentials may obtain a short-lived token.

    No credential/grant creation, token persistence, import side effects or retries.
    """
    def __init__(self, shop, token=None, *, request=https_request, fetch=fetch_asset,
                 client_id=None, client_secret=None):
        require(isinstance(shop, str) and SHOP.fullmatch(shop), 'shop_domain_invalid')
        self.shop, self.token, self.request, self.fetch = shop, token, request, fetch
        if not token:
            require(isinstance(client_id, str) and client_id and isinstance(client_secret, str)
                    and client_secret, 'existing_shopify_credentials_missing')
            status, _, raw = self.request('https://' + shop + '/admin/oauth/access_token', hosts={shop},
                method='POST', body=urlencode({'grant_type': 'client_credentials', 'client_id': client_id,
                'client_secret': client_secret}).encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
            require(status == 200, 'short_lived_token_exchange_failed')
            self.token = strict_json(raw).get('access_token')
        require(isinstance(self.token, str) and bool(self.token.strip()), 'shopify_token_missing')

    @classmethod
    def from_environment(cls, transport_shop, *, request=https_request, fetch=fetch_asset):
        # Credentials belong to the configured transport, which can differ from
        # Shopify's canonical myshopifyDomain. Never infer aliases or redirect a
        # token/client secret to a domain supplied only by the manifest.
        configured = os.environ.get('SHOPIFY_STORE')
        require(isinstance(configured, str) and configured, 'configured_shopify_transport_missing')
        configured = configured.removeprefix('https://').rstrip('/')
        require(SHOP.fullmatch(configured) and isinstance(transport_shop, str) and
                SHOP.fullmatch(transport_shop) and transport_shop == configured,
                'configured_shopify_transport_mismatch')
        return cls(configured, os.environ.get('SHOPIFY_ADMIN_TOKEN'), client_id=os.environ.get('SHOPIFY_CLIENT_ID'),
                   client_secret=os.environ.get('SHOPIFY_CLIENT_SECRET'), request=request, fetch=fetch)

    def gql(self, document, variables):
        status, _, raw = self.request('https://' + self.shop + '/admin/api/' + API_VERSION + '/graphql.json',
            hosts={self.shop}, method='POST', body=json_bytes({'query': document, 'variables': variables}),
            headers={'X-Shopify-Access-Token': self.token, 'Content-Type': 'application/json'})
        require(status == 200, 'shopify_http_error')
        result = strict_json(raw)
        require(isinstance(result, dict) and not result.get('errors') and isinstance(result.get('data'), dict),
                'shopify_graphql_error')
        return result['data']

    def connection(self, query, identity, field, *, node=False, key='id'):
        cursor, cursors, rows, identifiers = None, set(), [], set()
        for _ in range(MAX_PAGES):
            parent = self.gql(query, {'id': identity, 'after': cursor}).get('node' if node else 'product')
            require(isinstance(parent, dict) and parent.get('id') == identity, 'pagination_identity_mismatch')
            conn = parent.get(field)
            require(isinstance(conn, dict) and isinstance(conn.get('nodes'), list)
                    and isinstance(conn.get('pageInfo'), dict), 'pagination_incomplete')
            page = conn['pageInfo']
            require(type(page.get('hasNextPage')) is bool and 'endCursor' in page, 'pagination_incomplete')
            for row in conn['nodes']:
                require(isinstance(row, dict), 'pagination_row_invalid')
                identifier = (row.get('publication') or {}).get('id') if key == 'publication' else row.get(key)
                require(isinstance(identifier, str) and identifier and identifier not in identifiers,
                        'pagination_duplicate_or_missing_identity')
                identifiers.add(identifier)
                rows.append(row)
            if page['hasNextPage'] is False:
                return rows
            cursor = page.get('endCursor')
            require(bool(conn['nodes']) and isinstance(cursor, str) and cursor and cursor not in cursors,
                    'pagination_cursor_invalid')
            cursors.add(cursor)
        raise Hold('pagination_limit_reached')

    def read_snapshot(self, product_id):
        started = utcnow()
        base = self.gql(BASE_QUERY, {'id': product_id})
        require(isinstance(base.get('product'), dict), 'product_not_found')
        product = deepcopy(base['product'])
        product['media'] = self.connection(MEDIA_QUERY, product_id, 'media')
        for media in product['media']:
            require(media.get('status') == 'READY' and media.get('mediaContentType') == 'IMAGE',
                    'existing_media_not_ready_image')
            image = media.get('image') or {}
            media['fingerprint'] = bytes_fingerprint(self.fetch(image.get('url'), {'cdn.shopify.com'}))
            require((image.get('width'), image.get('height')) ==
                    (media['fingerprint']['width'], media['fingerprint']['height']), 'media_dimensions_mismatch')
        product['variants'] = self.connection(VARIANTS_QUERY, product_id, 'variants')
        for variant in product['variants']:
            variant['media'] = self.connection(VARIANT_MEDIA_QUERY, variant['id'], 'media', node=True)
            item = variant.get('inventoryItem') or {}
            item['inventoryLevels'] = self.connection(INVENTORY_QUERY, item.get('id'), 'inventoryLevels', node=True)
            variant['inventoryItem'] = item
        product['publications'] = self.connection(PUBLICATIONS_QUERY, product_id, 'resourcePublications', key='publication')
        require(self.gql(BASE_QUERY, {'id': product_id}) == base, 'snapshot_changed_during_pagination')
        return {'schema_version': 1, 'observed_at': started.isoformat(), 'complete': True,
                'shop': base.get('shop'), 'product': product}

    def append_once(self, product_id, assets):
        # This is the only remote mutation boundary. Do not add a retry here.
        result = self.gql(APPEND_MUTATION, {'product': {'id': product_id}, 'media': [
            {'originalSource': asset['asset_url'], 'mediaContentType': 'IMAGE', 'alt': asset['alt_text']} for asset in assets]})
        payload = result.get('productUpdate')
        require(isinstance(payload, dict) and payload.get('userErrors') == [] and
                (payload.get('product') or {}).get('id') == product_id, 'mutation_response_not_verified')
        return payload


def validate_snapshot(snapshot, *, now=None, fresh=True):
    now = now or utcnow()
    require(isinstance(snapshot, dict) and snapshot.get('complete') is True and
            type(snapshot.get('schema_version')) is int and snapshot['schema_version'] == 1,
            'complete_snapshot_required')
    age = (now - stamp(snapshot.get('observed_at'))).total_seconds()
    require(not fresh or 0 <= age <= 300, 'snapshot_stale_or_future')
    shop, product = snapshot.get('shop'), snapshot.get('product')
    require(isinstance(shop, dict) and valid_gid(shop.get('id'), 'Shop') and
            isinstance(shop.get('myshopifyDomain'), str) and SHOP.fullmatch(shop['myshopifyDomain']), 'shop_identity_invalid')
    require(isinstance(product, dict) and valid_gid(product.get('id'), 'Product') and
            product.get('status') in {'ACTIVE', 'DRAFT'}, 'product_identity_or_status_invalid')
    for key in ('handle', 'title', 'updatedAt'):
        require(isinstance(product.get(key), str) and product[key], 'product_field_missing:' + key)
    require('publishedAt' in product and type(product.get('totalInventory')) is int, 'product_inventory_publication_missing')
    for key in ('tags', 'options', 'media', 'variants', 'publications'):
        require(isinstance(product.get(key), list), 'snapshot_list_missing:' + key)
    require(all(isinstance(t, str) for t in product['tags']) and len(set(product['tags'])) == len(product['tags']), 'tags_invalid')
    require(product['variants'] and product['options'], 'variant_or_options_missing')
    for option in product['options']:
        require(isinstance(option, dict) and valid_gid(option.get('id'), 'ProductOption') and
                isinstance(option.get('name'), str) and type(option.get('position')) is int and
                isinstance(option.get('values'), list) and all(isinstance(v, str) for v in option['values']), 'options_invalid')
    for rows, key in ((product['media'], 'id'), (product['variants'], 'id'), (product['options'], 'id')):
        ids = [row.get(key) for row in rows if isinstance(row, dict)]
        require(len(ids) == len(rows) and len(set(ids)) == len(ids), 'duplicate_snapshot_identity')
    for media in product['media']:
        require(valid_gid(media.get('id'), 'MediaImage') and media.get('status') == 'READY' and
                media.get('mediaContentType') == 'IMAGE' and 'alt' in media and
                (media['alt'] is None or isinstance(media['alt'], str)), 'existing_media_unready_or_invalid')
        safe_url((media.get('image') or {}).get('url'), {'cdn.shopify.com'})
        fp = media.get('fingerprint')
        require(isinstance(fp, dict) and isinstance(fp.get('sha256'), str) and SHA256.fullmatch(fp['sha256'])
                and pixel_equal(fp, fp), 'existing_media_bytes_unverified')
    for variant in product['variants']:
        require(valid_gid(variant.get('id'), 'ProductVariant') and isinstance(variant.get('sku'), str)
                and variant['sku'] and isinstance(variant.get('selectedOptions'), list)
                and variant['selectedOptions'], 'variant_identity_missing')
        require(all(isinstance(o, dict) and isinstance(o.get('name'), str) and isinstance(o.get('value'), str)
                    for o in variant['selectedOptions']), 'variant_options_invalid')
        require(isinstance(variant.get('price'), str) and 'compareAtPrice' in variant and
                type(variant.get('inventoryQuantity')) is int and variant.get('inventoryPolicy') in {'DENY', 'CONTINUE'}
                and isinstance(variant.get('media'), list), 'variant_protection_missing')
        require(all(isinstance(m, dict) and valid_gid(m.get('id'), 'MediaImage') for m in variant['media']), 'variant_media_invalid')
        item = variant.get('inventoryItem') or {}
        require(valid_gid(item.get('id'), 'InventoryItem') and type(item.get('tracked')) is bool
                and isinstance(item.get('inventoryLevels'), list), 'inventory_protection_missing')
        level_ids = []
        for level in item['inventoryLevels']:
            require(isinstance(level, dict) and isinstance(level.get('id'), str) and
                    valid_gid((level.get('location') or {}).get('id'), 'Location') and
                    isinstance(level.get('quantities'), list), 'inventory_level_invalid')
            quantities = level['quantities']
            require(len(quantities) == len(QUANTITIES) and
                    {q.get('name') for q in quantities if isinstance(q, dict)} == set(QUANTITIES) and
                    all(type(q.get('quantity')) is int for q in quantities), 'inventory_quantities_incomplete')
            level_ids.append(level['id'])
        require(len(set(level_ids)) == len(level_ids), 'inventory_levels_duplicate')
    pubs = []
    for publication in product['publications']:
        require(isinstance(publication, dict) and valid_gid((publication.get('publication') or {}).get('id'), 'Publication')
                and type(publication.get('isPublished')) is bool and isinstance(publication.get('publishDate'), str),
                'publication_protection_missing')
        pubs.append(publication['publication']['id'])
    require(len(pubs) == len(set(pubs)), 'publication_duplicate')
    return snapshot


def snapshot_identity(snapshot, pd_no):
    product = snapshot['product']
    return {'shop': snapshot['shop'], 'product_id': product['id'], 'pd_no': pd_no,
            'title': product['title'], 'handle': product['handle'], 'options': product['options'],
            'variants': [{k: row[k] for k in ('id', 'sku', 'selectedOptions')} for row in product['variants']]}


def protection(snapshot, *, include_media=True, include_updated=False):
    result = deepcopy({'shop': snapshot['shop'], 'product': snapshot['product']})
    if not include_updated:
        result['product'].pop('updatedAt', None)
    if not include_media:
        result['product'].pop('media', None)
    return result


def validate_scope(scope, snapshot, now):
    require(isinstance(scope, dict), 'manual_scope_required')
    require(isinstance(scope.get('transport_shop'), str) and SHOP.fullmatch(scope['transport_shop']),
            'explicit_transport_shop_required')
    identity = scope.get('identity')
    require(isinstance(identity, dict) and isinstance(identity.get('pd_no'), str)
            and re.fullmatch(r'[0-9]+', identity['pd_no']), 'pd_no_invalid')
    require(snapshot_identity(snapshot, identity['pd_no']) == identity, 'exact_product_sku_options_identity_mismatch')
    pd_tags = [t for t in snapshot['product']['tags'] if t.startswith('daiso-pd-')]
    require(pd_tags == ['daiso-pd-' + identity['pd_no']], 'exact_pd_no_tag_required')
    require(scope.get('expected_status') == snapshot['product']['status'], 'current_status_mismatch')
    require(isinstance(scope.get('execution_ticket'), str) and
            re.fullmatch(r'[A-Za-z0-9_-]{8,128}', scope['execution_ticket']), 'manual_execution_ticket_required')
    issued, expires = stamp(scope.get('authorized_at')), stamp(scope.get('expires_at'))
    require(issued <= now < expires and timedelta(0) < expires - issued <= timedelta(hours=24),
            'execution_scope_expired_or_over_24h')
    hashes = scope.get('asset_sha256s')
    require(isinstance(hashes, list) and hashes and len(hashes) <= 20 and
            all(isinstance(h, str) and SHA256.fullmatch(h) for h in hashes) and len(set(hashes)) == len(hashes),
            'explicit_asset_scope_required')


def receipt(root, ref):
    require(isinstance(ref, dict), 'receipt_missing')
    try:
        return strict_json(gallery_review._bytes(Path(root).resolve(), ref.get('file'), ref.get('sha256')))
    except (ValueError, TypeError, OSError):
        raise Hold('receipt_bytes_unverified') from None


def operation_id(scope):
    # Independent of regenerated plan/media observations. Same ticket and asset
    # scope always resolve to the same durable operation identity.
    return digest({'ticket': scope['execution_ticket'], 'identity': scope['identity'],
                   'asset_sha256s': sorted(scope['asset_sha256s'])})


def compute_plan_digest(plan):
    payload = deepcopy(plan)
    payload.pop('plan_digest', None)
    payload.get('before', {}).pop('observed_at', None)
    return digest(payload)


def implementation_digest():
    return digest({Path(module.__file__).name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                   for module in (gallery_review, plan_active_product_gallery)} |
                  {Path(__file__).name: hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})


def build_reviewed_plan(scope, manifest, root, snapshot, *, now=None):
    now = now or utcnow()
    validate_snapshot(snapshot, now=now)
    validate_scope(scope, snapshot, now)
    pd_no = scope['identity']['pd_no']
    assessment = gallery_review.assess_gallery(pd_no, manifest, root, now=now)
    require(assessment['rights_review'] == 'recorded_bound' and assessment['label_review'] == 'recorded_bound',
            'rights_and_actual_label_evidence_required')
    require(not assessment['rejected_assets'], 'asset_receipt_or_final_qa_unverified')
    require(isinstance(manifest, dict) and manifest.get('execution_identity') == scope['identity'], 'manifest_identity_mismatch')
    for kind in ('rights', 'label'):
        doc = receipt(root, manifest['review_evidence'][kind])
        require(doc.get('execution_identity') == scope['identity'], kind + '_exact_identity_unverified')
    accepted = {a['asset_sha256']: a for a in assessment['accepted_assets']}
    assets = {a['asset_sha256']: a for a in manifest['assets']}
    require(set(scope['asset_sha256s']).issubset(accepted), 'requested_asset_not_accepted')
    additions, noops, held = [], [], []
    for asset_hash in scope['asset_sha256s']:
        asset = assets[asset_hash]
        doc = receipt(root, asset['review_receipt'])
        require(doc.get('execution_identity') == scope['identity'], 'asset_exact_identity_unverified')
        fp = fingerprint(asset.get('asset_file'), root)
        require(fp is not None and fp['sha256'] == asset_hash, 'final_output_bytes_unverified')
        matches = [m for m in snapshot['product']['media'] if pixel_equal(fp, m['fingerprint'])]
        attached_id, attached_url = asset.get('attached_media_id'), asset.get('attached_image_url')
        if attached_id is not None or attached_url is not None:
            matched = [m for m in matches if m['id'] == attached_id and m['image']['url'] == attached_url]
            require(len(matched) == 1, 'existing_media_id_url_pixel_binding_mismatch')
        if matches:
            noops.append({'asset_sha256': asset_hash, 'media_ids': [m['id'] for m in matches],
                          'decision': 'reuse_existing_noop', 'fingerprint': fp})
            continue
        url = asset_url(asset.get('asset_url'), scope.get('allowed_source_hosts'))
        # Shopify fetches this URL later; CDN version queries are not immutable bytes.
        require(urlsplit(url).hostname == 'raw.githubusercontent.com',
                'new_asset_immutable_commit_source_required')
        require(doc.get('asset_url') == url, 'final_output_url_receipt_binding_missing')
        alt = asset.get('alt_text')
        require(isinstance(alt, str) and 1 <= len(alt.strip()) <= 512 and alt == alt.strip()
                and not any(ord(c) < 32 or 127 <= ord(c) < 160 for c in alt)
                and doc.get('alt_text') == alt, 'reviewed_new_asset_alt_required')
        require(not any(m['image']['url'] == url for m in snapshot['product']['media']), 'existing_url_with_different_pixels')
        if any(pixel_equal(fp, a['fingerprint']) for a in additions):
            held.append({'asset_sha256': asset_hash, 'reason': 'duplicate_candidate_pixels'})
            continue
        additions.append({'asset_sha256': asset_hash, 'asset_url': url, 'alt_text': alt, 'fingerprint': fp,
                          'roles': accepted[asset_hash]['roles']})
    result = {'schema_version': 1, 'kind': 'reviewed_gallery_append_only', 'scope': deepcopy(scope),
              'operation_id': operation_id(scope), 'manifest_digest': digest(manifest),
              'implementation_digest': implementation_digest(),
              'assessment_digest': assessment['evidence_digest'], 'before': deepcopy(snapshot),
              'additions': additions, 'noops': noops, 'held': held,
              'preserve_media_ids': [m['id'] for m in snapshot['product']['media']],
              'gallery_complete': False, 'publication_allowed': False, 'legal_or_safety_approval': False,
              'missing_roles': assessment['missing_roles'], 'status': 'additions_prepared' if additions else 'noop',
              'source_verification': 'exact_remote_bytes_required_before_apply'}
    result['plan_digest'] = compute_plan_digest(result)
    return result


def validate_plan_digest(plan, expected):
    require(isinstance(plan, dict) and isinstance(expected, str) and SHA256.fullmatch(expected), 'expected_plan_digest_required')
    require(expected == plan.get('plan_digest') == compute_plan_digest(plan), 'plan_digest_mismatch')


def make_journal(plan, *, repository, run_id, run_attempt, code_sha, workflow_path):
    require(REPOSITORY.fullmatch(repository or '') and str(run_id).isdigit() and str(run_attempt).isdigit()
            and SHA1.fullmatch(code_sha or '') and re.fullmatch(r'\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml', workflow_path or ''),
            'workflow_context_required')
    name = 'gallery-checkpoint-' + plan['operation_id'] + '-' + str(run_id) + '-' + str(run_attempt)
    return {'schema_version': 1, 'operation_id': plan['operation_id'], 'plan_digest': plan['plan_digest'],
            'state': 'prepared', 'repository': repository, 'run_id': str(run_id), 'run_attempt': str(run_attempt),
            'code_sha': code_sha, 'workflow_path': workflow_path, 'artifact_name': name,
            'before': plan['before'], 'expected_after': {'protected': protection(plan['before'], include_media=False),
            'preserved_media': plan['before']['product']['media'], 'additions': plan['additions']},
            'write_attempts': 0, 'gallery_complete': False, 'publication_allowed': False}


class GitHubCheckpoint:
    """Read-only verification of an uploaded write-ahead artifact and prior history."""
    def __init__(self, token, artifact_id, artifact_digest, *, request=https_request):
        require(isinstance(token, str) and token and str(artifact_id).isdigit(), 'github_checkpoint_credentials_missing')
        require(isinstance(artifact_digest, str) and re.fullmatch(r'(sha256:)?[0-9a-f]{64}', artifact_digest), 'artifact_digest_invalid')
        self.token, self.artifact_id = token, str(artifact_id)
        self.expected_digest = artifact_digest.removeprefix('sha256:')
        self.request = request

    def api(self, path, *, raw=False):
        status, headers, body = self.request('https://api.github.com' + path, hosts={'api.github.com'},
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28'})
        if raw:
            return status, headers, body
        require(status == 200, 'github_checkpoint_api_failed')
        result = strict_json(body)
        require(isinstance(result, dict), 'github_checkpoint_response_invalid')
        return result

    def verify(self, plan, journal):
        prefix = '/repos/' + journal['repository']
        current = self.api(prefix + '/actions/artifacts/' + self.artifact_id)
        require(str(current.get('id')) == self.artifact_id and current.get('name') == journal['artifact_name']
                and current.get('expired') is False, 'checkpoint_artifact_identity_mismatch')
        require(str((current.get('workflow_run') or {}).get('id')) == journal['run_id'] and
                (current.get('workflow_run') or {}).get('head_sha') == journal['code_sha'], 'checkpoint_run_mismatch')
        require(stamp(current.get('expires_at')) - stamp(current.get('created_at')) >= timedelta(days=30) - timedelta(minutes=1),
                'checkpoint_retention_under_30_days')
        require(current.get('digest') == 'sha256:' + self.expected_digest, 'checkpoint_metadata_digest_mismatch')
        run = self.api(prefix + '/actions/runs/' + journal['run_id'])
        require(str(run.get('id')) == journal['run_id'] and str(run.get('run_attempt')) == journal['run_attempt']
                and run.get('head_sha') == journal['code_sha'] and run.get('path') == journal['workflow_path']
                and run.get('event') == 'workflow_dispatch' and run.get('status') == 'in_progress', 'checkpoint_workflow_mismatch')
        seen, total, prior = set(), None, []
        for page in range(1, MAX_PAGES + 1):
            batch = self.api(prefix + '/actions/artifacts?per_page=100&page=' + str(page))
            require(type(batch.get('total_count')) is int and isinstance(batch.get('artifacts'), list), 'checkpoint_scan_incomplete')
            if total is None:
                total = batch['total_count']
            require(batch['total_count'] == total, 'checkpoint_scan_drift')
            for artifact in batch['artifacts']:
                require(isinstance(artifact, dict) and type(artifact.get('id')) is int and artifact['id'] not in seen, 'checkpoint_scan_duplicate')
                seen.add(artifact['id'])
                if (artifact.get('name') or '').startswith('gallery-checkpoint-' + plan['operation_id'] + '-'):
                    if str(artifact['id']) != self.artifact_id:
                        prior.append(artifact)
            if len(seen) == total:
                break
            require(batch['artifacts'] and len(seen) < total, 'checkpoint_scan_incomplete')
        else:
            raise Hold('checkpoint_scan_limit')
        require(int(self.artifact_id) in seen, 'checkpoint_absent_from_history')
        if prior:
            raise PriorCheckpoint(sorted(prior, key=lambda a: a['id'])[0])
        found_plan, found_journal = self.download(journal['repository'])
        require(json_bytes(found_plan) == json_bytes(plan) and json_bytes(found_journal) == json_bytes(journal),
                'checkpoint_plan_or_journal_bytes_mismatch')
        return True

    def download(self, repository):
        require(REPOSITORY.fullmatch(repository or ''), 'checkpoint_repository_invalid')
        prefix = '/repos/' + repository
        status, headers, archive = self.api(prefix + '/actions/artifacts/' + self.artifact_id + '/zip', raw=True)
        if status == 302:
            target = headers.get('location')
            parsed = urlsplit(target or '')
            host = parsed.hostname or ''
            require(host.endswith('.blob.core.windows.net') or host.endswith('.actions.githubusercontent.com'),
                    'checkpoint_download_host_invalid')
            # GitHub authorization header is NEVER forwarded to signed object storage.
            status, _, archive = self.request(target, hosts={host})
        require(status == 200 and hashlib.sha256(archive).hexdigest() == self.expected_digest, 'checkpoint_zip_digest_mismatch')
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
                require(set(zipped.namelist()) == {'plan.json', 'journal.json'} and len(zipped.infolist()) == 2,
                        'checkpoint_zip_members_invalid')
                require(all(i.file_size <= MAX_BYTES and not i.flag_bits & 1 for i in zipped.infolist()), 'checkpoint_zip_unsafe')
                raw_plan, raw_journal = zipped.read('plan.json'), zipped.read('journal.json')
                plan, journal = strict_json(raw_plan), strict_json(raw_journal)
                require(raw_plan == json_bytes(plan) and raw_journal == json_bytes(journal), 'checkpoint_json_not_canonical')
        except (ValueError, OSError, zipfile.BadZipFile, RuntimeError):
            raise Hold('checkpoint_zip_invalid') from None
        return plan, journal

    def restore(self, repository, *, expected_plan_digest, expected_shop, expected_product):
        """Restore only an original checkpoint for READ-ONLY reconciliation.

        Completed/older attempts are allowed here. This method never grants apply.
        """
        require(REPOSITORY.fullmatch(repository or ''), 'checkpoint_repository_invalid')
        current = self.api('/repos/' + repository + '/actions/artifacts/' + self.artifact_id)
        require(str(current.get('id')) == self.artifact_id and current.get('expired') is False
                and current.get('digest') == 'sha256:' + self.expected_digest, 'restore_artifact_invalid')
        plan, journal = self.download(repository)
        validate_plan_digest(plan, expected_plan_digest)
        validate_snapshot(plan.get('before'), fresh=False)
        require(plan.get('kind') == 'reviewed_gallery_append_only' and plan.get('operation_id') == operation_id(plan['scope']),
                'restore_plan_scope_invalid')
        require(isinstance(plan['scope'].get('transport_shop'), str) and SHOP.fullmatch(plan['scope']['transport_shop']),
                'explicit_transport_shop_required')
        require(plan['scope']['identity']['shop']['myshopifyDomain'] == expected_shop and
                plan['scope']['identity']['product_id'] == expected_product and
                snapshot_identity(plan['before'], plan['scope']['identity']['pd_no']) == plan['scope']['identity'],
                'restore_exact_target_mismatch')
        expected = make_journal(plan, **{key: journal.get(key) for key in
            ('repository', 'run_id', 'run_attempt', 'code_sha', 'workflow_path')})
        require(json_bytes(expected) == json_bytes(journal) and journal['repository'] == repository and
                current.get('name') == journal['artifact_name'] and
                str((current.get('workflow_run') or {}).get('id')) == journal['run_id'] and
                (current.get('workflow_run') or {}).get('head_sha') == journal['code_sha'], 'restore_journal_identity_invalid')
        run = self.api('/repos/' + repository + '/actions/runs/' + journal['run_id'])
        require(str(run.get('id')) == journal['run_id'] and run.get('event') == 'workflow_dispatch' and
                run.get('head_sha') == journal['code_sha'] and run.get('path') == journal['workflow_path'] and
                int(run.get('run_attempt', 0)) >= int(journal['run_attempt']), 'restore_run_identity_invalid')
        return plan, journal


def verify_after(plan, snapshot):
    validate_snapshot(snapshot)
    require(protection(snapshot, include_media=False) == protection(plan['before'], include_media=False), 'protected_fields_changed')
    before = plan['before']['product']['media']
    after = snapshot['product']['media']
    require(after[:len(before)] == before, 'existing_media_deleted_reordered_or_changed')
    extra = after[len(before):]
    require(len(extra) == len(plan['additions']), 'unexpected_media_addition_count')
    remaining = list(extra)
    matches = []
    for asset in plan['additions']:
        eligible = [m for m in remaining if pixel_equal(asset['fingerprint'], m['fingerprint'])]
        require(len(eligible) == 1, 'appended_media_pixels_unverified_or_ambiguous')
        require(eligible[0]['alt'] == asset['alt_text'], 'appended_reviewed_alt_mismatch')
        remaining.remove(eligible[0])
        matches.append({'asset_sha256': asset['asset_sha256'], 'media_id': eligible[0]['id'],
                        'url': eligible[0]['image']['url']})
    return matches


def result(state, plan, **extra):
    return {'state': state, 'operation_id': plan['operation_id'], 'plan_digest': plan['plan_digest'],
            'gallery_complete': False, 'publication_allowed': False, 'legal_or_safety_approval': False, **extra}


def reconcile(plan, client, journal_path=None):
    """Read-only regardless of journal state, missing rows, timeout or mismatches."""
    journal = None
    if journal_path is not None:
        journal = read_json(journal_path)
        require(journal.get('operation_id') == plan['operation_id'] and journal.get('plan_digest') == plan['plan_digest'],
                'reconcile_journal_operation_mismatch')
    try:
        matches = verify_after(plan, client.read_snapshot(plan['scope']['identity']['product_id']))
        output = result('reconciled_noop', plan, matched_assets=matches, writes=0)
    except Exception as error:
        output = result('verification_pending', plan, reason=str(error) if isinstance(error, Hold) else type(error).__name__, writes=0)
    if journal is not None:
        journal['state'] = output['state']
        journal['last_readback'] = output
        atomic_json(journal_path, journal)
    return output


def execute_reviewed_plan(plan, *, manifest, root, expected_plan_digest, client=None,
                          journal_path=None, checkpoint=None, apply=False, now=None,
                          polls=3, pause=time.sleep):
    validate_plan_digest(plan, expected_plan_digest)
    require(type(apply) is bool, 'apply_must_be_boolean')
    require(type(polls) is int and 1 <= polls <= 10, 'readback_poll_limit_invalid')
    if not apply:
        return result('dry_run', plan, writes=0, additions=len(plan['additions']), noops=len(plan['noops']))
    require(client is not None and journal_path is not None, 'apply_client_and_journal_required')
    with journal_lock(journal_path):
        journal = read_json(journal_path)
        require(journal.get('operation_id') == plan['operation_id'] and journal.get('plan_digest') == expected_plan_digest,
                'journal_operation_mismatch')
        if journal.get('state') != 'prepared' or type(journal.get('write_attempts')) is not int or journal['write_attempts'] != 0:
            return reconcile(plan, client, journal_path)
        # A renewed prepare must not change the exact bytes/scope in the accepted plan.
        current = client.read_snapshot(plan['scope']['identity']['product_id'])
        # A live read stamps its observation after the request starts. Capture
        # validation time after the read, otherwise every real CLI read appears
        # to be from the future (fixed-clock mocks can hide this).
        clock = now or utcnow()
        validate_snapshot(current, now=clock)
        require(protection(current, include_updated=True) == protection(plan['before'], include_updated=True), 'preapply_snapshot_drift')
        rebuilt = build_reviewed_plan(plan['scope'], manifest, root, current, now=clock)
        rebuilt['before'] = plan['before']
        rebuilt['plan_digest'] = compute_plan_digest(rebuilt)
        require(rebuilt == plan, 'evidence_or_plan_changed')
        if not plan['additions']:
            return result('noop', plan, writes=0)
        require(checkpoint is not None, 'durable_checkpoint_required')
        expected_journal = make_journal(plan, **{key: journal.get(key) for key in
            ('repository', 'run_id', 'run_attempt', 'code_sha', 'workflow_path')})
        require(json_bytes(journal) == json_bytes(expected_journal), 'prepared_journal_shape_or_snapshot_mismatch')
        try:
            require(checkpoint.verify(plan, journal) is True, 'durable_checkpoint_not_verified')
        except PriorCheckpoint as previous:
            old_backend = GitHubCheckpoint(checkpoint.token, previous.artifact['id'], previous.artifact.get('digest'),
                                           request=checkpoint.request)
            old_plan, _ = old_backend.restore(journal['repository'], expected_plan_digest=expected_plan_digest,
                expected_shop=plan['scope']['identity']['shop']['myshopifyDomain'],
                expected_product=plan['scope']['identity']['product_id'])
            require(old_plan['operation_id'] == plan['operation_id'], 'prior_operation_scope_mismatch')
            return reconcile(old_plan, client)
        for asset in plan['additions']:
            raw = client.fetch(asset['asset_url'], set(plan['scope']['allowed_source_hosts']))
            require(hashlib.sha256(raw).hexdigest() == asset['asset_sha256'] and
                    bytes_fingerprint(raw) == asset['fingerprint'], 'public_final_asset_bytes_mismatch')
        # Last read occurs after source fetch and external checkpoint verification.
        last = client.read_snapshot(plan['scope']['identity']['product_id'])
        validate_snapshot(last, now=now or utcnow())
        require(protection(last, include_updated=True) == protection(plan['before'], include_updated=True), 'last_moment_snapshot_drift')
        validate_scope(plan['scope'], last, now or utcnow())
        journal.update(state='write_started', write_attempts=1, write_started_at=utcnow().isoformat())
        atomic_json(journal_path, journal)
        try:
            client.append_once(plan['scope']['identity']['product_id'], plan['additions'])
        except BaseException as error:
            # A timeout/error response may follow a successful append. NEVER retry.
            journal.update(state='write_unknown', error=type(error).__name__)
            atomic_json(journal_path, journal)
            if not isinstance(error, Exception):
                raise
            return result('write_unknown', plan, writes=1, reason=type(error).__name__)
        journal['state'] = 'verification_pending'
        atomic_json(journal_path, journal)
        output = None
        for index in range(polls):
            output = reconcile(plan, client)
            if output['state'] == 'reconciled_noop':
                break
            if index + 1 < polls:
                pause(2)
        journal['state'] = 'verified' if output['state'] == 'reconciled_noop' else 'verification_pending'
        journal['last_readback'] = output
        atomic_json(journal_path, journal)
        return result(journal['state'], plan, writes=1, readback=output)


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--scope', required=True)
    prepare.add_argument('--snapshot')
    prepare.add_argument('--read-live', action='store_true')
    prepare.add_argument('--output-dir', required=True)
    restore = commands.add_parser('reconcile-artifact')
    for argument in ('artifact-id', 'artifact-digest', 'repository', 'expected-plan-digest', 'expected-shop', 'expected-product'):
        restore.add_argument('--' + argument, required=True)
    for name in ('execute', 'reconcile'):
        command = commands.add_parser(name)
        command.add_argument('--plan', required=True)
        command.add_argument('--journal', required=True)
        command.add_argument('--expected-plan-digest', required=True)
        if name == 'execute':
            command.add_argument('--apply', action='store_true')
            command.add_argument('--artifact-id')
            command.add_argument('--artifact-digest')
    for command in (prepare, commands.choices['execute'], commands.choices['reconcile']):
        command.add_argument('--manifest', required=True)
        command.add_argument('--evidence-root', required=True)
        command.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY'))
        command.add_argument('--run-id', default=os.environ.get('GITHUB_RUN_ID'))
        command.add_argument('--run-attempt', default=os.environ.get('GITHUB_RUN_ATTEMPT'))
        command.add_argument('--code-sha', default=os.environ.get('GITHUB_SHA'))
        ref = os.environ.get('GITHUB_WORKFLOW_REF', '')
        workflow = re.search(r'/(\.github/workflows/[^@]+)@', ref)
        command.add_argument('--workflow-path', default=workflow.group(1) if workflow else None)
    args = parser.parse_args()
    try:
        if args.command == 'reconcile-artifact':
            backend = GitHubCheckpoint(os.environ.get('GITHUB_TOKEN'), args.artifact_id, args.artifact_digest)
            plan, _ = backend.restore(args.repository, expected_plan_digest=args.expected_plan_digest,
                                      expected_shop=args.expected_shop, expected_product=args.expected_product)
            client = ShopifyClient.from_environment(plan['scope']['transport_shop'])
            output = reconcile(plan, client)
            print(json.dumps(output, ensure_ascii=False))
            return 0 if output['state'] == 'reconciled_noop' else 2
        manifest = read_json(args.manifest)
        if args.command == 'prepare':
            scope = read_json(args.scope)
            require(bool(args.read_live) != bool(args.snapshot), 'choose_snapshot_or_read_live')
            if args.read_live:
                client = ShopifyClient.from_environment(scope.get('transport_shop'))
                snapshot = client.read_snapshot(scope['identity']['product_id'])
            else:
                snapshot = read_json(args.snapshot)
            plan = build_reviewed_plan(scope, manifest, args.evidence_root, snapshot)
            journal = make_journal(plan, **{k: getattr(args, k) for k in
                ('repository', 'run_id', 'run_attempt', 'code_sha', 'workflow_path')})
            directory = Path(args.output_dir)
            require(not (directory / 'plan.json').exists() and not (directory / 'journal.json').exists(), 'checkpoint_files_already_exist')
            atomic_json(directory / 'plan.json', plan)
            atomic_json(directory / 'journal.json', journal)
            output = result('prepared_dry_run' if plan['additions'] else 'noop', plan,
                            artifact_name=journal['artifact_name'], additions=len(plan['additions']), writes=0)
        else:
            plan = read_json(args.plan)
            validate_plan_digest(plan, args.expected_plan_digest)
            if args.command == 'execute' and not args.apply:
                output = execute_reviewed_plan(plan, manifest=manifest, root=args.evidence_root,
                                              expected_plan_digest=args.expected_plan_digest)
            else:
                client = ShopifyClient.from_environment(plan['scope'].get('transport_shop'))
                if args.command == 'reconcile':
                    output = reconcile(plan, client, args.journal)
                else:
                    journal = read_json(args.journal)
                    require(all(str(getattr(args, k)) == str(journal.get(k)) for k in
                        ('repository', 'run_id', 'run_attempt', 'code_sha', 'workflow_path')), 'execution_run_context_mismatch')
                    checkpoint = (GitHubCheckpoint(os.environ.get('GITHUB_TOKEN'), args.artifact_id, args.artifact_digest)
                                  if plan['additions'] and journal.get('state') == 'prepared' else None)
                    output = execute_reviewed_plan(plan, manifest=manifest, root=args.evidence_root,
                        expected_plan_digest=args.expected_plan_digest, client=client, journal_path=args.journal,
                        checkpoint=checkpoint, apply=True)
        print(json.dumps(output, ensure_ascii=False))
        return 0 if output['state'] in {'prepared_dry_run', 'dry_run', 'noop', 'verified', 'reconciled_noop'} else 2
    except (Hold, ValueError, TypeError, KeyError, OSError) as error:
        print(json.dumps({'state': 'hold', 'reason': str(error) if isinstance(error, Hold) else type(error).__name__,
                          'gallery_complete': False, 'publication_allowed': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(cli())
