"""Bounded LOCAL-ONLY evidence vault; no providers, publication or source edits.

Wrap commands in execution(root, task=..., team=..., operation=...). load_json
returns JSON decoded from hash-verified vault bytes. record_output binds stored
output to exact inputs consumed in that invocation. Analysis is not approval.
Repository owners must exclude /obsidian/JARVIS_LUNA/BrainRuntime/ BEFORE writes.
BrainRuntime is distinct from the tracked public Brain; never edit public Brain.
Only explicit test_namespace(root) permits non-Git OS-temp fixtures.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
import uuid

BRAIN = Path('obsidian/JARVIS_LUNA/BrainRuntime')
MAX_BYTES = 16 * 1024 * 1024
MAX_DERIVED_GRAPH_BYTES = 32 * 1024 * 1024

def source_byte_limit(relative):
    """Only the durable derived operations graph gets a larger source bound."""
    return (MAX_DERIVED_GRAPH_BYTES if str(relative).replace("\\", "/").lower()
            == "data/operations/knowledge_graph.json" else MAX_BYTES)
MAX_SCAN_FILES = 10000
TRANSITION_WAIT_SECONDS = 1.0
TRANSITION_POLL_SECONDS = 0.05
DATASET_INDEX = 'data/agents/brain_dataset_index.json'
_ACTIVE = ContextVar('brain_execution', default=None)
_TEST_ROOTS = ContextVar('brain_test_roots', default=frozenset())
_TIMESTAMP_KEYS = ('observed_at', 'collected_at', 'generated_at', 'updated_at',
                   'fetched_at', 'checked_at', 'timestamp', 'source_updated_at')
_ROOT_JSON = frozenset({'dashboard_runtime.json', 'cumulative_products.json'})
_SECRET_KEYS = re.compile(r'(?:^|_)(?:password|passwd|secret|token|api_key|authorization|cookie|private_key|client_secret)(?:$|_)', re.I)
_SECRET_BYTES = re.compile(rb'(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{30,}|Bearer\s+[A-Za-z0-9_.-]{12,})')


class BrainError(ValueError):
    """Safe codes only: never include credentials, raw payload or raw paths."""


class IntegrityError(BrainError):
    pass


class PathExcluded(BrainError):
    pass


class ArtifactParseError(BrainError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _no_links(target):
    for item in [*reversed(target.parents), target]:
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise PathExcluded('excluded_link_or_reparse_path')


def _root(root):
    value = Path(os.path.abspath(root))
    _no_links(value)
    if not value.is_dir():
        raise BrainError('root_directory_required')
    return value


def _safe(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise PathExcluded('excluded_path_escape')
    target = root / relative
    _no_links(target)
    return target


def _source_path(path, root, extensions):
    raw = Path(path)
    target = Path(os.path.abspath(raw if raw.is_absolute() else root / raw))
    try:
        rel = target.relative_to(root)
    except ValueError:
        raise PathExcluded('excluded_path_escape') from None
    if '..' in raw.parts:
        raise PathExcluded('excluded_path_escape')
    lower = rel.as_posix().lower()
    if _SECRET_BYTES.search(rel.as_posix().encode('utf-8')):
        raise PathExcluded('excluded_credential_path')
    parts = [p.lower() for p in rel.parts]
    # Shopify execution/planning records include authority bindings. Keep them
    # on their existing security path, never archive or count them as consumed.
    if lower == 'data/shopify_action_queue.json':
        raise PathExcluded('excluded_authorization_plan_path')
    if (lower == 'data/operations/state.json' or lower.startswith('data/operations/state/')
            or any(p.startswith('.') for p in parts) or 'manual' in parts
            or any(x in lower for x in ('mocra_profile', 'safety_checkpoint',
                'safetycheck', 'typesafe', 'credential', 'secret', 'token',
                'execution_context', 'execution-ledger', 'auth', 'password'))):
        raise PathExcluded('excluded_private_or_auth_path')
    if not ((parts and parts[0] == 'data') or lower in _ROOT_JSON):
        raise PathExcluded('excluded_unsupported_input_path')
    if target.suffix.lower() not in extensions:
        raise PathExcluded('excluded_unsupported_format')
    _no_links(target)
    return target, rel.as_posix()


def _git(root, *args):
    try:
        # Ambient Git variables must not hide ancestors or redirect this repo.
        environment = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
        # These are read-only checks. Disable optional index refresh writes
        # explicitly, rather than inheriting any Git environment overrides.
        environment['GIT_OPTIONAL_LOCKS'] = '0'
        return subprocess.run(['git', '-C', str(root), *args], env=environment,
                              capture_output=True, check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        raise BrainError('git_exclusion_verification_unavailable') from None


def _full_exclusion(root):
    repo = _git(root, 'rev-parse', '--show-toplevel')
    if repo.returncode:
        if root in _TEST_ROOTS.get():
            return
        raise BrainError('git_repository_or_explicit_test_namespace_required')
    relative = BRAIN.as_posix()
    tracked = _git(root, 'ls-files', '--', relative)
    if tracked.returncode or tracked.stdout.strip():
        raise BrainError('brain_must_be_untracked_and_git_excluded')
    for probe in (relative + '/', relative + '/payloads/00/probe.bin',
                  relative + '/nodes/00/probe.json', relative + '/notes/00/probe.md'):
        if _git(root, 'check-ignore', '--no-index', '-q', '--', probe).returncode:
            raise BrainError('brain_git_exclusion_required_before_write')
    return Path(os.fsdecode(repo.stdout).strip()).resolve()


def _policy_fingerprint(paths):
    """Cheap ordinary Git-change detection, never a directory/tree scan.

    Index is fingerprinted by identity/size/mtime/ctime: ordinary Git updates
    atomically replace it. Small policy files also have exact-byte hashes.
    A hostile filesystem capable of restoring all metadata is out of scope.
    """
    result = []
    for target in paths:
        _no_links(target)
        try:
            info = target.lstat()
        except FileNotFoundError:
            result.append(None)
            continue
        if target.name.endswith('.lock'):
            raise BrainError('git_policy_transition_in_progress')
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise BrainError('git_policy_file_not_regular')
        stamp = tuple(getattr(info, key) for key in (
            'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
        digest = None
        if target.name != 'index':
            if info.st_size > 1024 * 1024:
                raise BrainError('git_policy_file_limit_exceeded')
            raw, final = _read(target)
            if stamp != tuple(getattr(final, key) for key in (
                    'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')):
                raise BrainError('git_policy_changed_during_verification')
            digest = _sha(raw)
        result.append((stamp, digest))
    return tuple(result)


def _local_namespace_paths(root, top):
    # Caching is restricted to this exact Git root and an explicit full local
    # directory exclusion. Global patterns, wildcards and partial rules never
    # authorize a lease. Worktree/common metadata paths come from Git itself.
    if top != root.resolve():
        return None
    metadata = _git(root, 'rev-parse', '--absolute-git-dir',
                    '--path-format=absolute', '--git-common-dir')
    locations = os.fsdecode(metadata.stdout).strip().splitlines()
    if metadata.returncode or len(locations) != 2:
        return None
    gitdir, common = [Path(item).resolve() for item in locations]
    rule = _git(root, 'check-ignore', '--no-index', '-v', '--', BRAIN.as_posix() + '/')
    match = re.fullmatch(r'(.*):([0-9]+):([^\t]+)\t(.*)',
                         os.fsdecode(rule.stdout).rstrip('\r\n'))
    if rule.returncode or match is None:
        return None
    source, pattern = match[1], match[3]
    expected = BRAIN.as_posix() + '/'
    if pattern not in {expected, '/' + expected}:
        return None
    policy = Path(source)
    if not policy.is_absolute():
        policy = root / policy
    if policy.resolve() not in {(root / '.gitignore').resolve(), (common / 'info/exclude').resolve()}:
        return None
    paths = [root / '.git', root / '.gitignore', root / 'obsidian/.gitignore',
             root / 'obsidian/JARVIS_LUNA/.gitignore', common / 'info/exclude',
             common / 'config', common / 'config.worktree', common / 'packed-refs',
             gitdir / 'HEAD', gitdir / 'index', gitdir / 'config.worktree',
             gitdir / 'index.lock', gitdir / 'HEAD.lock', common / 'config.lock']
    # .git is a directory in ordinary repositories, a pointer file in worktrees.
    if (root / '.git').is_dir():
        paths.remove(root / '.git')
    head, _ = _read(gitdir / 'HEAD')
    if head.startswith(b'ref: '):
        ref = os.fsdecode(head[5:]).strip()
        if not re.fullmatch(r'refs/[A-Za-z0-9_./-]+', ref) or '..' in Path(ref).parts:
            return None
        paths.extend([common / ref, common / (ref + '.lock')])
    return tuple(dict.fromkeys(paths))


def _require_exclusion_once(root, *, force=False):
    run = _ACTIVE.get()
    run = run if run is not None and run.root == root else None
    lease = run.namespace_cache if run else None
    if lease is not None:
        paths, accepted = lease
        current = _policy_fingerprint(paths)
        if current == accepted:
            if not force:
                return
            _full_exclusion(root)
            if _policy_fingerprint(paths) != current:
                run.namespace_cache = None
                raise BrainError('git_policy_changed_during_verification')
            return
        run.namespace_cache = None
    top = _full_exclusion(root)
    if run is None or top is None:
        return  # Explicit non-Git fixture namespaces never receive a lease.
    paths = _local_namespace_paths(root, top)
    if paths is None:
        run.namespace_cache = None
        return
    before = _policy_fingerprint(paths)
    # Bind the full Git verdict to exactly the frozen filesystem state.
    _full_exclusion(root)
    after = _policy_fingerprint(paths)
    if before != after:
        run.namespace_cache = None
        raise BrainError('git_policy_changed_during_verification')
    run.namespace_cache = (paths, after)


def _require_exclusion(root, *, force=False):
    """Briefly wait for ordinary Git transitions, never ignore/remove a lock.

    The one-second waiting budget begins at the first observed lock. No vault
    writes occur inside this retry path. A lock invalidates any invocation lease;
    successful recovery requires fresh full Git checks and stable fingerprints.
    The budget bounds waiting/retry starts, not necessary Git subprocess latency.
    """
    deadline = None
    while True:
        try:
            return _require_exclusion_once(root, force=force)
        except BrainError as error:
            if str(error) != 'git_policy_transition_in_progress':
                raise
            run = _ACTIVE.get()
            if run is not None and run.root == root:
                run.namespace_cache = None
            if deadline is None:
                deadline = time.monotonic() + TRANSITION_WAIT_SECONDS
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(TRANSITION_POLL_SECONDS, remaining))
            if time.monotonic() >= deadline:
                raise
            force = True


@contextmanager
def test_namespace(root):
    """Only explicitly named non-Git temporary fixtures, never a global flag."""
    root = _root(root)
    temporary = Path(tempfile.gettempdir()).resolve()
    if root == temporary or temporary not in root.resolve().parents:
        raise BrainError('test_namespace_requires_temporary_fixture')
    if _git(root, 'rev-parse', '--show-toplevel').returncode == 0:
        raise BrainError('test_namespace_cannot_waive_git_repository')
    token = _TEST_ROOTS.set(_TEST_ROOTS.get() | {root})
    try:
        yield root
    finally:
        _TEST_ROOTS.reset(token)


def _read(target, *, limit=None):
    limit = MAX_BYTES if limit is None else limit
    if not isinstance(limit, int) or not 1 <= limit <= MAX_DERIVED_GRAPH_BYTES:
        raise BrainError("invalid_byte_limit")
    _no_links(target)
    before = target.lstat()
    def regular(info):
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PathExcluded('excluded_nonregular_or_hardlinked_file')
        if info.st_size > limit:
            raise BrainError('byte_limit_exceeded')
    regular(before)
    fd = os.open(target, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as handle:
        opened = os.fstat(handle.fileno())
        regular(opened)
        raw = handle.read(limit + 1)
        after = os.fstat(handle.fileno())
    _no_links(target)
    final = target.lstat()
    regular(final)
    for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns'):
        if len({getattr(i, key) for i in (before, opened, after, final)}) != 1:
            raise IntegrityError('file_changed_during_read')
    if before.st_ctime_ns != final.st_ctime_ns or opened.st_ctime_ns != after.st_ctime_ns:
        raise IntegrityError('file_changed_during_read')
    if len(raw) > limit or len(raw) != final.st_size:
        raise IntegrityError('file_size_mismatch')
    return raw, final


def _verified(root, relative, digest):
    try:
        relative_path = Path(relative)
        payload = relative_path.parts[:len(BRAIN.parts)+1] == (*BRAIN.parts, "payloads")
        raw, _ = _read(_safe(root, relative), limit=MAX_DERIVED_GRAPH_BYTES if payload else MAX_BYTES)
    except FileNotFoundError:
        raise IntegrityError('vault_object_missing') from None
    if _sha(raw) != digest:
        raise IntegrityError('vault_hash_mismatch')
    return raw


def _write_immutable(root, rel, raw):
    _require_exclusion(root)
    digest = _sha(raw)
    target = _safe(root, rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    _safe(root, rel)
    if not target.exists():
        fd, temporary = tempfile.mkstemp(prefix='.brain-', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            _safe(root, rel)
            _require_exclusion(root)
            try:
                os.link(temporary, target)  # Atomic create-if-absent, no overwrite.
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
    if _verified(root, rel, digest) != raw:
        raise IntegrityError('vault_object_changed')
    _require_exclusion(root)
    return digest, rel.as_posix()


def _put(root, category, raw, extension):
    digest = _sha(raw)
    rel = BRAIN / category / digest[:2] / (digest + extension)
    return _write_immutable(root, rel, raw)


def _node(root, value):
    digest, relative = _put(root, 'nodes', _canonical(value), '.json')
    edges = []
    for relation in value.get('relations', []):
        target = relation.get('target')
        kind = relation.get('target_type')
        label = relation.get('type')
        if (not isinstance(target, str) or not re.fullmatch(r'[0-9a-f]{64}', target)
                or not isinstance(label, str) or not re.fullmatch(r'[a-z_]{1,40}', label)):
            raise IntegrityError('invalid_typed_relation')
        if kind == 'payload':
            if relation.get('provenance_sha256') != target:
                raise IntegrityError('typed_relation_provenance_mismatch')
            path = BRAIN / 'payloads' / target[:2] / (target + '.bin')
            _verified(root, path, target)
        elif kind in {'artifact', 'execution', 'decision'}:
            path = BRAIN / 'nodes' / target[:2] / (target + '.json')
            target_node = json.loads(_verified(root, path, target))
            if target_node.get('type') != kind:
                raise IntegrityError('typed_relation_target_mismatch')
            expected = target_node.get('sha256') if kind == 'artifact' else target
            if relation.get('provenance_sha256') != expected:
                raise IntegrityError('typed_relation_provenance_mismatch')
            path = BRAIN / 'notes' / target[:2] / (target + '.md')
            # Alias bytes must be the deterministic rendering of their node.
            _verified(root, path, _sha(_note_bytes(target, target_node, root)))
        else:
            raise IntegrityError('unsupported_typed_relation')
        link = path.relative_to(Path('obsidian/JARVIS_LUNA')).as_posix()
        if path.suffix == '.md':
            link = link[:-3]
        edges.append('- ' + label + ': [[' + link + ']]')
    note = _note_bytes(digest, value, root, edges=edges)
    _write_immutable(root, BRAIN / 'notes' / digest[:2] / (digest + '.md'), note)
    return digest


def _note_bytes(digest, value, root, *, edges=None):
    # Pure deterministic rendering; only explicit, typed, hash-bound relations.
    if edges is None:
        edges = []
        for relation in value.get('relations', []):
            target = relation['target']
            category, suffix = ('payloads', '.bin') if relation['target_type'] == 'payload' else ('notes', '')
            link = 'BrainRuntime/' + category + '/' + target[:2] + '/' + target + suffix
            edges.append('- ' + relation['type'] + ': [[' + link + ']]')
    relative = (BRAIN / 'nodes' / digest[:2] / (digest + '.json')).as_posix()
    return ('---\ntype: ' + value['type'] + '\nid: ' + digest
            + '\nlocal_only: true\n---\n\nEvidence JSON: ' + relative
            + '\n\n' + '\n'.join(edges) + '\n').encode('utf-8')


def _check_secrets(raw, value=None):
    if _SECRET_BYTES.search(raw):
        raise PathExcluded('excluded_credential_content')
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                if _SECRET_KEYS.search(str(key)) and child not in (None, '', False):
                    raise PathExcluded('excluded_credential_field')
                pending.append(child)
        elif isinstance(item, list):
            pending.extend(item)


def _timestamps(value):
    return {key: value[key] for key in _TIMESTAMP_KEYS if key in value} if isinstance(value, dict) else {}


def _snapshot(root, relative, raw, info, value, role):
    _check_secrets(raw, value)
    digest, payload = _put(root, 'payloads', raw, '.bin')
    artifact = {
        'type': 'artifact', 'role': role, 'source_path': relative,
        'source_workspace_id': _sha(os.path.normcase(str(root.resolve())).encode('utf-8')),
        'sha256': digest, 'size_bytes': len(raw), 'source_mtime_ns': info.st_mtime_ns,
        'source_timestamps': _timestamps(value), 'write_at': _now(),
        'payload_path': payload, 'local_only': True,
        'relations': [{'type': 'snapshot_of', 'target': digest, 'target_type': 'payload',
                       'provenance_sha256': digest}],
    }
    return _node(root, artifact), digest, payload


@dataclass
class Execution:
    root: Path
    task: str
    team: str
    operation: str
    invocation: str = field(default_factory=lambda: uuid.uuid4().hex)
    consumed: dict = field(default_factory=dict)
    input_cache: dict = field(default_factory=dict)
    namespace_cache: object = None
    outputs: list = field(default_factory=list)
    excluded: list = field(default_factory=list)
    defaults: list = field(default_factory=list)

    def proof(self):
        return {'input_read_from_vault': bool(self.consumed),
                'output_stored': bool(self.outputs),
                'consumed_source_ids': sorted(self.consumed),
                'output_artifact_ids': list(self.outputs),
                'excluded': list(self.excluded), 'default_reasons': list(self.defaults),
                'business_approval': False, 'local_only': True}


def _label(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,120}', value):
        raise BrainError('bounded_nonsecret_execution_label_required')
    if _SECRET_BYTES.search(value.encode()):
        raise BrainError('credential_execution_label_denied')
    return value


@contextmanager
def execution(root, *, task, team, operation):
    root = _root(root)
    if _ACTIVE.get() is not None:
        raise BrainError('nested_execution_denied')
    run = Execution(root, _label(task), _label(team), _label(operation))
    token = _ACTIVE.set(run)
    try:
        yield run
    finally:
        try:
            if run.namespace_cache is not None:
                _require_exclusion(root, force=True)
        finally:
            _ACTIVE.reset(token)


def _run(root):
    run = _ACTIVE.get()
    if run is not None and run.root != root:
        raise BrainError('execution_root_mismatch')
    return run


def current_execution(root):
    """Current scoped invocation or None; rejects a mismatched root."""
    return _run(_root(root))


def note_exclusion(path, root):
    """Record known path-policy exclusion; never waive integrity/content errors.

    Returns True for supported exclusion categories only. False means the caller
    must use load_json, which can still reject credential content. This is NOT
    permission to publish excluded data. Source values are never read here.
    """
    root = _root(root)
    run = _run(root)
    raw = Path(path)
    target = Path(os.path.abspath(raw if raw.is_absolute() else root / raw))
    if target != root and root not in target.parents:
        raise PathExcluded('excluded_path_escape')
    _no_links(target)
    try:
        info = target.lstat()
    except FileNotFoundError:
        info = None
    if info is not None and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
        raise PathExcluded('excluded_nonregular_or_hardlinked_file')
    try:
        _source_path(path, root, {'.json'})
    except PathExcluded as error:
        if str(error) not in {'excluded_private_or_auth_path', 'excluded_authorization_plan_path',
                             'excluded_unsupported_input_path', 'excluded_unsupported_format'}:
            raise
        if run:
            run.excluded.append(str(error))
        return True
    return False


def _parse_artifact(raw, suffix):
    """Inspect secrets and parse without ever returning a source-side decode."""
    _check_secrets(raw)
    try:
        text = raw.decode('utf-8-sig')
        def invalid_constant(value):
            raise ValueError('non_json_numeric_constant')
        if suffix == '.json':
            value = json.loads(text, parse_constant=invalid_constant)
            count = len(value) if isinstance(value, (list, dict)) else 1
            unit = 'top_level_entries' if isinstance(value, (list, dict)) else 'scalar'
        elif suffix == '.jsonl':
            value = [json.loads(line, parse_constant=invalid_constant)
                     for line in text.splitlines() if line.strip()]
            count, unit = len(value), 'records'
        elif suffix == '.csv':
            import io
            rows = list(csv.reader(io.StringIO(text, newline=''), strict=True))
            headers = rows[0] if rows else []
            if any(_SECRET_KEYS.search(header) for header in headers):
                raise PathExcluded('excluded_credential_field')
            value = {'columns': headers, 'rows': rows[1:]}
            count, unit = len(value['rows']), 'data_rows'
        else:
            raise PathExcluded('excluded_unsupported_format')
    except PathExcluded:
        raise
    except (ValueError, UnicodeError, csv.Error):
        raise ArtifactParseError('source_invalid_' + suffix.lstrip('.')) from None
    _check_secrets(raw, value)
    return value, count, unit


def _load_artifact(path, root, extensions):
    root = _root(root)
    run = _run(root)
    try:
        source, relative = _source_path(path, root, extensions)
        try:
            raw, info = _read(source, limit=source_byte_limit(relative))
        except FileNotFoundError:
            raise ArtifactParseError('source_missing') from None
        suffix = source.suffix.lower()
        validated, _, _ = _parse_artifact(raw, suffix)
        source_digest = _sha(raw)
        cache_key = (relative, source_digest, info.st_mtime_ns)
        cached = run.input_cache.get(cache_key) if run else None
        if cached is None:
            artifact, digest, payload = _snapshot(root, relative, raw, info, validated, 'input')
        else:
            artifact, digest, payload = cached
            cached_node = json.loads(_verified(
                root, BRAIN / 'nodes' / artifact[:2] / (artifact + '.json'), artifact))
            workspace = _sha(os.path.normcase(str(root.resolve())).encode('utf-8'))
            if (cached_node.get('type') != 'artifact' or cached_node.get('role') != 'input'
                    or cached_node.get('source_path') != relative
                    or cached_node.get('source_workspace_id') != workspace
                    or cached_node.get('sha256') != source_digest
                    or cached_node.get('source_mtime_ns') != info.st_mtime_ns
                    or cached_node.get('payload_path') != payload or digest != source_digest):
                raise IntegrityError('cached_source_binding_mismatch')
        # Cache hits still freshly read the source and verify node AND payload.
        # All exposed values/counts come from the verified vault readback.
        value, count, unit = _parse_artifact(_verified(root, payload, digest), suffix)
        if run:
            run.consumed[artifact] = digest
            run.input_cache[cache_key] = (artifact, digest, payload)
        return {'value': value, 'source_path': relative, 'source_sha256': digest,
                'source_workspace_id': _sha(os.path.normcase(str(root.resolve())).encode('utf-8')),
                'payload_id': digest, 'artifact_id': artifact,
                'parser': suffix.lstrip('.'), 'count': count, 'count_unit': unit,
                'size_bytes': len(raw), 'source_mtime_ns': info.st_mtime_ns,
                'source_timestamps': _timestamps(value), 'input_read_from_vault': True}
    except PathExcluded as error:
        if run:
            run.excluded.append(str(error))
        raise


def load_artifact(path, root):
    """Strict JSON/JSONL/CSV input archive and verified vault-readback decode.

    Returns value plus hash/ID/parser/count metadata. CSV value retains columns
    and ordered rows, including duplicate columns. No default on parse failure,
    credential content, size limits or integrity errors. Source clocks are never
    replaced by a current observation timestamp; full source bytes are retained.
    """
    return _load_artifact(path, root, {'.json', '.jsonl', '.csv'})


def load_json(path, root, default):
    """Retained contract: missing/invalid JSON defaults; security failures raise."""
    try:
        return _load_artifact(path, root, {'.json'})['value']
    except ArtifactParseError as error:
        run = current_execution(root)
        if run:
            run.defaults.append(str(error))
        return default


def require_git_root(root):
    """Require the actual repository top level and private-vault exclusion."""
    root = _root(root)
    result = _git(root, 'rev-parse', '--show-toplevel')
    if result.returncode:
        raise BrainError('actual_git_root_required')
    top = Path(os.fsdecode(result.stdout).strip()).resolve()
    if os.path.normcase(str(root.resolve())) != os.path.normcase(str(top)):
        raise BrainError('actual_git_root_required')
    _require_exclusion(root)
    return root


def verify_consumed(root):
    """Reverify all source node/payload bindings in the active invocation."""
    root = _root(root)
    run = _run(root)
    if run is None:
        raise BrainError('matching_execution_context_required')
    for identifier, source_digest in run.consumed.items():
        source_node = json.loads(_verified(
            root, BRAIN / 'nodes' / identifier[:2] / (identifier + '.json'), identifier))
        if (source_node.get('type') != 'artifact' or source_node.get('role') != 'input'
                or source_node.get('sha256') != source_digest):
            raise IntegrityError('consumed_artifact_binding_mismatch')
        _verified(root, source_node['payload_path'], source_digest)
    return len(run.consumed)


def record_output(path, root, task, team, operation):
    """Snapshot output with this invocation's exact consumed source identities."""
    root = _root(root)
    run = _run(root)
    if run is None or (task, team, operation) != (run.task, run.team, run.operation):
        raise BrainError('matching_execution_context_required')
    if not run.consumed:
        raise BrainError('genuine_consumed_source_required')
    _require_exclusion(root, force=True)
    try:
        source, relative = _source_path(path, root, {'.json', '.jsonl', '.csv'})
        raw, info = _read(source, limit=source_byte_limit(relative))
        value = None
        if source.suffix.lower() == '.json':
            try:
                value = json.loads(raw.decode('utf-8-sig'))
            except (ValueError, UnicodeError):
                raise BrainError('output_invalid_json') from None
        elif source.suffix.lower() == '.jsonl':
            try:
                for line in raw.decode('utf-8-sig').splitlines():
                    if line.strip():
                        _check_secrets(line.encode(), json.loads(line))
            except PathExcluded:
                raise
            except (ValueError, UnicodeError):
                raise BrainError('output_invalid_jsonl') from None
        else:
            try:
                headers = next(csv.reader(raw.decode('utf-8-sig').splitlines()), [])
                if any(_SECRET_KEYS.search(header) for header in headers):
                    raise PathExcluded('excluded_credential_field')
            except UnicodeError:
                raise BrainError('output_invalid_csv') from None
        artifact, digest, payload = _snapshot(root, relative, raw, info, value, 'output')
        _verified(root, payload, digest)
        verify_consumed(root)
        relations = [{'type': 'consumed', 'target': identifier, 'target_type': 'artifact',
                      'provenance_sha256': source_digest}
                     for identifier, source_digest in sorted(run.consumed.items())]
        relations.append({'type': 'generated', 'target': artifact,
                          'target_type': 'artifact', 'provenance_sha256': digest})
        execution_id = _node(root, {
            'type': 'execution', 'invocation': run.invocation, 'task': run.task,
            'team': run.team, 'operation': run.operation, 'write_at': _now(),
            'input_read_from_vault': True, 'output_stored': True,
            'business_approval': False, 'local_only': True, 'relations': relations})
        decision_id = _node(root, {
            'type': 'decision', 'decision_kind': 'analysis_evidence_only',
            'business_approval': False, 'write_at': _now(), 'local_only': True,
            'relations': [{'type': 'evidenced_by', 'target': execution_id,
                           'target_type': 'execution', 'provenance_sha256': execution_id}]})
        _require_exclusion(root, force=True)
        run.outputs.append(artifact)
        return {**run.proof(), 'output_sha256': digest, 'execution_id': execution_id,
                'decision_id': decision_id}
    except PathExcluded as error:
        run.excluded.append(str(error))
        raise


def audit(root):
    """Constant-scope safety audit, deliberately no cold vault-note scan."""
    root = _root(root)
    _require_exclusion(root, force=True)
    real_git = _git(root, 'rev-parse', '--show-toplevel').returncode == 0
    return {'local_only': True, 'git_exclusion_verified': real_git,
            'explicit_test_namespace': not real_git,
            'coverage': 'consumed supported operational sources only',
            'excluded_categories': ['manual', 'private/auth', 'safety_checkpoints',
                                    'typesafe', 'unsupported paths/formats'],
            'cold_note_scan': False, 'business_approval': False}


def scan_public_data(root, *, limit=MAX_SCAN_FILES):
    """Bounded data JSON/CSV/JSONL metadata, no hashing or consumed claim.

    Path filtering does not certify that arbitrary file contents are public.
    Secret inspection occurs before snapshotting, not in this metadata index.
    """
    root = _root(root)
    if not isinstance(limit, int) or not 1 <= limit <= MAX_SCAN_FILES:
        raise BrainError('scan_limit_out_of_bounds')
    records, excluded, visited = [], 0, 0
    excluded_codes = {}
    def exclude(code):
        nonlocal excluded
        excluded += 1
        excluded_codes[code] = excluded_codes.get(code, 0) + 1
    def report(truncated):
        return {'entries': records, 'excluded_count': excluded,
                'excluded_codes': dict(sorted(excluded_codes.items())),
                'excluded_count_unit': 'files_or_pruned_directories',
                'truncated': truncated}
    data = _safe(root, 'data')
    if not data.exists():
        return report(False)
    for directory, dirs, files in os.walk(data, followlinks=False):
        kept = []
        for name in sorted(dirs):
            candidate = Path(directory) / name
            try:
                _source_path(candidate / 'probe.json', root, {'.json'})
                kept.append(name)
            except PathExcluded as error:
                exclude(str(error))
        dirs[:] = kept
        for name in sorted(files):
            if (Path(directory) / name).relative_to(root).as_posix().lower() == DATASET_INDEX:
                exclude('excluded_generated_dataset_index')
                continue
            try:
                candidate, relative = _source_path(Path(directory) / name, root, {'.json', '.csv', '.jsonl'})
                info = candidate.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise PathExcluded('excluded_nonregular_file')
                visited += 1
                if visited > limit:
                    return report(True)
                records.append({'source_path': relative, 'size_bytes': info.st_size,
                                'source_mtime_ns': info.st_mtime_ns, 'consumed': False})
            except PathExcluded as error:
                exclude(str(error))
    records.sort(key=lambda item: item['source_path'])
    return report(False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('audit', 'scan_public_data'))
    parser.add_argument('--root', required=True)
    args = parser.parse_args(argv)
    try:
        result = audit(args.root) if args.command == 'audit' else scan_public_data(args.root)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except BrainError as error:
        print(json.dumps({'blocked': str(error), 'local_only': True}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
