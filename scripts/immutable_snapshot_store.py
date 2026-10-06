"""Bounded exact-byte storage for four explicitly whitelisted report histories.

Keep up to 128 legacy flat files in place, then spill new content into its
SHA256 two-hex prefix directory (256 possible shards, 128 files per shard).
Never prune, move, rewrite, or reformat a retained snapshot. Publishers hold
the existing shared report/manifest lock across retention and publication.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile

HISTORY_PATHS = frozenset({
    'data/agents/workflow_status_history',
    'data/knowledge/moe_evaluation_history',
    'data/agents/gemini_escalation_history',
    'data/knowledge/gosi_observation_history',
    'data/daiso_real/candidate_pool_history',
})
MAX_ENTRIES = 128
MAX_SHARDS = 256
MAX_BYTES = 8 * 1024 * 1024
_DIGEST = re.compile(r'[0-9a-f]{64}')
_FILE = re.compile(r'([0-9a-f]{64})\.json')
_SHARD = re.compile(r'[0-9a-f]{2}')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _no_link(info):
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
        raise ValueError('symlink/reparse immutable snapshot path denied')


def _safe(root, name):
    target = root / name
    if '..' in target.parts or (target != root and root not in target.parents):
        raise ValueError('immutable snapshot path escapes root')
    for entry in [*reversed(target.parents), target]:
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        _no_link(info)
    return target


def _history(root, name):
    if name not in HISTORY_PATHS:
        raise ValueError('immutable snapshot history outside whitelist')
    root = Path(root).absolute()
    return root, _safe(root, name)


def _regular(info):
    _no_link(info)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('immutable snapshot must be a regular non-linked file')
    if info.st_size > MAX_BYTES:
        raise ValueError('immutable snapshot size bound exceeded')


def _read(root, name, digest):
    target = _safe(root, name)
    before = target.lstat()
    _regular(before)
    fd = os.open(target, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as handle:
        opened = os.fstat(handle.fileno())
        _regular(opened)
        if (before.st_dev, before.st_ino, before.st_size) != (opened.st_dev, opened.st_ino, opened.st_size):
            raise ValueError('concurrent immutable snapshot changed')
        raw = handle.read(MAX_BYTES + 1)
        after = os.fstat(handle.fileno())
    _regular(after)
    final = _safe(root, name).lstat()
    _regular(final)
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    # Some Windows/Python versions expose creation time through path stat,
    # change time through fd stat. Compare both APIs with themselves, while
    # identity/size/mtime must agree across APIs too. No ctime change is waived.
    changed = [k for k in fields if getattr(opened,k) != getattr(after,k)
               or getattr(before,k) != getattr(final,k)
               or (k != 'st_ctime_ns' and getattr(after,k) != getattr(final,k))]
    if changed:
        raise ValueError('concurrent immutable snapshot changed: '+','.join(changed))
    if len(raw) > MAX_BYTES or len(raw) != after.st_size:
        raise ValueError('immutable snapshot size bound exceeded')
    if _sha(raw) != digest:
        raise ValueError('immutable snapshot history malformed/tampered: hash mismatch')
    return raw


def _entries(directory, limit):
    result = []
    for entry in directory.iterdir():
        result.append(entry)
        if len(result) > limit:
            raise ValueError('immutable snapshot capacity exhausted; no pruning permitted')
    return sorted(result)


def _scan(root, name):
    root, history = _history(root, name)
    paths, counts, flat = {}, {}, 0
    if not history.exists():
        return root, paths, flat, counts
    if not stat.S_ISDIR(history.lstat().st_mode):
        raise ValueError('immutable snapshot history is not a directory')
    def accept(entry, prefix=None):
        match = _FILE.fullmatch(entry.name)
        if not match:
            raise ValueError('invalid immutable snapshot hash filename/path')
        digest = match[1]
        if prefix is not None and digest[:2] != prefix:
            raise ValueError('immutable snapshot stored in wrong shard')
        if digest in paths:
            raise ValueError('duplicate immutable snapshot path')
        relative = entry.relative_to(root).as_posix()
        _read(root, relative, digest)
        paths[digest] = relative
    for entry in _entries(history, MAX_ENTRIES + MAX_SHARDS):
        _safe(root, entry.relative_to(root))
        info = entry.lstat()
        if stat.S_ISDIR(info.st_mode):
            if not _SHARD.fullmatch(entry.name):
                raise ValueError('invalid immutable snapshot shard path')
            children = _entries(entry, MAX_ENTRIES)
            counts[entry.name] = len(children)
            if len(counts) > MAX_SHARDS:
                raise ValueError('immutable snapshot shard capacity exhausted')
            for child in children:
                accept(child, entry.name)
        else:
            flat += 1
            if flat > MAX_ENTRIES:
                raise ValueError('immutable snapshot flat capacity exhausted; no pruning permitted')
            accept(entry)
    return root, paths, flat, counts


def load_snapshots(root, history_name):
    """Return digest -> exact bytes, validating legacy flat and prefix shards."""
    root, paths, _, _ = _scan(root, history_name)
    return {digest: _read(root, name, digest) for digest, name in sorted(paths.items())}


def _sync(directory):
    if os.name == 'nt':
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write(root, name, raw, *, immutable):
    target = _safe(root, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    _safe(root, name)
    if target.exists():
        if _read(root, name, target.stem) != raw:
            raise ValueError('immutable snapshot changed')
        return
    fd, tmp = tempfile.mkstemp(prefix='.snapshot-write-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        _safe(root, name)
        try:
            os.link(tmp, target)
        except FileExistsError:
            if _read(root, name, target.stem) != raw:
                raise ValueError('immutable snapshot changed')
        os.unlink(tmp)
        _sync(target.parent)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def retain_snapshots(root, history_name, retained, *, atomic_writer=None):
    """Retain digest -> bytes; return digest -> relative path under caller lock.

    Preflight the entire batch and all existing evidence before any write.
    Full prefix shards fail closed, without overflow routing or pruning.
    atomic_writer lets publishers retain their existing atomic-write race hook.
    """
    root, paths, flat, counts = _scan(root, history_name)
    if not isinstance(retained, dict):
        raise ValueError('immutable snapshots must be a hash/bytes mapping')
    for digest, raw in retained.items():
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest) or not isinstance(raw, bytes) or len(raw) > MAX_BYTES or _sha(raw) != digest:
            raise ValueError('invalid immutable snapshot digest/bytes/size binding')
        if digest in paths and _read(root, paths[digest], digest) != raw:
            raise ValueError('immutable snapshot changed')
    planned = {}
    for digest in sorted(retained):
        if digest in paths:
            continue
        if flat < MAX_ENTRIES:
            planned[digest] = history_name + '/' + digest + '.json'
            flat += 1
        else:
            prefix = digest[:2]
            count = counts.get(prefix, 0)
            if count >= MAX_ENTRIES:
                raise ValueError('immutable snapshot shard capacity exhausted; no pruning permitted')
            counts[prefix] = count + 1
            planned[digest] = history_name + '/' + prefix + '/' + digest + '.json'
    writer = _write if atomic_writer is None else atomic_writer
    # Invoke the existing publisher hook for retained files too, as before.
    for digest in sorted(retained):
        name = paths.get(digest, planned.get(digest))
        writer(root, name, retained[digest], immutable=True)
        if _read(root, name, digest) != retained[digest]:
            raise ValueError('immutable snapshot changed during retention')
    _, actual, _, _ = _scan(root, history_name)
    expected = dict(paths, **planned)
    if actual != expected:
        raise ValueError('concurrent immutable snapshot history changed')
    return {digest: actual[digest] for digest in retained}
