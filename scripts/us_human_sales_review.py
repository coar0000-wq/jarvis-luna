#!/usr/bin/env python3
"""Offline US-human aggregate audit and non-executable English wording review.

No collector, Shopify writer, price change, publication payload or approval path.
Only explicit local inputs are read. CLI output must be outside this checkout.
Source-byte matching establishes provenance, never independent verification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from html import escape
import json
import os
from pathlib import Path
import re
import sys

try:
    from ai_shopping_copy import append_shopping_copy, banned_expressions
except ModuleNotFoundError:
    from .ai_shopping_copy import append_shopping_copy, banned_expressions

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 1_000_000
METRICS = {
    'sessions': 'sessions', 'add_to_cart_sessions': 'sessions',
    'checkout_sessions': 'sessions', 'converted_sessions': 'sessions',
    'pageviews': 'pageviews', 'product_views': 'product_views',
}
GUARDS = {
    'artifact_kind': 'non_executable_us_sales_review', 'non_executable': True,
    'review_only': True, 'business_approval': False,
    'eligible_for_shopify_import': False, 'publication_allowed': False,
    'shopify_write_performed': False, 'verified': False,
}
PERIOD_KEYS = {'start', 'end', 'timezone'}
QUERY_KEYS = {'status', 'coverage', 'unit', 'rows', 'shop', 'period'}
# Titles are identity evidence, not approval of quantities or marketing claims.
# This small review path has no label/quantity/efficacy verifier: hold, do not strip.
TITLE_REVIEW_TOKENS = re.compile(
    r'\d+(?:[.,]\d+)?\s*(?:%|(?:fl\.?\s*)?oz\b|[mk]?g\b|[mk]?l\b|mcg\b|'
    r'pcs?\b|pieces?\b|count\b|ct\b|[- ]?packs?\b|hours?\b|days?\b)|'
    r'\bpack\s+of\s+\d|\d\s*[x×]\s*\d|'
    r'\b(?:brighten\w*|whiten\w*|hydrat\w*|moisturi[sz]\w*|firming|lifting|'
    r'soothing|anti[- ]?(?:aging|wrinkle)|clinically|proven|guaranteed|'
    r'authentic|authorized|certified|official|shipping|delivery)\b', re.I)


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _clock(value):
    _require(isinstance(value, str) and len(value) <= 40, 'invalid_timestamp')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('invalid_timestamp') from None
    _require(result.tzinfo is not None, 'timestamp_requires_offset')
    return result


def _shop(value):
    _require(isinstance(value, dict), 'missing_expected_shop')
    gid, domain = value.get('shop_gid'), value.get('canonical_domain')
    _require(isinstance(gid, str) and re.fullmatch(r'gid://shopify/Shop/[1-9][0-9]*', gid),
             'invalid_shop_gid')
    _require(isinstance(domain, str) and len(domain) <= 253 and
             re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', domain),
             'invalid_canonical_domain')
    return {'shop_gid': gid, 'canonical_domain': domain}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def _decode(raw):
    _require(isinstance(raw, bytes) and len(raw) <= MAX_BYTES, 'source_missing_or_too_large')
    try:
        result = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError('invalid_source_json') from None
    _require(isinstance(result, dict), 'source_requires_object')
    return result


def _admit(envelope, raw, expected_shop, now):
    _require(isinstance(envelope, dict), 'input_not_supplied')
    _require(type(envelope.get('schema_version')) is int and envelope['schema_version'] == 1,
             'unsupported_schema')
    shop = _shop(expected_shop)
    _require(_shop(envelope.get('shop')) == shop, 'shop_mismatch')
    observed = _clock(envelope.get('observed_at'))
    _require(observed <= now, 'future_observation')
    source = envelope.get('source')
    _require(isinstance(source, dict), 'missing_original_source')
    ref, digest, kind = source.get('ref'), source.get('raw_sha256'), source.get('kind')
    _require(isinstance(ref, str) and 0 < len(ref.strip()) <= 500, 'missing_original_source')
    _require(kind in ('local_snapshot', 'source_transcription'), 'invalid_source_kind')
    if kind == 'source_transcription':
        _require(raw is None and digest is None, 'transcription_cannot_claim_original_bytes')
        payload = envelope.get('transcribed_payload')
        _require(isinstance(payload, dict), 'transcribed_payload_missing')
    else:
        _require(isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest), 'invalid_source_hash')
        payload = _decode(raw)
        _require(hashlib.sha256(raw).hexdigest() == digest, 'source_hash_mismatch')
    _require(payload.get('shop') == shop, 'source_shop_mismatch')
    _require(payload.get('observed_at') == envelope.get('observed_at'), 'source_observation_mismatch')
    try:
        observed_kst = observed.astimezone(timezone(timedelta(hours=9))).isoformat()
    except (OverflowError, ValueError):
        raise ValueError('invalid_timestamp_range') from None
    return payload, {
        'shop': shop, 'observed_at': observed.isoformat(),
        'observed_at_kst': observed_kst,
        'source_sha256': digest, 'original_source_reference_present': True,
        'source_bytes_matched': kind == 'local_snapshot', 'verified': False,
        'evidence_status': ('source_transcription' if kind == 'source_transcription'
                            else 'source_attributed_not_independently_verified'),
    }


def _unavailable(reason, unit=None):
    result = {'status': 'unavailable', 'value': None, 'reason': reason, 'verified': False}
    if unit:
        result['unit'] = unit
    return result


def _metric(query, unit, shop, period):
    try:
        _require(isinstance(query, dict), 'query_not_supplied')
        _require(query.get('status') == 'ok', 'query_failed_or_unavailable')
        _require(set(query) == QUERY_KEYS, 'query_fields_or_scope_missing')
        _require(query['shop'] == shop, 'query_shop_mismatch')
        _require(query['period'] == period, 'query_period_mismatch')
        _require(query.get('coverage') == 'complete', 'partial_or_unknown_coverage')
        _require(query.get('unit') == unit, 'metric_unit_mismatch')
        rows = query.get('rows')
        _require(isinstance(rows, list) and len(rows) <= 1000, 'invalid_aggregate_rows')
        seen, us_human = set(), None
        for row in rows:
            # Aggregates only. Customer/session/order identifiers never enter this contract.
            _require(isinstance(row, dict) and set(row) == {'country', 'traffic', 'value'},
                     'unexpected_aggregate_fields')
            country, traffic, count = row['country'], row['traffic'], row['value']
            _require(isinstance(country, str) and re.fullmatch(r'[A-Z]{2}|UNKNOWN', country),
                     'invalid_country_dimension')
            _require(traffic in ('human', 'bot', 'unknown'), 'invalid_traffic_dimension')
            _require(type(count) is int and 0 <= count <= 10**12, 'invalid_count')
            key = (country, traffic)
            _require(key not in seen, 'duplicate_aggregate_scope')
            seen.add(key)
            if key == ('US', 'human'):
                us_human = count
        # Missing US rows are unknown, including in a declared complete response.
        _require(us_human is not None, 'explicit_us_human_row_missing')
        return {'status': 'reported', 'value': us_human, 'unit': unit,
                'verified': False, 'reason': None}
    except (ValueError, TypeError) as error:
        return _unavailable(str(error) if isinstance(error, ValueError) else 'invalid_query', unit)


def audit_us_humans(envelope=None, raw_source=None, *, expected_shop=None, now=None):
    result = {
        'target_country': 'US', 'traffic': 'human',
        'excluded': ['bot', 'unknown_traffic', 'KR', 'all_other_countries'],
        'metrics': {name: _unavailable('input_not_supplied', unit) for name, unit in METRICS.items()},
        'conversion_rate': None, 'conversion_rate_unit': 'fraction',
        'conversion_rate_reason': 'input_not_supplied', 'verified': False,
    }
    try:
        payload, provenance = _admit(envelope, raw_source, expected_shop,
                                     now or datetime.now(timezone.utc))
        period = envelope.get('period')
        _require(isinstance(period, dict) and set(period) == PERIOD_KEYS, 'invalid_period_fields')
        _require(period.get('timezone') == 'Asia/Seoul',
                 'period_requires_asia_seoul')
        start, end = _clock(period.get('start')), _clock(period.get('end'))
        _require(start.utcoffset() == end.utcoffset() == timedelta(hours=9), 'period_requires_kst_offset')
        _require(start < end <= _clock(envelope['observed_at']), 'invalid_period_order')
        _require(payload.get('period') == period, 'source_period_mismatch')
        queries = payload.get('queries')
        _require(isinstance(queries, dict), 'missing_queries')
        safe_period = {key: period[key] for key in ('start', 'end', 'timezone')}
        result.update(provenance=provenance, period=safe_period, status='review_only')
        result['metrics'] = {name: _metric(queries.get(name), unit, provenance['shop'], safe_period)
                             for name, unit in METRICS.items()}
        sessions = result['metrics']['sessions']['value']
        # Session funnel counts must be session counts; orders are never a substitute.
        for name in ('add_to_cart_sessions', 'checkout_sessions', 'converted_sessions'):
            value = result['metrics'][name]['value']
            if sessions is not None and value is not None and value > sessions:
                result['metrics'][name] = _unavailable('funnel_count_exceeds_sessions', 'sessions')
        converted = result['metrics']['converted_sessions']['value']
        if sessions is None:
            result['conversion_rate_reason'] = 'us_human_sessions_unavailable'
        elif sessions == 0:
            result['conversion_rate_reason'] = 'zero_us_human_sessions'
        elif converted is None:
            result['conversion_rate_reason'] = 'us_human_converted_sessions_unavailable'
        else:
            result['conversion_rate'] = converted / sessions
            result['conversion_rate_reason'] = None
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        reason = str(error) if isinstance(error, ValueError) else 'invalid_audit_input'
        result.update(status='unavailable', conversion_rate_reason=reason)
        result['metrics'] = {name: _unavailable(reason, unit) for name, unit in METRICS.items()}
    return result


def wording_review(envelope=None, raw_source=None, *, expected_shop=None, now=None, banned_terms=None):
    result = dict(GUARDS, status='unavailable', wording=None)
    try:
        payload, provenance = _admit(envelope, raw_source, expected_shop,
                                     now or datetime.now(timezone.utc))
        envelope_keys = {'schema_version', 'shop', 'observed_at', 'source', 'product_gid',
                         'english_identity_reviewed', 'transcribed_payload'} | set(GUARDS)
        _require(not set(envelope) - envelope_keys, 'unreviewed_product_context_or_holds')
        _require(set(payload) == {'shop', 'observed_at', 'product'}, 'unreviewed_source_context_or_holds')
        _require(envelope.get('english_identity_reviewed') is True, 'english_identity_not_reviewed')
        product = payload.get('product')
        _require(isinstance(product, dict), 'product_not_supplied')
        _require(set(product) == {'id', 'title', 'status'}, 'unreviewed_product_details_or_warnings')
        product_id = product.get('id')
        _require(isinstance(product_id, str) and re.fullmatch(r'gid://shopify/Product/[1-9][0-9]*', product_id),
                 'invalid_product_gid')
        _require(product_id == envelope.get('product_gid'), 'product_mismatch')
        title = product.get('title')
        _require(isinstance(title, str) and 1 <= len(title) <= 70 and title == ' '.join(title.split())
                 and re.search(r'[A-Za-z]', title) and all(32 <= ord(c) <= 126 for c in title)
                 and not re.search(r'[<>&]|placeholder|\bTODO\b|\bTBD\b', title, re.I),
                 'english_identity_missing_or_unsafe')
        _require(not TITLE_REVIEW_TOKENS.search(title), 'title_quantity_or_claim_requires_review')
        _require(product.get('status') in ('ACTIVE', 'DRAFT', 'ARCHIVED'), 'invalid_observed_status')
        _require(isinstance(banned_terms, (list, tuple)) and len(banned_terms) > 0 and
                 all(isinstance(term, str) and term.strip() for term in banned_terms), 'claim_rules_unavailable')
        wording = append_shopping_copy({
            'seo_title': title,
            'seo_description': f'Explore {title}. Review the product details and selected option before ordering.',
            'description_html': '<p>' + escape(title) + '.</p>',
            'search_phrases': [title],
            'channel_text': f'Take a closer look at {title}. See the product page for details.',
        }, title)
        _require(not banned_expressions(wording, banned_terms), 'claim_rule_match')
        result.update(status='prepared_for_review', provenance=provenance,
                      product_reference={'product_gid': product_id, 'observed_status': product['status']},
                      wording=wording,
                      application_holds=['business_approval_required', 'physical_label_and_safety_review_required',
                                         'rights_and_shipping_review_required', 'no_public_edit_authorization'],
                      omissions=['net_contents', 'efficacy', 'ingredients', 'directions', 'warnings',
                                 'shipping', 'rights', 'price', 'sales_or_reviews', 'search_volume'],
                      identity_limit=('Verbatim source-listed English title only; proposed translations require '
                                      'a separate review. Name tokens do not substantiate claims.'))
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        result['reason'] = str(error) if isinstance(error, ValueError) else 'invalid_product_input'
    return result


def build_review(audit=None, product=None, *, audit_source=None, product_source=None,
                 expected_shop=None, now=None, banned_terms=None):
    """Pure projection. Never copies unrecognized input keys or customer records."""
    stamp = now or datetime.now(timezone.utc)
    return dict(GUARDS, schema_version=1, prepared_at=stamp.isoformat(),
                measurement=audit_us_humans(audit, audit_source, expected_shop=expected_shop, now=stamp),
                copy_review=wording_review(product, product_source, expected_shop=expected_shop,
                                           now=stamp, banned_terms=banned_terms))


def _local_path(path):
    target = Path(path).absolute()
    _require(not any(part.is_symlink() for part in (target, *target.parents)), 'symlink_path_not_allowed')
    return target.resolve()


def _git_checkout(directory):
    marker = directory / '.git'
    # Sandboxes may place empty, read-only .git guards at /tmp and workspace
    # roots. They are not repositories. git init creates HEAD and config.
    return (marker.is_file() or marker.is_symlink() or
            marker.is_dir() and any((marker / name).exists() for name in ('HEAD', 'config')))


def _read(path):
    if not path:
        return None
    target = _local_path(path)
    _require(target.is_file(), 'input_requires_regular_file')
    with target.open('rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    _require(len(raw) <= MAX_BYTES, 'input_too_large')
    return raw


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('audit', 'audit-source', 'product', 'product-source', 'shop-gid', 'canonical-domain', 'output'):
        parser.add_argument('--' + name)
    args = parser.parse_args(argv)
    try:
        audit_raw, product_raw = _read(args.audit), _read(args.product)
        # Missing wording rules must not disable a separate measurement audit.
        terms = None
        if product_raw:
            try:
                groups = _decode(_read(ROOT / 'data/us_claim_rules.json')).get('banned')
                terms = ([term for values in groups.values() for term in values]
                         if isinstance(groups, dict) and all(isinstance(v, list) for v in groups.values()) else None)
            except (OSError, ValueError):
                pass
        result = build_review(_decode(audit_raw) if audit_raw else None,
                              _decode(product_raw) if product_raw else None,
                              audit_source=_read(args.audit_source), product_source=_read(args.product_source),
                              expected_shop={'shop_gid': args.shop_gid, 'canonical_domain': args.canonical_domain},
                              banned_terms=terms)
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        if args.output:
            output = _local_path(args.output)
            _require(not output.is_relative_to(ROOT), 'output_must_be_outside_checkout')
            _require(not any(_git_checkout(parent) for parent in output.parents),
                     'output_must_be_outside_git_checkouts')
            # Exclusive creation prevents replacing source files, snapshots or previous reviews.
            descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                handle.write(text)
        else:
            print(text, end='')
        return 0
    except (OSError, ValueError, TypeError, RuntimeError, OverflowError):
        # Do not echo file paths, source records, tokens, or customer data on errors.
        print('Review input/output rejected; check local files, schema and a new output path.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
