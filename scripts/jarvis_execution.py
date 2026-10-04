"""Fail-closed, offline execution boundary. No credentials, network or shell calls.

execute(..., persist=callback) requires callback(snapshot) to durably and atomically
save the entire ledger while the caller holds an exclusive transaction lock.
Alternatively pass ExecutionStore(root) as ledger; it owns locking and fsync.
A callback is a TRUSTED persistence capability, never task-provided data.
Verifier(action, proof) is also trusted server code, not an editable approval flag.
Only snapshot_report and read_snapshot dispatch. Repair/external descriptors are
intentionally blocked until separately reviewed implementation is installed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType


def _plain(value):
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value):
            raise ValueError('JSON keys must be strings')
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('non-finite number')
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise ValueError('not JSON data')


def canonical(value):
    return json.dumps(_plain(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


REGISTRY = _freeze({
    'read_snapshot': {'level': 1, 'enabled': True, 'pure_read': True, 'scope': 'known_team_artifacts'},
    'snapshot_report': {'level': 2, 'enabled': True, 'pure_read': False, 'scope': 'data/operations/reports/'},
    'rebuild_dashboard': {'level': 3, 'enabled': False, 'pure_read': False, 'scope': 'existing_reviewed_repair_hooks_only'},
    'repair_graph': {'level': 3, 'enabled': False, 'pure_read': False, 'scope': 'existing_reviewed_repair_hooks_only'},
    'shopify_create_draft': {'level': 4, 'enabled': False, 'pure_read': False, 'scope': 'external_disabled'},
    'shopify_update': {'level': 4, 'enabled': False, 'pure_read': False, 'scope': 'external_disabled'},
    'shopify_publish': {'level': 4, 'enabled': False, 'pure_read': False, 'scope': 'external_disabled'},
    'mail_send': {'level': 4, 'enabled': False, 'pure_read': False, 'scope': 'external_disabled'},
    'ad_publish': {'level': 4, 'enabled': False, 'pure_read': False, 'scope': 'external_disabled'},
    'data_delete': {'level': 4, 'enabled': False, 'pure_read': False, 'scope': 'external_disabled'},
    'repair_team_report': {'level': 3, 'enabled': False, 'pure_read': False, 'scope': 'existing_reviewed_repair_hooks_only'},
    'publish_listing': {'level': 4, 'enabled': False, 'pure_read': False, 'scope': 'external_disabled'},
    'update_inventory': {'level': 4, 'enabled': False, 'pure_read': False, 'scope': 'external_disabled'},
    'change_price': {'level': 4, 'enabled': False, 'pure_read': False, 'scope': 'external_disabled'},
    'send_message': {'level': 4, 'enabled': False, 'pure_read': False, 'scope': 'external_disabled'},
    'external_delete': {'level': 4, 'enabled': False, 'pure_read': False, 'scope': 'external_disabled'},
    'payment': {'level': 4, 'enabled': False, 'pure_read': False, 'scope': 'external_disabled'},
})
SOURCES = MappingProxyType({
    'sourcing': 'data/product_team.json', 'institutions': 'data/institution_sources.json',
    'market': 'data/market_team.json', 'listing': 'data/listing_gate.json',
    'pricing': 'data/pricing_model.json', 'legal': 'data/legal_team.json',
    'robotics': 'data/robotics_sources.json', 'design': 'data/design_team.json',
    'channels': 'data/channel_candidates.json', 'knowledge': 'data/team_learning.json',
    'graph': 'data/artifact_graph.json',
})
POLICY_HASH = digest({'version': 1, 'registry': REGISTRY, 'sources': SOURCES, 'stale_seconds': 86400})


def _time(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        raise ValueError('time must be an aware datetime or ISO timestamp')
    if dt.tzinfo is None:
        raise ValueError('timezone required')
    return dt.astimezone(timezone.utc)


def _safe(root, relative, *, reports=False):
    """No absolute, parent, drive, backslash, symlink or junction components."""
    root = Path(root).absolute()
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise ValueError('unsafe path')
    parts = relative.split('/')
    if any(p in ('', '.', '..') for p in parts) or relative.startswith('/'):
        raise ValueError('unsafe path')
    if reports and (parts[:3] != ['data', 'operations', 'reports'] or len(parts) != 4):
        raise ValueError('report scope denied')
    # Check root ancestors too; resolve() alone would silently permit a redirected root.
    for p in [root, *root.parents]:
        if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
            raise ValueError('symlink/junction denied')
    current = root
    for part in parts:
        current /= part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('symlink/junction denied')
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError('outside root')
    return current


def make_action(task, *, target=None, evidence_version=None):
    task = _plain(task)
    kind = task.get('kind', 'snapshot_report')
    if kind not in REGISTRY:
        raise ValueError('unknown action kind')
    task_id = task.get('id') or task.get('task_id')
    if not isinstance(task_id, str) or not task_id:
        raise ValueError('task ID required')
    payload = task.get('payload')
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError('payload must be object')
    team = task.get('team', 'sourcing')
    if team not in SOURCES:
        raise ValueError('unknown team')
    if target is None:
        target = task.get('target') or payload.get('target')
    if target is None and kind == 'snapshot_report':
        target = 'data/operations/reports/' + digest({'task': task_id})[:24] + '.json'
    if target is None and kind == 'read_snapshot':
        target = SOURCES[team]
    base = {'schema_version': 1, 'task_id': task_id, 'kind': kind,
            'level': REGISTRY[kind]['level'], 'team': team, 'target': target,
            'payload': payload, 'payload_hash': digest(payload),
            'canonical_members': task.get('canonical_members', payload.get('canonical_members', [])),
            'preconditions': task.get('preconditions', payload.get('preconditions', {})),
            'evidence_version': evidence_version if evidence_version is not None else task.get('evidence_version', digest(task.get('evidence') or {})),
            'policy_hash': POLICY_HASH,
            'expires_at': task.get('expires_at') or task.get('approval_expires_at'),
            'nonce': task.get('nonce')}
    # Stable per-intent nonce prevents replays across restart. Expiry is never invented.
    if base['nonce'] is None:
        base['nonce'] = digest({'intent': base})
    base['action_id'] = digest(base)
    base['idempotency_key'] = str(task.get('idempotency_key') or task_id)
    base['action_hash'] = digest(base)
    return _freeze(base)


def verify_approval(action, proof, *, verifier=None, now=None):
    action = _plain(action)
    if digest({k: v for k, v in action.items() if k != 'action_hash'}) != action.get('action_hash'):
        raise ValueError('action envelope changed')
    if not callable(verifier):
        raise ValueError('trusted human verifier missing')
    if not isinstance(proof, Mapping) or not action.get('target'):
        raise ValueError('approval proof/target missing')
    claims = verifier(_freeze(action), _freeze(_plain(proof)))
    if not isinstance(claims, Mapping) or claims.get('human_verified') is not True:
        raise ValueError('trusted human verification failed')
    required = ('action_hash', 'task_id', 'kind', 'target', 'payload_hash', 'canonical_members',
                'preconditions', 'evidence_version', 'policy_hash', 'nonce', 'expires_at')
    for key in required:
        if key not in claims or canonical(claims[key]) != canonical(action.get(key)):
            raise ValueError('approval binding mismatch: ' + key)
    if not isinstance(claims.get('nonce'), str) or not claims['nonce']:
        raise ValueError('nonce missing')
    if not claims.get('expires_at') or _time(claims['expires_at']) <= _time(now):
        raise ValueError('approval expired or missing expiry')
    if claims.get('revoked') is not False or claims.get('replayed') is not False:
        raise ValueError('revocation/replay not verified')
    if not isinstance(claims.get('approval_id'), str) or not claims['approval_id']:
        raise ValueError('approval ID missing')
    return {'approval_id': claims['approval_id'], 'nonce': claims['nonce'],
            'action_hash': action['action_hash'], 'expires_at': claims['expires_at']}


def _atomic(root, relative, value):
    dest = _safe(root, relative, reports=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest = _safe(root, relative, reports=True)
    fd, temp = tempfile.mkstemp(prefix='.execution-', dir=dest.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write((canonical(value) + '\n').encode())
            stream.flush()
            os.fsync(stream.fileno())
        _safe(root, relative, reports=True)
        os.replace(temp, dest)
        if os.name != 'nt':
            directory = os.open(dest.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return dest


class ExecutionStore:
    """Safe single-writer store. Stale lock needs explicit human reconciliation.

    No lock expiry or automatic replay after crash. Store paths cannot be changed.
    """
    filename = 'data/operations/reports/.execution-ledger.json'
    lockname = 'data/operations/reports/.execution-ledger.lock'

    def __init__(self, root):
        self.root = Path(root).absolute()

    @contextmanager
    def transaction(self):
        lock = _safe(self.root, self.lockname, reports=True)
        lock.parent.mkdir(parents=True, exist_ok=True)
        _safe(self.root, self.lockname, reports=True)
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, b'exclusive execution transaction; crash requires reconciliation\n')
            os.fsync(fd)
            file = _safe(self.root, self.filename, reports=True)
            ledger = json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
            if not isinstance(ledger, dict):
                raise ValueError('invalid execution ledger')
            yield ledger, lambda value: _atomic(self.root, self.filename, value)
        finally:
            os.close(fd)
            lock.unlink()


def _captured(data):
    if not isinstance(data, dict):
        return None
    for key in ('captured_at', 'observed_at', 'collected_at', 'last_successful_fetch'):
        if isinstance(data.get(key), str):
            return data[key]
    if isinstance(data.get('source'), dict):
        return _captured(data['source'])
    return None


def _read_source(root, team, now):
    relative = SOURCES[team]
    result = {'team': team, 'path': relative, 'confidence': None, 'captured_at': None,
              'sha256': None, 'freshness': 'unknown', 'blockers': []}
    try:
        file = _safe(root, relative)
        raw = file.read_bytes()
        result['sha256'] = hashlib.sha256(raw).hexdigest()
        data = json.loads(raw)
        canonical(data)  # reject NaN and unsupported JSON values
        captured = _captured(data)
        result['captured_at'] = captured
        if captured is None:
            result['blockers'].append('source_timestamp_missing')
        else:
            age = (_time(now) - _time(captured)).total_seconds()
            result['freshness'] = 'future' if age < 0 else 'stale' if age > 86400 else 'fresh'
            if result['freshness'] != 'fresh':
                result['blockers'].append('source_' + result['freshness'])
    except FileNotFoundError:
        result['blockers'].append('source_missing')
    except (ValueError, OSError, TypeError):
        result['blockers'].append('source_invalid_or_unsafe')
    return result


def _snapshot(root, action, now):
    payload = action['payload']
    teams = payload.get('teams', [action['team']])
    if not isinstance(teams, (list, tuple)) or not teams or len(teams) > len(SOURCES):
        raise ValueError('invalid source teams')
    if any(t not in SOURCES for t in teams):
        raise ValueError('unknown source team')
    sources = [_read_source(root, t, now) for t in dict.fromkeys(teams)]
    report = {'schema_version': 1, 'task_id': action['task_id'], 'action_hash': action['action_hash'],
            'generated_at': _time(now).isoformat(), 'sources': sources, 'confidence': None,
            'blockers': [{'team': s['team'], 'reason': b} for s in sources for b in s['blockers']],
            'business_clearance': False, 'canonical_mutations': False}
    if payload.get('purpose') == 'verify_actual_watch_recovery_only':
        # Fixed pure reads only. A payload flag cannot register network/repair authority.
        import jarvis_watch
        recovery_id, source_team = payload.get('recovery_id'), payload.get('watcher_team')
        if not isinstance(recovery_id, str) or source_team not in jarvis_watch.SOURCE_MAPPINGS:
            raise ValueError('invalid source recovery context')
        config = _safe(root, 'config/jarvis_operations_policy.json')
        policy = json.loads(config.read_text(encoding='utf-8')).get('watch') if config.exists() else None
        observed = jarvis_watch.observe(root, now=now, policy=policy)
        watcher = next(w for w in observed['watchers'] if w['source_team'] == source_team)
        keys = ('source_team','source','status','source_hash','captured_at','observed_at','observation_kind','coverage')
        report['source_recovery_evidence'] = {'recovery_id':recovery_id, **{k:watcher.get(k) for k in keys}}
        report['sources'].append({'team':action['team'],'path':watcher['source'],
            'sha256':watcher.get('source_document_hash'),'captured_at':watcher.get('captured_at'),
            'observed_at':watcher.get('observed_at'),'freshness':'actual_watch_scope_only',
            'blockers':list(watcher.get('blockers') or [])})
    return report


def _receipt(action, status, reason=None, **extra):
    result = {'schema_version': 1, 'task_id': action.get('task_id'), 'kind': action.get('kind'),
              'action_hash': action.get('action_hash'), 'payload_hash': action.get('payload_hash'),
              'idempotency_key': action.get('idempotency_key'), 'target': action.get('target'),
              'status': status, 'verified': status == 'VERIFIED', 'reason': reason,
              'level': action.get('level'), 'issuer': 'jarvis-execution-v1',
              'root_owned': status == 'VERIFIED', 'output_verified': status == 'VERIFIED',
              'action': _plain(action), **extra}
    result['receipt_id'] = 'receipt-' + digest({'action': action.get('action_hash'), 'status': status})
    result['receipt_hash'] = digest(result)
    return result


def _valid_prior(root, receipt, action):
    if not isinstance(receipt, dict) or receipt.get('status') != 'VERIFIED':
        return False
    if digest({k: v for k, v in receipt.items() if k != 'receipt_hash'}) != receipt.get('receipt_hash'):
        return False
    if receipt.get('action_hash') != action['action_hash']:
        return False
    for output in receipt.get('outputs', []):
        try:
            file = _safe(root, output['path'], reports=action['kind'] == 'snapshot_report')
            if hashlib.sha256(file.read_bytes()).hexdigest() != output['sha256']:
                return False
        except (OSError, ValueError, KeyError):
            return False
    return bool(receipt.get('outputs'))


def execute(root, task, ledger, *, approval=None, verifier=None, adapter=None, now=None, persist=None):
    """Receipt, never fabricated dispatch success. See module persistence contract."""
    if isinstance(ledger, ExecutionStore):
        if Path(root).absolute() != ledger.root:
            return _receipt({}, 'BLOCKED', 'store root mismatch')
        try:
            with ledger.transaction() as (data, save):
                return execute(root, task, data, approval=approval, verifier=verifier,
                               adapter=adapter, now=now, persist=save)
        except FileExistsError:
            return _receipt({}, 'RECONCILIATION_REQUIRED', 'exclusive lock exists; global stop')
        except (ValueError, OSError):
            return _receipt({}, 'BLOCKED', 'execution store unavailable')
    try:
        action = make_action(task)
        when = _time(now)
    except (ValueError, TypeError):
        return _receipt({}, 'BLOCKED', 'invalid action')
    if not isinstance(ledger, dict) or not callable(persist):
        return _receipt(action, 'BLOCKED', 'durable atomic persistence required')
    if adapter is not None:
        return _receipt(action, 'BLOCKED', 'untrusted adapters cannot register capabilities')
    if not REGISTRY[action['kind']]['enabled']:
        return _receipt(action, 'BLOCKED', 'connector/repair capability disabled by server policy')
    if ledger.get('global_stop'):
        return _receipt(action, 'RECONCILIATION_REQUIRED', 'global stop pending reconciliation')
    claims = ledger.setdefault('claims', {})
    key = action['idempotency_key']
    old = claims.get(key)

    def stop(reason):
        ledger['global_stop'] = True
        ledger.setdefault('action_stops', {})[key] = reason
        receipt = _receipt(action, 'RECONCILIATION_REQUIRED', reason)
        if old is not None:
            old['status'] = 'RECONCILIATION_REQUIRED'
        try:
            persist(copy.deepcopy(ledger))
        except Exception:
            receipt['reason'] += '; durable stop save failed, prior claim still blocks replay'
            receipt['receipt_hash'] = digest({k: v for k, v in receipt.items() if k != 'receipt_hash'})
        return receipt

    interrupted = [k for k, v in claims.items() if v.get('status') in ('CLAIMED', 'RECONCILIATION_REQUIRED')]
    if interrupted:
        for interrupted_key in interrupted:
            ledger.setdefault('action_stops', {})[interrupted_key] = 'unresolved durable claim'
        return stop('unresolved durable claim; global reconciliation required')
    if old:
        if old.get('action_hash') != action['action_hash']:
            return stop('idempotency key reused with changed action/payload')
        if old.get('status') == 'VERIFIED' and _valid_prior(root, old.get('receipt'), action):
            return copy.deepcopy(old['receipt'])
        return stop('previous claim/output requires reconciliation; no redispatch')
    try:
        if action['kind'] == 'snapshot_report':
            dest = _safe(root, action['target'], reports=True)
            if not dest.name.endswith('.json') or dest.name.startswith('.'):
                raise ValueError('report filename must be non-hidden JSON')
            if dest.exists():
                raise ValueError('unclaimed report already exists')
        elif action['target'] != SOURCES[action['team']]:
            raise ValueError('read target outside known team artifact')
        if action['level'] >= 3 or approval is not None:
            authorized = verify_approval(action, approval, verifier=verifier, now=when)
            used = ledger.setdefault('used_nonces', {})
            if authorized['nonce'] in used:
                raise ValueError('approval nonce replay')
            used[authorized['nonce']] = action['action_hash']
        claims[key] = {'action_hash': action['action_hash'], 'status': 'CLAIMED', 'claimed_at': when.isoformat()}
        persist(copy.deepcopy(ledger))
    except Exception as exc:
        if key in claims:
            old = claims[key]
            return stop('claim persistence failed; dispatch not attempted')
        return _receipt(action, 'BLOCKED', str(exc))
    old = claims[key]
    try:
        if action['kind'] == 'snapshot_report':
            report = _snapshot(root, action, when)
            output = _atomic(root, action['target'], report)
            raw = output.read_bytes()
            if json.loads(raw) != report:
                raise ValueError('report readback mismatch')
            outputs = [{'path': action['target'], 'sha256': hashlib.sha256(raw).hexdigest()}]
            details = {'source_evidence': report['sources'], 'blockers': report['blockers'], 'confidence': None}
            if 'source_recovery_evidence' in report:
                details['source_recovery_evidence'] = report['source_recovery_evidence']
        else:
            # Only a proven pure local read can retry once. No API/auth/quota calls exist.
            for attempt in range(2):
                try:
                    source = _safe(root, action['target'])
                    raw = source.read_bytes()
                    canonical(json.loads(raw))
                    break
                except (InterruptedError, BlockingIOError):
                    if attempt:
                        raise
            outputs = [{'path': action['target'], 'sha256': hashlib.sha256(raw).hexdigest()}]
            details = {'confidence': None, 'source_evidence': [{'team': action['team'],
                       'path': action['target'], 'sha256': hashlib.sha256(raw).hexdigest(),
                       'captured_at': _captured(json.loads(raw)), 'confidence': None}]}
        outputs = [{**o, 'captured_at': when.isoformat()} for o in outputs]
        result = _receipt(action, 'VERIFIED', outputs=outputs, evidence_hash=digest(outputs),
                          completed_at=when.isoformat(), started_at=old['claimed_at'], ended_at=when.isoformat(),
                          output_evidence=outputs,
                          business_clearance=False, **details)
        if not _valid_prior(root, result, action):
            raise ValueError('output evidence changed before commit')
        ended = _time(now).isoformat()
        result.update(completed_at=ended, ended_at=ended)
        for output in result['outputs']:
            output['captured_at'] = ended
        result['receipt_hash'] = digest({k: v for k, v in result.items() if k != 'receipt_hash'})
        old.update(status='VERIFIED', receipt=result)
        persist(copy.deepcopy(ledger))
        return result
    except Exception:
        return stop('dispatch or receipt commit ambiguous; no retry')


def validate_receipt(root, receipt, ledger=None):
    """Revalidate trusted durable claim, complete binding, and actual file bytes.

    Pass the same durable ledger used by execute, or omit for ExecutionStore's
    default file. A caller-supplied ledger is trusted storage, not approval data.
    Returns bool; public flags or self-computed receipt hashes are not authority.
    """
    try:
        if isinstance(ledger, ExecutionStore):
            if ledger.root != Path(root).absolute():
                return False
            ledger = None
        if ledger is None:
            file = _safe(root, ExecutionStore.filename, reports=True)
            ledger = json.loads(file.read_text(encoding='utf-8'))
        if not isinstance(ledger, dict) or ledger.get('global_stop'):
            return False
        if not isinstance(receipt, dict):
            return False
        action = receipt['action']
        if not isinstance(action, dict):
            return False
        kind = action['kind']
        if kind not in REGISTRY or not REGISTRY[kind]['enabled']:
            return False
        if action['policy_hash'] != POLICY_HASH or action['level'] != REGISTRY[kind]['level']:
            return False
        if digest({k: v for k, v in action.items() if k != 'action_hash'}) != action['action_hash']:
            return False
        if digest(action['payload']) != action['payload_hash']:
            return False
        for key in ('task_id', 'kind', 'level', 'payload_hash', 'action_hash', 'idempotency_key', 'target'):
            if receipt.get(key) != action[key]:
                return False
        claim = ledger.get('claims', {}).get(action['idempotency_key'], {})
        if claim.get('status') != 'VERIFIED' or claim.get('action_hash') != action['action_hash']:
            return False
        if canonical(claim.get('receipt')) != canonical(receipt):
            return False
        if receipt.get('issuer') != 'jarvis-execution-v1' or receipt.get('root_owned') is not True or receipt.get('output_verified') is not True:
            return False
        outputs = receipt['outputs']
        if len(outputs) != 1 or outputs[0]['path'] != action['target']:
            return False
        if kind == 'read_snapshot' and action['target'] != SOURCES[action['team']]:
            return False
        if receipt.get('output_evidence') != outputs:
            return False
        if not _valid_prior(root, receipt, action):
            return False
        if kind == 'snapshot_report':
            report = json.loads(_safe(root, action['target'], reports=True).read_text(encoding='utf-8'))
            if report.get('action_hash') != action['action_hash'] or report.get('task_id') != action['task_id']:
                return False
            if report.get('sources') != receipt.get('source_evidence') or report.get('business_clearance') is not False:
                return False
            if action['payload'].get('purpose') == 'verify_actual_watch_recovery_only':
                evidence = report.get('source_recovery_evidence')
                if not isinstance(evidence, dict) or evidence != receipt.get('source_recovery_evidence'):
                    return False
                if evidence.get('recovery_id') != action['payload'].get('recovery_id') or evidence.get('source_team') != action['payload'].get('watcher_team'):
                    return False
        return True
    except (KeyError, TypeError, ValueError, OSError):
        return False
