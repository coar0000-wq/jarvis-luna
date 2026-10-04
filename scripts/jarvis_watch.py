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
    'robotics': ('url', 'title', 'published', 'kind', 'source_pool'),
    'design': ('url', 'date', 'feed', 'relevance'),
    'channels': ('key', 'url', 'kind', 'verdict', 'items', 'already_live'),
    'knowledge': ('url', 'title', 'product_id', 'source_pool', 'source', 'org', 'brand', 'query', 'channel'),
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


PARTIAL_TEAMS = frozenset(('institutions', 'robotics', 'design', 'channels', 'knowledge'))
LOCAL_TEAMS = frozenset(('listing', 'legal'))
SHORTLIST_OBSERVATIONS = 'data/daiso_real/shortlist_observations.json'


def _safe_source(base, relative):
    # No redirects through symlinks/junctions, including root ancestors.
    for parent in [base, *base.parents]:
        if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
            raise ValueError('source_outside_root')
    current = base
    for part in relative.split('/'):
        if part in ('', '.', '..') or ':' in part or '\\' in part:
            raise ValueError('source_outside_root')
        current /= part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('source_outside_root')
    if not current.resolve().is_relative_to(base.resolve()):
        raise ValueError('source_outside_root')
    return current


def _failure_count(doc, team):
    blocks = [doc]
    if team in ('institutions', 'robotics', 'knowledge') and isinstance(doc.get('sources'), dict):
        blocks = list(doc['sources'].values())
    elif team == 'design':
        blocks = [_get(doc, 'references') or doc]
    failed = 0
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if team == 'institutions':
            failures = block.get('failures') or []
            if not isinstance(failures, list):
                raise ValueError('invalid_record_schema')
            failed += max(len(failures), int(str(block.get('status', '')).lower() in ('failed','error','blocked')))
        results = block.get('source_results') or {}
        if isinstance(results, dict):
            for result in results.values():
                if not isinstance(result, dict):
                    continue
                last = result.get('last_attempt') or {}
                if (str(result.get('status', '')).lower() in ('failed','failure','partial','blocked')
                        or str(last.get('status', '')).lower() in ('failed','failure','error','blocked')):
                    failed += 1
    return failed


def _failed_institution_providers(doc):
    failed = set()
    sources = doc.get('sources') or {}
    if not isinstance(sources, dict):
        raise ValueError('invalid_record_schema')
    for pool, block in sources.items():
        if not isinstance(block, dict):
            raise ValueError('invalid_record_schema')
        if str(block.get('status', '')).lower() in ('failed', 'error', 'blocked'):
            failed.add((pool, None))
        for error in block.get('failures') or []:
            org = error.get('org') if isinstance(error, dict) else None
            failed.add((pool, str(org).casefold() if org else None))
    return failed


def _institution_unavailable(row, failed):
    pool = row.get('source')
    return (pool, None) in failed or (pool, str(row.get('org', '')).casefold()) in failed


def _rows(team, doc, diagnostics):
    _, container, _ = SOURCE_MAPPINGS[team]
    rows = _get(doc, container)
    if team == 'graph':
        return [doc]
    if team in ('robotics', 'knowledge') and isinstance(rows, dict):
        flattened = []
        for pool, block in rows.items():
            if not isinstance(block, dict):
                raise ValueError('invalid_record_schema')
            items = block.get('items')
            if not isinstance(items, list):
                diagnostics['failed_sources'] += 1
                diagnostics['unavailable_pools'].add(pool)
                continue
            # Registered hardcoded catalog is not an observed external source.
            catalog = (pool == 'organic_skincare' and
                       (block.get('evidence_scope') in ('catalog', 'catalog_registration', 'registered_catalog')
                        or block.get('capture_status') in ('not_collected', 'catalog_only') or block.get('evidence_type') == 'catalog_registration'
                        or block.get('source') in ('catalog', 'organic_skincare_catalog') or all(isinstance(v, dict) and (v.get('evidence_scope') == 'catalog_registration' or v.get('evidence_type') == 'catalog_registration' or v.get('capture_status') == 'not_collected') for v in items)))
            if catalog:
                diagnostics['catalog_only'] += len(items)
                continue
            if not items or str(block.get('status', '')).lower() in ('failed', 'error', 'blocked'):
                diagnostics['failed_sources'] += 1
                diagnostics['unavailable_pools'].add(pool)
                continue
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError('invalid_record_schema')
                proof = item.get('provenance') or {}
                result = (block.get('source_results') or {}).get(proof.get('source_key')) or {}
                attempt = result.get('last_attempt') or {}
                failed_attempt = str(result.get('status', '')).lower() in ('failed','error','blocked') or str(attempt.get('status', '')).lower() in ('failed','failure','error','blocked')
                flattened.append(dict(item, source_pool=pool, _pool_capture=block.get('collected_at'), _attempt_failed=failed_attempt))
        return flattened
    if isinstance(rows, dict):
        if any(not isinstance(v, dict) for v in rows.values()):
            raise ValueError('invalid_record_schema')
        return [dict(v, _source_key=k) for k, v in rows.items()]
    return rows


def _project(team, doc, *, observed_at=None, diagnostics=None):
    if diagnostics is None:
        diagnostics = {}
    diagnostics.update(total_records=0, missing_records=0, stale_records=0,
                       failed_sources=_failure_count(doc, team), catalog_only=0, unavailable_ids=set(), unavailable_pools=set())
    rows = _rows(team, doc, diagnostics)
    if not isinstance(rows, list) or not rows:
        raise ValueError('missing_or_empty_records')
    output, seen = {}, set()
    failed_institutions = _failed_institution_providers(doc) if team == 'institutions' else set()
    _, _, capture_field = SOURCE_MAPPINGS[team]
    for row in rows:
        diagnostics['total_records'] += 1
        if not isinstance(row, dict):
            raise ValueError('invalid_record_schema')
        identity = next((row[k] for k in ('canonical_product_id', 'key', 'workflow_id',
                        'id', 'url', 'product_id', '_source_key') if row.get(k) is not None), None)
        if team == 'knowledge' and row.get('product_id'):
            identity = row['product_id']
        if team == 'knowledge' and identity in (None, '') and not (row.get('collected_at') or row.get('captured_at')):
            # Undated/unidentified imported placeholders are not collected entities.
            diagnostics['missing_records'] += 1
            continue
        if team == 'graph':
            identity = 'obsidian-sync'
        if not isinstance(identity, (str, int)) or isinstance(identity, bool):
            raise ValueError('source_entity_id_missing')
        identity = str(identity)
        if team == 'institutions' and row.get('org') and row.get('url'):
            # The same work can belong to several orgs; this is one public work,
            # with org associations, NOT independent corroborating observations.
            identity = 'org-url:' + digest([str(row['org']), str(row['url'])])
        elif team in ('robotics', 'knowledge'):
            identity = 'pool-entity:' + digest([row.get('source_pool'), row.get('org'), row.get('query'), row.get('channel'), identity])
        elif identity.startswith(('https://', 'http://')):
            identity = 'url:' + digest(identity)
        if '?' in identity or '#' in identity or '@' in identity or not _SAFE_ID.fullmatch(identity):
            raise ValueError('unsafe_source_entity_id')
        if identity in seen:
            raise ValueError('duplicate_source_entity_id')
        seen.add(identity)
        if row.get('_attempt_failed') or (team == 'institutions' and _institution_unavailable(row, failed_institutions)) or (team == 'channels' and str(row.get('probe_status', row.get('status', ''))).lower() in ('failed','failure','error','blocked')):
            if team != 'institutions':
                diagnostics['failed_sources'] += 1
            diagnostics['unavailable_ids'].add(identity)
            diagnostics['missing_records'] += 1
            continue
        if team in LOCAL_TEAMS:
            captured = _time(observed_at).isoformat()
        else:
            captured = _get(row, capture_field) or row.get('captured_at') or row.get('collected_at')
            if not captured and team == 'institutions' and row.get('source'):
                meta = (doc.get('sources') or {}).get(row['source']) or {}
                if meta.get('status') in ('ok', 'success'):
                    captured = meta.get('collected_at')
            if not captured and team == 'robotics':
                captured = row.get('_pool_capture')
            if not captured and team not in ('robotics', 'knowledge', 'design', 'channels'):
                captured = _get(doc, capture_field)
            if not captured:
                if team in PARTIAL_TEAMS:
                    diagnostics['missing_records'] += 1
                    diagnostics['unavailable_ids'].add(identity)
                    continue
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
        for key in list(selected):
            val = selected[key]
            if isinstance(val, dict):
                if team == 'graph' and key == 'summary':
                    selected[key] = {k: v for k, v in val.items()
                                     if k in ('repo_to_vault', 'vault_to_repo', 'conflicts', 'unchanged') and _number(v)}
                elif team == 'secretary' and key in ('latest_attempt', 'last_success'):
                    selected[key] = {k: v for k, v in val.items()
                                     if k in ('id', 'status', 'conclusion', 'event', 'created_at',
                                              'run_started_at', 'finished_at', 'run_attempt')
                                     and (v is None or isinstance(v, (str, int)))}
                else:
                    del selected[key]
            elif isinstance(val, list):
                if key in ('blocked_by', 'agent_blocked_by', 'blockers'):
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
    if not output:
        raise ValueError('source_capture_missing')
    return output


def _event_id(event):
    return digest({k: event[k] for k in ('type', 'source_team', 'source_entity_id', 'change')})


def _semantic_gate(value):
    if isinstance(value, dict):
        return {k: _semantic_gate(v) for k, v in value.items() if k not in ('generated_at', 'gate_generated_at')}
    if isinstance(value, list):
        return [_semantic_gate(v) for v in value]
    return value


def _verify_local_dependencies(base, team, doc):
    gate = doc if team == 'listing' else json.loads(_safe_source(base, 'data/listing_gate.json').read_text(encoding='utf-8-sig'))
    signature = gate.get('agent_input_signature') or {}
    allowed = ('data/product_master.json', 'data/gosi.json', 'data/daiso_real/daiso_us_labels.json',
               'data/pricing_model.json', 'data/legal_products.json', 'data/daiso_real/shopify_s_recommendations.json',
               'data/shopify_listing_copy.json', 'data/shopify_shortlist.json', 'data/legal_full.json',
               'data/mocra_readiness.json', 'data/manual/legal_rp_status.json', 'data/manual/mocra_business.json',
               'data/manual/official_label_text.json', 'data/manual/mocra_adverse_event_sop.md')
    hashes = signature.get('semantic_sources')
    if signature.get('schema_version') != 2 or not isinstance(hashes, dict) or set(hashes) != set(allowed):
        raise ValueError('derived_dependency_signature_missing_or_stale')
    for relative in allowed:
        source = _safe_source(base, relative)
        try:
            if relative.endswith('.md'):
                text = source.read_text(encoding='utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
                evidence = {'status': 'present', 'text': text}
            else:
                value = json.loads(source.read_text(encoding='utf-8-sig'))
                _json_valid(value)
                evidence = {'status': 'present', 'document': _semantic_gate(value)}
        except (OSError, ValueError):
            evidence = {'status': 'missing_or_unreadable'}
        if digest(evidence) != hashes.get(relative):
            raise ValueError('derived_dependency_signature_missing_or_stale')
    recommendations = json.loads(_safe_source(base, 'data/daiso_real/shopify_s_recommendations.json').read_text(encoding='utf-8-sig'))
    rows = [v for v in recommendations.get('recommendations', []) if isinstance(v, dict)]
    if digest(_semantic_gate(rows)) != signature.get('recommendations_sha256'):
        raise ValueError('derived_dependency_signature_missing_or_stale')


def _verify_shortlist_scope(base, doc):
    if doc.get('schema_version') != 1 or doc.get('scope') != 'active_shopify_shortlist_only' or doc.get('operating_catalog_mutated') is not False:
        raise ValueError('invalid_observation_scope')
    shortlist = json.loads(_safe_source(base, 'data/shopify_shortlist.json').read_text(encoding='utf-8-sig'))
    master = json.loads(_safe_source(base, 'data/product_master.json').read_text(encoding='utf-8-sig'))
    pd_nos = shortlist.get('active_pd_nos')
    if not isinstance(pd_nos, list) or not 1 <= len(pd_nos) <= 10 or len(set(pd_nos)) != len(pd_nos):
        raise ValueError('invalid_observation_scope')
    mapping = {str(v['pd_no']): v['canonical_product_id'] for v in master.get('products', [])
               if isinstance(v, dict) and v.get('pd_no') is not None and isinstance(v.get('canonical_product_id'), str)}
    expected = {mapping.get(str(v)) for v in pd_nos}
    if None in expected or not isinstance(doc.get('expected_ids'), list) or set(doc['expected_ids']) != expected or len(doc['expected_ids']) != len(expected):
        raise ValueError('invalid_observation_scope')
    for row in doc.get('products', []):
        if not isinstance(row, dict) or row.get('canonical_product_id') != mapping.get(str(row.get('pd_no'))) or row.get('canonical_product_id') not in expected:
            raise ValueError('invalid_observation_scope')
        source = row.get('source') or {}
        proof = row.get('provenance') or {}
        if source.get('capture_kind') != 'successful_http_parse' or proof.get('http_status') != 200 or proof.get('parse_status') != 'exact_pd_no_numeric_price' or proof.get('robots_checked') is not True or not _HASH.fullmatch(str(proof.get('response_sha256', ''))):
            raise ValueError('invalid_observation_provenance')
    return expected


def observe(root, previous=None, *, now=None, policy=None):
    """Observe fixed allowlisted files. Capture, read time and local derivation differ."""
    stamp = _time(now)
    settings = _settings(policy)
    state = _cursor(previous)
    base = Path(root).absolute()
    if not base.is_dir():
        raise ValueError('root must be an existing directory')
    watchers, events = [], []
    for team, (default_relative, _, _) in SOURCE_MAPPINGS.items():
        relative = default_relative
        watcher = {'watcher_id': 'watch:' + team, 'source_team': team,
                   'function': 'artifact_observation', 'is_agent': False,
                   'source': relative, 'status': 'BLOCKED', 'blockers': [],
                   'scope': {'channels':'candidate_probes_only_not_registered_connectors',
                             'institutions':'collected_records_with_provider_coverage',
                             'knowledge':'genuine_captured_items_excluding_registered_catalog'}.get(team),
                   'observation_kind': 'local_derived_read' if team in LOCAL_TEAMS else 'source_capture',
                   'unconnected': ['orders', 'customer_activity', 'new_ai_tools']}
        old = state['sources'].get(team)
        doc, diagnostics, expected = None, {}, None
        try:
            if team in ('sourcing', 'pricing') and _safe_source(base, SHORTLIST_OBSERVATIONS).exists():
                relative = SHORTLIST_OBSERVATIONS
                watcher.update(source=relative, scope='active_shopify_shortlist_only')
            source_path = _safe_source(base, relative)
            if source_path.stat().st_size > 20_000_000:
                raise ValueError('source_too_large')
            raw = source_path.read_bytes()
            doc = json.loads(raw.decode('utf-8-sig'), parse_constant=lambda v: (_ for _ in ()).throw(ValueError('non_finite_json')))
            _json_valid(doc)
            if not isinstance(doc, dict):
                raise ValueError('invalid_source_schema')
            watcher.update(observed_at=stamp.isoformat(), source_document_hash=sha256(raw).hexdigest())
            if relative == SHORTLIST_OBSERVATIONS:
                expected = _verify_shortlist_scope(base, doc)
            if team in LOCAL_TEAMS:
                _verify_local_dependencies(base, team, doc)
                watcher.update(warnings=['NOT_EXTERNAL_CAPTURE', 'BUSINESS_EVIDENCE_NOT_CLEARED'], captured_at=None)
            if (str(doc.get('status', '')).lower() in ('failed', 'failure', 'error', 'blocked', 'unavailable')
                    and team not in PARTIAL_TEAMS and expected is None):
                raise ValueError('source_reported_failure')
            records = _project(team, doc, observed_at=stamp, diagnostics=diagnostics)
            max_age = settings['team_max_age_seconds'].get(team, settings['max_age_seconds'])
            partial_allowed = team in PARTIAL_TEAMS or expected is not None
            for entity, row in list(records.items()):
                age = (stamp - _time(row['captured_at'])).total_seconds()
                if age < 0:
                    raise ValueError('source_capture_in_future')
                if age > max_age:
                    if not partial_allowed:
                        raise ValueError('stale_source_capture')
                    diagnostics['stale_records'] += 1
                    diagnostics['unavailable_ids'].add(entity)
                    del records[entity]
            if team in ('robotics','knowledge') and old:
                present_pools = set(doc.get('sources') or {})
                for entity, prior in old.get('records', {}).items():
                    pool = prior.get('value', {}).get('source_pool')
                    if pool in diagnostics['unavailable_pools'] or (pool and pool not in present_pools):
                        diagnostics['unavailable_ids'].add(entity)
                if any(v.get('value',{}).get('source_pool') not in present_pools for v in old.get('records',{}).values() if v.get('value',{}).get('source_pool')):
                    diagnostics['failed_sources'] += 1
            if team == 'institutions' and old:
                failed_institutions = _failed_institution_providers(doc)
                for entity, prior in old.get('records', {}).items():
                    if _institution_unavailable(prior.get('value', {}), failed_institutions):
                        diagnostics['unavailable_ids'].add(entity)
            if expected is not None:
                absent = expected - set(records)
                diagnostics['missing_records'] += len(absent - diagnostics['unavailable_ids'])
                diagnostics['unavailable_ids'].update(absent)
                diagnostics['total_records'] = len(expected)
            if not records:
                raise ValueError('stale_source_capture' if diagnostics.get('stale_records') else 'source_capture_missing')
            partial = bool(diagnostics['missing_records'] or diagnostics['stale_records'] or diagnostics['failed_sources'])
            if str(doc.get('status', '')).lower() in ('failed', 'failure', 'error', 'blocked', 'unavailable', 'partial') or (expected is not None and doc.get('complete') is False):
                partial = True
                diagnostics['failed_sources'] += max(1, len(doc.get('failed_ids') or []))
            coverage = {k: diagnostics[k] for k in ('total_records','missing_records','stale_records','failed_sources','catalog_only')}
            coverage['fresh_records'] = len(records)
            semantic = digest({k: v['value'] for k, v in records.items()})
            evidence_hash = digest(_semantic_gate(doc)) if team in LOCAL_TEAMS else digest(records)
            watcher.update(status='BASELINE', semantic_hash=semantic, source_hash=evidence_hash,
                           coverage=coverage, source_entity_ids=sorted(records))
            if team not in LOCAL_TEAMS:
                watcher['captured_at'] = min(v['captured_at'] for v in records.values())
            comparable = old and old['status'] == 'VALID' and old.get('source', relative) == relative
            if comparable:
                watcher['status'] = 'NO_CHANGE' if old['semantic_hash'] == semantic else 'CHANGED'
                for entity in sorted(set(old['records']) | set(records)):
                    if entity in diagnostics['unavailable_ids']:
                        continue  # Failed/missing observations are NOT removals.
                    before, after = old['records'].get(entity), records.get(entity)
                    bv, av = (before or {}).get('value'), (after or {}).get('value')
                    if bv == av:
                        continue
                    event_type = 'SOURCE_CHANGED'
                    if team == 'pricing':
                        if not bv or not av or any(bv.get(k) != av.get(k) for k in ('canonical_product_id','currency','unit','metric')):
                            continue
                        if bv['amount'] == av['amount']:
                            continue
                        event_type = 'PRICE_CHANGED'
                    event = {'type': event_type, 'source_team': team, 'source_entity_id': entity,
                             'captured_at': (after or before)['captured_at'],
                             'change': {'before_hash':digest(bv),'after_hash':digest(av),
                                        'kind':'added' if before is None else 'removed' if after is None else 'updated'},
                             'evidence': {'source':relative,'before_source_hash':digest(old['records']),
                                          'source_hash':evidence_hash,'before_entity_hash':digest(before),'entity_hash':digest(after)},
                             'observation_kind': watcher['observation_kind']}
                    if event_type == 'PRICE_CHANGED':
                        event['change'].update(before=bv['amount'],after=av['amount'],currency=av['currency'],unit=av['unit'])
                    event['event_id'] = _event_id(event)
                    if event['event_id'] not in state['seen_events']:
                        state['pending_events'][event['event_id']] = event
            retained = {k:v for k,v in (old or {}).get('records',{}).items() if k in diagnostics['unavailable_ids']}
            retained.update(records)
            state['sources'][team] = {'status':'VALID','source':relative,
                'semantic_hash':digest({k:v['value'] for k,v in retained.items()}),'records':retained}
            last = state['last_emitted'].get(team)
            cooldown = settings['team_cooldown_seconds'].get(team, settings['cooldown_seconds'])
            deadline = settings['deadlines'].get(team)
            eligible = last is None or (stamp-_time(last)).total_seconds() >= cooldown or (deadline is not None and stamp >= _time(deadline))
            pending = [e for e in state['pending_events'].values() if e['source_team'] == team]
            if eligible:
                for event in sorted(pending,key=lambda e:e['event_id']):
                    age = (stamp-_time(event['captured_at'])).total_seconds()
                    if age < 0 or age > max_age or event['source_entity_id'] in diagnostics['unavailable_ids'] or event['evidence'].get('source') != relative:
                        watcher['pending_blocked'] = 'STALE_OR_FUTURE_EVENT_EVIDENCE'
                        continue
                    if event['event_id'] not in state['seen_events']:
                        events.append(deepcopy(event))
                        state['seen_events'][event['event_id']] = stamp.isoformat()
                        state['last_emitted'][team] = stamp.isoformat()
                    del state['pending_events'][event['event_id']]
            elif pending:
                watcher['status'] = 'COOLDOWN'
            if team in LOCAL_TEAMS:
                watcher['change_status'] = watcher['status']
                watcher['status'] = 'LOCAL_VERIFIED'
            elif partial:
                watcher.update(status='PARTIAL', blockers=['PARTIAL_SOURCE_COVERAGE'])
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            safe_reasons = {'source_outside_root','source_too_large','invalid_source_schema','source_reported_failure',
                            'missing_or_empty_records','invalid_record_schema','source_entity_id_missing',
                            'unsafe_source_entity_id','duplicate_source_entity_id','source_capture_missing',
                            'canonical_price_identity_missing','invalid_measured_price','invalid_price_unit',
                            'source_capture_in_future','stale_source_capture','invalid_observation_scope',
                            'invalid_observation_provenance','derived_dependency_signature_missing_or_stale'}
            reason = str(exc)
            watcher['blockers'] = [reason.upper() if reason in safe_reasons else 'SOURCE_MISSING_INVALID_OR_STALE']
            watcher['failure_evidence_hash'] = digest({'source':relative,'reason':watcher['blockers'],
                                                      'document':_semantic_gate(doc) if isinstance(doc,dict) else None})
            state['sources'][team] = {'status':'BLOCKED','source':relative,'records':{}}
        if watcher['status'] == 'PARTIAL':
            watcher['failure_evidence_hash'] = digest({'source':relative,'coverage':watcher['coverage'],
                                                      'source_hash':watcher['source_hash']})
        watchers.append(watcher)
    return {'state':state,'watchers':watchers,'events':events}
