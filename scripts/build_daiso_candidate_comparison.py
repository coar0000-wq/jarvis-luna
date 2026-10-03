#!/usr/bin/env python3
"""Compare separate Daiso discoveries with existing operating products, offline.

Scores reuse current deterministic demand rules. Only fresh timestamped market
observations with per-item URLs enter candidate comparison. No operating grade,
product, gate, shortlist, export or approval is written. Replacement is proposal
only, constrained to same category/form, and still requires evidence/approval.
"""
from copy import deepcopy
from datetime import timedelta
import json
import math
from pathlib import Path

from daiso_candidate_store import (pool_document, now_utc, timestamp, file_digest,
                                   canonical_digest)
from daiso.score_shopify_demand import (score_one, extract_signals, MATCH_CHANNELS,
                                       form_of, form_compatible)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
OUT = DATA / 'daiso_real' / 'candidate_comparison.json'


def market_universe(dashboard, now=None):
    clock = now_utc(now)
    channels, prices, evidence, excluded = {}, [], [], {}
    statuses = dashboard.get('global_channels_status') or {}
    for channel, rows in (dashboard.get('global_channels') or {}).items():
        if channel not in MATCH_CHANNELS or not isinstance(rows, list):
            continue
        meta = statuses.get(channel) or {}
        try:
            captured = timestamp(meta.get('collected_at'))
            age = clock - captured
            fresh = -timedelta(minutes=5) <= age <= timedelta(hours=48)
        except (ValueError, TypeError, OverflowError):
            fresh = False
        if not fresh or meta.get('status') != 'ok' or meta.get('trust') not in {'verified', 'manual'}:
            excluded[channel] = 'unverified_or_stale_source'
            continue
        usable = []
        for row in rows:
            if not isinstance(row, dict) or not str(row.get('url') or '').startswith('https://'):
                continue
            name = str(row.get('product') or row.get('name') or '').strip()
            if not name:
                continue
            usable.append(deepcopy(row))
            value = row.get('price')
            if value is None:
                value = row.get('price_usd')
            try:
                value = float(value)
            except (ValueError, TypeError, OverflowError):
                continue
            if math.isfinite(value) and value > 0:
                prices.append({'name': name.lower(), 'price': value})
        if usable:
            channels[channel] = usable
            evidence.append({'channel': channel, 'collected_at': captured.isoformat(),
                             'count': len(usable), 'trust': meta.get('trust')})
        else:
            excluded[channel] = 'per_item_source_urls_missing'
    return extract_signals(channels), prices, evidence, excluded


def build_comparison(pool, operating, dashboard, *, now=None, operating_sha256=None):
    clock = now_utc(now)
    pool = pool_document(pool)
    products = operating.get('products') if isinstance(operating, dict) else operating
    if not isinstance(products, list):
        raise ValueError('operating product list missing')
    signals, prices, evidence, excluded = market_universe(dashboard, clock)
    existing = [score_one(p, signals, market_listings=prices)
                for p in products if isinstance(p, dict)]
    operating_ids = {str(p.get('pd_no')) for p in products if isinstance(p, dict)}
    rows = []
    for pd_no, candidate in sorted(pool['items'].items()):
        if not isinstance(candidate, dict) or pd_no in operating_ids:
            raise ValueError('candidate pool overlaps operating identities')
        score = score_one(candidate, signals, market_listings=prices)
        try:
            observed = timestamp(candidate.get('collected_at'))
            fresh = -timedelta(minutes=5) <= clock - observed <= timedelta(hours=72)
        except (ValueError, TypeError, OverflowError):
            fresh = False
        blockers = []
        if not fresh:
            blockers.append('candidate_observation_stale_or_missing')
        if candidate.get('sold_out'):
            blockers.append('sold_out')
        if score['score_breakdown']['us_block_kind']:
            blockers.append(score['score_breakdown']['us_block_kind'])
        if not evidence or not score.get('best_global_match'):
            blockers.append('verified_market_match_missing')
        if score.get('s_rule') in {'non_core', 'non_core_bucket'}:
            blockers.append(score['s_rule'])
        form = form_of(score['name'])
        comparisons = [p for p in existing if p.get('bucket') == score['bucket']
                       and form and form_of(p['name'])
                       and form_compatible(form, form_of(p['name']))]
        comparisons.sort(key=lambda p: (p['shopify_score'], str(p.get('pd_no'))))
        incumbent = comparisons[0] if comparisons else None
        delta = round(score['shopify_score'] - incumbent['shopify_score'], 1) if incumbent else None
        if not incumbent:
            blockers.append('comparable_operating_product_missing')
        if delta is not None and delta < 5:
            blockers.append('score_advantage_below_5')
        proposal = None
        if not blockers:
            proposal = {'candidate_pd_no': pd_no,
                        'replace_pd_no': str(incumbent['pd_no']),
                        'bucket': score['bucket'], 'score_delta': delta,
                        'status': 'human_review_required',
                        'approval_required': True, 'operating_count_delta': 0,
                        'may_execute': False,
                        'remaining_gates': ['verified_label_and_ingredients', 'legal_review',
                                            'pricing_and_stock_review', 'canonical_gate',
                                            'payload_hash_approval']}
        rows.append({'pd_no': pd_no, 'name': score['name'], 'bucket': score['bucket'],
                     'url': candidate.get('url'), 'image_url': candidate.get('image_url'),
                     'collected_at': candidate.get('collected_at'),
                     'score': score,
                     'comparison_status': 'proposal_ready' if proposal else 'review_only',
                     'comparison_blockers': blockers,
                     'comparable_product': ({'pd_no': str(incumbent['pd_no']), 'name': incumbent['name'],
                                             'score': incumbent['shopify_score'], 'grade': incumbent['grade']}
                                            if incumbent else None),
                     'replacement_proposal': proposal,
                     'approval_required': True, 'may_replace': False, 'may_publish': False})
    rows.sort(key=lambda r: (r['comparison_status'] != 'proposal_ready', -r['score']['shopify_score'], r['pd_no']))
    return {'schema_version': 1, 'generated_at': clock.isoformat(),
            'purpose': 'comparison_only', 'paid_api_called': False,
            'may_replace_operating_products': False, 'may_publish': False,
            'approval_required': True, 'candidate_count': len(rows),
            'proposal_count': sum(bool(r['replacement_proposal']) for r in rows),
            'operating_product_count': len(products), 'operating_sha256': operating_sha256,
            'candidate_pool_digest': canonical_digest(pool),
            'market_evidence': evidence, 'excluded_market_sources': excluded,
            'scoring_note': 'Same deterministic demand rules, fresh verified per-item sources only. Comparison grades never change operating grades.',
            'items': rows}


def main():
    pool_path = DATA / 'daiso_real' / 'candidate_pool.json'
    product_path = DATA / 'daiso_real' / 'products.json'
    runtime_path = DATA / 'dashboard_runtime.json'
    pool = json.loads(pool_path.read_text(encoding='utf-8')) if pool_path.exists() else None
    operating = json.loads(product_path.read_text(encoding='utf-8'))
    dashboard = json.loads(runtime_path.read_text(encoding='utf-8'))
    before = file_digest(product_path)
    report = build_comparison(pool, operating, dashboard, operating_sha256=before)
    if file_digest(product_path) != before:
        raise RuntimeError('candidate comparison changed operating source')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"CANDIDATE_COMPARISON_OK candidates={report['candidate_count']} proposals={report['proposal_count']} operating={report['operating_product_count']} unchanged=true")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
