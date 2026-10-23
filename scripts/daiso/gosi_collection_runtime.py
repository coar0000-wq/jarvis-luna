"""Bounded, single-run GOSI worker transport and Linux process containment.

The worker writes only immutable journal events. The caller's supervisor callback
validates semantic changes and is the sole canonical publisher. Journals are NOT
a cross-run recovery protocol. No network operations are performed here.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
import time
import uuid

MAX_EVENT_BYTES = 4 * 1024 * 1024
# Canonical snapshots have a separate 8 MiB publication/checkpoint contract.
MAX_BASELINE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_EVENTS = 128
POLL_SECONDS = 0.025
KINDS = frozenset({'start_product', 'product_result', 'stop', 'complete'})
EVENT_FILE = re.compile(r'([0-9]{6})\.json\Z')


class JournalError(RuntimeError):
    pass


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(',', ':'), allow_nan=False) + '\n').encode()


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _regular_bytes(path, limit=MAX_EVENT_BYTES):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise JournalError('journal_file_type_or_size')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise JournalError('journal_file_size')
        return raw
    finally:
        os.close(fd)


def _immutable(path, raw, *, limit=None):
    """Publish a fully fsynced inode without replacing an existing event."""
    if limit is None:
        limit = MAX_EVENT_BYTES
    if len(raw) > limit:
        raise JournalError('journal_event_too_large')
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fchmod(stream.fileno(), 0o400)
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
        _sync_directory(path.parent)
    finally:
        os.unlink(temporary)
        _sync_directory(path.parent)


def _load_json(path, limit=MAX_EVENT_BYTES):
    try:
        return _parse_json(_regular_bytes(path, limit))
    except (ValueError, UnicodeError) as exc:
        raise JournalError('journal_invalid_json') from exc


def _parse_json(raw):
    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('nonfinite_json_number')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _binding(header):
    return {key: header[key] for key in ('schema_version', 'run_id', 'nonce', 'baseline_sha256')}


def _directory(path):
    path = Path(path).absolute()
    # Do not follow a substituted journal directory or any symlink ancestor.
    for entry in (path, *path.parents):
        if entry.is_symlink():
            raise JournalError('journal_symlink_directory')
    if not path.is_dir():
        raise JournalError('journal_directory_missing')
    return path


def _header(directory):
    header = _load_json(directory / 'header.json', 4096)
    if (not isinstance(header, dict) or header.get('schema_version') != 1 or
            not isinstance(header.get('run_id'), str) or not 1 <= len(header['run_id']) <= 256 or
            not re.fullmatch(r'[0-9a-f]{32}', str(header.get('nonce', ''))) or
            not re.fullmatch(r'[0-9a-f]{64}', str(header.get('baseline_sha256', ''))) or
            not isinstance(header.get('deadline'), (float, int)) or
            isinstance(header['deadline'], bool) or not math.isfinite(header['deadline'])):
        raise JournalError('journal_invalid_header')
    if _sha(_regular_bytes(directory / 'baseline.json', MAX_BASELINE_BYTES)) != header['baseline_sha256']:
        raise JournalError('journal_baseline_mismatch')
    return header


class JournalWriter:
    """Worker-side journal writer; no canonical paths or publisher are available."""

    def __init__(self, directory):
        self.directory = _directory(directory)
        self.header = _header(self.directory)
        self.deadline = float(self.header['deadline'])
        self.baseline_path = self.directory / 'baseline.json'
        self.sequence = 0
        self.total_bytes = 0
        self.completed = False
        if any(EVENT_FILE.fullmatch(p.name) for p in self.directory.iterdir()):
            raise JournalError('journal_worker_reuse_forbidden')

    @classmethod
    def from_env(cls):
        writer = cls(os.environ['GOSI_WORKER_JOURNAL'])
        if (Path(os.environ['GOSI_WORKER_BASELINE']).absolute() != writer.baseline_path or
                float(os.environ['GOSI_WORKER_DEADLINE_MONOTONIC']) != writer.deadline or
                os.environ.get('GOSI_WORKER_NONCE') != writer.header['nonce'] or
                os.environ.get('GOSI_WORKER_RUN_ID') != writer.header['run_id'] or
                os.environ.get('GOSI_WORKER_BASELINE_SHA256') != writer.header['baseline_sha256']):
            raise JournalError('journal_environment_binding_mismatch')
        return writer

    def emit(self, kind, payload, wait_for_ack=False):
        if kind not in KINDS or not isinstance(payload, dict) or self.completed:
            raise JournalError('journal_invalid_event_kind_or_order')
        if self.sequence >= MAX_EVENTS:
            raise JournalError('journal_event_count_bound')
        sequence = self.sequence + 1
        event = dict(_binding(self.header), sequence=sequence, kind=kind, payload=payload)
        raw = _json_bytes(event)
        if self.total_bytes + len(raw) > MAX_TOTAL_BYTES:
            raise JournalError('journal_total_size_bound')
        _immutable(self.directory / f'{sequence:06d}.json', raw)
        self.sequence = sequence
        self.total_bytes += len(raw)
        self.completed = kind == 'complete'
        if wait_for_ack:
            ack_path = self.directory / f'{sequence:06d}.ack'
            while True:
                try:
                    ack = _load_json(ack_path, 4096)
                except FileNotFoundError:
                    if time.monotonic() >= self.deadline:
                        raise JournalError('journal_ack_deadline')
                    time.sleep(min(POLL_SECONDS, max(0, self.deadline - time.monotonic())))
                    continue
                expected = dict(_binding(self.header), sequence=sequence,
                                event_sha256=_sha(raw), accepted=True)
                admitted = ack.get('admitted') if isinstance(ack, dict) else None
                if admitted is not None:
                    if kind != 'start_product' or type(admitted) is not bool:
                        raise JournalError('journal_invalid_admission_ack')
                    expected['admitted'] = admitted
                if ack != expected:
                    raise JournalError('journal_invalid_ack')
                if admitted is not None:
                    event = dict(event, admitted=admitted)
                break
        return event


class _Reader:
    def __init__(self, directory, header):
        self.directory, self.header = directory, header
        self.sequence = 0
        self.total_bytes = 0
        self.digests = {}
        self.complete = None
        self.stop_seen = False
        self.last_state = {}

    def drain(self, on_event):
        entries = list(self.directory.iterdir())
        if len(entries) > MAX_EVENTS * 2 + 8:
            raise JournalError('journal_directory_entry_bound')
        numbers = sorted(int(match[1]) for path in entries
                         if (match := EVENT_FILE.fullmatch(path.name)))
        if numbers and (numbers[-1] > MAX_EVENTS or numbers != list(range(1, numbers[-1] + 1))):
            raise JournalError('journal_sequence_gap_or_bound')
        for sequence in numbers:
            if sequence <= self.sequence:
                continue
            if self.complete is not None:
                raise JournalError('journal_event_after_complete')
            raw = _regular_bytes(self.directory / f'{sequence:06d}.json')
            self.total_bytes += len(raw)
            if self.total_bytes > MAX_TOTAL_BYTES:
                raise JournalError('journal_total_size_bound')
            try:
                event = _parse_json(raw)
            except (ValueError, UnicodeError) as exc:
                raise JournalError('journal_invalid_event_json') from exc
            if (not isinstance(event, dict) or set(event) != set(_binding(self.header)) | {'sequence', 'kind', 'payload'} or
                    any(event.get(k) != v for k, v in _binding(self.header).items()) or
                    type(event.get('sequence')) is not int or event['sequence'] != sequence or
                    event.get('kind') not in KINDS or not isinstance(event.get('payload'), dict)):
                raise JournalError('journal_event_identity_or_schema')
            if event['kind'] == 'complete':
                code = event['payload'].get('exit_code')
                if type(code) is not int or not 0 <= code <= 255:
                    raise JournalError('journal_invalid_complete')
            # A failed semantic validation/publication never gets an ACK.
            admitted = on_event(event)
            if admitted is not None and (event['kind'] != 'start_product' or type(admitted) is not bool):
                raise JournalError('journal_invalid_admission_result')
            if event['kind'] == 'stop':
                self.stop_seen = True
            if event['kind'] == 'complete':
                self.complete = event
            if isinstance(event['payload'].get('state'), dict):
                self.last_state = event['payload']['state']
            digest = _sha(raw)
            ack = dict(_binding(self.header), sequence=sequence, event_sha256=digest, accepted=True)
            if admitted is not None:
                ack['admitted'] = admitted
            _immutable(self.directory / f'{sequence:06d}.ack', _json_bytes(ack))
            self.digests[sequence] = digest
            self.sequence = sequence

    def verify_retained(self):
        if _header(self.directory) != self.header:
            raise JournalError('journal_header_changed')
        for sequence, digest in self.digests.items():
            if _sha(_regular_bytes(self.directory / f'{sequence:06d}.json')) != digest:
                raise JournalError('journal_accepted_event_changed')
        if any(p.name.startswith('.pending-') for p in self.directory.iterdir()):
            raise JournalError('journal_partial_event_retained')


def _proc_snapshot():
    """Read identity and ancestry without confusing reused Linux PIDs."""
    rows = {}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            raw = (path / 'stat').read_text()
            tail = raw[raw.rfind(')') + 2:].split()
            rows[int(path.name)] = (int(tail[1]), int(tail[19]), tail[0])
        except (OSError, ValueError, IndexError):
            continue
    return rows


class _ProcessTree:
    """A child-free, dedicated supervisor adopts orphaned worker descendants.

    /proc cannot prove the ancestry of an already reparented unrelated orphan.
    Refuse pre-existing child tasks rather than guessing and risking signaling
    their descendants after their original parent exits.
    """

    def __init__(self):
        if os.name != 'posix' or not Path('/proc/self/stat').is_file():
            raise JournalError('linux_subreaper_required')
        self.owner = os.getpid()
        if any(info[0] == self.owner for info in _proc_snapshot().values()):
            raise JournalError('dedicated_supervisor_requires_no_existing_children')
        self.libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        if self.libc.prctl(37, ctypes.byref(previous), 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), 'PR_GET_CHILD_SUBREAPER')
        self.previous = previous.value
        if self.libc.prctl(36, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), 'PR_SET_CHILD_SUBREAPER')
        if any(info[0] == self.owner for info in _proc_snapshot().values()):
            self.restore()
            raise JournalError('dedicated_supervisor_child_appeared_before_spawn')
        self.tracked = set()
        self.signalled = set()
        self.reaped = set()
        self.root = None

    def attach(self, process):
        self.root = process
        rows = _proc_snapshot()
        info = rows.get(process.pid)
        if info:
            self.tracked.add((process.pid, info[1]))
        self.scan()

    def scan(self):
        rows = _proc_snapshot()
        owned = {pid for pid, start in self.tracked if pid in rows and rows[pid][1] == start}
        # Detached/double-forked descendants become direct children of subreaper.
        owned.update(pid for pid, info in rows.items()
                     if info[0] == self.owner)
        changed = True
        while changed:
            changed = False
            for pid, (ppid, _, _) in rows.items():
                if ppid in owned and pid not in owned:
                    owned.add(pid)
                    changed = True
        owned.discard(self.owner)
        for pid in owned:
            self.tracked.add((pid, rows[pid][1]))
        return {pid: rows[pid] for pid in owned}

    def reap(self):
        if self.root is not None:
            self.root.poll()
        for pid, start in list(self.tracked):
            if self.root is not None and pid == self.root.pid:
                continue
            try:
                got, _ = os.waitpid(pid, os.WNOHANG)
                if got:
                    self.reaped.add((pid, start))
            except ChildProcessError:
                pass

    def send(self, sig):
        rows = self.scan()
        for pid, (_, start, state) in rows.items():
            if state == 'Z':
                continue
            # Recheck identity immediately before signaling; never signal a group
            # containing the wrapper or a later unrelated reuse of the PID.
            current = _proc_snapshot().get(pid)
            if current is None or current[1] != start:
                continue
            try:
                os.kill(pid, sig)
                self.signalled.add((pid, start, int(sig)))
            except ProcessLookupError:
                pass

    def cleanup(self, deadline):
        remaining = max(0.0, deadline - time.monotonic())
        term_until = time.monotonic() + min(2.0, remaining / 2)
        self.send(signal.SIGTERM)
        while True:
            self.reap()
            alive = self.scan()
            if not alive:
                return True
            now = time.monotonic()
            if now >= term_until:
                self.send(signal.SIGKILL)
            else:
                self.send(signal.SIGTERM)
            if now >= deadline:
                self.reap()
                return not self.scan()
            time.sleep(min(POLL_SECONDS, deadline - now))

    def restore(self):
        if self.libc.prctl(36, self.previous, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), 'restore_child_subreaper')


def run_supervised(command, *, journal_dir, baseline_bytes, deadline,
                   cleanup_seconds, on_event, env=None, cwd=None):
    """Supervise one worker; deadline includes the reserved cleanup interval.

    Callback failures fail closed and are never acknowledged. A complete event is
    necessary but insufficient for success: the worker must exit and all tracked
    descendants must be terminated/reaped. This function never writes canonical
    data. Caller must be a dedicated supervisor without concurrent child tasks.
    """
    if (not isinstance(baseline_bytes, bytes) or len(baseline_bytes) > MAX_BASELINE_BYTES or
            not math.isfinite(deadline) or not math.isfinite(cleanup_seconds) or cleanup_seconds <= 0):
        raise ValueError('invalid_supervisor_bounds')
    started = time.monotonic()
    cutoff = deadline - cleanup_seconds
    if cutoff <= started:
        return dict(exit_code=124, timed_out=True, cleanup_confirmed=True,
                    reason='no_worker_budget', journal_dir=None, state={})
    directory = Path(journal_dir).absolute()
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    _directory(directory)
    header = dict(schema_version=1, run_id=os.environ.get('RELEASE_EXECUTION_ID') or
                  ':'.join((os.environ.get('GITHUB_RUN_ID', 'local'),
                            os.environ.get('GITHUB_RUN_ATTEMPT', '1'))),
                  nonce=uuid.uuid4().hex, baseline_sha256=_sha(baseline_bytes), deadline=cutoff)
    _immutable(directory / 'baseline.json', baseline_bytes, limit=MAX_BASELINE_BYTES)
    _immutable(directory / 'header.json', _json_bytes(header))
    _sync_directory(directory.parent)
    reader = _Reader(directory, _header(directory))
    child_env = dict(os.environ if env is None else env)
    child_env.update(GOSI_WORKER_JOURNAL=str(directory),
                     GOSI_WORKER_BASELINE=str(directory / 'baseline.json'),
                     GOSI_WORKER_DEADLINE_MONOTONIC=str(cutoff),
                     GOSI_WORKER_RUN_ID=header['run_id'], GOSI_WORKER_NONCE=header['nonce'],
                     GOSI_WORKER_BASELINE_SHA256=header['baseline_sha256'])
    tree, process = None, None
    reason, error, timed_out, cleanup_confirmed = '', None, False, False
    child_code = None
    unexpected_descendants = False
    try:
        tree = _ProcessTree()
        process = subprocess.Popen(command, cwd=cwd, env=child_env, start_new_session=True)
        tree.attach(process)
        while True:
            reader.drain(on_event)
            tree.scan()
            child_code = process.poll()
            if child_code is not None:
                reader.drain(on_event)
                unexpected_descendants = bool(child_code == 0 and reader.complete is not None and
                    any(info[2] != 'Z' for info in tree.scan().values()))
                break
            if time.monotonic() >= cutoff:
                timed_out, reason = True, 'worker_deadline'
                break
            time.sleep(max(0, min(POLL_SECONDS, cutoff - time.monotonic())))
    except Exception as exc:
        reason, error = 'supervisor_error', type(exc).__name__ + ': ' + str(exc)
    finally:
        if tree is not None:
            try:
                cleanup_confirmed = tree.cleanup(deadline)
                if process is not None:
                    child_code = process.poll()
                # TERM may allow a last durable STOP/result. Accept only validated
                # events; an earlier callback error is not blindly retried.
                if error is None:
                    reader.drain(on_event)
                reader.verify_retained()
            except Exception as exc:
                reason, error = 'supervisor_error', type(exc).__name__ + ': ' + str(exc)
            finally:
                tree.restore()
        elif process is None:
            cleanup_confirmed = True
    complete_code = reader.complete['payload']['exit_code'] if reader.complete else None
    if not cleanup_confirmed:
        code, reason = 125, 'descendant_cleanup_unconfirmed'
    elif error:
        code = 1
    elif reader.stop_seen:
        code, reason = 2, 'provider_stop'
    elif timed_out:
        code = 124
    elif complete_code is None:
        code = child_code if child_code and child_code > 0 else 1
        reason = 'missing_complete' if child_code == 0 else 'worker_failed'
    elif child_code != complete_code:
        code = child_code if child_code and child_code > 0 else 1
        reason = 'worker_exit_mismatch'
    elif complete_code != 0:
        code, reason = complete_code, 'worker_reported_failure'
    elif unexpected_descendants:
        code, reason = 1, 'unexpected_descendants_after_complete'
    else:
        code, reason = 0, 'complete'
    return dict(exit_code=code, timed_out=timed_out, cleanup_confirmed=cleanup_confirmed,
                reason=reason, error=error, worker_exit_code=child_code,
                event_count=reader.sequence, stop_seen=reader.stop_seen,
                journal_dir=str(directory), state=reader.last_state,
                unexpected_descendants=unexpected_descendants,
                elapsed_seconds=time.monotonic() - started,
                tracked_pids=sorted(pid for pid, _ in tree.tracked) if tree else [],
                signalled_pids=sorted({pid for pid, _, _ in tree.signalled}) if tree else [])


def emit_guard_result(exit_code):
    """Child-only terminal token, called after all inner supervisor work returns.

    An inherited pipe is intentionally used rather than another fsynced journal:
    otherwise outer journal I/O would recreate the stall it must contain.
    """
    if type(exit_code) is not int or not 0 <= exit_code <= 255:
        raise ValueError('invalid_guard_exit_code')
    fd = int(os.environ['GOSI_GUARD_RESULT_FD'])
    token = _json_bytes(dict(schema_version=1, nonce=os.environ['GOSI_GUARD_NONCE'],
                            exit_code=exit_code))
    if len(token) > 4096:
        raise ValueError('guard_token_size')
    try:
        # The <= PIPE_BUF nonblocking write is atomic or fails; it cannot block
        # behind a hung filesystem, publication receipt, or ACK.
        if os.write(fd, token) != len(token):
            raise JournalError('guard_token_incomplete')
    finally:
        os.close(fd)


def run_guarded(command, *, deadline, cleanup_seconds, env=None, cwd=None):
    """Disk-free outer watchdog for a killable collection supervisor.

    The original absolute deadline includes this cleanup share. Pass its cutoff
    to the child as the INNER absolute deadline, and subtract this cleanup share
    from the existing reserve; do not append another reserve or reset the clock.
    The caller must have no other child tasks. No canonical paths, journal files,
    fsync, application callbacks, or captured stdout are used by this guard.
    """
    if (not isinstance(deadline, (int, float)) or not math.isfinite(deadline) or
            not isinstance(cleanup_seconds, (int, float)) or
            not math.isfinite(cleanup_seconds) or cleanup_seconds <= 0):
        raise ValueError('invalid_guard_bounds')
    started = time.monotonic()
    cutoff = deadline - cleanup_seconds
    if cutoff <= started:
        return dict(exit_code=124, timed_out=True, cleanup_confirmed=True,
                    reason='no_worker_budget', error=None, worker_exit_code=None,
                    state={}, tracked_pids=[], signalled_pids=[])
    nonce = uuid.uuid4().hex
    tree, process, reader_fd, writer_fd = None, None, None, None
    token = b''
    terminal = None
    child_code = None
    error = None
    timed_out, cleanup_confirmed, unexpected_descendants = False, False, False
    reason = ''

    def read_token():
        nonlocal token, terminal
        while True:
            try:
                chunk = os.read(reader_fd, 4097 - len(token))
            except BlockingIOError:
                break
            if not chunk:
                break
            token += chunk
            terminal = None
            if len(token) > 4096:
                raise JournalError('guard_token_size')
        if token.endswith(b'\n'):
            value = _parse_json(token)
            if (not isinstance(value, dict) or set(value) != {'schema_version', 'nonce', 'exit_code'} or
                    value.get('schema_version') != 1 or value.get('nonce') != nonce or
                    type(value.get('exit_code')) is not int or not 0 <= value['exit_code'] <= 255):
                raise JournalError('guard_token_binding')
            terminal = value

    try:
        tree = _ProcessTree()
        reader_fd, writer_fd = os.pipe2(os.O_CLOEXEC | os.O_NONBLOCK)
        child_env = dict(os.environ if env is None else env)
        child_env.update(GOSI_GUARD_RESULT_FD=str(writer_fd), GOSI_GUARD_NONCE=nonce,
                         GOSI_GUARD_DEADLINE_MONOTONIC=str(cutoff))
        process = subprocess.Popen(command, env=child_env, cwd=cwd,
                                   pass_fds=(writer_fd,), start_new_session=True)
        os.close(writer_fd)
        writer_fd = None
        tree.attach(process)
        while True:
            read_token()
            tree.scan()
            child_code = process.poll()
            if child_code is not None:
                read_token()
                unexpected_descendants = bool(child_code == 0 and terminal is not None and
                    any(info[2] != 'Z' for info in tree.scan().values()))
                break
            if time.monotonic() >= cutoff:
                timed_out, reason = True, 'worker_deadline'
                break
            time.sleep(max(0, min(POLL_SECONDS, cutoff - time.monotonic())))
    except Exception as exc:
        reason, error = 'supervisor_error', type(exc).__name__ + ': ' + str(exc)
    finally:
        try:
            if tree is not None:
                cleanup_confirmed = tree.cleanup(deadline)
                if process is not None:
                    child_code = process.poll()
                if reader_fd is not None and error is None:
                    read_token()
            elif process is None:
                cleanup_confirmed = True
        except Exception as exc:
            reason, error = 'supervisor_error', type(exc).__name__ + ': ' + str(exc)
        finally:
            for fd in (reader_fd, writer_fd):
                if fd is not None:
                    os.close(fd)
            if tree is not None:
                tree.restore()
    complete_code = terminal['exit_code'] if terminal else None
    if not cleanup_confirmed:
        code, reason = 125, 'descendant_cleanup_unconfirmed'
    elif error:
        code = 1
    elif timed_out:
        code = 124
    elif complete_code is None:
        code = child_code if child_code and child_code > 0 else 1
        reason = 'missing_complete' if child_code == 0 else 'worker_failed'
    elif child_code != complete_code:
        code = child_code if child_code and child_code > 0 else 1
        reason = 'worker_exit_mismatch'
    elif complete_code != 0:
        code, reason = complete_code, 'worker_reported_failure'
    elif unexpected_descendants:
        code, reason = 1, 'unexpected_descendants_after_complete'
    else:
        code, reason = 0, 'complete'
    return dict(exit_code=code, timed_out=timed_out, cleanup_confirmed=cleanup_confirmed,
                reason=reason, error=error, worker_exit_code=child_code,
                unexpected_descendants=unexpected_descendants,
                elapsed_seconds=time.monotonic() - started, state={},
                tracked_pids=sorted(pid for pid, _ in tree.tracked) if tree else [],
                signalled_pids=sorted({pid for pid, _, _ in tree.signalled}) if tree else [])
