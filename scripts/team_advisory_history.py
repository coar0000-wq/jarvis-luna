"""Exact team-advisory observations and transitions, never approval evidence.

The current report remains only the latest evaluation. Optional remote answer
metadata may disappear on a local fallback only after the publisher verifies
its exact prior/current snapshots, bounded input and narrow transition record.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.candidate_pool_history import parse, read_source
from scripts.immutable_snapshot_store import load_snapshots, retain_snapshots, _safe
from scripts.moe_evaluation_history import atomic_write, exact_head, sync_dir

REPORT = 'data/typesafe_team_advisory.json'
HISTORY = 'data/typesafe_team_advisory_history'
MANIFEST = 'data/publish_deletions.json'
LOCK = 'data/.evaluation-publication.lock'
POLICY_REF = 'scripts/team_advisory_history.py'
MEANING = 'historical_advisory_not_current_evidence_or_approval'
SCOPE = 'observed_cached_not_independently_verified'
KEYS = {'schema_version', 'visibility', 'generated_at', 'source', 'mode', 'enforced', 'approval',
        'question_version', 'model_policy_version', 'requested_model', 'model', 'context_schema_sha256',
        'material_inputs_sha256', 'scope', 'teams', 'answers', 'usage', 'paid_api_called'}
OPTIONAL = {'type', 'legend', 'probabilities'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def validate_report(raw):
    from scripts.evaluate_team_typesafe import ROLES, build_questions, number
    from scripts.typesafe_shared import validate_answers
    doc = parse(raw)
    if (not isinstance(doc, dict) or set(doc) != KEYS or type(doc['schema_version']) is not int
            or doc['schema_version'] != 1 or doc['visibility'] != 'private' or doc['scope'] != SCOPE
            or doc['approval'] is not False or doc['enforced'] is not False):
        raise ValueError('team advisory schema/authority invalid')
    for key in ('generated_at', 'source', 'mode', 'question_version', 'model_policy_version', 'requested_model'):
        if not isinstance(doc[key], str) or not doc[key].strip():
            raise ValueError('team advisory metadata invalid')
    if datetime.fromisoformat(doc['generated_at'].replace('Z', '+00:00')).tzinfo is None:
        raise ValueError('team advisory clock invalid')
    for key in ('context_schema_sha256', 'material_inputs_sha256'):
        if not isinstance(doc[key], str) or not re.fullmatch('[0-9a-f]{64}', doc[key]):
            raise ValueError('team advisory input digest invalid')
    questions = build_questions()
    validate_answers(doc['answers'], questions)
    for key, answer in doc['answers'].items():
        typ, criteria = questions[key]['type'], questions[key]['criteria']
        if not set(answer) <= {typ, 'confidence'} | OPTIONAL:
            raise ValueError('unexpected team advisory answer fields')
        labels = {str(i): v for i, v in enumerate(criteria)} if typ == 'score' else criteria
        if 'legend' in answer and (typ != 'score' or answer['legend'] != labels):
            raise ValueError('team advisory legend invalid')
        if 'probabilities' in answer:
            probs = answer['probabilities']
            if (not isinstance(probs, dict) or set(probs) != set(labels)
                    or any(not number(v) or v > 1 for v in probs.values())):
                raise ValueError('team advisory probabilities invalid')
    if not isinstance(doc['teams'], dict) or set(doc['teams']) != set(ROLES):
        raise ValueError('team advisory role identity changed')
    for role, row in doc['teams'].items():
        if (not isinstance(row, dict) or set(row) != {'quality', 'next_action', 'source', 'mode', 'approval', 'enforced'}
                or row['approval'] is not False or row['enforced'] is not False
                or row['source'] != doc['source'] or row['mode'] != doc['mode']
                or row['quality'] != doc['answers'][role + '_quality']
                or row['next_action'] != doc['answers'][role + '_next_action']):
            raise ValueError('team advisory role mirror/authority invalid')
    local = doc['source'] == 'deterministic_local'
    if local:
        if doc['model'] is not None or doc['usage'] is not None or doc['paid_api_called'] is not False:
            raise ValueError('local advisory claimed remote usage')
    elif (doc['source'] not in {'typesafe', 'typesafe_cache'}
            or not isinstance(doc['model'], str) or not doc['model'].startswith('jev-')
            or doc['model'] in {'jev-latest', 'jev-preview'}
            or not isinstance(doc['usage'], dict)
            or not {'input_tokens', 'output_tokens'} <= set(doc['usage'])
            or any(not number(v) for v in doc['usage'].values())
            or doc['paid_api_called'] is not (doc['source'] == 'typesafe')):
        raise ValueError('remote advisory provenance invalid')
    return doc


def validate_safe_payload(payload):
    """Only the producer's bounded counts, enums, dates and digests are retained."""
    from scripts import evaluate_team_typesafe as team
    from scripts.typesafe_shared import validate_payload
    validate_payload(payload)
    def obj(value, required, optional=()):
        if not isinstance(value, dict) or not set(required) <= set(value) or not set(value) <= set(required) | set(optional):
            raise ValueError('unsafe team advisory payload fields')
    def typed(value, numbers=(), flags=(), dates=(), enums=None):
        if any(key in value and not team.number(value[key]) for key in numbers):
            raise ValueError('unsafe team advisory payload number')
        if any(key in value and type(value[key]) is not bool for key in flags):
            raise ValueError('unsafe team advisory payload flag')
        if any(key in value and not team.date(value[key]) for key in dates):
            raise ValueError('unsafe team advisory payload date')
        for key, choices in (enums or {}).items():
            if key in value and (not isinstance(value[key], str) or value[key] not in choices | {'unknown'}):
                raise ValueError('unsafe team advisory payload category')
    state = payload['state']
    obj(state, {'scope', 'approval', 'rule', 'teams', 'audits', 'material_inputs_sha256'}, {'summary_bounded'})
    if (state['scope'] != SCOPE or state['approval'] is not False
            or state['rule'] != 'Missing/unknown evidence=review, not approval. All roles advisory only.'
            or 'summary_bounded' in state and state['summary_bounded'] is not True
            or not isinstance(state['material_inputs_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', state['material_inputs_sha256'])):
        raise ValueError('unsafe team advisory payload metadata')
    obj(state['teams'], team.ROLES)
    for role, row in state['teams'].items():
        obj(row, {'card_present', 'status', 'action_kind', 'waiting_kind', 'has_action', 'has_waiting', 'learning', 'improvement'},
            {'collection_freshness', 'heartbeat', 'steps'} if role == 'secretary' else {'collection_freshness', 'heartbeat'})
        typed(row, flags={'card_present', 'has_action', 'has_waiting'},
              enums={'status': team.STATUSES, 'action_kind': team.KINDS, 'waiting_kind': team.KINDS})
        for key in ('collection_freshness', 'heartbeat'):
            if key in row:
                dates = (set(team.SOURCE_DATES) - {'captured_at'}) | {'source_capture_at'}
                obj(row[key], {'status'}, set(team.FRESH_COUNTS) | set(team.FRESH_FLAGS) | dates)
                typed(row[key], team.FRESH_COUNTS, team.FRESH_FLAGS, dates, {'status': team.STATUSES})
        learned = row['learning']
        if learned != {}:
            obj(learned, {'status', 'pending_count', 'evidence'}, {'insights', 'videos_available', 'last_review'})
            typed(learned, {'pending_count', 'insights', 'videos_available'}, dates={'last_review'}, enums={'status': team.STATUSES})
            evidence = learned['evidence']
            obj(evidence, {'items', 'confidence', 'with_locator', 'with_summary'})
            typed(evidence, {'items', 'with_locator', 'with_summary'})
            obj(evidence['confidence'], (), {'high', 'medium', 'low', 'unknown'})
            typed(evidence['confidence'], evidence['confidence'])
        improved = row['improvement']
        if improved != {}:
            obj(improved, {'status', 'state', 'blocker_kind', 'has_open_action'}, {'streak', 'stale', 'since'})
            typed(improved, {'streak'}, {'has_open_action', 'stale'}, {'since'},
                  {'status': team.STATUSES, 'state': team.STATUSES, 'blocker_kind': team.KINDS})
        if 'steps' in row:
            steps = row['steps']
            obj(steps, {'count', 'dated'}, {'source_dates', 'source_ages_hours'})
            typed(steps, {'count', 'dated'})
            for key, validator in (('source_dates', team.date), ('source_ages_hours', team.number)):
                if key in steps and (not isinstance(steps[key], list) or not all(validator(v) for v in steps[key])):
                    raise ValueError('unsafe team advisory step summary')
    obj(state['audits'], {'collector_audit', 'signal_audit'})
    for audit in state['audits'].values():
        numbers = {'products_total', 'live_channels', 'total_channels', 'empty_or_failed_count',
                   'stale_or_manual_count', 'failure_types_count', 'requested', 'ok', 'parse_failed'}
        obj(audit, (), numbers | {'severity', 'last_run_finished_at'})
        typed(audit, numbers, {'severity'}, {'last_run_finished_at'})
    return payload


def transition(base, previous, current, payload_raw, previous_transition=None):
    from scripts.evaluate_team_typesafe import (MODEL, MODEL_POLICY_VERSION, QUESTION_VERSION,
                                               ROLES, build_questions, canonical, digest, fallback)
    from scripts.publish_transaction import removed_identities
    before, prior, now = map(validate_report, (base, previous, current))
    payload = validate_safe_payload(parse(payload_raw))
    state = payload['state']
    if (payload['model'] != MODEL or payload['question_version'] != QUESTION_VERSION
            or payload['model_policy_version'] != MODEL_POLICY_VERSION or payload['questions'] != build_questions()
            or not isinstance(state, dict) or state.get('approval') is not False or state.get('scope') != SCOPE
            or not isinstance(state.get('teams'), dict) or set(state['teams']) != set(ROLES)
            or len(canonical(payload)) > 12000 or len(canonical(payload).encode('utf-8')) >= 15000):
        raise ValueError('team advisory evaluation input invalid')
    if (now['context_schema_sha256'] != digest(payload)
            or now['material_inputs_sha256'] != state.get('material_inputs_sha256')
            or now['question_version'] != payload['question_version']
            or now['model_policy_version'] != payload['model_policy_version']
            or now['requested_model'] != payload['model']):
        raise ValueError('team advisory report/input mismatch')
    if now['source'] != 'deterministic_local' and now['model'] != payload['model']:
        raise ValueError('team advisory remote model differs from requested model')
    if now['source'] == 'deterministic_local' and now['answers'] != fallback(payload):
        raise ValueError('local advisory differs from deterministic fallback')
    # Check paths, not only flattened publisher tokens: a usage key named
    # "type" cannot borrow the optional answer-metadata permission. Compare
    # both HEAD and the preceding local observation, which may differ.
    def check_removals(old, new, where=()):
        if isinstance(old, dict) and isinstance(new, dict):
            for key, value in old.items():
                path = where + (key,)
                if key not in new:
                    answer_field = ((len(path) == 3 and path[0] == 'answers') or
                                    (len(path) == 4 and path[0] == 'teams' and path[2] in {'quality', 'next_action'}))
                    if not answer_field or key not in OPTIONAL:
                        raise ValueError('team advisory removal outside optional answer metadata')
                else:
                    check_removals(value, new[key], path)
        elif isinstance(old, (dict, list)) and type(new) is not type(old):
            if where != ('usage',) or now['source'] != 'deterministic_local' or new is not None:
                raise ValueError('team advisory container replacement outside local usage')
    check_removals(before, now)
    check_removals(prior, now)
    removed = sorted(set(removed_identities(before, now, {'identity_fields': ['id']})))
    return {'schema_version': 1, 'meaning': MEANING, 'approval': False, 'enforced': False,
            'baseline_sha256': sha(base), 'previous_sha256': sha(previous), 'current_sha256': sha(current),
            'payload_sha256': sha(payload_raw), 'previous_transition_sha256': previous_transition, 'removed_tokens': removed,
            'previous_source': prior['source'], 'current_source': now['source']}


def verify_evidence(base, current, evidence):
    if base is None or current is None or not isinstance(evidence, dict):
        raise ValueError('team advisory transition evidence missing')
    archives, record = evidence['archives'], evidence['record']
    if any(sha(raw) != digest for digest, raw in archives.items()):
        raise ValueError('team advisory archive hash mismatch')
    if archives.get(sha(base)) != base or archives.get(sha(current)) != current:
        raise ValueError('team advisory exact report archive missing')
    tokens = None
    seen = set()
    while True:
        digest = sha(encode(record))
        if digest in seen or archives.get(digest) != encode(record):
            raise ValueError('team advisory transition chain forged/missing')
        seen.add(digest)
        expected = transition(archives[record['baseline_sha256']], archives[record['previous_sha256']],
                              archives[record['current_sha256']], archives[record['payload_sha256']],
                              record['previous_transition_sha256'])
        if record != expected:
            raise ValueError('team advisory transition forged/missing')
        if tokens is None:
            if record['baseline_sha256'] != sha(base) or record['current_sha256'] != sha(current):
                raise ValueError('team advisory transition report binding invalid')
            tokens = expected['removed_tokens']
        previous_digest = record['previous_transition_sha256']
        if previous_digest is None:
            if record['previous_sha256'] != record['baseline_sha256']:
                raise ValueError('team advisory initial transition lost prior history')
            return tokens
        previous = parse(archives[previous_digest])
        if sha(encode(previous)) != previous_digest or previous['current_sha256'] != record['previous_sha256']:
            raise ValueError('team advisory preceding transition mismatch')
        record = previous


def manifest_record(base, current, evidence):
    return {'path': REPORT, 'base_sha256': sha(base), 'replacement_sha256': sha(current),
            'ids': verify_evidence(base, current, evidence), 'delete_file': False, 'policy_ref': POLICY_REF,
            'transition_sha256': sha(encode(evidence['record'])),
            'reason': 'Optional advisory answer metadata replaced; exact HEAD/prior/current observations and input retained as historical, never approval or current evidence.'}


def load_evidence(root, base, current, manifest):
    records = [r for r in manifest.get('deletions', []) if isinstance(r, dict) and r.get('path') == REPORT]
    if len(records) != 1 or records[0].get('policy_ref') != POLICY_REF:
        raise ValueError('team advisory requires one exact manifest record')
    archives = load_snapshots(root, HISTORY)
    evidence = {'archives': archives, 'record': parse(archives[records[0]['transition_sha256']])}
    if records[0] != manifest_record(base, current, evidence):
        raise ValueError('team advisory manifest does not bind transition')
    return evidence


def publish_advisory(root, report, payload):
    root = Path(root).absolute()
    lock = _safe(root, LOCK)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fsync(fd)
        from scripts.evaluate_team_typesafe import build_payload
        if payload != build_payload(root):
            raise ValueError('team advisory payload differs from generation-time sources')
        base = exact_head(root, REPORT)
        previous = read_source(root, REPORT)
        old_manifest = read_source(root, MANIFEST, optional=True)
        manifest = parse(old_manifest) if old_manifest is not None else {'schema_version': 1, 'deletions': []}
        if (not isinstance(manifest, dict) or manifest.get('schema_version') != 1
                or not isinstance(manifest.get('deletions'), list)
                or any(not isinstance(r, dict) for r in manifest['deletions'])):
            raise ValueError('team advisory manifest malformed')
        existing = [r for r in manifest['deletions'] if r.get('path') == REPORT]
        if len(existing) > 1 or any(r.get('policy_ref') != POLICY_REF for r in existing):
            raise ValueError('conflicting team advisory authorization')
        retained = load_snapshots(root, HISTORY)
        if existing:
            # A committed manifest still refers to its older baseline. Validate
            # that transition against the retained exact bytes, never waive it.
            old_base = retained[existing[0]['base_sha256']]
            load_evidence(root, old_base, previous, manifest)
        elif previous != base or retained:
            raise ValueError('unbound prior team advisory/history')
        current, payload_raw = encode(report), encode(payload)
        previous_transition = existing[0]['transition_sha256'] if existing else None
        record = transition(base, previous, current, payload_raw, previous_transition)
        for raw in (base, previous, current, payload_raw, encode(record)):
            retained[sha(raw)] = raw
        evidence = {'archives': retained, 'record': record}
        manifest = deepcopy(manifest)
        manifest['deletions'] = [r for r in manifest['deletions'] if r.get('path') != REPORT] + [manifest_record(base, current, evidence)]
        def unchanged():
            if (exact_head(root, REPORT) != base or read_source(root, REPORT) != previous
                    or read_source(root, MANIFEST, optional=True) != old_manifest
                    or payload != build_payload(root)):
                raise ValueError('concurrent team advisory HEAD/report/manifest changed')
        unchanged()
        retain_snapshots(root, HISTORY, retained)
        unchanged()
        if load_snapshots(root, HISTORY) != retained:
            raise ValueError('concurrent team advisory history changed')
        atomic_write(root, MANIFEST, encode(manifest))
        if exact_head(root, REPORT) != base or read_source(root, REPORT) != previous or payload != build_payload(root):
            raise ValueError('concurrent team advisory changed before replacement')
        atomic_write(root, REPORT, current)
        verify_final(root, base, current, evidence)
        return report
    finally:
        os.close(fd)
        lock.unlink()
        sync_dir(lock.parent)


def verify_final(root, base, current, evidence):
    if read_source(root, REPORT) != current:
        raise ValueError('final team advisory bytes changed')
    final = load_evidence(root, base, current, parse(read_source(root, MANIFEST)))
    if any(final['archives'].get(key) != raw for key, raw in evidence['archives'].items()):
        raise ValueError('final team advisory history lost or changed')
