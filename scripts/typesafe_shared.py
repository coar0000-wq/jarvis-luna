"""Free-only shared advisory dispatch. Local locks are not distributed enforcement.
CI needs serialized restore AND successful publication of this same ledger.
Proof is trusted operator attestation, not a signed provider billing guarantee.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

PRICE = .042 / 1000000
DEFAULTS = {'max_calls': 40, 'max_input_tokens': 60000, 'max_cost_usd': .00252}
SCOPE = 'shared local ledger; cross-run enforcement requires serialized restore and successful publication'

class SafetyStop(ValueError):
    pass

def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0

def canonical(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(v):
    return hashlib.sha256(canonical(v).encode('utf-8')).hexdigest()

def clean(v):
    if isinstance(v, dict):
        return {k: clean(x) for k,x in v.items() if k not in {'observed_at','captured_at','observation_timestamp'}}
    return [clean(x) for x in v] if isinstance(v,list) else v

def validate_payload(value):
    p = copy.deepcopy(value)
    if not isinstance(p,dict) or set(p) != {'state','model','questions','question_version','model_policy_version'}:
        raise SafetyStop('invalid_payload_contract')
    for k in ('model','question_version','model_policy_version'):
        if not isinstance(p[k],str) or not p[k].strip():
            raise SafetyStop('missing_version_or_model')
    if not isinstance(p['state'],(dict,list,str)):
        raise SafetyStop('invalid_state')
    p['state'] = clean(p['state'])
    qs = p['questions']
    if not isinstance(qs,dict) or not qs:
        raise SafetyStop('invalid_questions')
    for key,q in qs.items():
        if not isinstance(key,str) or not key or not isinstance(q,dict) or not isinstance(q.get('instructions'),str) or not q['instructions'].strip():
            raise SafetyStop('invalid_question')
        typ,c = q.get('type'),q.get('criteria')
        if typ == 'choice':
            if not isinstance(c,dict) or len(c)<2 or not all(isinstance(k,str) and k and isinstance(v,str) and v for k,v in c.items()):
                raise SafetyStop('invalid_choice_criteria')
        elif typ == 'score':
            if not isinstance(c,list) or len(c)<2 or not all(isinstance(x,str) and x for x in c):
                raise SafetyStop('invalid_score_criteria')
        elif typ != 'noul':
            raise SafetyStop('unsupported_type')
    canonical(p)
    return p

def validate_answers(a,qs):
    if not isinstance(a,dict) or set(a)!=set(qs):
        raise SafetyStop('answer_ids_mismatch')
    for key,q in qs.items():
        r=a[key]
        if not isinstance(r,dict):
            raise SafetyStop('invalid_answer')
        t=q['type']
        if 'type' in r and r['type'] != t:
            raise SafetyStop('answer_type_mismatch')
        if t=='choice' and (not isinstance(r.get('choice'),str) or r['choice'] not in q['criteria']):
            raise SafetyStop('invalid_choice')
        if t=='score' and (not number(r.get('score')) or r['score']>len(q['criteria'])-1):
            raise SafetyStop('invalid_score')
        if t=='noul' and (not number(r.get('noul')) or r['noul']>1):
            raise SafetyStop('invalid_noul')
        if t!='noul' or 'confidence' in r:
            if not number(r.get('confidence')) or r['confidence']>1:
                raise SafetyStop('invalid_confidence')
    canonical(a)

def validate_response(body,p):
    if not isinstance(body,dict) or body.get('error') or body.get('errors'):
        raise SafetyStop('provider_error')
    h=body.get('_http',{})
    if not isinstance(h,dict) or ('status' in h and (type(h['status']) is not int or not 200<=h['status']<300)):
        raise SafetyStop('http_failure')
    model=body.get('model')
    if not isinstance(model,str) or not model or not model.startswith('jev-') or model in ('jev-latest','jev-preview'):
        raise SafetyStop('concrete_response_model_required')
    if p['model'] not in ('jev-latest','jev-preview') and model!=p['model']:
        raise SafetyStop('response_model_mismatch')
    u=body.get('usage')
    if not isinstance(u,dict) or not all(number(u.get(k)) for k in ('input_tokens','output_tokens')) or not all(number(v) for v in u.values()):
        raise SafetyStop('invalid_usage')
    validate_answers(body.get('answers'),p['questions'])
    return {'answers':body['answers'],'usage':u,'model':model}

def proof(key):
    try:
        p=json.loads(Path(os.environ['TYPESAFE_BILLING_PROOF_PATH']).read_text(encoding='utf-8-sig'))
        fp=hashlib.sha256(key.encode('utf-8')).hexdigest()
        org=os.environ.get('TYPESAFE_ORG_ID','').strip()
        if p.get('key_sha256')!=fp or not org or p.get('org_id')!=org:
            raise SafetyStop('proof_identity_mismatch')
        if p.get('auto_recharge') is not False or p.get('payment_method_on_file') is not False:
            raise SafetyStop('proof_billing_unsafe')
        if not number(p.get('available_free_usd')) or p['available_free_usd']<=0:
            raise SafetyStop('proof_no_free_balance')
        start=datetime.fromisoformat(p['verified_at'].replace('Z','+00:00'))
        end=datetime.fromisoformat(p['expires_at'].replace('Z','+00:00'))
        now=datetime.now(timezone.utc)
        if start.tzinfo is None or end.tzinfo is None or not start<=now<end or not 0<(end-start).total_seconds()<=86400:
            raise SafetyStop('proof_stale_or_invalid')
        return fp,org,p['available_free_usd']
    except SafetyStop:
        raise
    except Exception:
        raise SafetyStop('proof_missing_or_invalid') from None

def ledger_path():
    raw=os.environ.get('TYPESAFE_SHARED_LEDGER_PATH','')
    if not raw or not Path(raw).is_absolute():
        raise SafetyStop('absolute_shared_ledger_path_required')
    return Path(raw)

@contextmanager
def lock(p):
    p.parent.mkdir(parents=True,exist_ok=True)
    with open(str(p)+'.lock','a+b') as f:
        f.seek(0,2)
        if f.tell()==0:
            f.write(b'0'); f.flush()
        deadline=time.monotonic()+120
        while True:
            try:
                f.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic()>deadline:
                    raise SafetyStop('ledger_lock_timeout')
                time.sleep(.02)
        try:
            yield
        finally:
            f.seek(0)
            if os.name=='nt':
                msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(f,fcntl.LOCK_UN)

def write(p,s):
    fd,tmp=tempfile.mkstemp(prefix=p.name+'.',suffix='.tmp',dir=p.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(canonical(s)); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,p)
        if os.name!='nt':
            d=os.open(str(p.parent),os.O_RDONLY)
            try:
                os.fsync(d)
            finally:
                os.close(d)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def read(p):
    if not p.exists():
        return None
    try:
        s=json.loads(p.read_text(encoding='utf-8'))
        if s['schema']!=1 or not isinstance(s['stopped'],str) or not all(isinstance(s[k],dict) for k in ('cache','versions','workflows')):
            raise ValueError()
        if not all(number(s[k]) for k in ('account_limit_usd','account_charged_tokens')):
            raise ValueError()
        for b in s['workflows'].values():
            if not all(number(b[k]) for k in ('calls','charged_input_tokens','reserved_input_tokens','input_tokens','output_tokens',*DEFAULTS)) or not isinstance(b['call_log'],list) or not isinstance(b.get('stopped',''),str):
                raise ValueError()
        return s
    except Exception:
        raise SafetyStop('ledger_corrupt') from None

def limits():
    out={}
    for k,env in (('max_calls','TYPESAFE_MAX_CALLS'),('max_input_tokens','TYPESAFE_MAX_INPUT_TOKENS'),('max_cost_usd','TYPESAFE_MAX_COST_USD')):
        v=float(os.environ.get(env,DEFAULTS[k]))
        if not number(v) or v<=0:
            raise SafetyStop('invalid_budget')
        out[k]=min(v,DEFAULTS[k])
    return out

def ledger():
    try:
        p=ledger_path()
        with lock(p):
            s=read(p) or {}
            b=s.get('workflows',{}).get(os.environ.get('TYPESAFE_WORKFLOW_ID','shared'),{})
            return {**b,'stopped':s.get('stopped','') or b.get('stopped',''),
                    'global_stopped':s.get('stopped',''),'workflow_stopped':b.get('stopped',''),
                    'workflow_id':os.environ.get('TYPESAFE_WORKFLOW_ID','shared'),
                    'estimated_cost_usd':b.get('charged_input_tokens',0)*PRICE,
                    'account_estimated_cost_usd':s.get('account_charged_tokens',0)*PRICE,
                    'purchased_credits':False,'scope':SCOPE,'input_token_price_per_mtok_usd':.042}
    except Exception:
        return {'stopped':'ledger_unavailable','scope':SCOPE,'purchased_credits':False}

def evaluate_typed(payload,fallback_answers=None,*,request_fn=None):
    """payload keys: state,model,questions,question_version,model_policy_version.
    Version strings must change whenever question definitions/model policy change.
    A version's question definitions and model alias are immutable in the ledger.
    choice: criteria map, answer {choice,confidence}; score: ordered criteria list,
    answer {score,confidence} with score 0..len-1; noul: {noul}, a single
    probability with no required confidence (official primitives/noul.md).
    Optional answer type must match the requested question type.
    All noul/confidence values must be finite in [0,1]; any supplied confidence
    is validated. The guessed probability-only noul response is rejected.
    request_fn(wire_payload,api_key) returns {answers,usage:{input_tokens,
    output_tokens},model:concrete_revision}, optional _http:{status}; exactly once.
    Wire omits version metadata and recursively omits observed_at/captured_at/
    observation_timestamp from state. Full remaining canonical payload is hashed.
    Alias cache TTL defaults 1h, capped at 24h via TYPESAFE_CACHE_TTL_SEC.
    Failure returns validated fallback or answers=None, source/mode, enforced:false.
    Required env: ENABLED=1, FREE_CREDITS_ONLY=1, API_KEY, ORG_ID,
    BILLING_PROOF_PATH, absolute SHARED_LEDGER_PATH (all prefixed TYPESAFE_).
    Proof fields key_sha256,org_id,available_free_usd,auto_recharge:false,
    payment_method_on_file:false,verified_at,expires_at (ISO aware, max24h).
    TYPESAFE_WORKFLOW_ID defaults 'shared', never resets per process/team.
    Only the publishing orchestrator sets a run ID; teams must not choose their own.
    Workflow budget denial stops only that run. Account/transport/protocol failures
    and reported usage overshoot stop the entire shared ledger.
    MAX_CALLS/MAX_INPUT_TOKENS/MAX_COST_USD can only lower 40/60000/.00252.
    Account allowance is initial verified free balance, never replenished on refresh.
    TYPESAFE_ACCOUNT_MAX_COST_USD can further lower that cumulative account cap.
    TYPESAFE_ALLOW_PAID=1 is unconditionally rejected. Never authoritative gates.
    """
    r={'source':'unavailable','mode':'blocked','enforced':False,'answers':None,'usage':None,'model':None,
       'paid_api_called':False,'free_credits_only':True,'provider_free_only_enforcement':False,'scope':SCOPE}
    try:
        p=validate_payload(payload); r['model']=p['model']
        if fallback_answers is not None:
            validate_answers(fallback_answers,p['questions'])
            r.update(source='deterministic_local',answers=copy.deepcopy(fallback_answers))
        if os.environ.get('TYPESAFE_ALLOW_PAID','').strip()=='1':
            raise SafetyStop('paid_override_rejected')
        if os.environ.get('TYPESAFE_ENABLED')!='1':
            raise SafetyStop('disabled_local_advisory')
        if os.environ.get('TYPESAFE_FREE_CREDITS_ONLY')!='1':
            raise SafetyStop('free_only_required')
        key=os.environ.get('TYPESAFE_API_KEY','').strip()
        if not key:
            raise SafetyStop('missing_api_key')
        fp,org,allowance=proof(key)
        path=ledger_path(); lim=limits()
        ttl=float(os.environ.get('TYPESAFE_CACHE_TTL_SEC','3600'))
        if not number(ttl) or not 0<ttl<=86400:
            raise SafetyStop('invalid_cache_ttl')
        wire={k:v for k,v in p.items() if k not in ('question_version','model_policy_version')}
        reserve=len(canonical(wire).encode('utf-8'))+2048
        ck=digest(p); qv='questions:'+p['question_version']; mv='model:'+p['model_policy_version']
        bindings={qv:digest(p['questions']),mv:digest(p['model'])}
        wid=os.environ.get('TYPESAFE_WORKFLOW_ID','shared').strip()
        if not wid:
            raise SafetyStop('workflow_id_required')
        with lock(path):
            fp,org,allowance=proof(key)
            s=read(path)
            if s is None:
                s={'schema':1,'key_sha256':fp,'org_id':org,'account_limit_usd':allowance,
                   'account_charged_tokens':0,'stopped':'','workflows':{},'cache':{},'versions':{}}
            if s.get('key_sha256')!=fp or s.get('org_id')!=org:
                raise SafetyStop('ledger_identity_mismatch')
            if s['stopped']:
                raise SafetyStop('shared_stopped:'+s['stopped'])
            for version,binding in bindings.items():
                if version in s['versions'] and s['versions'][version]!=binding:
                    raise SafetyStop('immutable_version_changed')
            hit=s['cache'].get(ck)
            if hit and number(hit.get('created_at')) and 0<=time.time()-hit['created_at']<min(ttl,hit['ttl']):
                valid=validate_response(hit['response'],p)
                return {**r,**valid,'source':'typesafe_cache','mode':'typesafe_cached_advisory','cache_hit':True}
            b=s['workflows'].setdefault(wid,{**lim,'calls':0,'charged_input_tokens':0,'reserved_input_tokens':0,
                                           'input_tokens':0,'output_tokens':0,'call_log':[],'stopped':''})
            if b.get('stopped'):
                raise SafetyStop('workflow_stopped:'+b['stopped'])
            for k,v in lim.items():
                b[k]=min(b[k],v)
            account_cap=float(os.environ.get('TYPESAFE_ACCOUNT_MAX_COST_USD',s['account_limit_usd']))
            if not number(account_cap) or account_cap<=0:
                raise SafetyStop('invalid_account_budget')
            s['account_limit_usd']=min(s['account_limit_usd'],account_cap)
            remaining=min(allowance,s['account_limit_usd']-s['account_charged_tokens']*PRICE)
            if reserve*PRICE>remaining:
                s['stopped']='account_budget_denied'; write(path,s); raise SafetyStop(s['stopped'])
            if (b['calls']+1>b['max_calls'] or b['charged_input_tokens']+reserve>b['max_input_tokens']
                or (b['charged_input_tokens']+reserve)*PRICE>b['max_cost_usd']):
                b['stopped']='pre_request_budget_denied'; write(path,s); raise SafetyStop(b['stopped'])
            s['versions'].update(bindings); b['calls']+=1
            b['reserved_input_tokens']+=reserve; b['charged_input_tokens']+=reserve
            s['account_charged_tokens']+=reserve; s['stopped']='request_in_flight_or_ambiguous'
            record={'cache_key':ck,'reserved_input_tokens':reserve,'ok':False}; b['call_log'].append(record)
            write(path,s)
            try:
                if request_fn is None:
                    try:
                        from .typesafe_decision_support import _request
                    except ImportError:
                        from typesafe_decision_support import _request
                    request_fn=_request
                body=request_fn(wire,key)
                u=body.get('usage',{}) if isinstance(body,dict) else {}
                actual=u.get('input_tokens') if isinstance(u,dict) else None
                if number(actual):
                    extra=max(0,actual-reserve); b['charged_input_tokens']+=extra; s['account_charged_tokens']+=extra
                    b['input_tokens']+=actual
                valid=validate_response(body,p)
                output=valid['usage']['output_tokens']; b['output_tokens']+=output; b['reserved_input_tokens']-=reserve
                record.update(input_tokens=actual,output_tokens=output,model=valid['model'])
                if (actual>reserve or b['charged_input_tokens']>b['max_input_tokens'] or b['charged_input_tokens']*PRICE>b['max_cost_usd']
                    or s['account_charged_tokens']*PRICE>s['account_limit_usd']):
                    raise SafetyStop('reported_usage_overshoot')
                record['ok']=True; s['stopped']=''
                s['cache'][ck]={'response':valid,'created_at':time.time(),'ttl':ttl}
                write(path,s)
                return {**r,**valid,'source':'typesafe','mode':'typesafe_observational_free_credits','cache_hit':False}
            except Exception as exc:
                s['stopped']=str(exc) if isinstance(exc,SafetyStop) else 'request_or_protocol_failure'
                record['ok']=False; s['cache'].pop(ck,None)
                try:
                    write(path,s)
                except Exception:
                    pass
                raise SafetyStop(s['stopped']) from None
    except Exception as exc:
        r['mode']=str(exc) if isinstance(exc,SafetyStop) else 'local_safety_failure'
        return r
