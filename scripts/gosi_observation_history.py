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
from scripts.gosi_image_sources import valid_denial_diagnostic

REPORT_PATH = 'data/gosi.json'
HISTORY_PATH = 'data/knowledge/gosi_observation_history'
POLICY_REF = 'scripts/gosi_observation_history.py'
FIELDS = ('volume', 'ingredients', 'maker', 'origin', 'warnings', 'expiry', 'functional', 'usage')

CONTINUITY_PROOF = '.gosi-safety-verified.json'
CONTINUITY_PENDING = '.gosi-safety-restore.pending'
COLLECTION_PENDING = '.gosi-collection.pending'


def require_continuity(root, *, forensic=False):
    """Fail closed on interrupted work; Actions also needs authenticated restore.

    Local/offline parser users do not acquire a network dependency. The proof is
    a local receipt written only by the authenticated restore entrypoint, never
    a substitute for GitHub authentication or a provider-success receipt.
    """
    root = Path(root).absolute()
    if not forensic:
        for name in (CONTINUITY_PENDING, COLLECTION_PENDING):
            if safe_path(root, name).exists():
                raise ValueError('gosi continuity reconciliation required')
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        return
    path = safe_path(root, CONTINUITY_PROOF)
    if not path.is_file() or path.stat().st_size > 512 * 1024:
        raise ValueError('gosi authenticated continuity proof required')
    proof = json.loads(path.read_bytes())
    import subprocess
    head = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                          capture_output=True, check=True).stdout.decode().strip()
    expected = {key: os.environ.get(env) for key, env in (
        ('repository', 'GITHUB_REPOSITORY'), ('run_id', 'GITHUB_RUN_ID'),
        ('run_attempt', 'GITHUB_RUN_ATTEMPT'))}
    if (proof.get('schema_version') != 1 or proof.get('head') != head
            or proof.get('event_sha') != os.environ.get('GITHUB_SHA', head)
            or not all(value and proof.get(key) == value for key, value in expected.items())
            or not re.fullmatch(r'[0-9a-f]{64}', str(proof.get('baseline_sha256', '')))):
        raise ValueError('gosi continuity proof identity invalid')

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
        for key in ('image_observations', 'field_observations'):
            if key in row and (not isinstance(row[key], dict) or any(not isinstance(x, dict) for x in row[key].values())):
                raise ValueError('observation mapping malformed')
        for key in ('detail_images', 'gosi_images', 'detail_image_paths'):
            if key in row and (not isinstance(row[key], list) or any(not isinstance(x, str) or not x for x in row[key])):
                raise ValueError('image list malformed')
    for key in ('provider_stops', 'provider_stop_history'):
        for stop in doc.get(key, []):
            if isinstance(stop, dict) and 'diagnostic' in stop and not valid_denial_diagnostic(stop['diagnostic']):
                raise ValueError('provider denial evidence malformed')
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

def _http_stop_code(value):
    # Do not coerce floats, booleans, identifiers, or partial numeric strings.
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value in (401, 403, 429) else None
    if isinstance(value, str) and value.strip() in ('401', '403', '429'):
        return int(value.strip())
    return None

def classify_stop(exc, provider):
    # Read actual exception/response status fields and structured API errors.
    # A PIL decode error contains a BytesIO memory address, which can include
    # 401/403/429 without representing an HTTP response at all.
    sources = [exc, getattr(exc, 'response', None), getattr(exc, 'reason', None)]
    if isinstance(exc, str):
        try:
            sources.append(json.loads(exc))
        except (ValueError, TypeError):
            pass
    values = []
    for source in list(sources):
        if isinstance(source, dict) and isinstance(source.get('error'), dict):
            sources.append(source['error'])
    for source in sources:
        for key in ('code', 'status_code', 'status'):
            value = source.get(key) if isinstance(source, dict) else getattr(source, key, None)
            if callable(value):
                value = value()
            values.append(value)
            code = _http_stop_code(value)
            if code:
                return ProviderStop(provider, code, 'quota' if code == 429 else 'auth')
    text = (type(exc).__name__ + ' ' + str(exc) + ' ' +
            str(getattr(exc, 'reason', '')) + ' ' + ' '.join(map(str, values))).lower()
    # Some network wrappers only retain an explicit HTTP error description.
    # Never match a bare number in an address, URL, product ID, or error text.
    status = re.search(r'\bhttp(?:/\d(?:\.\d)?\s+|(?:\s+(?:error|status(?:\s+code)?))?[\s:=]+)(401|403|429)(?!\w)', text)
    if status:
        code = int(status.group(1))
        return ProviderStop(provider, code, 'quota' if code == 429 else 'auth')
    if any(x in text for x in ('resource_exhausted', 'resourceexhausted', 'quota', 'too many requests')):
        return ProviderStop(provider, 429, 'quota')
    if any(x in text for x in ('permission_denied', 'unauthenticated', 'api_key_invalid',
                              'invalid api key', 'api key not valid', 'authentication', 'invalid_grant', 'invalid credentials', 'permissiondenied', 'unauthorized', 'forbidden')):
        return ProviderStop(provider, 403, 'auth')
    return None

# 2026-10-16: 정지가 영구였다. 10-11 21:27 에 daiso 403·gemini 429 가 한 번씩 기록된 뒤 지우는 코드가
# 없어서, 고시 수집기 두 개가 그 뒤 모든 회차에 시작하자마자 멈췄다('다음 회차 재판독' 이 오지 않았다).
# 같은 날 다이소몰은 200 을 돌려줬다. 403/429 는 대개 일시적이다(IP 차단·일일 할당량).
# 그래서 정지에 대기 시간을 둔다. 대기 중에는 --force 로도 못 넘는다. 새 403/429 가 나면 타이머를 다시 건다.
# stopped_at 이 없거나 못 읽으면 계속 정지로 본다(실패하면 닫힌 쪽).
STOP_COOLDOWN_HOURS = {'auth': 24, 'quota': 24}


def _stop_expired(stop, now):
    try:
        at = datetime.fromisoformat(str(stop.get('stopped_at')).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return False
    if at.tzinfo is None:
        return False
    hours = STOP_COOLDOWN_HOURS.get(stop.get('category'), 24)
    return (now - at).total_seconds() >= hours * 3600


def assert_not_stopped(doc, providers, now=None):
    stops = doc.get('provider_stops', [])
    if not isinstance(stops, list) or any(not isinstance(x, dict) for x in stops):
        raise ValueError('invalid persisted circuit state')
    now = now or datetime.now(timezone.utc)
    active = [x for x in stops if not _stop_expired(x, now)]
    if len(active) != len(stops):
        # 지우지 않고 이력으로 옮긴다. 언제 막혔고 언제 풀렸는지는 남긴다.
        history = doc.setdefault('provider_stop_history', [])
        for x in stops:
            if x not in active:
                history.append(dict(x, expired_at=now.isoformat()))
        del history[:-50]
        doc['provider_stops'] = active
    for stop in active:
        if stop.get('provider') in providers:
            raise ProviderStop(stop['provider'], stop.get('code'), stop.get('category', 'persisted_stop'))

def persist_stop(doc, exc, *, stopped_at=None):
    if stopped_at is not None:
        when = datetime.fromisoformat(str(stopped_at).replace('Z', '+00:00'))
        if not isinstance(stopped_at, str) or when.tzinfo is None or when > datetime.now(timezone.utc):
            raise ValueError('invalid observed provider stop clock')
    event = {'provider': exc.provider, 'code': exc.code, 'category': exc.category,
             'stopped_at': stopped_at if stopped_at is not None else utcnow()}
    if getattr(exc, 'diagnostic', None):
        event['diagnostic'] = deepcopy(exc.diagnostic)
    stops = doc.setdefault('provider_stops', [])
    # 같은 공급자의 예전 정지가 남아 있으면 새 시각으로 바꾼다. 안 바꾸면 대기 시간이 다시 걸리지 않는다.
    stops[:] = [x for x in stops if x.get('provider') != exc.provider] + [event]

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
        # provider_stops 는 '지금 막힌 공급자' 상태라 대기 시간이 지나면 빠지고 새 정지는 시각이 바뀐다(2026-10-16).
        # 풀린 기록은 provider_stop_history 에 덧붙여 남는다(그 목록은 일반 규칙대로 추가만 허용).
        allowed = where in {('vision_failures',), ('vision_deferred',), ('provider_stops',)} or (len(where) == 3 and where[0] == 'items' and where[2] == '텍스트_미수집')
        if allowed:
            if not isinstance(old, list) or not isinstance(new, list):
                raise ValueError('diagnostic must remain list')
            if where == ('provider_stops',):
                if any(not isinstance(x, dict) or not set(x) <= {'provider', 'code', 'category', 'stopped_at', 'diagnostic'}
                       or not isinstance(x.get('provider'), str) for x in old + new):
                    raise ValueError('provider stop diagnostic malformed')
            elif where[-1] == 'vision_failures':
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
