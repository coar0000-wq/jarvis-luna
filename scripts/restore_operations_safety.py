#!/usr/bin/env python3
"""Digest-bound operations history restoration. No bootstrap, rollback or replay.

Only fixed-repository GitHub Actions metadata is accepted. Unexplained history
changes need human reconciliation, not a speculative merge. A pending marker
survives any interrupted multi-file replacement. Readers must gate on PENDING.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'scripts') not in sys.path:
    sys.path.insert(0, str(ROOT / 'scripts'))
import github_artifact_io as transport
import jarvis_execution as execution
import jarvis_operations as core
import jarvis_recovery as recovery
import jarvis_watch as watch
import run_jarvis_operations as runner

REPOSITORY = transport.REPOSITORY
BASE = 'https://api.github.com/repos/' + REPOSITORY + '/actions/'
WORKFLOWS = frozenset(('.github/workflows/daiso-real-collection.yml',
    '.github/workflows/JARVIS-Core-Automation.yml', '.github/workflows/JARVIS-Deep-Analysis.yml'))
STATE = runner.STATE
LEDGER = execution.ExecutionStore.filename
PENDING = 'data/operations/.restore-pending.json'
MAX_FILES = 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = transport.MAX_ARCHIVE_BYTES
REPORT = re.compile(r'data/operations/reports/[A-Za-z0-9][A-Za-z0-9_.-]{0,190}\.json\Z')
UPLOAD_NAME = 'operations-safety-${{ github.run_id }}-${{ github.run_attempt }}'


class Blocked(ValueError):
    pass


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Blocked('duplicate_json_key')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(Blocked('nonfinite_json')))
    core.canonical(value)
    return value


def _pending(root):
    if execution._safe(root, PENDING).exists():
        raise Blocked('operations_restore_interrupted')


def _read(root, relative):
    path = execution._safe(root, relative)
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise Blocked('operations_file_missing_or_oversize')
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise Blocked('operations_file_oversize')
    return raw


def _snapshot(root, *, staging=()):
    _pending(root)
    files = {STATE: _read(root, STATE), LEDGER: _read(root, LEDGER)}
    directory = execution._safe(root, 'data/operations/reports')
    for path in directory.iterdir():
        relative = 'data/operations/reports/' + path.name
        execution._safe(root, relative, reports=True)
        if relative == LEDGER or path == execution._safe(root, execution.ExecutionStore.lockname) or path in staging:
            continue
        if not REPORT.fullmatch(relative) or not path.is_file():
            raise Blocked('unexpected_operations_report')
        files[relative] = _read(root, relative)
    if len(files) > MAX_FILES or sum(map(len, files.values())) > MAX_TOTAL_BYTES:
        raise Blocked('operations_snapshot_limit')
    return files


def _validate_files(files):
    if STATE not in files or LEDGER not in files:
        raise Blocked('operations_continuity_pair_missing')
    # Validate the entire candidate with existing safe IO/store and receipt APIs.
    # No policy substitution, registry modification or provider dispatch occurs.
    with tempfile.TemporaryDirectory(prefix='operations-safety-validation-') as folder:
        root = Path(folder)
        for relative, raw in files.items():
            if relative not in (STATE, LEDGER) and not REPORT.fullmatch(relative):
                raise Blocked('operations_file_scope')
            _json(raw)
            target = execution._safe(root, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        state = _json(files[STATE])
        ledger = _json(files[LEDGER])
        if not isinstance(ledger, dict) or set(ledger) - {'claims', 'used_nonces', 'global_stop', 'action_stops'}:
            raise Blocked('unknown_execution_schema')
        if 'global_stop' in ledger and type(ledger['global_stop']) is not bool:
            raise Blocked('invalid_execution_stop')
        for key in ('claims', 'used_nonces', 'action_stops'):
            if key in ledger and not isinstance(ledger[key], dict):
                raise Blocked('invalid_execution_table')
        with execution.ExecutionStore(root).transaction() as (loaded, _save):
            if loaded != ledger:
                raise Blocked('execution_safe_load_mismatch')
            # Existing validator rejects unresolved/global stops. Preserve fail
            # closed behavior rather than bypassing it to declare continuity.
            runner.validate_state(root, state)
            for key, claim in loaded.get('claims', {}).items():
                if not isinstance(claim, dict) or claim.get('status') not in ('CLAIMED', 'VERIFIED', 'RECONCILIATION_REQUIRED'):
                    raise Blocked('invalid_execution_claim')
                if not isinstance(claim.get('action_hash'), str) or not re.fullmatch('[0-9a-f]{64}', claim['action_hash']):
                    raise Blocked('invalid_claim_binding')
                execution._time(claim['claimed_at'])
                if claim['status'] != 'VERIFIED':
                    raise Blocked('unresolved_execution_claim')
                receipt = claim.get('receipt')
                if (not execution.validate_receipt(root, receipt, loaded)
                        or receipt['idempotency_key'] != key
                        or receipt['action']['policy_hash'] != execution.POLICY_HASH):
                    raise Blocked('execution_receipt_invalid')
            for receipt in state['receipts'].values():
                if not execution.validate_receipt(root, receipt, loaded):
                    raise Blocked('state_receipt_invalid')
        for tid in state['tasks']:
            core._task(state, tid)
        if state['watch']:
            watch._cursor(state['watch'])
        for pid, proposal in state['handoffs'].items():
            identity = core.digest(core._proposal_identity(proposal))
            if proposal.get('proposal_id') != pid or proposal.get('context_hash') != identity or pid != 'handoff_' + identity:
                raise Blocked('handoff_binding_invalid')
            core._task(state, proposal['task_id'])
            if proposal.get('status') == 'ACCEPTED':
                child = core._task(state, proposal['child_id'])
                if child['parent_id'] != proposal['task_id'] or child['team'] != proposal['recommended_team']:
                    raise Blocked('handoff_child_invalid')
            elif proposal.get('status') != 'PROPOSED' or proposal.get('child_id') is not None:
                raise Blocked('handoff_status_invalid')
        events = state['events']
        numbered = {k:v for k,v in events.items() if k.startswith('event_')}
        if len(numbered) != state['sequence']:
            raise Blocked('event_sequence_gap')
        for key, event in events.items():
            if key not in numbered and (not isinstance(event, dict) or event.get('event_id') != key or watch._event_id(event) != key):
                raise Blocked('watch_event_binding_invalid')
        for number in range(1, state['sequence'] + 1):
            key = 'event_' + str(number).zfill(12)
            event = events.get(key)
            if not isinstance(event, dict) or event.get('event_id') != key or type(event.get('sequence')) is not int or event['sequence'] != number:
                raise Blocked('event_sequence_invalid')
        recovery.validate(state)
        return state, ledger


def verify_current(root):
    root = Path(root).absolute()
    _pending(root)
    if execution._safe(root, runner.LOCK).exists() or execution._safe(root, execution.ExecutionStore.lockname).exists():
        raise Blocked('operations_locked_or_interrupted')
    files = _snapshot(root)
    _validate_files(files)
    return files


def _extension(old, new):
    """Unknown structures may only extend maps/lists without editing a value."""
    if type(old) is not type(new):
        raise Blocked('history_type_changed')
    if isinstance(old, dict):
        for key, value in old.items():
            if key not in new:
                raise Blocked('history_key_lost')
            _extension(value, new[key])
    elif isinstance(old, list):
        if len(new) < len(old) or new[:len(old)] != old:
            raise Blocked('history_prefix_changed')
    elif old != new:
        raise Blocked('unproved_history_edit')


def _watch_continuation(old, new, events):
    if not old:
        return
    watch._cursor(old)
    watch._cursor(new)
    _extension(old['seen_events'], new['seen_events'])
    if not set(old['sources']) <= set(new['sources']):
        raise Blocked('watch_cursor_source_lost')
    # sources is current derived observation, not an authorization/history table.
    for team, source in new['sources'].items():
        expected = watch.SOURCE_MAPPINGS[team][0]
        allowed = {expected}
        if team in ('sourcing', 'pricing'):
            allowed.add(watch.SHORTLIST_OBSERVATIONS)
        if source.get('source') not in allowed:
            raise Blocked('watch_source_binding_changed')
    for key, event in old['pending_events'].items():
        if key in new['pending_events']:
            if event != new['pending_events'][key]:
                raise Blocked('pending_event_rewritten')
        elif key not in new['seen_events'] or events.get(key) != event:
            raise Blocked('pending_event_lost')
    for team, stamp in old['last_emitted'].items():
        if team not in new['last_emitted'] or execution._time(new['last_emitted'][team]) < execution._time(stamp):
            raise Blocked('watch_cooldown_regression')


def _recovery_continuation(old, new):
    if old is None:
        return
    if new is None:
        raise Blocked('recovery_history_lost')
    for team, count in old['counters'].items():
        if new['counters'][team] < count:
            raise Blocked('recovery_counter_regression')
    mutable = {'last_detected_at','last_observed_at','current_source','blocker_codes','status',
               'attempts','attempt_receipts','escalation_code','receipt_id','recovered_evidence'}
    for key, episode in old['episodes'].items():
        after = new['episodes'].get(key)
        if not isinstance(after, dict):
            raise Blocked('recovery_episode_lost')
        _extension({k:v for k,v in episode.items() if k not in mutable},
                   {k:v for k,v in after.items() if k not in mutable})
        if after['attempts'] < episode['attempts']:
            raise Blocked('recovery_budget_reset')
        _extension(episode['attempt_receipts'], after['attempt_receipts'])
        for clock in ('last_detected_at', 'last_observed_at'):
            if execution._time(after[clock]) < execution._time(episode[clock]):
                raise Blocked('recovery_time_regression')
        for binding in ('receipt_id','recovered_evidence','escalation_code'):
            if episode[binding] is not None and after[binding] != episode[binding]:
                raise Blocked('recovery_binding_changed')
        if episode['status'] == 'RECOVERED' and after != episode:
            raise Blocked('completed_recovery_rewritten')
        if episode['status'] == 'ESCALATED' and after['status'] != 'ESCALATED':
            raise Blocked('recovery_stop_removed')


def _decisions_continuation(old, new, receipts):
    for key, decision in old.items():
        after = new.get(key)
        if after == decision:
            continue
        if not isinstance(after, dict) or decision.get('status') != 'PROPOSED' or after.get('status') not in ('LOCAL_OUTPUT_VERIFIED','SOURCE_EVIDENCE_CHANGED_RECONCILIATION_REQUIRED'):
            raise Blocked('decision_rewritten')
        _extension({k:v for k,v in decision.items() if k != 'status'},
                   {k:v for k,v in after.items() if k not in ('status','action_id','receipt_id')})
        receipt = receipts.get(after.get('receipt_id'))
        if not receipt or receipt['task_id'] != decision['task_id'] or receipt['action']['action_id'] != after.get('action_id'):
            raise Blocked('decision_receipt_binding_invalid')


def _nonregression(current, incoming):
    old, before = _validate_files(current)
    new, after = _validate_files(incoming)
    for relative, raw in current.items():
        if relative not in (STATE, LEDGER) and incoming.get(relative) != raw:
            raise Blocked('report_lost_or_byte_conflict')
    if new['sequence'] < old['sequence']:
        raise Blocked('sequence_regression')
    _extension(old['events'], new['events'])
    _extension(old['receipts'], new['receipts'])
    appended = [new['events']['event_' + str(n).zfill(12)] for n in range(old['sequence'] + 1, new['sequence'] + 1)]
    for tid, task in old['tasks'].items():
        other = new['tasks'].get(tid)
        if not isinstance(other, dict):
            raise Blocked('task_lost')
        mutable = {'state', 'updated_at', 'reason', 'result', 'receipt_id', 'receipt_hash'}
        _extension({k:v for k,v in task.items() if k not in mutable}, {k:v for k,v in other.items() if k not in mutable})
        for key in ('result', 'receipt_id', 'receipt_hash'):
            if task.get(key) is not None and other.get(key) != task[key]:
                raise Blocked('task_receipt_or_result_rewritten')
        if execution._time(other['updated_at']) < execution._time(task['updated_at']):
            raise Blocked('task_time_regression')
        status = task['state']
        transitions = [e for e in appended if e.get('task_id') == tid and e.get('kind') == 'TASK_TRANSITION']
        for event in transitions:
            detail = event.get('detail') or {}
            if detail.get('from') != status or detail.get('to') not in core._TRANSITIONS[status]:
                raise Blocked('task_transition_unproved')
            status = detail['to']
        if status != other['state'] or (not transitions and task != other):
            raise Blocked('task_change_without_event')
    for pid, proposal in old['handoffs'].items():
        other = new['handoffs'].get(pid)
        if other == proposal:
            continue
        if not isinstance(other, dict) or proposal['status'] != 'PROPOSED' or other['status'] != 'ACCEPTED':
            raise Blocked('handoff_rewritten')
        _extension({k:v for k,v in proposal.items() if k not in ('status','child_id')},
                   {k:v for k,v in other.items() if k not in ('status','child_id','accepted_at')})
        if not any(e.get('kind') == 'HANDOFF_ACCEPTED' and e.get('detail') == {'proposal_id':pid,'child_id':other['child_id']} for e in appended):
            raise Blocked('handoff_transition_unproved')
    # Claims/nonce/approval/signature/audit bindings stay immutable. Only known
    # fixed-schema derived watch cursors and recovery bookkeeping may advance.
    _extension(before, after)
    _watch_continuation(old['watch'], new['watch'], new['events'])
    _recovery_continuation(old.get('source_recovery'), new.get('source_recovery'))
    _decisions_continuation(old['decisions'], new['decisions'], new['receipts'])
    skip = {'sequence','events','receipts','tasks','handoffs','watch','source_recovery','decisions'}
    _extension({k:v for k,v in old.items() if k not in skip}, {k:v for k,v in new.items() if k not in skip})


def _archive(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_ARCHIVE_BYTES:
        raise Blocked('archive_size_limit')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if not entries or len(entries) > MAX_FILES + 4:
            raise Blocked('archive_count_limit')
        files, names, total, layout = {}, set(), 0, None
        for entry in entries:
            name = entry.filename
            if name in names or '\\' in name or ':' in name or name.startswith('/') or any(p in ('', '.', '..') for p in name.rstrip('/').split('/')):
                raise Blocked('archive_path_invalid')
            names.add(name)
            mode = entry.external_attr >> 16
            if (entry.flag_bits & 1 or entry.external_attr & 0x400 or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)
                    or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    or entry.file_size > MAX_FILE_BYTES or (entry.file_size > 1024 * 1024 and entry.file_size > max(1, entry.compress_size) * 200)):
                raise Blocked('archive_entry_unsafe')
            if entry.is_dir():
                if name not in ('reports/', 'data/', 'data/operations/', 'data/operations/reports/') or entry.file_size:
                    raise Blocked('archive_directory_invalid')
                continue
            if stat.S_IFMT(mode) == stat.S_IFDIR:
                raise Blocked('archive_type_invalid')
            prefix = 'data/operations/' if name.startswith('data/operations/') else ''
            if layout is not None and prefix != layout:
                raise Blocked('archive_mixed_layout')
            layout = prefix
            relative = name if prefix else 'data/operations/' + name
            if relative not in (STATE, LEDGER) and not REPORT.fullmatch(relative):
                raise Blocked('archive_file_scope')
            if relative in files:
                raise Blocked('archive_duplicate_target')
            total += entry.file_size
            if total > MAX_TOTAL_BYTES:
                raise Blocked('archive_total_limit')
            with archive.open(entry) as stream:
                body = stream.read(MAX_FILE_BYTES + 1)
            if len(body) != entry.file_size or len(body) > MAX_FILE_BYTES:
                raise Blocked('archive_read_limit')
            files[relative] = body
    _validate_files(files)
    return files


def _git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, timeout=30)


def _exact_head(root, files):
    for relative, raw in files.items():
        result = _git(root, 'show', 'HEAD:' + relative)
        if result.returncode or result.stdout != raw:
            raise Blocked('current_not_exact_tracked_head')


def _active_workflow(raw):
    # Absence of the new artifact marker proves pre-activation only when the
    # authenticated workflow bytes can be read. Any partial/unknown marker is
    # considered activated, so it cannot authorize a missing artifact.
    text = raw.decode('utf-8')
    return 'operations-safety-' in text


def _latest(root, fetch_json, current_run_id):
    payload = fetch_json(BASE + 'runs?per_page=100')
    runs = payload.get('workflow_runs') if isinstance(payload, dict) else None
    if not isinstance(runs, list):
        raise Blocked('run_history_unavailable')
    candidates = []
    for run in runs:
        if not isinstance(run, dict) or run.get('path') not in WORKFLOWS or str(run.get('id')) == str(current_run_id):
            continue
        if run.get('head_branch') != 'main' or (run.get('head_repository') or {}).get('full_name') != REPOSITORY or run.get('status') != 'completed':
            continue
        if type(run.get('id')) is not int or run['id'] <= 0 or type(run.get('run_attempt')) is not int or run['run_attempt'] <= 0:
            raise Blocked('run_identity_invalid')
        candidates.append(run)
    if not candidates:
        raise Blocked('run_history_missing')
    if len({r['id'] for r in candidates}) != len(candidates):
        raise Blocked('run_history_ambiguous')
    run = max(candidates, key=lambda r:r['id'])
    commit = run.get('head_sha', '')
    if not re.fullmatch('[0-9a-f]{40}', commit) or _git(root, 'merge-base', '--is-ancestor', commit, 'HEAD').returncode:
        raise Blocked('run_not_main_ancestor')
    workflow = _git(root, 'show', commit + ':' + run['path'])
    if workflow.returncode:
        raise Blocked('authenticated_workflow_missing')
    return run, _active_workflow(workflow.stdout)


def _sync(directory):
    if os.name != 'nt':
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


@contextmanager
def _locks(root):
    with runner.transaction(root):
        with execution.ExecutionStore(root).transaction() as (_ledger, _save):
            yield


def _stage(root, relative, raw):
    target = execution._safe(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.operations-restore-', dir=target.parent)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return Path(name)


def _restore(root, current, incoming, run):
    staged = {}
    try:
        for relative, raw in incoming.items():
            if current.get(relative) != raw:
                staged[relative] = _stage(root, relative, raw)
        if _snapshot(root, staging=tuple(staged.values())) != current:
            raise Blocked('operations_changed_during_restore')
        if not staged:
            return
        marker = execution._safe(root, PENDING)
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(core.canonical({'run_id': run['id'], 'run_attempt':run['run_attempt'],
                'before':{k:_sha(v) for k,v in current.items()}, 'after':{k:_sha(v) for k,v in incoming.items()},
                'status':'manual_reconciliation_required_if_present'}).encode())
            stream.flush()
            os.fsync(stream.fileno())
        _sync(marker.parent)
        # Outputs precede ledger/state. Marker gates every intermediate state.
        for relative in sorted(staged, key=lambda n: (n in (LEDGER, STATE), n == STATE, n)):
            target = execution._safe(root, relative)
            os.replace(staged[relative], target)
            _sync(target.parent)
        # Read exact bytes without bypassing the marker for public readers.
        if any(_read(root, relative) != raw for relative, raw in incoming.items()):
            raise Blocked('operations_restore_readback_failed')
        _validate_files(incoming)
        marker.unlink()
        _sync(marker.parent)
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)
        # Never remove the pending marker after a failed/interrupted mutation.


def restore_latest(root, *, fetch_json=transport.fetch_github_json,
                   fetch_bytes=transport.fetch_artifact_bytes, current_run_id=None):
    root = Path(root).absolute()
    current = verify_current(root)
    run, active = _latest(root, fetch_json, current_run_id)
    if not active:
        _exact_head(root, current)
        return {'continuity':'verified', 'status':'tracked_pre_activation_history', 'run_id':run['id']}
    response = fetch_json(BASE + f"runs/{run['id']}/artifacts?per_page=100")
    rows = response.get('artifacts') if isinstance(response, dict) else None
    if not isinstance(rows, list) or type(response.get('total_count')) is not int or response['total_count'] != len(rows):
        raise Blocked('artifact_listing_incomplete')
    name = f"operations-safety-{run['id']}-{run['run_attempt']}"
    artifacts = [a for a in rows if isinstance(a, dict) and a.get('name') == name]
    if len(artifacts) != 1 or artifacts[0].get('expired') is not False:
        raise Blocked('latest_operations_artifact_missing_or_ambiguous')
    artifact = artifacts[0]
    metadata = artifact.get('workflow_run') or {}
    if metadata.get('id') != run['id'] or metadata.get('head_sha') != run['head_sha'] or metadata.get('head_branch') != 'main':
        raise Blocked('artifact_lineage_invalid')
    identity = artifact.get('id')
    if type(identity) is not int or identity <= 0 or artifact.get('archive_download_url') != BASE + f'artifacts/{identity}/zip':
        raise Blocked('artifact_scope_invalid')
    digest = artifact.get('digest')
    if not isinstance(digest, str) or not re.fullmatch('sha256:[0-9a-f]{64}', digest):
        raise Blocked('authentic_artifact_digest_missing')
    raw = fetch_bytes(artifact['archive_download_url'])
    if not isinstance(raw, bytes) or _sha(raw) != digest[7:]:
        raise Blocked('artifact_digest_mismatch')
    incoming = _archive(raw)
    with _locks(root):
        _pending(root)
        current = _snapshot(root)
        try:
            _nonregression(current, incoming)
        except ValueError:
            _exact_head(root, current)
            _nonregression(incoming, current)
            return {'continuity':'verified', 'status':'artifact_history_already_preserved_in_head', 'run_id':run['id']}
        _restore(root, current, incoming, run)
    verify_current(root)
    return {'continuity':'verified', 'status':'authenticated_operations_safety_restored', 'run_id':run['id']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--verify-current', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.verify_current:
            verify_current(args.root)
            result = {'continuity':'verified', 'status':'verified_current'}
        else:
            if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
                raise Blocked('authenticated_github_runner_required')
            commit = os.environ.get('GITHUB_SHA', '')
            head = _git(args.root, 'rev-parse', '--verify', 'HEAD')
            if not re.fullmatch('[0-9a-f]{40}', commit) or head.returncode or head.stdout.strip() != commit.encode('ascii'):
                raise Blocked('authenticated_current_head_required')
            result = restore_latest(args.root, current_run_id=os.environ.get('GITHUB_RUN_ID'))
        output = os.environ.get('GITHUB_OUTPUT')
        if output:
            with open(output, 'a', encoding='utf-8') as stream:
                stream.write('operations_continuity=verified\n')
        print('OPERATIONS_SAFETY_OK ' + json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError, OverflowError,
            RecursionError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile):
        print('OPERATIONS_SAFETY_BLOCKED authenticated_history_or_reconciliation_required')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
