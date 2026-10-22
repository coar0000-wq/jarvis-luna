"""Offline exact-product correction, shared transaction and workflow regressions."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch
import zipfile

import yaml
import dr_cpu_active_copy as exe
import test_apply_reviewed_product_gallery as fixtures


class Client:
    def __init__(self,snapshot):
        self.live=deepcopy(snapshot);self.writes=0;self.reads=0;self.on_read={}
        self.error=None;self.alter_after=None;self.public_error=None;self.public_reads=0
    def read_snapshot(self,pid):
        self.reads+=1
        if self.reads in self.on_read:self.on_read[self.reads](self.live)
        return deepcopy(self.live)
    def update_once(self,pid,changes):
        self.writes+=1;self.live['product'].update(changes)
        if self.alter_after:self.alter_after(self.live)
        if self.error:raise self.error
    def verify_public(self,plan):
        self.public_reads+=1
        if self.public_error:raise self.public_error
        return {'public_readback_verified':True,'public_html_sha256':'e'*64}


def public_html(body,*,identity=True,canonical=exe.PUBLIC_URL):
    payload=json.dumps({'product':{'id':9590780723457 if identity else 1,'handle':exe.HANDLE}})
    from html import escape
    return ('<html><head><link rel="canonical" href="'+canonical+'"></head><body>'
            '<main id="MainContent" data-template="product">'
            '<product-component class="product-information__grid" data-product-grid-content view-event-payload="'+escape(payload,quote=True)+'">'
            '<rte-formatter class="'+exe.DESCRIPTION_CLASS+'">'+body+'</rte-formatter></product-component></main></body></html>').encode()


class ActiveCopyTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ExecutorTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root,self.now=self.fixture.root,self.fixture.now
        self.rule=exe.read_policy();self.snapshot=deepcopy(self.fixture.snapshot)
        self.snapshot['shop']={'id':exe.SHOP_ID,'myshopifyDomain':exe.CANONICAL_SHOP,'currencyCode':'USD'}
        p=self.snapshot['product'];p.update(id=exe.PRODUCT,title=exe.TITLE,handle=exe.HANDLE,status='ACTIVE',
            descriptionHtml=self.rule['before_html'],tags=['daiso-pd-'+exe.PD],vendor='Dr.CPU+',productType='Skincare',
            seo={'title':None,'description':'Existing SEO'},onlineStoreUrl=exe.PUBLIC_URL)
        template=deepcopy(p['variants'][0]);p['variants']=[]
        for i,identity in enumerate(self.rule['variant_identity']):
            v=deepcopy(template);v.update(identity,title=identity['selectedOptions'][0]['value'],barcode=None,taxable=True,
                                         price=['21.99','36.99'][i])
            v['inventoryItem'].update(id='gid://shopify/InventoryItem/'+str(i+1),requiresShipping=True,
                                     measurement={'weight':{'value':0,'unit':'KILOGRAMS'}})
            p['variants'].append(v)
        self.scope={'schema_version':1,'policy_id':exe.POLICY_ID,'policy_sha256':exe.POLICY_SHA,'shop_id':exe.SHOP_ID,
            'canonical_shop':exe.CANONICAL_SHOP,'transport_shop':'synthetic-transport.myshopify.com',
            'product_id':exe.PRODUCT,'pd_no':exe.PD,'expected_status':'ACTIVE','execution_ticket':'SYNTHETIC-ONLY',
            'authorized_at':self.now.isoformat(),'expires_at':(self.now+timedelta(hours=1)).isoformat(),
            'allowed_fields':['descriptionHtml'],'expected_implementation_digest':exe.implementation_digest()}
        self.path=self.root/'journal.json';self.client=Client(self.snapshot)
        self.context={'repository':'synthetic/repo','run_id':'1234','run_attempt':'1','code_sha':'a'*40,'workflow_path':exe.WORKFLOW}
        self.source_check=patch.object(exe,'verify_sources');self.source_check.start();self.addCleanup(self.source_check.stop)
        self.fetch_patch=patch.object(exe,'fetch_sources');self.fetch=self.fetch_patch.start();self.addCleanup(self.fetch_patch.stop)
        self.checkpoint=Mock();self.checkpoint.verify.return_value=True
    def plan(self):return exe.build_plan(self.scope,self.root,self.snapshot,now=self.now)
    def prepare(self):
        p=self.plan();journal=exe.make_journal(p,**self.context);exe.atomic_json(self.path,journal)
        if self.checkpoint is not None:self.checkpoint.restore.return_value=(deepcopy(p),deepcopy(journal))
        return p
    def run_apply(self,p=None):
        p=p or self.prepare()
        return exe.execute(p,root=self.root,expected_plan_digest=p['plan_digest'],client=self.client,
            journal_path=self.path,checkpoint=self.checkpoint,apply=True,now=self.now)
    def held(self):
        with self.assertRaises((exe.Hold,KeyError,TypeError,ValueError)):self.plan()
        self.assertEqual(self.client.writes,0)
    def test_real_fixture_exact_three_replacements(self):
        p=self.plan();body=p['copy_plan']['changes']['descriptionHtml']
        self.assertEqual(exe.text_sha(self.rule['before_html']),exe.BEFORE_SHA)
        self.assertEqual(exe.text_sha(body),exe.AFTER_SHA)
        self.assertEqual(set(p['copy_plan']['changes']),{'descriptionHtml'})
        changed=self.rule['before_html']
        for c in self.rule['replacements']:
            self.assertEqual(changed.count(c['old']),1);self.assertNotIn(c['new'],changed)
            changed=changed.replace(c['old'],c['new'],1)
        self.assertEqual(body,changed)
        self.assertEqual(body.split('<h3>Ingredients</h3>')[0],self.rule['before_html'].split('<h3>Ingredients</h3>')[0])
        self.assertIn('actual-label verification remains pending',body)
        self.assertIn('prices remain provisional',body)
        self.assertTrue(all(p[k] is False for k in exe.FLAGS))
    def test_hash_is_raw_utf8_not_json_hash(self):
        self.assertNotEqual(exe.text_sha(self.rule['before_html']),exe.sha(self.rule['before_html']))
    def test_policy_tamper_and_review_flags(self):
        for field,value in [('physical_label_verified',True),('product_id','gid://shopify/Product/9'),('before_html','different')]:
            modified=deepcopy(self.rule);modified[field]=value
            with patch.object(exe,'read_json',return_value=modified),self.assertRaises(exe.Hold):exe.read_policy()
    def test_wrong_identity_status_title_handle_or_public_url(self):
        for key,value in [('id','gid://shopify/Product/9'),('status','DRAFT'),('status','ARCHIVED'),
                          ('title','Custom title'),('handle','changed'),('onlineStoreUrl','https://example.test/')]:
            with self.subTest(key=key,value=value):
                original=deepcopy(self.snapshot);self.snapshot['product'][key]=value;self.held();self.snapshot=original
    def test_wrong_shop_and_missing_currency(self):
        for key,value in [('id','gid://shopify/Shop/9'),('myshopifyDomain','other.myshopify.com'),('currencyCode',None)]:
            original=deepcopy(self.snapshot);self.snapshot['shop'][key]=value;self.held();self.snapshot=original
    def test_wrong_and_duplicate_supplier_tags(self):
        for tags in [['daiso-pd-9'],['daiso-pd-1084687','daiso-pd-9'],['daiso-pd-1084687']*2]:
            self.snapshot['product']['tags']=tags;self.held()
    def test_variant_identity_pack_order_changed(self):
        for field,value in [('id','gid://shopify/ProductVariant/9'),('sku','wrong'),('selectedOptions',[{'name':'Pack','value':'Wrong'}])]:
            original=deepcopy(self.snapshot);self.snapshot['product']['variants'][0][field]=value;self.held();self.snapshot=original
        self.snapshot['product']['variants'].reverse();self.held()
    def test_missing_protected_top_fields(self):
        for key in ['descriptionHtml','seo','onlineStoreUrl','vendor','productType','title','options','media','variants','publications']:
            with self.subTest(key=key):
                original=deepcopy(self.snapshot);self.snapshot['product'].pop(key);self.held();self.snapshot=original
    def test_missing_variant_weight_and_shipping_fields(self):
        for key in ['title','barcode','taxable','inventoryPolicy','price','compareAtPrice']:
            original=deepcopy(self.snapshot);self.snapshot['product']['variants'][0].pop(key);self.held();self.snapshot=original
        for key in ['measurement','requiresShipping','tracked','inventoryLevels']:
            original=deepcopy(self.snapshot);self.snapshot['product']['variants'][0]['inventoryItem'].pop(key);self.held();self.snapshot=original
    def test_bad_weight_boolean_nonfinite_negative(self):
        for value in [True,float('nan'),float('inf'),-1,None]:
            self.snapshot['product']['variants'][0]['inventoryItem']['measurement']['weight']['value']=value;self.held()
    def test_stale_future_incomplete_snapshot(self):
        for delta in [-301,1]:
            self.snapshot['observed_at']=(self.now+timedelta(seconds=delta)).isoformat();self.held()
        self.snapshot['observed_at']=self.now.isoformat();self.snapshot['complete']=False;self.held()
    def test_missing_duplicate_partial_or_unrelated_body_changes(self):
        before=self.rule['before_html'];c=self.rule['replacements'][0]
        for body in ['',before+' ',before*2,before.replace(c['old'],c['new']),before+c['new'],before.replace(c['old'],'')]:
            self.snapshot['product']['descriptionHtml']=body;self.held()
    def test_after_body_zero_write_and_public_verified(self):
        self.snapshot['product']['descriptionHtml']=exe.target_html();self.client=Client(self.snapshot)
        p=self.prepare();self.assertEqual(p['copy_plan']['changes'],{})
        self.assertEqual(self.run_apply(p)['state'],'verified');self.assertEqual(self.client.writes,0)
        self.assertEqual(self.client.public_reads,1)
    def test_scope_exact_fields_expiry_authority_and_implementation(self):
        for change in [dict(expected_status='DRAFT'),dict(product_id='gid://shopify/Product/3'),dict(policy_id='other'),
                       dict(allowed_fields=['descriptionHtml','title']),dict(expected_implementation_digest='a'*64),
                       dict(expires_at=self.now.isoformat()),dict(authorized_at=(self.now+timedelta(seconds=1)).isoformat()),
                       dict(expires_at=(self.now+timedelta(hours=25)).isoformat()),dict(allow_active=True)]:
            old=deepcopy(self.scope);self.scope.update(change);self.held();self.scope=old
    def test_operation_id_independent_of_ticket_run_or_time(self):
        first=self.plan()['operation_id'];self.scope['execution_ticket']='NEW-SYNTHETIC-TICKET'
        self.assertEqual(first,self.plan()['operation_id'])
    def test_before_plan_protection_excludes_only_body_and_timestamps(self):
        p=exe.protected(self.snapshot);self.assertIn('title',p['product']);self.assertIn('seo',p['product'])
        self.assertNotIn('descriptionHtml',p['product']);self.assertNotIn('updatedAt',p['product']);self.assertNotIn('observed_at',p)
    def test_default_dry_run_no_reads_fetches_or_writes(self):
        p=self.plan();self.assertEqual(exe.execute(p,root=self.root,expected_plan_digest=p['plan_digest'])['state'],'dry_run')
        self.assertEqual((self.client.reads,self.client.writes),(0,0));self.fetch.assert_not_called()
    def test_only_once_and_repeat_is_readonly(self):
        p=self.prepare();self.assertEqual(self.run_apply(p)['state'],'verified');self.assertEqual(self.client.writes,1)
        self.assertEqual(self.run_apply(p)['state'],'verified');self.assertEqual(self.client.writes,1)
        self.assertEqual(exe.read_json(self.path)['state'],'verified')
    def test_timeout_after_write_and_readonly_recovery(self):
        p=self.prepare();self.client.error=TimeoutError('synthetic')
        self.assertEqual(self.run_apply(p)['state'],'write_unknown');self.assertEqual(self.client.writes,1)
        self.assertEqual(self.run_apply(p)['state'],'verified');self.assertEqual(self.client.writes,1)
    def test_request_failure_without_change_never_retries(self):
        def fail(*a):self.client.writes+=1;raise OSError('synthetic')
        self.client.update_once=fail;p=self.prepare()
        self.assertEqual(self.run_apply(p)['state'],'write_unknown')
        self.assertEqual(self.run_apply(p)['state'],'verification_pending');self.assertEqual(self.client.writes,1)
    def test_keyboard_interrupt_then_reconcile(self):
        p=self.prepare();self.client.error=KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.run_apply(p)
        self.assertEqual(exe.read_json(self.path)['state'],'write_unknown')
        self.run_apply(p);self.assertEqual(self.client.writes,1)
    def test_public_pending_then_only_public_and_admin_reads(self):
        p=self.prepare();self.client.public_error=exe.Hold('old cached HTML')
        self.assertEqual(self.run_apply(p)['state'],'public_verification_pending');self.assertEqual(self.client.writes,1)
        self.client.public_error=None;self.assertEqual(self.run_apply(p)['state'],'verified');self.assertEqual(self.client.writes,1)
    def test_missing_or_prior_checkpoint_no_write(self):
        self.checkpoint=None
        with self.assertRaises(exe.Hold):self.run_apply()
        self.assertEqual(self.client.writes,0)
        self.checkpoint=Mock();self.checkpoint.verify.side_effect=exe.gallery.PriorCheckpoint({'id':1})
        self.assertEqual(self.run_apply()['state'],'prior_checkpoint_reconcile_required');self.assertEqual(self.client.writes,0)
    def test_after_body_new_ticket_cannot_bypass_prior_checkpoint(self):
        original=self.prepare();self.client.alter_after=lambda s:s['product']['variants'][0].update(price='99.00')
        self.assertEqual(self.run_apply(original)['state'],'verification_pending')
        self.snapshot=deepcopy(self.client.live);self.scope['execution_ticket']='NEW-SYNTHETIC-TICKET'
        later=self.prepare();self.assertEqual(later['copy_plan']['changes'],{})
        self.checkpoint.verify.side_effect=exe.gallery.PriorCheckpoint({'id':89})
        self.assertEqual(self.run_apply(later)['state'],'prior_checkpoint_reconcile_required')
        self.assertEqual(self.client.writes,1)
        self.assertEqual(exe.reconcile(original,self.client)['state'],'verification_pending')
    def test_active_noop_without_checkpoint_never_claims_success(self):
        self.snapshot['product']['descriptionHtml']=exe.target_html();self.client=Client(self.snapshot)
        self.checkpoint=None
        with self.assertRaises(exe.Hold):self.run_apply()
        self.assertEqual((self.client.writes,self.client.public_reads),(0,0))
    def test_resumed_journal_cannot_bypass_original_checkpoint(self):
        original=self.prepare();self.client.alter_after=lambda s:s['product']['variants'][0].update(price='99.00')
        self.assertEqual(self.run_apply(original)['state'],'verification_pending')
        self.snapshot=deepcopy(self.client.live);self.scope['execution_ticket']='NEW-SYNTHETIC-TICKET'
        later=self.prepare();journal=exe.read_json(self.path);journal.update(state='write_started',write_attempts=1)
        exe.atomic_json(self.path,journal)
        self.checkpoint.restore.side_effect=exe.Hold('restore_original_checkpoint_required')
        before_reads=self.client.reads
        with self.assertRaisesRegex(exe.Hold,'restore_original_checkpoint_required'):self.run_apply(later)
        self.checkpoint.restore.assert_called_once()
        self.assertEqual((self.client.writes,self.client.reads),(1,before_reads))
    def test_resumed_without_checkpoint_or_with_different_restored_plan_holds(self):
        p=self.prepare();self.run_apply(p);backend=self.checkpoint
        self.checkpoint=None
        with self.assertRaises(exe.Hold):self.run_apply(p)
        self.checkpoint=backend
        original=deepcopy(p);original['scope']['execution_ticket']='OTHER'
        self.checkpoint.restore.return_value=(original,exe.make_journal(p,**self.context))
        with self.assertRaises(exe.Hold):self.run_apply(p)
        self.assertEqual(self.client.writes,1)
    def test_restore_later_after_body_artifact_cannot_reset_protected_baseline(self):
        original=self.plan();original_journal=exe.make_journal(original,**self.context)
        self.snapshot['product']['descriptionHtml']=exe.target_html()
        self.snapshot['product']['variants'][0]['price']='99.00'
        self.scope['execution_ticket']='NEW-SYNTHETIC-TICKET';later=self.plan()
        later_context={**self.context,'run_id':'1235'}
        later_journal=exe.make_journal(later,**later_context)
        archives={};artifacts=[];runs={}
        for aid,plan,journal in [(89,original,original_journal),(90,later,later_journal)]:
            buffer=io.BytesIO()
            with zipfile.ZipFile(buffer,'w') as z:
                z.writestr('plan.json',exe.json_bytes(plan));z.writestr('journal.json',exe.json_bytes(journal))
            raw=buffer.getvalue();digest=hashlib.sha256(raw).hexdigest();archives[aid]=raw
            artifacts.append({'id':aid,'name':journal['artifact_name'],'expired':False,'digest':'sha256:'+digest,
                'workflow_run':{'id':int(journal['run_id']),'head_sha':journal['code_sha']},
                'created_at':self.now.isoformat(),'expires_at':(self.now+timedelta(days=30)).isoformat()})
            runs[journal['run_id']]={'id':int(journal['run_id']),'run_attempt':1,'head_sha':journal['code_sha'],
                                    'path':exe.WORKFLOW,'event':'workflow_dispatch','status':'in_progress'}
        def request(url,**kwargs):
            if '/actions/artifacts?' in url:data={'total_count':2,'artifacts':artifacts}
            elif '/actions/runs/' in url:data=runs[url.rsplit('/',1)[1]]
            else:
                aid=int(url.split('/artifacts/',1)[1].split('/')[0])
                if url.endswith('/zip'):return 200,{},archives[aid]
                data=next(a for a in artifacts if a['id']==aid)
            return 200,{},exe.json_bytes(data)
        def restore(aid,plan):
            backend=exe.GitHubCheckpoint('SYNTHETIC TOKEN',str(aid),hashlib.sha256(archives[aid]).hexdigest(),request=request)
            return backend.restore(self.context['repository'],expected_plan_digest=plan['plan_digest'],
                expected_shop=exe.CANONICAL_SHOP,expected_product=exe.PRODUCT)
        with self.assertRaisesRegex(exe.Hold,'restore_original_checkpoint_required'):restore(90,later)
        restored,_=restore(89,original)
        self.assertEqual(exe.reconcile(restored,Client(self.snapshot))['state'],'verification_pending')
    def test_prewrite_journal_failure_no_request(self):
        p=self.prepare()
        with patch.object(exe,'atomic_json',side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):self.run_apply(p)
        self.assertEqual(self.client.writes,0)
    def test_postwrite_journal_failure_no_retry(self):
        p=self.prepare();real=exe.atomic_json;calls=[]
        def save(path,value):
            calls.append(1)
            if len(calls)>1:raise OSError('synthetic')
            return real(path,value)
        with patch.object(exe,'atomic_json',side_effect=save):r=self.run_apply(p)
        self.assertEqual(r['state'],'verified');self.assertFalse(r['journal_saved'])
        self.run_apply(p);self.assertEqual(self.client.writes,1)
    def test_protected_drift_before_or_last_read_no_request(self):
        for number in [1,2]:
            self.client=Client(self.snapshot);self.client.on_read[number]=lambda s:s['product']['variants'][0].update(price='99.00')
            with self.assertRaises(exe.Hold):self.run_apply()
            self.assertEqual(self.client.writes,0)
    def test_every_added_protected_field_drift_after_request(self):
        changes=[lambda p:p.update(title='Other'),lambda p:p.update(status='DRAFT'),lambda p:p.update(handle='Other'),
                 lambda p:p.update(seo={'title':'Other','description':None}),lambda p:p['variants'][0].update(price='99.00'),
                 lambda p:p['variants'][0]['inventoryItem']['measurement']['weight'].update(value=9),
                 lambda p:p['media'][0].update(alt='Other'),lambda p:p['media'][0]['fingerprint'].update(sha256='e'*64),
                 lambda p:p['publications'][0].update(isPublished=False),lambda p:p.update(totalInventory=99)]
        for change in changes:
            self.client=Client(self.snapshot);self.client.alter_after=lambda s,c=change:c(s['product'])
            self.assertEqual(self.run_apply()['state'],'verification_pending');self.assertEqual(self.client.writes,1)
    def test_forged_plan_rejected_even_with_recomputed_outer_hash(self):
        p=self.plan();p['copy_plan']['changes']['title']='Not allowed';p['plan_digest']=exe.compute_plan_digest(p)
        with self.assertRaises(exe.Hold):exe.validate_plan_digest(p,p['plan_digest'])
        p=self.plan();p['safety_approved']=True;p['plan_digest']=exe.compute_plan_digest(p)
        with self.assertRaises(exe.Hold):exe.validate_plan_digest(p,p['plan_digest'])
    def test_implementation_or_policy_drift_rejected(self):
        p=self.plan()
        with patch.object(exe,'implementation_digest',return_value='f'*64),self.assertRaises(exe.Hold):exe.validate_plan_digest(p,p['plan_digest'])
    def test_source_fetch_hash_mismatch_and_no_overwrite(self):
        self.fetch_patch.stop();src=self.root/'source.png';src.write_bytes(b'old')
        rule={'sources':[{'source_url':'https://cdn.daisomall.co.kr/test.png','local_file':'source.png','sha256':hashlib.sha256(b'synthetic').hexdigest()}]}
        with patch.object(exe,'read_policy',return_value=rule):
            with self.assertRaises(exe.Hold):exe.fetch_sources(exe.PD,self.root,fetch=lambda *a:b'bad')
            self.assertEqual(src.read_bytes(),b'old')
            exe.fetch_sources(exe.PD,self.root,fetch=lambda *a:b'synthetic');self.assertEqual(src.read_bytes(),b'synthetic')
    def test_source_missing_tampered_or_path_escape(self):
        self.source_check.stop()
        with self.assertRaises(exe.Hold):exe.verify_sources(self.root)
        for name in ['../outside.png','source.png']:
            rule={'sources':[{'local_file':name,'sha256':'0'*64}]}
            with patch.object(exe,'read_policy',return_value=rule),self.assertRaises(exe.Hold):exe.verify_sources(self.root)
    def test_mutation_exact_wire_payload_and_forbidden_fields(self):
        sent=[]
        def request(url,**kwargs):
            sent.append(json.loads(kwargs['body']));return 200,{},exe.json_bytes({'data':{'productUpdate':{'product':{'id':exe.PRODUCT},'userErrors':[]}}})
        c=exe.ShopifyClient('synthetic.myshopify.com','SYNTHETIC TOKEN',request=request)
        c.update_once(exe.PRODUCT,{'descriptionHtml':exe.target_html()})
        self.assertEqual(sent[0]['variables'],{'product':{'id':exe.PRODUCT,'descriptionHtml':exe.target_html()}})
        for field in ['title','status','price','variants','media','tags','seo','publications','unknown']:
            with self.assertRaises(exe.Hold):c.update_once(exe.PRODUCT,{'descriptionHtml':exe.target_html(),field:'bad'})
        for pid,body in [('gid://shopify/Product/9',exe.target_html()),(exe.PRODUCT,'bad')]:
            with self.assertRaises(exe.Hold):c.update_once(pid,{'descriptionHtml':body})
        self.assertEqual(len(sent),1)
    def test_transport_timeout_no_automatic_retry(self):
        request=Mock(side_effect=TimeoutError('synthetic'));c=exe.ShopifyClient('synthetic.myshopify.com','SYNTHETIC TOKEN',request=request)
        with self.assertRaises(TimeoutError):c.update_once(exe.PRODUCT,{'descriptionHtml':exe.target_html()})
        self.assertEqual(request.call_count,1)
    def test_transport_rejects_inherited_append_and_raw_mutation(self):
        request=Mock();c=exe.ShopifyClient('synthetic.myshopify.com','SYNTHETIC TOKEN',request=request)
        with self.assertRaises(exe.Hold):c.append_once(exe.PRODUCT,[{'asset_url':'https://example.test/a.png','alt_text':'new'}])
        with self.assertRaises(exe.Hold):c.gql('mutation { productDelete { deletedProductId } }',{})
        with self.assertRaises(exe.Hold):c.gql(exe.UPDATE,{'product':{'id':exe.PRODUCT,'status':'DRAFT'}})
        with self.assertRaises(exe.Hold):c.gql(exe.gallery.BASE_QUERY,{'id':'gid://shopify/Product/42'})
        with self.assertRaises(exe.Hold):c.gql(exe.gallery.INVENTORY_QUERY,{'id':'gid://shopify/InventoryItem/42','after':None})
        self.assertEqual(request.call_count,0)
    def test_transport_uncertainty_and_success_both_forbid_second_send(self):
        for error in [TimeoutError('synthetic'),None]:
            request=Mock(side_effect=error,return_value=(200,{},exe.json_bytes({'data':{'productUpdate':{'product':{'id':exe.PRODUCT},'userErrors':[]}}})))
            c=exe.ShopifyClient('synthetic.myshopify.com','SYNTHETIC TOKEN',request=request)
            if error:
                with self.assertRaises(TimeoutError):c.update_once(exe.PRODUCT,{'descriptionHtml':exe.target_html()})
            else:c.update_once(exe.PRODUCT,{'descriptionHtml':exe.target_html()})
            with self.assertRaises(exe.Hold):c.gql(exe.UPDATE,{'product':{'id':exe.PRODUCT,'descriptionHtml':exe.target_html()}})
            self.assertEqual(request.call_count,1)
    def test_transport_inventory_reads_require_product_bound_variants(self):
        nodes=[{'id':v['id'],'inventoryItem':{'id':'gid://shopify/InventoryItem/'+str(i+1)}} for i,v in enumerate(self.rule['variant_identity'])]
        request=Mock(return_value=(200,{},exe.json_bytes({'data':{'product':{'id':exe.PRODUCT,'variants':{'nodes':nodes}}}})))
        c=exe.ShopifyClient('synthetic.myshopify.com','SYNTHETIC TOKEN',request=request)
        c.gql(exe.gallery.VARIANTS_QUERY,{'id':exe.PRODUCT,'after':None})
        c.gql(exe.gallery.INVENTORY_QUERY,{'id':'gid://shopify/InventoryItem/1','after':None})
        with self.assertRaises(exe.Hold):c.gql(exe.gallery.INVENTORY_QUERY,{'id':'gid://shopify/InventoryItem/99','after':None})
        self.assertEqual(request.call_count,2)
    def test_two_complete_reads_detect_nested_changes_without_updatedat(self):
        c=exe.ShopifyClient('synthetic.myshopify.com','SYNTHETIC TOKEN');other=deepcopy(self.snapshot)
        other['product']['publications'][0]['isPublished']=False
        c._read_copy_snapshot=Mock(side_effect=[deepcopy(self.snapshot),other])
        with self.assertRaises(exe.Hold):c.read_snapshot(exe.PRODUCT)
    def test_reader_merges_additional_protection(self):
        c=exe.ShopifyClient('synthetic.myshopify.com','SYNTHETIC TOKEN')
        p=self.snapshot['product'];meta={k:p[k] for k in ['id','title','descriptionHtml','updatedAt','vendor','productType','handle','status','onlineStoreUrl','seo']}
        c.gql=Mock(return_value={'shop':deepcopy(self.snapshot['shop']),'product':deepcopy(meta)})
        extras=[{k:deepcopy(v[k]) for k in ['id','title','barcode','taxable','inventoryItem']} for v in p['variants']]
        c.connection=Mock(return_value=extras)
        with patch.object(exe.gallery.ShopifyClient,'read_snapshot',return_value=deepcopy(self.snapshot)):
            self.assertEqual(c.read_snapshot(exe.PRODUCT),self.snapshot)
    def test_public_exact_body_and_identity(self):
        r=exe.verify_public_html(public_html(exe.target_html()));self.assertTrue(r['public_readback_verified'])
        for raw in [public_html(self.rule['before_html']),public_html(exe.target_html(),identity=False),
                    public_html(exe.target_html(),canonical='https://wrong.test/')]:
            with self.assertRaises(exe.Hold):exe.verify_public_html(raw)
    def test_public_scripts_hidden_and_recommendation_text_do_not_pass(self):
        target=exe.target_html()
        for body in ['<script>'+target+'</script>','<div hidden>'+target+'</div>','<div style="display:none">'+target+'</div>']:
            with self.assertRaises(exe.Hold):exe.verify_public_html(public_html(body))
        raw=public_html('Old body').replace(b'</body>',('<rte-formatter>'+target+'</rte-formatter></body>').encode())
        with self.assertRaises(exe.Hold):exe.verify_public_html(raw)
    def test_public_only_designated_main_description_passes(self):
        target=exe.target_html();good=public_html(target)
        bad=[good.replace(b'data-product-grid-content',b'data-search-card'),
             good.replace(b'id="MainContent"',b'id="PredictiveSearch"'),
             good.replace(exe.DESCRIPTION_CLASS.encode(),b'resource-card__description'),
             public_html('<dialog>'+target+'</dialog>'),
             public_html('<details>'+target+'</details>'),public_html('<noscript>'+target+'</noscript>')]
        # Real theme has a same-product predictive-search card; its text cannot certify the main body.
        search=good.decode().split('<main',1)[1].split('</main>',1)[0]
        search=('<div class="resource-card__wrapper"><main'+search+'</main></div>').replace('id="MainContent"','id="Search"')
        search=search.replace('data-product-grid-content','data-search-card')
        bad.append(public_html('<p>Description is missing</p>').replace(b'</body>',(search+'</body>').encode()))
        for raw in bad:
            with self.assertRaises(exe.Hold):exe.verify_public_html(raw)
    def test_unbound_reconcile_cli_is_not_exposed(self):
        result=subprocess.run(['python','-B',str(exe.ROOT/'scripts/dr_cpu_active_copy.py'),'reconcile'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('invalid choice',result.stderr)
    def test_public_request_never_contains_admin_credentials(self):
        request=Mock(return_value=(200,{'content-type':'text/html'},public_html(exe.target_html())))
        c=exe.ShopifyClient('synthetic.myshopify.com','SYNTHETIC TOKEN',request=request)
        c.verify_public(self.plan());request.assert_called_once_with(exe.PUBLIC_URL,hosts={exe.PUBLIC_HOST})
    def test_real_active_checkpoint_and_draft_restore_rejection(self):
        import apply_reviewed_draft_copy as draft
        plan=self.prepare();journal=exe.read_json(self.path);buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:
            z.writestr('plan.json',exe.json_bytes(plan));z.writestr('journal.json',exe.json_bytes(journal))
        raw=buffer.getvalue();digest=hashlib.sha256(raw).hexdigest()
        artifact={'id':90,'name':journal['artifact_name'],'expired':False,'digest':'sha256:'+digest,
            'workflow_run':{'id':1234,'head_sha':self.context['code_sha']},
            'created_at':self.now.isoformat(),'expires_at':(self.now+timedelta(days=30)).isoformat()}
        run={'id':1234,'run_attempt':1,'head_sha':self.context['code_sha'],'path':exe.WORKFLOW,
             'event':'workflow_dispatch','status':'in_progress'}
        def request(url,**kwargs):
            if url.endswith('/zip'):return 200,{},raw
            data=({'total_count':1,'artifacts':[artifact]} if '/actions/artifacts?' in url
                  else run if '/actions/runs/' in url else artifact)
            return 200,{},exe.json_bytes(data)
        backend=exe.GitHubCheckpoint('SYNTHETIC TOKEN','90',digest,request=request)
        self.assertTrue(backend.verify(plan,journal))
        restored,_=backend.restore(self.context['repository'],expected_plan_digest=plan['plan_digest'],
            expected_shop=exe.CANONICAL_SHOP,expected_product=exe.PRODUCT)
        self.assertEqual(restored,plan)
        wrong=draft.GitHubCheckpoint('SYNTHETIC TOKEN','90',digest,request=request)
        with self.assertRaises(exe.Hold):wrong.restore(self.context['repository'],
            expected_plan_digest=plan['plan_digest'],expected_shop=exe.CANONICAL_SHOP,expected_product=exe.PRODUCT)

    def test_draft_entrypoints_still_reject_active(self):
        import plan_draft_product_copy as draft
        import apply_reviewed_draft_copy as runner
        with self.assertRaises(exe.Hold):draft.build_plan(self.snapshot,exe.PD,self.root,now=self.now)
        with self.assertRaises(exe.Hold):runner.validate_scope(self.scope,self.snapshot,self.now)


class ActiveWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=exe.ROOT/exe.WORKFLOW;cls.text=cls.path.read_text();cls.doc=yaml.safe_load(cls.text);cls.steps=cls.doc['jobs']['copy']['steps']
    def step(self,name):return next(s for s in self.steps if s.get('name')==name)
    def test_manual_main_default_false_shared_serialization(self):
        trigger=self.doc.get('on',self.doc.get(True));self.assertEqual(set(trigger),{'workflow_dispatch'})
        self.assertIs(trigger['workflow_dispatch']['inputs']['apply_copy']['default'],False)
        self.assertEqual(self.doc['jobs']['copy']['if'],"github.ref == 'refs/heads/main'")
        self.assertEqual(self.doc['concurrency'],{'group':'daiso-daily-beauty-shopify','cancel-in-progress':False})
        self.assertEqual(self.doc['permissions'],{'contents':'read','actions':'read'})
    def test_checkpoint_order_retention_and_no_overwrite(self):
        names=[s.get('name') for s in self.steps]
        sequence=['Check requested plan digest before checkpoint','Persist immutable checkpoint before write','Apply exact copy once']
        self.assertEqual([names.index(x) for x in sequence],sorted(names.index(x) for x in sequence))
        cp=self.step(sequence[1])['with'];self.assertIs(cp['overwrite'],False);self.assertEqual(cp['retention-days'],30)
        self.assertEqual(cp['path'].split(),['out/drcpu-copy/plan.json','out/drcpu-copy/journal.json'])
        self.assertEqual(self.step('Preserve results including failures (no supplier image binaries)')['if'],'always()')
    def test_fixed_policy_no_free_product_html_or_field_input(self):
        inputs=self.doc.get('on',self.doc.get(True))['workflow_dispatch']['inputs']
        self.assertEqual(set(inputs),{'review_ticket','apply_copy','expected_plan_digest','reconcile_artifact_id','reconcile_artifact_digest'})
        bounded=self.step('Validate bounded inputs')['run'];self.assertIn('import dr_cpu_active_copy as copy',bounded)
        self.assertIn('copy.validate_scope',bounded);self.assertNotIn('copy.ALLOWED',bounded)
        self.assertIn('reconciliation is read-only',bounded)
    def test_pins_shell_syntax_no_interpolation(self):
        for s in self.steps:
            if 'uses' in s:self.assertRegex(s['uses'],r'^[\w./-]+@[0-9a-f]{40}$')
            if 'run' in s:
                self.assertNotIn('${{',s['run'])
                r=subprocess.run(['bash','-n'],input=s['run'],text=True,capture_output=True);self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('--require-hashes --only-binary=:all:',self.step('Install pinned verification dependencies')['run'])
    def test_recovery_and_prepare_no_mutation(self):
        recovery=self.step('Restore original checkpoint and reconcile without writing')['run']
        self.assertIn('reconcile-artifact',recovery);self.assertNotIn('--apply',recovery)
        prepare=self.step('Prepare consistent live read-only plan')['run'];self.assertNotIn('--apply',prepare)
        self.assertIn('dr_cpu_active_copy.py prepare',prepare)
        for step in self.steps:
            if 'upload-artifact@' in step.get('uses',''):self.assertNotIn('drcpu-copy-evidence',step['with']['path'])
    def test_network_blocked_and_registered_preflight(self):
        offline=self.step('Offline regression tests')['run']
        self.assertIn('socket.create_connection = blocked',offline);self.assertIn('test_dr_cpu_active_copy',offline)
        self.assertIn('test_apply_reviewed_draft_copy',offline)
        self.assertIn('python -B scripts/test_dr_cpu_active_copy.py',(exe.ROOT/'.github/workflows/preflight.yml').read_text())
    def test_invalid_inputs_rejected_without_remote(self):
        script=self.step('Validate bounded inputs')['run']
        for changes in [{'REVIEW_TICKET':'../evil'},{'APPLY_COPY':'true','EXPECTED_DIGEST':''},
                        {'RESTORE_ID':'1','RESTORE_DIGEST':''},{'APPLY_COPY':'true','RESTORE_ID':'1','RESTORE_DIGEST':'a'*64}]:
            env=dict(os.environ,REVIEW_TICKET='missing-synthetic-ticket',APPLY_COPY='false',EXPECTED_DIGEST='',RESTORE_ID='',RESTORE_DIGEST='');env.update(changes)
            r=subprocess.run(['bash','-c',script],cwd=exe.ROOT,env=env,capture_output=True,text=True)
            self.assertNotEqual(r.returncode,0)


if __name__=='__main__':unittest.main()
