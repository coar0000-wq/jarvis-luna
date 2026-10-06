"""Pure scope-separated health. Receipt authority is supplied by a trusted caller.

No IO/clock: now is mandatory. Payload verified flags are never authority.
validated_receipt_sha256 contains hashes vouched for by an external validator
of GitHub step outcomes/artifact byte chains, not copied from receipt payloads.
collection_status_bytes binds receipts to EXACT original source bytes.
"""
from __future__ import annotations
from copy import deepcopy
from scripts.daiso_candidate_store import canonical_digest, pool_document, detail_url_valid, DISCOVERY_BUCKETS
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re

WORKFLOW = 'daiso-real-collection.yml'
SCOPES = ('candidate_discovery', 'operating_capture', 'shortlist_price', 'collection_publication', 'overall_workflow')
HEX = re.compile(r'[0-9a-f]{64}\Z')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def receipt_sha256(receipt):
    return sha(json.dumps(receipt, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode())


def timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        raise ValueError('source timestamp missing')
    if parsed.tzinfo is None:
        raise ValueError('source timezone missing')
    return parsed.astimezone(timezone.utc)


WHOLE_SECOND = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})\Z')
METADATA_PRECISION = {'github_whole_second': 'half_open_[t,t+1s)',
                      'capture_clocks': 'exact_unmodified', 'future_cap': 'observed_now',
                      'max_created_start_inversion_seconds': 1}


def github_not_after(actual, reported, now):
    """Whole-second API endpoints denote a second, not a rounded source clock."""
    value, bound, observed = timestamp(actual), timestamp(reported), timestamp(now)
    if value > observed or bound > observed:
        return False
    if isinstance(reported, str) and WHOLE_SECOND.fullmatch(reported):
        return value < bound + timedelta(seconds=1)
    return value <= bound


def run_metadata_precision(run):
    created = timestamp(run.get('created_at'))
    started = timestamp(run.get('run_started_at'))
    inversion = (created - started).total_seconds()
    if inversion > 0 and (inversion > 1 or not all(
            isinstance(run.get(k), str) and WHOLE_SECOND.fullmatch(run[k])
            for k in ('created_at', 'run_started_at'))):
        raise ValueError('invalid workflow completion times')
    return dict(METADATA_PRECISION, created_start_inversion_seconds=max(0, inversion))


def run_window(run, now):
    created = timestamp(run.get('created_at'))
    started = timestamp(run.get('run_started_at'))
    finished = timestamp(run.get('finished_at'))
    run_metadata_precision(run)
    if not started <= finished <= now or created > now or created > finished or run.get('status') != 'completed':
        raise ValueError('invalid workflow completion times')
    if type(run.get('id')) is not int or type(run.get('run_attempt')) is not int or min(run['id'], run['run_attempt']) <= 0:
        raise ValueError('invalid workflow identity')
    return min(created, started) if created > started else started, finished


def trusted(receipt, scope, now, validated):
    try:
        if receipt_sha256(receipt) not in validated or receipt.get('scope') != scope or receipt.get('source') != 'github_actions':
            return False
        rid, attempt = receipt.get('run_id'), receipt.get('run_attempt')
        if type(rid) is not int or type(attempt) is not int or min(rid, attempt) <= 0:
            return False
        job = receipt.get('job')
        if not isinstance(job, str) or not job or receipt.get('execution_id') != f'{rid}:{attempt}:{job}':
            return False
        if receipt.get('workflow') != WORKFLOW or receipt.get('completed') is not True or receipt.get('outcome') != 'success':
            return False
        if not timestamp(receipt.get('started_at')) <= timestamp(receipt.get('finished_at')) <= now:
            return False
        return bool(HEX.fullmatch(receipt.get('source_sha256', '')))
    except (TypeError, ValueError, OverflowError):
        return False


def collection_scope(run):
    """Coverage is data from a bound collector run, never a default or flag."""
    requested = run.get('requested')
    discovery, operating = run.get('discovery_enabled'), run.get('operating_updates_enabled')
    if type(requested) is not int or requested <= 0 or type(discovery) is not bool or type(operating) is not bool:
        raise ValueError('collection coverage missing/invalid')
    return {'requested': requested, 'discovery_enabled': discovery,
            'operating_updates_enabled': operating,
            'publication': 'operating_products' if operating else 'collection_metadata'}


DAILY_SCOPE = collection_scope({'requested': 110, 'discovery_enabled': True, 'operating_updates_enabled': False})


def result(status='unverified', reason='no_verified_source', **extra):
    return {'status': status, 'reason': reason, 'verified': status == 'success', **extra}


def evaluate_pipeline_health(collection_status, workflow_report, *, now,
                             collection_status_bytes=None, candidate_pool=None,
                             candidate_pool_sha256=None, operating_sha256=None,
                             shortlist_price=None, receipts=(),
                             validated_receipt_sha256=(), workflow_history=(), validated_failure_scopes=None):
    """Return schema v1 scopes + immutable failure evidence, without mutation.

    Callers must validate receipt fingerprints out-of-band. Discovery additionally
    uses existing validate_daiso_collection.validate against pool/current bytes.
    A narrow shortlist receipt NEVER authorizes full-workflow recovery.
    """
    observed = timestamp(now)
    validated = set(validated_receipt_sha256)
    scopes = {scope: result() for scope in SCOPES}
    history = []
    for report in (*workflow_history, workflow_report):
        item = (report or {}).get('workflows', {}).get(WORKFLOW, {})
        attempt = item.get('latest_attempt')
        if isinstance(attempt, dict) and attempt.get('conclusion') in {'failure', 'timed_out', 'startup_failure', 'action_required'}:
            evidence = {'run': deepcopy(attempt), 'metadata_verified': item.get('metadata_verified') is True,
                        'superseded': False}
            if not any(e['run'] == evidence['run'] for e in history):
                history.append(evidence)
    workflow = (workflow_report or {}).get('workflows', {}).get(WORKFLOW, {})
    latest = workflow.get('latest_attempt') or {}
    doc = collection_status if isinstance(collection_status, dict) else {}
    run = doc.get('last_run') or {}
    try:
        if not isinstance(collection_status_bytes, bytes) or json.loads(collection_status_bytes) != doc:
            raise ValueError('exact collection source bytes missing/mismatched')
        digest = sha(collection_status_bytes)
        scope = 'candidate_discovery' if run.get('status') == 'candidates_collected' else 'operating_capture'
        matches = [r for r in receipts if trusted(r, scope, observed, validated)
                   and r.get('source_sha256') == digest and r.get('execution_id') == run.get('execution_id')]
        if not matches:
            raise ValueError('no trusted matching collection receipt')
        receipt = matches[0]
        start, finish = timestamp(run.get('started_at')), timestamp(run.get('finished_at'))
        if not timestamp(receipt['started_at']) <= start <= finish <= timestamp(receipt['finished_at']):
            raise ValueError('collection outside verified execution')
        if latest.get('id') == receipt['run_id']:
            if latest.get('run_attempt') != receipt['run_attempt'] or workflow.get('metadata_verified') is not True:
                raise ValueError('run attempt mismatch/unverified workflow metadata')
            ws, wf = run_window(latest, observed)
            if not ws <= start <= finish or not github_not_after(finish, latest.get('finished_at'), observed):
                raise ValueError('collection outside workflow completion')
        elif latest:
            if workflow.get('metadata_verified') is not True:
                raise ValueError('unverified latest workflow metadata')
            _, wf = run_window(latest, observed)
            if start <= wf:
                raise ValueError('collection is older than latest workflow')
        if doc.get('last_attempt') != run or run.get('collector_completed') is not True or run.get('collector_version') != 2:
            raise ValueError('collector completion/current attempt invalid')
        counts = [run.get(k) for k in ('requested', 'ok', 'parse_failed', 'http_error')]
        if any(type(v) is not int or v < 0 for v in counts) or counts[1] > counts[0] or counts[2] or counts[3]:
            raise ValueError('invalid collection counts/parse/network failure')
        if (observed - finish).total_seconds() > 6 * 3600:
            raise ValueError('expired collection receipt')
        if scope == 'candidate_discovery':
            total = run.get('candidates_new', -1) + run.get('candidates_updated', -1)
            if total <= 0 or total > counts[0] or counts[1] or run.get('discovery_enabled') is not True or run.get('operating_updates_enabled') is not False or doc.get('last_candidate_success') != run:
                raise ValueError('candidate completion/counts invalid')
            if run.get('operating_before_sha256') != operating_sha256 or run.get('operating_after_sha256') != operating_sha256 or not operating_sha256:
                raise ValueError('operating byte preservation invalid')
            if not candidate_pool_sha256 or candidate_pool_sha256 != run.get('candidate_pool_sha256') or not isinstance(candidate_pool, dict):
                raise ValueError('candidate pool byte binding missing/mismatch')
            if candidate_pool.get('approval_required') is not True or candidate_pool.get('may_publish') is not False or candidate_pool.get('may_replace_operating_products') is not False:
                raise ValueError('candidate safety flags missing')
            pool = pool_document(candidate_pool)
            ids = run.get('candidate_ids')
            if canonical_digest(pool) != run.get('candidate_pool_digest') or not isinstance(ids, list) or len(ids) != total or len(set(ids)) != total:
                raise ValueError('candidate pool digest/identity mismatch')
            for pd_no in ids:
                candidate = pool['items'].get(pd_no, {})
                if candidate.get('bucket') not in DISCOVERY_BUCKETS or not detail_url_valid(candidate.get('url'), pd_no) or candidate.get('observation', {}).get('execution_id') != run['execution_id'] or not start <= timestamp(candidate.get('collected_at')) <= finish or candidate.get('may_publish') is not False or candidate.get('may_replace_operating_products') is not False:
                    raise ValueError('candidate current-execution provenance invalid')
            checked = {'mode': 'candidates'}
        else:
            if run.get('status') != 'ok' or counts[1] <= 0 or doc.get('last_success') != run:
                raise ValueError('operating capture completion invalid')
            checked = {'mode': 'collected'}
        scopes[scope] = result('success', checked['mode'], execution_id=run['execution_id'],
                               requested=run.get('requested'), candidate_count=run.get('candidate_count'),
                               completed_at=run['finished_at'])
    except (ValueError, TypeError, OverflowError) as exc:
        scopes['candidate_discovery' if run.get('status') == 'candidates_collected' else 'operating_capture'] = result(reason=str(exc))
    # Price observation completeness is limited to the explicit shortlist scope.
    if isinstance(shortlist_price, dict):
        try:
            rows = shortlist_price.get('products')
            ids = shortlist_price.get('expected_ids')
            if shortlist_price.get('scope') != 'active_shopify_shortlist_only' or shortlist_price.get('complete') is not True or shortlist_price.get('operating_catalog_mutated') is not False:
                raise ValueError('shortlist scope/completion invalid')
            if not isinstance(rows, list) or not rows or not isinstance(ids, list) or len(set(ids)) != len(ids) or {r.get('canonical_product_id') for r in rows} != set(ids) or len(rows) != len(ids):
                raise ValueError('shortlist identity coverage invalid')
            for row in rows:
                source, provenance = row.get('source', {}), row.get('provenance', {})
                captured = timestamp(source.get('collected_at'))
                if captured > observed or (observed-captured).total_seconds() >= 86400 or source.get('capture_kind') != 'successful_http_parse' or provenance.get('http_status') != 200 or provenance.get('parse_status') != 'exact_pd_no_numeric_price' or not HEX.fullmatch(provenance.get('response_sha256', '')) or type(row.get('price_krw')) is not int or row['price_krw'] <= 0:
                    raise ValueError('shortlist source proof invalid')
            scopes['shortlist_price'] = result('success', 'source_price_capture_only', count=len(rows), scope='active_shopify_shortlist_only')
        except (ValueError, TypeError, OverflowError) as exc:
            scopes['shortlist_price'] = result(reason=str(exc))
    publications = [r for r in receipts if trusted(r, 'collection_publication', observed, validated)
                    and r.get('publication_completed') is True and r.get('workflow_conclusion') == 'success'
                    and (observed - timestamp(r['finished_at'])).total_seconds() <= 6 * 3600]
    if publications:
        scopes['collection_publication'] = result('success', 'bound_collection_scope_published', collection_scope=publications[0].get('collection_scope'))
    full = [r for r in receipts if trusted(r, 'overall_workflow', observed, validated)
            and r.get('publication_completed') is True and r.get('workflow_conclusion') == 'success'
            and r.get('collection_scope') == DAILY_SCOPE
            and (observed - timestamp(r['finished_at'])).total_seconds() <= 6 * 3600]
    for failure in history:
        try:
            _, end = run_window(failure['run'], observed)
            failure['metadata_precision'] = run_metadata_precision(failure['run'])
            key = (failure['run']['id'], failure['run']['run_attempt'])
            required = (validated_failure_scopes or {}).get(key)
            failure['collection_scope'] = required
            if required is None:
                failure['coverage_reason'] = 'prior_failure_collection_coverage_unknown'
                continue
            for receipt in full:
                if receipt.get('collection_scope') != required:
                    continue
                if timestamp(receipt['started_at']) > end and (receipt['run_id'], receipt['run_attempt']) != (failure['run']['id'], failure['run']['run_attempt']):
                    failure['superseded'] = True
                    failure['superseded_by'] = receipt['execution_id']
                    break
        except (ValueError, TypeError, OverflowError):
            pass
    unresolved = any(not f['superseded'] for f in history)
    if unresolved:
        scopes['overall_workflow'] = result('failed', 'workflow_failure_not_superseded_by_same_scope_verified_publication')
    elif full:
        scopes['overall_workflow'] = result('success', 'verified_workflow_and_publication_completed')
    else:
        scopes['overall_workflow'] = result(reason='publication_completion_unverified')
    return {'schema_version': 1, 'scopes': scopes, 'status': scopes['overall_workflow']['status'],
            'failed_workflow_history': history, 'public_authority': False,
            'metadata_precision': dict(METADATA_PRECISION)}


# Stable convenience alias for downstream readers.
evaluate = evaluate_pipeline_health
