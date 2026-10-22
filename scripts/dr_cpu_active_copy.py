#!/usr/bin/env python3
"""One reviewed ACTIVE description correction. No activation, image or price writes.

The fixed policy permits only three exact substitutions for Dr.CPU 1084687.
Existing DRAFT guards remain separate. Default execution is offline/dry-run;
write uncertainty is reconciled read-only through the shared transaction engine.
"""
from copy import deepcopy
from datetime import timedelta
import argparse
import hashlib
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re

import apply_reviewed_product_gallery as gallery
import reviewed_copy_transaction as transaction
from apply_reviewed_product_gallery import (Hold, require, utcnow, stamp, read_json,
    json_bytes, atomic_json, https_request, SHA256, SHOP)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'data/manual/active_copy/1084687-20261022.json'
POLICY_ID = 'drcpu-1084687-description-20261022-v1'
POLICY_SHA = 'de9347683483c940f2e936e7ea1e12e635eec5f4c2926d474a341ab6f2edabbc'
PD = '1084687'
PRODUCT = 'gid://shopify/Product/9590780723457'
SHOP_ID = 'gid://shopify/Shop/82748997889'
CANONICAL_SHOP = 'rb3zh1-i1.myshopify.com'
TITLE = 'Dr.CPU+ Lacto Exosome Glutathione Capsule Cream'
BEFORE_SHA = '5a39446eb23495c69add58c7f335fdccf7fbb70dd34d67c6e8d49b79ab4cd3fa'
AFTER_SHA = 'd90ecc6170dfbd520d06a2dca6593f54f9a6ef758662316447810b6b417f9bfc'
PUBLIC_URL = 'https://coarfamily.myshopify.com/ko/products/dr-cpu-lacto-exosome-glutathione-capsule-cream'
PUBLIC_HOST = 'coarfamily.myshopify.com'
HANDLE = 'dr-cpu-lacto-exosome-glutathione-capsule-cream'
# Bind to the reviewed main product description, not search cards or modal copies.
DESCRIPTION_CLASS = 'text-block--AcTY4cVB6WTZLNW5CT__text_aEtTtq'
WORKFLOW = '.github/workflows/shopify-reviewed-active-copy.yml'
PREFIX = 'drcpu-description-checkpoint-'
FLAGS = ('rights_verified', 'physical_label_verified', 'quantity_conflict_resolved',
         'inci_verified', 'safety_approved', 'price_basis_verified', 'publication_allowed', 'upload_allowed')
SCOPE_KEYS = {'schema_version','policy_id','policy_sha256','shop_id','canonical_shop','transport_shop',
    'product_id','pd_no','expected_status','execution_ticket','authorized_at','expires_at',
    'allowed_fields','expected_implementation_digest'}
# Additional fields inspected with Shopify graphql_schema on 2026-10-22.
EXTRA_QUERY = '''query DrCpuCopyMetadata($id:ID!){shop{id myshopifyDomain currencyCode}
 product(id:$id){id title descriptionHtml updatedAt vendor productType handle status
 onlineStoreUrl seo{title description}}}'''
EXTRA_VARIANTS = '''query DrCpuCopyVariantMetadata($id:ID!,$after:String){product(id:$id){id
 variants(first:100,after:$after){nodes{id title barcode taxable
 inventoryItem{id requiresShipping measurement{weight{value unit}}}}
 pageInfo{hasNextPage endCursor}}}}'''
UPDATE = '''mutation DrCpuReviewedDescription($product:ProductUpdateInput!){
 productUpdate(product:$product){product{id} userErrors{field message}}}'''


def sha(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def text_sha(value):
    require(isinstance(value, str), 'description_string_required')
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def read_policy():
    policy = read_json(POLICY)
    require(sha(policy) == POLICY_SHA and policy.get('policy_id') == POLICY_ID,
            'immutable_policy_mismatch')
    require(all(policy.get(k) is False for k in FLAGS), 'review_flags_must_remain_false')
    require(policy.get('product_id') == PRODUCT and policy.get('shop_id') == SHOP_ID
            and policy.get('pd_no') == PD and policy.get('expected_status') == 'ACTIVE', 'policy_target_invalid')
    before = policy.get('before_html')
    require(text_sha(before) == policy.get('before_sha256') == BEFORE_SHA, 'policy_before_hash_invalid')
    after = before
    require(len(policy.get('replacements', [])) == 3, 'exact_three_replacements_required')
    for change in policy['replacements']:
        require(after.count(change['old']) == 1 and after.count(change['new']) == 0,
                'policy_replacement_not_unique')
        after = after.replace(change['old'], change['new'], 1)
    require(text_sha(after) == policy.get('after_sha256') == AFTER_SHA, 'policy_after_hash_invalid')
    return policy


def target_html(policy=None):
    policy = policy or read_policy()
    body = policy['before_html']
    for change in policy['replacements']:
        body = body.replace(change['old'], change['new'], 1)
    require(text_sha(body) == AFTER_SHA, 'target_hash_invalid')
    return body


def validate_snapshot(snapshot, *, now=None, fresh=True):
    gallery.validate_snapshot(snapshot, now=now, fresh=fresh)
    shop, p = snapshot['shop'], snapshot['product']
    require(shop.get('id') == SHOP_ID and shop.get('myshopifyDomain') == CANONICAL_SHOP,
            'exact_shop_required')
    require(isinstance(shop.get('currencyCode'), str) and re.fullmatch('[A-Z]{3}', shop['currencyCode']),
            'currency_protection_missing')
    require(p.get('id') == PRODUCT and p.get('status') == 'ACTIVE' and p.get('title') == TITLE
            and p.get('handle') == HANDLE and p.get('onlineStoreUrl') == PUBLIC_URL, 'exact_active_product_required')
    require([t for t in p['tags'] if t.startswith('daiso-pd-')] == ['daiso-pd-' + PD],
            'exact_supplier_identity_required')
    require(all(isinstance(p.get(k), str) for k in ('descriptionHtml','vendor','productType')),
            'copy_metadata_missing')
    seo = p.get('seo')
    require(isinstance(seo, dict) and set(seo) == {'title','description'} and
            all(v is None or isinstance(v, str) for v in seo.values()), 'seo_protection_missing')
    identity = [{k: v[k] for k in ('id','sku','selectedOptions')} for v in p['variants']]
    require(identity == read_policy()['variant_identity'], 'exact_variant_identity_required')
    for v in p['variants']:
        item = v['inventoryItem']
        require(isinstance(v.get('title'), str) and 'barcode' in v and
                (v['barcode'] is None or isinstance(v['barcode'], str)) and type(v.get('taxable')) is bool
                and type(item.get('requiresShipping')) is bool, 'variant_metadata_protection_missing')
        weight = (item.get('measurement') or {}).get('weight')
        require(isinstance(weight, dict) and type(weight.get('value')) in (int,float)
                and math.isfinite(weight['value']) and weight['value'] >= 0
                and weight.get('unit') in {'KILOGRAMS','GRAMS','OUNCES','POUNDS'}, 'weight_protection_missing')
    return snapshot


def protected(snapshot):
    result = deepcopy(snapshot)
    result.pop('observed_at', None)
    # Title is protected: unlike DRAFT copy, this operation cannot rename.
    for field in ('descriptionHtml','updatedAt'):
        result['product'].pop(field, None)
    return result


def implementation_digest():
    paths = ['scripts/dr_cpu_active_copy.py','scripts/reviewed_copy_transaction.py',
             'scripts/apply_reviewed_product_gallery.py','scripts/plan_active_product_gallery.py',
             'scripts/gallery_review.py','data/manual/active_copy/1084687-20261022.json',WORKFLOW]
    return sha({name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths})


def validate_scope(scope, snapshot, now, *, expiry=True):
    require(isinstance(scope, dict) and set(scope) == SCOPE_KEYS and
            type(scope.get('schema_version')) is int and scope['schema_version'] == 1, 'exact_scope_required')
    require(scope.get('policy_id') == POLICY_ID and scope.get('policy_sha256') == POLICY_SHA,
            'scope_policy_mismatch')
    require(scope.get('shop_id') == SHOP_ID and scope.get('canonical_shop') == CANONICAL_SHOP
            and scope.get('product_id') == PRODUCT and scope.get('pd_no') == PD
            and scope.get('expected_status') == snapshot['product']['status'] == 'ACTIVE', 'scope_target_mismatch')
    require(scope.get('allowed_fields') == ['descriptionHtml'], 'description_only_scope_required')
    require(isinstance(scope.get('transport_shop'), str) and SHOP.fullmatch(scope['transport_shop']),
            'explicit_transport_shop_required')
    require(isinstance(scope.get('execution_ticket'), str) and
            re.fullmatch(r'[A-Za-z0-9_-]{1,64}', scope['execution_ticket']), 'execution_ticket_invalid')
    start, end = stamp(scope.get('authorized_at')), stamp(scope.get('expires_at'))
    require(timedelta(0) < end-start <= timedelta(hours=24), 'scope_window_invalid')
    require(not expiry or start <= now < end, 'scope_expired_or_future')
    require(scope.get('expected_implementation_digest') == implementation_digest(), 'implementation_mismatch')


def operation_id(scope=None):
    # A different ticket/run cannot reset the same correction's attempt history.
    return sha({'policy_id':POLICY_ID,'shop_id':SHOP_ID,'product_id':PRODUCT,
                'before_sha256':BEFORE_SHA,'after_sha256':AFTER_SHA})[:32]


def source_path(root, source):
    root = Path(root).resolve(); path = root/source['local_file']
    require(path.resolve().is_relative_to(root) and not path.is_symlink(), 'source_path_unsafe')
    return path


def verify_sources(root):
    for source in read_policy()['sources']:
        path = source_path(root, source)
        require(path.is_file() and 0 < path.stat().st_size <= gallery.MAX_BYTES
                and hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256'], 'source_bytes_unverified')


def fetch_sources(pd_no, root, *, fetch=gallery.fetch_asset):
    require(pd_no == PD, 'source_product_not_allowlisted')
    for source in read_policy()['sources']:
        raw = fetch(source['source_url'], {'cdn.daisomall.co.kr'})
        require(isinstance(raw, bytes) and 0 < len(raw) <= gallery.MAX_BYTES
                and hashlib.sha256(raw).hexdigest() == source['sha256'], 'live_source_hash_mismatch')
        path = source_path(root, source); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)


def copy_plan(snapshot):
    policy = read_policy(); body = snapshot['product']['descriptionHtml']; digest = text_sha(body)
    require(digest in {BEFORE_SHA,AFTER_SHA}, 'unreviewed_current_body')
    after = target_html(policy)
    if digest == BEFORE_SHA:
        for c in policy['replacements']:
            require(body.count(c['old']) == 1 and body.count(c['new']) == 0, 'replacement_missing_duplicate_or_mixed')
    result = {'kind':'drcpu_exact_description','product_id':PRODUCT,'before':deepcopy(snapshot),
              'changes':{'descriptionHtml':after} if digest == BEFORE_SHA else {},
              'policy_sha256':POLICY_SHA,'protected_sha256':sha(protected(snapshot)),**dict.fromkeys(FLAGS,False)}
    result['plan_sha256'] = sha(result)
    return result


def compute_plan_digest(plan):
    value = deepcopy(plan); value.pop('plan_digest',None)
    value['before'].pop('observed_at',None)
    value['copy_plan']['before'].pop('observed_at',None)
    value['copy_plan'].pop('plan_sha256',None)
    return sha(value)


def build_plan(scope, root, snapshot, *, now=None):
    now = now or utcnow(); validate_snapshot(snapshot,now=now); validate_scope(scope,snapshot,now)
    verify_sources(root)
    result = {'schema_version':1,'kind':'reviewed_drcpu_active_description','operation_id':operation_id(),
              'scope':deepcopy(scope),'before':deepcopy(snapshot),'copy_plan':copy_plan(snapshot),
              'implementation_digest':implementation_digest(),**dict.fromkeys(FLAGS,False)}
    result['plan_digest'] = compute_plan_digest(result)
    return result


def validate_plan_digest(plan, expected):
    require(isinstance(expected,str) and SHA256.fullmatch(expected) and
            plan.get('plan_digest') == expected == compute_plan_digest(plan), 'plan_digest_mismatch')
    require(set(plan) == {'schema_version','kind','operation_id','scope','before','copy_plan',
                         'implementation_digest','plan_digest',*FLAGS}, 'plan_shape_invalid')
    require(plan['schema_version'] == 1 and plan['kind'] == 'reviewed_drcpu_active_description'
            and plan['operation_id'] == operation_id() and all(plan[k] is False for k in FLAGS), 'plan_authority_invalid')
    validate_snapshot(plan['before'],fresh=False)
    validate_scope(plan['scope'],plan['before'],utcnow(),expiry=False)
    require(plan['implementation_digest'] == implementation_digest(), 'plan_implementation_mismatch')
    require(plan['copy_plan'] == copy_plan(plan['before']), 'copy_plan_reconstruction_mismatch')


def verify_readback(cp, snapshot):
    validate_snapshot(snapshot)
    require(cp == copy_plan(cp['before']), 'copy_plan_tampered')
    require(protected(snapshot) == protected(cp['before']), 'protected_fields_changed')
    require(text_sha(snapshot['product']['descriptionHtml']) == AFTER_SHA, 'copy_readback_mismatch')
    return {'state':'copy_readback_verified',**dict.fromkeys(FLAGS,False)}


class Text(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.parts=[]
    def handle_data(self,data): self.parts.append(data)


def semantic(body):
    parser=Text(); parser.feed(body); return ' '.join(' '.join(parser.parts).split())


class PublicDescription(HTMLParser):
    """Inspect only the reviewed main product description, never cards or dialogs."""
    VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    def __init__(self):
        super().__init__(convert_charrefs=True); self.stack=[]; self.canonicals=[]; self.descriptions=[]; self.main_count=0
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs); parent=self.stack[-1] if self.stack else {}
        hidden=(parent.get('hidden',False) or tag in {'script','style','template','noscript'} or 'hidden' in attrs
                or (tag in {'dialog','details'} and 'open' not in attrs)
                or attrs.get('aria-hidden')=='true' or
                re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)',attrs.get('style',''),re.I))
        main=parent.get('main',False)
        if tag=='main':
            main=attrs.get('id')=='MainContent' and attrs.get('data-template')=='product'
            if main:self.main_count+=1
        exact=parent.get('exact',False)
        if tag=='product-component':
            try:
                identity=gallery.strict_json(attrs.get('view-event-payload','{}')).get('product',{})
                exact=(main and 'data-product-grid-content' in attrs
                       and 'product-information__grid' in attrs.get('class','').split()
                       and str(identity.get('id'))==PRODUCT.rsplit('/',1)[1] and identity.get('handle')==HANDLE)
            except (ValueError,TypeError,AttributeError): exact=False
        if tag=='link' and attrs.get('rel')=='canonical': self.canonicals.append(attrs.get('href'))
        if tag not in self.VOID:
            self.stack.append({'tag':tag,'hidden':bool(hidden),'exact':exact,'main':main,
                               'text':[] if tag=='rte-formatter' and exact and not hidden
                               and DESCRIPTION_CLASS in attrs.get('class','').split() else None})
    def handle_endtag(self,tag):
        if tag in self.VOID:return
        matches=[i for i,v in enumerate(self.stack) if v['tag']==tag]
        if not matches:return
        index=matches[-1]
        for item in self.stack[index:]:
            if item['text'] is not None:self.descriptions.append(' '.join(' '.join(item['text']).split()))
        del self.stack[index:]
    def handle_data(self,data):
        if self.stack and not self.stack[-1]['hidden']:
            for item in self.stack:
                if item['text'] is not None:item['text'].append(data)


def verify_public_html(raw):
    require(isinstance(raw,bytes) and 0<len(raw)<=gallery.MAX_BYTES,'public_html_invalid')
    parser=PublicDescription(); parser.feed(raw.decode('utf-8')); parser.close()
    require(parser.canonicals==[PUBLIC_URL], 'public_canonical_mismatch')
    require(parser.main_count==1 and parser.descriptions==[semantic(target_html())],
            'public_description_pending')
    return {'public_readback_verified':True,'public_html_sha256':hashlib.sha256(raw).hexdigest()}


class ShopifyClient(gallery.ShopifyClient):
    def gql(self,document,variables):
        # This final transport guard also closes inherited gallery/raw mutation paths.
        require(isinstance(variables,dict),'graphql_variables_invalid')
        if document==UPDATE:
            product=variables.get('product')
            require(set(variables)=={'product'} and isinstance(product,dict)
                    and set(product)=={'id','descriptionHtml'} and product['id']==PRODUCT
                    and text_sha(product['descriptionHtml'])==AFTER_SHA,'exact_description_mutation_required')
            require(not getattr(self,'_write_attempted',False),'mutation_already_attempted')
            self._write_attempted=True  # Set before request: even timeout forbids a second send.
        else:
            single={EXTRA_QUERY,gallery.BASE_QUERY}
            paged={EXTRA_VARIANTS,gallery.MEDIA_QUERY,gallery.VARIANTS_QUERY,
                   gallery.VARIANT_MEDIA_QUERY,gallery.INVENTORY_QUERY,gallery.PUBLICATIONS_QUERY}
            require(document in single|paged,'graphql_document_not_allowlisted')
            require(set(variables)==({'id'} if document in single else {'id','after'}),
                    'graphql_variables_invalid')
            if document in paged:
                require(variables['after'] is None or isinstance(variables['after'],str),
                        'graphql_cursor_invalid')
            allowed={PRODUCT}
            if document==gallery.VARIANT_MEDIA_QUERY:
                allowed={v['id'] for v in read_policy()['variant_identity']}
            elif document==gallery.INVENTORY_QUERY:
                allowed=getattr(self,'_inventory_ids',set())
            require(variables['id'] in allowed,'graphql_target_not_allowlisted')
        result=super().gql(document,variables)
        if document==gallery.VARIANTS_QUERY:
            product=result.get('product')
            require(isinstance(product,dict) and product.get('id')==PRODUCT,'variant_parent_mismatch')
            rows=(product.get('variants') or {}).get('nodes')
            require(isinstance(rows,list),'variant_inventory_identity_missing')
            allowed={v['id'] for v in read_policy()['variant_identity']}
            learned=set()
            for row in rows:
                require(isinstance(row,dict) and row.get('id') in allowed,'variant_not_allowlisted')
                identity=(row.get('inventoryItem') or {}).get('id')
                require(isinstance(identity,str) and re.fullmatch(r'gid://shopify/InventoryItem/[1-9]\d*',identity),
                        'inventory_identity_missing')
                learned.add(identity)
            self._inventory_ids=getattr(self,'_inventory_ids',set())|learned
        return result
    def _read_copy_snapshot(self,product_id):
        require(product_id==PRODUCT,'product_not_allowlisted')
        before=self.gql(EXTRA_QUERY,{'id':product_id})
        snapshot=super().read_snapshot(product_id)
        variants=self.connection(EXTRA_VARIANTS,product_id,'variants')
        after=self.gql(EXTRA_QUERY,{'id':product_id})
        require(before==after and isinstance(before.get('product'),dict),'metadata_changed_during_snapshot')
        meta=before['product']; product=snapshot['product']
        require(all(meta.get(k)==product.get(k) for k in ('id','title','handle','status','updatedAt')),
                'body_base_snapshot_mismatch')
        require(all(before.get('shop',{}).get(k)==v for k,v in snapshot['shop'].items()),'shop_snapshot_mismatch')
        require([v['id'] for v in variants]==[v['id'] for v in product['variants']],'variant_metadata_identity_mismatch')
        for current,extra in zip(product['variants'],variants):
            require(extra.get('inventoryItem',{}).get('id')==current['inventoryItem']['id'],'inventory_item_mismatch')
            current.update({k:v for k,v in extra.items() if k!='inventoryItem'})
            current['inventoryItem'].update(extra['inventoryItem'])
        snapshot['shop']=before['shop']; product.update(meta)
        validate_snapshot(snapshot)
        return snapshot
    def read_snapshot(self,product_id):
        first=self._read_copy_snapshot(product_id); last=self._read_copy_snapshot(product_id)
        a,b=deepcopy(first),deepcopy(last); a.pop('observed_at');b.pop('observed_at')
        require(a==b,'nested_snapshot_changed');return last
    def update_once(self,product_id,changes):
        require(product_id==PRODUCT and isinstance(changes,dict) and set(changes)=={'descriptionHtml'}
                and text_sha(changes['descriptionHtml'])==AFTER_SHA,'exact_description_mutation_required')
        result=self.gql(UPDATE,{'product':{'id':PRODUCT,'descriptionHtml':changes['descriptionHtml']}}).get('productUpdate')
        require(isinstance(result,dict) and result.get('userErrors')==[] and
                (result.get('product') or {}).get('id')==PRODUCT,'copy_response_unverified')
        return result
    def verify_public(self,plan):
        status,headers,raw=self.request(PUBLIC_URL,hosts={PUBLIC_HOST})
        require(status==200 and headers.get('content-type','').split(';')[0].lower()=='text/html',
                'public_http_pending')
        return verify_public_html(raw)


class _ActivePolicy:
    WORKFLOW=WORKFLOW
    PREFIX=PREFIX
    REQUIRE_ORIGINAL_CHECKPOINT=True
    def validate_plan_digest(self,plan,expected):return validate_plan_digest(plan,expected)
    def build_plan(self,scope,root,snapshot,*,now):return build_plan(scope,root,snapshot,now=now)
    def fetch_sources(self,pd_no,root,*,fetch):return fetch_sources(pd_no,root,fetch=fetch)
    def verify_readback(self,cp,snapshot):return verify_readback(cp,snapshot)
    def result(self,state,plan,**extra):return result(state,plan,**extra)
    def after_readback(self,plan,snapshot,client):
        try:return {'state':'verified','admin_readback_verified':True,**client.verify_public(plan)}
        except Exception as exc:return {'state':'public_verification_pending','admin_readback_verified':True,
                                       'public_readback_verified':False,'public_reason':str(exc) if isinstance(exc,Hold) else type(exc).__name__}


_ACTIVE_POLICY=_ActivePolicy()


def make_journal(plan,**context):return transaction.make_journal(_ACTIVE_POLICY,plan,**context)


class GitHubCheckpoint(transaction.GitHubCheckpoint):
    def __init__(self,token,artifact_id,artifact_digest,*,request=https_request):
        super().__init__(token,artifact_id,artifact_digest,policy=_ACTIVE_POLICY,request=request)


def result(state,plan,**extra):
    return {'state':state,'product_id':PRODUCT,'plan_digest':plan['plan_digest'],**extra,**dict.fromkeys(FLAGS,False)}


def reconcile(plan,client):return transaction.reconcile(_ACTIVE_POLICY,plan,client)


def execute(plan,*,root,expected_plan_digest,client=None,journal_path=None,checkpoint=None,
            apply=False,now=None,source_fetch=gallery.fetch_asset):
    return transaction.execute(_ACTIVE_POLICY,plan,root=root,expected_plan_digest=expected_plan_digest,
        client=client,journal_path=journal_path,checkpoint=checkpoint,apply=apply,now=now,
        source_fetch=source_fetch,atomic_write=atomic_json)


def cli():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    prepare=sub.add_parser('prepare')
    prepare.add_argument('--scope',required=True)
    prepare.add_argument('--snapshot')
    prepare.add_argument('--read-live',action='store_true')
    prepare.add_argument('--fetch-sources',action='store_true')
    prepare.add_argument('--output-dir',required=True)
    for name in ('execute',):
        p=sub.add_parser(name)
        p.add_argument('--plan',required=True)
        p.add_argument('--expected-plan-digest',required=True)
        if name=='execute':
            p.add_argument('--journal',required=True)
            p.add_argument('--apply',action='store_true')
            p.add_argument('--artifact-id');p.add_argument('--artifact-digest')
    restore=sub.add_parser('reconcile-artifact')
    for k in ('artifact-id','artifact-digest','repository','expected-plan-digest','expected-shop','expected-product'):
        restore.add_argument('--'+k,required=True)
    for p in (prepare,sub.choices['execute']):
        p.add_argument('--evidence-root',required=True)
        for arg,env in [('repository','GITHUB_REPOSITORY'),('run-id','GITHUB_RUN_ID'),
                        ('run-attempt','GITHUB_RUN_ATTEMPT'),('code-sha','GITHUB_SHA')]:
            p.add_argument('--'+arg,default=os.environ.get(env))
    args=parser.parse_args()
    try:
        if args.command=='reconcile-artifact':
            require(args.expected_shop == CANONICAL_SHOP and args.expected_product == PRODUCT, 'restore_target_not_allowlisted')
            backend=GitHubCheckpoint(os.environ.get('GITHUB_TOKEN'),args.artifact_id,args.artifact_digest)
            plan,_=backend.restore(args.repository,expected_plan_digest=args.expected_plan_digest,
                expected_shop=args.expected_shop,expected_product=args.expected_product)
            output=reconcile(plan,ShopifyClient.from_environment(plan['scope']['transport_shop']))
        elif args.command=='prepare':
            scope=read_json(args.scope)
            validate_scope(scope, {'product': {'status': 'ACTIVE'}}, utcnow())
            require(bool(args.read_live) != bool(args.snapshot),'choose_snapshot_or_read_live')
            if args.fetch_sources: fetch_sources(scope['pd_no'],args.evidence_root)
            snapshot=(ShopifyClient.from_environment(scope.get('transport_shop')).read_snapshot(scope['product_id'])
                      if args.read_live else read_json(args.snapshot))
            plan=build_plan(scope,args.evidence_root,snapshot)
            journal=make_journal(plan,repository=args.repository,run_id=args.run_id,run_attempt=args.run_attempt,
                                 code_sha=args.code_sha,workflow_path=WORKFLOW)
            directory=Path(args.output_dir)
            require(not (directory/'plan.json').exists() and not (directory/'journal.json').exists(),'checkpoint_files_exist')
            atomic_json(directory/'plan.json',plan);atomic_json(directory/'journal.json',journal)
            output=result('prepared',plan,writes=0,artifact_name=journal['artifact_name'])
        else:
            plan=read_json(args.plan);validate_plan_digest(plan,args.expected_plan_digest)
            if not args.apply:
                output=execute(plan,root=args.evidence_root,expected_plan_digest=args.expected_plan_digest)
            else:
                journal=read_json(args.journal)
                require(all(str(getattr(args,k))==str(journal.get(k)) for k in
                    ('repository','run_id','run_attempt','code_sha')), 'execution_context_mismatch')
                require(os.environ.get('GITHUB_WORKFLOW_REF') ==
                        args.repository+'/'+WORKFLOW+'@refs/heads/main','execution_workflow_ref_invalid')
                client=ShopifyClient.from_environment(plan['scope']['transport_shop'])
                backend=GitHubCheckpoint(os.environ.get('GITHUB_TOKEN'),args.artifact_id,args.artifact_digest)
                output=execute(plan,root=args.evidence_root,expected_plan_digest=args.expected_plan_digest,
                    client=client,journal_path=args.journal,checkpoint=backend,apply=True)
        print(json.dumps(output,ensure_ascii=False))
        return 0 if output['state'] in {'prepared','dry_run','no_op','verified'} else 2
    except (Hold,ValueError,TypeError,KeyError,OSError) as exc:
        print(json.dumps({'state':'hold','reason':str(exc) if isinstance(exc,Hold) else type(exc).__name__,
            'output_io_state':'possibly_replaced' if isinstance(exc,OSError) else 'not_claimed',
            'publication_allowed':False,'upload_allowed':False}))
        return 2


if __name__=='__main__':
    raise SystemExit(cli())
