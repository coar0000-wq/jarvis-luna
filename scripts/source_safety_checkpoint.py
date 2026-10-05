#!/usr/bin/env python3
"""Offline, bounded source-safety ZIP pack/restore. No network or regeneration.

Caller MUST authenticate the GitHub artifact and vouch for all four lineage
arguments; SHA256 detects corruption, not authenticity. Observer v2 is required
(no legacy migration). Procedure state/checkpoint are an optional inseparable
pair. Restore accepts an empty checkout or a provable non-regressing descendant;
partial loss, conflicting history and a current-ahead checkout are refused.

Writes are staged/fsynced before a durable fail-closed transaction marker. The
observer ledger is replaced BEFORE its observations, procedure state BEFORE its
checkpoint. An interrupted transaction leaves the marker and blocks all future
pack/restore calls; do not delete it or rerun collectors to repair continuity.
A caller must keep source execution quiescent after such a failure. There is no
receipt/ExecutionStore access, dispatch, source capture or genesis creation here.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from daiso import observe_shortlist as observer
from source_procedure_state import SourceProcedureStore, canonical

OBSERVATIONS = observer.OUTPUT
CLAIM = observer.LEDGER
PROCEDURE = 'data/agents/source_procedures/source-procedure-state.json'
CHECKPOINT = 'data/agents/source_procedures/checkpoint.json'
ALLOWLIST = (OBSERVATIONS, CLAIM, PROCEDURE, CHECKPOINT)
MANIFEST = 'source-safety-manifest.json'
PENDING = '.source-safety-restore.pending'
MAX_FILES = 5
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_ARCHIVE_BYTES = MAX_TOTAL_BYTES + 1024 * 1024


class Blocked(ValueError):
    pass


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(data):
    try:
        return json.loads(data, object_pairs_hook=observer._unique_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(Blocked('nonfinite_json')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Blocked('invalid_json') from exc


def _path(value):
    p = Path(value)
    if '..' in p.parts:
        raise Blocked('path_traversal')
    p = p.absolute()
    for q in (*reversed(p.parents), p):
        try:
            s = q.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(s.st_mode) or getattr(s, 'st_file_attributes', 0) & 0x400:
            raise Blocked('symlink_or_reparse_path')
        if q != p and not stat.S_ISDIR(s.st_mode):
            raise Blocked('non_directory_ancestor')
    return p


def _target(root, relative):
    if relative not in (*ALLOWLIST, PENDING):
        raise Blocked('not_allowlisted')
    return _path(root / relative)


def _read_file(p, limit=MAX_FILE_BYTES):
    p = _path(p)
    s = p.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_size > limit:
        raise Blocked('not_regular_or_oversize')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    fd = os.open(p, flags)
    try:
        actual = os.fstat(fd)
        if (actual.st_dev, actual.st_ino) != (s.st_dev, s.st_ino):
            raise Blocked('file_changed')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            result = stream.read(limit + 1)
        if len(result) > limit:
            raise Blocked('oversize')
        _path(p)
        return result
    finally:
        os.close(fd)


def _lineage(repository, run_id, run_attempt, commit):
    if not isinstance(repository, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise Blocked('invalid_repository')
    if any(not isinstance(v, (str, int)) or isinstance(v, bool) or not re.fullmatch(r'[1-9][0-9]{0,19}', str(v)) for v in (run_id, run_attempt)):
        raise Blocked('invalid_run_lineage')
    if not isinstance(commit, str) or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', commit):
        raise Blocked('invalid_commit')
    return dict(repository=repository, run_id=str(run_id), run_attempt=str(run_attempt), commit=commit)


def _pending(root):
    if _target(root, PENDING).exists():
        raise Blocked('interrupted_restore_manual_reconciliation_required')


def _snapshot(root):
    result = {}
    for rel in ALLOWLIST:
        p = _target(root, rel)
        if p.exists():
            result[rel] = _read_file(p, MAX_FILE_BYTES)
    if sum(map(len, result.values())) > MAX_TOTAL_BYTES:
        raise Blocked('total_size_limit')
    return result


def _validate(files):
    if set(files) - set(ALLOWLIST) or not {OBSERVATIONS, CLAIM} <= set(files):
        raise Blocked('observer_pair_missing')
    if (PROCEDURE in files) != (CHECKPOINT in files):
        raise Blocked('procedure_pair_missing')
    doc, ledger = _json(files[OBSERVATIONS]), _json(files[CLAIM])
    if not isinstance(doc, dict) or not isinstance(ledger, dict) or type(doc.get('schema_version')) is not int or doc.get('schema_version') != 2 or doc.get('policy') != observer.POLICY or ledger.get('policy') != observer.POLICY:
        raise Blocked('observer_v2_required_no_migration')
    count = ledger.get('total_http_attempts')
    if type(count) is not int or count < 0:
        raise Blocked('invalid_lifetime_counter')
    now = observer.time.time()
    for key in ('last_run_attempt_at', 'last_request_at', 'last_checked_at'):
        value = observer._epoch(ledger.get(key))
        if value is None or value > now:
            raise Blocked('invalid_source_clock')
    if observer._epoch(ledger['last_request_at']) < observer._epoch(ledger['last_run_attempt_at']):
        raise Blocked('source_clock_order')
    checkpoint = doc.get('budget_checkpoint')
    if not isinstance(checkpoint, dict) or checkpoint.get('policy_version') != 2 or not re.fullmatch(r'[0-9a-f]{64}', str(checkpoint.get('request_history_sha256', ''))):
        raise Blocked('missing_v2_history_proof')
    if type(checkpoint.get('total_http_attempts')) is not int or type(doc.get('http_attempt_count')) is not int or not 0 <= doc['http_attempt_count'] <= observer.POLICY['per_run_http_cap'] or doc['http_attempt_count'] > count:
        raise Blocked('invalid_attempt_counter')
    # Existing helper validates full sequence, clocks, prefix proof and budgets.
    # A copied no-op claim forbids its legacy migration/save side effects.
    checked = copy.deepcopy(ledger)
    observer._continuity(doc, SimpleNamespace(data=checked, save=lambda: None))
    if checked != ledger:
        raise Blocked('migration_forbidden')
    clocks = {'observer_last_request_at': ledger['last_request_at'],
              'observer_last_checked_at': ledger['last_checked_at'], 'capture_clocks': []}
    for key in ('products', 'retained_previous_products', 'capture_history'):
        rows = doc.get(key, [])
        if not isinstance(rows, list):
            raise Blocked('invalid_capture_history')
        identities = []
        for row in rows:
            if not isinstance(row, dict) or not re.fullmatch(r'[0-9]+', str(row.get('pd_no', ''))) or not re.fullmatch(r'CP[0-9]{6}', str(row.get('canonical_product_id', ''))):
                raise Blocked('invalid_capture_identity')
            pair = (row['pd_no'], row['canonical_product_id'])
            if not observer._valid_prior(row, [pair]) or observer._epoch(row['source']['collected_at']) > now:
                raise Blocked('invalid_actual_capture')
            identities.append(pair)
            clocks['capture_clocks'].append(row['source']['collected_at'])
        if key == 'products' and (len(set(identities)) != len(identities) or len({x[0] for x in identities}) != len(identities) or len({x[1] for x in identities}) != len(identities)):
            raise Blocked('duplicate_current_capture')
    if not isinstance(doc.get('observation_history', []), list) or not isinstance(doc.get('attempts', []), list):
        raise Blocked('invalid_observation_history')
    for event in doc.get('observation_history', []):
        if not isinstance(event, dict) or not isinstance(event.get('attempts'), list):
            raise Blocked('invalid_observation_history')
        cp = event.get('budget_checkpoint')
        if not isinstance(cp, dict) or not isinstance(cp.get('request_history_sha256'), str):
            # An evidenced legacy checkpoint remains verbatim. Its separate v2
            # migration proof binds the real reservation prefix and actual
            # migration CHECK time, never inventing a product capture clock.
            proof = event.get('legacy_budget_proof')
            original_digest = _sha(json.dumps(cp,sort_keys=True,separators=(',',':')).encode())
            if not isinstance(proof,dict) or set(proof) != {'legacy_checkpoint_sha256','checkpoint'} or proof['legacy_checkpoint_sha256'] != original_digest:
                raise Blocked('missing_historical_proof')
            modern = proof['checkpoint']
            migration = ledger.get('migration') or {}
            n = (cp or {}).get('total_http_attempts')
            if not isinstance(modern,dict) or type(n) is not int or n != migration.get('legacy_total_http_attempts') or modern.get('total_http_attempts') != n or modern.get('policy_version') != 2 or any(modern.get(k) != cp.get(k) for k in cp) or not all(r.get('kind') == 'legacy_reserved' for r in ledger['request_history'][:n]):
                raise Blocked('unproved_legacy_history')
            if observer._epoch(modern.get('last_checked_at')) > observer._epoch(ledger['last_checked_at']):
                raise Blocked('legacy_check_clock_conflict')
            cp = modern
        observer._check_budget_checkpoint({'budget_checkpoint': cp}, ledger)
        n = cp['total_http_attempts']
        if cp['request_history_sha256'] != observer._history_digest(ledger['request_history'][:n]):
            raise Blocked('historical_proof_conflict')
    if PROCEDURE in files:
        state, expected = _json(files[PROCEDURE]), _json(files[CHECKPOINT])
        store = SourceProcedureStore('.')
        store._validate(state)  # load() would mutate CLAIMED; never call it here.
        if not isinstance(expected, dict) or set(expected) != {'revision', 'table_hash', 'lifetime'} or type(expected['revision']) is not int or not isinstance(expected['lifetime'], dict) or any(type(v) is not int for v in expected['lifetime'].values()) or store._checkpoint(state) != expected:
            raise Blocked('procedure_checkpoint_mismatch')
        clocks['procedure_claim_clocks'] = [a['claimed_at'] for t in state['teams'].values() for e in t['episodes'] for a in e['attempts']]
        ended = [a['ended_at'] for t in state['teams'].values() for e in t['episodes'] for a in e['attempts'] if a['ended_at'] is not None]
        if any(observer._epoch(t) is None or observer._epoch(t) > now for t in clocks['procedure_claim_clocks'] + ended):
            raise Blocked('future_procedure_clock')
    clocks['capture_clocks'] = sorted(set(clocks['capture_clocks']))
    return clocks


def _prefix(old, new, reason):
    if len(old) > len(new) or new[:len(old)] != old:
        raise Blocked(reason)


def _nonregression(current, incoming):
    if not current:
        return
    _validate(current)
    if PROCEDURE in current and PROCEDURE not in incoming:
        raise Blocked('procedure_history_loss')
    if PROCEDURE not in current and PROCEDURE in incoming:
        raise Blocked('ambiguous_procedure_pair_loss')
    old, new = _json(current[CLAIM]), _json(incoming[CLAIM])
    if old['total_http_attempts'] > new['total_http_attempts']:
        raise Blocked('current_ahead_main')
    _prefix(old['request_history'], new['request_history'], 'request_history_conflict')
    for key in ('last_run_attempt_at', 'last_request_at', 'last_checked_at'):
        if observer._epoch(old[key]) > observer._epoch(new[key]):
            raise Blocked('current_ahead_source_clock')
    if old.get('automatic_retry_block') and new.get('automatic_retry_block') != old['automatic_retry_block']:
        raise Blocked('safety_stop_loss')
    for pd, attempt in old.get('member_attempts', {}).items():
        target = new.get('member_attempts', {}).get(pd)
        if not target or observer._epoch(target['attempted_at']) < observer._epoch(attempt['attempted_at']):
            raise Blocked('member_attempt_history_loss')
    olddoc, newdoc = _json(current[OBSERVATIONS]), _json(incoming[OBSERVATIONS])
    if olddoc['budget_checkpoint']['total_http_attempts'] > newdoc['budget_checkpoint']['total_http_attempts'] or observer._epoch(olddoc['budget_checkpoint']['last_checked_at']) > observer._epoch(newdoc['budget_checkpoint']['last_checked_at']):
        raise Blocked('observation_checkpoint_regression')
    captures = {canonical(r) for k in ('products', 'retained_previous_products', 'capture_history') for r in newdoc.get(k, [])}
    for k in ('products', 'retained_previous_products', 'capture_history'):
        if any(canonical(r) not in captures for r in olddoc.get(k, [])):
            raise Blocked('capture_history_loss')
    _prefix(olddoc.get('observation_history', []), newdoc.get('observation_history', []), 'observation_history_loss')
    if olddoc.get('attempts'):
        event = {k: olddoc.get(k) for k in ('attempts', 'budget_checkpoint', 'status')}
        latest = {k: newdoc.get(k) for k in ('attempts', 'budget_checkpoint', 'status')}
        if event != latest and event not in newdoc.get('observation_history', []):
            raise Blocked('current_observation_history_loss')
    if PROCEDURE in current:
        oldstate, newstate = _json(current[PROCEDURE]), _json(incoming[PROCEDURE])
        if oldstate['revision'] > newstate['revision']:
            raise Blocked('current_ahead_procedure')
        if oldstate['revision'] == newstate['revision'] and oldstate != newstate:
            raise Blocked('procedure_revision_conflict')
        for team, oldrow in oldstate['teams'].items():
            newrow = newstate['teams'][team]
            if oldrow['lifetime'] > newrow['lifetime'] or newrow['budget'] > oldrow['budget'] or (oldrow['stopped'] and not newrow['stopped']):
                raise Blocked('procedure_counter_or_stop_regression')
            if len(oldrow['episodes']) > len(newrow['episodes']):
                raise Blocked('procedure_episode_loss')
            for index, episode in enumerate(oldrow['episodes']):
                other = newrow['episodes'][index]
                if episode['failure_fingerprint'] != other['failure_fingerprint'] or len(episode['attempts']) > len(other['attempts']):
                    raise Blocked('procedure_history_conflict')
                for i, attempt in enumerate(episode['attempts']):
                    after = other['attempts'][i]
                    if attempt == after:
                        continue
                    if attempt['status'] not in ('CLAIMED', 'reconciliation_required') or any(attempt[k] != after[k] for k in attempt if k not in ('status', 'ended_at', 'outcome')) or (attempt['status'] == 'reconciliation_required' and after['status'] == 'CLAIMED'):
                        raise Blocked('procedure_attempt_history_conflict')


@contextmanager
def _locks(root):
    """Use the observer's exact OS lock and the store's non-expiring lock."""
    directory = _path(root / 'data/daiso_real')
    directory.mkdir(parents=True, exist_ok=True)
    handle = None
    acquired = False
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            kernel.CreateMutexW.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.CreateMutexW(None, False, 'Local\\JarvisShortlist_' + _sha(str(root).casefold().encode()))
            if not handle or kernel.WaitForSingleObject(handle, 0) not in (0, 0x80):
                raise Blocked('observer_locked')
        else:
            import fcntl
            handle = os.open(directory, os.O_RDONLY)
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        procdir = _path(root / Path(PROCEDURE).parent)
        with SourceProcedureStore(procdir)._lock() as owned:
            yield owned
    finally:
        if handle is not None:
            if os.name == 'nt':
                if acquired:
                    kernel.ReleaseMutex(handle)
                kernel.CloseHandle(handle)
            else:
                os.close(handle)


def _sync_dir(directory):
    if os.name != 'nt':
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _stage(target, data):
    _path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = _path(target.parent / ('.source-safety-' + os.urandom(16).hex()))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return temp


def pack(root, output, *, repository, run_id, run_attempt, commit):
    lineage = _lineage(repository, run_id, run_attempt, commit)
    root, output = _path(root), _path(output)
    if not root.is_dir() or output in [_target(root, x) for x in (*ALLOWLIST, PENDING)]:
        raise Blocked('unsafe_output')
    _pending(root)
    with _locks(root) as owned:
        _pending(root)
        files = _snapshot(root)
        clocks = _validate(files)
        manifest = {'schema_version': 1, 'lineage': lineage, 'source_clocks': clocks,
                    'files': {k: {'sha256': _sha(v), 'size': len(v)} for k, v in files.items()}}
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = _stage(output, b'')
        try:
            with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(MANIFEST, canonical(manifest).encode())
                for rel, data in files.items():
                    archive.writestr(rel, data)
            if temp.stat().st_size > MAX_ARCHIVE_BYTES:
                raise Blocked('archive_size_limit')
            with open(temp, 'r+b') as stream:
                stream.flush()
                os.fsync(stream.fileno())
            owned()
            if _snapshot(root) != files:
                raise Blocked('source_changed')
            _path(output)
            os.replace(temp, output)
            _sync_dir(output.parent)
        finally:
            temp.unlink(missing_ok=True)
    return {'status': 'packed', 'files': sorted(files), 'lineage': lineage}


def _archive(archive_path, expected):
    raw = _read_file(archive_path, MAX_ARCHIVE_BYTES)
    import io
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        names = [x.filename for x in members]
        if len(members) > MAX_FILES or len(set(names)) != len(names) or MANIFEST not in names or set(names) - {*ALLOWLIST, MANIFEST}:
            raise Blocked('archive_file_allowlist')
        files = {}
        total = 0
        for entry in members:
            mode = entry.external_attr >> 16
            limit = MAX_MANIFEST_BYTES if entry.filename == MANIFEST else MAX_FILE_BYTES
            if entry.is_dir() or entry.external_attr & 0x400 or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)) or entry.flag_bits & 1 or entry.file_size > limit or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise Blocked('unsafe_archive_entry')
            total += entry.file_size
            if total > MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES:
                raise Blocked('archive_total_size_limit')
            with archive.open(entry) as stream:
                body = stream.read(limit + 1)
            if len(body) != entry.file_size or len(body) > limit:
                raise Blocked('archive_size_mismatch')
            files[entry.filename] = body
    manifest = _json(files.pop(MANIFEST))
    if not isinstance(manifest, dict) or set(manifest) != {'schema_version', 'lineage', 'files', 'source_clocks'} or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1 or manifest['lineage'] != expected:
        raise Blocked('archive_lineage_mismatch')
    if manifest['files'] != {k: {'sha256': _sha(v), 'size': len(v)} for k, v in files.items()}:
        raise Blocked('archive_hash_or_manifest_mismatch')
    if manifest['source_clocks'] != _validate(files):
        raise Blocked('source_clock_manifest_mismatch')
    return files


def restore(root, archive, *, expected_repository, expected_run_id, expected_run_attempt, expected_commit):
    expected = _lineage(expected_repository, expected_run_id, expected_run_attempt, expected_commit)
    root = _path(root)
    _pending(root)
    incoming = _archive(_path(archive), expected)
    root.mkdir(parents=True, exist_ok=True)
    with _locks(root) as owned:
        _pending(root)
        current = _snapshot(root)
        _nonregression(current, incoming)
        if current == incoming:
            return {'status': 'unchanged', 'files': sorted(incoming), 'lineage': expected}
        staged = {}
        try:
            for rel, data in incoming.items():
                staged[rel] = _stage(_target(root, rel), data)
            owned()
            if _snapshot(root) != current:
                raise Blocked('current_changed')
            marker = _target(root, PENDING)
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(canonical({'lineage': expected, 'before': {k: _sha(v) for k, v in current.items()}, 'after': {k: _sha(v) for k, v in incoming.items()}, 'status': 'manual_reconciliation_required_if_present'}).encode())
                stream.flush()
                os.fsync(stream.fileno())
            _sync_dir(root)
            for rel in (CLAIM, OBSERVATIONS, PROCEDURE, CHECKPOINT):
                if rel in staged:
                    owned()
                    target = _target(root, rel)
                    os.replace(staged[rel], target)
                    _sync_dir(target.parent)
            if _snapshot(root) != incoming:
                raise Blocked('restore_verification_failed')
            _validate(incoming)
            owned()
            _target(root, PENDING).unlink()
            _sync_dir(root)
        finally:
            for temp in staged.values():
                _path(temp).unlink(missing_ok=True)
            # Intentionally retain the marker after ANY interrupted mutation.
    return {'status': 'restored', 'files': sorted(incoming), 'lineage': expected}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('pack')
    p.add_argument('--root', required=True)
    p.add_argument('--output', required=True)
    for name in ('repository', 'run-id', 'run-attempt', 'commit'):
        p.add_argument('--' + name, required=True)
    r = commands.add_parser('restore')
    r.add_argument('--root', required=True)
    r.add_argument('--archive', required=True)
    for name in ('repository', 'run-id', 'run-attempt', 'commit'):
        r.add_argument('--expected-' + name, required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop('command')
    try:
        result = pack(**args) if command == 'pack' else restore(**args)
    except (ValueError, OSError, KeyError, TypeError, AttributeError, OverflowError, RecursionError, zipfile.BadZipFile, RuntimeError):
        # No attacker-controlled paths, content, tokens or exception text emitted.
        print(json.dumps({'status': 'blocked', 'reason': 'source_safety_validation_or_transaction_failed'}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
