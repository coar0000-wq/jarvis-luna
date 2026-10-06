#!/usr/bin/env python3
"""Offline secretary-controlled operating loop, not an external business executor.

Existing eleven teams, eight functions. Durable claims precede local dispatch;
only actual hash-verified receipts establish completion. No model/API calls.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

import jarvis_operations as core
import jarvis_execution as execution
import jarvis_feedback as feedback
import jarvis_watch as watch
import jarvis_recovery as recovery
import jarvis_audit as audit

ROOT = Path(__file__).resolve().parents[1]
STATE = 'data/operations/state.json'
BOARD = 'data/operations/board.json'
LOCK = 'data/operations/.state.lock'
POLICY = 'config/jarvis_operations_policy.json'
CHAIN = dict(zip(('sourcing','market','pricing','legal','listing'),
                 ('market','pricing','legal','listing','channels')))
ENGINE_NAMES = {'manager':'Manager','router':'Router','task':'Task','handoff':'Handoff',
    'watch':'Watch/Event','approval':'Approval','execution':'Execution','knowledge':'Knowledge/Feedback'}
INPUTS = ('data/product_master.json','data/pricing_model.json','data/listing_gate.json',
          'data/legal_full.json','data/mocra_readiness.json','data/shopify_shortlist.json')


def read(root, relative, default=None):
    file = execution._safe(root, relative)
    if not file.exists():
        return copy.deepcopy(default)
    raw = file.read_bytes()
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError('operation input size limit')
    value = json.loads(raw)
    core.canonical(value)
    return value


def atomic(root, relative, value):
    if not (relative.startswith('data/operations/') or relative == 'data/dashboard_runtime.json'):
        raise ValueError('operation write scope denied')
    if relative == STATE:
        body = (json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
        if len(body) > 8 * 1024 * 1024:
            raise ValueError('operations state storage capacity reached; pruning/reset forbidden')
    else:
        body = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                           allow_nan=False) + '\n').encode('utf-8')
    dest = execution._safe(root, relative)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest = execution._safe(root, relative)
    fd, temp = tempfile.mkstemp(prefix='.operations-', dir=dest.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        execution._safe(root, relative)
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


@contextmanager
def transaction(root):
    lock = execution._safe(root, LOCK)
    lock.parent.mkdir(parents=True, exist_ok=True)
    execution._safe(root, LOCK)
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, b'operation transaction; stale lock requires reconciliation\n')
        os.fsync(fd)
        yield
    finally:
        os.close(fd)
        lock.unlink()


def semantic(value):
    if isinstance(value, dict):
        return {k: semantic(v) for k,v in value.items() if k not in ('generated_at','gate_generated_at')}
    if isinstance(value, list):
        return [semantic(v) for v in value]
    return value


def input_version(root):
    return core.digest({name: semantic(read(root, name, None)) for name in INPUTS})


def validate_state(root, state):
    core.project_summary(state)
    recovery.validate(state)
    ledger = read(root, execution.ExecutionStore.filename, {}) or {}
    if ledger.get('global_stop'):
        raise ValueError('execution global stop; explicit reconciliation required')
    audit.validate(state, root=root)
    batches = state.get('event_batches', {})
    if not isinstance(batches, dict) or len(batches) > 10000:
        raise ValueError('watch batch capacity/schema invalid')
    for key, batch in batches.items():
        if (not isinstance(batch, dict)
                or set(batch) != {'source_team','event_ids','scope'}
                or batch['source_team'] not in core.TEAMS
                or batch['scope'] != 'same_observation_saved_event_review_only'
                or not isinstance(batch['event_ids'], list)
                or not 2 <= len(batch['event_ids']) <= 10000
                or batch['event_ids'] != sorted(set(batch['event_ids']))
                or key != 'event_batch_' + core.digest(batch)
                or any(state['events'].get(e, {}).get('source_team') != batch['source_team']
                       for e in batch['event_ids'])):
            raise ValueError('immutable watch batch/reference invalid')
    for receipt in state['receipts'].values():
        if not execution.validate_receipt(root, receipt):
            raise ValueError('trusted execution ledger/output mismatch')
    for task in state['tasks'].values():
        if task.get('state') == 'COMPLETED' and not core._completion_valid(state, task):
            raise ValueError('completion receipt missing or modified')
    # A merged monotonic event stream cannot silently lose events/counters.
    numbered = [v.get('sequence') for v in state['events'].values() if v.get('kind','').startswith(('TASK_','HANDOFF_'))]
    if numbered and (any(type(n) is not int for n in numbered) or max(numbered) != state['sequence']
                     or len(set(numbered)) != len(numbered) or len(numbered) != state['sequence']):
        raise ValueError('operation event sequence collision/rollback')


def canonical_members(root):
    shortlist = read(root, 'data/shopify_shortlist.json', {}) or {}
    allowed = {str(p) for p in shortlist.get('active_pd_nos') or []}
    master = read(root, 'data/product_master.json', {}) or {}
    return sorted({p['canonical_product_id'] for p in master.get('products') or []
                   if isinstance(p,dict) and str(p.get('pd_no')) in allowed
                   and isinstance(p.get('canonical_product_id'),str) and p['canonical_product_id']})


def payload(team, version, members):
    return {'teams':[team], 'input_version':version, 'purpose':'saved_snapshot_review_only',
            'canonical_members':list(members)}


def bootstrap(state, version, members, *, goal=None):
    # Optional label admits only the same fixed eleven-team local report chain.
    # It is not a parsed instruction, capability, external action or approval.
    goal = ('사업 준비 스냅샷 검토' if goal is None else core._text(goal, 'internal review goal', 500)) + ' / ' + version[:16]
    core.route_intent(goal, forced_teams=list(core.TEAMS))
    for team in core.TEAMS:
        if team in set(CHAIN.values()):
            continue
        core.create_task(state, goal=goal, team=team, kind='snapshot_report',
                         payload=payload(team, version, members), priority='high',
                         evidence={'input_version':version, 'scope':'local_report_not_sales_clearance'})
    return goal


def handoffs(state, version, goal, members):
    for task in list(state['tasks'].values()):
        if task.get('goal') != goal or task.get('state') != 'COMPLETED' or task['team'] not in CHAIN:
            continue
        team = CHAIN[task['team']]
        proposal = core.propose_handoff(state, task['task_id'], team,
            '검증된 로컬 보고서를 다음 기존 팀의 스냅샷 검토에 전달',
            payload=payload(team, version, members), priority='high')
        if state['handoffs'][proposal['proposal_id']]['status'] == 'PROPOSED':
            core.accept_handoff(state, proposal['proposal_id'], actor='secretary')


def approval_cards(root):
    queue = read(root, 'data/shopify_action_queue.json', {}) or {}
    cards = []
    for action in queue.get('draft_actions', []):
        if not isinstance(action, dict):
            continue
        bound = action.get('immutablePayload') or {}
        context = bound.get('execution_context') or bound.get('context') or {}
        if not context:
            context = {k:bound.get(k) for k in ('target_shop','api_version','operation','remote_preconditions')}
        cards.append({'action_id':str(action.get('action_id') or ''), 'kind':'shopify_create_draft',
            'level':4, 'status':'WAITING_APPROVAL', 'may_approve':False,'may_execute':False,
            'reason':'원격 대상·인증 승인·커넥터 검증 필요',
            'member_count':len(action.get('canonical_product_ids') or action.get('members') or []),
            'payload_hash':action.get('payload_hash'), 'target_configured':bool(context.get('target_shop')),
            'before':'원격 상태 미검증', 'after':'Draft · 비공개 · 재고 0'})
    return cards


def recovery_watchers(observed):
    rows = copy.deepcopy(observed['watchers'])
    # Cursor-relative change labels are not source health. Pure execution reads
    # have no prior cursor, so bind identical actual healthy evidence as baseline.
    for row in rows:
        if row.get('status') in ('NO_CHANGE','CHANGED','COOLDOWN','READY'):
            row['status'] = 'BASELINE'
    return rows


def apply_watch(state, observed, stamp):
    state['watch'] = observed['state']
    current_recovery_watchers = recovery_watchers(observed)
    recovery.reconcile(state, current_recovery_watchers, now=stamp)
    grouped = {}
    for event in observed['events']:
        key = event.get('event_id') or core.digest(event)
        old = state['events'].get(key)
        if old is not None and old != event:
            raise ValueError('immutable watch event collision')
        state['events'][key] = event
        team = event.get('source_team')
        if team in core.TEAMS:
            grouped.setdefault(team, []).append(key)
    # Keep every event, with one review per team/observation instead of hundreds
    # of identical entity-level tasks. Hashes are integrity, never authority.
    for team, keys in grouped.items():
        keys = sorted(set(keys))
        if len(keys) == 1:
            key = keys[0]
            evidence = state['events'][key].get('evidence')
        else:
            record = {'source_team':team, 'event_ids':keys,
                      'scope':'same_observation_saved_event_review_only'}
            key = 'event_batch_' + core.digest(record)
            batches = state.setdefault('event_batches', {})
            if key in batches and batches[key] != record:
                raise ValueError('immutable watch batch collision')
            batches.setdefault(key, record)
            evidence = {'event_batch_ref':key, 'event_count':len(keys),
                        'event_batch_hash':core.digest(record), 'scope':record['scope']}
        core.create_task(state, goal='관찰 이벤트 검토 / ' + key[:16], team=team,
            payload={'teams':[team],'source_event':key,'purpose':'saved_event_review_only'},
            evidence=evidence, priority='high')


def summarize(root, state, observed, learned, now):
    safe = core.project_summary(state)
    tasks = safe.get('tasks') or []
    recovery_board = recovery.project(state)
    latest_recovery = {}
    for item in recovery_board['episodes']:
        latest_recovery[item['source_team']] = item
    watchers = [{'team': v.get('source_team'),
                 **{k:v.get(k) for k in ('status','captured_at','observed_at','observation_kind','scope','coverage')},
                 'reason': ', '.join(v.get('blockers') or []),
                 'recovery': latest_recovery.get(v.get('source_team'))} for v in observed['watchers']]
    local_verified = sum(t.get('state') == 'COMPLETED' and t.get('level',4) <= 2 for t in tasks)
    cards = approval_cards(root)
    procedures = read(root, 'data/agents/source_procedures/report.json', {}) or {}
    if procedures and (procedures.get('schema_version') != 1 or procedures.get('authority') is not False
            or procedures.get('business_clearance') is not False or procedures.get('receipt_verified') is not False):
        raise ValueError('source procedure projection cannot authorize execution')
    mocra = read(root, 'data/mocra_readiness.json', {}) or {}
    def count(*keys):
        for key in keys:
            v = mocra.get(key)
            if type(v) is int and v >= 0:
                return v
        return 0
    # Explicit missing evidence is not manufactured business clearance.
    business = {'ready':count('ready_count','ready'),'exempt':count('exempt_count','exempt'),
                'total':count('total_checks','total_count','total'), 'sales_allowed':False,
                'blockers':[]}
    labels = {'responsible_person':'책임자 라벨 정보','safety_substantiation':'제품별 제조사 안전성 자료',
              'label_fields':'필수 영문 라벨'}
    for check in mocra.get('checks') or []:
        if isinstance(check,dict) and check.get('status') not in ('ready','exempt'):
            business['blockers'].append(labels.get(check.get('id'),'규제 근거 미완료'))
    if not mocra:
        business['blockers'].append('사업 준비 근거 없음')
    engines = []
    details = {'manager':'기존 비서실장 제어', 'router':'기존 11팀으로 작업 라우팅',
       'task':'의존성·한도·실행증거 기반 상태', 'handoff':'비서실장만 팀 간 인계 수락',
       'watch':'실제 캡처 시각·의미 있는 변경만 관찰',
       'approval':'정확한 내용에 인증 승인 필요',
       'execution':'L1 읽기·L2 로컬 보고서만 실행',
       'knowledge':'결정·관계 기록, 실제 피드백 대기'}
    for name, label in ENGINE_NAMES.items():
        engines.append({'id':name,'name':label,'status':'gated' if name in ('approval','execution') else 'local_only',
                        'detail':details[name]})
    return {'schema_version':1,'generated_at':now,'status':'local_only',
       'organization':'기존 비서실장 > 11팀 팀장 > 전문 기능', 'engines':engines,
       'counts':{'tasks_total':len(tasks),'local_verified':local_verified,'external_verified':0,
          'handoffs_accepted':sum(h.get('status') == 'ACCEPTED' for h in state['handoffs'].values()),
          'watchers_ready':sum(w['status'] in ('BASELINE','NO_CHANGE','CHANGED','READY','COOLDOWN') for w in watchers),
          'watchers_blocked':sum(w['status'] == 'BLOCKED' for w in watchers),
          'watchers_partial':sum(w['status'] == 'PARTIAL' for w in watchers),
          'watchers_local':sum(w['status'] == 'LOCAL_VERIFIED' for w in watchers),
          'source_recoveries_verified':sum(e['status'] == 'RECOVERED' for e in recovery_board['episodes']),
          'source_recoveries_open':sum(e['status'] != 'RECOVERED' for e in recovery_board['episodes']),
          'events':len(state['events']),'approval_waiting':len(cards)},
       'audit':audit.project_summary(state),
       'tasks':tasks[-40:], 'watchers':watchers, 'source_recovery':recovery_board,
       'source_procedures':procedures,
       'action_cards':cards, 'business':business,
       'feedback':{'status':'awaiting_actual_observations','verified_observations':0,'training_performed':False}}


def resumable_local_task(task):
    descriptor = execution.REGISTRY.get(task.get('kind'), {})
    local_only = (descriptor.get('pure_read') is True or
                  (task.get('kind') == 'snapshot_report' and descriptor.get('scope') == 'data/operations/reports/'))
    return (task.get('state') in ('IN_PROGRESS','VERIFYING','EXECUTING')
            and descriptor.get('enabled') is True and local_only
            and descriptor.get('level') in (1,2))


def run(root=ROOT, *, now=None, execute_local=True, goal=None):
    root = Path(root).absolute()
    if goal is not None:
        goal = core._text(goal, 'internal review goal', 500)
    if execution._safe(root,'data/operations/.restore-pending.json').exists():
        raise ValueError('operations_safety_restore_pending')
    stamp = core.utc(now)
    policy = read(root, POLICY, {}) or {}
    if policy.get('teams', list(core.TEAMS)) != list(core.TEAMS):
        raise ValueError('organizational roster changed')
    with transaction(root):
        exists = execution._safe(root, STATE).exists()
        if not exists and execution._safe(root, execution.ExecutionStore.filename).exists():
            raise ValueError('task state missing with execution history; reconcile, do not reset')
        state = read(root, STATE, core.empty_state())
        validate_state(root, state)
        if not state['watch'] and state['sequence']:
            raise ValueError('watch cursor missing with task history; reconcile, do not reset')
        observed = watch.observe(root, state['watch'] or None, now=stamp, policy=policy.get('watch'))
        apply_watch(state, observed, stamp)
        current_recovery_watchers = recovery_watchers(observed)
        version = input_version(root)
        members = canonical_members(root)
        goal = bootstrap(state, version, members, goal=goal)
        handoffs(state, version, goal, members)
        atomic(root, STATE, state)
        if execute_local:
            # Restart only idempotent receipt-backed local work, never external effects.
            candidates = [t for t in state['tasks'].values() if resumable_local_task(t)]
            restart_ids = {t['task_id'] for t in candidates}
            candidates += core.ready_tasks(state)
            processed = set()
            for _ in range(32):
                active = [t for t in candidates if t['task_id'] not in processed and
                          (t['task_id'] in restart_ids or t.get('goal') == goal or t.get('payload',{}).get('source_event')
                           or t.get('payload',{}).get('recovery_id'))]
                if not active:
                    break
                for task in active:
                    task_id = task['task_id']
                    processed.add(task_id)
                    was_executing = state['tasks'][task_id]['state'] == 'EXECUTING'
                    for target in ('ROUTED','IN_PROGRESS','VERIFYING'):
                        current = state['tasks'][task_id]['state']
                        order = ('CREATED','ROUTED','IN_PROGRESS','VERIFYING','EXECUTING')
                        if current in order and order.index(current) < order.index(target):
                            core.transition(state, task_id, target)
                            atomic(root, STATE, state)
                    preparation = audit.prepare(state, task_id, now=stamp)
                    decision_id = preparation['decision_id']
                    atomic(root, STATE, state)
                    if state['tasks'][task_id]['state'] == 'VERIFYING':
                        core.transition(state, task_id, 'EXECUTING')
                        atomic(root, STATE, state)
                    # A persisted outcome is never a reason to redispatch missing logs.
                    prior_outcomes = [o for o in state['audit']['outcomes'].values()
                                      if o['preparation_id'] == preparation['preparation_id']]
                    try:
                        if prior_outcomes:
                            receipt = prior_outcomes[-1]['result']['receipt']
                            if not receipt or not execution.validate_receipt(root, receipt):
                                raise ValueError('audit outcome requires reconciliation; no replay')
                        elif was_executing:
                            ledger = read(root, execution.ExecutionStore.filename, {}) or {}
                            action = state['audit']['payloads'][preparation['action_hash']]
                            claim = ledger.get('claims', {}).get(action['idempotency_key'], {})
                            receipt = claim.get('receipt')
                            if not receipt or not execution.validate_receipt(root, receipt):
                                raise ValueError('interrupted execution without verified receipt; no replay')
                        else:
                            receipt = execution.execute(root, state['tasks'][task_id], execution.ExecutionStore(root), now=stamp)
                        result = audit.outcome(state, preparation, root=root, receipt=receipt, now=stamp)
                        atomic(root, STATE, state)
                    except Exception as exc:
                        audit.outcome(state, preparation, root=root, error=exc, now=stamp)
                        if state['tasks'][task_id]['state'] == 'EXECUTING':
                            core.transition(state, task_id, 'BLOCKED', reason='Execution error; explicit reconciliation required')
                        atomic(root, STATE, state)
                        raise
                    if result['result']['output_verified'] and execution.validate_receipt(root, receipt):
                        state['receipts'][receipt['receipt_id']] = receipt
                        action = receipt['action']
                        state.setdefault('actions',{})[action['action_id']] = {**action,
                            'status':'VERIFIED','receipt_id':receipt['receipt_id']}
                        if decision_id is not None:
                            state['decisions'][decision_id].update(status='LOCAL_OUTPUT_VERIFIED',
                                action_id=action['action_id'],receipt_id=receipt['receipt_id'])
                        recovery_id = task.get('payload',{}).get('recovery_id')
                        if recovery_id:
                            # Re-read after the report receipt, not just the cached
                            # pre-dispatch observation. Historical report != live health.
                            fresh_observation = watch.observe(root, now=stamp, policy=policy.get('watch'))
                            row = next(w for w in recovery_watchers(fresh_observation)
                                       if w['source_team'] == task['payload']['watcher_team'])
                            keys = ('source_team','source','status','source_hash','captured_at','observed_at','observation_kind','coverage')
                            expected = {'recovery_id':recovery_id, **{k:row.get(k) for k in keys}}
                            document_evidence = [s for s in receipt.get('source_evidence',[]) if s.get('path') == row.get('source')]
                            source_bytes_match = bool(document_evidence and document_evidence[-1].get('sha256') == row.get('source_document_hash'))
                            if receipt.get('source_recovery_evidence') != expected or not source_bytes_match:
                                recovery.record_attempt(state, recovery_id, receipt)
                                recovery.escalate(state, recovery_id, now=stamp)
                                if decision_id is not None:
                                    state['decisions'][decision_id]['status'] = 'SOURCE_EVIDENCE_CHANGED_RECONCILIATION_REQUIRED'
                            else:
                                core.transition(state, task_id, 'COMPLETED', receipt=receipt)
                                recovery.verify_completed(state, recovery_id, receipt, row, now=stamp)
                        else:
                            core.transition(state, task_id, 'COMPLETED', receipt=receipt)
                    else:
                        core.transition(state, task_id, 'BLOCKED', reason='실행 기록 검증 실패: ' + str(receipt.get('status')))
                    handoffs(state, version, goal, members)
                    atomic(root, STATE, state)
                    validate_state(root, state)
                candidates = core.ready_tasks(state)
        # Report current health as well as historical output proof. Preserve the
        # original cursor/dedup stream; a pure receipt read must never reset it.
        observed = watch.observe(root, state['watch'], now=stamp, policy=policy.get('watch'))
        apply_watch(state, observed, stamp)
        validate_state(root, state)
        learned = feedback.build(state, root, now=stamp)
        atomic(root, STATE, state)
        for name in ('decisions','knowledge_graph','feedback'):
            atomic(root, 'data/operations/' + name + '.json', learned[name])
        board = summarize(root, state, observed, learned, stamp)
        atomic(root, BOARD, board)
        runtime = read(root, 'data/dashboard_runtime.json', None)
        if isinstance(runtime,dict):
            runtime['operations'] = board
            atomic(root, 'data/dashboard_runtime.json', runtime)
        return board


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--observe-only',action='store_true')
    parser.add_argument('--goal', help='Bounded label for a new internal L2 saved-snapshot review only')
    args = parser.parse_args()
    try:
        marker = args.root/'data/operations/.restore-pending.json'
        if marker.exists() or marker.is_symlink():
            raise ValueError('operations_safety_restore_pending')
        if os.getenv('GITHUB_ACTIONS') == 'true' and os.getenv('JARVIS_OPERATIONS_CONTINUITY') != 'verified':
            raise ValueError('authenticated_runner_operations_continuity_required')
        board = run(args.root, execute_local=not args.observe_only, goal=args.goal)
        print('JARVIS_OPERATIONS_OK ' + json.dumps(board['counts'],sort_keys=True))
        return 0
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print('JARVIS_OPERATIONS_BLOCKED ' + type(exc).__name__ + ': ' + str(exc))
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
