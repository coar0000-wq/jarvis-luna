#!/usr/bin/env python3
"""Exact existing-DRAFT text correction; default prepare/dry-run, no import I/O.

Only id/title/descriptionHtml may reach the sole mutation. No retry after an
attempt. Immutable Actions checkpoint is required before writes. Source review
is not image rights, actual-stock label, INCI, legal or safety approval.
"""
from copy import deepcopy
from datetime import timedelta
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

import apply_reviewed_product_gallery as gallery
import plan_draft_product_copy as copy
import reviewed_copy_transaction as transaction
from apply_reviewed_product_gallery import (Hold, PriorCheckpoint, require, utcnow,
    stamp, read_json, json_bytes, strict_json, atomic_json, journal_lock,
    validate_snapshot, https_request, SHA1, SHA256, SHOP, REPOSITORY, MAX_PAGES)

WORKFLOW = '.github/workflows/shopify-reviewed-draft-copy.yml'
PREFIX = 'draft-copy-checkpoint-'
BODY_QUERY = '''query CopyBody($id:ID!){product(id:$id){id title descriptionHtml updatedAt vendor productType}}'''
COPY_MUTATION = '''mutation UpdateReviewedDraftCopy($product:ProductUpdateInput!){
 productUpdate(product:$product){product{id} userErrors{field message}}}'''
# Schema fields checked via official schema tool 2026-10-22. Code validator
# returned "validation skipped"; this is NOT a successful static API validation.


class ShopifyClient(gallery.ShopifyClient):
    def read_snapshot(self, product_id):
        require(product_id in copy.ALLOWED.values(), 'product_not_allowlisted')
        before = self.gql(BODY_QUERY, {'id': product_id}).get('product')
        snapshot = super().read_snapshot(product_id)
        after = self.gql(BODY_QUERY, {'id': product_id}).get('product')
        require(isinstance(before, dict) and before == after and before.get('id') == product_id,
                'body_changed_during_snapshot')
        require(all(before.get(k) == snapshot['product'].get(k) for k in ('id','title','updatedAt')),
                'body_base_snapshot_mismatch')
        require(all(isinstance(before.get(k), str) for k in ('descriptionHtml','vendor','productType')),
                'body_or_metadata_missing')
        snapshot['product'].update(before)
        return snapshot

    def update_once(self, product_id, changes):
        require(product_id in copy.ALLOWED.values() and changes and
                set(changes) <= {'title','descriptionHtml'}, 'copy_mutation_scope_invalid')
        response = self.gql(COPY_MUTATION, {'product': {'id': product_id, **changes}}).get('productUpdate')
        require(isinstance(response, dict) and response.get('userErrors') == [] and
                (response.get('product') or {}).get('id') == product_id, 'copy_response_unverified')
        return response


def operation_id(scope):
    return copy.sha({k: scope[k] for k in ('execution_ticket','shop_id','product_id')})[:32]


def validate_scope(scope, snapshot, now, *, expiry=True):
    require(isinstance(scope, dict) and scope.get('schema_version') == 1, 'scope_required')
    require(scope.get('pd_no') in copy.ALLOWED and scope.get('product_id') == copy.ALLOWED[scope['pd_no']],
            'scope_product_not_allowlisted')
    require(scope.get('shop_id') == 'gid://shopify/Shop/82748997889' == snapshot['shop']['id'], 'scope_shop_mismatch')
    require(isinstance(scope.get('canonical_shop'), str) and SHOP.fullmatch(scope['canonical_shop']) and
            scope['canonical_shop'] == snapshot['shop']['myshopifyDomain'], 'canonical_shop_mismatch')
    require(isinstance(scope.get('transport_shop'), str) and SHOP.fullmatch(scope['transport_shop']), 'transport_shop_required')
    require(scope.get('expected_status') == snapshot['product']['status'] == 'DRAFT' and
            snapshot['product']['id'] == scope['product_id'], 'draft_exact_product_required')
    require(isinstance(scope.get('execution_ticket'), str) and
            re.fullmatch(r'[A-Za-z0-9_-]{1,64}', scope['execution_ticket']), 'execution_ticket_invalid')
    start, end = stamp(scope.get('authorized_at')), stamp(scope.get('expires_at'))
    require(timedelta(0) < end-start <= timedelta(hours=24), 'scope_window_invalid')
    require(not expiry or start <= now <= end, 'scope_expired_or_future')
    require(scope.get('allowed_fields') == ['title','descriptionHtml'], 'scope_fields_invalid')


def implementation_digest():
    root = Path(__file__).resolve().parents[1]
    files = ['scripts/apply_reviewed_draft_copy.py','scripts/plan_draft_product_copy.py',
             'scripts/reviewed_copy_transaction.py',
             'scripts/apply_reviewed_product_gallery.py','scripts/plan_active_product_gallery.py',
             'scripts/gallery_review.py','data/manual/draft_copy/verified_fields.json',WORKFLOW]
    return copy.sha({f: hashlib.sha256((root/f).read_bytes()).hexdigest() for f in files})


def compute_plan_digest(plan):
    normalized = deepcopy(plan)
    normalized.pop('plan_digest', None)
    normalized['before'].pop('observed_at', None)
    normalized['copy_plan']['before'].pop('observed_at', None)
    normalized['copy_plan'].pop('plan_sha256', None)
    return copy.sha(normalized)


def validate_plan_digest(plan, expected):
    require(isinstance(expected, str) and SHA256.fullmatch(expected) and
            plan.get('plan_digest') == expected == compute_plan_digest(plan), 'plan_digest_mismatch')
    require(plan.get('kind') == 'reviewed_draft_copy' and
            plan.get('operation_id') == operation_id(plan['scope']), 'plan_kind_or_operation_invalid')
    require(all(plan.get(k) is False for k in (*copy.FLAGS,'upload_allowed','publication_allowed')),
            'approval_flags_invalid')
    require(plan['before'] == plan['copy_plan']['before'], 'snapshot_binding_mismatch')
    validate_snapshot(plan['before'], fresh=False)
    validate_scope(plan['scope'], plan['before'], utcnow(), expiry=False)
    require(plan['copy_plan']['product_id'] == plan['scope']['product_id'] and
            plan['copy_plan']['pd_no'] == plan['scope']['pd_no'], 'copy_identity_mismatch')
    require(set(plan['copy_plan']['changes']) <= {'title','descriptionHtml'}, 'copy_fields_invalid')
    unsigned = {k:v for k,v in plan['copy_plan'].items() if k != 'plan_sha256'}
    require(copy.sha(unsigned) == plan['copy_plan']['plan_sha256'], 'copy_plan_digest_mismatch')


def build_plan(scope, root, snapshot, *, now=None):
    now = now or utcnow()
    validate_snapshot(snapshot, now=now)
    validate_scope(scope, snapshot, now)
    require(all(isinstance(snapshot['product'].get(k),str) for k in ('vendor','productType')), 'metadata_protection_missing')
    cp = copy.build_plan(snapshot, scope['pd_no'], root, now=now)
    plan = {'schema_version':1,'kind':'reviewed_draft_copy','operation_id':operation_id(scope),
            'scope':deepcopy(scope),'before':deepcopy(snapshot),'copy_plan':cp,
            'implementation_digest':implementation_digest(),
            'upload_allowed':False,'publication_allowed':False,**dict.fromkeys(copy.FLAGS,False)}
    plan['plan_digest'] = compute_plan_digest(plan)
    return plan


def fetch_sources(pd_no, root, *, fetch=gallery.fetch_asset):
    require(pd_no in copy.ALLOWED, 'source_product_not_allowlisted')
    policy = read_json(copy.POLICY)
    rule = next(p for p in policy['products'] if p['pd_no'] == pd_no)
    root = Path(root).resolve()
    for source in rule['sources']:
        raw = fetch(source['source_url'], {'cdn.daisomall.co.kr'})
        require(hashlib.sha256(raw).hexdigest() == source['sha256'], 'live_source_hash_mismatch')
        path = root / source['local_file']
        require(path.resolve().is_relative_to(root) and not path.is_symlink(), 'source_path_unsafe')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


class _DraftPolicy:
    """Fixed DRAFT authority; call current module helpers for public test seams."""
    WORKFLOW = WORKFLOW
    PREFIX = PREFIX

    def validate_plan_digest(self, plan, expected):
        return validate_plan_digest(plan, expected)

    def build_plan(self, scope, root, snapshot, *, now):
        return build_plan(scope, root, snapshot, now=now)

    def fetch_sources(self, pd_no, root, *, fetch):
        return fetch_sources(pd_no, root, fetch=fetch)

    def verify_readback(self, copy_plan, snapshot):
        return copy.verify_readback(copy_plan, snapshot)

    def result(self, state, plan, **extra):
        return result(state, plan, **extra)


_DRAFT_POLICY = _DraftPolicy()


def make_journal(plan, *, repository, run_id, run_attempt, code_sha, workflow_path):
    return transaction.make_journal(_DRAFT_POLICY, plan, repository=repository,
        run_id=run_id, run_attempt=run_attempt, code_sha=code_sha, workflow_path=workflow_path)


class GitHubCheckpoint(transaction.GitHubCheckpoint):
    """DRAFT-only checkpoint backend; no caller-selectable policy or namespace."""
    def __init__(self, token, artifact_id, artifact_digest, *, request=https_request):
        super().__init__(token, artifact_id, artifact_digest, policy=_DRAFT_POLICY, request=request)


def result(state, plan, **extra):
    return {'state':state,'product_id':plan['scope']['product_id'],'plan_digest':plan['plan_digest'],
            'publication_allowed':False,'upload_allowed':False,**dict.fromkeys(copy.FLAGS,False),**extra}


def reconcile(plan, client):
    return transaction.reconcile(_DRAFT_POLICY, plan, client)


def save_after_attempt(path, journal):
    return transaction.save_after_attempt(path, journal, atomic_write=atomic_json)


def execute(plan, *, root, expected_plan_digest, client=None, journal_path=None,
            checkpoint=None, apply=False, now=None, source_fetch=gallery.fetch_asset):
    return transaction.execute(_DRAFT_POLICY, plan, root=root,
        expected_plan_digest=expected_plan_digest, client=client, journal_path=journal_path,
        checkpoint=checkpoint, apply=apply, now=now, source_fetch=source_fetch,
        atomic_write=atomic_json)


def cli():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    prepare=sub.add_parser('prepare')
    prepare.add_argument('--scope',required=True)
    prepare.add_argument('--snapshot')
    prepare.add_argument('--read-live',action='store_true')
    prepare.add_argument('--fetch-sources',action='store_true')
    prepare.add_argument('--output-dir',required=True)
    for name in ('execute','reconcile'):
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
            backend=GitHubCheckpoint(os.environ.get('GITHUB_TOKEN'),args.artifact_id,args.artifact_digest)
            plan,_=backend.restore(args.repository,expected_plan_digest=args.expected_plan_digest,
                expected_shop=args.expected_shop,expected_product=args.expected_product)
            output=reconcile(plan,ShopifyClient.from_environment(plan['scope']['transport_shop']))
        elif args.command=='prepare':
            scope=read_json(args.scope)
            require(scope.get('pd_no') in copy.ALLOWED and scope.get('product_id') == copy.ALLOWED[scope['pd_no']],
                    'scope_product_not_allowlisted')
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
            if args.command=='reconcile':
                output=reconcile(plan,ShopifyClient.from_environment(plan['scope']['transport_shop']))
            elif not args.apply:
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
