"""Pure bounded recovery reconciliation. Caller owns lock, persistence and receipts.
No IO, dispatch, collection, registry or execution-policy changes.
"""
from __future__ import annotations
import copy
import re
from datetime import datetime
import jarvis_operations as core

PURPOSE = 'verify_actual_watch_recovery_only'
MAX_ATTEMPTS = 2
MAX_EPISODES_PER_TEAM = 128
HEALTHY = frozenset(('BASELINE', 'NO_CHANGE', 'CHANGED', 'COOLDOWN', 'LOCAL_VERIFIED'))
SOURCES = {
    'sourcing': 'data/product_master.json', 'institutions': 'data/institution_sources.json',
    'market': 'data/google_trends_beauty.json', 'listing': 'data/listing_gate.json',
    'pricing': 'data/product_master.json', 'legal': 'data/legal_full.json',
    'robotics': 'data/robotics_sources.json', 'design': 'data/design_team.json',
    'channels': 'data/channel_candidates.json', 'knowledge': 'data/knowledge/real_sources.json',
    'graph': 'data/obsidian_sync_status.json', 'secretary': 'data/dashboard_runtime.json',
}
ALTERNATE = 'data/daiso_real/shortlist_observations.json'
OWNERS = {t: 'graph' if t == 'secretary' else t for t in SOURCES}
NEXT_ACTIONS = {
    'sourcing': '정해진 활성 후보만 읽기 전용으로 재수집하고 실제 캡처시각 확인' ,
    'institutions': '실패 공급원의 날짜·파싱 근거 확인 후 허용 범위에서 실제 재수집',
    'market': '공식 트렌드 자료를 허용 범위에서 재수집하고 실제 캡처시각 확인',
    'listing': '검증된 입력으로 고정 산출물 재생성. 법률·판매 승인은 별도 대기',
    'pricing': '실측 가격·정본 ID·원화 단위·실제 캡처시각 재확인',
    'legal': '법률 파생물 입력 서명 재검증. 책임자·라벨·안전성 자료 의존성 유지',
    'robotics': '설정된 공개 로보틱스 수집기를 재실행하고 실제 캡처시각 확인',
    'design': '설정된 공개 디자인 피드를 재수집하고 참조·실제 캡처시각 확인',
    'channels': '접근이 허용된 후보만 재탐색. 탐색 성공은 연동 등록이 아님',
    'knowledge': '원수집기의 실제 캡처시각·항목 ID를 보강한 후 허용 범위 재수집',
    'graph': '기존 Obsidian 동기화 경로·연결 권한 확인 후 실제 동기화 재관찰',
    'secretary': '실제 워크플로 관찰로 고정 대시보드 재생성 후 관찰시각 확인',
}
_HASH = re.compile(r'^[0-9a-f]{64}$')
_CODE = re.compile(r'^[A-Z][A-Z0-9_]{0,99}$')
_STATUSES = {'WAITING_SOURCE_RECOVERY', 'READY_LOCAL_VERIFICATION', 'RECOVERED', 'ESCALATED'}
ESCALATION_CODES = frozenset(('SOURCE_VERIFICATION_CHANGED', 'VERIFICATION_ATTEMPT_LIMIT'))
_FIELDS = {'recovery_id', 'episode', 'owner', 'source_team', 'source', 'initial_source', 'current_source', 'task_id', 'blocker_codes',
           'initial_evidence_hash', 'first_detected_at', 'last_detected_at', 'last_observed_at',
           'status', 'attempts', 'attempt_receipts', 'escalation_code', 'recovered_evidence', 'receipt_id'}


def _date(v):
    return datetime.fromisoformat(core.utc(v))


def _hash(v):
    return isinstance(v, str) and bool(_HASH.fullmatch(v))


def _source(team, source):
    return source == SOURCES[team] or team in ('sourcing', 'pricing') and source == ALTERNATE


def _source_transition(team, initial, current):
    return current == initial or (team in ('sourcing', 'pricing')
                                  and {initial, current} == {SOURCES[team], ALTERNATE})


def _rid(team, number):
    return 'recovery_' + team + '_' + str(number).zfill(6)


def _seal(table):
    table['table_hash'] = core.digest({k: v for k, v in table.items() if k != 'table_hash'})


def _new():
    table = {'schema_version': 1, 'counters': {t: 0 for t in SOURCES}, 'episodes': {}}
    _seal(table)
    return table


def _codes(values):
    if not isinstance(values, list) or len(values) > 64:
        raise ValueError('Invalid blocker codes')
    return sorted(set(v if isinstance(v, str) and _CODE.fullmatch(v) else 'SOURCE_UNAVAILABLE' for v in values))


def _watch(w):
    if not isinstance(w, dict):
        raise ValueError('Invalid watcher')
    team = w.get('source_team')
    if not isinstance(team, str) or team not in SOURCES or not _source(team, w.get('source')):
        raise ValueError('Unknown watcher source or owner')
    if w.get('status') not in HEALTHY | {'BLOCKED', 'PARTIAL'}:
        raise ValueError('Invalid watcher status')
    return team, _codes(w.get('blockers', []))


def _evidence(w, now, minimum=None):
    team, codes = _watch(w)
    if w['status'] not in HEALTHY or codes or w.get('required_scope_complete') is False:
        return None
    coverage = w.get('coverage')
    if isinstance(coverage, dict) and (coverage.get('complete') is False or coverage.get('status') in ('PARTIAL', 'BLOCKED')):
        return None
    if not _hash(w.get('source_hash')) or not w.get('observed_at'):
        return None
    try:
        observed = core.utc(w['observed_at'])
        captured = core.utc(w['captured_at']) if w.get('captured_at') else None
        local = w['status'] == 'LOCAL_VERIFIED' and w.get('observation_kind') == 'local_derived_read'
        if not local and captured is None:
            return None
        age = w.get('max_age_seconds', 172800)
        if type(age) not in (int, float) or not 0 <= age <= 31536000:
            return None
        clock = captured or observed
        if not _date(clock) <= _date(observed) <= _date(now) or (_date(now) - _date(clock)).total_seconds() > age:
            return None
        if minimum is not None and _date(observed) < _date(minimum):
            return None
    except (KeyError, ValueError, TypeError, OverflowError):
        return None
    return {'source_team': team, 'source': w['source'], 'status': w['status'],
            'source_hash': w['source_hash'], 'captured_at': captured, 'observed_at': observed,
            'observation_kind': w.get('observation_kind'), 'coverage': copy.deepcopy(coverage)}


def _payload(e):
    return {'purpose': PURPOSE, 'recovery_id': e['recovery_id'], 'watcher_team': e['source_team'],
            'teams': [e['owner']], 'source': e['source']}


def _bound(receipt, e, evidence):
    binding = receipt.get('source_recovery_evidence')
    if not isinstance(binding, dict) or binding.get('recovery_id') != e['recovery_id']:
        return False
    if any(binding.get(k) != evidence.get(k) for k in evidence):
        return False
    try:
        return _date(e['last_detected_at']) <= _date(evidence['observed_at']) <= _date(receipt['ended_at'])
    except (KeyError, ValueError, TypeError):
        return False


def _validate(state):
    core._state(state)
    tasks = {tid for tid, task in state['tasks'].items() if isinstance(task, dict)
             and isinstance(task.get('payload'), dict) and
             (task['payload'].get('purpose') == PURPOSE or 'recovery_id' in task['payload'])}
    table = state.get('source_recovery')
    if table is None:
        if 'source_recovery' in state or tasks:
            raise ValueError('Recovery table lost; refusing reset')
        return _new()
    if not isinstance(table, dict) or set(table) != {'schema_version', 'counters', 'episodes', 'table_hash'}:
        raise ValueError('Invalid recovery table')
    if type(table['schema_version']) is not int or table['schema_version'] != 1:
        raise ValueError('Invalid recovery schema')
    if table['table_hash'] != core.digest({k: v for k, v in table.items() if k != 'table_hash'}):
        raise ValueError('Edited recovery table')
    if not isinstance(table['counters'], dict) or set(table['counters']) != set(SOURCES) or not isinstance(table['episodes'], dict):
        raise ValueError('Invalid recovery maps')
    seen = set()
    for team, count in table['counters'].items():
        if type(count) is not int or not 0 <= count <= MAX_EPISODES_PER_TEAM:
            raise ValueError('Invalid episode counter')
        rows = [e for e in table['episodes'].values() if isinstance(e, dict) and e.get('source_team') == team]
        if len(rows) != count or any(type(e.get('episode')) is not int for e in rows) or sorted(e['episode'] for e in rows) != list(range(1, count + 1)):
            raise ValueError('Lost episode or edited counter')
        if sum(e.get('status') != 'RECOVERED' for e in rows) > 1 or any(e.get('status') != 'RECOVERED' and e['episode'] != count for e in rows):
            raise ValueError('Invalid active episodes')
    for rid, e in table['episodes'].items():
        if not isinstance(e, dict) or set(e) != _FIELDS:
            raise ValueError('Malformed recovery episode')
        team = e['source_team']
        if not isinstance(team, str) or team not in SOURCES or type(e['episode']) is not int or e['episode'] < 1 or rid != _rid(team, e['episode']) or e['recovery_id'] != rid:
            raise ValueError('Modified recovery ID')
        if (e['owner'] != OWNERS[team] or not _source(team, e['source'])
            or e['initial_source'] != e['source']
            or not isinstance(e['current_source'], str)
            or not _source_transition(team, e['initial_source'], e['current_source'])
            or e['status'] not in _STATUSES):
            raise ValueError('Modified source, owner or status')
        if not _hash(e['initial_evidence_hash']) or _codes(e['blocker_codes']) != e['blocker_codes']:
            raise ValueError('Invalid recovery evidence')
        if not all(e[k] is not None for k in ('first_detected_at', 'last_detected_at', 'last_observed_at')) or not _date(e['first_detected_at']) <= _date(e['last_detected_at']) <= _date(e['last_observed_at']):
            raise ValueError('Invalid recovery chronology')
        task = core._task(state, e['task_id'])
        if (task['task_id'] in seen or task['team'] != e['owner'] or task['kind'] != 'snapshot_report'
            or task['payload'] != _payload(e) or task['evidence'] != {'initial_evidence_hash': e['initial_evidence_hash']}
            or task['goal'] != 'Verify actual source recovery ' + rid):
            raise ValueError('Modified recovery task binding')
        seen.add(task['task_id'])
        if type(e['attempts']) is not int or not isinstance(e['attempt_receipts'], dict) or e['attempts'] != len(e['attempt_receipts']) or not 0 <= e['attempts'] <= MAX_ATTEMPTS:
            raise ValueError('Invalid verification budget')
        for receipt_id, receipt_hash in e['attempt_receipts'].items():
            receipt = state['receipts'].get(receipt_id)
            core._verified_receipt(state, task, receipt)
            if core.digest(receipt) != receipt_hash:
                raise ValueError('Modified verification receipt')
        if e['status'] == 'ESCALATED':
            if (e['escalation_code'] not in ESCALATION_CODES or e['attempts'] < 1
                or e['escalation_code'] == 'VERIFICATION_ATTEMPT_LIMIT' and e['attempts'] != MAX_ATTEMPTS):
                raise ValueError('Invalid escalation')
        elif e['escalation_code'] is not None:
            raise ValueError('Invalid escalation code')
        if e['status'] == 'RECOVERED':
            if task['state'] != 'COMPLETED' or not core._completion_valid(state, task) or e['receipt_id'] != task['receipt_id'] or e['receipt_id'] not in e['attempt_receipts']:
                raise ValueError('Lost recovery completion binding')
            evidence = e['recovered_evidence']
            if not isinstance(evidence, dict) or evidence.get('source_team') != team or evidence.get('source') != e['current_source'] or not _hash(evidence.get('source_hash')) or not _bound(state['receipts'][e['receipt_id']], e, evidence):
                raise ValueError('Edited recovered evidence')
        elif e['receipt_id'] is not None or e['recovered_evidence'] is not None:
            raise ValueError('Unresolved episode cannot claim recovery')
    if seen != tasks:
        raise ValueError('Orphan recovery task or episode')
    return copy.deepcopy(table)


def validate(state):
    """Raise ValueError for malformed/edited/lost state; return True otherwise."""
    try:
        _validate(state)
    except (KeyError, TypeError, OverflowError, AttributeError) as exc:
        raise ValueError('Malformed recovery state') from exc
    return True


def _commit(state, work, table):
    _seal(table)
    work['source_recovery'] = table
    validate(work)
    state.clear()
    state.update(work)


def reconcile(state, watchers, now=None):
    """Mutate atomically; return project(state). List of up to 12 unique watchers."""
    validate(state)
    table, stamp = _validate(state), core.utc(now)
    if not isinstance(watchers, list) or len(watchers) > len(SOURCES):
        raise ValueError('Invalid watcher list')
    teams = [_watch(w)[0] for w in watchers]
    if len(set(teams)) != len(teams):
        raise ValueError('Duplicate watcher')
    work = copy.deepcopy(state)
    for w in watchers:
        team, codes = _watch(w)
        e = next((e for e in table['episodes'].values() if e['source_team'] == team and e['status'] != 'RECOVERED'), None)
        unhealthy = w['status'] in ('BLOCKED', 'PARTIAL') or bool(codes)
        if e is None and unhealthy:
            number = table['counters'][team] + 1
            if number > MAX_EPISODES_PER_TEAM:
                raise ValueError('Recovery history bound reached; archival review required')
            rid = _rid(team, number)
            e = {'recovery_id': rid, 'episode': number, 'owner': OWNERS[team], 'source_team': team,
                 'source': w['source'], 'initial_source': w['source'], 'current_source': w['source'],
                 'task_id': None, 'blocker_codes': codes,
                 'initial_evidence_hash': core.digest(w), 'first_detected_at': stamp,
                 'last_detected_at': stamp, 'last_observed_at': stamp, 'status': 'WAITING_SOURCE_RECOVERY',
                 'attempts': 0, 'attempt_receipts': {}, 'escalation_code': None,
                 'recovered_evidence': None, 'receipt_id': None}
            task = core.create_task(work, goal='Verify actual source recovery ' + rid, team=e['owner'],
                                    kind='snapshot_report', payload=_payload(e),
                                    evidence={'initial_evidence_hash': e['initial_evidence_hash']})
            e['task_id'] = task['task_id']
            core.transition(work, task['task_id'], 'BLOCKED', reason='WAITING_SOURCE_RECOVERY')
            table['episodes'][rid], table['counters'][team] = e, number
        if e is None:
            continue
        if not _source_transition(team, e['initial_source'], w['source']):
            raise ValueError('Active recovery source changed outside fixed allowed pair')
        e['current_source'] = w['source']
        if _date(stamp) < _date(e['last_observed_at']):
            raise ValueError('Recovery clock regression')
        e['last_observed_at'] = stamp
        task = core._task(work, e['task_id'])
        evidence = _evidence(w, stamp, e['last_detected_at'])
        if unhealthy or evidence is None:
            e['last_detected_at'], e['blocker_codes'] = stamp, codes or ['SOURCE_EVIDENCE_INCOMPLETE']
            if task['state'] in ('CREATED', 'ROUTED', 'IN_PROGRESS', 'VERIFYING', 'EXECUTING', 'WAITING_APPROVAL'):
                core.transition(work, task['task_id'], 'BLOCKED', reason='WAITING_SOURCE_RECOVERY')
            if e['status'] != 'ESCALATED':
                e['status'] = 'WAITING_SOURCE_RECOVERY'
        elif e['status'] != 'ESCALATED':
            e['blocker_codes'], e['status'] = [], 'READY_LOCAL_VERIFICATION'
            if task['state'] == 'BLOCKED':
                core.transition(work, task['task_id'], 'ROUTED')
    _commit(state, work, table)
    return project(state)


def record_attempt(state, recovery_id, receipt):
    """Count only real core-verified execution receipts; never blocked dispatches.

    Dedup by receipt_id. No task completion is inferred. Useful before completion
    if a real diagnostic failed to establish source health. Cap is two receipts.
    """
    validate(state)
    table = _validate(state)
    if not isinstance(recovery_id, str) or recovery_id not in table['episodes']:
        raise ValueError('Unknown recovery ID')
    e = table['episodes'][recovery_id]
    task = core._task(state, e['task_id'])
    stored = core._verified_receipt(state, task, receipt)
    if task['state'] == 'BLOCKED':
        raise ValueError('Blocked tasks cannot have verification attempts')
    if e['status'] == 'RECOVERED':
        return project(state)
    rid = stored['receipt_id']
    if rid not in e['attempt_receipts']:
        if e['attempts'] >= MAX_ATTEMPTS:
            raise ValueError('Verification attempt limit reached')
        e['attempt_receipts'][rid], e['attempts'] = core.digest(stored), e['attempts'] + 1
    if e['attempts'] >= MAX_ATTEMPTS:
        e['status'], e['escalation_code'] = 'ESCALATED', 'VERIFICATION_ATTEMPT_LIMIT'
    _commit(state, copy.deepcopy(state), table)
    return project(state)


def escalate(state, recovery_id, code='SOURCE_VERIFICATION_CHANGED', now=None):
    """Hold a raced real verification for explicit controller review, never replay.

    Requires an already recorded genuine receipt. Only fixed safe codes accepted.
    Reconcile cannot release ESCALATED episodes on a later healthy observation.
    """
    validate(state)
    table = _validate(state)
    if not isinstance(recovery_id, str) or recovery_id not in table['episodes']:
        raise ValueError('Unknown recovery ID')
    if not isinstance(code, str) or code not in ESCALATION_CODES:
        raise ValueError('Unknown escalation code')
    e = table['episodes'][recovery_id]
    if e['status'] == 'RECOVERED' or e['attempts'] < 1:
        raise ValueError('Unresolved actual verification receipt required')
    if code == 'VERIFICATION_ATTEMPT_LIMIT' and e['attempts'] != MAX_ATTEMPTS:
        raise ValueError('Attempt limit not reached')
    stamp = core.utc(now)
    if _date(stamp) < _date(e['last_observed_at']):
        raise ValueError('Recovery clock regression')
    work = copy.deepcopy(state)
    task = core._task(work, e['task_id'])
    if task['state'] != 'BLOCKED':
        if task['state'] not in ('CREATED', 'ROUTED', 'IN_PROGRESS', 'VERIFYING', 'EXECUTING', 'WAITING_APPROVAL'):
            raise ValueError('Escalation cannot reopen terminal task')
        core.transition(work, task['task_id'], 'BLOCKED', reason=code)
    e['status'], e['escalation_code'], e['blocker_codes'] = 'ESCALATED', code, [code]
    e['last_observed_at'] = stamp
    _commit(state, work, table)
    return project(state)


def verify_completed(state, recovery_id, receipt, watcher, now=None):
    """Require core COMPLETED plus matching receipt and exact current source proof.

    receipt.source_recovery_evidence requires recovery_id plus source_team, source,
    status, source_hash, captured_at, observed_at, observation_kind, coverage.
    Parent validates actual output and ledger before inserting trusted receipts.
    A diagnostic without source proof stays unresolved, even if it completed.
    """
    validate(state)
    table = _validate(state)
    if not isinstance(recovery_id, str) or recovery_id not in table['episodes']:
        raise ValueError('Unknown recovery ID')
    e = table['episodes'][recovery_id]
    task = core._task(state, e['task_id'])
    stored = core._verified_receipt(state, task, receipt)
    if _watch(watcher)[0] != e['source_team'] or watcher['source'] != e['current_source']:
        raise ValueError('Wrong completion watcher')
    if task['state'] != 'COMPLETED' or not core._completion_valid(state, task) or task['receipt_id'] != stored['receipt_id']:
        raise ValueError('Actual matching core COMPLETED task required')
    if e['status'] == 'RECOVERED':
        return project(state)
    rid = stored['receipt_id']
    if rid not in e['attempt_receipts']:
        if e['attempts'] >= MAX_ATTEMPTS:
            raise ValueError('Verification attempt limit reached')
        e['attempt_receipts'][rid], e['attempts'] = core.digest(stored), e['attempts'] + 1
    evidence = _evidence(watcher, core.utc(now), max(e['last_detected_at'], stored['started_at'], key=_date))
    if evidence and _bound(stored, e, evidence):
        e['status'], e['blocker_codes'] = 'RECOVERED', []
        e['receipt_id'], e['recovered_evidence'], e['escalation_code'] = rid, evidence, None
    else:
        e['status'], e['blocker_codes'] = 'WAITING_SOURCE_RECOVERY', ['VERIFICATION_SOURCE_EVIDENCE_UNCONFIRMED']
        if e['attempts'] >= MAX_ATTEMPTS:
            e['status'], e['escalation_code'] = 'ESCALATED', 'VERIFICATION_ATTEMPT_LIMIT'
    _commit(state, copy.deepcopy(state), table)
    return project(state)


def project(state):
    """Safe metadata only: no watcher contents, raw URLs, contacts or exceptions."""
    validate(state)
    table = _validate(state)
    episodes = []
    for rid, e in sorted(table['episodes'].items()):
        row = {k: copy.deepcopy(e[k]) for k in ('recovery_id', 'episode', 'owner', 'source_team', 'source',
               'initial_source', 'current_source', 'task_id', 'blocker_codes', 'initial_evidence_hash', 'first_detected_at', 'last_detected_at',
               'status', 'attempts', 'escalation_code', 'receipt_id')}
        next_action = ('실제 재관찰·영수증 검증 완료' if e['status'] == 'RECOVERED' else
                       '비서실장 검토 필요. 자동 재시도 없음' if e['status'] == 'ESCALATED' else
                       NEXT_ACTIONS[e['source_team']])
        row.update(attempt_limit=MAX_ATTEMPTS, next_action=next_action,
                   execution_enabled=False, dependencies_are_not_execution_authority=True)
        episodes.append(row)
    return {'schema_version': 1, 'counters': copy.deepcopy(table['counters']), 'episodes': episodes}
