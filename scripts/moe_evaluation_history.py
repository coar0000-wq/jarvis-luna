"""Bounded exact-byte MoE history and narrow numeric replacement evidence."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from scripts.immutable_snapshot_store import retain_snapshots
from scripts.publish_transaction import deletion_authorized, removed_identities, identity

REPORT_PATH = 'data/knowledge/moe_tuning_report.json'
HISTORY_PATH = 'data/knowledge/moe_evaluation_history'
MANIFEST_PATH = 'data/publish_deletions.json'
LOCK_PATH = 'data/.evaluation-publication.lock'
POLICY_REF = 'scripts/moe_evaluation_history.py'
MAX_REPORTS = 128
ALLOWED = {('mean_gate_load',), ('search_space', 'experts')}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(root, name):
    root = Path(root).absolute()
    target = root / name
    if '..' in target.parts or (target != root and root not in target.parents):
        raise ValueError('evidence path escapes root')
    for p in [*reversed(target.parents), target]:
        if not p.exists() and not p.is_symlink():
            continue
        info = p.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
            raise ValueError('symlink/junction evidence path denied')
    return target


def sync_dir(directory):
    # Python cannot open directory fsync handles on Windows.
    if os.name == 'nt':
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(root, name, data, *, immutable=False):
    target = safe_path(root, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    safe_path(root, name)
    if immutable and target.exists():
        if target.read_bytes() != data:
            raise ValueError('immutable evaluation history changed')
        return
    fd, tmp = tempfile.mkstemp(prefix='.moe-write-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        safe_path(root, name)
        if immutable:
            try:
                os.link(tmp, target)  # Atomic no-overwrite publication.
            except FileExistsError:
                if target.read_bytes() != data:
                    raise ValueError('immutable evaluation history changed')
            os.unlink(tmp)
        else:
            os.replace(tmp, target)
        sync_dir(target.parent)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def exact_head(root, name):
    result = subprocess.run(['git', '-C', str(root), 'show', 'HEAD:' + name], capture_output=True)
    if result.returncode:
        raise ValueError('immutable HEAD report unavailable')
    return result.stdout


def numeric(values):
    return isinstance(values, list) and bool(values) and all(type(v) in (int, float) and math.isfinite(v) for v in values)


def replacement_ids(before, current, policy):
    """Use publisher ID spellings, never authorize fields or identity removals."""
    contract = {'identity_fields': policy['identity_fields']}
    permitted = []
    def visit(old, new, where=()):
        if where in ALLOWED:
            if not numeric(old) or not numeric(new):
                raise ValueError('replacement must remain a finite numeric vector')
            permitted.extend(removed_identities(old, new, contract))
        elif isinstance(old, dict):
            if not isinstance(new, dict):
                raise ValueError('unexpected evaluation container replacement')
            for key, value in old.items():
                if key not in new:
                    raise ValueError('unexpected evaluation field removal')
                visit(value, new[key], where + (key,))
        elif isinstance(old, list):
            if not isinstance(new, list) or removed_identities(old, new, contract):
                raise ValueError('unexpected evaluation identity/list removal')
            field = identity(old + new, contract['identity_fields'])
            if field:
                rows = {str(row[field]): row for row in new}
                for row in old:
                    visit(row, rows[str(row[field])], where + (str(row[field]),))
    visit(before, current)
    actual = removed_identities(before, current, contract)
    if set(actual) != set(permitted):
        raise ValueError('unexpected semantic evaluation removals')
    return sorted(set(actual))


def publication_manifest(document, base, ids, report_name, current):
    if document is None:
        document = {'schema_version': 1, 'deletions': []}
    if not isinstance(document, dict) or document.get('schema_version') != 1 or not isinstance(document.get('deletions'), list):
        raise ValueError('publish deletion manifest malformed')
    if any(not isinstance(row, dict) or not isinstance(row.get('ids', []), list) for row in document['deletions']):
        raise ValueError('publish deletion record malformed')
    result = deepcopy(document)
    result['deletions'] = [row for row in result['deletions'] if not (row.get('path') == report_name and row.get('policy_ref') == POLICY_REF)]
    if ids:
        result['deletions'].append({'path': report_name, 'base_sha256': sha(base), 'replacement_sha256': sha(current), 'ids': ids,
            'reason': 'Numeric evaluation vector/search-space replacement; exact baseline and current reports retained by SHA256.',
            'policy_ref': POLICY_REF, 'delete_file': False})
        if not deletion_authorized(report_name, base, ids, result, replacement=current):
            raise ValueError('publication evidence does not satisfy removal contract')
    return result


def publish_evaluation(root, report, report_name=REPORT_PATH):
    root = Path(root).absolute()
    if report_name != REPORT_PATH:
        raise ValueError('MoE evaluation evidence only supports the canonical report')
    report_path = safe_path(root, report_name)
    manifest_path = safe_path(root, MANIFEST_PATH)
    lock = safe_path(root, LOCK_PATH)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fsync(fd)
        base = exact_head(root, report_name)
        previous = report_path.read_bytes() if report_path.exists() else None
        prior_manifest = manifest_path.read_bytes() if manifest_path.exists() else None
        current = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
        policy = json.loads(safe_path(root, 'config/publish_policy.json').read_bytes())
        ids = replacement_ids(json.loads(base), json.loads(current), policy)
        if previous is not None:
            replacement_ids(json.loads(previous), json.loads(current), policy)
        document = json.loads(prior_manifest) if prior_manifest is not None else None
        manifest = publication_manifest(document, base, ids, report_name, current)
        retained = {sha(base): base, sha(current): current}
        if previous is not None:
            retained[sha(previous)] = previous
        def unchanged(name, expected):
            target = safe_path(root, name)
            observed = target.read_bytes() if target.exists() else None
            if observed != expected:
                raise ValueError('concurrent evaluation publication changed ' + name)
        def check_report():
            unchanged(report_name, previous)
            if exact_head(root, report_name) != base:
                raise ValueError('concurrent evaluation HEAD report changed')
        retain_snapshots(root, HISTORY_PATH, retained, atomic_writer=atomic_write)
        check_report()
        unchanged(MANIFEST_PATH, prior_manifest)
        atomic_write(root, MANIFEST_PATH, (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        check_report()
        atomic_write(root, report_name, current)
        return {'baseline_sha256': sha(base), 'current_sha256': sha(current), 'removed_ids': ids}
    finally:
        os.close(fd)
        lock.unlink()
        sync_dir(lock.parent)
