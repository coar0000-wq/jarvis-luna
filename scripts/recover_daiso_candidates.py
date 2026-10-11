#!/usr/bin/env python3
"""Publish-only recovery of an authenticated candidate capture. Never recollect.

Original status/pool/collector receipts remain byte-exact. Old sparse zero-count
fields are explained by a hash-bound reason manifest, not a guard exemption.
Future captures use daiso_candidate_store's stable zero-count schema.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import subprocess
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import daiso_pipeline_inputs as proof
from scripts.daiso_candidate_store import DISCOVERY_SKIP_REASONS
from scripts.github_artifact_io import fetch_github_json, fetch_artifact_bytes
from scripts.publish_transaction import deletion_authorized, removed_identities

MANIFEST = 'data/publish_deletions.json'
RECOVERY = 'data/agents/daiso_candidate_recovery.json'
COUNTER_PARENTS = {f'{slot}/prefetch_policy/skipped' for slot in
                   ('last_run', 'last_attempt', 'last_candidate_success')}


def missing_fields(old, new, where=''):
    result = []
    if isinstance(old, dict) and isinstance(new, dict):
        for key in old:
            child = (where + '/' + key).lstrip('/')
            if key not in new:
                result.append((where, key, old[key]))
            else:
                result.extend(missing_fields(old[key], new[key], child))
    return result


def preserved_snapshot_ids(old, new, old_pool, new_pool, where=''):
    """Only rotating execution-ID lists may drop IDs; the products must remain."""
    allowed = {slot + '/candidate_ids' for slot in
               ('last_run', 'last_attempt', 'last_candidate_success')}
    result = set()
    if isinstance(old, dict) and isinstance(new, dict):
        for key in old:
            if key in new:
                result.update(preserved_snapshot_ids(old[key], new[key], old_pool, new_pool,
                              (where + '/' + key).lstrip('/')))
    elif isinstance(old, list) and isinstance(new, list) and all(not isinstance(x, (dict, list)) for x in old + new):
        removed = [x for x in old if x not in new]
        if removed and where not in allowed:
            raise ValueError('unexpected rotating list removal')
        for identity in removed:
            if (not isinstance(identity, str) or identity not in old_pool.get('items', {})
                    or new_pool.get('items', {}).get(identity) != old_pool['items'][identity]):
                raise ValueError('prior candidate product was removed or changed')
            result.add(identity)
    return result


def counter_manifest(base, captured, manifest, policy, *, retained_snapshot_ids=()):
    old, new = json.loads(base), json.loads(captured)
    missing = missing_fields(old, new)
    counter_ids = set()
    for parent, key, value in missing:
        if parent not in COUNTER_PARENTS or key not in DISCOVERY_SKIP_REASONS or type(value) is not int or value < 0:
            raise ValueError('unexpected field deletion outside sparse skip counters')
        counter_ids.add(key)
    run = new.get('last_run') or {}
    tally = (run.get('prefetch_policy') or {})
    counts = tally.get('skipped') or {}
    if (any(type(v) is not int or v < 0 for v in counts.values())
            or sum(counts.values()) + tally.get('new_identities', -1)
               + tally.get('revalidation_identities', -1) != run.get('queue_size')):
        raise ValueError('zero-counter interpretation lacks full queue tally evidence')
    removed = sorted(set(removed_identities(old, new, policy, where=proof.STATUS)))
    for item in set(removed) - counter_ids:
        if item not in retained_snapshot_ids and not deletion_authorized(proof.STATUS, base, [item], manifest, replacement=captured):
            raise ValueError('non-counter removal lacks prior exact-base authorization')
    result = deepcopy(manifest)
    if removed and not deletion_authorized(proof.STATUS, base, removed, result, replacement=captured):
        result.setdefault('deletions', []).append({
            'path': proof.STATUS, 'base_sha256': proof.sha(base),
            'replacement_sha256': proof.sha(captured), 'ids': removed,
            'delete_file': False, 'policy_ref': 'scripts/recover_daiso_candidates.py',
            'reason': ('Authenticated original collector snapshot recovery: sparse per-attempt zero skip '
                       'counters were omitted by the old serializer; the complete queue tally proves zero. '
                       'Only declared latest-execution candidate-ID lists rotate: prior candidate products remain '
                       'unchanged in the pool, and the exact old status remains in the original main commit. '
                       'Other removals require existing exact-base authorization. Original capture bytes and '
                       'timestamps are unchanged and retained in GitHub attempt artifacts.')})
    if removed and not deletion_authorized(proof.STATUS, base, removed, result, replacement=captured):
        raise ValueError('recovery reason manifest failed the normal deletion guard')
    return result


def prepare(root, members, run, jobs, metadata, archive_digest, now=None):
    root = Path(root).absolute()
    observed = now or datetime.now(timezone.utc)
    proof.execution_identity(run)
    if (run.get('head_repository', {}).get('full_name') != proof.REPOSITORY
            or run.get('event') not in ('schedule', 'workflow_dispatch')):
        raise ValueError('fork or non-main dispatch source is not authorized')
    if run.get('status') != 'completed':
        raise ValueError('original attempt is not completed')
    status = json.loads(members[proof.STATUS])
    attempt = status.get('last_run') or {}
    execution = f"{run['id']}:{run['run_attempt']}:collect"
    if (attempt.get('execution_id') != execution or attempt.get('status') != 'candidates_collected'
            or attempt.get('operating_updates_enabled') is not False or attempt.get('ok') != 0):
        raise ValueError('only candidates-only, non-operating captures may be recovered')
    baseline = proof.exact_head(root, proof.STATUS)
    current_manifest = json.loads(proof.read(root, MANIFEST))
    captured_manifest = json.loads(members[MANIFEST])
    merged = deepcopy(current_manifest)
    for row in captured_manifest.get('deletions', []):
        if row not in merged.setdefault('deletions', []):
            merged['deletions'].append(row)
    policy = json.loads(proof.read(root, 'config/publish_policy.json'))
    baseline_pool = proof.exact_head(root, proof.POOL)
    retained_ids = preserved_snapshot_ids(json.loads(baseline), status,
                    json.loads(baseline_pool), json.loads(members[proof.POOL]))
    merged = counter_manifest(baseline, members[proof.STATUS], merged, policy, retained_snapshot_ids=retained_ids)
    current_index = json.loads(proof.read(root, proof.INDEX))
    for name, raw in members.items():
        if name == MANIFEST:
            continue
        if '/history/' in name or name.startswith(proof.HISTORY + '/') or name.startswith('data/daiso_real/candidate_pool_history/'):
            if proof.sha(raw) != Path(name).stem:
                raise ValueError('immutable recovery history hash mismatch')
            target = root / name
            if target.exists() and target.read_bytes() != raw:
                raise ValueError('existing immutable history cannot be replaced')
        proof.atomic_write(root, name, raw)
    matches = [entry for entry in proof.histories(root, proof.HISTORY)
               if (entry.get('receipt') or {}).get('execution_id') == execution]
    if len(matches) != 1:
        raise ValueError('original exact collector receipt is missing or ambiguous')
    receipt, _, _ = proof.verify_bound_entry(root, matches[0], run, jobs, observed)
    if receipt.get('mode') != 'candidates':
        raise ValueError('authenticated receipt is not a candidate capture')
    index = json.loads(members[proof.INDEX])
    index['history_sha256'] = sorted(set(index['history_sha256']) | set(current_index['history_sha256']))
    proof.atomic_write(root, proof.INDEX, proof.encode(index))
    proof.atomic_write(root, MANIFEST, proof.encode(merged))
    record = {'schema_version': 1, 'kind': 'candidate_metadata_recovery',
              'original_run_id': run['id'], 'original_execution_id': execution,
              'original_head_sha': run['head_sha'], 'original_finished_at': attempt['finished_at'],
              'artifact_id': metadata['id'], 'artifact_sha256': archive_digest,
              'source_sha256': proof.sha(members[proof.STATUS]),
              'candidate_pool_sha256': proof.sha(members[proof.POOL]),
              'candidate_count': attempt['candidate_count'], 'candidates_new': attempt['candidates_new'],
              'operating_changed': False, 'recollected': False, 'public_authority': False,
              'publication_run_id': os.environ.get('GITHUB_RUN_ID'), 'prepared_at': observed.isoformat()}
    proof.atomic_write(root, RECOVERY, proof.encode(record))
    return {'paths': sorted(set(members) | {RECOVERY}), 'record': record}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True, type=int)
    parser.add_argument('--artifact-id', required=True, type=int)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        expected = proof.REPOSITORY + '/.github/workflows/daiso-candidate-recovery.yml@refs/heads/main'
        if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_WORKFLOW_REF') != expected
                or args.run_id <= 0 or args.artifact_id <= 0):
            raise ValueError('actual authorized recovery workflow context required')
        endpoint = 'https://api.github.com/repos/' + proof.REPOSITORY + '/actions/'
        run = fetch_github_json(endpoint + f'runs/{args.run_id}')
        proof.execution_identity(run)
        ancestry = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', run['head_sha'], 'HEAD'], capture_output=True)
        if ancestry.returncode != 0:
            raise ValueError('original capture commit is not trusted main ancestry')
        metadata = fetch_github_json(endpoint + f'artifacts/{args.artifact_id}')
        jobs = fetch_github_json(endpoint + f"runs/{args.run_id}/attempts/{run['run_attempt']}/jobs?per_page=100")
        archive = fetch_artifact_bytes(endpoint + f'artifacts/{args.artifact_id}/zip')
        members = proof.archive_members(metadata, archive, run)
        result = prepare(root, members, run, jobs, metadata, proof.sha(archive))
        output = os.environ.get('GITHUB_OUTPUT')
        if output:
            with open(output, 'a', encoding='utf-8') as handle:
                handle.write('paths=' + ' '.join(result['paths']) + '\n')
        print('CANDIDATE_RECOVERY_PREPARED ' + json.dumps(result['record'], ensure_ascii=False))
        return 0
    except (ValueError, KeyError, OSError) as error:
        print('CANDIDATE_RECOVERY_BLOCKED ' + (str(error) if isinstance(error, ValueError) else type(error).__name__))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
