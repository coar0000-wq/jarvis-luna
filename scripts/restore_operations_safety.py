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
import urllib.request
import urllib.error
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


def _audit_continuation(old, new, old_sequence):
    """Audit integrity advances its head only; records and activation stay fixed."""
    if old is None:
        if new is not None and new.get('start_sequence') != old_sequence + 1:
            raise Blocked('audit_activation_sequence_invalid')
        return
    if not isinstance(new, dict):
        raise Blocked('audit_history_lost')
    _extension({k:v for k,v in old.items() if k != 'head'},
               {k:v for k,v in new.items() if k != 'head'})
    for key in ('schema_version', 'mode', 'start_sequence'):
        if old.get(key) != new.get(key):
            raise Blocked('audit_activation_rewritten')
    # _validate_files has rechecked the complete future event/record/receipt chain.


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
    _audit_continuation(old.get('audit'), new.get('audit'), old['sequence'])
    skip = {'sequence','events','receipts','tasks','handoffs','watch','source_recovery','decisions','audit'}
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


def never_started(run, fetch_json, base):
    """True only for a run GitHub cancelled before creating any job (concurrency supersede).

    Shared group main-publish keeps one pending run; GitHub cancels the older pending
    run. Such a run executed nothing, so it cannot have produced or changed safety
    evidence. Proven per run through the authenticated jobs API; any doubt keeps it.
    """
    if run.get('status') != 'completed' or run.get('conclusion') != 'cancelled':
        return False
    payload = fetch_json(base + f"runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100")
    return (isinstance(payload, dict) and payload.get('total_count') == 0
            and payload.get('jobs') == [])


def _latest(root, fetch_json, current_run_id):
    payload = fetch_json(BASE + 'runs?per_page=100')
    runs = payload.get('workflow_runs') if isinstance(payload, dict) else None
    if not isinstance(runs, list):
        raise Blocked('run_history_unavailable')
    candidates = []
    for run in runs:
        if not isinstance(run, dict) or run.get('path') not in WORKFLOWS or str(run.get('id')) == str(current_run_id):
            continue
        if run.get('id') == 37299237632:
            _incident_run(run, _ABORT_RUN)
        if run.get('path') in WORKFLOWS and run.get('head_branch') == 'main' and run.get('status') != 'completed':
            raise Blocked('producer_run_not_completed')
        if run.get('head_branch') != 'main' or (run.get('head_repository') or {}).get('full_name') != REPOSITORY or run.get('status') != 'completed':
            continue
        if type(run.get('id')) is not int or run['id'] <= 0 or type(run.get('run_attempt')) is not int or run['run_attempt'] <= 0:
            raise Blocked('run_identity_invalid')
        candidates.append(run)
    if not candidates:
        raise Blocked('run_history_missing')
    if len({r['id'] for r in candidates}) != len(candidates):
        raise Blocked('run_history_ambiguous')
    candidates = sorted(candidates, key=lambda r:r['id'], reverse=True)
    while candidates and never_started(candidates[0], fetch_json, BASE):
        candidates.pop(0)
    if not candidates:
        raise Blocked('run_history_missing')
    run = candidates[0]
    commit = run.get('head_sha', '')
    if not re.fullmatch('[0-9a-f]{40}', commit) or _git(root, 'merge-base', '--is-ancestor', commit, 'HEAD').returncode:
        raise Blocked('run_not_main_ancestor')
    workflow = _git(root, 'show', commit + ':' + run['path'])
    if workflow.returncode:
        raise Blocked('authenticated_workflow_missing')
    return run, _active_workflow(workflow.stdout)


# One reviewed incident, not a general missing-artifact fallback. These are
# comparison pins, never persisted flags or replacement history. Evidence must
# be freshly returned by the fixed authenticated GitHub transport each time.
_ABORT_RUN = _json("{\"id\":37299237632,\"run_attempt\":1,\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\",\"path\":\".github/workflows/JARVIS-Core-Automation.yml\",\"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"failure\",\"event\":\"schedule\",\"workflow_id\":336052084,\"created_at\":\"2026-10-05T10:51:33Z\",\"run_started_at\":\"2026-10-05T10:51:33Z\",\"updated_at\":\"2026-10-05T10:52:33Z\",\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37299237632\",\"jobs_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37299237632/jobs\",\"artifacts_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37299237632/artifacts\"}")
_ABORT_PREDECESSOR = _json("{\"id\":37287805994,\"run_attempt\":1,\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\",\"path\":\".github/workflows/JARVIS-Deep-Analysis.yml\",\"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"failure\",\"event\":\"schedule\",\"workflow_id\":336052085,\"created_at\":\"2026-10-05T09:06:00Z\",\"run_started_at\":\"2026-10-05T09:06:00Z\",\"updated_at\":\"2026-10-05T09:53:43Z\",\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37287805994\",\"jobs_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37287805994/jobs\",\"artifacts_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37287805994/artifacts\"}")
_ABORT_JOB = _json("{\"id\":111727736270,\"run_id\":37299237632,\"run_attempt\":1,\"name\":\"core-automation\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\",\"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"failure\",\"created_at\":\"2026-10-05T10:51:34Z\",\"started_at\":\"2026-10-05T10:51:37Z\",\"completed_at\":\"2026-10-05T10:52:32Z\",\"run_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37299237632\",\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/jobs/111727736270\"}")
_ABORT_STEPS = _json("[[1,\"Set up job\",\"completed\",\"success\",\"2026-10-05T10:51:38Z\",\"2026-10-05T10:51:39Z\"],[2,\"Run actions/checkout@692973e3d937129bcbf40652eb9f2f61becf3332\",\"completed\",\"success\",\"2026-10-05T10:51:39Z\",\"2026-10-05T10:52:09Z\"],[3,\"Python 3.11\",\"completed\",\"success\",\"2026-10-05T10:52:09Z\",\"2026-10-05T10:52:09Z\"],[4,\"Runtime dependencies\",\"completed\",\"success\",\"2026-10-05T10:52:09Z\",\"2026-10-05T10:52:12Z\"],[5,\"Restore durable source safety before observation\",\"completed\",\"success\",\"2026-10-05T10:52:12Z\",\"2026-10-05T10:52:16Z\"],[6,\"Restore immutable operations safety before execution\",\"completed\",\"success\",\"2026-10-05T10:52:16Z\",\"2026-10-05T10:52:21Z\"],[7,\"Required canonical source processing\",\"completed\",\"success\",\"2026-10-05T10:52:21Z\",\"2026-10-05T10:52:21Z\"],[8,\"Optional YouTube source status (RSS robots blocked)\",\"completed\",\"success\",\"2026-10-05T10:52:21Z\",\"2026-10-05T10:52:21Z\"],[9,\"Synthetic Google Trends refresher disabled\",\"completed\",\"success\",\"2026-10-05T10:52:21Z\",\"2026-10-05T10:52:21Z\"],[10,\"Bounded existing-team source recovery\",\"completed\",\"skipped\",\"2026-10-05T10:52:21Z\",\"2026-10-05T10:52:21Z\"],[11,\"Observe actual Actions freshness (read-only)\",\"completed\",\"success\",\"2026-10-05T10:52:21Z\",\"2026-10-05T10:52:27Z\"],[12,\"Required current canonical runtime\",\"completed\",\"skipped\",\"2026-10-05T10:52:27Z\",\"2026-10-05T10:52:27Z\"],[13,\"Aggregate actual Core outcomes before publication\",\"completed\",\"failure\",\"2026-10-05T10:52:27Z\",\"2026-10-05T10:52:27Z\"],[14,\"Required candidate release quality\",\"completed\",\"failure\",\"2026-10-05T10:52:27Z\",\"2026-10-05T10:52:28Z\"],[15,\"산출물 발행 (원격 최신 위에 이번 변경만)\",\"completed\",\"skipped\",\"2026-10-05T10:52:28Z\",\"2026-10-05T10:52:28Z\"],[16,\"Record truthful Core result\",\"completed\",\"success\",\"2026-10-05T10:52:28Z\",\"2026-10-05T10:52:28Z\"],[17,\"Pack durable source safety even after publication failure\",\"completed\",\"success\",\"2026-10-05T10:52:28Z\",\"2026-10-05T10:52:28Z\"],[18,\"Retain source safety checkpoint\",\"completed\",\"success\",\"2026-10-05T10:52:28Z\",\"2026-10-05T10:52:29Z\"],[19,\"Retain immutable operations safety history\",\"completed\",\"skipped\",\"2026-10-05T10:52:29Z\",\"2026-10-05T10:52:29Z\"],[37,\"Post Python 3.11\",\"completed\",\"skipped\",\"2026-10-05T10:52:29Z\",\"2026-10-05T10:52:29Z\"],[38,\"Post Run actions/checkout@692973e3d937129bcbf40652eb9f2f61becf3332\",\"completed\",\"success\",\"2026-10-05T10:52:29Z\",\"2026-10-05T10:52:29Z\"],[39,\"Complete job\",\"completed\",\"success\",\"2026-10-05T10:52:29Z\",\"2026-10-05T10:52:29Z\"]]")
_ABORT_SOURCE = _json("{\"id\":11340074740,\"name\":\"source-safety-37299237632-1\",\"expired\":false,\"digest\":\"sha256:40b2a52c68b01e47aeb9bc8ebf19cac15def296901a83474a5095a9d163982c7\",\"archive_download_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11340074740/zip\",\"workflow_run\":{\"id\":37299237632,\"repository_id\":1334276889,\"head_repository_id\":1334276889,\"head_branch\":\"main\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\"}}")
_ABORT_ARTIFACT_DIGEST = 'sha256:8935b43af5de1671cd89b292858ad4d812ee2af1587296651ba39f5d06eff831'
_ABORT_CODE = _json("{\"scripts/check_release_quality.py\":\"b68a7c125030a77a2ad01d83ab338f4a12658d25a4977b3af122b953c40f5b6c\",\"scripts/restore_operations_safety.py\":\"dea467c8b60ad1bd68b1a197a4eedac199352017c337e88f1d237194f9241fbc\",\"scripts/source_safety_checkpoint.py\":\"3d1073a4ed7fbb1e12f32554b87d0059bd5d522f19ac5ddc88c92f2c2079b725\",\"scripts/youtube_dropshipping_analysis.py\":\"093b892db55ff3cf8ef44443e5d3eb3dda33ad372b6615528f70e81c09edf9c8\",\"scripts/collect_workflow_status.py\":\"70a6989f3f62ebfa2fee52aaa68309f926d6128f035d0f8340d75b14f1973e03\",\".github/workflows/JARVIS-Core-Automation.yml\":\"6cec8cd96a84641951ca7887657722aba907958aa1a6b043d2f5eedb1214fb48\",\"scripts/collector_result.py\":\"db95a13d79bff5516b9d5629ea0abf922948f9125c6f3bd95d81185baf10fd63\",\"scripts/build_product_master.py\":\"86294f5fb519dd96511573e3c7731bb7cc9a5b07f7616cf4d15be31fae9b5472\"}")


def _incident_run(run, expected):
    if not isinstance(run, dict) or {k:run.get(k) for k in expected} != expected:
        raise Blocked('pre_execution_abort_run_unproved')
    for field in ('repository', 'head_repository'):
        repo = run.get(field) or {}
        if repo.get('full_name') != REPOSITORY or repo.get('id') != 1334276889:
            raise Blocked('pre_execution_abort_repository_unproved')


def _pre_execution_predecessor(root, run, fetch_json, current_run_id):
    _incident_run(run, _ABORT_RUN)
    _incident_run(fetch_json(BASE + f"runs/{run['id']}"), _ABORT_RUN)
    # A rerun or partial jobs response cannot attest to the reviewed attempt.
    payload = fetch_json(BASE + f"runs/{run['id']}/attempts/1/jobs?per_page=100")
    jobs = payload.get('jobs') if isinstance(payload, dict) else None
    if not isinstance(jobs, list) or payload.get('total_count') != 1 or len(jobs) != 1:
        raise Blocked('pre_execution_abort_jobs_incomplete')
    job = jobs[0]
    if not isinstance(job, dict) or {k:job.get(k) for k in _ABORT_JOB} != _ABORT_JOB:
        raise Blocked('pre_execution_abort_job_unproved')
    rows = job.get('steps')
    if not isinstance(rows, list) or any(not isinstance(s, dict) for s in rows):
        raise Blocked('pre_execution_abort_steps_missing')
    observed = [[s.get(k) for k in ('number','name','status','conclusion','started_at','completed_at')] for s in rows]
    # Full observed step topology/window: runtime, recovery, publication and
    # retention skipped; no unknown step or extra job can execute operations.
    if observed != _ABORT_STEPS:
        raise Blocked('pre_execution_abort_steps_unproved')
    for relative, digest in _ABORT_CODE.items():
        code = _git(root, 'show', run['head_sha'] + ':' + relative)
        if code.returncode or _sha(code.stdout) != digest:
            raise Blocked('pre_execution_abort_reviewed_code_changed')
    # Requery the bounded window, including noncompleted runs: never jump over
    # an intervening/running relevant producer or reconcile a chain of gaps.
    history = fetch_json(BASE + 'runs?per_page=100')
    history = history.get('workflow_runs') if isinstance(history, dict) else None
    if not isinstance(history, list):
        raise Blocked('pre_execution_abort_window_missing')
    window = [r for r in history if isinstance(r, dict) and r.get('path') in WORKFLOWS
              and r.get('head_branch') == 'main' and str(r.get('id')) != str(current_run_id)]
    if any(type(r.get('id')) is not int for r in window) or len({r['id'] for r in window}) != len(window):
        raise Blocked('pre_execution_abort_window_ambiguous')
    window.sort(key=lambda r:r['id'], reverse=True)
    if len(window) < 2:
        raise Blocked('pre_execution_abort_predecessor_missing')
    _incident_run(window[0], _ABORT_RUN)
    _incident_run(window[1], _ABORT_PREDECESSOR)
    prior = fetch_json(BASE + f"runs/{window[1]['id']}")
    _incident_run(prior, _ABORT_PREDECESSOR)
    if _git(root, 'merge-base', '--is-ancestor', prior['head_sha'], 'HEAD').returncode:
        raise Blocked('run_not_main_ancestor')
    return prior


# Completed zero-actuation incidents are pinned separately below. REST success
# was masked by continue-on-error: exact raw command failure, gated skipped
# actuation, and full immutable topology jointly prove these gaps, not failure.
_ZERO_GAPS = _json("{\"37396063331\":{\"run\":{\"id\":37396063331,\"run_attempt\":1,\"run_number\":60,\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\",\"path\":\".github/workflows/daiso-real-collection.yml\",\"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"failure\",\"event\":\"schedule\",\"workflow_id\":340397025,\"created_at\":\"2026-10-06T00:50:13Z\",\"run_started_at\":\"2026-10-06T00:50:13Z\",\"updated_at\":\"2026-10-06T01:49:37Z\",\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37396063331\",\"jobs_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37396063331/jobs\",\"artifacts_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37396063331/artifacts\"},\"job\":{\"id\":112052184612,\"run_id\":37396063331,\"run_attempt\":1,\"name\":\"collect\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\",\"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"failure\",\"created_at\":\"2026-10-06T00:50:13Z\",\"started_at\":\"2026-10-06T00:50:17Z\",\"completed_at\":\"2026-10-06T01:49:37Z\",\"run_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37396063331\",\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/jobs/112052184612\"},\"steps\":[[1,\"Set up job\",\"completed\",\"success\",\"2026-10-06T00:50:18Z\",\"2026-10-06T00:50:19Z\"],[2,\"Checkout\",\"completed\",\"success\",\"2026-10-06T00:50:19Z\",\"2026-10-06T00:51:04Z\"],[3,\"Setup Python\",\"completed\",\"success\",\"2026-10-06T00:51:04Z\",\"2026-10-06T00:51:05Z\"],[4,\"Install dependencies\",\"completed\",\"success\",\"2026-10-06T00:51:05Z\",\"2026-10-06T00:51:08Z\"],[5,\"Restore durable source safety before observation\",\"completed\",\"success\",\"2026-10-06T00:51:08Z\",\"2026-10-06T00:51:11Z\"],[6,\"Restore immutable operations safety before execution\",\"completed\",\"success\",\"2026-10-06T00:51:11Z\",\"2026-10-06T00:51:14Z\"],[7,\"환율 갱신 (USD/KRW)\",\"completed\",\"success\",\"2026-10-06T00:51:14Z\",\"2026-10-06T00:51:15Z\"],[8,\"뷰티 URL 큐 만들기\",\"completed\",\"success\",\"2026-10-06T00:51:15Z\",\"2026-10-06T00:51:44Z\"],[9,\"Collect Daiso products\",\"completed\",\"success\",\"2026-10-06T00:51:44Z\",\"2026-10-06T01:49:13Z\"],[10,\"실제 수집 결과 검증\",\"completed\",\"success\",\"2026-10-06T01:49:13Z\",\"2026-10-06T01:49:13Z\"],[11,\"제외 규칙으로 상품 목록 정리\",\"completed\",\"skipped\",\"2026-10-06T01:49:13Z\",\"2026-10-06T01:49:13Z\"],[12,\"Product Master 갱신 + Score Shopify demand\",\"completed\",\"skipped\",\"2026-10-06T01:49:13Z\",\"2026-10-06T01:49:13Z\"],[13,\"점수 파생 보드 재생성\",\"completed\",\"skipped\",\"2026-10-06T01:49:13Z\",\"2026-10-06T01:49:13Z\"],[14,\"Shopify 게이트 통과 Export와 Action 큐 생성\",\"completed\",\"skipped\",\"2026-10-06T01:49:13Z\",\"2026-10-06T01:49:13Z\"],[15,\"채널 후보 재생성\",\"completed\",\"skipped\",\"2026-10-06T01:49:13Z\",\"2026-10-06T01:49:13Z\"],[16,\"Keep canonical product inputs on no_change\",\"completed\",\"success\",\"2026-10-06T01:49:13Z\",\"2026-10-06T01:49:13Z\"],[17,\"Build separate candidate comparisons\",\"completed\",\"success\",\"2026-10-06T01:49:13Z\",\"2026-10-06T01:49:13Z\"],[18,\"Record actual collector stage receipt\",\"completed\",\"success\",\"2026-10-06T01:49:13Z\",\"2026-10-06T01:49:13Z\"],[19,\"Observe active shortlist source prices without operating writes\",\"completed\",\"success\",\"2026-10-06T01:49:13Z\",\"2026-10-06T01:49:14Z\"],[20,\"Observe actual Actions freshness (read-only)\",\"completed\",\"success\",\"2026-10-06T01:49:14Z\",\"2026-10-06T01:49:18Z\"],[21,\"대시보드 최종 생성\",\"completed\",\"success\",\"2026-10-06T01:49:18Z\",\"2026-10-06T01:49:23Z\"],[22,\"Validate artifacts\",\"completed\",\"skipped\",\"2026-10-06T01:49:23Z\",\"2026-10-06T01:49:23Z\"],[23,\"발행 전 감사 미리 보기\",\"completed\",\"success\",\"2026-10-06T01:49:23Z\",\"2026-10-06T01:49:23Z\"],[24,\"Summary\",\"completed\",\"success\",\"2026-10-06T01:49:23Z\",\"2026-10-06T01:49:23Z\"],[25,\"산출물 발행 (원격 최신 위에 이번 변경만)\",\"completed\",\"skipped\",\"2026-10-06T01:49:23Z\",\"2026-10-06T01:49:23Z\"],[26,\"정상 무변경 관측 metadata 발행\",\"completed\",\"failure\",\"2026-10-06T01:49:23Z\",\"2026-10-06T01:49:31Z\"],[27,\"수집 시도 진단 보존\",\"completed\",\"success\",\"2026-10-06T01:49:31Z\",\"2026-10-06T01:49:32Z\"],[28,\"Pack durable source safety even after publication failure\",\"completed\",\"success\",\"2026-10-06T01:49:32Z\",\"2026-10-06T01:49:32Z\"],[29,\"Retain source safety checkpoint\",\"completed\",\"success\",\"2026-10-06T01:49:32Z\",\"2026-10-06T01:49:34Z\"],[30,\"Retain immutable operations safety history\",\"completed\",\"skipped\",\"2026-10-06T01:49:34Z\",\"2026-10-06T01:49:34Z\"],[31,\"최종 결과\",\"completed\",\"success\",\"2026-10-06T01:49:34Z\",\"2026-10-06T01:49:34Z\"],[61,\"Post Setup Python\",\"completed\",\"skipped\",\"2026-10-06T01:49:34Z\",\"2026-10-06T01:49:34Z\"],[62,\"Post Checkout\",\"completed\",\"success\",\"2026-10-06T01:49:34Z\",\"2026-10-06T01:49:34Z\"],[63,\"Complete job\",\"completed\",\"success\",\"2026-10-06T01:49:34Z\",\"2026-10-06T01:49:34Z\"]],\"artifacts\":{\"total_count\":2,\"artifacts\":[{\"id\":11385147858,\"node_id\":\"MDg6QXJ0aWZhY3QxMTM4NTE0Nzg1OA==\",\"name\":\"daiso-attempt-37396063331-1\",\"size_in_bytes\":30162,\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11385147858\",\"archive_download_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11385147858/zip\",\"expired\":false,\"digest\":\"sha256:7e99c22e348575ca2e4fc5b8dd90eca4cf01b43c4151daab7fa89a3cd44bc3cf\",\"created_at\":\"2026-10-06T01:49:32Z\",\"updated_at\":\"2026-10-06T01:49:32Z\",\"expires_at\":\"2026-10-20T01:49:31Z\",\"workflow_run\":{\"id\":37396063331,\"repository_id\":1334276889,\"head_repository_id\":1334276889,\"head_branch\":\"main\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\"}},{\"id\":11384987935,\"node_id\":\"MDg6QXJ0aWZhY3QxMTM4NDk4NzkzNQ==\",\"name\":\"source-safety-37396063331-1\",\"size_in_bytes\":5361,\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11384987935\",\"archive_download_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11384987935/zip\",\"expired\":false,\"digest\":\"sha256:0869f49659390f307a0a97568755f1b24c01521752ad4c9b354a38bba8e5546a\",\"created_at\":\"2026-10-06T01:49:34Z\",\"updated_at\":\"2026-10-06T01:49:34Z\",\"expires_at\":\"2026-10-20T01:49:33Z\",\"workflow_run\":{\"id\":37396063331,\"repository_id\":1334276889,\"head_repository_id\":1334276889,\"head_branch\":\"main\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\"}}]},\"log_url\":\"https://github.com/coar0000-wq/jarvis-luna/commit/6fd693fff935d47745f78a5633754fb321bf56f3/checks/112052184612/logs\",\"log_bytes\":86415,\"log_sha\":\"de4e71d06c7dc3602eadfd3ff55d338dd757b3d5de32272aacd3f25ce65985b4\"},\"37398490984\":{\"run\":{\"id\":37398490984,\"run_attempt\":1,\"run_number\":602,\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\",\"path\":\".github/workflows/JARVIS-Deep-Analysis.yml\",\"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"failure\",\"event\":\"schedule\",\"workflow_id\":336052085,\"created_at\":\"2026-10-06T01:18:28Z\",\"run_started_at\":\"2026-10-06T01:18:28Z\",\"updated_at\":\"2026-10-06T02:10:32Z\",\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37398490984\",\"jobs_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37398490984/jobs\",\"artifacts_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37398490984/artifacts\"},\"job\":{\"id\":112068286778,\"run_id\":37398490984,\"run_attempt\":1,\"name\":\"Collect, normalize, graph, train and publish runtime state\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\",\"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"failure\",\"created_at\":\"2026-10-06T01:49:37Z\",\"started_at\":\"2026-10-06T01:49:40Z\",\"completed_at\":\"2026-10-06T02:10:31Z\",\"run_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37398490984\",\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/jobs/112068286778\"},\"steps\":[[1,\"Set up job\",\"completed\",\"success\",\"2026-10-06T01:49:41Z\",\"2026-10-06T01:49:42Z\"],[2,\"Checkout repository\",\"completed\",\"success\",\"2026-10-06T01:49:42Z\",\"2026-10-06T01:50:07Z\"],[3,\"Set up Python 3.11\",\"completed\",\"success\",\"2026-10-06T01:50:07Z\",\"2026-10-06T01:50:35Z\"],[4,\"Stage TypeSafe billing proof and restore shared allowance\",\"completed\",\"success\",\"2026-10-06T01:50:35Z\",\"2026-10-06T01:51:23Z\"],[5,\"Install runtime dependencies\",\"completed\",\"success\",\"2026-10-06T01:51:23Z\",\"2026-10-06T01:51:28Z\"],[6,\"Restore durable source safety before observation\",\"completed\",\"success\",\"2026-10-06T01:51:28Z\",\"2026-10-06T01:51:32Z\"],[7,\"Restore immutable operations safety before execution\",\"completed\",\"success\",\"2026-10-06T01:51:32Z\",\"2026-10-06T01:51:35Z\"],[8,\"Collect robotics sources (OpenAlex robotics + robot media RSS)\",\"completed\",\"success\",\"2026-10-06T01:51:35Z\",\"2026-10-06T01:51:46Z\"],[9,\"Collect institution reports and papers (35 orgs)\",\"completed\",\"success\",\"2026-10-06T01:51:46Z\",\"2026-10-06T01:52:45Z\"],[10,\"디자인 소스 수집 (폰트·팔레트·기사)\",\"completed\",\"success\",\"2026-10-06T01:52:45Z\",\"2026-10-06T01:52:54Z\"],[11,\"Build design team board (checklist + references)\",\"completed\",\"success\",\"2026-10-06T01:52:54Z\",\"2026-10-06T01:53:01Z\"],[12,\"지정 YouTube 채널 수집 (최신 영상 목록)\",\"completed\",\"success\",\"2026-10-06T01:53:01Z\",\"2026-10-06T01:54:22Z\"],[13,\"지정 YouTube 영상 수집 (사람이 넣은 링크)\",\"completed\",\"success\",\"2026-10-06T01:54:22Z\",\"2026-10-06T01:54:22Z\"],[14,\"논문 수집 (사람 지정)\",\"completed\",\"success\",\"2026-10-06T01:54:22Z\",\"2026-10-06T01:54:22Z\"],[15,\"Build per-team feeds (route pools + FDA for legal)\",\"completed\",\"success\",\"2026-10-06T01:54:22Z\",\"2026-10-06T01:54:29Z\"],[16,\"Collect real public sources\",\"completed\",\"success\",\"2026-10-06T01:54:29Z\",\"2026-10-06T01:54:32Z\"],[17,\"Collect Open Beauty Facts (오픈데이터, 인증 불필요)\",\"completed\",\"success\",\"2026-10-06T01:54:32Z\",\"2026-10-06T01:55:03Z\"],[18,\"Collect OliveYoung US 베스트셀러 (실수집)\",\"completed\",\"success\",\"2026-10-06T01:55:03Z\",\"2026-10-06T01:55:04Z\"],[19,\"Collect Reddit beauty RSS (AsianBeauty 등, 키 불필요)\",\"completed\",\"success\",\"2026-10-06T01:55:04Z\",\"2026-10-06T01:55:17Z\"],[20,\"Collect public trend RSS (HN + Google News)\",\"completed\",\"success\",\"2026-10-06T01:55:17Z\",\"2026-10-06T01:55:25Z\"],[21,\"Collect Google Trends beauty-only\",\"completed\",\"success\",\"2026-10-06T01:55:25Z\",\"2026-10-06T01:55:42Z\"],[22,\"Collect Google CSE (시크릿 있을 때만)\",\"completed\",\"success\",\"2026-10-06T01:55:42Z\",\"2026-10-06T01:55:42Z\"],[23,\"수동 입력 채널 반영 (data/manual/)\",\"completed\",\"success\",\"2026-10-06T01:55:42Z\",\"2026-10-06T01:55:42Z\"],[24,\"Prepare transparent real-data corpus\",\"completed\",\"success\",\"2026-10-06T01:55:42Z\",\"2026-10-06T01:55:42Z\"],[25,\"팀 자기개선 루프\",\"completed\",\"success\",\"2026-10-06T01:55:42Z\",\"2026-10-06T01:55:59Z\"],[26,\"Normalize Obsidian wikilinks\",\"completed\",\"success\",\"2026-10-06T01:55:59Z\",\"2026-10-06T01:56:23Z\"],[27,\"Rebuild Obsidian graph from real records\",\"completed\",\"success\",\"2026-10-06T01:56:23Z\",\"2026-10-06T01:56:36Z\"],[28,\"팀 허브 생성 (그래프 층 나누기)\",\"completed\",\"success\",\"2026-10-06T01:56:36Z\",\"2026-10-06T01:56:36Z\"],[29,\"MoE 튜닝 후 승격 (실측 말뭉치만)\",\"completed\",\"success\",\"2026-10-06T01:56:36Z\",\"2026-10-06T02:01:20Z\"],[30,\"MoE 팀 배정기 학습·조건부 승격\",\"completed\",\"success\",\"2026-10-06T02:01:20Z\",\"2026-10-06T02:05:21Z\"],[31,\"YouTube 검토 큐·팀 학습 보드\",\"completed\",\"success\",\"2026-10-06T02:05:21Z\",\"2026-10-06T02:05:21Z\"],[32,\"Collect Soko Glam (미국 K뷰티 편집숍)\",\"completed\",\"success\",\"2026-10-06T02:05:21Z\",\"2026-10-06T02:05:26Z\"],[33,\"Sync Global Channels and Fix Dashboard UI\",\"completed\",\"success\",\"2026-10-06T02:05:26Z\",\"2026-10-06T02:05:26Z\"],[34,\"K뷰티 미국 기사 수집 (상품군·성분 언급 집계)\",\"completed\",\"success\",\"2026-10-06T02:05:26Z\",\"2026-10-06T02:05:46Z\"],[35,\"공개 소스 4종 수집 (Trends/Wikipedia/Allure/openFDA)\",\"completed\",\"success\",\"2026-10-06T02:05:46Z\",\"2026-10-06T02:06:04Z\"],[36,\"환율 갱신 (USD/KRW)\",\"completed\",\"success\",\"2026-10-06T02:06:04Z\",\"2026-10-06T02:06:04Z\"],[37,\"Build product master (canonical_product_id)\",\"completed\",\"success\",\"2026-10-06T02:06:04Z\",\"2026-10-06T02:06:05Z\"],[38,\"Score Shopify demand (다이소 실측 지표 기반)\",\"completed\",\"success\",\"2026-10-06T02:06:05Z\",\"2026-10-06T02:06:05Z\"],[39,\"한국→미국 실배송 원가 모델 계산\",\"completed\",\"success\",\"2026-10-06T02:06:05Z\",\"2026-10-06T02:06:05Z\"],[40,\"손익 미달 상품 제외\",\"completed\",\"success\",\"2026-10-06T02:06:05Z\",\"2026-10-06T02:06:05Z\"],[41,\"제외 반영해 점수·원가 다시 계산\",\"completed\",\"success\",\"2026-10-06T02:06:05Z\",\"2026-10-06T02:06:06Z\"],[42,\"S등급 고시 필수 항목 누락 감지\",\"completed\",\"success\",\"2026-10-06T02:06:06Z\",\"2026-10-06T02:06:06Z\"],[43,\"고시 원문 수집용 무료 브라우저 준비\",\"completed\",\"success\",\"2026-10-06T02:06:06Z\",\"2026-10-06T02:06:31Z\"],[44,\"렌더링된 공식 alt에서 S등급 고시 자동 복구\",\"completed\",\"success\",\"2026-10-06T02:06:31Z\",\"2026-10-06T02:08:00Z\"],[45,\"고시 → 영문 라벨 동기화 (표기 되돌림 포함)\",\"completed\",\"success\",\"2026-10-06T02:08:00Z\",\"2026-10-06T02:08:01Z\"],[46,\"Legal auto-check (claims / functional / OTC / label)\",\"completed\",\"success\",\"2026-10-06T02:08:01Z\",\"2026-10-06T02:08:01Z\"],[47,\"Build listing gate (copy/gosi/price/legal)\",\"completed\",\"success\",\"2026-10-06T02:08:01Z\",\"2026-10-06T02:08:01Z\"],[48,\"빈 영문 카피 무료 보완\",\"completed\",\"success\",\"2026-10-06T02:08:01Z\",\"2026-10-06T02:08:02Z\"],[49,\"수출 서류 자동 준비 (HS코드·라벨 시안)\",\"completed\",\"success\",\"2026-10-06T02:08:02Z\",\"2026-10-06T02:08:04Z\"],[50,\"Product Master 게이트 동기화 + Shopify Export·Action 큐\",\"completed\",\"success\",\"2026-10-06T02:08:04Z\",\"2026-10-06T02:08:05Z\"],[51,\"내 사이트 수집 (브랜드 기준)\",\"completed\",\"success\",\"2026-10-06T02:08:05Z\",\"2026-10-06T02:08:07Z\"],[52,\"브랜드 키트 준비 (색·글꼴·규격·정책)\",\"completed\",\"success\",\"2026-10-06T02:08:07Z\",\"2026-10-06T02:08:07Z\"],[53,\"마케팅 조사 분석팀 보드 생성\",\"completed\",\"success\",\"2026-10-06T02:08:07Z\",\"2026-10-06T02:08:07Z\"],[54,\"신규 수집 채널 발굴 (제안만, 자동 등록 안 함)\",\"completed\",\"success\",\"2026-10-06T02:08:07Z\",\"2026-10-06T02:08:21Z\"],[55,\"Observe active shortlist source prices without operating writes\",\"completed\",\"success\",\"2026-10-06T02:08:21Z\",\"2026-10-06T02:08:21Z\"],[56,\"기관 수집팀 + 채널 운영팀 지속 확장\",\"completed\",\"success\",\"2026-10-06T02:08:21Z\",\"2026-10-06T02:08:42Z\"],[57,\"수집원 생존 확인 (러너에서 직접 호출)\",\"completed\",\"success\",\"2026-10-06T02:08:42Z\",\"2026-10-06T02:09:34Z\"],[58,\"Bounded existing-team source recovery\",\"completed\",\"skipped\",\"2026-10-06T02:09:34Z\",\"2026-10-06T02:09:34Z\"],[59,\"Observe actual Actions freshness (read-only)\",\"completed\",\"success\",\"2026-10-06T02:09:34Z\",\"2026-10-06T02:09:39Z\"],[60,\"에러 보고서 생성 (막힘·고장·대기·보류)\",\"completed\",\"success\",\"2026-10-06T02:09:39Z\",\"2026-10-06T02:09:39Z\"],[61,\"Generate final dashboard snapshot\",\"completed\",\"success\",\"2026-10-06T02:09:39Z\",\"2026-10-06T02:09:44Z\"],[62,\"JARVIS multi-agent + Safe Auto-Fix\",\"completed\",\"skipped\",\"2026-10-06T02:09:44Z\",\"2026-10-06T02:09:44Z\"],[63,\"Rebuild Obsidian graph after Safe Auto-Fix\",\"completed\",\"success\",\"2026-10-06T02:09:44Z\",\"2026-10-06T02:10:21Z\"],[64,\"Generate final dashboard runtime after Auto-Fix\",\"completed\",\"success\",\"2026-10-06T02:10:21Z\",\"2026-10-06T02:10:26Z\"],[65,\"Refresh typed ops plan and conditional Gemini escalation\",\"completed\",\"skipped\",\"2026-10-06T02:10:26Z\",\"2026-10-06T02:10:26Z\"],[66,\"최종 커머스·운영 heartbeat 안전 검증\",\"completed\",\"failure\",\"2026-10-06T02:10:26Z\",\"2026-10-06T02:10:26Z\"],[67,\"Validate Safe Auto-Fix report and remediation ledger\",\"completed\",\"skipped\",\"2026-10-06T02:10:26Z\",\"2026-10-06T02:10:26Z\"],[68,\"Validate real-data artifacts\",\"completed\",\"skipped\",\"2026-10-06T02:10:26Z\",\"2026-10-06T02:10:26Z\"],[69,\"Aggregate actual Deep outcomes before publication\",\"completed\",\"failure\",\"2026-10-06T02:10:26Z\",\"2026-10-06T02:10:26Z\"],[70,\"Required Deep candidate release quality\",\"completed\",\"failure\",\"2026-10-06T02:10:26Z\",\"2026-10-06T02:10:27Z\"],[71,\"산출물 발행 (원격 최신 위에 이번 변경만)\",\"completed\",\"skipped\",\"2026-10-06T02:10:27Z\",\"2026-10-06T02:10:27Z\"],[72,\"Complete summary\",\"completed\",\"success\",\"2026-10-06T02:10:27Z\",\"2026-10-06T02:10:27Z\"],[73,\"Upload TypeSafe budget receipt (best effort)\",\"completed\",\"success\",\"2026-10-06T02:10:27Z\",\"2026-10-06T02:10:28Z\"],[74,\"Pack durable source safety even after publication failure\",\"completed\",\"success\",\"2026-10-06T02:10:28Z\",\"2026-10-06T02:10:28Z\"],[75,\"Retain source safety checkpoint\",\"completed\",\"success\",\"2026-10-06T02:10:28Z\",\"2026-10-06T02:10:29Z\"],[76,\"Retain immutable operations safety history\",\"completed\",\"skipped\",\"2026-10-06T02:10:29Z\",\"2026-10-06T02:10:29Z\"],[151,\"Post Set up Python 3.11\",\"completed\",\"skipped\",\"2026-10-06T02:10:29Z\",\"2026-10-06T02:10:29Z\"],[152,\"Post Checkout repository\",\"completed\",\"success\",\"2026-10-06T02:10:29Z\",\"2026-10-06T02:10:29Z\"],[153,\"Complete job\",\"completed\",\"success\",\"2026-10-06T02:10:29Z\",\"2026-10-06T02:10:29Z\"]],\"artifacts\":{\"total_count\":2,\"artifacts\":[{\"id\":11385966574,\"node_id\":\"MDg6QXJ0aWZhY3QxMTM4NTk2NjU3NA==\",\"name\":\"source-safety-37398490984-1\",\"size_in_bytes\":5335,\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11385966574\",\"archive_download_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11385966574/zip\",\"expired\":false,\"digest\":\"sha256:f2cb9660ff16fe83fe779c28d529ab0498cc79fc4b2b56b5c5473d7bc623ac5e\",\"created_at\":\"2026-10-06T02:10:28Z\",\"updated_at\":\"2026-10-06T02:10:28Z\",\"expires_at\":\"2026-10-20T02:10:28Z\",\"workflow_run\":{\"id\":37398490984,\"repository_id\":1334276889,\"head_repository_id\":1334276889,\"head_branch\":\"main\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\"}},{\"id\":11385921628,\"node_id\":\"MDg6QXJ0aWZhY3QxMTM4NTkyMTYyOA==\",\"name\":\"typesafe-budget-receipt-37398490984-1\",\"size_in_bytes\":1357,\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11385921628\",\"archive_download_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11385921628/zip\",\"expired\":false,\"digest\":\"sha256:2799deea0346dd11d2390e7bd15a22f4b986c06dc53503146873cce002e65d24\",\"created_at\":\"2026-10-06T02:10:28Z\",\"updated_at\":\"2026-10-06T02:10:28Z\",\"expires_at\":\"2026-10-27T02:10:27Z\",\"workflow_run\":{\"id\":37398490984,\"repository_id\":1334276889,\"head_repository_id\":1334276889,\"head_branch\":\"main\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\"}}]},\"log_url\":\"https://github.com/coar0000-wq/jarvis-luna/commit/6fd693fff935d47745f78a5633754fb321bf56f3/checks/112068286778/logs\",\"log_bytes\":293070,\"log_sha\":\"8e75b5f234625317e68531a7cbf77c21ae90db7273b905a9639b7b0245549d04\"},\"37401512848\":{\"run\":{\"id\":37401512848,\"run_attempt\":1,\"run_number\":608,\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\",\"path\":\".github/workflows/JARVIS-Core-Automation.yml\",\"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"failure\",\"event\":\"schedule\",\"workflow_id\":336052084,\"created_at\":\"2026-10-06T01:54:22Z\",\"run_started_at\":\"2026-10-06T01:54:22Z\",\"updated_at\":\"2026-10-06T02:11:21Z\",\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37401512848\",\"jobs_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37401512848/jobs\",\"artifacts_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37401512848/artifacts\"},\"job\":{\"id\":112073662885,\"run_id\":37401512848,\"run_attempt\":1,\"name\":\"core-automation\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\",\"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"failure\",\"created_at\":\"2026-10-06T02:10:32Z\",\"started_at\":\"2026-10-06T02:10:34Z\",\"completed_at\":\"2026-10-06T02:11:20Z\",\"run_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37401512848\",\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/jobs/112073662885\"},\"steps\":[[1,\"Set up job\",\"completed\",\"success\",\"2026-10-06T02:10:35Z\",\"2026-10-06T02:10:36Z\"],[2,\"Run actions/checkout@692973e3d937129bcbf40652eb9f2f61becf3332\",\"completed\",\"success\",\"2026-10-06T02:10:36Z\",\"2026-10-06T02:10:59Z\"],[3,\"Python 3.11\",\"completed\",\"success\",\"2026-10-06T02:10:59Z\",\"2026-10-06T02:10:59Z\"],[4,\"Runtime dependencies\",\"completed\",\"success\",\"2026-10-06T02:10:59Z\",\"2026-10-06T02:11:02Z\"],[5,\"Restore durable source safety before observation\",\"completed\",\"success\",\"2026-10-06T02:11:02Z\",\"2026-10-06T02:11:05Z\"],[6,\"Restore immutable operations safety before execution\",\"completed\",\"success\",\"2026-10-06T02:11:05Z\",\"2026-10-06T02:11:08Z\"],[7,\"Required canonical source processing\",\"completed\",\"success\",\"2026-10-06T02:11:08Z\",\"2026-10-06T02:11:08Z\"],[8,\"Optional YouTube source status (RSS robots blocked)\",\"completed\",\"success\",\"2026-10-06T02:11:08Z\",\"2026-10-06T02:11:08Z\"],[9,\"Synthetic Google Trends refresher disabled\",\"completed\",\"success\",\"2026-10-06T02:11:08Z\",\"2026-10-06T02:11:08Z\"],[10,\"Bounded existing-team source recovery\",\"completed\",\"skipped\",\"2026-10-06T02:11:08Z\",\"2026-10-06T02:11:08Z\"],[11,\"Observe actual Actions freshness (read-only)\",\"completed\",\"success\",\"2026-10-06T02:11:08Z\",\"2026-10-06T02:11:13Z\"],[12,\"Required current canonical runtime\",\"completed\",\"skipped\",\"2026-10-06T02:11:13Z\",\"2026-10-06T02:11:13Z\"],[13,\"Aggregate actual Core outcomes before publication\",\"completed\",\"failure\",\"2026-10-06T02:11:13Z\",\"2026-10-06T02:11:13Z\"],[14,\"Required candidate release quality\",\"completed\",\"failure\",\"2026-10-06T02:11:13Z\",\"2026-10-06T02:11:13Z\"],[15,\"산출물 발행 (원격 최신 위에 이번 변경만)\",\"completed\",\"skipped\",\"2026-10-06T02:11:13Z\",\"2026-10-06T02:11:13Z\"],[16,\"Record truthful Core result\",\"completed\",\"success\",\"2026-10-06T02:11:13Z\",\"2026-10-06T02:11:13Z\"],[17,\"Pack durable source safety even after publication failure\",\"completed\",\"success\",\"2026-10-06T02:11:13Z\",\"2026-10-06T02:11:13Z\"],[18,\"Retain source safety checkpoint\",\"completed\",\"success\",\"2026-10-06T02:11:13Z\",\"2026-10-06T02:11:14Z\"],[19,\"Retain immutable operations safety history\",\"completed\",\"skipped\",\"2026-10-06T02:11:14Z\",\"2026-10-06T02:11:14Z\"],[37,\"Post Python 3.11\",\"completed\",\"skipped\",\"2026-10-06T02:11:14Z\",\"2026-10-06T02:11:14Z\"],[38,\"Post Run actions/checkout@692973e3d937129bcbf40652eb9f2f61becf3332\",\"completed\",\"success\",\"2026-10-06T02:11:14Z\",\"2026-10-06T02:11:14Z\"],[39,\"Complete job\",\"completed\",\"success\",\"2026-10-06T02:11:14Z\",\"2026-10-06T02:11:14Z\"]],\"artifacts\":{\"total_count\":1,\"artifacts\":[{\"id\":11385339937,\"node_id\":\"MDg6QXJ0aWZhY3QxMTM4NTMzOTkzNw==\",\"name\":\"source-safety-37401512848-1\",\"size_in_bytes\":5335,\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11385339937\",\"archive_download_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11385339937/zip\",\"expired\":false,\"digest\":\"sha256:0d976efb496ca92a1d4abcdfb1782e6b5aa71c025b8a12a2beeb5fb136ad1936\",\"created_at\":\"2026-10-06T02:11:14Z\",\"updated_at\":\"2026-10-06T02:11:14Z\",\"expires_at\":\"2026-10-20T02:11:13Z\",\"workflow_run\":{\"id\":37401512848,\"repository_id\":1334276889,\"head_repository_id\":1334276889,\"head_branch\":\"main\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\"}}]},\"log_url\":\"https://github.com/coar0000-wq/jarvis-luna/commit/6fd693fff935d47745f78a5633754fb321bf56f3/checks/112073662885/logs\",\"log_bytes\":35758,\"log_sha\":\"ea63bae5f25619ac68825bf1471c6dbf0541c5560c0a0e1d2886d91b800ec259\"},\"37362386981\":{\"run\":{\"id\":37362386981,\"run_attempt\":1,\"run_number\":601,\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\",\"path\":\".github/workflows/JARVIS-Deep-Analysis.yml\",\"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"failure\",\"event\":\"schedule\",\"workflow_id\":336052085,\"created_at\":\"2026-10-05T19:17:48Z\",\"run_started_at\":\"2026-10-05T19:17:48Z\",\"updated_at\":\"2026-10-05T19:37:59Z\",\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37362386981\",\"jobs_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37362386981/jobs\",\"artifacts_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37362386981/artifacts\"},\"job\":{\"id\":111939845386,\"run_id\":37362386981,\"run_attempt\":1,\"name\":\"Collect, normalize, graph, train and publish runtime state\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\",\"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"failure\",\"created_at\":\"2026-10-05T19:17:48Z\",\"started_at\":\"2026-10-05T19:18:00Z\",\"completed_at\":\"2026-10-05T19:37:58Z\",\"run_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37362386981\",\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/jobs/111939845386\"},\"steps\":[[1,\"Set up job\",\"completed\",\"success\",\"2026-10-05T19:18:01Z\",\"2026-10-05T19:18:02Z\"],[2,\"Checkout repository\",\"completed\",\"success\",\"2026-10-05T19:18:02Z\",\"2026-10-05T19:18:26Z\"],[3,\"Set up Python 3.11\",\"completed\",\"success\",\"2026-10-05T19:18:26Z\",\"2026-10-05T19:18:53Z\"],[4,\"Stage TypeSafe billing proof and restore shared allowance\",\"completed\",\"success\",\"2026-10-05T19:18:53Z\",\"2026-10-05T19:19:48Z\"],[5,\"Install runtime dependencies\",\"completed\",\"success\",\"2026-10-05T19:19:48Z\",\"2026-10-05T19:19:54Z\"],[6,\"Restore durable source safety before observation\",\"completed\",\"success\",\"2026-10-05T19:19:54Z\",\"2026-10-05T19:19:58Z\"],[7,\"Restore immutable operations safety before execution\",\"completed\",\"success\",\"2026-10-05T19:19:58Z\",\"2026-10-05T19:20:01Z\"],[8,\"Collect robotics sources (OpenAlex robotics + robot media RSS)\",\"completed\",\"success\",\"2026-10-05T19:20:01Z\",\"2026-10-05T19:20:12Z\"],[9,\"Collect institution reports and papers (35 orgs)\",\"completed\",\"success\",\"2026-10-05T19:20:12Z\",\"2026-10-05T19:21:12Z\"],[10,\"디자인 소스 수집 (폰트·팔레트·기사)\",\"completed\",\"success\",\"2026-10-05T19:21:12Z\",\"2026-10-05T19:21:21Z\"],[11,\"Build design team board (checklist + references)\",\"completed\",\"success\",\"2026-10-05T19:21:21Z\",\"2026-10-05T19:21:28Z\"],[12,\"지정 YouTube 채널 수집 (최신 영상 목록)\",\"completed\",\"success\",\"2026-10-05T19:21:28Z\",\"2026-10-05T19:22:49Z\"],[13,\"지정 YouTube 영상 수집 (사람이 넣은 링크)\",\"completed\",\"success\",\"2026-10-05T19:22:49Z\",\"2026-10-05T19:22:49Z\"],[14,\"논문 수집 (사람 지정)\",\"completed\",\"success\",\"2026-10-05T19:22:49Z\",\"2026-10-05T19:22:49Z\"],[15,\"Build per-team feeds (route pools + FDA for legal)\",\"completed\",\"success\",\"2026-10-05T19:22:49Z\",\"2026-10-05T19:22:56Z\"],[16,\"Collect real public sources\",\"completed\",\"success\",\"2026-10-05T19:22:56Z\",\"2026-10-05T19:22:59Z\"],[17,\"Collect Open Beauty Facts (오픈데이터, 인증 불필요)\",\"completed\",\"success\",\"2026-10-05T19:22:59Z\",\"2026-10-05T19:23:19Z\"],[18,\"Collect OliveYoung US 베스트셀러 (실수집)\",\"completed\",\"success\",\"2026-10-05T19:23:19Z\",\"2026-10-05T19:23:56Z\"],[19,\"Collect Reddit beauty RSS (AsianBeauty 등, 키 불필요)\",\"completed\",\"success\",\"2026-10-05T19:23:56Z\",\"2026-10-05T19:24:10Z\"],[20,\"Collect public trend RSS (HN + Google News)\",\"completed\",\"success\",\"2026-10-05T19:24:10Z\",\"2026-10-05T19:24:18Z\"],[21,\"Collect Google Trends beauty-only\",\"completed\",\"success\",\"2026-10-05T19:24:18Z\",\"2026-10-05T19:24:36Z\"],[22,\"Collect Google CSE (시크릿 있을 때만)\",\"completed\",\"success\",\"2026-10-05T19:24:36Z\",\"2026-10-05T19:24:36Z\"],[23,\"수동 입력 채널 반영 (data/manual/)\",\"completed\",\"success\",\"2026-10-05T19:24:36Z\",\"2026-10-05T19:24:36Z\"],[24,\"Prepare transparent real-data corpus\",\"completed\",\"success\",\"2026-10-05T19:24:36Z\",\"2026-10-05T19:24:36Z\"],[25,\"팀 자기개선 루프\",\"completed\",\"success\",\"2026-10-05T19:24:36Z\",\"2026-10-05T19:24:53Z\"],[26,\"Normalize Obsidian wikilinks\",\"completed\",\"success\",\"2026-10-05T19:24:53Z\",\"2026-10-05T19:25:17Z\"],[27,\"Rebuild Obsidian graph from real records\",\"completed\",\"success\",\"2026-10-05T19:25:17Z\",\"2026-10-05T19:25:30Z\"],[28,\"팀 허브 생성 (그래프 층 나누기)\",\"completed\",\"success\",\"2026-10-05T19:25:30Z\",\"2026-10-05T19:25:30Z\"],[29,\"MoE 튜닝 후 승격 (실측 말뭉치만)\",\"completed\",\"success\",\"2026-10-05T19:25:30Z\",\"2026-10-05T19:31:02Z\"],[30,\"MoE 팀 배정기 학습·조건부 승격\",\"completed\",\"success\",\"2026-10-05T19:31:02Z\",\"2026-10-05T19:34:38Z\"],[31,\"YouTube 검토 큐·팀 학습 보드\",\"completed\",\"success\",\"2026-10-05T19:34:38Z\",\"2026-10-05T19:34:39Z\"],[32,\"Collect Soko Glam (미국 K뷰티 편집숍)\",\"completed\",\"success\",\"2026-10-05T19:34:39Z\",\"2026-10-05T19:34:43Z\"],[33,\"Sync Global Channels and Fix Dashboard UI\",\"completed\",\"success\",\"2026-10-05T19:34:43Z\",\"2026-10-05T19:34:44Z\"],[34,\"K뷰티 미국 기사 수집 (상품군·성분 언급 집계)\",\"completed\",\"success\",\"2026-10-05T19:34:44Z\",\"2026-10-05T19:35:04Z\"],[35,\"공개 소스 4종 수집 (Trends/Wikipedia/Allure/openFDA)\",\"completed\",\"success\",\"2026-10-05T19:35:04Z\",\"2026-10-05T19:35:21Z\"],[36,\"환율 갱신 (USD/KRW)\",\"completed\",\"success\",\"2026-10-05T19:35:21Z\",\"2026-10-05T19:35:22Z\"],[37,\"Build product master (canonical_product_id)\",\"completed\",\"success\",\"2026-10-05T19:35:22Z\",\"2026-10-05T19:35:22Z\"],[38,\"Score Shopify demand (다이소 실측 지표 기반)\",\"completed\",\"success\",\"2026-10-05T19:35:22Z\",\"2026-10-05T19:35:23Z\"],[39,\"한국→미국 실배송 원가 모델 계산\",\"completed\",\"success\",\"2026-10-05T19:35:23Z\",\"2026-10-05T19:35:23Z\"],[40,\"손익 미달 상품 제외\",\"completed\",\"success\",\"2026-10-05T19:35:23Z\",\"2026-10-05T19:35:23Z\"],[41,\"제외 반영해 점수·원가 다시 계산\",\"completed\",\"success\",\"2026-10-05T19:35:23Z\",\"2026-10-05T19:35:23Z\"],[42,\"S등급 고시 필수 항목 누락 감지\",\"completed\",\"success\",\"2026-10-05T19:35:23Z\",\"2026-10-05T19:35:23Z\"],[43,\"고시 원문 수집용 무료 브라우저 준비\",\"completed\",\"skipped\",\"2026-10-05T19:35:23Z\",\"2026-10-05T19:35:23Z\"],[44,\"렌더링된 공식 alt에서 S등급 고시 자동 복구\",\"completed\",\"skipped\",\"2026-10-05T19:35:23Z\",\"2026-10-05T19:35:23Z\"],[45,\"고시 → 영문 라벨 동기화 (표기 되돌림 포함)\",\"completed\",\"success\",\"2026-10-05T19:35:23Z\",\"2026-10-05T19:35:25Z\"],[46,\"Legal auto-check (claims / functional / OTC / label)\",\"completed\",\"success\",\"2026-10-05T19:35:25Z\",\"2026-10-05T19:35:25Z\"],[47,\"Build listing gate (copy/gosi/price/legal)\",\"completed\",\"success\",\"2026-10-05T19:35:25Z\",\"2026-10-05T19:35:25Z\"],[48,\"빈 영문 카피 무료 보완\",\"completed\",\"success\",\"2026-10-05T19:35:25Z\",\"2026-10-05T19:35:25Z\"],[49,\"수출 서류 자동 준비 (HS코드·라벨 시안)\",\"completed\",\"success\",\"2026-10-05T19:35:25Z\",\"2026-10-05T19:35:27Z\"],[50,\"Product Master 게이트 동기화 + Shopify Export·Action 큐\",\"completed\",\"success\",\"2026-10-05T19:35:27Z\",\"2026-10-05T19:35:28Z\"],[51,\"내 사이트 수집 (브랜드 기준)\",\"completed\",\"success\",\"2026-10-05T19:35:28Z\",\"2026-10-05T19:35:31Z\"],[52,\"브랜드 키트 준비 (색·글꼴·규격·정책)\",\"completed\",\"success\",\"2026-10-05T19:35:31Z\",\"2026-10-05T19:35:31Z\"],[53,\"마케팅 조사 분석팀 보드 생성\",\"completed\",\"success\",\"2026-10-05T19:35:31Z\",\"2026-10-05T19:35:31Z\"],[54,\"신규 수집 채널 발굴 (제안만, 자동 등록 안 함)\",\"completed\",\"success\",\"2026-10-05T19:35:31Z\",\"2026-10-05T19:35:45Z\"],[55,\"Observe active shortlist source prices without operating writes\",\"completed\",\"success\",\"2026-10-05T19:35:45Z\",\"2026-10-05T19:35:45Z\"],[56,\"기관 수집팀 + 채널 운영팀 지속 확장\",\"completed\",\"success\",\"2026-10-05T19:35:45Z\",\"2026-10-05T19:36:06Z\"],[57,\"수집원 생존 확인 (러너에서 직접 호출)\",\"completed\",\"success\",\"2026-10-05T19:36:06Z\",\"2026-10-05T19:37:01Z\"],[58,\"Bounded existing-team source recovery\",\"completed\",\"skipped\",\"2026-10-05T19:37:01Z\",\"2026-10-05T19:37:01Z\"],[59,\"Observe actual Actions freshness (read-only)\",\"completed\",\"success\",\"2026-10-05T19:37:01Z\",\"2026-10-05T19:37:07Z\"],[60,\"에러 보고서 생성 (막힘·고장·대기·보류)\",\"completed\",\"success\",\"2026-10-05T19:37:07Z\",\"2026-10-05T19:37:07Z\"],[61,\"Generate final dashboard snapshot\",\"completed\",\"success\",\"2026-10-05T19:37:07Z\",\"2026-10-05T19:37:12Z\"],[62,\"JARVIS multi-agent + Safe Auto-Fix\",\"completed\",\"skipped\",\"2026-10-05T19:37:12Z\",\"2026-10-05T19:37:12Z\"],[63,\"Rebuild Obsidian graph after Safe Auto-Fix\",\"completed\",\"success\",\"2026-10-05T19:37:12Z\",\"2026-10-05T19:37:48Z\"],[64,\"Generate final dashboard runtime after Auto-Fix\",\"completed\",\"success\",\"2026-10-05T19:37:48Z\",\"2026-10-05T19:37:53Z\"],[65,\"Refresh typed ops plan and conditional Gemini escalation\",\"completed\",\"skipped\",\"2026-10-05T19:37:53Z\",\"2026-10-05T19:37:53Z\"],[66,\"최종 커머스·운영 heartbeat 안전 검증\",\"completed\",\"failure\",\"2026-10-05T19:37:53Z\",\"2026-10-05T19:37:53Z\"],[67,\"Validate Safe Auto-Fix report and remediation ledger\",\"completed\",\"skipped\",\"2026-10-05T19:37:53Z\",\"2026-10-05T19:37:53Z\"],[68,\"Validate real-data artifacts\",\"completed\",\"skipped\",\"2026-10-05T19:37:53Z\",\"2026-10-05T19:37:53Z\"],[69,\"Aggregate actual Deep outcomes before publication\",\"completed\",\"failure\",\"2026-10-05T19:37:53Z\",\"2026-10-05T19:37:53Z\"],[70,\"Required Deep candidate release quality\",\"completed\",\"failure\",\"2026-10-05T19:37:53Z\",\"2026-10-05T19:37:53Z\"],[71,\"산출물 발행 (원격 최신 위에 이번 변경만)\",\"completed\",\"skipped\",\"2026-10-05T19:37:53Z\",\"2026-10-05T19:37:53Z\"],[72,\"Complete summary\",\"completed\",\"success\",\"2026-10-05T19:37:53Z\",\"2026-10-05T19:37:54Z\"],[73,\"Upload TypeSafe budget receipt (best effort)\",\"completed\",\"success\",\"2026-10-05T19:37:54Z\",\"2026-10-05T19:37:54Z\"],[74,\"Pack durable source safety even after publication failure\",\"completed\",\"success\",\"2026-10-05T19:37:54Z\",\"2026-10-05T19:37:55Z\"],[75,\"Retain source safety checkpoint\",\"completed\",\"success\",\"2026-10-05T19:37:55Z\",\"2026-10-05T19:37:56Z\"],[76,\"Retain immutable operations safety history\",\"completed\",\"skipped\",\"2026-10-05T19:37:56Z\",\"2026-10-05T19:37:56Z\"],[151,\"Post Set up Python 3.11\",\"completed\",\"skipped\",\"2026-10-05T19:37:56Z\",\"2026-10-05T19:37:56Z\"],[152,\"Post Checkout repository\",\"completed\",\"success\",\"2026-10-05T19:37:56Z\",\"2026-10-05T19:37:56Z\"],[153,\"Complete job\",\"completed\",\"success\",\"2026-10-05T19:37:56Z\",\"2026-10-05T19:37:56Z\"]],\"artifacts\":{\"total_count\":2,\"artifacts\":[{\"id\":11368365512,\"node_id\":\"MDg6QXJ0aWZhY3QxMTM2ODM2NTUxMg==\",\"name\":\"source-safety-37362386981-1\",\"size_in_bytes\":5353,\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11368365512\",\"archive_download_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11368365512/zip\",\"expired\":false,\"digest\":\"sha256:c7974a7a0a591aca465ec540990bcebe777fb92b5f82ffe12216b68c44e87867\",\"created_at\":\"2026-10-05T19:37:55Z\",\"updated_at\":\"2026-10-05T19:37:55Z\",\"expires_at\":\"2026-10-19T19:37:55Z\",\"workflow_run\":{\"id\":37362386981,\"repository_id\":1334276889,\"head_repository_id\":1334276889,\"head_branch\":\"main\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\"}},{\"id\":11368270566,\"node_id\":\"MDg6QXJ0aWZhY3QxMTM2ODI3MDU2Ng==\",\"name\":\"typesafe-budget-receipt-37362386981-1\",\"size_in_bytes\":1357,\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11368270566\",\"archive_download_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11368270566/zip\",\"expired\":false,\"digest\":\"sha256:47adc698f58e32560efad23a7ee92ee3da005cc3808d19a71b5f62859e89c85d\",\"created_at\":\"2026-10-05T19:37:54Z\",\"updated_at\":\"2026-10-05T19:37:54Z\",\"expires_at\":\"2026-10-26T19:37:54Z\",\"workflow_run\":{\"id\":37362386981,\"repository_id\":1334276889,\"head_repository_id\":1334276889,\"head_branch\":\"main\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\"}}]},\"log_url\":\"https://github.com/coar0000-wq/jarvis-luna/commit/6fd693fff935d47745f78a5633754fb321bf56f3/checks/111939845386/logs\",\"log_bytes\":259949,\"log_sha\":\"1de2bad8a68bc1b105225bcc56b973925d34d94cab71b036f50d020aa3116b97\"},\"37365343578\":{\"run\":{\"id\":37365343578,\"run_attempt\":1,\"run_number\":607,\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\",\"path\":\".github/workflows/JARVIS-Core-Automation.yml\",\"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"failure\",\"event\":\"schedule\",\"workflow_id\":336052084,\"created_at\":\"2026-10-05T19:44:27Z\",\"run_started_at\":\"2026-10-05T19:44:27Z\",\"updated_at\":\"2026-10-05T19:45:28Z\",\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37365343578\",\"jobs_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37365343578/jobs\",\"artifacts_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37365343578/artifacts\"},\"job\":{\"id\":111949005520,\"run_id\":37365343578,\"run_attempt\":1,\"name\":\"core-automation\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\",\"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"failure\",\"created_at\":\"2026-10-05T19:44:28Z\",\"started_at\":\"2026-10-05T19:44:38Z\",\"completed_at\":\"2026-10-05T19:45:27Z\",\"run_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37365343578\",\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/jobs/111949005520\"},\"steps\":[[1,\"Set up job\",\"completed\",\"success\",\"2026-10-05T19:44:39Z\",\"2026-10-05T19:44:40Z\"],[2,\"Run actions/checkout@692973e3d937129bcbf40652eb9f2f61becf3332\",\"completed\",\"success\",\"2026-10-05T19:44:40Z\",\"2026-10-05T19:45:07Z\"],[3,\"Python 3.11\",\"completed\",\"success\",\"2026-10-05T19:45:07Z\",\"2026-10-05T19:45:07Z\"],[4,\"Runtime dependencies\",\"completed\",\"success\",\"2026-10-05T19:45:07Z\",\"2026-10-05T19:45:09Z\"],[5,\"Restore durable source safety before observation\",\"completed\",\"success\",\"2026-10-05T19:45:09Z\",\"2026-10-05T19:45:12Z\"],[6,\"Restore immutable operations safety before execution\",\"completed\",\"success\",\"2026-10-05T19:45:12Z\",\"2026-10-05T19:45:16Z\"],[7,\"Required canonical source processing\",\"completed\",\"success\",\"2026-10-05T19:45:16Z\",\"2026-10-05T19:45:16Z\"],[8,\"Optional YouTube source status (RSS robots blocked)\",\"completed\",\"success\",\"2026-10-05T19:45:16Z\",\"2026-10-05T19:45:16Z\"],[9,\"Synthetic Google Trends refresher disabled\",\"completed\",\"success\",\"2026-10-05T19:45:16Z\",\"2026-10-05T19:45:16Z\"],[10,\"Bounded existing-team source recovery\",\"completed\",\"skipped\",\"2026-10-05T19:45:16Z\",\"2026-10-05T19:45:16Z\"],[11,\"Observe actual Actions freshness (read-only)\",\"completed\",\"success\",\"2026-10-05T19:45:16Z\",\"2026-10-05T19:45:22Z\"],[12,\"Required current canonical runtime\",\"completed\",\"skipped\",\"2026-10-05T19:45:22Z\",\"2026-10-05T19:45:22Z\"],[13,\"Aggregate actual Core outcomes before publication\",\"completed\",\"failure\",\"2026-10-05T19:45:22Z\",\"2026-10-05T19:45:22Z\"],[14,\"Required candidate release quality\",\"completed\",\"failure\",\"2026-10-05T19:45:22Z\",\"2026-10-05T19:45:22Z\"],[15,\"산출물 발행 (원격 최신 위에 이번 변경만)\",\"completed\",\"skipped\",\"2026-10-05T19:45:22Z\",\"2026-10-05T19:45:22Z\"],[16,\"Record truthful Core result\",\"completed\",\"success\",\"2026-10-05T19:45:22Z\",\"2026-10-05T19:45:22Z\"],[17,\"Pack durable source safety even after publication failure\",\"completed\",\"success\",\"2026-10-05T19:45:22Z\",\"2026-10-05T19:45:22Z\"],[18,\"Retain source safety checkpoint\",\"completed\",\"success\",\"2026-10-05T19:45:22Z\",\"2026-10-05T19:45:24Z\"],[19,\"Retain immutable operations safety history\",\"completed\",\"skipped\",\"2026-10-05T19:45:24Z\",\"2026-10-05T19:45:24Z\"],[37,\"Post Python 3.11\",\"completed\",\"skipped\",\"2026-10-05T19:45:24Z\",\"2026-10-05T19:45:24Z\"],[38,\"Post Run actions/checkout@692973e3d937129bcbf40652eb9f2f61becf3332\",\"completed\",\"success\",\"2026-10-05T19:45:24Z\",\"2026-10-05T19:45:24Z\"],[39,\"Complete job\",\"completed\",\"success\",\"2026-10-05T19:45:24Z\",\"2026-10-05T19:45:24Z\"]],\"artifacts\":{\"total_count\":1,\"artifacts\":[{\"id\":11367174500,\"node_id\":\"MDg6QXJ0aWZhY3QxMTM2NzE3NDUwMA==\",\"name\":\"source-safety-37365343578-1\",\"size_in_bytes\":5355,\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11367174500\",\"archive_download_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11367174500/zip\",\"expired\":false,\"digest\":\"sha256:c01f850026634c222443d8061f551e9f88cf16c32a01a60072eecc118e9c49ab\",\"created_at\":\"2026-10-05T19:45:23Z\",\"updated_at\":\"2026-10-05T19:45:23Z\",\"expires_at\":\"2026-10-19T19:45:22Z\",\"workflow_run\":{\"id\":37365343578,\"repository_id\":1334276889,\"head_repository_id\":1334276889,\"head_branch\":\"main\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\"}}]},\"log_url\":\"https://github.com/coar0000-wq/jarvis-luna/commit/6fd693fff935d47745f78a5633754fb321bf56f3/checks/111949005520/logs\",\"log_bytes\":36774,\"log_sha\":\"81b0654a6ba4c9d06bf5c825efb96a0f5fb72dae5dc11425edaef5dddf347176\"},\"37439906629\":{\"run\":{\"id\":37439906629,\"run_attempt\":1,\"run_number\":603,\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\",\"path\":\".github/workflows/JARVIS-Deep-Analysis.yml\",\"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"failure\",\"event\":\"schedule\",\"workflow_id\":336052085,\"created_at\":\"2026-10-06T08:59:59Z\",\"run_started_at\":\"2026-10-06T08:59:59Z\",\"updated_at\":\"2026-10-06T09:16:55Z\",\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37439906629\",\"jobs_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37439906629/jobs\",\"artifacts_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37439906629/artifacts\"},\"job\":{\"id\":112190829536,\"run_id\":37439906629,\"run_attempt\":1,\"name\":\"Collect, normalize, graph, train and publish runtime state\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\",\"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"failure\",\"created_at\":\"2026-10-06T09:00:00Z\",\"started_at\":\"2026-10-06T09:00:03Z\",\"completed_at\":\"2026-10-06T09:16:54Z\",\"run_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/runs/37439906629\",\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/jobs/112190829536\"},\"steps\":[[1,\"Set up job\",\"completed\",\"success\",\"2026-10-06T09:00:03Z\",\"2026-10-06T09:00:04Z\"],[2,\"Checkout repository\",\"completed\",\"success\",\"2026-10-06T09:00:04Z\",\"2026-10-06T09:00:22Z\"],[3,\"Set up Python 3.11\",\"completed\",\"success\",\"2026-10-06T09:00:22Z\",\"2026-10-06T09:00:50Z\"],[4,\"Stage TypeSafe billing proof and restore shared allowance\",\"completed\",\"success\",\"2026-10-06T09:00:50Z\",\"2026-10-06T09:00:58Z\"],[5,\"Install runtime dependencies\",\"completed\",\"success\",\"2026-10-06T09:00:58Z\",\"2026-10-06T09:01:01Z\"],[6,\"Restore durable source safety before observation\",\"completed\",\"success\",\"2026-10-06T09:01:01Z\",\"2026-10-06T09:01:05Z\"],[7,\"Restore immutable operations safety before execution\",\"completed\",\"success\",\"2026-10-06T09:01:05Z\",\"2026-10-06T09:01:08Z\"],[8,\"Collect robotics sources (OpenAlex robotics + robot media RSS)\",\"completed\",\"success\",\"2026-10-06T09:01:08Z\",\"2026-10-06T09:01:18Z\"],[9,\"Collect institution reports and papers (35 orgs)\",\"completed\",\"success\",\"2026-10-06T09:01:18Z\",\"2026-10-06T09:02:14Z\"],[10,\"디자인 소스 수집 (폰트·팔레트·기사)\",\"completed\",\"success\",\"2026-10-06T09:02:14Z\",\"2026-10-06T09:02:23Z\"],[11,\"Build design team board (checklist + references)\",\"completed\",\"success\",\"2026-10-06T09:02:23Z\",\"2026-10-06T09:02:29Z\"],[12,\"지정 YouTube 채널 수집 (최신 영상 목록)\",\"completed\",\"success\",\"2026-10-06T09:02:29Z\",\"2026-10-06T09:03:49Z\"],[13,\"지정 YouTube 영상 수집 (사람이 넣은 링크)\",\"completed\",\"success\",\"2026-10-06T09:03:49Z\",\"2026-10-06T09:03:49Z\"],[14,\"논문 수집 (사람 지정)\",\"completed\",\"success\",\"2026-10-06T09:03:49Z\",\"2026-10-06T09:03:49Z\"],[15,\"Build per-team feeds (route pools + FDA for legal)\",\"completed\",\"success\",\"2026-10-06T09:03:49Z\",\"2026-10-06T09:03:56Z\"],[16,\"Collect real public sources\",\"completed\",\"success\",\"2026-10-06T09:03:56Z\",\"2026-10-06T09:03:59Z\"],[17,\"Collect Open Beauty Facts (오픈데이터, 인증 불필요)\",\"completed\",\"success\",\"2026-10-06T09:03:59Z\",\"2026-10-06T09:04:24Z\"],[18,\"Collect OliveYoung US 베스트셀러 (실수집)\",\"completed\",\"success\",\"2026-10-06T09:04:24Z\",\"2026-10-06T09:04:24Z\"],[19,\"Collect Reddit beauty RSS (AsianBeauty 등, 키 불필요)\",\"completed\",\"success\",\"2026-10-06T09:04:24Z\",\"2026-10-06T09:04:38Z\"],[20,\"Collect public trend RSS (HN + Google News)\",\"completed\",\"success\",\"2026-10-06T09:04:38Z\",\"2026-10-06T09:04:47Z\"],[21,\"Collect Google Trends beauty-only\",\"completed\",\"success\",\"2026-10-06T09:04:47Z\",\"2026-10-06T09:05:03Z\"],[22,\"Collect Google CSE (시크릿 있을 때만)\",\"completed\",\"success\",\"2026-10-06T09:05:03Z\",\"2026-10-06T09:05:04Z\"],[23,\"수동 입력 채널 반영 (data/manual/)\",\"completed\",\"success\",\"2026-10-06T09:05:04Z\",\"2026-10-06T09:05:04Z\"],[24,\"Prepare transparent real-data corpus\",\"completed\",\"success\",\"2026-10-06T09:05:04Z\",\"2026-10-06T09:05:04Z\"],[25,\"팀 자기개선 루프\",\"completed\",\"success\",\"2026-10-06T09:05:04Z\",\"2026-10-06T09:05:13Z\"],[26,\"Normalize Obsidian wikilinks\",\"completed\",\"success\",\"2026-10-06T09:05:13Z\",\"2026-10-06T09:05:25Z\"],[27,\"Rebuild Obsidian graph from real records\",\"completed\",\"success\",\"2026-10-06T09:05:25Z\",\"2026-10-06T09:05:33Z\"],[28,\"팀 허브 생성 (그래프 층 나누기)\",\"completed\",\"success\",\"2026-10-06T09:05:33Z\",\"2026-10-06T09:05:33Z\"],[29,\"MoE 튜닝 후 승격 (실측 말뭉치만)\",\"completed\",\"success\",\"2026-10-06T09:05:33Z\",\"2026-10-06T09:09:17Z\"],[30,\"MoE 팀 배정기 학습·조건부 승격\",\"completed\",\"success\",\"2026-10-06T09:09:17Z\",\"2026-10-06T09:11:41Z\"],[31,\"YouTube 검토 큐·팀 학습 보드\",\"completed\",\"success\",\"2026-10-06T09:11:41Z\",\"2026-10-06T09:11:42Z\"],[32,\"Collect Soko Glam (미국 K뷰티 편집숍)\",\"completed\",\"success\",\"2026-10-06T09:11:42Z\",\"2026-10-06T09:11:46Z\"],[33,\"Sync Global Channels and Fix Dashboard UI\",\"completed\",\"success\",\"2026-10-06T09:11:46Z\",\"2026-10-06T09:11:46Z\"],[34,\"K뷰티 미국 기사 수집 (상품군·성분 언급 집계)\",\"completed\",\"success\",\"2026-10-06T09:11:46Z\",\"2026-10-06T09:12:07Z\"],[35,\"공개 소스 4종 수집 (Trends/Wikipedia/Allure/openFDA)\",\"completed\",\"success\",\"2026-10-06T09:12:07Z\",\"2026-10-06T09:12:23Z\"],[36,\"환율 갱신 (USD/KRW)\",\"completed\",\"success\",\"2026-10-06T09:12:23Z\",\"2026-10-06T09:12:24Z\"],[37,\"Build product master (canonical_product_id)\",\"completed\",\"success\",\"2026-10-06T09:12:24Z\",\"2026-10-06T09:12:24Z\"],[38,\"Score Shopify demand (다이소 실측 지표 기반)\",\"completed\",\"success\",\"2026-10-06T09:12:24Z\",\"2026-10-06T09:12:24Z\"],[39,\"한국→미국 실배송 원가 모델 계산\",\"completed\",\"success\",\"2026-10-06T09:12:24Z\",\"2026-10-06T09:12:24Z\"],[40,\"손익 미달 상품 제외\",\"completed\",\"success\",\"2026-10-06T09:12:24Z\",\"2026-10-06T09:12:24Z\"],[41,\"제외 반영해 점수·원가 다시 계산\",\"completed\",\"success\",\"2026-10-06T09:12:24Z\",\"2026-10-06T09:12:25Z\"],[42,\"S등급 고시 필수 항목 누락 감지\",\"completed\",\"success\",\"2026-10-06T09:12:25Z\",\"2026-10-06T09:12:25Z\"],[43,\"고시 원문 수집용 무료 브라우저 준비\",\"completed\",\"success\",\"2026-10-06T09:12:25Z\",\"2026-10-06T09:12:44Z\"],[44,\"렌더링된 공식 alt에서 S등급 고시 자동 복구\",\"completed\",\"success\",\"2026-10-06T09:12:44Z\",\"2026-10-06T09:14:48Z\"],[45,\"고시 → 영문 라벨 동기화 (표기 되돌림 포함)\",\"completed\",\"success\",\"2026-10-06T09:14:48Z\",\"2026-10-06T09:14:49Z\"],[46,\"Legal auto-check (claims / functional / OTC / label)\",\"completed\",\"success\",\"2026-10-06T09:14:49Z\",\"2026-10-06T09:14:49Z\"],[47,\"Build listing gate (copy/gosi/price/legal)\",\"completed\",\"success\",\"2026-10-06T09:14:49Z\",\"2026-10-06T09:14:49Z\"],[48,\"빈 영문 카피 무료 보완\",\"completed\",\"success\",\"2026-10-06T09:14:49Z\",\"2026-10-06T09:14:50Z\"],[49,\"수출 서류 자동 준비 (HS코드·라벨 시안)\",\"completed\",\"success\",\"2026-10-06T09:14:50Z\",\"2026-10-06T09:14:51Z\"],[50,\"Product Master 게이트 동기화 + Shopify Export·Action 큐\",\"completed\",\"success\",\"2026-10-06T09:14:51Z\",\"2026-10-06T09:14:52Z\"],[51,\"내 사이트 수집 (브랜드 기준)\",\"completed\",\"success\",\"2026-10-06T09:14:52Z\",\"2026-10-06T09:14:54Z\"],[52,\"브랜드 키트 준비 (색·글꼴·규격·정책)\",\"completed\",\"success\",\"2026-10-06T09:14:54Z\",\"2026-10-06T09:14:54Z\"],[53,\"마케팅 조사 분석팀 보드 생성\",\"completed\",\"success\",\"2026-10-06T09:14:54Z\",\"2026-10-06T09:14:55Z\"],[54,\"신규 수집 채널 발굴 (제안만, 자동 등록 안 함)\",\"completed\",\"success\",\"2026-10-06T09:14:55Z\",\"2026-10-06T09:15:09Z\"],[55,\"Observe active shortlist source prices without operating writes\",\"completed\",\"success\",\"2026-10-06T09:15:09Z\",\"2026-10-06T09:15:09Z\"],[56,\"기관 수집팀 + 채널 운영팀 지속 확장\",\"completed\",\"success\",\"2026-10-06T09:15:09Z\",\"2026-10-06T09:15:28Z\"],[57,\"수집원 생존 확인 (러너에서 직접 호출)\",\"completed\",\"success\",\"2026-10-06T09:15:28Z\",\"2026-10-06T09:16:19Z\"],[58,\"Bounded existing-team source recovery\",\"completed\",\"skipped\",\"2026-10-06T09:16:19Z\",\"2026-10-06T09:16:19Z\"],[59,\"Observe actual Actions freshness (read-only)\",\"completed\",\"success\",\"2026-10-06T09:16:19Z\",\"2026-10-06T09:16:25Z\"],[60,\"에러 보고서 생성 (막힘·고장·대기·보류)\",\"completed\",\"success\",\"2026-10-06T09:16:25Z\",\"2026-10-06T09:16:25Z\"],[61,\"Generate final dashboard snapshot\",\"completed\",\"success\",\"2026-10-06T09:16:25Z\",\"2026-10-06T09:16:27Z\"],[62,\"JARVIS multi-agent + Safe Auto-Fix\",\"completed\",\"skipped\",\"2026-10-06T09:16:27Z\",\"2026-10-06T09:16:27Z\"],[63,\"Rebuild Obsidian graph after Safe Auto-Fix\",\"completed\",\"success\",\"2026-10-06T09:16:27Z\",\"2026-10-06T09:16:47Z\"],[64,\"Generate final dashboard runtime after Auto-Fix\",\"completed\",\"success\",\"2026-10-06T09:16:47Z\",\"2026-10-06T09:16:50Z\"],[65,\"Refresh typed ops plan and conditional Gemini escalation\",\"completed\",\"skipped\",\"2026-10-06T09:16:50Z\",\"2026-10-06T09:16:50Z\"],[66,\"최종 커머스·운영 heartbeat 안전 검증\",\"completed\",\"failure\",\"2026-10-06T09:16:50Z\",\"2026-10-06T09:16:50Z\"],[67,\"Validate Safe Auto-Fix report and remediation ledger\",\"completed\",\"skipped\",\"2026-10-06T09:16:50Z\",\"2026-10-06T09:16:50Z\"],[68,\"Validate real-data artifacts\",\"completed\",\"skipped\",\"2026-10-06T09:16:50Z\",\"2026-10-06T09:16:50Z\"],[69,\"Aggregate actual Deep outcomes before publication\",\"completed\",\"failure\",\"2026-10-06T09:16:50Z\",\"2026-10-06T09:16:50Z\"],[70,\"Required Deep candidate release quality\",\"completed\",\"failure\",\"2026-10-06T09:16:50Z\",\"2026-10-06T09:16:50Z\"],[71,\"산출물 발행 (원격 최신 위에 이번 변경만)\",\"completed\",\"skipped\",\"2026-10-06T09:16:50Z\",\"2026-10-06T09:16:50Z\"],[72,\"Complete summary\",\"completed\",\"success\",\"2026-10-06T09:16:50Z\",\"2026-10-06T09:16:50Z\"],[73,\"Upload TypeSafe budget receipt (best effort)\",\"completed\",\"success\",\"2026-10-06T09:16:50Z\",\"2026-10-06T09:16:51Z\"],[74,\"Pack durable source safety even after publication failure\",\"completed\",\"success\",\"2026-10-06T09:16:51Z\",\"2026-10-06T09:16:51Z\"],[75,\"Retain source safety checkpoint\",\"completed\",\"success\",\"2026-10-06T09:16:51Z\",\"2026-10-06T09:16:52Z\"],[76,\"Retain immutable operations safety history\",\"completed\",\"skipped\",\"2026-10-06T09:16:52Z\",\"2026-10-06T09:16:52Z\"],[151,\"Post Set up Python 3.11\",\"completed\",\"skipped\",\"2026-10-06T09:16:52Z\",\"2026-10-06T09:16:52Z\"],[152,\"Post Checkout repository\",\"completed\",\"success\",\"2026-10-06T09:16:52Z\",\"2026-10-06T09:16:52Z\"],[153,\"Complete job\",\"completed\",\"success\",\"2026-10-06T09:16:52Z\",\"2026-10-06T09:16:52Z\"]],\"artifacts\":{\"total_count\":2,\"artifacts\":[{\"id\":11401796518,\"node_id\":\"MDg6QXJ0aWZhY3QxMTQwMTc5NjUxOA==\",\"name\":\"source-safety-37439906629-1\",\"size_in_bytes\":5348,\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11401796518\",\"archive_download_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11401796518/zip\",\"expired\":false,\"digest\":\"sha256:3d34dc75601c21f3bfae7a327afeeac448a885cdce08f1764e759154b05626ca\",\"created_at\":\"2026-10-06T09:16:52Z\",\"updated_at\":\"2026-10-06T09:16:52Z\",\"expires_at\":\"2026-10-20T09:16:51Z\",\"workflow_run\":{\"id\":37439906629,\"repository_id\":1334276889,\"head_repository_id\":1334276889,\"head_branch\":\"main\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\"}},{\"id\":11401741397,\"node_id\":\"MDg6QXJ0aWZhY3QxMTQwMTc0MTM5Nw==\",\"name\":\"typesafe-budget-receipt-37439906629-1\",\"size_in_bytes\":1357,\"url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11401741397\",\"archive_download_url\":\"https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/11401741397/zip\",\"expired\":false,\"digest\":\"sha256:83701d7c834f894e521f40631430b9d14da28aa4294daaaf2ebd2781bc743719\",\"created_at\":\"2026-10-06T09:16:51Z\",\"updated_at\":\"2026-10-06T09:16:51Z\",\"expires_at\":\"2026-10-27T09:16:50Z\",\"workflow_run\":{\"id\":37439906629,\"repository_id\":1334276889,\"head_repository_id\":1334276889,\"head_branch\":\"main\",\"head_sha\":\"6fd693fff935d47745f78a5633754fb321bf56f3\"}}]},\"log_url\":\"https://github.com/coar0000-wq/jarvis-luna/commit/6fd693fff935d47745f78a5633754fb321bf56f3/checks/112190829536/logs\",\"log_bytes\":291840,\"log_sha\":\"5054c0628c20d92669010b6a6ae9b77ce7632d4a896cb4a3c19397ec54fb51d1\"}}")
_ZERO_CODE = _json("{\"scripts/generate_dashboard_runtime.py\":\"54b993eeea189342db24e0271031f6896a4c1115a9783a9294fdcf3990677dc4\",\".github/workflows/daiso-real-collection.yml\":\"d9efcbc602a7b08b50445210d4960078f448221e13373398fb0117122bc9b981\",\"scripts/restore_operations_safety.py\":\"dea467c8b60ad1bd68b1a197a4eedac199352017c337e88f1d237194f9241fbc\",\"scripts/run_jarvis_operations.py\":\"d50c1b7c2842436a683d3d1af58a2a21aa9185dd0c909bbdc19f0c75d3c69ede\",\".github/workflows/JARVIS-Core-Automation.yml\":\"6cec8cd96a84641951ca7887657722aba907958aa1a6b043d2f5eedb1214fb48\",\".github/workflows/JARVIS-Deep-Analysis.yml\":\"23f317ad142ca59b84dbda9caa37f00cf9f55efe79fe8478520c11e05c4a2439\",\"scripts/run_jarvis_agents_safe_autofix.py\":\"f78e7c28975bd64d64351f568d7dcff2429b0d9c46a6ea67ff66ad68b775abc7\",\"scripts/run_jarvis_agents.py\":\"6f9b281ee02b86abc2fba5c2aed9ad8cac14b4fc7670480a90fffd709f0e712d\",\"scripts/build_team_improvement.py\":\"3e9752f444501f738ed7275e22c0518c3904a785e305fa01567b535bcea865bf\",\"scripts/publish_transaction.py\":\"f82c39028603fb62a75a7167366c444f0b7171208bbcd5750dd63cef964d8628\",\".github/actions/publish/action.yml\":\"21f3c399a2a9dda880d19222f3837358151e5121ea9e09e4ccc12a91fe4556e0\",\"scripts/run_source_procedures.py\":\"f84c380c0c249d61e2750803dec3ea7ac03edf2353d008789158c1301f615445\"}")
_ZERO_ORDER = (37439906629, 37401512848, 37398490984, 37396063331,
               37365343578, 37362386981, 37299237632, 37287805994)
_MAX_GAP_LOG = 1024 * 1024


def _fetch_job_log(job_id):
    if type(job_id) is not int or job_id <= 0:
        raise Blocked('zero_gap_job_identity_invalid')
    # Fixed Actions endpoint; never forward credentials to redirect storage.
    opener = urllib.request.build_opener(transport._NoRedirect())
    request = urllib.request.Request(BASE + f'jobs/{job_id}/logs', headers=transport._headers())
    try:
        try:
            with opener.open(request, timeout=30) as response:
                return transport._bounded(response, _MAX_GAP_LOG)
        except urllib.error.HTTPError as error:
            if error.code != 302:
                raise Blocked('zero_gap_log_unavailable') from None
            location = error.headers.get('Location')
            error.close()
            if not location:
                raise Blocked('zero_gap_log_redirect_missing')
        transport._storage_url(location)
        with opener.open(urllib.request.Request(location, headers={'User-Agent':'JARVIS-source-safety/1'}), timeout=30) as response:
            return transport._bounded(response, _MAX_GAP_LOG)
    except (OSError, ValueError):
        raise Blocked('zero_gap_log_unavailable') from None


def _zero_operations_predecessor(root, run, fetch_json, current_run_id, fetch_log):
    case = _ZERO_GAPS.get(str(run.get('id')))
    if case is None:
        raise Blocked('zero_gap_unknown_producer')
    history = fetch_json(BASE + 'runs?per_page=100')
    rows = history.get('workflow_runs') if isinstance(history, dict) else None
    if not isinstance(rows, list) or len(rows) > 100:
        raise Blocked('zero_gap_window_missing')
    window = [r for r in rows if isinstance(r, dict) and r.get('path') in WORKFLOWS
              and r.get('head_branch') == 'main' and str(r.get('id')) != str(current_run_id)]
    if any(type(r.get('id')) is not int for r in window) or len({r['id'] for r in window}) != len(window):
        raise Blocked('zero_gap_window_ambiguous')
    if any(r.get('status') != 'completed' for r in window):
        raise Blocked('producer_run_not_completed')
    window.sort(key=lambda r:r['id'], reverse=True)
    expected = _ZERO_ORDER[_ZERO_ORDER.index(run['id']):]
    relevant = [r for r in window if r['id'] >= _ABORT_PREDECESSOR['id']]
    if tuple(r['id'] for r in relevant) != expected:
        raise Blocked('zero_gap_unreviewed_intervening_producer')
    _incident_run(run, case['run'])
    for observed in relevant[:-2]:
        proof = _ZERO_GAPS[str(observed['id'])]
        _incident_run(observed, proof['run'])
        _incident_run(fetch_json(BASE + f"runs/{observed['id']}"), proof['run'])
        if _git(root, 'merge-base', '--is-ancestor', observed['head_sha'], 'HEAD').returncode:
            raise Blocked('run_not_main_ancestor')
        jobs = fetch_json(BASE + f"runs/{observed['id']}/attempts/1/jobs?per_page=100")
        if not isinstance(jobs, dict) or jobs.get('total_count') != 1 or not isinstance(jobs.get('jobs'), list) or len(jobs['jobs']) != 1:
            raise Blocked('zero_gap_jobs_incomplete')
        job = jobs['jobs'][0]
        if not isinstance(job, dict) or {k:job.get(k) for k in proof['job']} != proof['job']:
            raise Blocked('zero_gap_job_changed')
        steps = job.get('steps')
        if not isinstance(steps, list) or any(not isinstance(s, dict) for s in steps) or [[s.get(k) for k in ('number','name','status','conclusion','started_at','completed_at')] for s in steps] != proof['steps']:
            raise Blocked('zero_gap_topology_changed')
        if fetch_json(BASE + f"runs/{observed['id']}/artifacts?per_page=100") != proof['artifacts']:
            raise Blocked('zero_gap_artifacts_changed')
        for relative, digest in _ZERO_CODE.items():
            code = _git(root, 'show', observed['head_sha'] + ':' + relative)
            if code.returncode or _sha(code.stdout) != digest:
                raise Blocked('zero_gap_code_changed')
        raw = fetch_log(job['id'])
        if not isinstance(raw, bytes) or len(raw) > _MAX_GAP_LOG or len(raw) != proof['log_bytes'] or _sha(raw) != proof['log_sha']:
            raise Blocked('zero_gap_raw_log_changed')
    _incident_run(relevant[-2], _ABORT_RUN)
    _incident_run(relevant[-1], _ABORT_PREDECESSOR)
    # Full newer chain was proved above. Preserve the original incident proof
    # for its sole predecessor, using the authenticated window's exact tail.
    def tail_fetch(url):
        if url == BASE + 'runs?per_page=100':
            return {'workflow_runs':[r for r in window if r['id'] <= _ABORT_RUN['id']]}
        return fetch_json(url)
    inventory = fetch_json(BASE + f"runs/{_ABORT_RUN['id']}/artifacts?per_page=100")
    rows = inventory.get('artifacts') if isinstance(inventory, dict) else None
    if not isinstance(rows, list) or inventory.get('total_count') != 1 or len(rows) != 1 or not isinstance(rows[0], dict) or {k:rows[0].get(k) for k in _ABORT_SOURCE} != _ABORT_SOURCE:
        raise Blocked('pre_execution_abort_artifact_inventory_unproved')
    return _pre_execution_predecessor(root, relevant[-2], tail_fetch, current_run_id)


# Exact authenticated Deep member. No generic per-file capacity exception.
_REVIEWED_STATE_BYTES = 10011832
_REVIEWED_STATE_SHA = '09bb3bcf279aa6d568e8c9ce403086a4fb3f973e1731666ab3d7b956e8a3212e'
_REVIEWED_COMPACT_BYTES = 7875412
_REVIEWED_COMPACT_SHA = 'b01f6002dcceadd6820a64a99e961e164b8c8f1251d301a6980dbe6628eaedb2'
_REVIEWED_ARCHIVE_MEMBERS = 714


def _whitespace_compact(source, *, expected_bytes, expected_sha):
    """Remove only JSON whitespace outside strings, from bounded ZIP reads."""
    digest, count, inside, escaped = hashlib.sha256(), 0, False, False
    result = bytearray()
    # Original bytes are retained temporarily for independent strict parsing;
    # ZIP/transducer IO is always <=64KiB. No history content is regenerated.
    with tempfile.TemporaryFile() as original:
        while True:
            chunk = source.read(64 * 1024)
            if not chunk:
                break
            if not isinstance(chunk, bytes) or len(chunk) > 64 * 1024:
                raise Blocked('reviewed_state_stream_invalid')
            count += len(chunk)
            if count > expected_bytes:
                raise Blocked('reviewed_state_stream_oversize')
            digest.update(chunk)
            original.write(chunk)
            for value in chunk:
                if inside:
                    result.append(value)
                    if escaped:
                        escaped = False
                    elif value == 92:
                        escaped = True
                    elif value == 34:
                        inside = False
                elif value == 34:
                    inside = True
                    result.append(value)
                elif value not in (9, 10, 13, 32):
                    result.append(value)
                if len(result) > MAX_FILE_BYTES:
                    raise Blocked('reviewed_compact_state_oversize')
        if count != expected_bytes or digest.hexdigest() != expected_sha:
            raise Blocked('reviewed_state_original_binding_invalid')
        if inside or escaped:
            raise Blocked('reviewed_state_string_unterminated')
        compact = bytes(result)
        original.seek(0)
        # Both parsers reject duplicates, NaN and malformed JSON. Equality is
        # additional evidence, not a substitute for exact original byte pins.
        original_raw = b''.join(iter(lambda: original.read(64 * 1024), b''))
        if _json(original_raw) != _json(compact):
            raise Blocked('reviewed_state_compaction_changed_object')
    return compact


def _compact_reviewed_archive(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_ARCHIVE_BYTES or _sha(raw) != _ABORT_ARTIFACT_DIGEST[7:]:
        raise Blocked('reviewed_archive_binding_invalid')
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) != _REVIEWED_ARCHIVE_MEMBERS or len(entries) > MAX_FILES + 4:
            raise Blocked('archive_count_limit')
        total = sum(entry.file_size for entry in entries)
        if total > MAX_TOTAL_BYTES:
            raise Blocked('archive_size_limit')
        oversized = [entry for entry in entries if entry.file_size > MAX_FILE_BYTES]
        if len(oversized) != 1 or oversized[0].filename != 'state.json' or oversized[0].file_size != _REVIEWED_STATE_BYTES:
            raise Blocked('reviewed_archive_member_unproved')
        with zipfile.ZipFile(output, 'w') as normalized:
            for entry in entries:
                mode = entry.external_attr >> 16
                # Preserve ALL original ZIP safety predicates except the exact
                # pinned state's raw byte size; its output must fit existing cap.
                if (entry.flag_bits & 1 or entry.external_attr & 0x400
                        or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)
                        or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                        or (entry.file_size > 1024 * 1024 and entry.file_size > max(1, entry.compress_size) * 200)):
                    raise Blocked('archive_entry_unsafe')
                with archive.open(entry) as source:
                    if entry is oversized[0]:
                        body = _whitespace_compact(source, expected_bytes=_REVIEWED_STATE_BYTES,
                                                   expected_sha=_REVIEWED_STATE_SHA)
                        if len(body) != _REVIEWED_COMPACT_BYTES or _sha(body) != _REVIEWED_COMPACT_SHA:
                            raise Blocked('reviewed_compact_state_binding_invalid')
                    else:
                        # Member bytes and metadata are unchanged. The ordinary
                        # validator below still checks paths/layout/duplicates.
                        chunks, length = [], 0
                        while True:
                            chunk = source.read(64 * 1024)
                            if not chunk:
                                break
                            length += len(chunk)
                            if length > MAX_FILE_BYTES:
                                raise Blocked('archive_entry_unsafe')
                            chunks.append(chunk)
                        body = b''.join(chunks)
                normalized.writestr(copy.copy(entry), body)
    normalized = output.getvalue()
    files = _archive(normalized)  # unchanged generic capacity/integrity validator
    return files, {'archive_sha256':_sha(raw), 'member':'state.json',
                   'raw_bytes':_REVIEWED_STATE_BYTES, 'raw_sha256':_REVIEWED_STATE_SHA,
                   'compact_bytes':_REVIEWED_COMPACT_BYTES, 'compact_sha256':_REVIEWED_COMPACT_SHA,
                   'parsed_object_equal':True, 'whitespace_only':True}


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
                   fetch_bytes=transport.fetch_artifact_bytes, current_run_id=None, fetch_log=_fetch_job_log):
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
    if not artifacts:
        if str(run['id']) in _ZERO_GAPS:
            run = _zero_operations_predecessor(root, run, fetch_json, current_run_id, fetch_log)
        else:
            if len(rows) != 1 or not isinstance(rows[0], dict) or {k:rows[0].get(k) for k in _ABORT_SOURCE} != _ABORT_SOURCE:
                raise Blocked('pre_execution_abort_artifact_inventory_unproved')
            run = _pre_execution_predecessor(root, run, fetch_json, current_run_id)
        response = fetch_json(BASE + f"runs/{run['id']}/artifacts?per_page=100")
        rows = response.get('artifacts') if isinstance(response, dict) else None
        if not isinstance(rows, list) or type(response.get('total_count')) is not int or response['total_count'] != len(rows):
            raise Blocked('artifact_listing_incomplete')
        name = f"operations-safety-{run['id']}-{run['run_attempt']}"
        artifacts = [a for a in rows if isinstance(a, dict) and a.get('name') == name]
        if len(artifacts) != 1 or artifacts[0].get('digest') != _ABORT_ARTIFACT_DIGEST:
            raise Blocked('pre_execution_abort_predecessor_artifact_unproved')
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
    normalization = None
    if digest == _ABORT_ARTIFACT_DIGEST:
        incoming, normalization = _compact_reviewed_archive(raw)
    else:
        incoming = _archive(raw)
    with _locks(root):
        _pending(root)
        current = _snapshot(root)
        try:
            _nonregression(current, incoming)
        except ValueError:
            _exact_head(root, current)
            _nonregression(incoming, current)
            return {'continuity':'verified', 'status':'artifact_history_already_preserved_in_head', 'run_id':run['id'], 'normalization':normalization}
        _restore(root, current, incoming, run)
    verify_current(root)
    return {'continuity':'verified', 'status':'authenticated_operations_safety_restored', 'run_id':run['id'], 'normalization':normalization}


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
