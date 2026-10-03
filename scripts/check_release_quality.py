#!/usr/bin/env python3
"""Offline release gate. Typed source/commerce joins supplement existing gates."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def number(value, low=None, high=None):
    return (not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
            and (low is None or value >= low) and (high is None or value <= high))


def removal_evidence(root, baseline, removed_ids):
    try:
        from daiso.product_change_ledger import validate_removal_evidence
        return validate_removal_evidence(root, baseline, removed_ids)
    except (ImportError, OSError, ValueError, TypeError) as exc:
        return False, ['policy removal evidence unavailable/invalid: ' + type(exc).__name__]


def check(root=ROOT, *, phase='candidate', baseline=None, collector_report=None,
          execution_id=None, architecture=True, now=None):
    root = Path(root); clock = now or datetime.now(timezone.utc)
    errors, warnings, hashes, documents = [], [], {}, {}
    def require(ok, message):
        if not ok: errors.append(message)
    policy_path = root / 'config/quality_policy.yml'
    try:
        policy = read(policy_path)
        require(policy.get('schema_version') == 1, 'invalid quality policy')
    except (OSError, ValueError, AttributeError):
        policy = {}; errors.append('quality policy missing/invalid')
    required = policy.get('required_artifacts') or [
        'data/daiso_real/products.json', 'data/product_master.json',
        'data/daiso_real/shopify_demand_score.json', 'data/pricing_model.json',
        'data/dashboard_runtime.json']
    for name in required:
        try:
            p = root / name
            require(not p.is_symlink(), name + ': symlink prohibited')
            doc = read(p)
            require(isinstance(doc, dict), name + ': object required')
            documents[name] = doc
            hashes[name] = hashlib.sha256(p.read_bytes()).hexdigest()
        except (OSError, ValueError, UnicodeError):
            errors.append(name + ': missing/invalid JSON')
    try:
        source = documents['data/daiso_real/products.json']
        rows = source['products']
        require(isinstance(rows, list) and len(rows) > 0, 'operating products must be nonempty list')
        source_ids = [str(p.get('pd_no') or '') for p in rows]
        require(all(source_ids) and len(set(source_ids)) == len(source_ids), 'operating identity duplicate/missing')
        require(type(source.get('count')) is int and source['count'] == len(rows), 'operating count mismatch')
        for p in rows:
            require(isinstance(p.get('name'), str) and bool(p['name'].strip()), 'operating name missing')
            require(number(p.get('price_krw'), 1), 'operating observed price invalid')
            require(isinstance(p.get('url'), str) and p['url'].startswith('https://'), 'operating source URL missing')
        master = documents['data/product_master.json']
        products = master['products']
        require(master.get('schema_version') == 3 and isinstance(products, list), 'master schema invalid')
        master_ids = [str(p.get('pd_no') or '') for p in products]
        cp_ids = [p.get('canonical_product_id') for p in products]
        require(set(master_ids) == set(source_ids) and len(master_ids) == len(source_ids), 'master-source identity mismatch')
        require(all(isinstance(cp, str) and cp.startswith('CP') for cp in cp_ids) and len(set(cp_ids)) == len(cp_ids), 'canonical identity duplicate/missing')
        require(type(master.get('active_product_count')) is int and master['active_product_count'] == len(products), 'master active count mismatch')
        require(all(master.get('pd_no_to_cp', {}).get(str(p['pd_no'])) == p['canonical_product_id'] for p in products), 'canonical registry mismatch')
        scores = documents['data/daiso_real/shopify_demand_score.json']
        scored = scores['all_scored']
        require(isinstance(scored, list), 'scores list required')
        score_ids = [str(p.get('pd_no') or '') for p in scored]
        require(set(score_ids) == set(source_ids) and len(score_ids) == len(source_ids), 'score-source identity mismatch')
        require(type(scores.get('total_products')) is int and scores['total_products'] == len(scored), 'score total mismatch')
        summary = scores.get('grade_summary')
        require(isinstance(summary, dict) and all(type(v) is int and v >= 0 for v in summary.values()), 'score grade summary untyped')
        require(dict(Counter(p.get('grade') for p in scored)) == summary, 'score grade summary mismatch')
        for p in scored:
            require(number(p.get('shopify_score'), 0, 100) and p.get('grade') in {'S', 'A', 'B', 'C'}, 'score range/grade invalid')
        score_index = {str(p['pd_no']): p for p in scored}
        for p in products:
            s = score_index.get(str(p['pd_no']), {})
            require(p.get('grade') == s.get('grade') and p.get('shopify_score') == s.get('shopify_score'), 'master-score value mismatch')
        pricing = documents['data/pricing_model.json']
        fx = pricing['exchange_rate']
        require(number(fx.get('usd_to_krw'), 500, 3000), 'FX outside policy range')
        source_url = fx.get('api_url') or fx.get('source')
        if not isinstance(source_url,str) or not source_url.startswith('https://'):
            # The pricing writer retains a provider label, while its immutable
            # input keeps the actual endpoint and successful observation time.
            cached_fx = read(root/'data/daiso_real/collection_status.json').get('fx') or {}
            endpoints = {'ExchangeRate-API':'https://open.er-api.com/v6/latest/USD',
                         'Frankfurter API':'https://api.frankfurter.app/latest?from=USD&to=KRW',
                         'exchangerate-api':'https://api.exchangerate-api.com/v4/latest/USD'}
            observed = datetime.fromisoformat(str(cached_fx.get('fetched_at') or '').replace('Z','+00:00'))
            require(observed.tzinfo is not None and -300 <= (clock-observed).total_seconds() <= policy.get('max_fx_age_days',4)*86400,
                    'FX source observation stale/future/unaware')
            require(cached_fx.get('ok') is True and cached_fx.get('api_url') == endpoints.get(fx.get('source'))
                    and all(cached_fx.get(k) == fx.get(k) for k in ('usd_to_krw','as_of','source')), 'FX input/source provenance mismatch')
            source_url = cached_fx.get('api_url')
        require(isinstance(source_url, str) and source_url.startswith('https://'), 'FX source missing')
        fx_day = datetime.fromisoformat(fx['as_of']).replace(tzinfo=timezone.utc)
        require(-1 <= (clock - fx_day).total_seconds() / 86400 <= policy.get('max_fx_age_days', 4), 'FX stale/future')
        offers = pricing['offers_by_product']
        for kind in ('single', 'bundle'):
            entries = offers.get(kind)
            require(isinstance(entries, list) and bool(entries), 'pricing product offers missing')
            seen = set()
            for offer in entries:
                pid = str(offer.get('pd_no') or '')
                require(pid in set(source_ids) and pid not in seen, 'pricing identity missing/duplicate')
                seen.add(pid)
                for field in ('price_usd', 'unit_price_usd', 'landed_cost_total_usd', 'fee_usd'):
                    require(number(offer.get(field), 0), 'pricing numeric field invalid: ' + field)
                require(type(offer.get('qty')) is int and offer['qty'] > 0, 'pricing quantity invalid')
                price, cost, fee = offer['price_usd'], offer['landed_cost_total_usd'], offer['fee_usd']
                require(price > 0 and number(offer.get('net_profit_usd')), 'pricing profit invalid')
                require(abs(price - cost - fee - offer['net_profit_usd']) <= 0.031, 'pricing net profit arithmetic mismatch')
                require(abs(price / offer['qty'] - offer['unit_price_usd']) <= 0.011, 'pricing unit arithmetic mismatch')
                require(number(offer.get('margin_pct')) and abs(100 * offer['net_profit_usd'] / price - offer['margin_pct']) <= 0.16, 'pricing margin arithmetic mismatch')
        runtime = documents['data/dashboard_runtime.json']
        require(runtime.get('schema_version') == 1 and isinstance(runtime.get('teams'), list), 'runtime schema invalid')
        sourcing = next((t for t in runtime['teams'] if t.get('id') == 'sourcing'), {})
        require(str(len(rows)) + '개 상품' in str(sourcing.get('summary')), 'runtime operating count mismatch')
        discovery = runtime.get('candidate_discovery') or {}
        require(not discovery or (discovery.get('may_publish') is False and discovery.get('may_replace_operating_products') is False), 'candidate promotion unsafe')
        pool_path = root / 'data/daiso_real/candidate_pool.json'
        if pool_path.exists():
            pool = read(pool_path)
            require(isinstance(pool.get('items'), dict) and not set(pool['items']).intersection(source_ids), 'candidate-operating identities overlap')
            require(pool.get('approval_required') is True and pool.get('may_publish') is False and pool.get('may_replace_operating_products') is False, 'candidate safety flags invalid')
        if baseline:
            old = read(Path(baseline) / 'data/daiso_real/products.json')
            removed = {str(p['pd_no']) for p in old['products']} - set(source_ids)
            if removed:
                verified, reasons = removal_evidence(root, baseline, removed)
                require(verified, 'unexplained/unverified operating product removals: ' + ','.join(sorted(removed)))
                if not verified:
                    errors.extend('policy removal: ' + str(reason) for reason in reasons)
        if collector_report:
            report = read(collector_report)
            identity = execution_id or os.environ.get('RELEASE_EXECUTION_ID') or ':'.join((os.environ.get('GITHUB_RUN_ID', 'local'), os.environ.get('GITHUB_RUN_ATTEMPT', '1')))
            require(report.get('schema_version') == 1 and report.get('execution_id') == identity, 'outcome current-run evidence missing')
            require(report.get('publish_allowed') is True and report.get('status') in {'success', 'degraded'}, 'required process/evidence failure blocks publication')
            require(not report.get('required_failures') and not report.get('evidence_errors'), 'required/evidence failures cannot be overridden by report status')
            if 'results' in report:
                require(isinstance(report['results'], list), 'typed collector rows required')
                for row in report['results']:
                    require(row.get('execution_id') == identity and type(row.get('required')) is bool,
                            'collector row stale/untyped')
                    if row.get('required'):
                        require(row.get('status') == 'success' and row.get('process_exit_code') == 0,
                                'required collector row failed')
            health = runtime.get('pipeline_health') or {}
            require(health.get('execution_id') == identity and health.get('status') == report.get('status'), 'runtime actual-outcome status mismatch')
            for key, field in (('required_failure_count', 'required_failures'), ('optional_failure_count', 'optional_failures'), ('evidence_error_count', 'evidence_errors')):
                require(health.get(key) == len(report[field]), 'runtime outcome counts mismatch: ' + key)
            if report.get('status') == 'degraded': warnings.append('optional sources degraded, no successful-fetch timestamp inferred')
    except (OSError, UnicodeError, OverflowError, KeyError, TypeError, ValueError, AttributeError, StopIteration, ZeroDivisionError) as exc:
        errors.append('typed schema validation failed: ' + type(exc).__name__)
    if architecture and (root / 'scripts/validate_commerce_architecture.py').is_file():
        process = subprocess.run([sys.executable, str(root / 'scripts/validate_commerce_architecture.py'), '--require-ops-runtime'], cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace')
        require(process.returncode == 0, 'existing architecture gate blocked: ' + process.stdout[-700:] + process.stderr[-700:])
    return {'schema_version': 1, 'phase': phase, 'generated_at': clock.isoformat(),
            'status': 'failed' if errors else 'warning' if warnings else 'passed',
            'publish_allowed': not errors, 'errors': errors, 'warnings': warnings,
            'artifact_sha256': hashes, 'paid_api_called': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['candidate', 'final'], required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--collector-report', type=Path)
    parser.add_argument('--execution-id')
    args = parser.parse_args()
    report = check(args.root, phase=args.phase, baseline=args.baseline,
                   collector_report=args.collector_report, execution_id=args.execution_id)
    p = Path(args.report); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('RELEASE_QUALITY', report['status'], 'phase=' + args.phase)
    for error in report['errors']: print('BLOCK:', error)
    return 0 if report['publish_allowed'] else 1


if __name__ == '__main__':
    sys.exit(main())
