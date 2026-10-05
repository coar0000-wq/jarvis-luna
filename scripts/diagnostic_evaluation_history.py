"""Exact-byte history for one diagnostic report with narrow deletion evidence.

Missing committed HEAD is a production error; isolated tests explicitly patch
exact_head or publish_evaluation. No provider execution or policy changes.
"""
from __future__ import annotations
from copy import deepcopy
import json
import os
from pathlib import Path
from scripts.moe_evaluation_history import safe_path, atomic_write, exact_head, sha, sync_dir, LOCK_PATH
from scripts.immutable_snapshot_store import retain_snapshots
from scripts.publish_transaction import deletion_authorized, removed_identities, identity

REPORT_PATH = 'data/agents/gemini_escalation.json'
HISTORY_PATH = 'data/agents/gemini_escalation_history'
MANIFEST_PATH = 'data/publish_deletions.json'
POLICY_REF = 'scripts/diagnostic_evaluation_history.py'
MAX_REPORTS = 128
ALLOWED = {'advice', 'usage', 'reasons'}


def replacement_ids(before, current, policy):
    """Reject removals everywhere except inside three retained root fields."""
    contract = {'identity_fields': policy['identity_fields']}
    if not isinstance(before, dict) or not isinstance(current, dict):
        raise ValueError('diagnostic report must remain an object')
    def visit(old, new):
        if isinstance(old, dict):
            if not isinstance(new, dict):
                raise ValueError('unexpected diagnostic container replacement')
            for key, value in old.items():
                if key not in new:
                    raise ValueError('unexpected diagnostic field removal')
                visit(value, new[key])
        elif isinstance(old, list):
            if not isinstance(new, list) or removed_identities(old, new, contract):
                raise ValueError('unexpected diagnostic identity/list removal')
            field = identity(old + new, contract['identity_fields'])
            if field:
                rows = {str(row[field]): row for row in new}
                for row in old:
                    visit(row, rows[str(row[field])])
            elif any(isinstance(row, (dict, list)) for row in old):
                if any(row not in new for row in old):
                    raise ValueError('unexpected diagnostic unkeyed record removal')
    for key, value in before.items():
        if key not in current:
            raise ValueError('unexpected diagnostic topfield removal')
        if key not in ALLOWED:
            visit(value, current[key])
    actual = removed_identities(before, current, contract)
    permitted = []
    for key in ALLOWED:
        if key in before and key in current:
            permitted.extend(removed_identities(before[key], current[key], contract))
    if set(actual) != set(permitted):
        raise ValueError('unexpected diagnostic semantic removal')
    return sorted(set(actual))


def publication_manifest(document, base, ids, current):
    if document is None:
        document = {'schema_version': 1, 'deletions': []}
    if not isinstance(document, dict) or document.get('schema_version') != 1 or not isinstance(document.get('deletions'), list):
        raise ValueError('publish deletion manifest malformed')
    if any(not isinstance(row, dict) or not isinstance(row.get('ids', []), list) for row in document['deletions']):
        raise ValueError('publish deletion record malformed')
    result = deepcopy(document)
    result['deletions'] = [row for row in result['deletions'] if not (row.get('path') == REPORT_PATH and row.get('policy_ref') == POLICY_REF)]
    if ids:
        result['deletions'].append({'path': REPORT_PATH, 'base_sha256': sha(base), 'replacement_sha256': sha(current), 'ids': ids,
            'reason': 'Ephemeral diagnostic advice/usage/reasons replacement; exact HEAD, prior and current bytes retained by SHA256.',
            'policy_ref': POLICY_REF, 'delete_file': False})
        if not deletion_authorized(REPORT_PATH, base, ids, result, replacement=current):
            raise ValueError('diagnostic publication evidence rejected')
    return result


def publish_evaluation(root, report, report_name=REPORT_PATH):
    root = Path(root).absolute()
    if report_name != REPORT_PATH:
        raise ValueError('diagnostic evidence only supports the canonical report')
    report_path = safe_path(root, REPORT_PATH)
    manifest_path = safe_path(root, MANIFEST_PATH)
    lock = safe_path(root, LOCK_PATH)
    lock.parent.mkdir(parents=True, exist_ok=True)
    safe_path(root, lock.relative_to(root))
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fsync(fd)
        base = exact_head(root, REPORT_PATH)
        previous = report_path.read_bytes() if report_path.exists() else None
        prior_manifest = manifest_path.read_bytes() if manifest_path.exists() else None
        current = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
        policy = json.loads(safe_path(root, 'config/publish_policy.json').read_bytes())
        ids = replacement_ids(json.loads(base), json.loads(current), policy)
        if previous is not None:
            replacement_ids(json.loads(previous), json.loads(current), policy)
        manifest = publication_manifest(json.loads(prior_manifest) if prior_manifest is not None else None, base, ids, current)
        retained = {sha(base): base, sha(current): current}
        if previous is not None:
            retained[sha(previous)] = previous
        def unchanged(name, expected):
            target = safe_path(root, name)
            observed = target.read_bytes() if target.exists() else None
            if observed != expected:
                raise ValueError('concurrent diagnostic publication changed ' + name)
        def check_report():
            unchanged(REPORT_PATH, previous)
            if exact_head(root, REPORT_PATH) != base:
                raise ValueError('concurrent diagnostic HEAD report changed')
        retain_snapshots(root, HISTORY_PATH, retained, atomic_writer=atomic_write)
        check_report()
        unchanged(MANIFEST_PATH, prior_manifest)
        atomic_write(root, MANIFEST_PATH, (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        check_report()
        atomic_write(root, REPORT_PATH, current)
        return {'baseline_sha256': sha(base), 'current_sha256': sha(current), 'removed_ids': ids}
    finally:
        os.close(fd)
        lock.unlink()
        sync_dir(lock.parent)
