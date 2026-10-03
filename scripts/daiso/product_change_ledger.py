#!/usr/bin/env python3
"""Read-only deterministic removal proof and exact-base publish deletion records."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess

PRODUCT_PATH = 'data/daiso_real/products.json'
ARCHIVE_PATH = 'data/daiso_real/excluded_products.json'
PRICING_PATH = 'data/pricing_model.json'
RULE_PATH = 'data/daiso_real/profitability_rule.json'
LEDGER_PATH = 'data/daiso_real/product_change_reasons.json'
MANIFEST_PATH = 'data/publish_deletions.json'
REASON_TAG = '손익·마진 미달'


def sha(data): return hashlib.sha256(data).hexdigest()
def canonical(doc): return json.dumps(doc,ensure_ascii=False,sort_keys=True,separators=(',', ':'),allow_nan=False).encode('utf-8')
def encode(doc): return (json.dumps(doc,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
def read_json(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def finite(value, name, *, positive=False, nonnegative=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(f'{name}: finite numeric fact required')
    if (positive and value<=0) or (nonnegative and value<0): raise ValueError(f'{name}: invalid numeric range')
    return float(value)


def thresholds(cfg):
    if not isinstance(cfg,dict): raise ValueError('profitability rule must be an object')
    return {'min_margin_pct':finite(cfg.get('min_margin_pct'),'min_margin_pct',nonnegative=True),
            'min_net_profit_usd':finite(cfg.get('min_net_profit_usd'),'min_net_profit_usd',nonnegative=True)}


def rows_index(doc):
    rows = doc.get('products') if isinstance(doc,dict) else doc
    if not isinstance(rows,list): raise ValueError('product list missing/malformed')
    found={}
    for row in rows:
        if not isinstance(row,dict): raise ValueError('product row malformed')
        pd_no=str(row.get('pd_no') or row.get('product_id') or '').strip()
        if not pd_no or pd_no in found: raise ValueError('missing/duplicate product identity')
        found[pd_no]=row
    return found


def archive_items(doc):
    if not isinstance(doc,dict) or not isinstance(doc.get('items'),dict): raise ValueError('archive items object missing/malformed')
    for pd_no,row in doc['items'].items():
        if not str(pd_no).strip() or not isinstance(row,dict): raise ValueError('archive identity/record malformed')
    return doc['items']


def validate_offer(row):
    if not isinstance(row,dict) or not str(row.get('pd_no') or '').strip(): raise ValueError('offer identity missing')
    price=finite(row.get('price_usd'),'price_usd',positive=True)
    cost=finite(row.get('landed_cost_total_usd'),'landed_cost_total_usd',nonnegative=True)
    fee=finite(row.get('fee_usd'),'fee_usd',nonnegative=True)
    net=finite(row.get('net_profit_usd'),'net_profit_usd')
    margin=finite(row.get('margin_pct'),'margin_pct')
    qty=finite(row.get('qty'),'qty',positive=True)
    if qty!=int(qty): raise ValueError('offer qty must be a positive integer')
    actual_net=price-cost-fee
    # Inputs/net have cent rounding; margin has one decimal rounding.
    if abs(actual_net-net)>0.021: raise ValueError('offer net-profit arithmetic mismatch')
    if abs(net/price*100-margin)>0.11: raise ValueError('offer margin arithmetic mismatch')
    if row.get('register_blocked') and actual_net>=0:
        raise ValueError('register_blocked cannot replace a proven loss calculation')
    return {'net_profit_calculated_usd':round(actual_net,8),'margin_calculated_pct':round(net/price*100,8)}


def offer_groups(pricing):
    if not isinstance(pricing,dict) or not isinstance(pricing.get('offers_by_product'),dict): raise ValueError('offers_by_product missing/malformed')
    groups={}
    for form,rows in pricing['offers_by_product'].items():
        if not isinstance(rows,list):
            if form=='규칙' and isinstance(rows,str): continue
            raise ValueError('offer form must contain rows')
        seen=set()
        for row in rows:
            validate_offer(row);pd_no=str(row['pd_no']).strip()
            if pd_no in seen: raise ValueError('duplicate offer identity in one form')
            seen.add(pd_no);groups.setdefault(pd_no,[]).append(dict(deepcopy(row),form=form))
    return groups


def best_from_rows(rows):
    if not isinstance(rows,list) or not rows: raise ValueError('observed offer facts missing')
    seen=set()
    for row in rows:
        validate_offer(row)
        key=(str(row['pd_no']),str(row.get('form') or ''))
        if not key[1] or key in seen: raise ValueError('missing/duplicate observed offer form')
        seen.add(key)
    return deepcopy(max(rows,key=lambda r:(float(r['margin_pct']),float(r['net_profit_usd']))))


def below_policy(row,cfg):
    validate_offer(row);limits=thresholds(cfg)
    return (float(row['margin_pct'])<limits['min_margin_pct'] or float(row['net_profit_usd'])<limits['min_net_profit_usd'])


def proof_record(pd_no,action,original,offers,cfg,pricing_bytes,rule_bytes,before,after,execution_id,observed_at):
    best=best_from_rows(offers)
    if action not in {'exclude','restore'} or below_policy(best,cfg)!=(action=='exclude'):
        raise ValueError('change is not supported by actual deterministic profitability decision')
    reason=(f"Best observed {best['form']} offer margin={best['margin_pct']}% net=${best['net_profit_usd']}; "
            f"policy minimum margin={cfg['min_margin_pct']}% net=${cfg['min_net_profit_usd']}; {action}")
    return {'pd_no':str(pd_no),'action':action,'verified':True,'reason':reason,'source':PRICING_PATH,'policy_ref':RULE_PATH,
            'before_sha256':sha(before),'after_sha256':sha(after),'execution_id':execution_id,'observed_at':observed_at,
            'evidence':{'offers':deepcopy(offers),'offers_sha256':sha(canonical(offers)),
                        'best_offer':best,'thresholds':thresholds(cfg),'pricing_source_sha256':sha(pricing_bytes),
                        'rule_sha256':sha(rule_bytes),'archive_original':deepcopy(original),
                        'archive_original_sha256':sha(canonical(original)),**validate_offer(best)}}


def append_changes(document,records,pricing_bytes=None):
    if document is None: document={'schema_version':1,'changes':[],'pricing_sources':{}}
    if not isinstance(document,dict) or document.get('schema_version')!=1 or not isinstance(document.get('changes'),list): raise ValueError('change ledger malformed')
    result=deepcopy(document);keys=set()
    snapshots=result.setdefault('pricing_sources',{})
    if not isinstance(snapshots,dict): raise ValueError('pricing snapshots malformed')
    if pricing_bytes is not None:
        text=pricing_bytes.decode('utf-8')
        offer_groups(json.loads(text))
        snapshots[sha(pricing_bytes)]=text
    for row in result['changes']:
        if not isinstance(row,dict): raise ValueError('change ledger record malformed')
        keys.add((row.get('pd_no'),row.get('action'),row.get('before_sha256'),row.get('after_sha256')))
    for row in records:
        key=(row['pd_no'],row['action'],row['before_sha256'],row['after_sha256'])
        if key not in keys:result['changes'].append(deepcopy(row));keys.add(key)
    return result


def head_file(root,name):
    result=subprocess.run(['git','-C',str(root),'show','HEAD:'+name],capture_output=True)
    if result.returncode: raise ValueError('tracked immutable HEAD input unavailable: '+name)
    return result.stdout


def deletion_manifest(root,document,path,removed,reason):
    if not removed:return deepcopy(document) if document is not None else None
    base=head_file(root,path);doc=json.loads(base)
    available=set(rows_index(doc)) if path==PRODUCT_PATH else set(archive_items(doc))
    ids=sorted(set(map(str,removed)) & available)
    if not ids:return deepcopy(document) if document is not None else None
    if document is None:document={'schema_version':1,'deletions':[]}
    if not isinstance(document,dict) or document.get('schema_version')!=1 or not isinstance(document.get('deletions'),list): raise ValueError('publish deletion manifest malformed')
    result=deepcopy(document);base_hash=sha(base)
    matching=[]
    for row in result['deletions']:
        if not isinstance(row,dict) or not isinstance(row.get('ids',[]),list): raise ValueError('publish deletion record malformed')
        if row.get('path')==path and row.get('base_sha256')==base_hash and row.get('policy_ref')==RULE_PATH:matching.append(row)
    if matching:
        record=matching[0];record['ids']=sorted(set(map(str,record['ids']))|set(ids))
        result['deletions']=[row for row in result['deletions'] if row not in matching[1:]]
    else:
        result['deletions'].append({'path':path,'base_sha256':base_hash,'ids':ids,'reason':reason,'policy_ref':RULE_PATH,'delete_file':False})
    return result


def validate_removal_evidence(root,baseline,removed_ids):
    """Validate actual monetary facts and replay exact-byte exclusion/restore chains."""
    root,baseline=Path(root),Path(baseline);errors=[]
    try:
        baseline_file=baseline/PRODUCT_PATH if baseline.is_dir() else baseline
        before=baseline_file.read_bytes();after=(root/PRODUCT_PATH).read_bytes()
        old=rows_index(json.loads(before));current=rows_index(json.loads(after));ids=set(map(str,removed_ids))
        if ids!=set(old)-set(current):raise ValueError('requested removals do not match exact operating-ID delta')
        if not ids:return True,[]
        ledger=read_json(root/LEDGER_PATH)
        if not isinstance(ledger,dict) or ledger.get('schema_version')!=1 or not isinstance(ledger.get('changes'),list):raise ValueError('removal ledger malformed')
        snapshots=ledger.get('pricing_sources')
        if not isinstance(snapshots,dict):raise ValueError('captured pricing sources missing')
        archive=archive_items(read_json(root/ARCHIVE_PATH))
        rule_bytes=(root/RULE_PATH).read_bytes();cfg=json.loads(rule_bytes);limits=thresholds(cfg)
        def verify(row):
            e=row.get('evidence') or {};pd_no=str(row.get('pd_no') or '')
            if row.get('verified') is not True or row.get('action') not in {'exclude','restore'} or row.get('source')!=PRICING_PATH or row.get('policy_ref')!=RULE_PATH or not row.get('execution_id') or not isinstance(row.get('reason'),str) or len(row['reason'].strip())<8:raise ValueError('removal provenance missing')
            observed=datetime.fromisoformat(row['observed_at'].replace('Z','+00:00'))
            if observed.tzinfo is None or observed>datetime.now(timezone.utc)+timedelta(minutes=5):raise ValueError('invalid removal observation time')
            if e.get('thresholds')!=limits or e.get('rule_sha256')!=sha(rule_bytes):raise ValueError('profitability policy changed/missing')
            captured=snapshots.get(e.get('pricing_source_sha256'))
            if not isinstance(captured,str) or sha(captured.encode('utf-8'))!=e.get('pricing_source_sha256'):raise ValueError('captured pricing source missing/tampered')
            offers=e.get('offers');best=best_from_rows(offers)
            if offer_groups(json.loads(captured)).get(pd_no)!=offers or e.get('offers_sha256')!=sha(canonical(offers)) or e.get('best_offer')!=best:raise ValueError('complete captured offers disagree with proof')
            if below_policy(best,cfg)!=(row['action']=='exclude'):raise ValueError('actual best offer does not justify action')
            original=e.get('archive_original')
            if not isinstance(original,dict) or str(original.get('pd_no') or original.get('product_id') or '')!=pd_no or e.get('archive_original_sha256')!=sha(canonical(original)):raise ValueError('archived original proof invalid')
            if any(e.get(k)!=v for k,v in validate_offer(best).items()):raise ValueError('monetary math evidence mismatch')
            return original,best
        groups={}
        for row in ledger['changes']:
            if not isinstance(row,dict):raise ValueError('ledger record malformed')
            key=(row.get('before_sha256'),row.get('after_sha256'),row.get('execution_id'))
            groups.setdefault(key,[]).append(row)
        pending=[(before,[])];seen=set();proof_path=None
        while pending:
            state_bytes,trail=pending.pop(0);state_hash=sha(state_bytes)
            if state_hash==sha(after):proof_path=trail;break
            if state_hash in seen:continue
            seen.add(state_hash)
            for (base_hash,target_hash,_),records in groups.items():
                if base_hash!=state_hash:continue
                try:
                    doc=json.loads(state_bytes);by_id=rows_index(doc)
                    rows=deepcopy(doc['products'] if isinstance(doc,dict) else doc)
                    batch_ids=set()
                    for row in records:
                        pd_no=str(row.get('pd_no') or '')
                        if pd_no in batch_ids:raise ValueError('duplicate identity in policy-change batch')
                        batch_ids.add(pd_no);original,_best=verify(row)
                        if row['action']=='exclude':
                            if by_id.get(pd_no)!=original:raise ValueError('exclusion original disagrees with before state')
                            rows=[p for p in rows if str(p.get('pd_no') or p.get('product_id') or '')!=pd_no]
                        else:
                            if pd_no in by_id:raise ValueError('restoration would duplicate operating identity')
                            rows.append(deepcopy(original))
                    if isinstance(doc,dict):doc['products']=rows;doc['count']=len(rows)
                    else:doc=rows
                    next_bytes=encode(doc)
                    if sha(next_bytes)!=target_hash:raise ValueError('policy delta cannot reproduce declared after hash')
                    pending.append((next_bytes,trail+records))
                except (ValueError,TypeError,KeyError,AttributeError):continue
        if proof_path is None:raise ValueError('complete exact-baseline policy change chain missing or invalid')
        for pd_no in sorted(ids):
            matches=[r for r in proof_path if str(r.get('pd_no'))==pd_no and r.get('action')=='exclude']
            if not matches:raise ValueError('actual removal proof missing: '+pd_no)
            original,best=verify(matches[-1]);record=archive.get(pd_no,{})
            if original!=old[pd_no] or record.get('원본')!=original or record.get('뺀_규칙')!=REASON_TAG or record.get('그때_숫자')!=best:raise ValueError('archive does not preserve baseline and actual monetary facts: '+pd_no)
    except (OSError,ValueError,TypeError,KeyError,AttributeError,OverflowError,json.JSONDecodeError) as exc:errors.append(str(exc))
    return not errors,errors
