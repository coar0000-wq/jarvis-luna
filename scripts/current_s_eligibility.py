#!/usr/bin/env python3
"""Current registration evidence, separate from retained historical S grades.

Pure offline evaluation. Never writes source observations or substitutes a build
clock for collected_at. Consumers re-read this evidence, not saved eligibility.
"""
from copy import deepcopy
from collections import Counter
from datetime import timedelta
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

from daiso_candidate_store import detail_url_valid, now_utc, timestamp

MARKET_TTL_HOURS = 48
PRODUCT_TTL_HOURS = 72
FUTURE_TOLERANCE_MINUTES = 5
BLOCKER = 'current_s_evidence'


def observation_reason(value, clock, ttl_hours, prefix):
    try:
        age = clock - timestamp(value)
    except (ValueError, TypeError, OverflowError):
        return prefix + '_timestamp_missing_or_invalid'
    if age < -timedelta(minutes=FUTURE_TOLERANCE_MINUTES):
        return prefix + '_timestamp_future'
    if age > timedelta(hours=ttl_hours):
        return prefix + '_stale'
    return ''


def source_url_valid(value):
    try:
        parsed = urlsplit(value if isinstance(value, str) else '')
        return bool(parsed.scheme == 'https' and parsed.hostname and not parsed.username
                    and parsed.path.strip('/'))
    except ValueError:
        return False


def current_channels(dashboard, now=None):
    """Only explicitly healthy, trusted, timestamped product-level sources."""
    from daiso.score_shopify_demand import MATCH_CHANNELS
    clock = now_utc(now)
    document = dashboard if isinstance(dashboard, dict) else {}
    sources = document.get('global_channels')
    statuses = document.get('global_channels_status')
    sources = sources if isinstance(sources, dict) else {}
    statuses = statuses if isinstance(statuses, dict) else {}
    channels, evidence, excluded = {}, [], {}
    for channel, rows in sources.items():
        if channel not in MATCH_CHANNELS or not isinstance(rows, list):
            continue
        meta = statuses.get(channel)
        meta = meta if isinstance(meta, dict) else {}
        reason = observation_reason(meta.get('collected_at'), clock, MARKET_TTL_HOURS, 'market_observation')
        if reason or meta.get('status') != 'ok' or meta.get('trust') not in ('verified', 'manual'):
            excluded[channel] = 'unverified_or_stale_source'
            continue
        usable = [deepcopy(row) for row in rows if isinstance(row, dict)
                  and source_url_valid(row.get('url'))
                  and str(row.get('product') or row.get('name') or '').strip()]
        if usable:
            channels[channel] = usable
            evidence.append({'channel': channel, 'collected_at': meta['collected_at'],
                             'count': len(usable), 'trust': meta['trust'], 'status': meta['status']})
        else:
            excluded[channel] = 'per_item_source_urls_missing'
    return channels, evidence, excluded


def market_universe(dashboard, now=None):
    """Shared with candidate comparison; no untimestamped historical price fallback."""
    from daiso.score_shopify_demand import extract_signals
    channels, evidence, excluded = current_channels(dashboard, now)
    prices = []
    for rows in channels.values():
        for row in rows:
            value = row.get('price') if row.get('price') is not None else row.get('price_usd')
            if isinstance(value, bool):
                continue
            try:
                value = float(value)
            except (ValueError, TypeError, OverflowError):
                continue
            if math.isfinite(value) and value > 0:
                prices.append({'name': str(row.get('product') or row.get('name')).lower(), 'price': value})
    return extract_signals(channels), prices, evidence, excluded


def assess_rows(rows, products, dashboard, *, now=None):
    """A historical S must independently satisfy S rules on fresh-only inputs.

    Historical quota/rank selection remains authoritative. This check never
    promotes an A, deletes an S, or transfers expired channel/US-listing points.
    A healthy independent channel is sufficient only if the same score/match or
    category-desk rules pass using its fresh evidence (including desk hit counts).
    """
    from daiso import score_shopify_demand as scorer
    clock = now_utc(now)
    signals, prices, evidence, excluded = market_universe(dashboard, clock)
    product_rows = products.get('products') if isinstance(products, dict) else products
    product_rows = product_rows if isinstance(product_rows, list) else []
    by_id = {}
    for product in product_rows:
        if isinstance(product, dict) and product.get('pd_no'):
            by_id.setdefault(str(product['pd_no']), []).append(product)
    canonical_counts = Counter(str(row.get('pd_no') or '') for row in rows if isinstance(row, dict))
    results = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        pd_no = str(row.get('pd_no') or '')
        sources = by_id.get(pd_no) or []
        product = sources[0] if len(sources) == 1 else {}
        reasons = []
        if not pd_no or canonical_counts[pd_no] != 1:
            reasons.append('canonical_identity_missing_or_ambiguous')
        if row.get('grade') != 'S':
            reasons.append('canonical_grade_not_s')
        if not product:
            reasons.append('product_observation_missing_or_ambiguous')
        else:
            reason = observation_reason(product.get('collected_at'), clock, PRODUCT_TTL_HOURS, 'product_observation')
            if reason:
                reasons.append(reason)
            if not detail_url_valid(product.get('url'), pd_no):
                reasons.append('product_observation_source_url_missing_or_invalid')
        if not evidence:
            reasons.append('verified_current_market_evidence_missing')
        fresh_score = None
        if product and evidence:
            try:
                fresh_score = scorer.score_one(product, signals, market_listings=prices)
                scorer.desk_promote([fresh_score])
                if fresh_score.get('grade') != 'S' or fresh_score.get('desk') not in scorer.DESK_NAME:
                    reasons.append('fresh_market_s_rules_not_met')
            except (ValueError, TypeError, OverflowError, AttributeError):
                reasons.append('current_scoring_inputs_invalid')
        results[pd_no] = {
            'eligible': not reasons,
            'reasons': reasons,
            'policy': 'market_48h_product_72h_future_tolerance_5m',
            'product_collected_at': product.get('collected_at'),
            'product_source_url': product.get('url'),
            'market_evidence': evidence,
            'excluded_market_sources': excluded,
            'fresh_shopify_score': fresh_score.get('shopify_score') if fresh_score else None,
            'fresh_s_rule': fresh_score.get('s_rule') if fresh_score else None,
            'fresh_us_market_hits': fresh_score.get('us_market_hits') if fresh_score else None,
            'fresh_global_match': fresh_score.get('best_global_match') if fresh_score else None,
        }
    return results


def _document(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeDecodeError):
        return {}


def assess_current(rows, root, *, now=None):
    if not rows:
        return {}
    data = Path(root) / 'data'
    return assess_rows(rows, _document(data / 'daiso_real/products.json'),
                       _document(data / 'dashboard_runtime.json'), now=now)
