#!/usr/bin/env python3
"""Authenticated, bounded GOSI continuity; never fetch products or reset stops.

This is prospective preservation, not reconstruction of missing historical runs.
Only exact GOSI/source snapshots cross runs. The shared publication manifest is
regenerated against current HEAD, never copied from an artifact. An interrupted
restore remains fail-closed. GitHub metadata authenticates the OUTER ZIP digest;
hashes inside a payload alone do not establish authenticity.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from collections.abc import MutableMapping, Mapping
from datetime import datetime, timezone
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
import urllib.parse
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import gosi_observation_history as h
from scripts.github_artifact_io import REPOSITORY, fetch_github_json, fetch_artifact_bytes
from scripts.immutable_snapshot_store import retain_snapshots, _scan as scan_history, MAX_ENTRIES, MAX_SHARDS

MANIFEST = 'gosi-safety-manifest.json'
HELPER = 'scripts/gosi_safety_checkpoint.py'
BASE = 'https://api.github.com/repos/' + REPOSITORY + '/actions/'
WORKFLOWS = frozenset(('.github/workflows/JARVIS-Deep-Analysis.yml',
    '.github/workflows/gosi-alt.yml', '.github/workflows/gosi-vision.yml'))
WORKFLOW_ORDER = tuple(sorted(WORKFLOWS))
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_TOTAL_BYTES + 1024 * 1024
MAX_RECOVERY_BYTES = 60 * 1024 * 1024
MAX_WIRE_BYTES = MAX_RECOVERY_BYTES + 1024 * 1024
MAX_FILES = 1024
MAX_HISTORY_FILES = MAX_ENTRIES * (MAX_SHARDS + 1)
MAX_RUNS = 1000
MAX_ATTEMPTS = 20
MAX_DETAIL_CALLS = 100
MAX_SEED_PAGES = 3
MAX_SEED_ARTIFACTS = 10
HISTORY_FILE = re.compile(re.escape(h.HISTORY_PATH) + r'/(?:[0-9a-f]{2}/)?([0-9a-f]{64})\.json')
RECOVERY_FILE = re.compile(r'recovery/(?:\.gosi-(?:collection|safety-restore)\.pending|publication-lock|'
    r'journal/(?:header\.json|baseline\.json|[0-9]{6}\.(?:json|ack)|'
    r'publications/[0-9a-f]{32}\.(?:input|receipt)\.json))')


class Blocked(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Blocked(reason)


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(Blocked('nonfinite_json')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Blocked('invalid_json') from exc


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                       separators=(',', ':')) + '\n').encode()


def _git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, timeout=30)


def _head(root):
    result = _git(root, 'rev-parse', 'HEAD')
    require(result.returncode == 0, 'head_unavailable')
    return result.stdout.decode().strip()


def _lineage(repository, run_id, run_attempt, commit):
    require(repository == REPOSITORY, 'repository_scope_invalid')
    require(all(re.fullmatch(r'[1-9][0-9]{0,19}', str(v)) and not isinstance(v, bool)
                for v in (run_id, run_attempt)), 'run_identity_invalid')
    require(isinstance(commit, str) and re.fullmatch(r'[0-9a-f]{40}', commit), 'commit_invalid')
    return dict(repository=repository, run_id=str(run_id), run_attempt=str(run_attempt), commit=commit)


def _checkout_binding(root, event_commit, checkout_commit):
    """Reuse queued-checkout policy, keeping the event identity separate."""
    require(all(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{40}', value)
                for value in (event_commit, checkout_commit)), 'checkout_commit_invalid')
    require(not _git(root, 'merge-base', '--is-ancestor', event_commit, checkout_commit).returncode
            and not _git(root, 'merge-base', '--is-ancestor', checkout_commit, 'HEAD').returncode,
            'checkout_not_event_descendant')
    if checkout_commit != event_commit:
        from scripts.fast_forward_queued_checkout import plan
        policy = _git(root, 'show', event_commit + ':config/publish_policy.json')
        changed = _git(root, 'diff', '--name-only', event_commit, checkout_commit)
        require(policy.returncode == changed.returncode == 0, 'checkout_binding_unavailable')
        require(plan(event_commit, checkout_commit, changed.stdout.decode().splitlines(),
                     _json(policy.stdout)) == 'fast_forward', 'checkout_producer_policy_changed')


def _coverage(value):
    require(isinstance(value, dict) and len(value) <= MAX_RUNS * len(WORKFLOWS), 'coverage_invalid')
    for identity, row in value.items():
        require(isinstance(identity, str) and re.fullmatch(r'[1-9][0-9]{0,19}', identity)
                and isinstance(row, list) and len(row) == 3
                and type(row[0]) is int and 1 <= row[0] <= MAX_ATTEMPTS
                and type(row[1]) is int and 0 <= row[1] < len(WORKFLOW_ORDER)
                and isinstance(row[2], str) and re.fullmatch(r'[0-9a-f]{40}', row[2]), 'coverage_record_invalid')
    return value


def _pack_coverage(root, lineage):
    proof_path = h.safe_path(root, h.CONTINUITY_PROOF)
    proof = _json(_read(root, h.CONTINUITY_PROOF, 512 * 1024)) if proof_path.exists() else {}
    coverage = dict(_coverage(proof.get('coverage', {})))
    workflow = proof.get('workflow_path', WORKFLOW_ORDER[0])
    require(workflow in WORKFLOWS, 'coverage_workflow_invalid')
    coverage[lineage['run_id']] = [int(lineage['run_attempt']), WORKFLOW_ORDER.index(workflow), lineage['commit']]
    return _coverage(coverage)


def _epoch(value):
    require(isinstance(value, str), 'stop_clock_missing')
    try:
        when = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(when.tzinfo is not None, 'clock_timezone_missing')
        return when.timestamp()
    except (ValueError, OverflowError) as exc:
        raise Blocked('clock_invalid') from exc


def _read(root, name, limit=MAX_FILE_BYTES):
    path = h.safe_path(root, name)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and before.st_size <= limit, 'unsafe_or_oversize_file')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        opened = os.fstat(fd)
        require((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino), 'file_changed')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(limit + 1)
        after = os.fstat(fd)
        final = h.safe_path(root, name).lstat()
        require(len(raw) <= limit and len(raw) == before.st_size and
            all(getattr(before, k) == getattr(after, k) == getattr(final, k)
                for k in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')), 'file_changed')
        return raw
    finally:
        os.close(fd)


def _pending(root):
    for name in (h.CONTINUITY_PENDING, h.COLLECTION_PENDING):
        require(not h.safe_path(root, name).exists(), 'gosi_reconciliation_required')


class FileSet(MutableMapping):
    """Exact immutable references are read one at a time, never all retained."""
    def __init__(self, root=None, files=None, refs=None):
        self.root, self.files, self.refs = root, dict(files or {}), dict(refs or {})

    def __getitem__(self, name):
        if name in self.files:
            return self.files[name]
        digest, size, commit = self.refs[name]
        if commit is None:
            raw = _read(self.root, name)
        else:
            result = _git(self.root, 'show', commit + ':' + name)
            require(result.returncode == 0, 'base_snapshot_unavailable')
            raw = result.stdout
        require(len(raw) == size and h.sha(raw) == digest, 'base_snapshot_changed')
        return raw

    def __setitem__(self, name, raw):
        self.refs.pop(name, None)
        self.files[name] = raw

    def __delitem__(self, name):
        if name in self.files:
            del self.files[name]
        else:
            del self.refs[name]

    def __iter__(self):
        return iter((*self.files, *self.refs))

    def __len__(self):
        return len(self.files) + len(self.refs)

    def inventory(self):
        result = {name: {'sha256': digest, 'size': size} for name, (digest, size, _) in self.refs.items()}
        result.update({name: {'sha256': h.sha(raw), 'size': len(raw)} for name, raw in self.files.items()})
        return result

    def __eq__(self, other):
        if isinstance(other, FileSet):
            return self.inventory() == other.inventory()
        return isinstance(other, Mapping) and len(self) == len(other) and all(other.get(k) == self[k] for k in self)


def _snapshot(root):
    root, paths, _, _ = scan_history(root, h.HISTORY_PATH)
    refs = {name: (digest, h.safe_path(root, name).stat().st_size, None) for digest, name in paths.items()}
    return FileSet(root, {h.REPORT_PATH: _read(root, h.REPORT_PATH)}, refs)


class History(Mapping):
    def __init__(self, files):
        self.files = files
        self.paths = {HISTORY_FILE.fullmatch(name)[1]: name for name in files if name != h.REPORT_PATH}

    def __getitem__(self, digest):
        return self.files[self.paths[digest]]

    def __iter__(self):
        return iter(self.paths)

    def __len__(self):
        return len(self.paths)


def _history(files):
    return History(files)


def _base_inventory(root, commit):
    listing = _git(root, 'ls-tree', '-r', '-l', '-z', commit, '--', h.HISTORY_PATH)
    require(listing.returncode == 0 and len(listing.stdout) <= 8 * 1024 * 1024, 'base_history_unavailable')
    refs, flat, shards, seen = {}, 0, {}, set()
    for record in listing.stdout.split(b'\0'):
        if not record:
            continue
        meta, path = record.split(b'\t', 1)
        mode, kind, _, size = meta.decode().split()
        name = path.decode()
        match = HISTORY_FILE.fullmatch(name)
        require(match and mode == '100644' and kind == 'blob' and int(size) <= MAX_FILE_BYTES,
                'base_history_path_invalid')
        require(len(refs) < MAX_HISTORY_FILES and match[1] not in seen, 'base_history_duplicate_or_full')
        seen.add(match[1])
        relative = name[len(h.HISTORY_PATH) + 1:]
        if '/' in relative:
            shard = relative.split('/')[0]
            require(shard == match[1][:2], 'base_history_shard_invalid')
            shards[shard] = shards.get(shard, 0) + 1
            require(shards[shard] <= MAX_ENTRIES, 'base_history_shard_full')
        else:
            flat += 1
            require(flat <= MAX_ENTRIES, 'base_history_flat_full')
        refs[name] = (match[1], int(size), commit)
    tree = _git(root, 'rev-parse', commit + ':' + h.HISTORY_PATH)
    tree_sha = tree.stdout.decode().strip() if tree.returncode == 0 else None
    require(tree_sha is not None or not refs, 'base_history_tree_missing')
    return FileSet(root, refs=refs), tree_sha


def _incremental(root, files, commit):
    base, tree_sha = _base_inventory(root, commit)
    # All referenced bytes are checked against Git and the current immutable file.
    require(all(name in files and files[name] == base[name] for name in base), 'base_history_missing_or_changed')
    delta, size = {}, 0
    for name in files:
        if name in base:
            continue
        raw = files[name]
        size += len(raw)
        require(len(delta) < MAX_FILES and size <= MAX_TOTAL_BYTES, 'delta_size_limit')
        delta[name] = raw
    descriptor = {'commit': commit, 'history_tree': tree_sha,
                  'inventory_sha256': h.sha(_bytes(base.inventory())), 'file_count': len(base)}
    return descriptor, delta


def collection_admission(root, *, reserve_bytes):
    """Read-only admission, preserving room for the next bounded publications."""
    require(type(reserve_bytes) is int and reserve_bytes >= 0, 'collection_reserve_invalid')
    files = _snapshot(Path(root).absolute())
    _, delta = _incremental(root, files, _head(root))
    return sum(map(len, delta.values())) + reserve_bytes <= MAX_TOTAL_BYTES


def _document(raw):
    doc = _json(raw)
    h.validate_document(doc)
    now = datetime.now(timezone.utc).timestamp()
    for key in ('provider_stops', 'provider_stop_history'):
        require(isinstance(doc.get(key, []), list), 'stop_list_invalid')
        for event in doc.get(key, []):
            require(isinstance(event, dict) and isinstance(event.get('provider'), str)
                    and bool(event['provider']) and type(event.get('code')) is int
                    and event['code'] in (401, 403, 429)
                    and isinstance(event.get('category'), str), 'stop_invalid')
            require(_epoch(event.get('stopped_at')) <= now, 'future_stop_clock')
    return doc


def _stops_not_lost(before, after):
    now = datetime.now(timezone.utc)
    for stop in before.get('provider_stops', []):
        if h._stop_expired(stop, now):
            continue
        later = [x for x in after.get('provider_stops', []) if x['provider'] == stop['provider']]
        require(any(_epoch(x['stopped_at']) >= _epoch(stop['stopped_at']) for x in later), 'active_provider_stop_loss')


def _validate(files):
    require(h.REPORT_PATH in files and len(files) <= MAX_HISTORY_FILES + 1, 'gosi_missing')
    current = _document(files[h.REPORT_PATH])
    seen = set()
    for name, raw in files.items():
        require(len(raw) <= MAX_FILE_BYTES, 'file_size_limit')
        if name == h.REPORT_PATH:
            continue
        match = HISTORY_FILE.fullmatch(name)
        require(match and h.sha(raw) == match[1] and match[1] not in seen, 'snapshot_identity_invalid')
        if '/' in name[len(h.HISTORY_PATH) + 1:]:
            require(name.split('/')[-2] == match[1][:2], 'snapshot_shard_invalid')
        seen.add(match[1])
        # Immutable history cannot be used to hide a still-active denial.
        _stops_not_lost(_document(raw), current)
    return current


def _nonregression(root, current, incoming):
    old, new = _validate(current), _validate(incoming)
    policy = _json(_read(root, 'config/publish_policy.json'))
    h.replacement_ids(old, new, policy)
    _stops_not_lost(old, new)
    old_history, new_history = _history(current), _history(incoming)
    require(all(new_history.get(key) == raw for key, raw in old_history.items()), 'immutable_history_loss')
    require(current[h.REPORT_PATH] == incoming[h.REPORT_PATH]
            or new_history.get(h.sha(current[h.REPORT_PATH])) == current[h.REPORT_PATH], 'prior_gosi_bytes_missing')


def _exact_head(root, files):
    for name, raw in files.items():
        result = _git(root, 'show', 'HEAD:' + name)
        require(result.returncode == 0 and result.stdout == raw, 'current_not_exact_head')
    tracked = _git(root, 'ls-tree', '-r', '--name-only', 'HEAD', '--', h.HISTORY_PATH)
    require(tracked.returncode == 0, 'head_history_unavailable')
    names = set(tracked.stdout.decode().splitlines())
    require(names == set(files) - {h.REPORT_PATH}, 'head_history_missing')


@contextmanager
def _lock(root):
    path = h.safe_path(root, h.LOCK_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        yield
    finally:
        os.close(fd)
        path.unlink()
        h.sync_dir(path.parent)


def _write_archive(output, files, manifest, *, cap=MAX_ARCHIVE_BYTES):
    manifest_raw = _bytes(manifest)
    require(len(manifest_raw) <= 256 * 1024, 'manifest_size_limit')
    fd, name = tempfile.mkstemp(prefix='.gosi-pack-', dir=output.parent)
    os.close(fd)
    temp = Path(name)
    try:
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(MANIFEST, manifest_raw)
            for path, raw in sorted(files.items()):
                archive.writestr(path, raw)
        require(temp.stat().st_size <= cap, 'archive_size_limit')
        with temp.open('rb') as stream:
            os.fsync(stream.fileno())
        os.replace(temp, output)
        h.sync_dir(output.parent)
    finally:
        temp.unlink(missing_ok=True)


def _recovery_pack(root, output, lineage):
    """Forensics only: never label pending or partial state as restorable."""
    files, errors = {}, []
    def capture(base, path, archive_name):
        try:
            require(len(files) < MAX_FILES, 'recovery_file_limit')
            raw = _read(base, path)
            require(sum(map(len, files.values())) + len(raw) <= MAX_RECOVERY_BYTES, 'recovery_total_limit')
            files[archive_name] = raw
        except (ValueError, OSError):
            errors.append({'path': archive_name, 'reason': 'unavailable_changed_or_over_limit'})
    for name in (h.CONTINUITY_PENDING, h.COLLECTION_PENDING):
        if h.safe_path(root, name).exists():
            capture(root, name, 'recovery/' + name)
    if h.safe_path(root, h.LOCK_PATH).exists():
        capture(root, h.LOCK_PATH, 'recovery/publication-lock')
    capture(root, h.REPORT_PATH, h.REPORT_PATH)
    marker = files.get('recovery/' + h.COLLECTION_PENDING)
    if marker:
        try:
            journal = Path(_json(marker)['journal_dir']).absolute()
            temp_root = Path(os.environ.get('RUNNER_TEMP') or tempfile.gettempdir()).absolute()
            require(journal.name == 'journal' and journal.parent.parent == temp_root
                    and re.fullmatch(r'gosi-runtime-[A-Za-z0-9_-]+', journal.parent.name), 'recovery_journal_scope')
            h.safe_path(temp_root, journal.relative_to(temp_root).as_posix())
            for name in ('header.json', 'baseline.json'):
                capture(journal, name, 'recovery/journal/' + name)
            # Preserve committed STOP events before optional publication copies.
            count = 0
            for entry in journal.iterdir():
                count += 1
                require(count <= 300, 'recovery_journal_entry_limit')
                if re.fullmatch(r'[0-9]{6}\.(?:json|ack)', entry.name):
                    capture(journal, entry.name, 'recovery/journal/' + entry.name)
            publications = h.safe_path(journal, 'publications')
            if publications.is_dir():
                count = 0
                for entry in publications.iterdir():
                    count += 1
                    require(count <= 256, 'recovery_publication_entry_limit')
                    if re.fullmatch(r'[0-9a-f]{32}\.(?:input|receipt)\.json', entry.name):
                        rel = 'publications/' + entry.name
                        capture(journal, rel, 'recovery/journal/' + rel)
        except (ValueError, OSError, KeyError, TypeError):
            errors.append({'path': 'recovery/journal', 'reason': 'journal_missing_invalid_or_incomplete'})
    manifest = {'schema_version': 1, 'lineage': lineage, 'checkout_commit': _head(root), 'state': 'recovery_required',
        'canonical_sha256': h.sha(files[h.REPORT_PATH]) if h.REPORT_PATH in files else None,
        'recovery_errors': errors,
        'files': {k: {'sha256': h.sha(v), 'size': len(v)} for k, v in files.items()}}
    _write_archive(output, files, manifest, cap=MAX_WIRE_BYTES)
    return {'status': 'packed_recovery_required', 'lineage': lineage,
            'file_count': len(files), 'recovery_error_count': len(errors)}


def pack(root, output, *, repository, run_id, run_attempt, commit):
    root, output = Path(root).absolute(), Path(output).absolute()
    lineage = _lineage(repository, run_id, run_attempt, commit)
    _checkout_binding(root, commit, _head(root))
    require(root not in output.parents, 'archive_must_be_outside_checkout')
    # Validate all ancestors and preserve no symlink output route.
    h.safe_path(output.parent, output.name)
    output.parent.mkdir(parents=True, exist_ok=True)
    if any(h.safe_path(root, name).exists() for name in (h.CONTINUITY_PENDING, h.COLLECTION_PENDING)):
        # Forensics cannot authorize collection or a verified restore. It may
        # preserve an interrupted restore before any continuity proof existed.
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            require(all(os.environ.get(env) == value for env, value in (
                ('GITHUB_REPOSITORY', repository), ('GITHUB_RUN_ID', str(run_id)),
                ('GITHUB_RUN_ATTEMPT', str(run_attempt)), ('GITHUB_SHA', commit))), 'recovery_run_binding_invalid')
        return _recovery_pack(root, output, lineage)
    h.require_continuity(root)
    with _lock(root):
        _pending(root)
        files = _snapshot(root)
        _validate(files)
        base, delta = _incremental(root, files, _head(root))
        manifest = {'schema_version': 1, 'lineage': lineage, 'checkout_commit': _head(root), 'base': base,
            'coverage': _pack_coverage(root, lineage),
            'files': {name: {'sha256': h.sha(raw), 'size': len(raw)} for name, raw in delta.items()}}
        require(_snapshot(root) == files, 'gosi_changed_during_pack')
        _write_archive(output, delta, manifest)
    return {'status': 'packed', 'lineage': lineage, 'file_count': len(delta), 'base_file_count': base['file_count']}


def _archive(raw, expected, *, root=None, workflow_path=None):
    require(len(raw) <= MAX_WIRE_BYTES, 'archive_size_limit')
    files, total = {}, 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries) <= MAX_FILES + 1 and len({x.filename for x in entries}) == len(entries), 'archive_members_invalid')
        for entry in entries:
            name = entry.filename
            require(name in (MANIFEST, h.REPORT_PATH) or HISTORY_FILE.fullmatch(name)
                    or RECOVERY_FILE.fullmatch(name), 'archive_path_denied')
            mode = entry.external_attr >> 16
            limit = 256 * 1024 if name == MANIFEST else MAX_FILE_BYTES
            require(not entry.is_dir() and stat.S_IFMT(mode) in (0, stat.S_IFREG)
                    and not entry.flag_bits & 1 and not entry.external_attr & 0x400
                    and entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    and entry.file_size <= limit, 'archive_entry_unsafe')
            total += entry.file_size
            require(total <= MAX_RECOVERY_BYTES + 256 * 1024, 'archive_total_limit')
            with archive.open(entry) as stream:
                data = stream.read(limit + 1)
            require(len(data) == entry.file_size and len(data) <= limit, 'archive_entry_size_mismatch')
            files[name] = data
    require(MANIFEST in files, 'archive_manifest_missing')
    manifest = _json(files.pop(MANIFEST))
    if isinstance(manifest, dict) and manifest.get('state') == 'recovery_required':
        require(manifest.get('lineage') == expected and manifest.get('files') ==
                {k: {'sha256': h.sha(v), 'size': len(v)} for k, v in files.items()}, 'recovery_archive_mismatch')
        raise Blocked('recovery_required_checkpoint_not_restorable')
    require(isinstance(manifest, dict) and set(manifest) == {'schema_version', 'lineage', 'checkout_commit', 'base', 'coverage', 'files'}
            and type(manifest['schema_version']) is int and manifest['schema_version'] == 1
            and manifest['lineage'] == expected, 'archive_lineage_mismatch')
    require(manifest['files'] == {k: {'sha256': h.sha(v), 'size': len(v)} for k, v in files.items()}, 'archive_manifest_mismatch')
    coverage = _coverage(manifest['coverage'])
    own = coverage.get(str(expected['run_id']))
    require(own is not None and own[0] == int(expected['run_attempt']) and own[2] == expected['commit']
            and (workflow_path is None or WORKFLOW_ORDER[own[1]] == workflow_path), 'coverage_producer_binding_invalid')
    require(sum(map(len, files.values())) <= MAX_TOTAL_BYTES, 'delta_size_limit')
    checkout = manifest['checkout_commit']
    descriptor = manifest['base']
    require(isinstance(descriptor, dict) and set(descriptor) == {'commit', 'history_tree', 'inventory_sha256', 'file_count'}
            and descriptor['commit'] == checkout, 'base_descriptor_invalid')
    if root is None:
        require(checkout == expected['commit'] and descriptor == {'commit': checkout,
                'history_tree': None, 'inventory_sha256': h.sha(_bytes({})), 'file_count': 0}, 'base_checkout_required')
        combined = FileSet(files=files)
    else:
        _checkout_binding(root, expected['commit'], checkout)
        base, tree_sha = _base_inventory(root, checkout)
        require(descriptor == {'commit': checkout, 'history_tree': tree_sha,
                'inventory_sha256': h.sha(_bytes(base.inventory())), 'file_count': len(base)}, 'base_inventory_mismatch')
        require(not set(base) & set(files), 'base_delta_duplicate')
        combined = FileSet(root, files, base.refs)
    _validate(combined)
    combined.coverage = coverage
    return combined


def _proof(root, current, *, run_id, run_attempt, source, event_commit=None, coverage=None, workflow_path=None):
    proof = dict(schema_version=1, repository=REPOSITORY, run_id=str(run_id),
        run_attempt=str(run_attempt), head=_head(root), event_sha=event_commit or _head(root),
        baseline_sha256=h.sha(current[h.REPORT_PATH]), source=source,
        coverage=_coverage(coverage or {}), workflow_path=workflow_path or WORKFLOW_ORDER[0])
    h.atomic_write(root, h.CONTINUITY_PROOF, _bytes(proof))


def _begin_restore(root, run_id, run_attempt):
    _pending(root)
    marker = {'token': uuid.uuid4().hex, 'run_id': str(run_id), 'run_attempt': str(run_attempt),
              'phase': 'authenticate_history'}
    path = h.safe_path(root, h.CONTINUITY_PENDING)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(_bytes(marker))
        stream.flush()
        os.fsync(stream.fileno())
    h.sync_dir(root)
    return marker['token']


def _finish_restore(root):
    h.safe_path(root, h.CONTINUITY_PENDING).unlink()
    h.sync_dir(root)


def restore_files(root, incoming, *, lineage, run_id, run_attempt, pending_token=None, event_commit=None,
                  coverage=None, workflow_path=None):
    root = Path(root).absolute()
    if pending_token is None:
        pending_token = _begin_restore(root, run_id, run_attempt)
    marker_value = _json(_read(root, h.CONTINUITY_PENDING))
    require(marker_value.get('token') == pending_token and marker_value.get('run_id') == str(run_id)
            and marker_value.get('run_attempt') == str(run_attempt)
            and not h.safe_path(root, h.COLLECTION_PENDING).exists(), 'restore_marker_mismatch')
    _validate(incoming)
    current = _snapshot(root)
    _validate(current)
    _exact_head(root, current)
    try:
        _nonregression(root, current, incoming)
    except ValueError:
        _nonregression(root, incoming, current)
        _proof(root, current, run_id=run_id, run_attempt=run_attempt, source=lineage, event_commit=event_commit,
               coverage=coverage, workflow_path=workflow_path)
        _finish_restore(root)
        return 'artifact_already_preserved_in_exact_head'
    if current == incoming:
        _proof(root, current, run_id=run_id, run_attempt=run_attempt, source=lineage, event_commit=event_commit,
               coverage=coverage, workflow_path=workflow_path)
        _finish_restore(root)
        return 'unchanged'
    # Marker is outside canonical evidence and is never auto-deleted on failure.
    h.atomic_write(root, h.CONTINUITY_PENDING, _bytes(dict(marker_value, phase='restore_files',
        lineage=lineage, before_sha256=h.sha(current[h.REPORT_PATH]), incoming_sha256=h.sha(incoming[h.REPORT_PATH]))))
    with _lock(root):
        require(_snapshot(root) == current, 'current_changed')
        existing = _history(current)
        retained = {key: raw for key, raw in _history(incoming).items() if key not in existing}
        require(sum(map(len, retained.values())) <= MAX_TOTAL_BYTES, 'restore_delta_size_limit')
        retained[h.sha(current[h.REPORT_PATH])] = current[h.REPORT_PATH]
        retained[h.sha(incoming[h.REPORT_PATH])] = incoming[h.REPORT_PATH]
        retain_snapshots(root, h.HISTORY_PATH, retained)
    # Publisher owns its existing lock and rebuilds only the GOSI manifest entry.
    h.publish_observation(root, _document(incoming[h.REPORT_PATH]))
    after = _snapshot(root)
    _nonregression(root, incoming, after)
    require(_document(after[h.REPORT_PATH]) == _document(incoming[h.REPORT_PATH]), 'restored_document_mismatch')
    _proof(root, after, run_id=run_id, run_attempt=run_attempt, source=lineage, event_commit=event_commit,
           coverage=coverage, workflow_path=workflow_path)
    _finish_restore(root)
    return 'authenticated_gosi_restored'


def _outer(raw):
    require(len(raw) <= MAX_WIRE_BYTES + 1024 * 1024, 'outer_archive_size_limit')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries) == 1, 'outer_members_invalid')
        entry = entries[0]
        require(entry.filename == 'gosi-safety.zip' and not entry.is_dir()
                and stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG)
                and not entry.flag_bits & 1 and entry.file_size <= MAX_WIRE_BYTES,
                'outer_member_invalid')
        with archive.open(entry) as stream:
            data = stream.read(MAX_WIRE_BYTES + 1)
        require(len(data) == entry.file_size, 'outer_size_mismatch')
        return data


def _artifact_payload(root, artifact, *, run_id, attempt, commit, workflow, fetch_bytes):
    require(isinstance(artifact, dict) and artifact.get('name') == f'gosi-safety-{run_id}-{attempt}'
            and artifact.get('expired') is False, 'latest_gosi_artifact_missing_or_ambiguous')
    metadata = artifact.get('workflow_run') or {}
    require(metadata.get('id') == run_id and metadata.get('head_sha') == commit
            and metadata.get('head_branch') == 'main', 'artifact_run_binding_invalid')
    identity = artifact.get('id')
    require(type(identity) is int and identity > 0, 'artifact_identity_invalid')
    url = BASE + f'artifacts/{identity}/zip'
    require(artifact.get('archive_download_url') == url, 'artifact_download_scope_invalid')
    digest = artifact.get('digest', '')
    require(isinstance(digest, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', digest), 'authenticated_digest_missing')
    raw = fetch_bytes(url)
    require(hashlib.sha256(raw).hexdigest() == digest.split(':')[1], 'artifact_digest_mismatch')
    lineage = _lineage(REPOSITORY, run_id, attempt, commit)
    incoming = _archive(_outer(raw), lineage, root=root, workflow_path=workflow)
    return lineage, incoming


def _coverage_seed(root, fetch_json, fetch_bytes):
    # A seed only bounds already-authenticated history. It is never a fallback
    # for a newer missing/failed checkpoint: all uncovered attempts are inspected.
    inspected = 0
    for page in range(1, MAX_SEED_PAGES + 1):
        payload = fetch_json(BASE + f'artifacts?per_page=100&page={page}')
        require(isinstance(payload, dict) and type(payload.get('total_count')) is int
                and isinstance(payload.get('artifacts'), list) and len(payload['artifacts']) <= 100,
                'artifact_catalog_unavailable')
        for artifact in payload['artifacts']:
            require(isinstance(artifact, dict), 'artifact_catalog_invalid')
            match = re.fullmatch(r'gosi-safety-([1-9][0-9]{0,19})-([1-9][0-9]{0,19})', str(artifact.get('name', '')))
            if not match or artifact.get('expired') is True:
                continue
            require(inspected < MAX_SEED_ARTIFACTS, 'coverage_seed_budget_exhausted')
            inspected += 1
            run_id, attempt = map(int, match.groups())
            value = fetch_json(BASE + f'runs/{run_id}/attempts/{attempt}')
            require(isinstance(value, dict) and value.get('id') == run_id and value.get('run_attempt') == attempt
                    and value.get('path') in WORKFLOWS and value.get('head_branch') == 'main'
                    and (value.get('head_repository') or {}).get('full_name') == REPOSITORY,
                    'coverage_seed_run_invalid')
            require(value.get('status') == 'completed', 'coverage_seed_run_unresolved')
            bound = fetch_json(BASE + f'runs/{run_id}/artifacts?per_page=100')
            require(isinstance(bound, dict) and type(bound.get('total_count')) is int
                    and isinstance(bound.get('artifacts'), list)
                    and bound['total_count'] == len(bound['artifacts']) <= 100, 'artifact_history_incomplete')
            matches = [row for row in bound['artifacts'] if isinstance(row, dict)
                       and row.get('name') == artifact.get('name')]
            require(len(matches) == 1 and all(matches[0].get(key) == artifact.get(key) for key in
                    ('id', 'name', 'expired', 'digest', 'archive_download_url', 'workflow_run')),
                    'coverage_seed_artifact_ambiguous_or_changed')
            lineage, incoming = _artifact_payload(root, artifact, run_id=run_id, attempt=attempt,
                commit=value.get('head_sha'), workflow=value['path'], fetch_bytes=fetch_bytes)
            jobs = fetch_json(BASE + f'runs/{run_id}/attempts/{attempt}/jobs?per_page=100')
            require(isinstance(jobs, dict) and type(jobs.get('total_count')) is int
                    and isinstance(jobs.get('jobs'), list) and 0 < jobs['total_count'] == len(jobs['jobs']) <= 100,
                    'coverage_seed_jobs_incomplete')
            ended = max(_epoch(job.get('completed_at')) for job in jobs['jobs'])
            return incoming.coverage, (ended, run_id, attempt, lineage['commit']), lineage, incoming
        if page * 100 >= payload['total_count']:
            break
        require(payload['artifacts'], 'artifact_catalog_incomplete')
    raise Blocked('activation_baseline_unverified_manual_reconciliation_required')


def _run_listing(fetch_json):
    """Complete bounded workflow listing; creation time is never a filter."""
    rows = []
    for workflow in sorted(WORKFLOWS):
        found, total = [], None
        for page in range(1, MAX_RUNS // 100 + 1):
            url = BASE + 'workflows/' + workflow.rsplit('/', 1)[1] + '/runs?per_page=100&page=' + str(page)
            payload = fetch_json(url)
            require(isinstance(payload, dict) and type(payload.get('total_count')) is int
                    and isinstance(payload.get('workflow_runs'), list), 'run_history_unavailable')
            if total is None:
                total = payload['total_count']
            require(payload['total_count'] == total and 0 <= total <= MAX_RUNS, 'run_history_incomplete_or_changed')
            require(len(payload['workflow_runs']) <= 100, 'run_page_limit')
            found.extend(payload['workflow_runs'])
            require(len(found) <= total, 'run_history_duplicate')
            if len(found) == total:
                break
            require(payload['workflow_runs'], 'run_history_incomplete')
        require(len(found) == total and len({r.get('id') for r in found if isinstance(r, dict)}) == total,
                'run_history_incomplete')
        require(all(isinstance(r, dict) and r.get('path') == workflow for r in found), 'workflow_history_mismatch')
        rows.extend(found)
    require(len({r['id'] for r in rows}) == len(rows), 'run_history_duplicate')
    return rows


def _run_fingerprint(rows):
    fields = ('id', 'run_attempt', 'path', 'head_branch', 'head_repository', 'head_sha',
              'status', 'conclusion', 'created_at', 'run_started_at', 'updated_at')
    return h.sha(_bytes([{key: run.get(key) for key in fields} for run in sorted(rows, key=lambda r: r['id'])]))


def _runs(root, fetch_json, current_run_id, current_attempt, *, coverage=None, seed=None):
    # Full metadata discovery catches old run IDs with new attempts. Covered
    # history skips only detailed jobs, never listing or the final stable check.
    rows, details = _run_listing(fetch_json), 0
    fingerprint = _run_fingerprint(rows)
    def detail(url):
        nonlocal details
        require(details < MAX_DETAIL_CALLS, 'attempt_detail_budget_exhausted')
        details += 1
        return fetch_json(url)
    coverage = dict(_coverage(coverage or {}))
    by_id = {str(run['id']): run for run in rows}
    for identity, covered in coverage.items():
        run = by_id.get(identity)
        require(run is not None and run.get('head_branch') == 'main'
                and (run.get('head_repository') or {}).get('full_name') == REPOSITORY
                and run.get('path') == WORKFLOW_ORDER[covered[1]] and run.get('head_sha') == covered[2]
                and type(run.get('run_attempt')) is int and run['run_attempt'] >= covered[0],
                'covered_history_missing_or_regressed')
        require(identity != str(current_run_id) or covered[0] < int(current_attempt), 'coverage_current_attempt_invalid')
    attempts = [seed] if seed is not None else []
    for run in rows:
        if run.get('head_branch') != 'main':
            continue
        require((run.get('head_repository') or {}).get('full_name') == REPOSITORY, 'run_repository_mismatch')
        require(type(run.get('id')) is int and type(run.get('run_attempt')) is int
                and 1 <= run['run_attempt'] <= MAX_ATTEMPTS, 'run_identity_invalid')
        commit = run.get('head_sha', '')
        require(isinstance(commit, str) and re.fullmatch(r'[0-9a-f]{40}', commit), 'run_commit_invalid')
        covered = coverage.get(str(run['id']), [0])[0]
        if covered == run['run_attempt']:
            require(run.get('status') == 'completed', 'covered_attempt_still_active')
        for number in range(covered + 1, run['run_attempt'] + 1):
            if str(run['id']) == str(current_run_id) and number >= int(current_attempt):
                continue
            value = run if number == run['run_attempt'] else detail(BASE + f"runs/{run['id']}/attempts/{number}")
            require(isinstance(value, dict) and value.get('id') == run['id'] and value.get('run_attempt') == number
                    and value.get('head_sha') == commit and value.get('path') == run['path']
                    and value.get('head_branch') == 'main', 'attempt_identity_mismatch')
            jobs = detail(BASE + f"runs/{run['id']}/attempts/{number}/jobs?per_page=100")
            require(isinstance(jobs, dict) and type(jobs.get('total_count')) is int
                    and isinstance(jobs.get('jobs'), list) and jobs['total_count'] == len(jobs['jobs'])
                    and jobs['total_count'] <= 100, 'job_history_incomplete')
            # A queued successor behind main-publish has not executed. An active
            # or unresolved attempt with any job is conservatively a hold.
            if not jobs['jobs'] and value.get('status') in ('queued', 'pending', 'waiting', 'requested'):
                continue
            record = [number, WORKFLOW_ORDER.index(run['path']), commit]
            if not jobs['jobs'] and value.get('status') == 'completed' and value.get('conclusion') == 'cancelled':
                coverage[str(run['id'])] = record
                continue
            require(value.get('status') == 'completed', 'prior_source_run_still_active')
            require(jobs['jobs'], 'executed_run_jobs_missing')
            require(not _git(root, 'merge-base', '--is-ancestor', commit, 'HEAD').returncode, 'run_not_head_ancestor')
            ended = max(_epoch(job.get('completed_at')) for job in jobs['jobs'])
            require(seed is None or ended > seed[0], 'uncovered_precheckpoint_execution')
            attempts.append((ended, run['id'], number, commit))
            coverage[str(run['id'])] = record
    return sorted(attempts, reverse=True), coverage, fingerprint


def restore_latest(root, *, fetch_json=fetch_github_json, fetch_bytes=fetch_artifact_bytes,
                   current_run_id, current_attempt):
    root = Path(root).absolute()
    pending_token = _begin_restore(root, current_run_id, current_attempt)
    current = _snapshot(root)
    _validate(current)
    _exact_head(root, current)
    _lineage(REPOSITORY, current_run_id, current_attempt, _head(root))
    caller = fetch_json(BASE + f'runs/{current_run_id}/attempts/{current_attempt}')
    require(isinstance(caller, dict) and str(caller.get('id')) == str(current_run_id)
            and str(caller.get('run_attempt')) == str(current_attempt)
            and caller.get('path') in WORKFLOWS
            and caller.get('head_branch') == 'main'
            and (caller.get('head_repository') or {}).get('full_name') == REPOSITORY,
            'current_run_identity_invalid')
    event_commit = caller.get('head_sha')
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        require(event_commit == os.environ.get('GITHUB_SHA'), 'event_sha_identity_mismatch')
    _checkout_binding(root, event_commit, _head(root))
    covered, seed, seed_lineage, seed_files = _coverage_seed(root, fetch_json, fetch_bytes)
    candidates, coverage, fingerprint = _runs(root, fetch_json, current_run_id, current_attempt, coverage=covered, seed=seed)
    # Exact HEAD does not prove that a failed pre-activation runner observed no
    # denial. Initial admission needs separately reviewed continuity evidence;
    # this preventive change does not authorize or fabricate such a bootstrap.
    require(candidates, 'activation_baseline_unverified_manual_reconciliation_required')
    _, run_id, attempt, commit = candidates[0]
    if (run_id, attempt, commit) == (seed[1], seed[2], seed[3]):
        lineage, incoming = seed_lineage, seed_files
    else:
        payload = fetch_json(BASE + f'runs/{run_id}/artifacts?per_page=100')
        require(isinstance(payload, dict) and type(payload.get('total_count')) is int
                and isinstance(payload.get('artifacts'), list)
                and payload['total_count'] == len(payload['artifacts']) <= 100, 'artifact_history_incomplete')
        matches = [a for a in payload['artifacts'] if isinstance(a, dict)
                   and a.get('name') == f'gosi-safety-{run_id}-{attempt}']
        require(len(matches) == 1, 'latest_gosi_artifact_missing_or_ambiguous')
        workflow = WORKFLOW_ORDER[coverage[str(run_id)][1]]
        lineage, incoming = _artifact_payload(root, matches[0], run_id=run_id, attempt=attempt,
                                             commit=commit, workflow=workflow, fetch_bytes=fetch_bytes)
        # A later checkpoint must not delete or regress any authenticated coverage.
        require(all(identity in incoming.coverage and incoming.coverage[identity][1:] == row[1:]
                    and incoming.coverage[identity][0] >= row[0] for identity, row in coverage.items()),
                'checkpoint_coverage_regressed')
    require(_run_fingerprint(_run_listing(fetch_json)) == fingerprint, 'run_history_changed_during_restore')
    status = restore_files(root, incoming, lineage=lineage, run_id=current_run_id, run_attempt=current_attempt,
                           pending_token=pending_token, event_commit=event_commit,
                           coverage=coverage, workflow_path=caller['path'])
    return {'status': status, 'source_run_id': run_id, 'source_run_attempt': attempt}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    restore = commands.add_parser('restore')
    restore.add_argument('--root', type=Path, default=ROOT)
    check = commands.add_parser('verify-current')
    check.add_argument('--root', type=Path, default=ROOT)
    bundle = commands.add_parser('pack')
    bundle.add_argument('--root', type=Path, default=ROOT)
    bundle.add_argument('--output', type=Path, required=True)
    for key in ('repository', 'run-id', 'run-attempt', 'commit'):
        bundle.add_argument('--' + key, required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop('command')
    try:
        if command == 'pack':
            result = pack(**args)
        elif command == 'verify-current':
            h.require_continuity(args['root'])
            _validate(_snapshot(args['root']))
            result = {'status': 'verified_current'}
        else:
            require(os.environ.get('GITHUB_ACTIONS') == 'true'
                    and os.environ.get('GITHUB_REPOSITORY') == REPOSITORY, 'authenticated_runner_required')
            result = restore_latest(args['root'], current_run_id=os.environ['GITHUB_RUN_ID'],
                                    current_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
            output = os.environ.get('GITHUB_OUTPUT')
            if output:
                with open(output, 'a', encoding='utf-8') as stream:
                    stream.write('gosi_continuity=verified\n')
        print('GOSI_SAFETY_OK ' + json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError, OverflowError,
            RecursionError, zipfile.BadZipFile, subprocess.SubprocessError):
        print('GOSI_SAFETY_BLOCKED authenticated_history_or_reconciliation_required')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
