"""Future-only audit integrity, never authentication or business authority."""
from __future__ import annotations
import copy
import jarvis_operations as core
import jarvis_execution as execution

MAX_BYTES = 1024 * 1024
MAX_RECORDS = 100000


def bounded(value):
    remaining = 20000
    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 32:
            raise ValueError('audit bounds exceeded')
        if isinstance(item, dict):
            for k, v in item.items():
                if not isinstance(k, str):
                    raise ValueError('audit keys must be strings')
                visit(v, depth + 1)
        elif isinstance(item, list):
            for v in item:
                visit(v, depth + 1)
    visit(value, 0)
    if len(core.canonical(value).encode('utf-8')) > MAX_BYTES:
        raise ValueError('audit byte bound exceeded')
    return copy.deepcopy(value)


def _store(state):
    if 'audit' not in state:
        state['audit'] = {'schema_version': 1, 'mode': 'future_only',
            'start_sequence': state['sequence'] + 1, 'head': None,
            'payloads': {}, 'preparations': {}, 'outcomes': {}}
    return state['audit']


def _insert(table, key, value):
    value = bounded(value)
    if key in table and table[key] != value:
        raise ValueError('immutable audit conflict')
    if key not in table and len(table) >= MAX_RECORDS:
        raise ValueError('audit record bound exceeded')
    table.setdefault(key, value)


def approval_state(action):
    descriptor = execution.REGISTRY.get(action.get('kind'), {})
    local = descriptor.get('pure_read') is True or (
        action.get('kind') == 'snapshot_report' and descriptor.get('scope') == 'data/operations/reports/')
    return ('not_required_local' if descriptor.get('enabled') is True and
            descriptor.get('level') in (1, 2) and local else 'unavailable')


def event_metadata(state, event, supplied=None):
    store = _store(state)
    task = state['tasks'].get(event['task_id'], {})
    detail = event.get('detail') or {}
    proposal_id = detail.get('proposal_id') if isinstance(detail, dict) else None
    proposal = state['handoffs'].get(proposal_id, {})
    evidence = bounded(task.get('evidence') or {})
    meta = {'schema_version': 1, 'mode': 'future_only', 'reason_code': event['kind'],
        'reason': proposal.get('reason') or task.get('reason') or event['kind'],
        'evidence_hash': core.digest(evidence), 'evidence_ref': event['task_id'],
        'actor_role': 'secretary', 'actor_role_is_authproof': False,
        'external_authority': False, 'proposal_id': proposal_id}
    preparation = next((p for p in store['preparations'].values() if p['task_id'] == event['task_id']), None)
    if preparation:
        meta.update({k: preparation[k] for k in ('decision_id', 'action_id', 'action_hash', 'payload_hash', 'approval_state')})
        meta['preparation_id'] = preparation['preparation_id']
        meta['receipt_id'] = task.get('receipt_id')
    if supplied:
        meta.update(bounded(supplied))
    meta.update(previous=copy.deepcopy(store['head']), actor_role_is_authproof=False, external_authority=False)
    event['audit'] = bounded(meta)
    bounded(event)
    event['audit']['event_hash'] = core.digest(event)
    store['head'] = {'event_id': event['event_id'], 'event_hash': event['audit']['event_hash']}


def _emit(state, task_id, phase, record_id, **context):
    return core._event(state, 'TASK_AUDIT_' + phase, task_id, {'record_id': record_id}, audit=context)


def prepare(state, task_id, *, now=None):
    """Caller must persist before EXECUTING. Legacy execution is observation only."""
    validate(state)
    task = core._task(state, task_id)
    if task['state'] not in ('CREATED', 'ROUTED', 'IN_PROGRESS', 'VERIFYING', 'EXECUTING'):
        raise ValueError('audit preparation is future work only')
    action = bounded(execution._plain(execution.make_action(task)))
    store = _store(state)
    key = 'prepare_' + core.digest({'task_id': task_id, 'action_hash': action['action_hash']})
    if key in store['preparations']:
        return copy.deepcopy(store['preparations'][key])
    restart = task['state'] == 'EXECUTING'
    did = 'decision_' + core.digest({'task_id': task_id, 'kind': task['kind']})
    if not restart:
        state['decisions'].setdefault(did, {'decision_id': did, 'task_id': task_id,
            'kind': 'local_snapshot_review', 'status': 'PROPOSED',
            'reason': 'Saved snapshot review only; not business clearance', 'confidence': None,
            'evidence': bounded(task.get('evidence') or {})})
    if did not in state['decisions']:
        did = None
    record = {'preparation_id': key, 'task_id': task_id, 'action_id': action['action_id'],
        'action_hash': action['action_hash'], 'payload_hash': action['payload_hash'], 'decision_id': did,
        'decision_snapshot': bounded(state['decisions'][did]) if did else None,
        'evidence_hash': core.digest(task.get('evidence') or {}), 'approval_state': approval_state(action),
        'external_authority': False, 'actor_role_is_authproof': False,
        'observation': 'restart_observation' if restart else 'pre_execution_decision', 'at': core.utc(now)}
    record['record_hash'] = core.digest(record)
    _insert(store['payloads'], action['action_hash'], action)
    _insert(store['preparations'], key, record)
    _emit(state, task_id, 'RESTART_OBSERVATION' if restart else 'PREPARED', key,
          preparation_hash=record['record_hash'], decision_id=did, action_id=action['action_id'],
          action_hash=action['action_hash'], payload_hash=action['payload_hash'],
          approval_state=record['approval_state'], observation=record['observation'],
          reason_code='RESTART_OBSERVATION' if restart else 'LOCAL_SNAPSHOT_REVIEW',
          reason='Observed interrupted task; no prior decision asserted' if restart else record['decision_snapshot']['reason'])
    return copy.deepcopy(record)


def outcome(state, preparation, *, root, receipt=None, error=None, now=None):
    """Raw failed receipts are audit-only, never trusted state.receipts."""
    validate(state)
    store = _store(state)
    key = preparation['preparation_id']
    if store['preparations'].get(key) != preparation:
        raise ValueError('modified audit preparation')
    raw = bounded(receipt) if receipt is not None else None
    matching = isinstance(raw, dict) and raw.get('action') == store['payloads'][preparation['action_hash']]
    verified = bool(matching and execution.validate_receipt(root, raw))
    result = {'receipt': raw, 'error_code': type(error).__name__ if error else None,
        'status': 'VERIFIED' if verified else ('ERROR' if error else 'BLOCKED'),
        'actual_execution': verified, 'output_verified': verified,
        'proof_scope': 'verified_local_output' if verified else 'audit_only'}
    oid = 'outcome_' + core.digest({'preparation_id': key, 'phase': 'outcome', 'result': result})
    if oid in store['outcomes']:
        return copy.deepcopy(store['outcomes'][oid])
    record = {'outcome_id': oid, 'preparation_id': key, 'task_id': preparation['task_id'],
        'action_hash': preparation['action_hash'], 'result': result, 'at': core.utc(now)}
    record['record_hash'] = core.digest(record)
    _insert(store['outcomes'], oid, record)
    _emit(state, preparation['task_id'], 'OUTCOME', oid, outcome_id=oid,
          outcome_hash=record['record_hash'], decision_id=preparation['decision_id'],
          action_hash=preparation['action_hash'], receipt_id=raw.get('receipt_id') if isinstance(raw, dict) else None,
          result=result['status'], actual_execution=verified, output_verified=verified)
    return copy.deepcopy(record)


def validate(state, *, root=None):
    store = state.get('audit')
    if store is None:
        if any('audit' in e for e in state['events'].values()):
            raise ValueError('audit store missing')
        return
    if (store.get('schema_version') != 1 or store.get('mode') != 'future_only'
            or type(store.get('start_sequence')) is not int
            or not 1 <= store['start_sequence'] <= state['sequence'] + 1):
        raise ValueError('invalid audit schema')
    for name in ('payloads', 'preparations', 'outcomes'):
        if not isinstance(store.get(name), dict) or len(store[name]) > MAX_RECORDS:
            raise ValueError('invalid audit table')
    previous, linked = None, {}
    for event in sorted(state['events'].values(), key=lambda e: e.get('sequence', 0)):
        if not event.get('kind', '').startswith(('TASK_', 'HANDOFF_')):
            continue
        meta = event.get('audit')
        if meta is None:
            if event['sequence'] >= store['start_sequence']:
                raise ValueError('future audit event missing')
            continue
        bounded(event)
        unsigned = copy.deepcopy(event)
        recorded = unsigned['audit'].pop('event_hash', None)
        if (recorded != core.digest(unsigned) or meta.get('previous') != previous
                or meta.get('external_authority') is not False or meta.get('actor_role_is_authproof') is not False
                or ('approval_state' in meta and meta['approval_state'] not in ('not_required_local', 'unavailable'))):
            raise ValueError('audit chain modified')
        previous = {'event_id': event['event_id'], 'event_hash': recorded}
        if event['kind'].startswith('TASK_AUDIT_'):
            rid = (event.get('detail') or {}).get('record_id')
            if rid in linked:
                raise ValueError('duplicate audit phase')
            linked[rid] = meta
    if previous != store['head']:
        raise ValueError('audit head mismatch')
    for ah, action in store['payloads'].items():
        bounded(action)
        if (ah != action.get('action_hash') or execution.digest({k:v for k,v in action.items() if k != 'action_hash'}) != ah
                or execution.digest(action['payload']) != action.get('payload_hash')):
            raise ValueError('audit payload modified')
    used = set()
    for pid, prep in store['preparations'].items():
        bounded(prep)
        action = store['payloads'].get(prep.get('action_hash'))
        if (not action or action != execution._plain(execution.make_action(core._task(state, prep['task_id'])))
                or pid != 'prepare_' + core.digest({'task_id': prep['task_id'], 'action_hash': prep['action_hash']})
                or prep['approval_state'] != approval_state(action) or prep.get('external_authority') is not False
                or prep.get('actor_role_is_authproof') is not False
                or prep.get('observation') not in ('restart_observation', 'pre_execution_decision')
                or prep.get('record_hash') != core.digest({k:v for k,v in prep.items() if k != 'record_hash'})
                or linked.get(pid, {}).get('preparation_hash') != prep['record_hash']):
            raise ValueError('audit preparation modified')
        decision = prep.get('decision_snapshot')
        did = prep.get('decision_id')
        if did is not None:
            current = state['decisions'].get(did)
            mutable = ('status', 'action_id', 'receipt_id')
            if (not isinstance(decision, dict) or not isinstance(current, dict)
                    or {k:v for k,v in decision.items() if k not in mutable} !=
                       {k:v for k,v in current.items() if k not in mutable}
                    or not (current.get('status') == decision.get('status') or
                        (decision.get('status') == 'PROPOSED' and current.get('status') in
                         ('LOCAL_OUTPUT_VERIFIED', 'SOURCE_EVIDENCE_CHANGED_RECONCILIATION_REQUIRED')))):
                raise ValueError('audit decision context modified')
            if current.get('status') != 'PROPOSED' and (current.get('action_id') != action['action_id']
                    or current.get('receipt_id') not in state['receipts']):
                raise ValueError('audit decision output binding missing')
        elif decision is not None or prep['observation'] != 'restart_observation':
            raise ValueError('audit decision missing')
        used.add(prep['action_hash'])
    if used != set(store['payloads']):
        raise ValueError('orphan audit payload')
    for oid, record in store['outcomes'].items():
        bounded(record)
        prep = store['preparations'].get(record.get('preparation_id'))
        result = record.get('result', {})
        if (not prep or record.get('action_hash') != prep['action_hash'] or record.get('task_id') != prep['task_id']
                or oid != 'outcome_' + core.digest({'preparation_id': record['preparation_id'], 'phase':'outcome','result':result})
                or record.get('record_hash') != core.digest({k:v for k,v in record.items() if k != 'record_hash'})
                or linked.get(oid, {}).get('outcome_hash') != record['record_hash']
                or result.get('actual_execution') != (result.get('status') == 'VERIFIED')
                or result.get('output_verified') != (result.get('status') == 'VERIFIED')):
            raise ValueError('audit outcome modified')
        if result['status'] == 'VERIFIED':
            receipt = result.get('receipt')
            if (not isinstance(receipt, dict) or receipt.get('action') != store['payloads'][prep['action_hash']]
                    or (root is not None and not execution.validate_receipt(root, receipt))):
                raise ValueError('audit output proof not verified')
    if set(linked) != set(store['preparations']) | set(store['outcomes']):
        raise ValueError('audit record missing')


def project_summary(state):
    """Strict public allowlist: no text, identifiers, hashes, proofs or payloads."""
    validate(state)
    store = state.get('audit', {})
    events = list(state['events'].values())
    preps = list(store.get('preparations', {}).values())
    outcomes = list(store.get('outcomes', {}).values())
    return {'mode': 'future_only', 'external_authority': False, 'counts': {
        'audited': sum('audit' in e for e in events), 'legacy': sum('audit' not in e for e in events),
        'decisions': sum(p['observation'] == 'pre_execution_decision' for p in preps),
        'prepared': len(preps), 'outcomes': len(outcomes),
        'failure': sum(o['result']['status'] != 'VERIFIED' for o in outcomes),
        'unavailable': sum(p['approval_state'] == 'unavailable' for p in preps)}}
