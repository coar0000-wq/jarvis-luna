#!/usr/bin/env python3
"""Separate, approval-only Daiso discovery storage. No operating-product writes.

Queue names/categories are selection hints only. A candidate is saved only after
an actual, current detail/search observation supplies identity, price and URL.
Legacy crawl.visited is deliberately not an input: it includes quota-discarded
products that were never admitted to a comparison pool.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from urllib.parse import parse_qs, urlsplit

UTC = timezone.utc
DISCOVERY_BUCKETS = {'스킨케어', '마스크팩', '클렌징', '메이크업', '헤어케어', '바디케어'}
PRODUCT_PATH = '/pd/pdr/SCR_PDR_0001'
DISCOVERY_SKIP_REASONS = (
    'malformed_queue_row', 'duplicate_or_missing_identity', 'operating_identity',
    'parked_exclusion', 'unknown_or_non_core_bucket', 'invalid_detail_url',
    'legal_exclusion', 'previously_rejected', 'failure_cooldown',
    'candidate_recently_verified',
)


def discovery_skip_counts():
    # Per-attempt counts must retain their schema when an old nonzero becomes 0.
    # Omitting a zero incorrectly looks like a source-field deletion at publish.
    return dict.fromkeys(DISCOVERY_SKIP_REASONS, 0)


def timestamp(value):
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and ('T' in value or ' ' in value):
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        raise ValueError('candidate observation timestamp missing')
    if result.tzinfo is None:
        raise ValueError('candidate timestamp requires timezone')
    return result.astimezone(UTC)


def now_utc(value=None):
    return timestamp(value) if value is not None else datetime.now(UTC)


def product_id(value):
    return str(value or '').strip()


def detail_url_valid(url, pd_no):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and parsed.hostname == 'www.daisomall.co.kr'
                and parsed.path == PRODUCT_PATH and not parsed.username
                and parse_qs(parsed.query).get('pdNo') == [str(pd_no)])
    except (ValueError, TypeError):
        return False


def pool_document(document=None):
    if document is None:
        document = {'schema_version': 1, 'items': {}}
    if not isinstance(document, dict) or document.get('schema_version') != 1:
        raise ValueError('invalid candidate pool schema')
    if not isinstance(document.get('items'), dict):
        raise ValueError('candidate pool items must be an object')
    result = deepcopy(document)
    result.update(purpose='comparison_only', approval_required=True,
                  may_replace_operating_products=False, may_publish=False)
    return result


def state_document(document=None):
    if document is None:
        document = {'schema_version': 1, 'observations': {}}
    if not isinstance(document, dict) or document.get('schema_version') != 1:
        raise ValueError('invalid candidate observation schema')
    if not isinstance(document.get('observations'), dict):
        raise ValueError('candidate observations must be an object')
    return deepcopy(document)


def select_discovery(queue, operating_ids, pool=None, state=None, *, now=None,
                     allowed_buckets=DISCOVERY_BUCKETS, excluded_name=None, excluded_ids=()):
    """Round-robin known beauty buckets, new identities before stale candidates.

    No operational quotas or legacy visited records suppress discovery. Existing
    operating identities, legal exclusions, and non-beauty/unknown queue hints
    are skipped before a request. Failed observations cool down for 24 hours.
    Accepted candidates can be revalidated after 72 hours, after unseen ones.
    """
    clock = now_utc(now)
    pool, state = pool_document(pool), state_document(state)
    if not isinstance(queue, dict) or not isinstance(queue.get('items'), list):
        return [], {'mode': 'candidate_discovery', 'reason': 'queue_missing',
                    'new_identities': 0, 'revalidation_identities': 0, 'skipped': discovery_skip_counts()}
    operating = {product_id(x) for x in operating_ids}
    parked = {product_id(x) for x in excluded_ids}
    skipped, seen, fresh, recheck = discovery_skip_counts(), set(), {}, {}

    def skip(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    for row in queue['items']:
        if not isinstance(row, dict):
            skip('malformed_queue_row'); continue
        pd_no = product_id(row.get('pdNo'))
        bucket = row.get('예상버킷')
        name = str(row.get('이름_list') or '').strip()
        url = row.get('url')
        if not pd_no or pd_no in seen:
            skip('duplicate_or_missing_identity'); continue
        seen.add(pd_no)
        if pd_no in operating:
            skip('operating_identity'); continue
        if pd_no in parked:
            skip('parked_exclusion'); continue
        if bucket not in allowed_buckets or not name:
            skip('unknown_or_non_core_bucket'); continue
        if not detail_url_valid(url, pd_no):
            skip('invalid_detail_url'); continue
        if excluded_name and excluded_name(name):
            skip('legal_exclusion'); continue
        previous = state['observations'].get(pd_no) or {}
        if previous.get('status') in {'excluded', 'not_beauty', 'non_core', 'invalid_observation'}:
            skip('previously_rejected'); continue
        if previous.get('status') in {'failed', 'http_error', 'parse_failed'}:
            try:
                if clock - timestamp(previous.get('at')) < timedelta(hours=24):
                    skip('failure_cooldown'); continue
            except (ValueError, TypeError, OverflowError):
                pass
        existing = pool['items'].get(pd_no)
        target = fresh
        if isinstance(existing, dict):
            try:
                age = clock - timestamp(existing.get('collected_at'))
                if age < timedelta(hours=72):
                    skip('candidate_recently_verified'); continue
            except (ValueError, TypeError, OverflowError):
                pass
            target = recheck
        target.setdefault(bucket, []).append((pd_no, url))

    def interleave(groups):
        # First observed list order is preserved inside each bucket.
        ordered, buckets = [], sorted(groups)
        size = max((len(x) for x in groups.values()), default=0)
        for i in range(size):
            for bucket in buckets:
                if i < len(groups[bucket]):
                    ordered.append(groups[bucket][i])
        return ordered

    unseen, stale = interleave(fresh), interleave(recheck)
    return unseen + stale, {'mode': 'candidate_discovery', 'reason': 'comparison_pool_not_operating_quota',
                            'legacy_visited_ignored': True, 'operating_limit_unchanged': True,
                            'new_identities': len(unseen), 'revalidation_identities': len(stale),
                            'eligible_buckets': sorted(set(fresh) | set(recheck)), 'skipped': skipped}


def upsert_candidate(document, product, *, operating_ids, execution_id, now=None):
    """Store only observed facts. Never promote a candidate or carry approvals."""
    clock = now_utc(now)
    result = pool_document(document)
    if not isinstance(product, dict):
        raise ValueError('candidate must be an observed product')
    pd_no = product_id(product.get('pd_no'))
    if not pd_no or pd_no in {product_id(x) for x in operating_ids}:
        raise ValueError('operating identity cannot enter discovery pool')
    if product.get('bucket') not in DISCOVERY_BUCKETS:
        raise ValueError('candidate bucket outside approved discovery scope')
    if not str(product.get('name') or '').strip() or not detail_url_valid(product.get('url'), pd_no):
        raise ValueError('candidate identity/URL not verified')
    price = product.get('price_krw')
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        raise ValueError('candidate observed price missing')
    captured = timestamp(product.get('collected_at'))
    if captured > clock + timedelta(minutes=5) or clock - captured > timedelta(hours=6):
        raise ValueError('candidate observation stale or future')
    if not execution_id:
        raise ValueError('candidate execution identity missing')
    previous = result['items'].get(pd_no)
    new = previous is None
    row = deepcopy(product)
    for key in ('registerable', 'ready', 'approved', 'approval', 'canonical_product_id'):
        row.pop(key, None)
    row.update(candidate_status='pending_comparison', approval_required=True,
               may_replace_operating_products=False, may_publish=False,
               first_seen_at=(previous or {}).get('first_seen_at') or captured.isoformat(),
               last_seen_at=captured.isoformat(),
               observation={'execution_id': execution_id,
                            'method': 'daiso_search_fallback' if product.get('fallback_used') else 'daiso_detail',
                            'url': product['url'], 'captured_at': captured.isoformat()})
    result['items'][pd_no] = row
    result['count'] = len(result['items'])
    result['generated_at'] = clock.isoformat()
    return result, new


def record_observation(document, pd_no, status, *, at, reason='', execution_id=''):
    result = state_document(document)
    result['observations'][product_id(pd_no)] = {
        'status': status, 'at': timestamp(at).isoformat(), 'reason': str(reason),
        'execution_id': execution_id,
    }
    result['generated_at'] = timestamp(at).isoformat()
    return result


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def canonical_digest(document):
    return hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()
