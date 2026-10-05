"""Exact-byte gosi history. Diagnostic replacement only; no factual exemptions."""
from __future__ import annotations
from copy import deepcopy
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from scripts.moe_evaluation_history import (LOCK_PATH, MANIFEST_PATH, MAX_REPORTS, atomic_write, exact_head, safe_path, sha, sync_dir)
from scripts.immutable_snapshot_store import retain_snapshots
from scripts.publish_transaction import removed_identities

REPORT_PATH = 'data/gosi.json'
HISTORY_PATH = 'data/knowledge/gosi_observation_history'
POLICY_REF = 'scripts/gosi_observation_history.py'
FIELDS = ('volume', 'ingredients', 'maker', 'origin', 'warnings', 'expiry', 'functional', 'usage')

def validate_document(doc):
    if not isinstance(doc, dict) or not isinstance(doc.get('items'), dict):
        raise ValueError('gosi items must be an object; list conversion is forbidden')
    for pid, row in doc['items'].items():
        if not isinstance(pid, str) or not pid.strip() or not isinstance(row, dict):
            raise ValueError('invalid gosi row shape')
        for key in ('product_id', 'pd_no'):
            if key in row and (not isinstance(row[key], str) or row[key] != pid):
                raise ValueError('gosi identity mismatch')
        for key in FIELDS:
            if key in row and not isinstance(row[key], str):
                raise ValueError('gosi fact must be text')
        for key in ('detail_images', 'gosi_images', 'detail_image_paths'):
            if key in row and (not isinstance(row[key], list) or any(not isinstance(x, str) or not x for x in row[key])):
                raise ValueError('image list malformed')
    return doc['items']

class ProviderStop(RuntimeError):
    def __init__(self, provider, code, category='auth_or_quota'):
        super().__init__(f'{provider}: {category} circuit stopped ({code})')
        self.provider, self.code, self.category = provider, code, category

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def receipt(raw, source, scope='source_response'):
    return {'source': source, 'received_at': utcnow(), 'sha256': sha(raw),
            'byte_count': len(raw), 'capture_scope': scope, 'verified': False}

def classify_stop(exc, provider):
    code = getattr(exc, 'code', None) or getattr(exc, 'status_code', None)
    if callable(code):
        code = code()
    text = (type(exc).__name__ + ' ' + str(exc) + ' ' + str(getattr(exc, 'reason', '')) + ' ' + str(code)).lower()
    if code in (401, 403, 429):
        return ProviderStop(provider, code, 'quota' if code == 429 else 'auth')
    if any(x in text for x in ('resource_exhausted', 'resourceexhausted', 'quota', 'too many requests', '429')):
        return ProviderStop(provider, 429, 'quota')
    if any(x in text for x in ('permission_denied', 'unauthenticated', 'api_key_invalid',
                              'invalid api key', 'api key not valid', 'authentication', 'invalid_grant', 'invalid credentials', 'permissiondenied', 'unauthorized', 'forbidden', '403', '401')):
        return ProviderStop(provider, 403, 'auth')
    return None

def assert_not_stopped(doc, providers):
    stops = doc.get('provider_stops', [])
    if not isinstance(stops, list) or any(not isinstance(x, dict) for x in stops):
        raise ValueError('invalid persisted circuit state')
    for stop in stops:
        if stop.get('provider') in providers:
            raise ProviderStop(stop['provider'], stop.get('code'), stop.get('category', 'persisted_stop'))

def persist_stop(doc, exc):
    event = {'provider': exc.provider, 'code': exc.code, 'category': exc.category, 'stopped_at': utcnow()}
    if not any(x.get('provider') == exc.provider for x in doc.get('provider_stops', [])):
        doc.setdefault('provider_stops', []).append(event)

def attempt(row, when, source, status, **details):
    row.setdefault('observation_attempts', []).append(dict(attempted_at=when, source=source, status=status, **details))

def observe_field(row, field, value, provenance):
    if field not in FIELDS or not isinstance(value, str) or not value.strip():
        return False
    value = value.strip()
    if row.get(field):
        if row[field] != value:
            row.setdefault('observation_conflicts', []).append({'field': field, 'retained_value': row[field], 'observed_value': value, 'provenance': deepcopy(provenance)})
            row['reconciliation_blocked'] = True
        return False
    row[field] = value
    row.setdefault('field_observations', {})[field] = dict(deepcopy(provenance), verified=False, stale=False)
    if row.get('verified') is True:
        row.setdefault('prior_verification', {'verified': True, 'fields': [k for k in FIELDS if k in row and k != field]})
    row['verified'] = False
    return True

def mark_stale(row):
    row['retained_source_stale'] = True
    for observations in ('field_observations', 'image_observations'):
        for observation in row.get(observations, {}).values():
            observation['stale'] = True

def merge_images(row, urls, paths, observations):
    for key, values in (('detail_images', urls), ('gosi_images', paths)):
        existing = row.setdefault(key, [])
        for value in values:
            if value not in existing:
                existing.append(value)
    if paths:
        row.setdefault('gosi_image', paths[0])
    for key, value in observations.items():
        row.setdefault('image_observations', {}).setdefault(key, deepcopy(value))

def replacement_ids(before, current, policy):
    validate_document(before)
    validate_document(current)
    contract = {'identity_fields': policy['identity_fields']}
    permitted = []
    def visit(old, new, where=()):
        allowed = where in {('vision_failures',), ('vision_deferred',)} or (len(where) == 3 and where[0] == 'items' and where[2] == '텍스트_미수집')
        if allowed:
            if not isinstance(old, list) or not isinstance(new, list):
                raise ValueError('diagnostic must remain list')
            if where[-1] == 'vision_failures':
                if any(not isinstance(x, dict) or set(x) != {'pd_no', 'reason'} or not all(isinstance(v, str) for v in x.values()) for x in old + new):
                    raise ValueError('failure diagnostic malformed')
            elif any(not isinstance(x, str) for x in old + new):
                raise ValueError('text diagnostic malformed')
            if where[-1] == '텍스트_미수집' and any(x not in FIELDS for x in old + new):
                raise ValueError('missing-field diagnostic malformed')
            permitted.extend(removed_identities(old, new, contract))
        elif isinstance(old, dict):
            if not isinstance(new, dict):
                raise ValueError('container replaced')
            for k, v in old.items():
                if k not in new:
                    raise ValueError('field removal forbidden')
                visit(v, new[k], where + (k,))
        elif isinstance(old, list):
            if not isinstance(new, list) or old != new[:len(old)]:
                raise ValueError('non-diagnostic list replacement forbidden')
        elif old != new:
            root_diagnostics = {'vision_status', 'vision_note', 'gosi_ok_count'}
            row_flags = {'reconciliation_blocked', 'retained_source_stale', 'verified'}
            allowed = (len(where) == 1 and where[0] in root_diagnostics)
            allowed |= (len(where) == 3 and where[0] == 'items' and where[2] in FIELDS and old == '' and isinstance(new, str) and bool(new.strip()) and isinstance(current['items'][where[1]].get('field_observations', {}).get(where[2]), dict))
            allowed |= (len(where) == 3 and where[0] == 'items' and where[2] in row_flags and
                        ((where[2] == 'verified' and new is False) or (where[2] != 'verified' and new is True)))
            allowed |= (len(where) == 5 and where[0] == 'items' and where[2] in {'field_observations', 'image_observations'} and where[4] == 'stale' and new is True)
            if not allowed:
                raise ValueError('non-diagnostic scalar overwrite forbidden')
    visit(before, current)
    actual = removed_identities(before, current, contract)
    if set(actual) != set(permitted):
        raise ValueError('non-diagnostic deletion forbidden')
    return sorted(set(actual))

def publish_observation(root, document):
    root = Path(root).absolute()
    validate_document(document)
    lock = safe_path(root, LOCK_PATH)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        base = exact_head(root, REPORT_PATH)
        target = safe_path(root, REPORT_PATH)
        prior = target.read_bytes()
        manifest_path = safe_path(root, MANIFEST_PATH)
        prior_manifest = manifest_path.read_bytes() if manifest_path.exists() else None
        current = (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
        policy = json.loads(safe_path(root, 'config/publish_policy.json').read_bytes())
        ids = replacement_ids(json.loads(base), document, policy)
        replacement_ids(json.loads(prior), document, policy)
        manifest = json.loads(prior_manifest) if prior_manifest else {'schema_version': 1, 'deletions': []}
        if not isinstance(manifest, dict) or manifest.get('schema_version') != 1 or not isinstance(manifest.get('deletions'), list) or any(not isinstance(x, dict) for x in manifest['deletions']):
            raise ValueError('invalid publication manifest')
        manifest = deepcopy(manifest)
        manifest['deletions'] = [x for x in manifest['deletions'] if not (x.get('path') == REPORT_PATH and x.get('policy_ref') == POLICY_REF)]
        if ids:
            manifest['deletions'].append({'path': REPORT_PATH, 'base_sha256': sha(base), 'replacement_sha256': sha(current), 'ids': ids, 'reason': 'Exact diagnostic replacement; immutable HEAD, prior and current gosi retained.', 'policy_ref': POLICY_REF, 'delete_file': False})
        retained = {sha(x): x for x in (base, prior, current)}
        retain_snapshots(root, HISTORY_PATH, retained, atomic_writer=atomic_write)
        if target.read_bytes() != prior or exact_head(root, REPORT_PATH) != base or (manifest_path.read_bytes() if manifest_path.exists() else None) != prior_manifest:
            raise ValueError('concurrent publication changed')
        atomic_write(root, MANIFEST_PATH, (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode())
        if target.read_bytes() != prior or exact_head(root, REPORT_PATH) != base:
            raise ValueError('concurrent gosi changed')
        atomic_write(root, REPORT_PATH, current)
        return {'baseline_sha256': sha(base), 'prior_sha256': sha(prior), 'current_sha256': sha(current), 'removed_ids': ids}
    finally:
        os.close(fd)
        lock.unlink()
        sync_dir(lock.parent)
