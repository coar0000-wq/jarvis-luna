"""Fail-closed export projections with exact report/source/transition evidence.

Archived reports are historical drafts, never active products or legal approval.
Only the current legal scope and computed label summary may leave the active
projection. The publisher verifies this independently, without HTS/network IO.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

from scripts.immutable_snapshot_store import retain_snapshots, load_snapshots, _safe
from scripts.moe_evaluation_history import atomic_write, sync_dir
from scripts.candidate_pool_history import parse, read_source

REPORT = 'data/legal_export_prep.json'
HISTORY = 'data/legal_export_history'
MANIFEST = 'data/publish_deletions.json'
LOCK = 'data/.evaluation-publication.lock'
POLICY_REF = 'scripts/legal_export_history.py'
LEGAL = 'data/legal_products.json'
SOURCES = (LEGAL, 'data/gosi.json', 'data/daiso_real/shopify_demand_score.json', 'data/shopify_listing_copy.json')
SUMMARY = '사람이_채워야_하는_칸'
MEANING = 'historical_export_draft_not_current_scope_or_legal_approval'
REPORT_KEYS = {'generated_at', 'generator', '왜', 'hs_출처', 'hs_주의', 'label_기준', 'total', 'hs_filled_this_run', 'label_complete', SUMMARY, 'items'}
ROW_KEYS = {'pd_no', 'name', 'bucket', 'grade', '용도', '성분', '제조국', '내용량', '제조업자', 'name_en', 'product_type_en', 'hs', 'label', 'hard_block', 'hard_block_reason'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def revision(root):
    result = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True)
    if result.returncode:
        raise ValueError('export HEAD unavailable')
    return result.stdout.strip()


def head_report(root):
    result = subprocess.run(['git', '-C', str(root), 'show', 'HEAD:' + REPORT], capture_output=True)
    if result.returncode:
        raise ValueError('export baseline missing')
    return result.stdout


def ids(rows, *, coerce=False):
    if (not isinstance(rows, list) or not rows or any(not isinstance(r, dict)
            or (not isinstance(r.get('pd_no'), str) and not (coerce and type(r.get('pd_no')) is int))
            or not str(r['pd_no']).strip() for r in rows)):
        raise ValueError('export source identities invalid/empty')
    result = [str(r['pd_no']) for r in rows]
    if len(result) != len(set(result)):
        raise ValueError('export duplicate source identity')
    return result


def validate_sources(raws):
    if set(raws) != set(SOURCES):
        raise ValueError('export source set invalid')
    docs = {name: parse(value) for name, value in raws.items()}
    if any(not isinstance(doc, dict) for doc in docs.values()):
        raise ValueError('export source must be an object')
    legal, gosi, score, copy = (docs[name] for name in SOURCES)
    for source in (legal, gosi):
        rows = source.get('items')
        if not isinstance(rows, dict) or not rows or any(not isinstance(k, str) or not k.strip()
                or not isinstance(v, dict) for k, v in rows.items()):
            raise ValueError('export source items invalid/empty')
    archived = legal.get('out_of_scope', {})
    if not isinstance(archived, dict) or set(archived) & set(legal['items']):
        raise ValueError('export canonical archived scope invalid')
    score_ids = ids(score.get('all_scored'), coerce=True)
    ids(copy.get('items'), coerce=True)
    if not set(legal['items']) <= set(score_ids):
        raise ValueError('export legal scope missing score identities')
    for row in legal['items'].values():
        if (not isinstance(row.get('status'), str) or row['status'] not in {'pending', 'auto_checked', 'pass', 'fail'}
                or type(row.get('hard_block')) is not bool
                or not isinstance(row.get('hard_block_reason'), str)
                or row['hard_block'] and not row['hard_block_reason'].strip()
                or any(k in row and not isinstance(row[k], str) for k in ('name', 'hs_code'))):
            raise ValueError('export legal safety fields missing/invalid')
    for row in gosi['items'].values():
        if any(k in row and not isinstance(row[k], str) for k in ('ingredients', 'volume', 'origin', 'maker')):
            raise ValueError('export gosi field type invalid')
    for row in score['all_scored']:
        if any(k in row and not isinstance(row[k], str) for k in ('name', 'bucket')):
            raise ValueError('export score field type invalid')
    for row in copy['items']:
        cp = row.get('copy')
        if cp is not None and (not isinstance(cp, dict) or any(k in cp and not isinstance(cp[k], str)
                for k in ('title', 'product_type'))):
            raise ValueError('export copy field type invalid')
    return docs


def validate_report(raw):
    from scripts.prepare_legal_export import LABEL_FIELDS
    doc = parse(raw)
    if not isinstance(doc, dict) or set(doc) != REPORT_KEYS:
        raise ValueError('export report fields changed/malformed')
    keys = ids(doc['items'])
    if type(doc['total']) is not int or doc['total'] != len(keys):
        raise ValueError('export report count invalid')
    if (any(type(doc[k]) is not int or not 0 <= doc[k] <= len(keys) for k in ('hs_filled_this_run', 'label_complete'))
            or doc['generator'] != 'scripts/prepare_legal_export.py'):
        raise ValueError('export report metadata invalid')
    if any(not isinstance(doc[k], str) for k in ('generated_at', '왜', 'hs_출처', 'hs_주의', 'label_기준')):
        raise ValueError('export report text/clock invalid')
    at = datetime.fromisoformat(doc['generated_at'].replace('Z', '+00:00'))
    if at.tzinfo is None:
        raise ValueError('export report clock invalid')
    for row in doc['items']:
        if (set(row) != ROW_KEYS or type(row['hard_block']) is not bool
                or row['grade'] is not None and not isinstance(row['grade'], str)):
            raise ValueError('export row fields changed/malformed')
        if any(not isinstance(row[k], str) for k in ROW_KEYS - {'hs', 'label', 'grade', 'hard_block'}):
            raise ValueError('export row field type invalid')
        hs, label = row['hs'], row['label']
        if (not isinstance(hs, dict) or set(hs) != {'code', 'basis', 'label', 'official'}
                or any(not isinstance(hs[k], str) for k in ('code', 'basis', 'label'))
                or not isinstance(hs['official'], list) or any(not isinstance(r, dict)
                or set(r) != {'htsno', 'description'} or not isinstance(r['htsno'], str)
                or not isinstance(r['description'], str) for r in hs['official'])):
            raise ValueError('export HTS evidence malformed')
        if (not isinstance(label, dict) or set(label) != {'draft', 'missing', 'note', 'inci_status'}
                or not isinstance(label['draft'], dict) or set(label['draft']) != {k for k, _, _ in LABEL_FIELDS}
                or not isinstance(label['note'], str) or label['inci_status'] not in {'korean_only', 'no_ingredients'}):
            raise ValueError('export label fields changed/malformed')
        missing = []
        for key, ko, rule in LABEL_FIELDS:
            entry = label['draft'][key]
            if (not isinstance(entry, dict) or set(entry) != {'label', 'value', 'rule'}
                    or entry['label'] != ko or entry['rule'] != rule or not isinstance(entry['value'], str)):
                raise ValueError('export label field changed/malformed')
            if not entry['value']:
                missing.append(ko)
        if label['missing'] != missing:
            raise ValueError('export label missing summary inconsistent')
    if (doc[SUMMARY] != sorted({v for r in doc['items'] for v in r['label']['missing']})
            or doc['label_complete'] != sum(not r['label']['missing'] for r in doc['items'])):
        raise ValueError('export aggregate summary inconsistent')
    return doc


def projection(doc):
    return {k: v for k, v in doc.items() if k not in {'generated_at', 'hs_filled_this_run'}}


def verify_projection(current, sources, observations, *, retained_counter=False):
    """Rebuild using retained complete HTS observations; never call the API.

    The visible report keeps only six rows, but pick_hts can derive its label
    from a later row. Retain/replay the full normalized lookup, not that slice.
    """
    from scripts.prepare_legal_export import build_report, pick_hts
    if (not isinstance(observations, dict) or not observations or any(
            not isinstance(key, str) or not isinstance(rows, list) or any(
                not isinstance(row, dict) or set(row) != {'htsno', 'description'}
                or not isinstance(row['htsno'], str) or not isinstance(row['description'], str)
                for row in rows) for key, rows in observations.items())):
        raise ValueError('export HTS lookup evidence malformed')
    used = set()
    def lookup(keyword, cache):
        used.add(keyword)
        return observations[keyword]
    def resolver(name, bucket, cache):
        return pick_hts(name, bucket, cache, lookup=lookup)
    expected, after = build_report(sources, current['generated_at'], resolver=resolver)
    if (projection(expected) != projection(current) or used != set(observations)
            or not retained_counter and expected['hs_filled_this_run'] != current['hs_filled_this_run']):
        raise ValueError('export projection differs from canonical inputs/HTS observations')
    return after


def transition(base, previous, current, source_raws, legal_after, observations_raw):
    before, prior, now = map(validate_report, (base, previous, current))
    sources = validate_sources(source_raws)
    after = verify_projection(now, sources, parse(observations_raw), retained_counter=current == base)
    if parse(legal_after) != after:
        raise ValueError('export changed canonical legal data beyond HS proposals')
    active = set(sources[LEGAL]['items'])
    inactive = sorted((set(ids(before['items'])) | set(ids(prior['items']))) - active)
    archived = sources[LEGAL].get('out_of_scope', {})
    for key in inactive:
        row = archived.get(key)
        if (not isinstance(row, dict) or not isinstance(row.get('row'), dict)
                or not isinstance(row.get('왜_뺐나'), str) or not row['왜_뺐나'].strip()
                or not isinstance(row.get('뺀_시각'), str) or not row['뺀_시각'].strip()):
            raise ValueError('export removed identity lacks canonical archived scope reason')
        if datetime.fromisoformat(row['뺀_시각'].replace('Z', '+00:00')).tzinfo is None:
            raise ValueError('export archived scope clock invalid')
    removed = sorted((set(ids(before['items'])) - active) | (set(before[SUMMARY]) - set(now[SUMMARY])))
    return {'schema_version': 1, 'meaning': MEANING, 'baseline_sha256': sha(base),
        'previous_sha256': sha(previous), 'current_sha256': sha(current),
        'source_sha256': {n: sha(v) for n, v in source_raws.items()},
        'published_legal_sha256': sha(legal_after), 'hts_observations_sha256': sha(observations_raw),
        'active_ids': sorted(active),
        'inactive_ids': inactive, 'added_ids': sorted(active - set(ids(before['items']))),
        'summary_before': before[SUMMARY], 'summary_after': now[SUMMARY], 'removed_tokens': removed}


def verify_evidence(base, current, evidence):
    if base is None or current is None or not isinstance(evidence, dict):
        raise ValueError('export transition evidence missing')
    archives, record = evidence['archives'], evidence['record']
    for digest, raw in archives.items():
        if sha(raw) != digest:
            raise ValueError('export archive hash mismatch')
    if archives.get(sha(base)) != base or archives.get(sha(current)) != current:
        raise ValueError('export exact report archive missing')
    source_raws = {n: archives[h] for n, h in record['source_sha256'].items()}
    expected = transition(base, archives[record['previous_sha256']], current, source_raws,
                          archives[record['published_legal_sha256']], archives[record['hts_observations_sha256']])
    if record != expected or archives.get(sha(encode(record))) != encode(record):
        raise ValueError('export transition evidence forged/missing')
    return expected['removed_tokens']


def manifest_record(base, current, evidence):
    tokens = verify_evidence(base, current, evidence)
    return {'path': REPORT, 'base_sha256': sha(base), 'replacement_sha256': sha(current),
        'ids': tokens, 'delete_file': False, 'policy_ref': POLICY_REF,
        'transition_sha256': sha(encode(evidence['record'])),
        'reason': 'Current canonical legal scope and computed label summary only; exact prior export drafts and source bytes retained as inactive history, not legal approval.'}


def load_evidence(root, base, current, manifest):
    records = [r for r in manifest.get('deletions', []) if isinstance(r, dict) and r.get('path') == REPORT]
    if len(records) != 1 or records[0].get('policy_ref') != POLICY_REF:
        raise ValueError('export requires one narrowly bound manifest record')
    archives = load_snapshots(root, HISTORY)
    evidence = {'archives': archives, 'record': parse(archives[records[0]['transition_sha256']])}
    if records[0] != manifest_record(base, current, evidence):
        raise ValueError('export manifest does not bind exact transition')
    return evidence


def publish_export(root, builder):
    root = Path(root).absolute()
    lock = _safe(root, LOCK)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fsync(fd)
        rev, base = revision(root), head_report(root)
        previous = read_source(root, REPORT)
        old_manifest = read_source(root, MANIFEST, optional=True)
        source_raws = {n: read_source(root, n) for n in SOURCES}
        sources = validate_sources(source_raws)
        validate_report(base); prior = validate_report(previous)
        retained = load_snapshots(root, HISTORY)
        for raw in retained.values():
            parse(raw)
        # Validate old manifest before any HTS work or mutation.
        manifest = parse(old_manifest) if old_manifest is not None else {'schema_version': 1, 'deletions': []}
        if (not isinstance(manifest, dict) or manifest.get('schema_version') != 1
                or not isinstance(manifest.get('deletions'), list)
                or any(not isinstance(r, dict) or not isinstance(r.get('ids', []), list) for r in manifest['deletions'])):
            raise ValueError('export publication manifest malformed')
        existing = [r for r in manifest['deletions'] if r.get('path') == REPORT]
        if len(existing) > 1 or any(r.get('policy_ref') != POLICY_REF for r in existing):
            raise ValueError('conflicting export publication authorization')
        observations = {}
        generated, legal_after = builder(sources, datetime.now(timezone.utc).isoformat(), observations=observations)
        payload = generated
        observations_raw = encode(observations)
        # Unchanged projections are the same snapshot, not timestamp-only churn.
        if projection(payload) == projection(prior):
            payload = prior
        current = previous if payload is prior else encode(payload)
        legal_raw = source_raws[LEGAL] if legal_after == sources[LEGAL] else encode(legal_after)
        def unchanged():
            if (revision(root) != rev or head_report(root) != base or read_source(root, REPORT) != previous
                    or read_source(root, MANIFEST, optional=True) != old_manifest
                    or any(read_source(root, n) != raw for n, raw in source_raws.items())):
                raise ValueError('concurrent export HEAD/source/manifest changed')
        if (previous == current and legal_raw == source_raws[LEGAL] and existing
                and existing[0].get('base_sha256') == sha(base)
                and existing[0].get('replacement_sha256') == sha(current)):
            old_evidence = load_evidence(root, base, current, manifest)
            old_record = old_evidence['record']
            if (all(sha(raw) == (old_record['published_legal_sha256'] if n == LEGAL
                   else old_record['source_sha256'][n]) for n, raw in source_raws.items())
                    and sha(observations_raw) == old_record['hts_observations_sha256']):
                unchanged()
                return payload
        # A self-asserted previous=current proof cannot excuse a false fresh
        # counter. Only Git's exact baseline is independently known history.
        # Otherwise new input bytes require a freshly computed fill counter.
        if current == previous and previous != base:
            payload, current = generated, encode(generated)
        record = transition(base, previous, current, source_raws, legal_raw, observations_raw)
        for raw in [base, previous, current, *source_raws.values(), legal_raw, observations_raw, encode(record)]:
            retained[sha(raw)] = raw
        evidence = {'archives': retained, 'record': record}
        replacement = manifest_record(base, current, evidence)
        manifest = deepcopy(manifest)
        manifest['deletions'] = [r for r in manifest['deletions'] if r.get('path') != REPORT] + [replacement]
        unchanged()
        retain_snapshots(root, HISTORY, retained)
        unchanged()
        if load_snapshots(root, HISTORY) != retained:
            raise ValueError('concurrent export history changed')
        # Evidence first; a partial write cannot authorize an unbound report.
        atomic_write(root, MANIFEST, encode(manifest))
        if any(read_source(root, n) != raw for n, raw in source_raws.items()) or read_source(root, REPORT) != previous:
            raise ValueError('concurrent export source changed before replacement')
        if legal_raw != source_raws[LEGAL]:
            atomic_write(root, LEGAL, legal_raw)
        if read_source(root, REPORT) != previous:
            raise ValueError('concurrent export report changed before replacement')
        if current != previous:
            atomic_write(root, REPORT, current)
        if (revision(root) != rev or head_report(root) != base or read_source(root, REPORT) != current
                or read_source(root, LEGAL) != legal_raw or read_source(root, MANIFEST) != encode(manifest)
                or any(read_source(root, n) != raw for n, raw in source_raws.items() if n != LEGAL)):
            raise ValueError('concurrent export publication changed')
        return payload
    finally:
        os.close(fd)
        lock.unlink()
        sync_dir(lock.parent)


def verify_final(root, base, current, evidence):
    if read_source(root, REPORT) != current:
        raise ValueError('final export bytes changed')
    final = load_evidence(root, base, current, parse(read_source(root, MANIFEST)))
    if any(final['archives'].get(k) != v for k, v in evidence['archives'].items()):
        raise ValueError('final export history lost or changed')
    verify_current_sources(current, evidence, {n: read_source(root, n) for n in SOURCES})


def verify_current_sources(current, evidence, source_raws):
    """Check post-export commerce regeneration without trusting its timestamps."""
    sources = validate_sources(source_raws)
    observations = parse(evidence['archives'][evidence['record']['hts_observations_sha256']])
    # The counter was verified against the archived pre-fill producer inputs.
    # Final commerce regeneration can already contain those HS proposals.
    verify_projection(validate_report(current), sources, observations, retained_counter=True)
    if set(sources[LEGAL]['items']) != set(evidence['record']['active_ids']):
        raise ValueError('final export canonical scope changed')
    old_legal = parse(evidence['archives'][evidence['record']['source_sha256'][LEGAL]])
    for key in evidence['record']['inactive_ids']:
        if sources[LEGAL].get('out_of_scope', {}).get(key) != old_legal['out_of_scope'][key]:
            raise ValueError('final export canonical archive changed')
