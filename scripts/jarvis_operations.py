"""Pure durable controller helpers. Caller owns persistence, locks, trusted receipts.

No IO, API, dispatch, credentials, or new agents. Receipt verification here is
structural: the root MUST validate actual output files and the execution ledger
before inserting a receipt. Untrusted task results must never populate receipts.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from types import MappingProxyType

TEAMS = ('sourcing', 'institutions', 'market', 'listing', 'pricing', 'legal',
         'robotics', 'design', 'channels', 'knowledge', 'graph')
MAX_TASKS_PER_GOAL = 32
MAX_DEPTH = 6
READ_SOURCES = MappingProxyType({
    'sourcing': 'data/product_team.json',
    'institutions': 'data/institution_sources.json',
    'market': 'data/market_team.json',
    'listing': 'data/listing_gate.json',
    'pricing': 'data/pricing_model.json',
    'legal': 'data/legal_team.json',
    'robotics': 'data/robotics_sources.json',
    'design': 'data/design_team.json',
    'channels': 'data/channel_candidates.json',
    'knowledge': 'data/team_learning.json',
    'graph': 'data/knowledge/knowledge_graph.json',
})
ACTION_LEVELS = MappingProxyType({
    'read_snapshot': 1, 'snapshot_report': 2,
    'rebuild_dashboard': 3, 'repair_graph': 3,
    'shopify_create_draft': 4, 'shopify_update': 4, 'shopify_publish': 4,
    'mail_send': 4, 'ad_publish': 4, 'payment': 4, 'data_delete': 4,
})
STATES = frozenset(('CREATED', 'ROUTED', 'IN_PROGRESS', 'VERIFYING',
    'WAITING_APPROVAL', 'EXECUTING', 'COMPLETED', 'FAILED', 'BLOCKED', 'CANCELLED'))
_TRANSITIONS = {
    'CREATED': {'ROUTED', 'BLOCKED', 'CANCELLED'},
    'ROUTED': {'IN_PROGRESS', 'BLOCKED', 'CANCELLED'},
    'IN_PROGRESS': {'VERIFYING', 'WAITING_APPROVAL', 'FAILED', 'BLOCKED', 'CANCELLED'},
    'VERIFYING': {'EXECUTING', 'WAITING_APPROVAL', 'COMPLETED', 'FAILED', 'BLOCKED', 'CANCELLED'},
    'WAITING_APPROVAL': {'BLOCKED', 'CANCELLED'},
    'EXECUTING': {'COMPLETED', 'FAILED', 'BLOCKED'},
    'BLOCKED': {'ROUTED', 'CANCELLED'},
    'COMPLETED': set(), 'FAILED': set(), 'CANCELLED': set(),
}
_TABLES = ('tasks', 'handoffs', 'events', 'receipts', 'decisions', 'watch')
_ID_FIELDS = ('goal', 'team', 'kind', 'payload', 'depends_on', 'parent_id', 'priority', 'deadline', 'evidence')
_HASH = re.compile(r'^[0-9a-f]{64}$')


def _json_check(value):
    if value is None or isinstance(value, (str, bool)):
        return
    if type(value) is int:
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _json_check(item)
        return
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        for item in value.values():
            _json_check(item)
        return
    raise ValueError('Only finite, string-keyed JSON values are accepted')


def canonical(value):
    """Stable JSON; bool remains a distinct JSON type, never numeric coercion."""
    _json_check(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def utc(value=None):
    if value is None:
        value = datetime.now(timezone.utc)
    elif isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError as exc:
            raise ValueError('Invalid timestamp') from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Timezone-aware datetime required')
    return value.astimezone(timezone.utc).isoformat()


def action_level(kind):
    if not isinstance(kind, str) or kind not in ACTION_LEVELS:
        raise ValueError('Unknown action kind')
    return ACTION_LEVELS[kind]


def _text(value, name, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('Invalid ' + name)
    return ' '.join(value.split())


def _team(value):
    if not isinstance(value, str) or value not in TEAMS:
        raise ValueError('Unknown team')
    return value


def _priority(value):
    if not isinstance(value, str) or value not in ('low', 'normal', 'high', 'urgent'):
        raise ValueError('Invalid priority')
    return value


def route_intent(goal, forced_teams=None):
    goal = _text(goal, 'goal')
    teams = []
    if forced_teams is not None:
        if not isinstance(forced_teams, (list, tuple)) or not forced_teams:
            raise ValueError('forced_teams must be a nonempty team list')
        teams = list(dict.fromkeys(_team(t) for t in forced_teams))
    text = goal.casefold()
    report = any(w in text for w in ('report', 'snapshot', 'review', 'analysis', '보고', '검토', '분석'))
    request = any(w in text for w in ('publish', 'inventory', 'payment', 'send message', '게시', '결제'))
    hints = {
        'sourcing': ('sourcing', 'supplier', '소싱', '다이소'),
        'institutions': ('institution', '기관'), 'market': ('market', 'trend', '시장', '마케팅'),
        'listing': ('listing', 'shopify', '리스팅'), 'pricing': ('price', 'pricing', '가격'),
        'legal': ('legal', 'compliance', 'mocra', '법률', '규제'), 'robotics': ('robot', '로봇'),
        'design': ('design', '디자인'), 'channels': ('channel', '채널'),
        'knowledge': ('knowledge', '논문', '지식'), 'graph': ('graph', '그래프'),
    }
    inferred = [team for team, tokens in hints.items() if any(w in text for w in tokens)]
    teams = teams or inferred or (list(TEAMS) if report else [])
    known = report or (request and bool(inferred))
    return {'goal': goal, 'priority': 'normal', 'deadline': None,
            'teams_required': teams if known else [], 'approval_required': bool(request or not known),
            'method': ('request_only' if request else 'local_report') if known else 'blocked',
            'status': 'ROUTED' if known else 'BLOCKED'}


def empty_state():
    return {'schema_version': 1, **{key: {} for key in _TABLES}, 'sequence': 0}


def _state(state):
    if (not isinstance(state, dict) or type(state.get('schema_version')) is not int or state['schema_version'] != 1
        or any(not isinstance(state.get(k), dict) for k in _TABLES)
        or type(state.get('sequence')) is not int or state['sequence'] < 0):
        raise ValueError('Invalid durable state schema')
    if 'event_' + str(state['sequence'] + 1).zfill(12) in state['events']:
        raise ValueError('Sequence would overwrite an immutable event')


def _event(state, kind, task_id, detail=None, *, audit=None, at=None):
    import jarvis_audit
    jarvis_audit._store(state)
    event_id = 'event_' + str(state['sequence'] + 1).zfill(12)
    event = {'event_id': event_id, 'sequence': state['sequence'] + 1, 'kind': kind,
             'task_id': task_id, 'detail': copy.deepcopy(detail), 'at': utc(at)}
    jarvis_audit.event_metadata(state, event, audit)
    state['sequence'] += 1
    state['events'][event_id] = event
    return copy.deepcopy(event)


def _identity(task):
    return {k: task[k] for k in _ID_FIELDS}


def _task(state, task_id):
    _state(state)
    if not isinstance(task_id, str):
        raise ValueError('Invalid task ID')
    task = state['tasks'].get(task_id)
    if not isinstance(task, dict) or task.get('task_id') != task_id:
        raise ValueError('Unknown task')
    try:
        identity_hash = digest(_identity(task))
        if (identity_hash != task.get('context_hash') or 'task_' + identity_hash != task_id
            or digest(task['payload']) != task.get('payload_hash') or digest(task['goal']) != task.get('goal_id')
            or task.get('level') != action_level(task['kind']) or type(task.get('level')) is not int
            or task.get('state') not in STATES or type(task.get('depth')) is not int
            or not 1 <= task['depth'] <= MAX_DEPTH):
            raise ValueError('Modified task identity or policy')
        _team(task['team'])
        _priority(task['priority'])
        # Depth is derived from ancestry, never trusted as a caller counter.
        ancestor, seen, actual_depth = task, set(), 0
        while ancestor is not None:
            if not isinstance(ancestor, dict) or ancestor.get('task_id') in seen:
                raise ValueError('Unknown or cyclic task ancestry')
            seen.add(ancestor['task_id'])
            actual_depth += 1
            if actual_depth > MAX_DEPTH or ancestor.get('goal_id') != task['goal_id']:
                raise ValueError('Invalid task ancestry')
            parent_id = ancestor.get('parent_id')
            if parent_id is not None:
                if parent_id not in ancestor.get('depends_on', []):
                    raise ValueError('Parent must also be an execution dependency')
                ancestor = state['tasks'].get(parent_id)
                if ancestor is None:
                    raise ValueError('Unknown parent')
            else:
                ancestor = None
        if actual_depth != task['depth']:
            raise ValueError('Task depth was modified')
    except (KeyError, TypeError) as exc:
        raise ValueError('Malformed task') from exc
    return task


def _dependency_issue(state, task_id):
    visiting, done = set(), set()
    def walk(node):
        if node in visiting:
            return 'Dependency cycle'
        if node in done:
            return None
        try:
            task = _task(state, node)
        except ValueError:
            return 'Unknown or invalid dependency'
        visiting.add(node)
        pending = False
        for dep in task['depends_on']:
            issue = walk(dep)
            if issue and issue != 'Dependency awaiting verified completion':
                return issue
            target = state['tasks'][dep]
            if target['state'] in ('FAILED', 'CANCELLED', 'BLOCKED'):
                return 'Dependency unsuccessful or blocked'
            if issue or target['state'] != 'COMPLETED' or not _completion_valid(state, target):
                pending = True
        visiting.remove(node)
        done.add(node)
        return 'Dependency awaiting verified completion' if pending else None
    return walk(task_id)


def create_task(state, *, goal, team, kind='snapshot_report', payload=None, depends_on=None,
                parent_id=None, priority='normal', deadline=None, evidence=None):
    _state(state)
    goal, team = _text(goal, 'goal'), _team(team)
    level = action_level(kind)
    _priority(priority)
    payload = {} if payload is None else payload
    evidence = {} if evidence is None else evidence
    if not isinstance(payload, dict):
        raise ValueError('Payload must be an object')
    canonical(payload)
    canonical(evidence)
    depends_on = [] if depends_on is None else depends_on
    if not isinstance(depends_on, (list, tuple)) or any(not isinstance(d, str) or not d for d in depends_on):
        raise ValueError('Invalid dependencies')
    depends_on = sorted(set(depends_on))
    depth = 1
    if parent_id is not None:
        parent = _task(state, parent_id)
        if parent['goal'] != goal or parent['team'] != team:
            raise ValueError('Cross-team children require secretary handoff and same goal')
        depth = parent['depth'] + 1
        depends_on = sorted(set(depends_on + [parent_id]))
    deadline = None if deadline is None else utc(deadline)
    return _create(state, goal, team, kind, payload, depends_on, parent_id, priority, deadline, evidence, depth, level)


def _create(state, goal, team, kind, payload, depends_on, parent_id, priority, deadline, evidence, depth, level):
    if depth > MAX_DEPTH:
        raise ValueError('Depth limit exceeded')
    identity = dict(goal=goal, team=team, kind=kind, payload=copy.deepcopy(payload), depends_on=list(depends_on),
                    parent_id=parent_id, priority=priority, deadline=deadline, evidence=copy.deepcopy(evidence))
    context_hash = digest(identity)
    task_id = 'task_' + context_hash
    if task_id in depends_on:
        raise ValueError('Self dependency')
    if task_id in state['tasks']:
        return copy.deepcopy(_task(state, task_id))
    goal_id = digest(goal)
    if sum(isinstance(t, dict) and t.get('goal_id') == goal_id for t in state['tasks'].values()) >= MAX_TASKS_PER_GOAL:
        raise ValueError('Goal task bound exceeded')
    task = {**identity, 'task_id': task_id, 'goal_id': goal_id, 'context_hash': context_hash,
            'payload_hash': digest(payload), 'level': level, 'depth': depth, 'state': 'CREATED',
            'created_at': utc(), 'updated_at': utc(), 'source': {'controller': 'secretary', 'team': team},
            'ownership': {'team_lead': team, 'specialist': team + ':' + kind},
            'receipt_id': None, 'receipt_hash': None, 'result': None, 'reason': None}
    state['tasks'][task_id] = task
    issue = _dependency_issue(state, task_id)
    if issue and issue != 'Dependency awaiting verified completion':
        task['state'], task['reason'] = 'BLOCKED', issue
    _event(state, 'TASK_CREATED', task_id, {'state': task['state']})
    return copy.deepcopy(task)


def _verified_receipt(state, task, receipt):
    if not isinstance(receipt, dict) or not isinstance(receipt.get('receipt_id'), str):
        raise ValueError('Root-owned execution receipt required')
    stored = state['receipts'].get(receipt['receipt_id'])
    if not isinstance(stored, dict) or canonical(stored) != canonical(receipt):
        raise ValueError('Receipt not present in trusted root ledger')
    outputs = stored.get('output_evidence')
    if (stored.get('status') != 'VERIFIED' or stored.get('issuer') != 'jarvis-execution-v1'
        or stored.get('root_owned') is not True or stored.get('output_verified') is not True
        or stored.get('task_id') != task['task_id'] or stored.get('kind') != task['kind']
        or stored.get('payload_hash') != task['payload_hash'] or type(stored.get('level')) is not int
        or stored['level'] != action_level(task['kind'])
        or not isinstance(stored.get('action_hash'), str) or not _HASH.fullmatch(stored['action_hash'])
        or not isinstance(stored.get('idempotency_key'), str) or not stored['idempotency_key']
        or not isinstance(outputs, list) or len(outputs) != 1):
        raise ValueError('Receipt lacks verified execution/payload binding')
    for output in outputs:
        if (not isinstance(output, dict) or not isinstance(output.get('sha256'), str)
            or not _HASH.fullmatch(output['sha256']) or not isinstance(output.get('path'), str)
            or '\\' in output['path'] or '..' in output['path'].split('/')):
            raise ValueError('Hash-verified scoped output evidence required')
        output_path = output['path']
        if task['kind'] == 'read_snapshot':
            if output_path != READ_SOURCES[task['team']]:
                raise ValueError('Read snapshot must match its exact team source')
        elif task['kind'] == 'snapshot_report':
            if (not output_path.startswith('data/operations/reports/')
                or output_path == 'data/operations/reports/'):
                raise ValueError('Report output must be in the reports scope')
        else:
            raise ValueError('No verified output scope for this action kind')
        if not output.get('captured_at'):
            raise ValueError('Missing capture time')
        utc(output['captured_at'])
    for key in ('started_at', 'ended_at'):
        if not stored.get(key):
            raise ValueError('Execution timestamps required')
        utc(stored[key])
    if datetime.fromisoformat(utc(stored['ended_at'])) < datetime.fromisoformat(utc(stored['started_at'])):
        raise ValueError('Invalid execution time order')
    return stored


def _completion_valid(state, task):
    try:
        stored = _verified_receipt(state, task, state['receipts'].get(task.get('receipt_id')))
        return bool(task.get('receipt_hash') and digest(stored) == task['receipt_hash'])
    except (ValueError, TypeError):
        return False


def transition(state, task_id, new_state, *, result=None, reason=None, receipt=None):
    task = _task(state, task_id)
    if not isinstance(new_state, str) or new_state not in STATES or new_state not in _TRANSITIONS[task['state']]:
        raise ValueError('Unsafe, unsupported, or replayed transition')
    if result is not None:
        canonical(result)
    reason = None if reason is None else _text(reason, 'reason')
    if new_state in ('BLOCKED', 'FAILED', 'CANCELLED') and reason is None:
        raise ValueError('A reason is required')
    if new_state in ('IN_PROGRESS', 'VERIFYING', 'EXECUTING', 'COMPLETED'):
        issue = _dependency_issue(state, task_id)
        if issue:
            raise ValueError(issue)
    if new_state == 'EXECUTING' and task['level'] >= 3:
        raise ValueError('Privileged execution is not enabled by this controller')
    if new_state == 'COMPLETED':
        if task['level'] >= 3:
            raise ValueError('No enabled privileged execution capability')
        stored = _verified_receipt(state, task, receipt)
        if any(isinstance(t, dict) and t['task_id'] != task_id and t.get('receipt_id') == stored['receipt_id']
               for t in state['tasks'].values()):
            raise ValueError('Receipt already consumed')
        task['receipt_id'], task['receipt_hash'] = stored['receipt_id'], digest(stored)
        task['result'] = {'receipt_id': stored['receipt_id'], 'output_evidence': copy.deepcopy(stored['output_evidence']),
                          'result_schema': {'actual_execution': True, 'output_verified': True}}
    elif receipt is not None:
        raise ValueError('Receipt only accepted for completion')
    elif result is not None:
        task['progress'] = copy.deepcopy(result)
    old = task['state']
    task['state'], task['reason'], task['updated_at'] = new_state, reason, utc()
    _event(state, 'TASK_TRANSITION', task_id, {'from': old, 'to': new_state})
    return copy.deepcopy(task)


def _proposal_identity(proposal):
    return {k: proposal[k] for k in ('task_id', 'recommended_team', 'reason', 'kind', 'payload', 'priority')}


def propose_handoff(state, task_id, recommended_team, reason, *, kind='snapshot_report', payload=None, priority='normal'):
    parent = _task(state, task_id)
    recommended_team = _team(recommended_team)
    if recommended_team == parent['team']:
        raise ValueError('Handoff must recommend another existing team')
    reason = _text(reason, 'handoff reason')
    action_level(kind)
    _priority(priority)
    payload = {} if payload is None else payload
    if not isinstance(payload, dict):
        raise ValueError('Payload must be an object')
    identity = dict(task_id=task_id, recommended_team=recommended_team, reason=reason, kind=kind,
                    payload=copy.deepcopy(payload), priority=priority)
    proposal_id = 'handoff_' + digest(identity)
    if proposal_id in state['handoffs']:
        return copy.deepcopy(state['handoffs'][proposal_id])
    proposal = {**identity, 'proposal_id': proposal_id, 'context_hash': digest(identity),
                'status': 'PROPOSED', 'child_id': None, 'created_at': utc()}
    state['handoffs'][proposal_id] = proposal
    _event(state, 'HANDOFF_PROPOSED', task_id, {'proposal_id': proposal_id})
    return copy.deepcopy(proposal)


def accept_handoff(state, proposal_id, *, actor='secretary'):
    _state(state)
    if actor != 'secretary':
        raise ValueError('Only the secretary controller can accept handoffs')
    if not isinstance(proposal_id, str):
        raise ValueError('Invalid handoff ID')
    proposal = state['handoffs'].get(proposal_id)
    if not isinstance(proposal, dict):
        raise ValueError('Unknown handoff')
    try:
        identity_hash = digest(_proposal_identity(proposal))
        if (proposal.get('proposal_id') != proposal_id or proposal.get('context_hash') != identity_hash
            or proposal_id != 'handoff_' + identity_hash or proposal.get('status') != 'PROPOSED'):
            raise ValueError('Modified or replayed handoff')
    except (KeyError, TypeError) as exc:
        raise ValueError('Invalid handoff') from exc
    parent = _task(state, proposal['task_id'])
    if parent['state'] != 'COMPLETED' or not _completion_valid(state, parent):
        raise ValueError('Verified parent completion required')
    team = _team(proposal['recommended_team'])
    _priority(proposal['priority'])
    ancestor, seen = parent, set()
    while ancestor:
        if ancestor['task_id'] in seen or ancestor['team'] == team:
            raise ValueError('Handoff cycle or repeated ancestral team')
        seen.add(ancestor['task_id'])
        ancestor = _task(state, ancestor['parent_id']) if ancestor['parent_id'] else None
    child = _create(state, parent['goal'], team, proposal['kind'], proposal['payload'], [parent['task_id']],
                    parent['task_id'], proposal['priority'], parent['deadline'],
                    {'handoff_parent': parent['task_id'], 'receipt_id': parent['receipt_id'], 'receipt_hash': parent['receipt_hash']},
                    parent['depth'] + 1, action_level(proposal['kind']))
    proposal['status'], proposal['child_id'], proposal['accepted_at'] = 'ACCEPTED', child['task_id'], utc()
    _event(state, 'HANDOFF_ACCEPTED', parent['task_id'], {'proposal_id': proposal_id, 'child_id': child['task_id']})
    return child


def ready_tasks(state):
    _state(state)
    ready = []
    for task_id in sorted(state['tasks']):
        try:
            task = _task(state, task_id)
        except ValueError:
            continue
        if task['state'] not in ('CREATED', 'ROUTED'):
            continue
        issue = _dependency_issue(state, task_id)
        if issue:
            if issue != 'Dependency awaiting verified completion':
                task['state'], task['reason'] = 'BLOCKED', issue
                _event(state, 'TASK_DEPENDENCY_BLOCKED', task_id, {'reason': issue})
            continue
        ready.append(copy.deepcopy(task))
    order = {'urgent': 0, 'high': 1, 'normal': 2, 'low': 3}
    return sorted(ready, key=lambda t: (order[t['priority']], t['deadline'] or '9999', t['task_id']))


def project_summary(state):
    """Public allowlist: no free text, raw payloads, identities, proofs or billing."""
    _state(state)
    tasks, cards, counts = [], [], Counter()
    for task_id in sorted(state['tasks']):
        try:
            task = _task(state, task_id)
        except ValueError:
            counts['BLOCKED'] += 1
            continue
        status = task['state']
        if status == 'COMPLETED' and not _completion_valid(state, task):
            status = 'BLOCKED'
        counts[status] += 1
        tasks.append({'task_id': task_id, 'goal_id': task['goal_id'], 'team': task['team'], 'kind': task['kind'],
                      'state': status, 'priority': task['priority'], 'deadline': task['deadline'], 'level': task['level'],
                      'parent_id': task['parent_id'], 'depends_on': list(task['depends_on'])})
        if task['level'] >= 3 or status == 'WAITING_APPROVAL':
            cards.append({'request_id': task_id, 'team': task['team'], 'kind': task['kind'], 'level': task['level'],
                          'status': 'REQUEST_ONLY', 'approval_required': True, 'execution_enabled': False})
    return {'schema_version': 1, 'engine': {'controller': 'secretary', 'mode': 'local_only', 'external_execution_enabled': False},
            'teams': list(TEAMS), 'counts': dict(sorted(counts.items())), 'tasks': tasks, 'actioncards': cards}
