"""Bounded offline input/receipt integration. No provider or network calls.

record-collector runs AFTER validation and canonical no-change FX preservation.
Only validate_github_artifact at an authenticated HTTP boundary can establish
persisted authority. Stored receipt 'verified' flags are never authority.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import sys
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts.daiso_pipeline_health import evaluate_pipeline_health, receipt_sha256, sha, timestamp, run_window, WORKFLOW
from scripts.validate_daiso_collection import validate
from scripts.operational_freshness import assess_collection
from scripts.moe_evaluation_history import safe_path, atomic_write, exact_head

STATUS = 'data/daiso_real/collection_status.json'
POOL = 'data/daiso_real/candidate_pool.json'
OPERATING = 'data/daiso_real/products.json'
SHORTLIST = 'data/daiso_real/shortlist_observations.json'
INDEX = 'data/agents/daiso_pipeline_receipts.json'
HISTORY = 'data/agents/daiso_pipeline_history'
DERIVED = 'data/agents/daiso_pipeline_health.json'
REPORT = 'data/agents/workflow_freshness.json'
MAX_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 128
COLLECTOR = 'Collect Daiso products'
VALIDATOR = '실제 수집 결과 검증'
PRESERVE = 'Keep canonical product inputs on no_change'
PUBLICATIONS = ('산출물 발행 (원격 최신 위에 이번 변경만)', '정상 무변경 관측 metadata 발행')
UPLOAD = '수집 시도 진단 보존'


def clock(now=None):
    return timestamp(now if now is not None else datetime.now(timezone.utc))


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def read(root, name, optional=False):
    target = safe_path(root, name)
    try:
        if target.stat().st_size > MAX_BYTES:
            raise ValueError('source byte bound exceeded')
        raw = target.read_bytes()
        if len(raw) > MAX_BYTES:
            raise ValueError('source byte bound exceeded')
        return raw
    except FileNotFoundError:
        if optional:
            return None
        raise ValueError('missing source: ' + name) from None


def inputs(root):
    return {n: read(root, n, optional=n == POOL) for n in (STATUS, POOL, OPERATING)}


def hashes(raw):
    return {n: sha(b) if b is not None else None for n, b in raw.items()}


def doc(raw):
    return json.loads(raw) if raw is not None else {}


def histories(root, directory):
    target = safe_path(root, directory)
    if not target.exists():
        return []
    paths = sorted(target.iterdir())
    if len(paths) > MAX_RECORDS:
        raise ValueError('history capacity exhausted; pruning forbidden')
    result = []
    for p in paths:
        if not p.is_file() or not re.fullmatch(r'[0-9a-f]{64}\.json', p.name):
            raise ValueError('invalid immutable history name')
        raw = read(root, str(p.relative_to(root)))
        if sha(raw) != p.stem:
            raise ValueError('immutable history hash mismatch')
        result.append(doc(raw))
    return result


def retain(root, entry):
    entries = histories(root, HISTORY)
    raw = encode(entry)
    name = HISTORY + '/' + sha(raw) + '.json'
    if len(entries) >= MAX_RECORDS and not safe_path(root, name).exists():
        raise ValueError('history capacity exhausted; pruning forbidden')
    atomic_write(root, name, raw, immutable=True)
    return name


def context_id(context=None):
    values = os.environ if context is None else context
    text = '%s:%s:%s' % (values.get('GITHUB_RUN_ID'), values.get('GITHUB_RUN_ATTEMPT'), values.get('GITHUB_JOB'))
    match = re.fullmatch(r'([1-9][0-9]*):([1-9][0-9]*):([A-Za-z0-9_-]+)', text)
    ref = values.get('GITHUB_WORKFLOW_REF', '')
    if values.get('GITHUB_ACTIONS') != 'true' or not match or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/\.github/workflows/daiso-real-collection\.yml@refs/heads/main', ref):
        raise ValueError('actual GitHub Actions workflow context required')
    if values.get('DAISO_EXECUTION_ID', text) != text:
        raise ValueError('execution context mismatch')
    return int(match[1]), int(match[2]), match[3], text


def check(raw, outcome, execution_id, started_after, now, baseline=None):
    collection = doc(raw[STATUS])
    pool = doc(raw[POOL]) if raw[POOL] is not None else None
    result = validate(collection, outcome=outcome, execution_id=execution_id,
                      started_after=started_after, now=now, candidate_pool=pool,
                      operating_sha256=sha(raw[OPERATING]))
    if result['collection_valid'] != 'true':
        raise ValueError('; '.join(result['errors']))
    run = collection['last_run']
    if result['mode'] == 'candidates' and run.get('candidate_pool_sha256') != sha(raw[POOL]):
        raise ValueError('candidate pool exact bytes mismatch')
    if result['mode'] in {'candidates', 'no_change'}:
        if baseline is None:
            raise ValueError('canonical FX baseline required')
        previous = doc(baseline)
        if ('fx' in previous) != ('fx' in collection) or previous.get('fx') != collection.get('fx'):
            raise ValueError('canonical FX preservation incomplete')
        if any(run.get(k) != sha(raw[OPERATING]) for k in ('operating_before_sha256', 'operating_after_sha256')):
            raise ValueError('operating exact bytes not preserved')
    return result


def record_collector(root, *, collector_outcome, started_after, context=None, now=None, baseline_status_bytes=None):
    root, observed = Path(root).absolute(), clock(now)
    rid, attempt, job, execution = context_id(context)
    raw = inputs(root)
    collection = doc(raw[STATUS])
    run = collection.get('last_run') or {}
    mode, errors = 'failed', []
    try:
        if baseline_status_bytes is None and run.get('status') in {'candidates_collected', 'no_change'}:
            baseline_status_bytes = exact_head(root, STATUS)
        mode = check(raw, collector_outcome, execution, started_after, observed, baseline_status_bytes)['mode']
    except (ValueError, TypeError, OverflowError) as error:
        errors = [str(error)]
    current = run.get('execution_id') == execution
    receipt = {'schema_version': 1, 'source': 'github_actions', 'workflow': WORKFLOW,
               'scope': 'candidate_discovery' if mode == 'candidates' else 'operating_capture',
               'run_id': rid, 'run_attempt': attempt, 'job': job, 'execution_id': execution,
               'started_at': run.get('started_at') if current else started_after,
               'finished_at': run.get('finished_at') if current else None,
               'completed': mode != 'failed', 'outcome': collector_outcome, 'mode': mode,
               'source_sha256': sha(raw[STATUS]), 'public_authority': False}
    entry = {'schema_version': 1, 'kind': 'collector_receipt', 'receipt': receipt,
             'sources': hashes(raw), 'baseline_status_sha256': sha(baseline_status_bytes) if baseline_status_bytes else None,
             'canonical_fx': {'present': 'fx' in doc(baseline_status_bytes), 'value': doc(baseline_status_bytes).get('fx')} if baseline_status_bytes else None,
             'started_after': started_after, 'recorded_at': observed.isoformat(),
             'validation_errors': errors, 'public_authority': False}
    if inputs(root) != raw:
        raise ValueError('concurrent collection mutation')
    receipt_path = retain(root, entry)
    entries = sorted(p.stem for p in safe_path(root, HISTORY).iterdir())
    atomic_write(root, INDEX, encode({'schema_version': 1, 'history_sha256': entries, 'public_authority': False}))
    return {'mode': mode, 'collection_valid': str(mode != 'failed').lower(),
            'publish_products': str(mode == 'collected').lower(), 'errors': errors,
            'receipt_path': receipt_path, 'receipts_path': INDEX, 'public_authority': False}


def execution_steps(run, jobs, receipt, now):
    if (run.get('id'), run.get('run_attempt')) != (receipt.get('run_id'), receipt.get('run_attempt')):
        raise ValueError('wrong run attempt')
    if run.get('path') != '.github/workflows/' + WORKFLOW or run.get('head_branch') != 'main':
        raise ValueError('wrong workflow/branch')
    start, end = run_window(dict(run, finished_at=run.get('updated_at')), now)
    rows = jobs.get('jobs')
    if not isinstance(rows, list) or len(rows) > 32 or jobs.get('total_count') != len(rows):
        raise ValueError('jobs coverage invalid')
    match = [j for j in rows if j.get('name') == receipt.get('job')]
    if len(match) != 1:
        raise ValueError('ambiguous job')
    job = match[0]
    if job.get('run_id') != run['id'] or job.get('run_attempt') != run['run_attempt'] or job.get('status') != 'completed':
        raise ValueError('job attempt incomplete/mismatched')
    js, je = timestamp(job.get('started_at')), timestamp(job.get('completed_at'))
    if not start <= js <= je <= end:
        raise ValueError('job times invalid')
    steps = job.get('steps')
    if not isinstance(steps, list) or len(steps) > 128:
        raise ValueError('steps coverage invalid')
    mapped = {s.get('name'): s for s in steps}
    if len(mapped) != len(steps):
        raise ValueError('ambiguous step names')
    def success(name):
        step = mapped.get(name, {})
        if step.get('status') != 'completed' or step.get('conclusion') != 'success':
            raise ValueError('required step not successful: ' + name)
        a, b = timestamp(step.get('started_at')), timestamp(step.get('completed_at'))
        if not js <= a <= b <= je:
            raise ValueError('step times invalid')
        return a, b
    cs, ce = success(COLLECTOR)
    vs, ve = success(VALIDATOR)
    if not cs <= timestamp(receipt.get('started_at')) <= timestamp(receipt.get('finished_at')) <= ce <= vs <= ve:
        raise ValueError('capture outside collector/validator window')
    if receipt.get('mode') in {'candidates', 'no_change'} and ve > success(PRESERVE)[0]:
        raise ValueError('FX preservation order invalid')
    return mapped, success


def archive_members(metadata, archive, run):
    if not isinstance(archive, bytes) or len(archive) > MAX_BYTES:
        raise ValueError('archive byte bound exceeded')
    if metadata.get('expired') is not False or type(metadata.get('id')) is not int or metadata['id'] <= 0:
        raise ValueError('artifact identity/expiry invalid')
    if metadata.get('name') != 'daiso-attempt-%s-%s' % (run['id'], run['run_attempt']):
        raise ValueError('artifact attempt mismatch')
    wf = metadata.get('workflow_run') or {}
    if wf.get('id') != run['id'] or wf.get('head_sha') != run.get('head_sha') or not re.fullmatch(r'[0-9a-f]{40}', run.get('head_sha', '')):
        raise ValueError('artifact execution mismatch')
    if metadata.get('digest') != 'sha256:' + sha(archive) or metadata.get('size_in_bytes') != len(archive):
        raise ValueError('actual archive digest mismatch')
    result = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        members = z.infolist()
        if len(members) > 256 or sum(m.file_size for m in members) > MAX_BYTES:
            raise ValueError('archive extraction bound exceeded')
        for m in members:
            if m.filename.startswith('/') or '..' in m.filename.split('/') or '\\' in m.filename or m.flag_bits & 1:
                raise ValueError('unsafe artifact member')
            name = m.filename if m.filename.startswith('data/') else 'data/' + m.filename
            if name in result:
                raise ValueError('duplicate artifact member')
            result[name] = z.read(m)
    return result


def verify_bound_entry(root, entry, run, jobs, now):
    raw = inputs(root)
    receipt = entry['receipt']
    if entry.get('kind') != 'collector_receipt' or entry.get('sources') != hashes(raw):
        raise ValueError('exact source byte bindings changed')
    if receipt.get('public_authority') is not False or receipt.get('source_sha256') != sha(raw[STATUS]) or receipt.get('outcome') != 'success' or receipt.get('completed') is not True:
        raise ValueError('receipt completion/binding invalid')
    mapped, success = execution_steps(run, jobs, receipt, now)
    baseline = exact_head(root, STATUS) if receipt.get('mode') in {'candidates', 'no_change'} else None
    if baseline is not None:
        previous = doc(baseline)
        canonical_fx = {'present': 'fx' in previous, 'value': previous.get('fx')}
        if canonical_fx != entry.get('canonical_fx'):
            raise ValueError('canonical FX baseline changed')
    if check(raw, mapped[COLLECTOR]['conclusion'], receipt['execution_id'], entry['started_after'], now, baseline)['mode'] != receipt.get('mode'):
        raise ValueError('collector mode mismatch')
    return receipt, mapped, success


def validate_github_artifact(root, report, raw_run, raw_jobs, artifact_metadata, archive_bytes, *, now=None):
    """Call ONLY with independently authenticated REST metadata/download bytes."""
    root, observed = Path(root).absolute(), clock(now)
    from scripts.collect_workflow_status import _run
    normalized, faults = _run(raw_run, observed)
    workflow = (report.get('workflows') or {}).get(WORKFLOW) or {}
    if faults or normalized is None or workflow.get('metadata_verified') is not True or workflow.get('latest_attempt') != normalized['metadata']:
        raise ValueError('raw GitHub execution/current observation mismatch')
    actual = archive_members(artifact_metadata, archive_bytes, raw_run)
    raw = inputs(root)
    if actual.get(STATUS) != raw[STATUS] or (raw[POOL] is not None and actual.get(POOL) != raw[POOL]):
        raise ValueError('artifact/current exact source bytes mismatch')
    index = doc(actual.get(INDEX))
    if index.get('schema_version') != 1 or index.get('public_authority') is not False:
        raise ValueError('artifact receipt index missing')
    verified, receipts, selected = [], [], None
    digests = index.get('history_sha256')
    if not isinstance(digests, list) or len(digests) > MAX_RECORDS or len(set(digests)) != len(digests):
        raise ValueError('artifact receipt history coverage invalid')
    for digest in digests:
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('receipt history identity invalid')
        name = HISTORY + '/' + digest + '.json'
        exact = actual.get(name)
        if exact is None or sha(exact) != digest:
            raise ValueError('artifact receipt chain missing/mismatched')
        entry = doc(exact)
        if entry.get('kind') != 'collector_receipt':
            continue
        diagnostic = entry.get('receipt') or {}
        if ((diagnostic.get('run_id'), diagnostic.get('run_attempt')) == (raw_run.get('id'), raw_run.get('run_attempt'))
                and diagnostic.get('workflow') == WORKFLOW and diagnostic.get('source_sha256') == sha(raw[STATUS])
                and entry.get('sources') == hashes(raw) and diagnostic.get('completed') is False
                and diagnostic.get('outcome') in {'failure', 'cancelled', 'skipped'}):
            # Authenticated failed-run artifacts are diagnostic evidence only.
            # Retain exact immutable bytes without minting any validated hash.
            run_window(dict(raw_run, finished_at=raw_run.get('updated_at')), observed)
            retain(root, entry)
            selected = entry
            continue
        try:
            receipt, mapped, success = verify_bound_entry(root, entry, raw_run, raw_jobs, observed)
        except (ValueError, KeyError, TypeError, OSError):
            continue
        selected = entry
        receipts.append(receipt)
        verified.append(receipt_sha256(receipt))
        if raw_run.get('conclusion') == 'success':
            pubs = [n for n in PUBLICATIONS if mapped.get(n, {}).get('conclusion') == 'success']
            if len(pubs) == 1:
                ps, pe = success(pubs[0])
                us, ue = success(UPLOAD)
                created = timestamp(artifact_metadata.get('created_at'))
                if timestamp(receipt['finished_at']) <= ps <= pe <= us <= created <= ue:
                    full = dict(receipt, scope='overall_workflow', publication_completed=True,
                                workflow_conclusion='success', started_at=raw_run['run_started_at'],
                                finished_at=raw_run['updated_at'], source_sha256=sha(archive_bytes))
                    receipts.append(full)
                    verified.append(receipt_sha256(full))
    if selected is None:
        raise ValueError('no independently validated current receipt')
    return {'entry': selected, 'run': raw_run, 'jobs': raw_jobs, 'artifact': artifact_metadata,
            'archive_sha256': sha(archive_bytes), 'sources': hashes(raw), 'receipts': receipts,
            'validated_receipt_sha256': verified, 'public_authority': False}


def publish_validated_health(root, report, raw_run, raw_jobs, artifact_metadata, archive_bytes, *, now=None):
    root, observed = Path(root).absolute(), clock(now)
    validation = validate_github_artifact(root, report, raw_run, raw_jobs, artifact_metadata, archive_bytes, now=observed)
    entry = {'schema_version': 1, 'kind': 'github_validation', 'validation': validation,
             'workflow_report_sha256': sha(encode(report)), 'observed_at': observed.isoformat(), 'public_authority': False}
    retained = retain(root, entry)
    derived = {'schema_version': 1, 'history_path': retained,
               'validation_sha256': sha(encode(entry)), 'public_authority': False}
    atomic_write(root, DERIVED, encode(derived))
    health = load_pipeline_inputs(root, now=observed, workflow_report=report)
    derived['health'] = health
    derived['observed_at'] = observed.isoformat()
    atomic_write(root, DERIVED, encode(derived))
    return health


def load_pipeline_inputs(root, *, now=None, workflow_report=None):
    root, observed = Path(root).absolute(), clock(now)
    errors, raw = [], {n: None for n in (STATUS, POOL, OPERATING)}
    def optional(name):
        try:
            return doc(read(root, name, optional=True))
        except (OSError, ValueError):
            errors.append('invalid optional source: ' + name)
            return {}
    try:
        raw = inputs(root)
        collection = doc(raw[STATUS])
        pool = doc(raw[POOL]) if raw[POOL] else None
    except (ValueError, OSError) as error:
        errors.append(str(error))
        collection, pool = {}, None
    report = workflow_report if workflow_report is not None else optional(REPORT)
    receipts, verified, history = [], [], []
    try:
        from scripts.immutable_snapshot_store import load_snapshots
        history = [doc(raw) for raw in load_snapshots(root, 'data/agents/workflow_status_history').values()]
        # Preserve failed observations from immutable validation entries too.
        entries = histories(root, HISTORY)
        for e in entries:
            if e.get('kind') == 'github_validation':
                run = e['validation']['run']
                history.append({'workflows': {WORKFLOW: {'latest_attempt': dict(run, finished_at=run.get('updated_at')), 'metadata_verified': True}}})
        derived = optional(DERIVED)
        if derived:
            name = derived.get('history_path', '')
            if not re.fullmatch(HISTORY + r'/[0-9a-f]{64}\.json', name):
                raise ValueError('invalid validation history path')
            exact = read(root, name)
            if sha(exact) != derived.get('validation_sha256') or sha(exact) != Path(name).stem:
                raise ValueError('derived validation chain mismatch')
            saved = doc(exact)
            if saved.get('kind') != 'github_validation' or saved.get('public_authority') is not False or saved.get('workflow_report_sha256') != sha(encode(report)):
                raise ValueError('workflow observation binding changed')
            v = saved['validation']
            receipt, mapped, success = verify_bound_entry(root, v['entry'], v['run'], v['jobs'], observed)
            if v.get('sources') != hashes(raw) or v['artifact'].get('digest') != 'sha256:' + v['archive_sha256']:
                raise ValueError('derived artifact/source binding changed')
            receipts = [receipt]
            verified = [receipt_sha256(receipt)]
            # Recompute full authority from raw steps; ignore persisted flags/hashes.
            pubs = [n for n in PUBLICATIONS if mapped.get(n, {}).get('conclusion') == 'success']
            if v['run'].get('conclusion') == 'success' and len(pubs) == 1:
                ps, pe = success(pubs[0])
                us, ue = success(UPLOAD)
                created = timestamp(v['artifact'].get('created_at'))
                if timestamp(receipt['finished_at']) <= ps <= pe <= us <= created <= ue:
                    full = dict(receipt, scope='overall_workflow', publication_completed=True,
                                workflow_conclusion='success', started_at=v['run']['run_started_at'],
                                finished_at=v['run']['updated_at'], source_sha256=v['archive_sha256'])
                    receipts.append(full)
                    verified.append(receipt_sha256(full))
    except (ValueError, OSError, KeyError, TypeError, OverflowError) as error:
        errors.append(str(error))
        receipts, verified = [], []
    health = evaluate_pipeline_health(collection, report, now=observed, collection_status_bytes=raw[STATUS],
        candidate_pool=pool, candidate_pool_sha256=sha(raw[POOL]) if raw[POOL] else None,
        operating_sha256=sha(raw[OPERATING]) if raw[OPERATING] else None, shortlist_price=optional(SHORTLIST),
        receipts=receipts, validated_receipt_sha256=verified, workflow_history=history)
    health['input_errors'] = errors
    health['operating_staleness'] = assess_collection(collection, now=observed)
    return health


pipeline_health = load_pipeline_inputs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    record = sub.add_parser('record-collector')
    record.add_argument('--root', type=Path, required=True)
    record.add_argument('--collector-outcome', required=True)
    record.add_argument('--started-after', required=True)
    record.add_argument('--github-output', default=os.environ.get('GITHUB_OUTPUT'))
    args = parser.parse_args(argv)
    try:
        result = record_collector(args.root, collector_outcome=args.collector_outcome, started_after=args.started_after)
    except (ValueError, OSError, TypeError) as error:
        result = {'mode': 'failed', 'collection_valid': 'false', 'publish_products': 'false', 'errors': [str(error)], 'public_authority': False}
    print(json.dumps(result, ensure_ascii=False))
    if args.github_output:
        with open(args.github_output, 'a', encoding='utf-8') as output:
            for key in ('mode', 'collection_valid', 'publish_products', 'receipt_path', 'receipts_path'):
                if key in result:
                    output.write(key + '=' + result[key] + '\n')
    return int(result['mode'] == 'failed')


if __name__ == '__main__':
    raise SystemExit(main())
