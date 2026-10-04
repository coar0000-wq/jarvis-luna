"""Read-only operational feedback. No execution, model loading, training or writes.

Prediction/observation schema: metric, unit, entity_id (or canonical_entity_id),
cohort, horizon_seconds, window_start/end, kind, value. Probability observations
have kind='binary' and numeric value 0/1. Observations require status='VERIFIED',
observed_at, and source evidence with path/source and SHA256. All times need TZ.
Graph nodes/edges are lists with stable IDs. Source counts never imply confidence.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _time(value):
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        raise ValueError('timestamp_missing')
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('timezone_required')
    return result.astimezone(timezone.utc)


def _number(value):
    try:
        return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)
    except (OverflowError, TypeError):
        return False


def _confidence(record):
    value = record.get('confidence')
    return value if _number(value) and 0 <= value <= 1 else None


def _evidence(value):
    return [copy.deepcopy(value)] if isinstance(value, dict) else copy.deepcopy(value) if isinstance(value, list) else []


def _observed_evidence(record):
    return [e for e in _evidence(record.get('evidence')) if isinstance(e, dict)
            and isinstance(e.get('sha256', e.get('hash')), str)
            and len(e.get('sha256', e.get('hash'))) == 64
            and all(c in '0123456789abcdef' for c in e.get('sha256', e.get('hash')).lower())
            and (e.get('source') or e.get('path'))]


def evaluate_feedback(prediction, observation, *, now=None):
    """Require a mature, evidenced, dimensionally identical real observation."""
    result = {'status': 'awaiting_evidence', 'reason': 'missing_outcome', 'confidence': None,
              'evidence': [], 'score': None, 'training_allowed': False, 'promotion_allowed': False}
    if not isinstance(prediction, dict):
        return dict(result, status='invalid_prediction', reason='prediction_not_mapping')
    result['confidence'] = _confidence(prediction)
    if not isinstance(observation, dict) or observation.get('value') is None:
        return result
    result['evidence'] = _evidence(observation.get('evidence'))
    if observation.get('status') != 'VERIFIED' or not _observed_evidence(observation):
        return dict(result, reason='unverified_observation')
    for field in ('metric', 'unit', 'cohort'):
        if prediction.get(field) is None or observation.get(field) is None:
            return dict(result, reason='missing_' + field)
        if prediction[field] != observation[field]:
            return dict(result, status='not_comparable', reason=field + '_mismatch')
    p_entity = prediction.get('canonical_entity_id', prediction.get('entity_id'))
    o_entity = observation.get('canonical_entity_id', observation.get('entity_id'))
    if not isinstance(p_entity, str) or not p_entity or not isinstance(o_entity, str) or not o_entity:
        return dict(result, reason='missing_entity')
    if p_entity != o_entity:
        return dict(result, status='not_comparable', reason='entity_mismatch')
    try:
        current = _time(now) if now is not None else datetime.now(timezone.utc)
        ps, pe = _time(prediction.get('window_start')), _time(prediction.get('window_end'))
        os, oe = _time(observation.get('window_start')), _time(observation.get('window_end'))
        captured = _time(observation.get('observed_at'))
    except (TypeError, ValueError, OverflowError) as exc:
        return dict(result, status='not_comparable', reason='invalid_timestamp:' + str(exc))
    ph, oh = prediction.get('horizon_seconds'), observation.get('horizon_seconds')
    if not _number(ph) or not _number(oh) or ph <= 0 or oh <= 0:
        return dict(result, status='not_comparable', reason='invalid_horizon')
    if ph != oh:
        return dict(result, status='not_comparable', reason='horizon_mismatch')
    if ps >= pe or os >= oe:
        return dict(result, status='not_comparable', reason='invalid_window')
    if (pe - ps).total_seconds() != ph or (oe - os).total_seconds() != oh:
        return dict(result, status='not_comparable', reason='horizon_window_mismatch')
    if ps != os or pe != oe:
        return dict(result, status='not_comparable', reason='window_mismatch')
    if current < pe:
        return dict(result, reason='horizon_not_elapsed')
    if captured < oe or captured > current:
        return dict(result, reason='observation_time_invalid')
    pv, ov = prediction.get('value'), observation.get('value')
    if not _number(pv) or not _number(ov):
        return dict(result, status='not_comparable', reason='invalid_numeric_value')
    pk, ok = prediction.get('kind'), observation.get('kind')
    if pk == 'probability':
        if ok != 'binary' or prediction['unit'] != 'probability' or not 0 <= pv <= 1 or ov not in (0, 1):
            return dict(result, status='not_comparable', reason='probability_requires_binary_outcome')
        return dict(result, status='evaluated', reason='evidenced_binary_outcome',
                    score={'metric': 'brier', 'value': (pv - ov) ** 2}, predicted=pv, observed=ov,
                    calibration='requires_multiple_observations')
    if pk != 'numeric' or ok != 'numeric':
        return dict(result, status='not_comparable', reason='kind_mismatch')
    error = ov - pv
    if not math.isfinite(error):
        return dict(result, status='not_comparable', reason='numeric_overflow')
    return dict(result, status='evaluated', reason='evidenced_same_metric_outcome',
                score={'metric': 'signed_error', 'value': error}, predicted=pv, observed=ov)


def _records(state, name):
    value = state.get(name, {})
    return [(str(k), v) for k, v in sorted(value.items(), key=lambda p: str(p[0])) if isinstance(v, dict)] if isinstance(value, dict) else []


def _safe_file(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('unsafe_path')
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError('unsafe_path')
    return target


def _receipt_status(receipt, task, root):
    if receipt.get('status') != 'VERIFIED':
        return receipt.get('status') or 'UNKNOWN', 'receipt_not_verified'
    if not task or receipt.get('task_id') != task.get('id', task.get('task_id')):
        return 'INVALID', 'receipt_task_mismatch'
    if (receipt.get('issuer') != 'jarvis-execution-v1' or receipt.get('root_owned') is not True
            or receipt.get('output_verified') is not True):
        return 'INVALID', 'receipt_provenance_unverified'
    if receipt.get('receipt_hash') is not None and receipt['receipt_hash'] != _digest({k: v for k, v in receipt.items() if k != 'receipt_hash'}):
        return 'INVALID', 'receipt_hash_mismatch'
    if receipt.get('kind') not in ('snapshot_report', 'read_snapshot'):
        return 'INVALID', 'unsupported_external_receipt'
    if receipt.get('kind') != task.get('kind'):
        return 'INVALID', 'receipt_kind_mismatch'
    actual_payload_hash = _digest(task.get('payload') or {})
    if (receipt.get('payload_hash') != task.get('payload_hash', actual_payload_hash)
            or receipt.get('payload_hash') != actual_payload_hash):
        return 'INVALID', 'receipt_payload_hash_mismatch'
    outputs = receipt.get('outputs') or receipt.get('output_evidence')
    if isinstance(outputs, dict):
        outputs = [outputs]
    if not isinstance(outputs, list) or not outputs:
        return 'INVALID', 'missing_actual_output_evidence'
    for output in outputs:
        if not isinstance(output, dict):
            return 'INVALID', 'invalid_output_evidence'
        try:
            file = _safe_file(root, output.get('path'))
            actual = hashlib.sha256(file.read_bytes()).hexdigest()
        except (OSError, TypeError, ValueError):
            return 'INVALID', 'output_unavailable_or_unsafe'
        known_sources = {'data/product_team.json', 'data/institution_sources.json', 'data/market_team.json',
                         'data/listing_gate.json', 'data/pricing_model.json', 'data/legal_team.json',
                         'data/robotics_sources.json', 'data/design_team.json', 'data/channel_candidates.json',
                         'data/team_learning.json', 'data/knowledge/knowledge_graph.json'}
        relative = str(output.get('path', '')).replace(chr(92), '/')
        if receipt['kind'] == 'snapshot_report' and not relative.startswith('data/operations/reports/'):
            return 'INVALID', 'output_outside_report_scope'
        if receipt['kind'] == 'read_snapshot' and relative not in known_sources:
            return 'INVALID', 'output_outside_read_scope'
        if actual != output.get('sha256', output.get('hash')):
            return 'INVALID', 'receipt_output_hash_mismatch'
    return 'VERIFIED', 'actual_output_hash_verified'


def build(state, root, *, observations=None, now=None):
    """Pure projection; existing ledgers/thresholds are untouched and models never run."""
    if not isinstance(state, dict):
        raise TypeError('state must be a mapping')
    root = Path(root).resolve()
    nodes, edges, decisions, feedback = {}, {}, [], []
    stores = {name: dict(_records(state, name)) for name in ('tasks', 'actions', 'handoffs', 'decisions', 'receipts')}

    def add_node(kind, key, record):
        ident = kind + ':' + str(key)
        nodes[ident] = {'id': ident, 'type': kind, 'record_id': str(key),
                        'reason': copy.deepcopy(record.get('reason', record.get('audit_reason'))),
                        'evidence': _evidence(record.get('evidence')), 'confidence': _confidence(record),
                        'data': copy.deepcopy(record)}
        return ident

    def edge(source, relation, target, evidence):
        if source not in nodes or target not in nodes:
            return
        rec = {'source': source, 'relation': relation, 'target': target, 'evidence': copy.deepcopy(evidence)}
        rec['id'] = 'relation:' + _digest(rec)[:24]
        edges[rec['id']] = rec

    for name, kind in (('tasks', 'task'), ('actions', 'action'), ('handoffs', 'handoff'), ('decisions', 'decision'), ('receipts', 'receipt')):
        for key, record in stores[name].items():
            add_node(kind, key, record)
    for key, task in stores['tasks'].items():
        action = task.get('action')
        if isinstance(action, dict) and action.get('id', action.get('action_id')):
            action_key = str(action.get('id', action.get('action_id')))
            stores['actions'].setdefault(action_key, dict(action, task_id=key))
            add_node('action', action_key, stores['actions'][action_key])
    # A task's action intent is a proposal, never a completed execution.
    for key, task in stores['tasks'].items():
        if task.get('kind') and not any(a.get('task_id') == key for a in stores['actions'].values()):
            action_key = str(task.get('action_id') or ('intent:' + key))
            action = {'task_id': key, 'kind': task['kind'], 'payload': copy.deepcopy(task.get('payload') or {}),
                      'status': 'PROPOSED', 'evidence': [{'store': 'tasks', 'record_id': key, 'field': 'kind'}]}
            stores['actions'][action_key] = action
            add_node('action', action_key, action)
    task_receipts = {}
    for key, receipt in stores['receipts'].items():
        task_id = str(receipt.get('task_id', ''))
        task = stores['tasks'].get(task_id)
        status, reason = _receipt_status(receipt, dict(task, id=task_id) if task else None, root)
        nodes['receipt:' + key].update(receipt_status=status, verification_reason=reason)
        task_receipts.setdefault(task_id, []).append({'id': key, 'status': status, 'reason': reason})
        edge('receipt:' + key, 'verifies' if status == 'VERIFIED' else 'reports_on', 'task:' + task_id,
             [{'store': 'receipts', 'record_id': key, 'record_hash': _digest(receipt), 'verification_reason': reason}])
        action_id = receipt.get('action_id') or (receipt.get('action') or {}).get('action_id')
        if action_id:
            edge('receipt:' + key, 'result_of', 'action:' + str(action_id), [{'store': 'receipts', 'record_id': key}])
    for key, task in stores['tasks'].items():
        receipts = task_receipts.get(key, [])
        verified = any(r['status'] == 'VERIFIED' for r in receipts)
        nodes['task:' + key].update(completed=verified, receipt_status='VERIFIED' if verified else 'AWAITING_EVIDENCE', receipts=receipts)
        for dependency in task.get('depends_on') or []:
            edge('task:' + key, 'depends_on', 'task:' + str(dependency), [{'store': 'tasks', 'record_id': key, 'field': 'depends_on'}])
        if task.get('parent_id'):
            edge('task:' + key, 'child_of', 'task:' + str(task['parent_id']), [{'store': 'tasks', 'record_id': key, 'field': 'parent_id'}])
    for name, kind in (('tasks', 'task'), ('actions', 'action'), ('handoffs', 'handoff'), ('decisions', 'decision')):
        for key, record in stores[name].items():
            source = kind + ':' + key
            evidence = [{'store': name, 'record_id': key, 'record_hash': _digest(record)}] + _evidence(record.get('evidence'))
            for field, target_kind, relation in (('task_id', 'task', 'concerns'), ('action_id', 'action', 'recommends'),
                    ('decision_id', 'decision', 'implements'), ('receipt_id', 'receipt', 'evidenced_by'),
                    ('child_task_id', 'task', 'routes_to'), ('child_id', 'task', 'routes_to')):
                if record.get(field):
                    edge(source, relation, target_kind + ':' + str(record[field]), evidence)
            explicit = []
            for obj in (record, record.get('payload') or {}):
                if not isinstance(obj, dict):
                    continue
                for field in ('canonical_entity_id', 'canonical_id', 'entity_id'):
                    if isinstance(obj.get(field), str) and obj[field]:
                        explicit.append(obj[field])
                for member in obj.get('canonical_members') or []:
                    if isinstance(member, str) and member:
                        explicit.append(member)
                    elif isinstance(member, dict) and isinstance(member.get('canonical_id'), str):
                        explicit.append(member['canonical_id'])
            for entity in sorted(set(explicit)):
                ident = 'entity:' + entity
                if ident not in nodes:
                    add_node('entity', entity, {'canonical_id': entity, 'evidence': evidence})
                edge(source, 'concerns_entity', ident, evidence)
    observations = observations if isinstance(observations, dict) else {}
    for key, record in stores['decisions'].items():
        item = {'id': key, 'reason': copy.deepcopy(record.get('reason', record.get('audit_reason'))),
                'evidence': _evidence(record.get('evidence')), 'confidence': _confidence(record),
                'task_id': record.get('task_id'), 'action_id': record.get('action_id'),
                'receipt_status': nodes.get('task:' + str(record.get('task_id')), {}).get('receipt_status', 'AWAITING_EVIDENCE'),
                'status': record.get('status', 'PROPOSED'), 'completed': False,
                'training_allowed': False, 'promotion_allowed': False}
        item['completed'] = item['receipt_status'] == 'VERIFIED'
        decisions.append(item)
        prediction = record.get('prediction')
        if isinstance(prediction, dict):
            observation = observations.get(key)
            evaluated = evaluate_feedback(prediction, observation, now=now)
            if evaluated['status'] == 'evaluated':
                valid = False
                for evidence in _observed_evidence(observation):
                    try:
                        file = _safe_file(root, evidence.get('path'))
                        raw = file.read_bytes()
                        valid = hashlib.sha256(raw).hexdigest() == evidence.get('sha256', evidence.get('hash'))
                        document = json.loads(raw)
                        records = document.get('observations', [document]) if isinstance(document, dict) else document
                        fields = ('metric', 'unit', 'cohort', 'horizon_seconds', 'kind', 'value')
                        def matches(actual):
                            if not isinstance(actual, dict) or not all(actual.get(f) == observation.get(f) for f in fields):
                                return False
                            if actual.get('canonical_entity_id', actual.get('entity_id')) != observation.get('canonical_entity_id', observation.get('entity_id')):
                                return False
                            return all(_time(actual.get(f)) == _time(observation.get(f)) for f in ('window_start', 'window_end', 'observed_at'))
                        valid = valid and isinstance(records, list) and any(matches(actual) for actual in records)
                    except (TypeError, ValueError, OSError):
                        valid = False
                    if not valid:
                        break
                if not valid:
                    evaluated.update(status='awaiting_evidence', reason='observation_source_hash_unverified', score=None)
            feedback.append(dict(evaluated, decision_id=key))
    return {'decisions': decisions, 'knowledge_graph': {'nodes': list(nodes.values()), 'edges': list(edges.values())}, 'feedback': feedback}
