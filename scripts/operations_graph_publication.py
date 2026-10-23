"""Complete bounded graph publication; logical removal rules remain unchanged.

The graph is a derived projection, separate from the private state/receipt safety
snapshot. Its immutable members are never merged, reformatted, or removed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

from scripts import operations_graph_storage as storage

GRAPH = storage.GRAPH_PATH
DIRECTORY = storage.GRAPH_DIRECTORY
PREFIX = DIRECTORY + '/'
MANIFEST = 'data/publish_deletions.json'


def owns(name):
    return name == GRAPH or name.startswith(PREFIX)


def file_limit(name):
    return storage.GRAPH_MAX_BYTES if name == GRAPH else storage.GRAPH_MEMBER_MAX_BYTES


def _safe(root, name):
    root = Path(root).absolute()
    if not owns(name) or '\\' in name or ':' in name or any(p in ('', '.', '..') for p in name.split('/')):
        raise ValueError('operations graph path scope invalid')
    path = root / name
    for part in [*reversed(path.parents), path]:
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('operations graph link denied')
    return path


def read_file(root, name, *, expected=None):
    path = _safe(root, name)
    before = path.lstat()
    limit = file_limit(name)
    def regular(info):
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError('operations graph member missing, linked, or oversized')
    def unchanged(*infos):
        if any(len({getattr(info, key) for info in infos}) != 1
               for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')):
            raise ValueError('operations graph member changed during read')
    regular(before)
    if expected is not None:
        unchanged(expected, before)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        regular(opened)
        unchanged(before, opened)
        raw = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    _safe(root, name)
    final = path.lstat()
    regular(final)
    if (len(raw) > limit or len(raw) != final.st_size or
            any(len({getattr(info, key) for info in (before, opened, after, final)}) != 1
                for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))):
        raise ValueError('operations graph member changed during read')
    return raw


def segmented(files):
    if any(name.startswith(PREFIX) for name in files):
        return True
    raw = files.get(GRAPH)
    return bool(raw is not None and storage.is_graph_manifest(raw))


def validate_snapshot(files):
    if len(files) > storage.GRAPH_MAX_MEMBERS + 1 or sum(map(len, files.values())) > storage.GRAPH_AGGREGATE_MAX_BYTES:
        raise ValueError('operations graph retained storage capacity reached')
    for name, raw in files.items():
        if not owns(name) or not isinstance(raw, bytes) or len(raw) > file_limit(name):
            raise ValueError('operations graph snapshot scope/size invalid')
        if name != GRAPH:
            storage.validate_graph_member(name, raw)
    if not files:
        return None
    if GRAPH not in files:
        raise ValueError('operations graph manifest missing with retained members')
    return storage.load_operations_graph(files[GRAPH], files.__getitem__)


def disk_inventory(root):
    """Bound the whole namespace from metadata before reading any payload."""
    entries, total, members = {}, 0, 0
    def add(name):
        nonlocal total, members
        info = _safe(root, name).lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_size > file_limit(name)):
            raise ValueError('operations graph member missing, linked, or oversized')
        total += info.st_size
        members += name != GRAPH
        if (members > storage.GRAPH_MAX_MEMBERS
                or total > storage.GRAPH_AGGREGATE_MAX_BYTES):
            raise ValueError('operations graph retained storage capacity reached')
        entries[name] = info
    path = _safe(root, GRAPH)
    if path.exists():
        add(GRAPH)
    directory = _safe(root, PREFIX + 'probe').parent
    if directory.exists():
        if not directory.is_dir():
            raise ValueError('operations graph storage directory invalid')
        for path in directory.iterdir():
            add(PREFIX + path.name)
    return entries


def snapshot(root):
    files = {name: read_file(root, name, expected=info)
             for name, info in disk_inventory(root).items()}
    validate_snapshot(files)
    return files


def _git(root, *args, input=None):
    result = subprocess.run(['git', '-C', str(root), *args], input=input, capture_output=True)
    if result.returncode:
        raise ValueError('operations graph Git snapshot unavailable')
    return result.stdout


def git_inventory(root, ref):
    """Validate immutable blob sizes and aggregate bounds before blob IO."""
    tree = _git(root, 'ls-tree', '-r', '-z', '-l', ref, '--', GRAPH, DIRECTORY)
    entries, total, members = {}, 0, 0
    for entry in tree.split(b'\0'):
        if not entry:
            continue
        attributes, raw_name = entry.split(b'\t', 1)
        mode, kind, digest, raw_size = attributes.split()
        name, size = raw_name.decode('utf-8'), int(raw_size)
        if mode not in (b'100644', b'100755') or kind != b'blob' or not owns(name):
            raise ValueError('operations graph Git snapshot scope invalid')
        total += size
        members += name != GRAPH
        if (size > file_limit(name) or total > storage.GRAPH_AGGREGATE_MAX_BYTES or
                members > storage.GRAPH_MAX_MEMBERS):
            raise ValueError('operations graph Git snapshot capacity reached')
        entries[name] = (digest, size)
    return entries


def read_git_blob(root, entry):
    digest, size = entry
    raw = _git(root, 'cat-file', 'blob', digest.decode('ascii'))
    if len(raw) != size:
        raise ValueError('operations graph Git blob size mismatch')
    return raw


def git_snapshot(root, ref):
    entries = git_inventory(root, ref)
    if not entries:
        return {}
    batch = _git(root, 'cat-file', '--batch', input=b''.join(digest + b'\n' for digest, _ in entries.values()))
    files, offset = {}, 0
    for name, (digest, size) in entries.items():
        end = batch.index(b'\n', offset)
        if batch[offset:end] != digest + b' blob ' + str(size).encode():
            raise ValueError('operations graph Git blob mismatch')
        offset = end + 1
        files[name] = batch[offset:offset + size]
        offset += size
        if batch[offset:offset + 1] != b'\n':
            raise ValueError('operations graph Git blob truncated')
        offset += 1
    if offset != len(batch):
        raise ValueError('operations graph Git snapshot trailing bytes')
    validate_snapshot(files)
    return files


def continuation(before, after):
    """Storage transitions cannot remove or rewrite any old immutable bytes."""
    validate_snapshot(before)
    validate_snapshot(after)
    if before and not after:
        raise ValueError('operations graph snapshot removal forbidden')
    for name, raw in before.items():
        if name != GRAPH and after.get(name) != raw:
            raise ValueError('operations graph immutable member removed or changed')
    if before.get(GRAPH) is not None and storage.is_graph_manifest(before[GRAPH]):
        if not after.get(GRAPH) or not storage.is_graph_manifest(after[GRAPH]):
            raise ValueError('operations graph storage downgrade forbidden')


def graph_pair(base, local):
    return validate_snapshot(base), validate_snapshot(local)


def removal_ids(base, local, policy):
    from scripts.collector_snapshot_history import allowed_removals
    old, new = graph_pair(base, local)
    if old is None:
        return []
    if new is None:
        raise ValueError('operations graph snapshot removal forbidden')
    return sorted(set(map(str, allowed_removals(GRAPH, old, new, policy))))


def verify_removals(base, local, policy, manifest):
    from scripts.publish_transaction import deletion_authorized
    ids = removal_ids(base, local, policy)
    if ids:
        from hashlib import sha256
        records = [r for r in (manifest or {}).get('deletions', []) if isinstance(r, dict)
                   and r.get('path') == GRAPH]
        bound = any(r.get('base_sha256') == sha256(base[GRAPH]).hexdigest()
                    and r.get('replacement_sha256') == sha256(local[GRAPH]).hexdigest()
                    and r.get('ids') == ids and r.get('delete_file') is False
                    and r.get('policy_ref') == 'scripts/collector_snapshot_history.py'
                    and deletion_authorized(
                        GRAPH, base[GRAPH], ids, {'deletions': [r]}, replacement=local[GRAPH])
                    for r in records)
        if not bound:
            raise ValueError('operations graph logical removal requires exact reason manifest')
    return ids


def _install(root, chosen):
    """Members first, one mutable manifest last; caller operates a private tree."""
    for name in sorted(chosen, key=lambda name: name == GRAPH):
        raw = chosen[name]
        target = _safe(root, name)
        if target.exists():
            current = read_file(root, name)
            if current == raw:
                continue
            if name != GRAPH:
                raise ValueError('operations graph immutable member conflict')
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = _safe(root, GRAPH).parent
        staging.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.graph-publication-', dir=staging)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            _safe(root, name)
            if name == GRAPH:
                os.replace(temporary, target)
            else:
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    if read_file(root, name) != raw:
                        raise ValueError('operations graph immutable member conflict')
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        if os.name != 'nt':
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)


class SnapshotGuard:
    def __init__(self, base, candidate, policy, manifest):
        self.base, self.candidate = dict(base), dict(candidate)
        self.policy, self.manifest = policy, manifest
        self.active = False
        self.captured_matches_disk = True
        self.manifest_matches_capture = True

    def activate(self):
        if self.active:
            return
        if not self.captured_matches_disk:
            raise ValueError('operations graph snapshot omitted from publication paths or changed after capture')
        continuation(self.base, self.candidate)
        ids = verify_removals(self.base, self.candidate, self.policy, self.manifest)
        if ids and not self.manifest_matches_capture:
            raise ValueError('operations graph removal manifest omitted or changed after capture')
        self.active = True

    @classmethod
    def capture(cls, root, ref, delta, policy, manifest):
        from scripts.operations_publication import git_snapshot_manifest
        base, actual = git_snapshot(root, ref), snapshot(root)
        captured = dict(base)
        for name, (_before, after) in delta.items():
            if owns(name):
                if after is None:
                    captured.pop(name, None)
                else:
                    captured[name] = after
        guard = cls(base, captured, policy, manifest)
        guard.captured_matches_disk = captured == actual
        before = git_snapshot_manifest(root, ref)
        captured_manifest = delta[MANIFEST][1] if MANIFEST in delta else before
        manifest_path = Path(root) / MANIFEST
        actual_manifest = manifest_path.read_bytes() if manifest_path.exists() else None
        guard.manifest_matches_capture = captured_manifest == actual_manifest
        if segmented(base) or segmented(actual):
            guard.activate()
        return guard

    def install(self, root):
        remote = snapshot(root)
        if not self.active and not segmented(remote):
            return remote, None
        self.activate()
        continuation(self.base, remote)
        if self.candidate == self.base:
            chosen = remote
        elif remote not in (self.base, self.candidate):
            raise ValueError('concurrent operations graph snapshot requires reconciliation')
        else:
            chosen = self.candidate
        continuation(remote, chosen)
        _install(root, chosen)
        if snapshot(root) != chosen:
            raise ValueError('operations graph snapshot changed during overlay')
        return remote, dict(chosen)

    def verify_final(self, root, remote, installed):
        final = snapshot(root)
        if not self.active and not segmented(final):
            return None
        self.activate()
        for before in (self.candidate, remote, installed):
            if before is not None:
                continuation(before, final)
                removal_ids(before, final, self.policy)
        from scripts.collector_snapshot_history import update
        # The final regenerated projection is checked against fetched HEAD and
        # receives exactly the existing logical nodes/edges removal reasons.
        update(Path(root), [GRAPH])
        manifest_path = Path(root) / MANIFEST
        manifest = json.loads(manifest_path.read_bytes()) if manifest_path.exists() else {}
        verify_removals(remote, final, self.policy, manifest)
        if snapshot(root) != final:
            raise ValueError('operations graph snapshot changed during final validation')
        return final
