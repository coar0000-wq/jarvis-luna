"""Read-only artifact observations, not autonomous agents or business clearance.

observe(root, previous=None, *, now=None, policy=None) returns JSON-safe state,
watchers and events. Persist returned state atomically outside this module. A
missing capture clock is deliberately BLOCKED; file mtime/generator clocks are
not collection evidence. No order/customer/tool connector is implemented.
Policy: max_age_seconds (default 172800), cooldown_seconds (default 3600),
team_max_age_seconds/team_cooldown_seconds maps, deadlines {team: UTC ISO}.
Cooldown postpones new events; a reached deadline bypasses it, never dedup.
"""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

TEAMS = ('sourcing', 'institutions', 'market', 'listing', 'pricing', 'legal',
         'robotics', 'design', 'channels', 'knowledge', 'graph')
# Explicitly selected public operational fields; never serialize whole reports.
SOURCE_MAPPINGS = {
    'sourcing': ('data/product_master.json', 'products', 'source.collected_at'),
    'institutions': ('data/institution_sources.json', 'items', 'collected_at'),
    'market': ('data/google_trends_beauty.json', 'items', 'collected_at'),
    'listing': ('data/listing_gate.json', 'items', 'collected_at'),
    'pricing': ('data/product_master.json', 'products', 'source.collected_at'),
    'legal': ('data/legal_full.json', 'items', 'collected_at'),
    'robotics': ('data/robotics_sources.json', 'sources', 'collected_at'),
    'design': ('data/design_team.json', 'references.items', 'collected_at'),
    'channels': ('data/channel_candidates.json', 'candidates', 'collected_at'),
    'knowledge': ('data/knowledge/real_sources.json', 'sources', 'collected_at'),
    'graph': ('data/obsidian_sync_status.json', '', 'last_successful_sync_at'),
    'secretary': ('data/dashboard_runtime.json',
                  'automation_freshness.workflows.workflows',
                  'automation_freshness.workflows.observed_at'),
}
KNOWN_SOURCE_MAPPINGS = SOURCE_MAPPINGS
_CLOCKS = {'generated_at', 'generator', 'gate_generated_at'}
_CAPTURE = {'captured_at', 'collected_at', 'observed_at', 'last_successful_sync_at'}
_SAFE_ID = re.compile(r'^[A-Za-z0-9_:./-]{1,200}$')
_HASH = re.compile(r'^[0-9a-f]{64}$')
_FIELDS = {
    'sourcing': ('canonical_product_id', 'pd_no', 'brand', 'category', 'price_krw',
                 'rating', 'review_count', 'grade', 'shopify_score'),
    'pricing': ('canonical_product_id', 'price_krw', 'price_unit'),
    'institutions': ('url', 'date', 'org', 'category', 'kind', 'source'),
    'market': ('url', 'keyword', 'kind', 'beauty'),
    'listing': ('canonical_product_id', 'pd_no', 'ready', 'public_ready',
                'agent_ready', 'blocked_by', 'agent_blocked_by'),
    'legal': ('canonical_product_id', 'pd_no', 'complete', 'blockers',
              'hard_block', 'auto_legal_status', 'translation_status'),
    'robotics': ('status', 'items'),
    'design': ('url', 'date', 'feed', 'relevance'),
    'channels': ('key', 'url', 'kind', 'verdict', 'items', 'already_live'),
    'knowledge': ('status', 'source', 'items'),
    'graph': ('connected', 'state', 'last_successful_sync_at', 'summary'),
    'secretary': ('id', 'workflow_id', 'name', 'status', 'conclusion', 'run_id',
                  'last_attempt_at', 'last_success_at', 'observed_at',
                  'latest_attempt', 'last_success'),
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def digest(value):
    return sha256(canonical(value).encode('utf-8')).hexdigest()


def _time(value):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        raise ValueError('timestamp must be ISO string or aware datetime')
    if result.tzinfo is None:
        raise ValueError('timestamp must include timezone')
    return result.astimezone(timezone.utc)


def _get(value, key):
    for part in key.split('.') if key else []:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _clean(value, clocks=False):
    if isinstance(value, dict):
        return {k: _clean(v, clocks) for k, v in sorted(value.items())
                if k not in _CLOCKS and (not clocks or k not in _CAPTURE)}
    if isinstance(value, list):
        return sorted((_clean(v, clocks) for v in value), key=canonical)
    return value


def _json_valid(value, depth=0):
    if depth > 30:
        raise ValueError('JSON nesting exceeds limit')
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError('JSON keys must be strings')
            _json_valid(v, depth + 1)
    elif isinstance(value, list):
        for v in value:
            _json_valid(v, depth + 1)
    elif value is not None and not isinstance(value, (str, bool, int, float)):
        raise ValueError('unsupported JSON value')
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError('non-finite number')


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _settings(policy):
    if policy is None:
        policy = {}
    if not isinstance(policy, dict):
        raise ValueError('policy must be an object')
    allowed = {'max_age_seconds', 'cooldown_seconds', 'team_max_age_seconds',
               'team_cooldown_seconds', 'deadlines'}
    if set(policy) - allowed:
        raise ValueError('unknown watch policy field')
    result = {'max_age_seconds': 172800, 'cooldown_seconds': 3600,
              'team_max_age_seconds': {}, 'team_cooldown_seconds': {}, 'deadlines': {}}
    result.update(deepcopy(policy))
    for key in ('max_age_seconds', 'cooldown_seconds'):
        if not _number(result[key]) or result[key] < 0:
            raise ValueError('invalid duration')
    for key in ('team_max_age_seconds', 'team_cooldown_seconds', 'deadlines'):
        if not isinstance(result[key], dict) or set(result[key]) - set(SOURCE_MAPPINGS):
            raise ValueError('invalid team policy')
        for v in result[key].values():
            if key == 'deadlines':
                _time(v)
            elif not _number(v) or v < 0:
                raise ValueError('invalid team duration')
    return result


def _cursor(previous):
    if previous is None:
        return {'schema_version': 1, 'sources': {}, 'seen_events': {},
                'pending_events': {}, 'last_emitted': {}}
    _json_valid(previous)
    if (not isinstance(previous, dict) or type(previous.get('schema_version')) is not int
            or previous.get('schema_version') != 1):
        raise ValueError('unsupported cursor schema')
    if set(previous) != {'schema_version', 'sources', 'seen_events',
                         'pending_events', 'last_emitted'}:
        raise ValueError('invalid cursor fields')
    for field in ('sources', 'seen_events', 'pending_events', 'last_emitted'):
        if not isinstance(previous[field], dict):
            raise ValueError('invalid cursor map')
    for team, src in previous['sources'].items():
        if team not in SOURCE_MAPPINGS or not isinstance(src, dict):
            raise ValueError('invalid source cursor')
        if (src.get('status') not in ('VALID', 'BLOCKED') or
                not isinstance(src.get('records'), dict)):
            raise ValueError('invalid source records')
        for entity, record in src['records'].items():
            if (not isinstance(entity, str) or not isinstance(record, dict) or
                    not isinstance(record.get('value'), dict) or
                    not isinstance(record.get('captured_at'), str)):
                raise ValueError('invalid record cursor')
            _time(record['captured_at'])
            if team == 'pricing' and (not _number(record['value'].get('amount'))
                    or record['value'].get('amount', -1) < 0
                    or record['value'].get('canonical_product_id') != entity
                    or record['value'].get('currency') != 'KRW'
                    or not isinstance(record['value'].get('unit'), str)):
                raise ValueError('invalid price cursor')
        if src['status'] == 'VALID':
            if not isinstance(src.get('semantic_hash'), str) or not _HASH.fullmatch(src['semantic_hash']):
                raise ValueError('invalid source hash')
            if src['semantic_hash'] != digest({k: v['value'] for k, v in src['records'].items()}):
                raise ValueError('source cursor hash mismatch')
    for event_id, stamp in previous['seen_events'].items():
        if not isinstance(event_id, str) or not _HASH.fullmatch(event_id):
            raise ValueError('invalid dedup ID')
        _time(stamp)
    for team, stamp in previous['last_emitted'].items():
        if team not in SOURCE_MAPPINGS:
            raise ValueError('invalid cooldown team')
        _time(stamp)
    for event_id, event in previous['pending_events'].items():
        if (not isinstance(event, dict) or event.get('event_id') != event_id or
                event.get('source_team') not in SOURCE_MAPPINGS or
                event.get('type') not in ('SOURCE_CHANGED', 'PRICE_CHANGED') or
                not _HASH.fullmatch(event_id) or not isinstance(event.get('evidence'), dict)
                or not isinstance(event.get('change'), dict)):
            raise ValueError('invalid pending event')
        if not isinstance(event.get('captured_at'), str) or not isinstance(event.get('source_entity_id'), str):
            raise ValueError('invalid pending event metadata')
        _time(event['captured_at'])
        for key in ('before_source_hash', 'source_hash', 'before_entity_hash', 'entity_hash'):
            value = event['evidence'].get(key)
            if not isinstance(value, str) or not _HASH.fullmatch(value):
                raise ValueError('invalid pending evidence hash')
        for key in ('before_hash', 'after_hash'):
            value = event['change'].get(key)
            if not isinstance(value, str) or not _HASH.fullmatch(value):
                raise ValueError('invalid pending change hash')
        if event['type'] == 'PRICE_CHANGED' and (
                not _number(event['change'].get('before')) or not _number(event['change'].get('after'))
                or event['change'].get('currency') != 'KRW' or not isinstance(event['change'].get('unit'), str)):
            raise ValueError('invalid pending price schema')
        if event_id != _event_id(event):
            raise ValueError('pending event ID mismatch')
    return deepcopy(previous)


def _project(team, doc):
    _, container, capture_field = SOURCE_MAPPINGS[team]
    rows = _get(doc, container)
    if team == 'graph':
        rows = [doc]
    elif isinstance(rows, dict):
        if any(not isinstance(v, dict) for v in rows.values()):
            raise ValueError('invalid_record_schema')
        rows = [dict(v, _source_key=k) for k, v in rows.items()]
    if not isinstance(rows, list) or not rows:
        raise ValueError('missing_or_empty_records')
    output = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('invalid_record_schema')
        identity = next((row[k] for k in ('canonical_product_id', 'key', 'workflow_id',
                        'id', 'url', '_source_key') if row.get(k) is not None), None)
        if team == 'graph':
            identity = 'obsidian-sync'
        if not isinstance(identity, (str, int)) or isinstance(identity, bool):
            raise ValueError('source_entity_id_missing')
        identity = str(identity)
        # Public feed URLs may contain query selectors. Use opaque stable IDs;
        # neither credentials nor private query parameters enter public cursors.
        if identity.startswith(('https://', 'http://')):
            identity = 'url:' + digest(identity)
        if '?' in identity or '#' in identity or '@' in identity or not _SAFE_ID.fullmatch(identity):
            raise ValueError('unsafe_source_entity_id')
        if identity in output:
            raise ValueError('duplicate_source_entity_id')
        captured = _get(row, capture_field) or row.get('collected_at') or _get(doc, capture_field)
        if not captured:
            raise ValueError('source_capture_missing')
        captured = _time(captured).isoformat()
        selected = {k: row[k] for k in _FIELDS[team] if k in row}
        if 'url' in selected:
            if not isinstance(selected['url'], str):
                raise ValueError('invalid_record_schema')
            parsed = urlsplit(selected['url'])
            if parsed.scheme not in ('https', 'http') or not parsed.hostname:
                raise ValueError('invalid_record_schema')
            selected['url'] = parsed.scheme + '://' + parsed.hostname + parsed.path
        for key, val in selected.items():
            if key in ('price_krw', 'rating', 'review_count', 'shopify_score', 'relevance'):
                if val is not None and (not _number(val) or val < 0):
                    raise ValueError('invalid_record_schema')
            if key in ('ready', 'public_ready', 'agent_ready', 'complete', 'hard_block',
                       'connected', 'already_live', 'beauty') and not isinstance(val, bool):
                raise ValueError('invalid_record_schema')
            if key in ('canonical_product_id', 'pd_no', 'key', 'url', 'price_unit'):
                if not isinstance(val, str):
                    raise ValueError('invalid_record_schema')
        # Nested free-form fields are never copied from potentially private reports.
        for key in list(selected):
            val = selected[key]
            if isinstance(val, dict):
                if team == 'graph' and key == 'summary':
                    selected[key] = {k: v for k, v in val.items()
                                     if k in ('repo_to_vault', 'vault_to_repo', 'conflicts', 'unchanged')
                                     and _number(v)}
                elif team == 'secretary' and key in ('latest_attempt', 'last_success'):
                    selected[key] = {k: v for k, v in val.items()
                                     if k in ('id', 'status', 'conclusion', 'event', 'created_at',
                                              'run_started_at', 'finished_at', 'run_attempt')
                                     and (v is None or isinstance(v, (str, int)))}
                else:
                    del selected[key]
            elif isinstance(val, list):
                if key in ('blocked_by', 'agent_blocked_by', 'blockers'):
                    # Blocker text can contain contact data. Only safe code tokens survive.
                    selected[key] = sorted(v for v in val if isinstance(v, str)
                                           and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', v))
                else:
                    del selected[key]
        if team == 'pricing':
            price = selected.get('price_krw')
            if not isinstance(row.get('canonical_product_id'), str) or row['canonical_product_id'] != identity:
                raise ValueError('canonical_price_identity_missing')
            if not _number(price) or price < 0:
                raise ValueError('invalid_measured_price')
            unit = row.get('price_unit', 'product')
            if not isinstance(unit, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', unit):
                raise ValueError('invalid_price_unit')
            selected = {'canonical_product_id': identity, 'amount': price,
                        'currency': 'KRW', 'unit': unit, 'metric': 'observed_source_price'}
        output[identity] = {'value': _clean(selected, True), 'captured_at': captured}
    return output


def _event_id(event):
    return digest({k: event[k] for k in ('type', 'source_team', 'source_entity_id', 'change')})


def observe(root, previous=None, *, now=None, policy=None):
    """Observe fixed allowlisted files. No writes, network, mtime freshness or execution."""
    stamp = _time(now)
    settings = _settings(policy)
    state = _cursor(previous)
    base = Path(root).resolve()
    if not base.is_dir():
        raise ValueError('root must be an existing directory')
    watchers, events = [], []
    for team, (relative, _, _) in SOURCE_MAPPINGS.items():
        watcher = {'watcher_id': 'watch:' + team, 'source_team': team,
                   'function': 'artifact_observation', 'is_agent': False,
                   'source': relative, 'status': 'BLOCKED', 'blockers': [],
                   'unconnected': ['orders', 'customer_activity', 'new_ai_tools']}
        old = state['sources'].get(team)
        try:
            source_path = (base / relative).resolve()
            if not source_path.is_relative_to(base):
                raise ValueError('source_outside_root')
            if source_path.stat().st_size > 20_000_000:
                raise ValueError('source_too_large')
            doc = json.loads(source_path.read_text(encoding='utf-8-sig'),
                             parse_constant=lambda v: (_ for _ in ()).throw(ValueError('non_finite_json')))
            _json_valid(doc)
            if not isinstance(doc, dict):
                raise ValueError('invalid_source_schema')
            if str(doc.get('status', '')).lower() in ('failed', 'failure', 'error', 'blocked', 'unavailable'):
                raise ValueError('source_reported_failure')
            records = _project(team, doc)
            max_age = settings['team_max_age_seconds'].get(team, settings['max_age_seconds'])
            for row in records.values():
                age = (stamp - _time(row['captured_at'])).total_seconds()
                if age < 0:
                    raise ValueError('source_capture_in_future')
                if age > max_age:
                    raise ValueError('stale_source_capture')
            semantic = digest({k: v['value'] for k, v in records.items()})
            evidence_hash = digest(records)
            watcher.update({'status': 'BASELINE', 'semantic_hash': semantic,
                            'source_hash': evidence_hash,
                            'captured_at': min(v['captured_at'] for v in records.values()),
                            'source_entity_ids': sorted(records)})
            if old and old['status'] == 'VALID':
                watcher['status'] = 'NO_CHANGE' if old['semantic_hash'] == semantic else 'CHANGED'
                for entity in sorted(set(old['records']) | set(records)):
                    before = old['records'].get(entity)
                    after = records.get(entity)
                    bv, av = (before or {}).get('value'), (after or {}).get('value')
                    if bv == av:
                        continue
                    event_type = 'SOURCE_CHANGED'
                    if team == 'pricing':
                        if (not bv or not av or any(bv.get(k) != av.get(k)
                                for k in ('canonical_product_id', 'currency', 'unit', 'metric'))):
                            continue
                        if bv['amount'] == av['amount']:
                            continue
                        event_type = 'PRICE_CHANGED'
                    event = {'type': event_type, 'source_team': team,
                             'source_entity_id': entity,
                             'captured_at': (after or before)['captured_at'],
                             'change': {'before_hash': digest(bv), 'after_hash': digest(av),
                                        'kind': 'added' if before is None else 'removed' if after is None else 'updated'},
                             'evidence': {'source': relative, 'before_source_hash': digest(old['records']),
                                          'source_hash': evidence_hash, 'before_entity_hash': digest(before),
                                          'entity_hash': digest(after)}}
                    if event_type == 'PRICE_CHANGED':
                        event['change'].update({'before': bv['amount'], 'after': av['amount'],
                                                'currency': av['currency'], 'unit': av['unit']})
                    event['event_id'] = _event_id(event)
                    if event['event_id'] not in state['seen_events']:
                        state['pending_events'][event['event_id']] = event
            state['sources'][team] = {'status': 'VALID', 'semantic_hash': semantic, 'records': records}
            last = state['last_emitted'].get(team)
            cooldown = settings['team_cooldown_seconds'].get(team, settings['cooldown_seconds'])
            deadline = settings['deadlines'].get(team)
            eligible = (last is None or (stamp - _time(last)).total_seconds() >= cooldown
                        or (deadline is not None and stamp >= _time(deadline)))
            pending = [e for e in state['pending_events'].values() if e['source_team'] == team]
            if eligible:
                for event in sorted(pending, key=lambda e: e['event_id']):
                    event_age = (stamp - _time(event['captured_at'])).total_seconds()
                    if event_age < 0 or event_age > max_age:
                        watcher['pending_blocked'] = 'STALE_OR_FUTURE_EVENT_EVIDENCE'
                        continue
                    if event['event_id'] not in state['seen_events']:
                        events.append(deepcopy(event))
                        state['seen_events'][event['event_id']] = stamp.isoformat()
                        state['last_emitted'][team] = stamp.isoformat()
                    del state['pending_events'][event['event_id']]
            elif pending:
                watcher['status'] = 'COOLDOWN'
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            # Only explicitly enumerated codes, never exceptions containing private data.
            safe_reasons = {'source_outside_root', 'source_too_large', 'invalid_source_schema',
                            'source_reported_failure', 'missing_or_empty_records', 'invalid_record_schema',
                            'source_entity_id_missing', 'unsafe_source_entity_id', 'duplicate_source_entity_id',
                            'source_capture_missing', 'canonical_price_identity_missing', 'invalid_measured_price',
                            'invalid_price_unit', 'source_capture_in_future', 'stale_source_capture'}
            reason = str(exc)
            watcher['blockers'] = [reason.upper() if reason in safe_reasons else 'SOURCE_MISSING_INVALID_OR_STALE']
            state['sources'][team] = {'status': 'BLOCKED', 'records': {}}
        watchers.append(watcher)
    return {'state': state, 'watchers': watchers, 'events': events}
