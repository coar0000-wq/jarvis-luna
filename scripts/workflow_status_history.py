"""Exact HEAD/prior/current workflow history; no volatile exemption or pruning."""
from __future__ import annotations
from copy import deepcopy
import json
import os
from pathlib import Path
from scripts.moe_evaluation_history import LOCK_PATH, safe_path, sync_dir, atomic_write, exact_head, sha
from scripts.immutable_snapshot_store import retain_snapshots
from scripts.publish_transaction import deletion_authorized, removed_identities, identity

REPORT_PATH = 'data/agents/workflow_freshness.json'
HISTORY_PATH = 'data/agents/workflow_status_history'
MANIFEST_PATH = 'data/publish_deletions.json'
POLICY_REF = 'scripts/workflow_status_history.py'
MAX_REPORTS = 128
RUN_FIELDS = {'id', 'status', 'conclusion', 'event', 'created_at', 'run_started_at', 'finished_at', 'html_url', 'run_attempt', 'metadata_precision'}


def snapshot(value):
    if value is None:
        return
    if not isinstance(value, dict) or not set(value) <= RUN_FIELDS:
        raise ValueError('unexpected run snapshot fields')
    if not {'id', 'status', 'conclusion', 'event', 'created_at', 'run_started_at', 'html_url'} <= set(value):
        raise ValueError('incomplete run snapshot')
    if value['status'] == 'completed' and 'finished_at' not in value:
        raise ValueError('completed snapshot missing finished_at')
    if value['status'] != 'completed' and 'finished_at' in value:
        raise ValueError('unfinished snapshot has finished_at')
    if 'metadata_precision' in value:
        precision = value['metadata_precision']
        if (not isinstance(precision, dict)
                or set(precision) != {'created_start_inversion_seconds','capture_clocks'}
                or type(precision['created_start_inversion_seconds']) not in (int,float)
                or not 0 < precision['created_start_inversion_seconds'] <= 1
                or precision['capture_clocks'] != 'not_metadata'):
            raise ValueError('run metadata precision malformed')


def replacement_ids(before, current, policy):
    """Workflow identities and non-diagnostic fields cannot be removed."""
    contract = {'identity_fields': policy['identity_fields']}
    allowed = []
    for doc in (before, current):
        if not isinstance(doc, dict) or doc.get('schema_version') != 1 or not isinstance(doc.get('workflows'), dict):
            raise ValueError('workflow report schema invalid')
    if set(before['workflows']) != set(current['workflows']):
        raise ValueError('workflow identity replacement denied')
    def visit(old, new, where=()):
        diagnostic = len(where) == 3 and where[0] == 'workflows'
        if diagnostic and where[2] in {'latest_attempt', 'last_success'}:
            snapshot(old)
            snapshot(new)
            allowed.extend(removed_identities(old, new, contract))
            return
        if diagnostic and where[2] == 'validation_warnings':
            if not isinstance(old, list) or not isinstance(new, list) or not all(isinstance(v, str) for v in old + new):
                raise ValueError('workflow error arrays must remain strings')
            allowed.extend(removed_identities(old, new, contract))
            return
        if isinstance(old, dict):
            if not isinstance(new, dict):
                raise ValueError('workflow container replacement denied')
            for key, value in old.items():
                if key not in new:
                    raise ValueError('workflow field removal denied: ' + '/'.join(where + (key,)))
                visit(value, new[key], where + (key,))
        elif isinstance(old, list):
            if not isinstance(new, list) or removed_identities(old, new, contract):
                raise ValueError('workflow semantic list removal denied')
            field = identity(old + new, contract['identity_fields'])
            if field:
                rows = {str(row[field]): row for row in new}
                for row in old:
                    visit(row, rows[str(row[field])], where + (str(row[field]),))
    visit(before, current)
    actual = removed_identities(before, current, contract)
    if set(actual) - set(allowed):
        raise ValueError('unexpected semantic workflow removals')
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
            'reason': 'Workflow run snapshot/error replacement; exact HEAD/prior/current reports retained by SHA256.',
            'policy_ref': POLICY_REF, 'delete_file': False})
        if not deletion_authorized(report_name, base, ids, result, replacement=current):
            raise ValueError('workflow publication evidence does not satisfy removal contract')
    return result

def publish_workflow_report(root, report, report_name=REPORT_PATH):
    root = Path(root).absolute()
    if report_name != REPORT_PATH:
        raise ValueError('Workflow report evidence only supports the canonical report')
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
                raise ValueError('concurrent workflow report publication changed ' + name)
        def check_report():
            unchanged(report_name, previous)
            if exact_head(root, report_name) != base:
                raise ValueError('concurrent workflow report HEAD report changed')
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
