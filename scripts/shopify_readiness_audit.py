"""Private offline readiness projection. Never publish this evidence report."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json

from payment_fees import PAYMENT_FEE_RATE, PAYMENT_FEE_SOURCE, profit_flags

MAX_NUMBER = Decimal('1e12')
MIN_NONZERO = Decimal('1e-6')


def _number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not n.is_finite() or n < 0 or n > MAX_NUMBER or (n != 0 and n < MIN_NONZERO):
        return None
    return n if not positive or n > 0 else None


def _time(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp if stamp.utcoffset() is not None else None
    except (ValueError, TypeError, AttributeError):
        return None


def observation(raw, now, max_age_seconds):
    raw = raw if isinstance(raw, dict) else {}
    result = deepcopy(raw)
    stamp = _time(raw.get('captured_at'))
    age = (now - stamp).total_seconds() if stamp else None
    result['freshness'] = ('unknown' if age is None else 'future' if age < 0 else
                           'stale' if age > max_age_seconds else 'fresh')
    result['usable'] = bool(raw.get('value') is not None and isinstance(raw.get('source'), str)
                            and raw['source'].strip() and result['freshness'] == 'fresh')
    return result


def project(snapshot, *, now, max_age_seconds=172800):
    """Private JSON-safe report. Monetary inputs are KRW, same order and quantity.

    Customer shipping is revenue; seller shipping is cost. Shared fee is only a
    policy scenario, never a verified actual fee. Full profit remains unverified.
    """
    clock = _time(now)
    if clock is None or type(max_age_seconds) is not int or not 0 < max_age_seconds <= 172800:
        raise ValueError('timezone-aware now and bounded freshness required')
    if (not isinstance(snapshot, dict) or not isinstance(snapshot.get('variants'), list)
            or len(snapshot['variants']) > 10000):
        raise ValueError('snapshot with variants list required')
    canonical = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False)
    rows, seen = [], set()
    for row in snapshot['variants']:
        if not isinstance(row, dict) or not isinstance(row.get('variant_id'), str) or not row['variant_id'] or row['variant_id'] in seen:
            raise ValueError('unique nonempty string variant_id required')
        seen.add(row['variant_id'])
        facts = {k: observation(v, clock, max_age_seconds) for k, v in (row.get('facts') or {}).items()}

        def value(key):
            obs = facts.get(key, {})
            return obs.get('value') if obs.get('usable') else None

        def amount(key, positive=False):
            return _number(value(key), positive=positive)

        cost = amount('cost_krw', True)
        weight = amount('packed_weight_g', True)
        shipping = amount('seller_shipping_krw')
        collected = amount('customer_shipping_krw')
        other = amount('other_known_costs_krw')
        sale = amount('merchandise_revenue_krw', True)
        rate = Decimal(str(PAYMENT_FEE_RATE))
        reasons = [key + '_unknown_or_invalid' for key, val in [
            ('cost_krw', cost), ('packed_weight_g', weight), ('seller_shipping_krw', shipping),
            ('customer_shipping_krw', collected), ('other_known_costs_krw', other)] if val is None]
        floor = contribution = None
        if not reasons:
            floor = max(Decimal(0), (cost + shipping + other + Decimal(3000)) / (1-rate) - collected)
            floor = int(floor.to_integral_value(rounding=ROUND_CEILING))
            if sale is not None:
                contribution = float((sale + collected) * (1-rate) - cost - shipping - other)
        tracked, qty = value('inventory_tracked'), amount('inventory_quantity')
        inventory = ('untracked_not_stockout' if tracked is False else
                     'tracked_zero_quantity' if tracked is True and qty == 0 else
                     'positive_quantity_observed' if tracked is True and qty is not None and qty > 0 else 'unknown')
        hold, published, public_price = value('hold_reason'), value('published'), amount('public_price', True)
        findings = list(reasons)
        hold_obs = facts.get('hold_reason', {})
        if hold_obs.get('value') and hold_obs.get('freshness') == 'stale':
            findings.append('stale_hold_record_review_required')
        if isinstance(hold, str):
            if 'DRAFT ONLY' in hold and value('admin_status') == 'ACTIVE':
                findings.append('admin_active_with_draft_only_hold_claim')
            native = value('admin_price_unconverted')
            if ('Zero prices are placeholders' in hold and isinstance(native, dict)
                    and native.get('currencyCode') and _number(native.get('amount'), positive=True) is not None):
                findings.append('admin_positive_price_with_zero_placeholder_hold_claim')
            updated = _time(hold_obs.get('source_updated_at'))
            if updated and (clock - updated).total_seconds() > max_age_seconds:
                findings.append('hold_source_update_stale_review_required')
        if hold and published is True:
            findings.append('hold_publication_mismatch_review_required')
        if hold == 'zero_price' and public_price is not None:
            findings.append('zero_price_hold_contradicts_public_price')
        rows.append({'variant_id': row['variant_id'], 'facts': facts, 'findings': findings,
                     'inventory_observation': inventory, 'purchase_availability': 'unknown',
                     'economics': {'currency': 'KRW', 'minimum_contribution_krw': 3000,
                         'assumed_fee_rate': float(rate), 'fee_source': PAYMENT_FEE_SOURCE,
                         'fee_status': 'user_assumption_not_verified', 'minimum_merchandise_price_krw': floor,
                         'modeled_contribution_krw': contribution, 'verified_actual_fee_rate': None,
                         'verified_actual_contribution_krw': None,
                         'modeled_margin_pct': (100 * contribution / float(sale + collected) if contribution is not None else None),
                         'status': 'incomplete' if reasons else 'scenario_only', **profit_flags()},
                     'stages': {stage: observation((row.get('stages') or {}).get(stage), clock, max_age_seconds)
                                for stage in ('proposed', 'applied', 'verified', 'measured')}})
    public = {k: observation(v, clock, max_age_seconds) for k, v in (snapshot.get('public_observations') or {}).items()}
    channels = {}
    for name in ('shopify_catalog', 'google_merchant_center', 'google_search_console'):
        obs = observation((snapshot.get('channels') or {}).get(name), clock, max_age_seconds)
        channels[name] = {**obs, 'eligibility': 'unknown', 'verification': 'caller_snapshot_only',
                          'reported_eligibility': (obs.get('value') if obs['usable'] and obs.get('authenticated') is True
                          and obs.get('value') in ('eligible', 'ineligible') else 'unknown')}
    analytics = observation(snapshot.get('analytics'), clock, max_age_seconds)
    vals = analytics.get('value') if analytics['usable'] and isinstance(analytics.get('value'), dict) else {}
    sessions, orders, converted = vals.get('human_sessions'), vals.get('human_orders'), vals.get('human_converted_sessions')
    def valid(x):
        return type(x) is int and 0 <= x <= MAX_NUMBER
    denominator = valid(sessions) and sessions > 0 and vals.get('same_cohort') is True and vals.get('same_period') is True
    cvr = converted / sessions if denominator and valid(converted) and converted <= sessions else None
    orders_per_session = orders / sessions if denominator and valid(orders) else None
    return {'schema_version': 1, 'generated_at': now, 'snapshot_sha256': hashlib.sha256(canonical.encode()).hexdigest(),
            'status': 'local_review_only', 'variants': rows, 'public_observations': public, 'channels': channels,
            'analytics': {**analytics, 'human_conversion_rate': cvr, 'orders_per_human_session': orders_per_session},
            'guards': {'execution_enabled': False, 'publication_authorized': False, 'safety_cleared': False, 'advisory_only': True},
            'interpretation': 'Schema/sitemap observations do not prove channel eligibility, indexing, sales or safety.'}
