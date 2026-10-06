"""Exact-byte candidate pool history; only last_run collection snapshot may shrink."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.immutable_snapshot_store import retain_snapshots, load_snapshots, _safe, _regular, _read
from scripts.moe_evaluation_history import atomic_write, sync_dir

POOL_PATH = 'data/daiso_real/candidate_pool.json'
HISTORY_PATH = 'data/daiso_real/candidate_pool_history'
MANIFEST_PATH = 'data/publish_deletions.json'
LOCK_PATH = 'data/.evaluation-publication.lock'
POLICY_REF = 'scripts/candidate_pool_history.py'
LAST_KEYS = {'execution_id', 'at', 'new', 'updated', 'collected_ids'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def parse(raw):
    def pairs(rows):
        obj = {}
        for key, value in rows:
            if key in obj:
                raise ValueError('duplicate candidate JSON field')
            obj[key] = value
        return obj
    def constant(value):
        raise ValueError('nonfinite candidate JSON')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def clock(value):
    if not isinstance(value, str):
        raise ValueError('candidate observation clock missing')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('naive clock')
        return parsed
    except (TypeError, ValueError) as exc:
        raise ValueError('candidate observation clock invalid') from exc


def validate_pool(pool):
    if not isinstance(pool, dict) or pool.get('schema_version') != 1:
        raise ValueError('candidate pool schema invalid')
    items = pool.get('items')
    if not isinstance(items, dict) or type(pool.get('count')) is not int or pool['count'] != len(items):
        raise ValueError('candidate identity count invalid')
    for row in [pool, *items.values()]:
        if not isinstance(row, dict) or row.get('approval_required') is not True or row.get('may_publish') is not False or row.get('may_replace_operating_products') is not False:
            raise ValueError('candidate approval flags invalid')
    for key, row in items.items():
        if not isinstance(key, str) or not key or row.get('pd_no') != key:
            raise ValueError('candidate product identity invalid')
        observation = row.get('observation')
        if not isinstance(observation, dict) or not isinstance(observation.get('execution_id'), str) or not observation['execution_id'].strip():
            raise ValueError('candidate observation identity invalid')
        if observation.get('method') != 'daiso_detail' or observation.get('url') != row.get('url') or not row.get('url'):
            raise ValueError('candidate observation source invalid')
        if observation.get('captured_at') != row.get('collected_at'):
            raise ValueError('candidate observation clock mismatch')
        clock(observation['captured_at'])
    run = pool.get('last_run')
    if not isinstance(run, dict) or set(run) != LAST_KEYS or not isinstance(run['execution_id'], str) or not run['execution_id'].strip():
        raise ValueError('candidate last_run metadata invalid')
    ids = run['collected_ids']
    if not isinstance(ids, list) or any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids) or not set(ids) <= set(items):
        raise ValueError('candidate collected identities invalid')
    if any(type(run[k]) is not int or run[k] < 0 for k in ('new', 'updated')) or run['new'] + run['updated'] != len(ids):
        raise ValueError('candidate collection counts invalid')
    at = clock(run['at'])
    observed = {key for key, row in items.items() if row['observation']['execution_id'] == run['execution_id']}
    if observed != set(ids) or any(clock(items[key]['observation']['captured_at']) > at for key in ids):
        raise ValueError('candidate collection execution evidence mismatch')
    return pool


def no_removals(old, new, where=()):
    if where == ('last_run',):
        return
    if isinstance(old, dict):
        if not isinstance(new, dict) or not set(old) <= set(new):
            raise ValueError('candidate identity/field removal denied')
        for key, value in old.items():
            no_removals(value, new[key], where + (key,))
    elif isinstance(old, list):
        if old != new:
            raise ValueError('candidate semantic array replacement denied')
    elif (isinstance(new, (dict, list)) or (old is not None and type(old) is not type(new))
          or (isinstance(old, str) and old.strip() and not new.strip())):
        raise ValueError('candidate evidence erasure/type replacement denied')


def replacement_ids(base, current):
    before, after = validate_pool(parse(base)), validate_pool(parse(current))
    no_removals(before, after)
    return sorted(set(before['last_run']['collected_ids']) - set(after['last_run']['collected_ids']))


def verify_evidence(base, current, ids, snapshots):
    expected = replacement_ids(base, current)
    if not isinstance(ids, list) or ids != expected or not isinstance(snapshots, dict):
        raise ValueError('candidate replacement IDs/evidence invalid')
    if snapshots.get(sha(base)) != base or snapshots.get(sha(current)) != current:
        raise ValueError('candidate exact baseline/current archive missing')
    for digest, raw in snapshots.items():
        if sha(raw) != digest:
            raise ValueError('candidate immutable archive hash mismatch')
        replacement_ids(raw, current)
    return True


def head(root):
    p = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True)
    if p.returncode:
        raise ValueError('candidate HEAD unavailable')
    return p.stdout.strip()


def exact_head(root):
    p = subprocess.run(['git', '-C', str(root), 'show', 'HEAD:' + POOL_PATH], capture_output=True)
    if p.returncode:
        raise ValueError('candidate HEAD source unavailable')
    return p.stdout


def read_source(root, name, optional=False):
    target = _safe(root, name)
    if optional and not target.exists():
        return None
    before = target.lstat()
    _regular(before)
    raw = target.read_bytes()
    if _read(root, name, sha(raw)) != raw:
        raise ValueError('concurrent candidate source changed')
    after = target.lstat()
    if any(getattr(before, k) != getattr(after, k) for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')):
        raise ValueError('concurrent candidate source changed')
    return raw


def preserve_candidate_pool(root):
    """Archive exact HEAD, existing prior histories and current bytes; never write pool."""
    root = Path(root).absolute()
    lock = _safe(root, LOCK_PATH)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fsync(fd)
        revision, base = head(root), exact_head(root)
        current = read_source(root, POOL_PATH)
        prior_manifest = read_source(root, MANIFEST_PATH, optional=True)
        prior = load_snapshots(root, HISTORY_PATH)
        ids = replacement_ids(base, current)
        retained = dict(prior)
        retained.update({sha(base): base, sha(current): current})
        verify_evidence(base, current, ids, retained)
        document = parse(prior_manifest) if prior_manifest is not None else {'schema_version': 1, 'deletions': []}
        if not isinstance(document, dict) or document.get('schema_version') != 1 or not isinstance(document.get('deletions'), list) or any(not isinstance(row, dict) or not isinstance(row.get('ids', []), list) for row in document['deletions']):
            raise ValueError('candidate publication manifest malformed')
        manifest = deepcopy(document)
        manifest['deletions'] = [r for r in manifest['deletions'] if not (r.get('path') == POOL_PATH and r.get('policy_ref') == POLICY_REF)]
        if ids:
            manifest['deletions'].append({'path': POOL_PATH, 'base_sha256': sha(base), 'replacement_sha256': sha(current), 'ids': ids, 'delete_file': False,
                'policy_ref': POLICY_REF, 'reason': 'Execution last_run collected_ids replacement only; exact HEAD, prior and current pools retained by SHA256.'})
        def unchanged():
            if head(root) != revision or exact_head(root) != base or read_source(root, POOL_PATH) != current or read_source(root, MANIFEST_PATH, optional=True) != prior_manifest:
                raise ValueError('concurrent candidate HEAD/source/manifest changed')
        unchanged()
        retain_snapshots(root, HISTORY_PATH, retained)
        if load_snapshots(root, HISTORY_PATH) != retained:
            raise ValueError('concurrent candidate history changed')
        unchanged()
        atomic_write(root, MANIFEST_PATH, (json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))
        if head(root) != revision or exact_head(root) != base or read_source(root, POOL_PATH) != current:
            raise ValueError('concurrent candidate HEAD/source changed')
        return {'baseline_sha256': sha(base), 'current_sha256': sha(current), 'removed_ids': ids}
    finally:
        os.close(fd)
        lock.unlink()
        sync_dir(lock.parent)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = preserve_candidate_pool(args.root)
        print('CANDIDATE_POOL_HISTORY_OK ' + json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('CANDIDATE_POOL_HISTORY_BLOCKED ' + type(error).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
