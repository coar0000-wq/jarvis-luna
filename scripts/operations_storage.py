"""Lossless, bounded operations history storage; no trust or validation bypass.

Small/legacy v1 states remain readable. Large states use append-only,
content-addressed immutable maps and retain the original v1 bytes once. All
callers receive the complete logical v1 state before existing validators run.
This module does not perform IO or authorize execution.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re

OPS_STATE_PATH = 'data/operations/state.json'
OPS_STATE_DIRECTORY = 'data/operations/state'
OPS_STATE_MAX_BYTES = 32 * 1024 * 1024
OPS_MEMBER_MAX_BYTES = 8 * 1024 * 1024
OPS_MIGRATION_THRESHOLD = 24 * 1024 * 1024
OPS_SEGMENT_TARGET_BYTES = 1024 * 1024
OPS_LOGICAL_MAX_BYTES = 120 * 1024 * 1024
OPS_STORAGE_MAX_MEMBERS = 8192
OPS_SNAPSHOT_MAX_FILES = 20000
OPS_BASE_TOTAL_BYTES = 96 * 1024 * 1024
STORAGE_KEY = '_operations_storage'
SCOPES = ('events', 'audit.payloads', 'audit.preparations', 'audit.outcomes')
_MEMBER = re.compile(r'data/operations/state/(segment-([0-9a-f]{64})\.json|legacy-([0-9a-f]{64})\.bin)\Z')
_HASH = re.compile(r'[0-9a-f]{64}\Z')


def _sha(body):
    return hashlib.sha256(body).hexdigest()


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def _json(body):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('operations storage duplicate JSON key')
            value[key] = item
        return value
    def finite_float(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError('operations storage nonfinite JSON')
        return value
    return json.loads(body, object_pairs_hook=pairs, parse_float=finite_float,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('operations storage nonfinite JSON')))


def operations_file_max_bytes(relative, ordinary_max_bytes=OPS_MEMBER_MAX_BYTES):
    """Return the state exception only for its exact canonical repository path."""
    return OPS_STATE_MAX_BYTES if relative == OPS_STATE_PATH else ordinary_max_bytes


def operations_snapshot_max_bytes(state_size):
    """Unchanged safety snapshot budget, including every immutable member."""
    return OPS_BASE_TOTAL_BYTES + max(0, state_size - OPS_MEMBER_MAX_BYTES)


def require_operations_state_size(body):
    if not isinstance(body, bytes):
        raise TypeError('operations state must be serialized bytes')
    if len(body) > OPS_STATE_MAX_BYTES:
        raise ValueError('operations state storage capacity reached; pruning/reset forbidden')


def is_operations_state_member(relative):
    return isinstance(relative, str) and _MEMBER.fullmatch(relative) is not None


is_operations_history_path = is_operations_state_member


def validate_operations_state_member(relative, body):
    """Validate an immutable member even if a failed checkpoint orphaned it."""
    match = _MEMBER.fullmatch(relative) if isinstance(relative, str) else None
    if not match or not isinstance(body, bytes) or not 0 < len(body) <= OPS_MEMBER_MAX_BYTES:
        raise ValueError('operations storage member scope/size invalid')
    if _sha(body) != (match.group(2) or match.group(3)):
        raise ValueError('operations storage member hash mismatch')
    if match.group(2):
        segment = _json(body)
        if (not isinstance(segment, dict) or set(segment) != {'schema_version', 'scope', 'previous', 'records'}
                or type(segment['schema_version']) is not int or segment['schema_version'] != 1
                or segment['scope'] not in SCOPES
                or not (segment['previous'] is None or isinstance(segment['previous'], str)
                        and _HASH.fullmatch(segment['previous']))
                or not isinstance(segment['records'], dict) or not segment['records']
                or any(not isinstance(key, str) or not key or not isinstance(value, dict)
                       for key, value in segment['records'].items())
                or _canonical(segment) != body):
            raise ValueError('operations storage segment schema invalid')
        return segment
    return None


def _manifest(body, *, parsed=None):
    require_operations_state_size(body)
    state = _json(body) if parsed is None else parsed
    if not isinstance(state, dict):
        raise ValueError('operations state must be an object')
    if STORAGE_KEY not in state:
        return state, None
    meta = state[STORAGE_KEY]
    if (not isinstance(meta, dict) or set(meta) != {'schema_version', 'segments', 'migration', 'logical_sha256'}
            or type(meta['schema_version']) is not int or meta['schema_version'] != 2
            or not isinstance(meta['logical_sha256'], str) or not _HASH.fullmatch(meta['logical_sha256'])
            or not isinstance(meta['segments'], list) or len(meta['segments']) > OPS_STORAGE_MAX_MEMBERS
            or type(state.get('schema_version')) is not int or state['schema_version'] != 1):
        raise ValueError('operations storage manifest schema invalid')
    previous, paths, total = None, set(), len(body)
    for item in meta['segments']:
        if (not isinstance(item, dict) or set(item) != {'path', 'sha256', 'bytes', 'scope', 'records', 'previous'}
                or not isinstance(item['sha256'], str) or not _HASH.fullmatch(item['sha256'])
                or item['path'] != OPS_STATE_DIRECTORY + '/segment-' + item['sha256'] + '.json'
                or item['scope'] not in SCOPES or item['previous'] != previous
                or type(item['bytes']) is not int or not 0 < item['bytes'] <= OPS_MEMBER_MAX_BYTES
                or type(item['records']) is not int or not 0 < item['records'] <= 1000000
                or item['path'] in paths):
            raise ValueError('operations storage segment reference/order invalid')
        paths.add(item['path'])
        total += item['bytes']
        previous = item['sha256']
    migration = meta['migration']
    if migration is not None:
        if (not isinstance(migration, dict) or set(migration) != {'sha256', 'bytes', 'logical_sha256', 'chunks'}
                or any(not isinstance(migration[k], str) or not _HASH.fullmatch(migration[k])
                       for k in ('sha256', 'logical_sha256'))
                or type(migration['bytes']) is not int or not 0 < migration['bytes'] <= OPS_STATE_MAX_BYTES
                or not isinstance(migration['chunks'], list)
                or len(migration['chunks']) != (migration['bytes'] + OPS_MEMBER_MAX_BYTES - 1) // OPS_MEMBER_MAX_BYTES):
            raise ValueError('operations storage migration schema invalid')
        for index, item in enumerate(migration['chunks']):
            expected_size = min(OPS_MEMBER_MAX_BYTES, migration['bytes'] - index * OPS_MEMBER_MAX_BYTES)
            if (not isinstance(item, dict) or set(item) != {'path', 'sha256', 'bytes', 'index'}
                    or not isinstance(item['sha256'], str) or not _HASH.fullmatch(item['sha256'])
                    or item['path'] != OPS_STATE_DIRECTORY + '/legacy-' + item['sha256'] + '.bin'
                    or type(item['index']) is not int or item['index'] != index
                    or type(item['bytes']) is not int or item['bytes'] != expected_size):
                raise ValueError('operations storage migration chunk/order invalid')
            if item['path'] not in paths:
                paths.add(item['path'])
                total += item['bytes']
    if len(paths) > OPS_STORAGE_MAX_MEMBERS or total > operations_snapshot_max_bytes(len(body)):
        raise ValueError('operations storage aggregate capacity reached; pruning/reset forbidden')
    return state, meta


def operations_state_members(body):
    """Referenced member paths, in stable order, with strict manifest checks."""
    _state, meta = _manifest(body)
    if meta is None:
        return ()
    items = meta['segments'] + (meta['migration']['chunks'] if meta['migration'] else [])
    return tuple(dict.fromkeys(item['path'] for item in items))


def _member(item, read_member, checked=None):
    key = (item['path'], item['sha256'], item['bytes'])
    if checked is not None and key in checked:
        return checked[key]
    if read_member is None:
        raise ValueError('operations storage member reader required')
    try:
        body = read_member(item['path'])
    except (KeyError, FileNotFoundError) as exc:
        raise ValueError('operations storage member missing') from exc
    segment = validate_operations_state_member(item['path'], body)
    if len(body) != item['bytes'] or _sha(body) != item['sha256']:
        raise ValueError('operations storage member reference mismatch')
    if checked is not None:
        checked[key] = (body, segment)
    return body, segment


def _migration_snapshot(meta, read_member, checked_members=None, checked_migrations=None):
    if meta is None or meta['migration'] is None:
        return None, None
    migration = meta['migration']
    key = _canonical(migration)
    if checked_migrations is not None and key in checked_migrations:
        return checked_migrations[key]
    original = b''.join(_member(item, read_member, checked_members)[0] for item in migration['chunks'])
    if len(original) != migration['bytes'] or _sha(original) != migration['sha256']:
        raise ValueError('operations storage migration reconstruction mismatch')
    legacy, reserved = _manifest(original)
    if (reserved is not None or type(legacy.get('schema_version')) is not int or legacy['schema_version'] != 1
            or _sha(_canonical(legacy)) != migration['logical_sha256']):
        raise ValueError('operations storage migration logical mismatch')
    if checked_migrations is not None:
        checked_migrations[key] = (original, legacy)
    return original, legacy


def operations_migration_bytes(body, read_member):
    _state, meta = _manifest(body)
    return _migration_snapshot(meta, read_member)[0]


def _table(state, scope):
    parts = scope.split('.')
    parent = state
    for part in parts[:-1]:
        if part not in parent:
            return None
        parent = parent[part]
        if not isinstance(parent, dict):
            raise ValueError('operations storage immutable table invalid')
    value = parent.get(parts[-1])
    if value is not None and not isinstance(value, dict):
        raise ValueError('operations storage immutable table invalid')
    return value


def _replace_table(state, scope, table):
    parts = scope.split('.')
    parent = state
    for part in parts[:-1]:
        parent = parent[part]
    parent[parts[-1]] = table


def _preserved(old, new):
    for scope in SCOPES:
        before, after = _table(old, scope), _table(new, scope)
        if before is None:
            continue
        if (after is None or not before.keys() <= after.keys()
                or _canonical(before) != _canonical({key: after[key] for key in before})):
            raise ValueError('operations storage immutable history removed or changed')


def _load_parsed_state(state, meta, read_member, checked_members=None, checked_migrations=None):
    if meta is None:
        return state
    state.pop(STORAGE_KEY)
    for scope in SCOPES:
        table = _table(state, scope)
        if table is not None and len(_canonical(table)) > OPS_SEGMENT_TARGET_BYTES:
            raise ValueError('operations storage inline tail capacity reached')
    logical_size = len(_canonical(state))
    for item in meta['segments']:
        raw, segment = _member(item, read_member, checked_members)
        if (segment['scope'] != item['scope'] or segment['previous'] != item['previous']
                or len(segment['records']) != item['records']):
            raise ValueError('operations storage segment metadata mismatch')
        table = _table(state, item['scope'])
        if table is None:
            raise ValueError('operations storage missing immutable table')
        for key, value in segment['records'].items():
            if key in table:
                raise ValueError('operations storage duplicate/conflicting historical record')
            table[key] = value
        logical_size += len(raw)
        if logical_size > OPS_LOGICAL_MAX_BYTES:
            raise ValueError('operations logical state capacity reached; pruning/reset forbidden')
    logical = _canonical(state)
    if len(logical) > OPS_LOGICAL_MAX_BYTES or _sha(logical) != meta['logical_sha256']:
        raise ValueError('operations storage logical digest/capacity mismatch')
    _original, legacy = _migration_snapshot(meta, read_member, checked_members, checked_migrations)
    if legacy is not None:
        _preserved(legacy, state)
    return state


def load_operations_state(body, read_member=None):
    """Reconstruct and integrity-check ALL history; callers still validate it."""
    state, meta = _manifest(body)
    return _load_parsed_state(state, meta, read_member)


def operations_state_from_files(files):
    return load_operations_state(files[OPS_STATE_PATH], files.__getitem__)


def prepare_operations_state(state, previous_body=None, read_member=None, *, force=False):
    """Return ONLY new immutable files and state.json, without filesystem writes.

    Callers must create/fsync immutable members first and replace/fsync state
    last. Old members are never rewritten or removed, including valid orphans.
    """
    if not isinstance(state, dict) or STORAGE_KEY in state:
        raise ValueError('operations storage requires full logical state')
    logical = _canonical(state)
    prior, meta = (None, None) if previous_body is None else _manifest(previous_body)
    if meta is None and not force and len(logical) < OPS_MIGRATION_THRESHOLD:
        if prior is not None:
            _preserved(prior, state)
        require_operations_state_size(logical)
        return {OPS_STATE_PATH: logical}
    if len(logical) > OPS_LOGICAL_MAX_BYTES:
        raise ValueError('operations logical state capacity reached; pruning/reset forbidden')
    if type(state.get('schema_version')) is not int or state['schema_version'] != 1 or not isinstance(state.get('events'), dict):
        require_operations_state_size(logical)
        raise ValueError('operations storage requires v1 logical schema')
    inline_keys = {scope: set(_table(prior, scope) or {}) for scope in SCOPES} if meta else {}
    # Reuse only values whose bytes/hash/schema were checked in this call. No
    # cache crosses checkpoints, and all historical records are still compared.
    checked_members, checked_migrations = {}, {}
    previous = _load_parsed_state(prior, meta, read_member, checked_members, checked_migrations) if previous_body is not None else None
    if previous is not None:
        _preserved(previous, state)
    files = {}
    segments = copy.deepcopy(meta['segments']) if meta else []
    migration = copy.deepcopy(meta['migration']) if meta else None
    if meta is None and previous_body is not None:
        if type(prior.get('schema_version')) is not int or prior['schema_version'] != 1:
            raise ValueError('operations storage migration requires v1 state')
        chunks = []
        for index, offset in enumerate(range(0, len(previous_body), OPS_MEMBER_MAX_BYTES)):
            chunk = previous_body[offset:offset + OPS_MEMBER_MAX_BYTES]
            digest = _sha(chunk)
            path = OPS_STATE_DIRECTORY + '/legacy-' + digest + '.bin'
            files[path] = chunk
            chunks.append({'path': path, 'sha256': digest, 'bytes': len(chunk), 'index': index})
        migration = {'sha256': _sha(previous_body), 'bytes': len(previous_body),
                     'logical_sha256': _sha(_canonical(previous)), 'chunks': chunks}
    # Only map pointers change; never deepcopy the entire retained history.
    hot = dict(state)
    if 'audit' in hot:
        hot['audit'] = dict(hot['audit'])
    previous_hash = segments[-1]['sha256'] if segments else None
    def flush(scope, records):
        nonlocal previous_hash
        if not records:
            return
        raw = _canonical({'schema_version': 1, 'scope': scope, 'previous': previous_hash, 'records': records})
        if len(raw) > OPS_MEMBER_MAX_BYTES:
            raise ValueError('operations storage record/member capacity reached; pruning/reset forbidden')
        digest = _sha(raw)
        path = OPS_STATE_DIRECTORY + '/segment-' + digest + '.json'
        files[path] = raw
        segments.append({'path': path, 'sha256': digest, 'bytes': len(raw), 'scope': scope,
                         'records': len(records), 'previous': previous_hash})
        previous_hash = digest
    for scope in SCOPES:
        table = _table(state, scope)
        if table is None:
            continue
        # Only already-segmented keys are excluded. Prior inline records remain
        # in the bounded tail until a full chunk can be appended. Never
        # repartition or recopy old segments when a hash sorts before them.
        retained = set(_table(previous, scope) or {}) - inline_keys[scope] if meta else set()
        records, size = {}, 256
        for key in sorted(table.keys() - retained):
            record_size = len(_canonical({key: table[key]}))
            if records and size + record_size > OPS_SEGMENT_TARGET_BYTES:
                flush(scope, records)
                records, size = {}, 256
            records[key] = table[key]
            size += record_size
            if size >= OPS_SEGMENT_TARGET_BYTES:
                flush(scope, records)
                records, size = {}, 256
        _replace_table(hot, scope, records)
    hot[STORAGE_KEY] = {'schema_version': 2, 'segments': segments, 'migration': migration,
                        'logical_sha256': _sha(logical)}
    body = _canonical(hot)
    require_operations_state_size(body)
    _manifest(body, parsed=hot)
    files[OPS_STATE_PATH] = body
    # Verify reconstruction before the caller writes the first new member.
    def candidate_member(path):
        if path in files:
            return files[path]
        if read_member is None:
            raise ValueError('operations storage member reader required')
        return read_member(path)
    if _load_parsed_state(hot, hot[STORAGE_KEY], candidate_member, checked_members, checked_migrations) != state:
        raise ValueError('operations storage lossless reconstruction failed')
    return files


def validate_operations_storage_continuation(previous_body, next_body, read_old_member=None, read_new_member=None):
    """Forbid manifest downgrade, resegmentation, or migration-byte rebinding."""
    _old, before = _manifest(previous_body)
    _new, after = _manifest(next_body)
    if before is not None:
        if after is None:
            raise ValueError('operations storage downgrade forbidden')
        if (after['segments'][:len(before['segments'])] != before['segments']
                or after['migration'] != before['migration']):
            raise ValueError('operations storage immutable reference prefix changed')
    old = _load_parsed_state(_old, before, read_old_member)
    new = _load_parsed_state(_new, after, read_new_member)
    _preserved(old, new)
