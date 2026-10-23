"""Lossless, bounded storage for the derived operations knowledge graph.

Legacy graphs remain ordinary JSON. Large graphs are an integrity-bound manifest
and immutable content-addressed JSON segments. Array order, object field order,
IDs, metadata and complete records survive reconstruction; nothing is summarized
or pruned. This module performs no IO and grants no execution authority.

Writers must validate existing members, create/fsync missing members without
replacement, and atomically replace the manifest LAST. Never remove old members,
including valid orphans. The graph is derived, so new manifests may reference new
segments; this does not permit editing any already-published member.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

if __package__:
    from .operations_storage import OPS_LOGICAL_MAX_BYTES, OPS_STORAGE_MAX_MEMBERS
else:
    from operations_storage import OPS_LOGICAL_MAX_BYTES, OPS_STORAGE_MAX_MEMBERS

GRAPH_PATH = 'data/operations/knowledge_graph.json'
GRAPH_DIRECTORY = 'data/operations/knowledge_graph'
GRAPH_MAX_BYTES = 32 * 1024 * 1024
GRAPH_MEMBER_MAX_BYTES = 8 * 1024 * 1024
GRAPH_SEGMENT_TARGET_BYTES = 1024 * 1024
GRAPH_MIGRATION_THRESHOLD = GRAPH_MAX_BYTES
GRAPH_LOGICAL_MAX_BYTES = OPS_LOGICAL_MAX_BYTES
# Stored wrappers are charged too: a near-limit logical graph can fail before
# 120 MiB rather than bypass the existing aggregate safety limit.
GRAPH_AGGREGATE_MAX_BYTES = OPS_LOGICAL_MAX_BYTES
GRAPH_MAX_MEMBERS = OPS_STORAGE_MAX_MEMBERS
STORAGE_KEY = '_operations_graph_storage'
SCOPES = ('nodes', 'edges')
_MEMBER = re.compile(r'data/operations/knowledge_graph/segment-([0-9a-f]{64})\.json\Z')
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_ENCODER = json.JSONEncoder(ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _sha(body):
    return hashlib.sha256(body).hexdigest()


def _native(value, active=None):
    """Reject lossy JSON coercions (integer keys, tuples, cycles, nonfinite)."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError('operations graph nonfinite JSON')
        return
    if type(value) not in (dict, list):
        raise ValueError('operations graph requires native JSON values')
    active = set() if active is None else active
    if id(value) in active:
        raise ValueError('operations graph cyclic JSON')
    active.add(id(value))
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError('operations graph JSON keys must be strings')
            _native(item, active)
    else:
        for item in value:
            _native(item, active)
    active.remove(id(value))


def _canonical(value, limit=None):
    """Deterministic compact UTF-8, preserving every object's field order."""
    limit = GRAPH_LOGICAL_MAX_BYTES if limit is None else limit
    result = bytearray()
    try:
        for token in _ENCODER.iterencode(value):
            # UTF-8 cannot be shorter than its Python string's character count.
            if len(result) + len(token) + 1 > limit:
                raise ValueError('operations graph serialized capacity reached')
            chunk = token.encode('utf-8')
            if len(result) + len(chunk) + 1 > limit:
                raise ValueError('operations graph serialized capacity reached')
            result.extend(chunk)
        result.extend(b'\n')
    except (RecursionError, UnicodeError, TypeError) as exc:
        raise ValueError('operations graph JSON encoding invalid') from exc
    return bytes(result)


def _json(body, limit):
    # Bound BEFORE decoding, parsing or hashing any caller-supplied bytes.
    if not isinstance(body, bytes) or not 0 < len(body) <= limit:
        raise ValueError('operations graph serialized scope/size invalid')

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('operations graph duplicate JSON key')
            result[key] = value
        return result

    def finite_float(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError('operations graph nonfinite JSON')
        return value

    def nonfinite(_value):
        raise ValueError('operations graph nonfinite JSON')

    try:
        return json.loads(body.decode('utf-8'), object_pairs_hook=pairs,
                          parse_float=finite_float, parse_constant=nonfinite)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError('operations graph JSON decoding invalid') from exc


def _records(records, seen=None):
    if not isinstance(records, list):
        raise ValueError('operations graph records must be arrays')
    seen = set() if seen is None else seen
    for record in records:
        if (not isinstance(record, dict) or not isinstance(record.get('id'), str)
                or not record['id']):
            raise ValueError('operations graph record schema invalid')
        if record['id'] in seen:
            raise ValueError('operations graph duplicate record ID')
        seen.add(record['id'])


def _graph(value):
    if (not isinstance(value, dict) or STORAGE_KEY in value
            or any(scope not in value for scope in SCOPES)):
        raise ValueError('operations graph logical schema invalid')
    for scope in SCOPES:
        _records(value[scope])


def is_graph_member(name):
    return isinstance(name, str) and _MEMBER.fullmatch(name) is not None


def validate_graph_member(name, body):
    """Validate every immutable segment, including unreferenced old segments."""
    if not is_graph_member(name):
        raise ValueError('operations graph member path invalid')
    if not isinstance(body, bytes) or not 0 < len(body) <= GRAPH_MEMBER_MAX_BYTES:
        raise ValueError('operations graph member size invalid')
    if _sha(body) != _MEMBER.fullmatch(name).group(1):
        raise ValueError('operations graph member hash mismatch')
    segment = _json(body, GRAPH_MEMBER_MAX_BYTES)
    if (not isinstance(segment, dict)
            or set(segment) != {'schema_version', 'scope', 'records'}
            or type(segment['schema_version']) is not int or segment['schema_version'] != 1
            or segment['scope'] not in SCOPES
            or not isinstance(segment['records'], list) or not segment['records']):
        raise ValueError('operations graph segment schema invalid')
    _records(segment['records'])
    if _canonical(segment, GRAPH_MEMBER_MAX_BYTES) != body:
        raise ValueError('operations graph segment JSON must be canonical')
    return segment


def _manifest(body):
    value = _json(body, GRAPH_MAX_BYTES)
    if not isinstance(value, dict):
        raise ValueError('operations graph must be an object')
    if STORAGE_KEY not in value:
        # Historical graph producers accepted loose JSON objects. Keep that
        # exact contract for bounded legacy bytes; strict record IDs apply
        # only to the new segmented format.
        return value, None
    meta = value[STORAGE_KEY]
    if (set(value) != {STORAGE_KEY} or not isinstance(meta, dict)
            or set(meta) != {'schema_version', 'metadata', 'field_order', 'segments',
                             'counts', 'order', 'logical_sha256', 'logical_bytes'}
            or type(meta['schema_version']) is not int or meta['schema_version'] != 1
            or not isinstance(meta['metadata'], dict)
            or any(key in meta['metadata'] for key in (*SCOPES, STORAGE_KEY))
            or not isinstance(meta['field_order'], list)
            or any(not isinstance(key, str) for key in meta['field_order'])
            or len(set(meta['field_order'])) != len(meta['field_order'])
            or set(meta['field_order']) != set(meta['metadata']) | set(SCOPES)
            or [key for key in meta['field_order'] if key not in SCOPES] != list(meta['metadata'])
            or not isinstance(meta['segments'], list) or len(meta['segments']) > GRAPH_MAX_MEMBERS
            or not isinstance(meta['counts'], dict) or set(meta['counts']) != set(SCOPES)
            or any(type(meta['counts'][key]) is not int or meta['counts'][key] < 0 for key in SCOPES)
            or not isinstance(meta['order'], dict) or set(meta['order']) != set(SCOPES)
            or any(not isinstance(meta['order'][key], list) for key in SCOPES)
            or not isinstance(meta['logical_sha256'], str) or not _HASH.fullmatch(meta['logical_sha256'])
            or type(meta['logical_bytes']) is not int
            or not 0 < meta['logical_bytes'] <= GRAPH_LOGICAL_MAX_BYTES):
        raise ValueError('operations graph manifest schema invalid')
    paths, total, last_scope = set(), len(body), 0
    for item in meta['segments']:
        if (not isinstance(item, dict)
                or set(item) != {'path', 'sha256', 'bytes', 'scope', 'records'}
                or not isinstance(item['sha256'], str) or not _HASH.fullmatch(item['sha256'])
                or not is_graph_member(item['path'])
                or item['path'] != GRAPH_DIRECTORY + '/segment-' + item['sha256'] + '.json'
                or item['path'] in paths or item['scope'] not in SCOPES
                or type(item['bytes']) is not int or not 0 < item['bytes'] <= GRAPH_MEMBER_MAX_BYTES
                or type(item['records']) is not int or not 0 < item['records'] <= item['bytes']
                or SCOPES.index(item['scope']) < last_scope):
            raise ValueError('operations graph segment reference/order invalid')
        paths.add(item['path'])
        last_scope = SCOPES.index(item['scope'])
        total += item['bytes']
        if total > GRAPH_AGGREGATE_MAX_BYTES:
            raise ValueError('operations graph aggregate capacity reached')
    locations, used, first_use = set(), set(), []
    for scope in SCOPES:
        if len(meta['order'][scope]) != meta['counts'][scope]:
            raise ValueError('operations graph logical counts mismatch')
        for ref in meta['order'][scope]:
            if (not isinstance(ref, list) or len(ref) != 2
                    or any(type(index) is not int for index in ref)
                    or not 0 <= ref[0] < len(meta['segments'])
                    or not 0 <= ref[1] < meta['segments'][ref[0]]['records']
                    or meta['segments'][ref[0]]['scope'] != scope
                    or tuple(ref) in locations):
                raise ValueError('operations graph record reference/order invalid')
            locations.add(tuple(ref))
            if ref[0] not in used:
                used.add(ref[0])
                first_use.append(ref[0])
    # Every descriptor must be used; descriptor order is first logical use.
    # Unselected old records inside a used immutable chunk remain preserved.
    if first_use != list(range(len(meta['segments']))):
        raise ValueError('operations graph unused or reordered segment reference')
    if total > GRAPH_AGGREGATE_MAX_BYTES:
        raise ValueError('operations graph aggregate capacity reached')
    return value, meta


def is_graph_manifest(body):
    """Recognize the reserved envelope only after validating its manifest."""
    return _manifest(body)[1] is not None


def graph_members(body):
    """Return referenced paths in stable order, with no member IO."""
    _value, meta = _manifest(body)
    return () if meta is None else tuple(item['path'] for item in meta['segments'])


def _load_parsed(value, meta, read_member=None, checked=None):
    if meta is None:
        _canonical(value)  # Enforce logical size and reject surrogate strings.
        return value
    if read_member is None and meta['segments'] and checked is None:
        raise ValueError('operations graph member reader required')
    checked = {} if checked is None else checked
    segments = []
    for item in meta['segments']:
        key = (item['path'], item['sha256'], item['bytes'])
        if key in checked:
            segment = checked[key]
        else:
            if read_member is None:
                raise ValueError('operations graph member reader required')
            try:
                raw = read_member(item['path'])
            except (KeyError, FileNotFoundError) as exc:
                raise ValueError('operations graph member missing') from exc
            if not isinstance(raw, bytes) or len(raw) != item['bytes']:
                raise ValueError('operations graph member size/reference mismatch')
            segment = validate_graph_member(item['path'], raw)
            checked[key] = segment
        if (segment['scope'] != item['scope']
                or len(segment['records']) != item['records']):
            raise ValueError('operations graph segment metadata mismatch')
        segments.append(segment)
    tables = {}
    for scope in SCOPES:
        tables[scope] = [segments[chunk]['records'][index] for chunk, index in meta['order'][scope]]
        _records(tables[scope])
    graph = {key: tables[key] if key in SCOPES else meta['metadata'][key]
             for key in meta['field_order']}
    logical = _canonical(graph)
    if len(logical) != meta['logical_bytes'] or _sha(logical) != meta['logical_sha256']:
        raise ValueError('operations graph logical digest/size mismatch')
    return graph


def load_operations_graph(body, read_member=None):
    """Return the full logical graph after bounded, strict integrity checks.

    ``read_member`` must itself use safe paths and a bounded read (8 MiB + 1),
    never unrestricted Path.read_bytes on untrusted filesystem members. This
    module verifies returned sizes before parsing, but cannot bound caller IO.
    """
    value, meta = _manifest(body)
    return _load_parsed(value, meta, read_member)


def prepare_operations_graph(value, previous_body=None, read_member=None, *, force=False):
    """Return ONLY new immutable members and graph.json; no IO or deletions.

    A validated previous manifest lets unchanged individual records reuse their
    old chunk/index regardless of insertions or reordering. Only new/changed
    records are packed. Old chunk bytes, including unselected historical records
    and orphan files, must be retained and aggregate-bounded by the caller.
    Returned members may already exist as orphans; never overwrite them blindly.
    """
    try:
        _native(value)
    except RecursionError as exc:
        raise ValueError('operations graph JSON nesting invalid') from exc
    if not isinstance(value, dict) or STORAGE_KEY in value:
        raise ValueError('operations graph requires a full logical object')
    logical = _canonical(value)
    checked, reusable, descriptors = {}, {}, {}
    if previous_body is not None:
        prior, previous_meta = _manifest(previous_body)
        _load_parsed(prior, previous_meta, read_member, checked)
        if previous_meta is not None:
            force = True  # A prior manifest can never silently downgrade.
            for item in previous_meta['segments']:
                descriptors[item['sha256']] = item
                segment = checked[(item['path'], item['sha256'], item['bytes'])]
                for index, record in enumerate(segment['records']):
                    key = (item['scope'], record['id'], _sha(_canonical(record, GRAPH_MEMBER_MAX_BYTES)))
                    reusable.setdefault(key, (item['sha256'], index))
    if not force and len(logical) <= GRAPH_MIGRATION_THRESHOLD:
        if len(logical) > GRAPH_MAX_BYTES:
            raise ValueError('operations graph serialized capacity reached')
        return {GRAPH_PATH: logical}
    _graph(value)
    files, locations, aggregate = {}, {}, 0

    def flush(scope, records):
        nonlocal aggregate
        if not records:
            return
        raw = _canonical({'schema_version': 1, 'scope': scope, 'records': records}, GRAPH_MEMBER_MAX_BYTES)
        digest = _sha(raw)
        path = GRAPH_DIRECTORY + '/segment-' + digest + '.json'
        files[path] = raw
        aggregate += len(raw)
        if aggregate > GRAPH_AGGREGATE_MAX_BYTES or len(files) > GRAPH_MAX_MEMBERS:
            raise ValueError('operations graph aggregate capacity reached')
        descriptors[digest] = {'path': path, 'sha256': digest, 'bytes': len(raw),
                               'scope': scope, 'records': len(records)}
        for index, record in enumerate(records):
            locations[(scope, record['id'])] = (digest, index)

    for scope in SCOPES:
        overhead = len(_canonical({'schema_version': 1, 'scope': scope, 'records': []},
                                  GRAPH_MEMBER_MAX_BYTES))
        records, size = [], overhead
        for record in value[scope]:
            record_raw = _canonical(record, GRAPH_MEMBER_MAX_BYTES)
            previous = reusable.get((scope, record['id'], _sha(record_raw)))
            if previous is not None:
                locations[(scope, record['id'])] = previous
                continue
            if records and size + len(record_raw) > min(GRAPH_SEGMENT_TARGET_BYTES, GRAPH_MEMBER_MAX_BYTES):
                flush(scope, records)
                records, size = [], overhead
            records.append(record)
            size += len(record_raw)
            if size >= GRAPH_SEGMENT_TARGET_BYTES:
                flush(scope, records)
                records, size = [], overhead
        flush(scope, records)
    # Compact integer pairs preserve exact logical ordering without repeating a
    # 64-character digest for every record. Descriptors bind every used chunk.
    segments, segment_indices, order = [], {}, {scope: [] for scope in SCOPES}
    for scope in SCOPES:
        for record in value[scope]:
            digest, index = locations[(scope, record['id'])]
            if digest not in segment_indices:
                segment_indices[digest] = len(segments)
                segments.append(descriptors[digest])
            order[scope].append([segment_indices[digest], index])
    meta = {'schema_version': 1,
            'metadata': {key: item for key, item in value.items() if key not in SCOPES},
            'field_order': list(value), 'segments': segments, 'order': order,
            'counts': {scope: len(value[scope]) for scope in SCOPES},
            'logical_sha256': _sha(logical), 'logical_bytes': len(logical)}
    body = _canonical({STORAGE_KEY: meta}, GRAPH_MAX_BYTES)
    _manifest(body)
    files[GRAPH_PATH] = body
    # Reuse only records read and verified in this call, never across calls.
    def candidate_member(path):
        if path in files:
            return files[path]
        if read_member is None:
            raise ValueError('operations graph member reader required')
        return read_member(path)
    rebuilt = _load_parsed({STORAGE_KEY: meta}, meta, candidate_member, checked)
    if _canonical(rebuilt) != logical:
        raise ValueError('operations graph lossless reconstruction failed')
    return files
