"""Atomic publication boundary for segmented operations safety snapshots.

No merge, history deletion waiver, provider dispatch or policy mutation lives
here. The existing restore validators validate the complete logical snapshot.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

from scripts import operations_storage as storage

STATE = storage.OPS_STATE_PATH
HISTORY = storage.OPS_STATE_DIRECTORY + '/'
REPORTS = 'data/operations/reports/'
MANIFEST = 'data/publish_deletions.json'
POLICY_REF = 'scripts/collector_snapshot_history.py'


def owns(name):
    return name == STATE or name.startswith((HISTORY, REPORTS))


def segmented(files):
    if any(name.startswith(HISTORY) for name in files):
        return True
    body = files.get(STATE)
    if body is None:
        return False
    value = json.loads(body)
    return isinstance(value, dict) and storage.STORAGE_KEY in value


def worktree_segmented(root):
    from scripts.restore_operations_safety import _read, execution
    root = Path(root)
    directory = execution._safe(root, storage.OPS_STATE_DIRECTORY)
    if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
        return True
    path = execution._safe(root, STATE)
    return segmented({STATE: _read(root, STATE)}) if path.exists() else False


def git_snapshot(root, ref):
    """Read exact snapshot blobs in one batch, including orphan history files."""
    def command(*args, input=None):
        result = subprocess.run(['git', '-C', str(root), *args], input=input, capture_output=True)
        if result.returncode:
            raise ValueError('operations Git snapshot unavailable')
        return result.stdout
    tree = command('ls-tree', '-r', '-z', '-l', ref, '--', STATE,
                   REPORTS.rstrip('/'), HISTORY.rstrip('/'))
    entries = []
    total = 0
    state_size = 0
    for entry in tree.split(b'\0'):
        if not entry:
            continue
        attributes, raw_name = entry.split(b'\t', 1)
        mode, kind, digest, size = attributes.split()
        name = raw_name.decode('utf-8')
        if mode not in (b'100644', b'100755') or kind != b'blob' or not owns(name):
            raise ValueError('operations Git snapshot contains unsafe member')
        size = int(size)
        if size > storage.operations_file_max_bytes(name):
            raise ValueError('operations Git snapshot file oversized')
        total += size
        if name == STATE:
            state_size = size
        entries.append((name, digest, size))
    if len(entries) > storage.OPS_SNAPSHOT_MAX_FILES or total > storage.operations_snapshot_max_bytes(state_size):
        raise ValueError('operations Git snapshot capacity reached')
    if not entries:
        return {}
    batch = command('cat-file', '--batch', input=b''.join(digest + b'\n' for _, digest, _ in entries))
    files = {}
    offset = 0
    for name, digest, size in entries:
        end = batch.index(b'\n', offset)
        if batch[offset:end] != digest + b' blob ' + str(size).encode():
            raise ValueError('operations Git snapshot blob mismatch')
        offset = end + 1
        files[name] = batch[offset:offset + size]
        offset += size
        if batch[offset:offset + 1] != b'\n':
            raise ValueError('operations Git snapshot truncated')
        offset += 1
    if offset != len(batch):
        raise ValueError('operations Git snapshot trailing bytes')
    return files


def raw_snapshot(root):
    """Bounded exact capture before a later runtime can first migrate legacy.

    Missing continuity pairs remain usable only by existing legacy behavior;
    activation invokes the strict complete snapshot validator before any use.
    """
    from scripts.restore_operations_safety import _read, execution, REPORT, LEDGER
    root = Path(root)
    files, total = {}, 0
    limit = storage.operations_snapshot_max_bytes(0)

    def add(name):
        nonlocal total, limit
        path = execution._safe(root, name)
        size = path.stat().st_size
        if name == STATE:
            limit = storage.operations_snapshot_max_bytes(size)
        if (size > storage.operations_file_max_bytes(name) or
                len(files) >= storage.OPS_SNAPSHOT_MAX_FILES or total + size > limit):
            raise ValueError('operations captured snapshot capacity reached')
        raw = _read(root, name)
        total += len(raw)
        if total > limit:
            raise ValueError('operations captured snapshot capacity reached')
        files[name] = raw

    state = execution._safe(root, STATE)
    if state.exists():
        add(STATE)
    for relative in (REPORTS.rstrip('/'), HISTORY.rstrip('/')):
        directory = execution._safe(root, relative)
        if directory.exists():
            if not directory.is_dir():
                raise ValueError('operations snapshot directory invalid')
            for path in directory.iterdir():
                name = path.relative_to(root).as_posix()
                execution._safe(root, name)
                if name == REPORTS + '.execution-ledger.lock':
                    continue
                if (not path.is_file() or
                        relative == HISTORY.rstrip('/') and not storage.is_operations_state_member(name) or
                        relative == REPORTS.rstrip('/') and name != LEDGER and not REPORT.fullmatch(name)):
                    raise ValueError('operations snapshot member scope invalid')
                add(name)
    return files


def snapshot(root):
    from scripts.restore_operations_safety import verify_current
    return verify_current(root)


def state_pair(base, local):
    """Hydrate both logical states; no storage metadata is a rotation waiver."""
    return storage.operations_state_from_files(base), storage.operations_state_from_files(local)


def removal_ids(base, local, policy):
    from scripts.collector_snapshot_history import allowed_removals
    old, new = state_pair(base, local)
    return sorted(set(map(str, allowed_removals(STATE, old, new, policy))))


def verify_removals(base, local, policy, manifest):
    from scripts.publish_transaction import deletion_authorized
    ids = removal_ids(base, local, policy)
    if ids and not deletion_authorized(STATE, base[STATE], ids, manifest, replacement=local[STATE]):
        raise ValueError('operations logical removal manifest does not bind exact snapshot')
    return ids


class SnapshotGuard:
    def __init__(self, base, candidate, policy, manifest, *, active=True):
        self.base = dict(base)
        self.candidate = dict(candidate)
        self.policy = policy
        self.manifest = manifest
        self.active = False
        self.captured_matches_disk = True
        self.manifest_matches_capture = True
        if active:
            self.activate()

    def activate(self):
        if self.active:
            return
        from scripts.restore_operations_safety import _nonregression
        if not self.captured_matches_disk:
            raise ValueError('operations snapshot omitted from publication paths or changed after capture')
        _nonregression(self.base, self.candidate)
        self.removals = verify_removals(self.base, self.candidate, self.policy, self.manifest)
        if self.removals and not self.manifest_matches_capture:
            raise ValueError('operations removal manifest omitted or changed after capture')
        self.active = True

    @classmethod
    def capture(cls, root, ref, delta, policy, manifest):
        base = git_snapshot(root, ref)
        actual = raw_snapshot(root)
        captured = dict(base)
        for name, (_before, after) in delta.items():
            if owns(name):
                if after is None:
                    captured.pop(name, None)
                else:
                    captured[name] = after
        guard = cls(base, captured, policy, manifest, active=False)
        guard.captured_matches_disk = captured == actual
        before = git_snapshot_manifest(root, ref)
        captured_manifest = delta[MANIFEST][1] if MANIFEST in delta else before
        manifest_path = Path(root) / MANIFEST
        actual_manifest = manifest_path.read_bytes() if manifest_path.exists() else None
        guard.manifest_matches_capture = captured_manifest == actual_manifest
        if segmented(base) or segmented(actual):
            guard.activate()
            if snapshot(root) != actual:
                raise ValueError('operations snapshot changed after capture')
        return guard

    def install(self, root):
        remote = raw_snapshot(root)
        if not self.active and not segmented(remote):
            return remote, None
        self.activate()
        from scripts.restore_operations_safety import _nonregression
        remote = snapshot(root)
        _nonregression(self.base, remote)
        # Independent executions cannot produce a hybrid state/ledger/report
        # chain. An untouched local snapshot may safely follow latest remote.
        if self.candidate == self.base:
            chosen = remote
        elif remote not in (self.base, self.candidate):
            raise ValueError('concurrent operations snapshot requires reconciliation')
        else:
            chosen = self.candidate
        _nonregression(remote, chosen)
        for name, raw in chosen.items():
            target = Path(root) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.read_bytes() != raw:
                target.write_bytes(raw)
        if snapshot(root) != chosen:
            raise ValueError('operations snapshot changed during atomic overlay')
        return remote, dict(chosen)

    def verify_final(self, root, remote, installed):
        final_raw = raw_snapshot(root)
        if not self.active and not segmented(final_raw):
            return None
        self.activate()
        from scripts.restore_operations_safety import _nonregression
        from scripts.collector_snapshot_history import update
        final = snapshot(root)
        checked = []
        for before in (self.candidate, remote, installed):
            if before not in checked:
                _nonregression(before, final)
                removal_ids(before, final, self.policy)
                checked.append(before)
        # Bind any permitted current-watch rotation to the actual fetched HEAD
        # and final bytes; retain every unrelated manifest record unchanged.
        update(Path(root), [STATE])
        manifest_path = Path(root) / MANIFEST
        manifest = json.loads(manifest_path.read_bytes()) if manifest_path.exists() else {}
        verify_removals(remote, final, self.policy, manifest)
        if snapshot(root) != final:
            raise ValueError('operations snapshot changed while validating final manifest')
        return final


def git_snapshot_manifest(root, ref):
    result = subprocess.run(['git', '-C', str(root), 'show', ref + ':' + MANIFEST], capture_output=True)
    return result.stdout if result.returncode == 0 else None
