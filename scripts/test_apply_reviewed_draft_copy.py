"""All transports synthetic; no Shopify, GitHub or supplier network calls."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import zipfile

import apply_reviewed_draft_copy as exe
import test_plan_draft_product_copy as planner_tests


class Client:
    def __init__(self,snapshot):
        self.live=deepcopy(snapshot);self.writes=0;self.reads=0;self.error=None;self.on_read={};self.alter_after=None
    def read_snapshot(self,pid):
        self.reads+=1
        if self.reads in self.on_read:self.on_read[self.reads](self.live)
        return deepcopy(self.live)
    def update_once(self,pid,changes):
        self.writes+=1;self.live['product'].update(changes)
        if self.alter_after:self.alter_after(self.live)
        if self.error:raise self.error


class CopyExecutorTests(unittest.TestCase):
    def setUp(self):
        self.fixture=planner_tests.CopyPlanTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root,self.now,self.snapshot=self.fixture.root,self.fixture.now,self.fixture.snapshot
        self.snapshot['product'].update(vendor='Synthetic vendor',productType='Body Care')
        self.scope={'schema_version':1,'pd_no':self.fixture.pid,'product_id':self.snapshot['product']['id'],
            'shop_id':self.snapshot['shop']['id'],'canonical_shop':self.snapshot['shop']['myshopifyDomain'],
            'transport_shop':'synthetic-transport.myshopify.com','expected_status':'DRAFT',
            'execution_ticket':'SYNTHETIC-ONLY','authorized_at':self.now.isoformat(),
            'expires_at':(self.now+timedelta(hours=1)).isoformat(),'allowed_fields':['title','descriptionHtml']}
        self.context=dict(repository='synthetic/repo',run_id='1234',run_attempt='1',code_sha='a'*40,workflow_path=exe.WORKFLOW)
        self.path=self.root/'journal.json';self.client=Client(self.snapshot);self.checkpoint=Mock();self.checkpoint.verify.return_value=True
        self.fetch_patch=patch.object(exe,'fetch_sources');self.fetch=self.fetch_patch.start();self.addCleanup(self.fetch_patch.stop)
    def plan(self):return exe.build_plan(self.scope,self.root,self.snapshot,now=self.now)
    def prepare(self):
        plan=self.plan();exe.atomic_json(self.path,exe.make_journal(plan,**self.context));return plan
    def run_apply(self,plan=None):
        plan=plan or self.prepare()
        return exe.execute(plan,root=self.root,expected_plan_digest=plan['plan_digest'],client=self.client,
            journal_path=self.path,checkpoint=self.checkpoint,apply=True,now=self.now)
    def test_exact_once_and_idempotent_restart(self):
        p=self.prepare();self.assertEqual(self.run_apply(p)['state'],'verified');self.assertEqual(self.client.writes,1)
        self.assertEqual(self.run_apply(p)['state'],'verified');self.assertEqual(self.client.writes,1)
    def test_other_exact_draft_applies_independently(self):
        self.fixture.prepare('1073406');self.snapshot=self.fixture.snapshot
        self.scope.update(pd_no='1073406',product_id=self.snapshot['product']['id'])
        self.client=Client(self.snapshot)
        self.assertEqual(self.run_apply()['state'],'verified');self.assertEqual(self.client.writes,1)
        self.assertIn('THE LAB by BLANC DOUX',self.client.live['product']['title'])
    def test_fetch_checks_source_hash_before_local_replace(self):
        self.fetch_patch.stop()
        rule=self.fixture.rule;data={r['source_url']:(self.root/r['local_file']).read_bytes() for r in rule['sources']}
        def fetch(url,hosts):
            self.assertEqual(hosts,{'cdn.daisomall.co.kr'});return data[url]
        with patch.object(exe,'read_json',return_value=self.fixture.policy):
            exe.fetch_sources(self.fixture.pid,self.root,fetch=fetch)
            before=(self.root/rule['sources'][0]['local_file']).read_bytes()
            with self.assertRaises(exe.Hold):exe.fetch_sources(self.fixture.pid,self.root,fetch=lambda *a:b'changed')
            self.assertEqual((self.root/rule['sources'][0]['local_file']).read_bytes(),before)
    def test_default_dry_run_no_reads_fetches_writes(self):
        p=self.plan();self.assertEqual(exe.execute(p,root=self.root,expected_plan_digest=p['plan_digest'])['state'],'dry_run')
        self.assertEqual(self.client.writes,0);self.assertEqual(self.client.reads,0);self.fetch.assert_not_called()
    def test_noop_zero_writes(self):
        first=self.plan();self.snapshot['product'].update(first['copy_plan']['changes']);self.client=Client(self.snapshot)
        self.assertEqual(self.run_apply()['state'],'no_op');self.assertEqual(self.client.writes,0)
    def test_timeout_unknown_then_readonly_reconciliation(self):
        p=self.prepare();self.client.error=TimeoutError('synthetic')
        self.assertEqual(self.run_apply(p)['state'],'write_unknown');self.assertEqual(self.client.writes,1)
        self.assertEqual(self.run_apply(p)['state'],'verified');self.assertEqual(self.client.writes,1)
    def test_interruption_no_retry(self):
        p=self.prepare();self.client.error=KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.run_apply(p)
        self.assertEqual(exe.read_json(self.path)['state'],'write_unknown')
        self.run_apply(p);self.assertEqual(self.client.writes,1)
    def test_request_error_without_change_stays_pending(self):
        def fail(*a):self.client.writes+=1;raise OSError('synthetic')
        self.client.update_once=fail;p=self.prepare()
        self.assertEqual(self.run_apply(p)['state'],'write_unknown')
        self.assertEqual(self.run_apply(p)['state'],'verification_pending');self.assertEqual(self.client.writes,1)
    def test_missing_checkpoint_zero_writes(self):
        self.checkpoint=None
        with self.assertRaises(exe.Hold):self.run_apply()
        self.assertEqual(self.client.writes,0)
    def test_invalid_checkpoint_zero_writes(self):
        for answer in (False,None,'true'):
            self.checkpoint.verify.return_value=answer
            with self.assertRaises(exe.Hold):self.run_apply()
        self.assertEqual(self.client.writes,0)
    def test_prior_checkpoint_reconcile_only(self):
        self.checkpoint.verify.side_effect=exe.PriorCheckpoint({'id':1})
        self.assertEqual(self.run_apply()['state'],'prior_checkpoint_reconcile_required');self.assertEqual(self.client.writes,0)
    def test_prewrite_drift_zero_writes(self):
        p=self.prepare();self.client.live['product']['variants'][0]['price']='999.00'
        with self.assertRaises(exe.Hold):self.run_apply(p)
        self.assertEqual(self.client.writes,0)
    def test_last_moment_drift_zero_writes(self):
        self.client.on_read[2]=lambda s:s['product'].update(descriptionHtml='changed')
        with self.assertRaises(exe.Hold):self.run_apply()
        self.assertEqual(self.client.writes,0)
    def test_postwrite_protected_field_drift_pending(self):
        self.client.alter_after=lambda s:s['product'].update(handle='changed')
        self.assertEqual(self.run_apply()['state'],'verification_pending');self.assertEqual(self.client.writes,1)
    def test_prewrite_journal_io_failure_zero_writes(self):
        p=self.prepare()
        with patch.object(exe,'atomic_json',side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):self.run_apply(p)
        self.assertEqual(self.client.writes,0)
    def test_postwrite_journal_io_failure_readback_without_retry(self):
        p=self.prepare();real=exe.atomic_json;calls=[]
        def save(path,value):
            calls.append(1)
            if len(calls)>1:raise OSError('synthetic')
            real(path,value)
        with patch.object(exe,'atomic_json',side_effect=save):r=self.run_apply(p)
        self.assertEqual(r['state'],'verified');self.assertFalse(r['journal_saved']);self.assertEqual(self.client.writes,1)
        self.assertEqual(exe.read_json(self.path)['state'],'write_started');self.run_apply(p);self.assertEqual(self.client.writes,1)
    def test_prewrite_directory_fsync_failure_zero_writes(self):
        p=self.prepare()
        with patch.object(exe.gallery.os,'fsync',side_effect=[None,OSError('directory fsync')]):
            with self.assertRaises(OSError):self.run_apply(p)
        self.assertEqual(self.client.writes,0);self.assertEqual(exe.read_json(self.path)['state'],'write_started')
    def test_expiry_wrong_scope_active_no_metadata(self):
        for modify in (lambda s:s.update(expires_at=(self.now-timedelta(seconds=1)).isoformat()),
                       lambda s:s.update(shop_id='gid://shopify/Shop/9'),
                       lambda s:s.update(allowed_fields=['status']),lambda s:s.update(expected_status='ACTIVE')):
            old=deepcopy(self.scope);modify(self.scope)
            with self.assertRaises(exe.Hold):self.plan()
            self.scope=old
        self.snapshot['product'].pop('vendor')
        with self.assertRaises(exe.Hold):self.plan()
    def test_plan_code_policy_drift(self):
        p=self.prepare()
        with patch.object(exe,'implementation_digest',return_value='f'*64):
            with self.assertRaises(exe.Hold):self.run_apply(p)
        self.assertEqual(self.client.writes,0)
    def test_observation_clock_only_digest_stable(self):
        p=self.plan();self.snapshot['observed_at']=(self.now-timedelta(seconds=1)).isoformat()
        self.assertEqual(p['plan_digest'],self.plan()['plan_digest'])
    def test_unknown_journal_state_is_readonly(self):
        p=self.prepare();j=exe.read_json(self.path);j['state']='unknown';exe.atomic_json(self.path,j)
        self.assertEqual(self.run_apply(p)['state'],'verification_pending');self.assertEqual(self.client.writes,0)
    def test_tampered_journal_zero_writes(self):
        p=self.prepare();j=exe.read_json(self.path);j['changes']['status']='ACTIVE';exe.atomic_json(self.path,j)
        with self.assertRaises(exe.Hold):self.run_apply(p)
        self.assertEqual(self.client.writes,0)
    def test_source_failure_zero_writes(self):
        self.fetch.side_effect=exe.Hold('source hash mismatch')
        with self.assertRaises(exe.Hold):self.run_apply()
        self.assertEqual(self.client.writes,0)
    def test_reader_consistent_and_body_changed(self):
        c=exe.ShopifyClient('synthetic.myshopify.com','SYNTHETIC TOKEN')
        body={k:self.snapshot['product'][k] for k in ('id','title','descriptionHtml','updatedAt','vendor','productType')}
        with patch.object(exe.gallery.ShopifyClient,'read_snapshot',return_value=deepcopy(self.snapshot)):
            c.gql=Mock(return_value={'product':deepcopy(body)})
            self.assertEqual(c.read_snapshot(body['id'])['product']['descriptionHtml'],body['descriptionHtml'])
            bad=deepcopy(body);bad['descriptionHtml']='changed';c.gql=Mock(side_effect=[{'product':body},{'product':bad}])
            with self.assertRaises(exe.Hold):c.read_snapshot(body['id'])
    def test_mutation_transport_only_exact_fields_once(self):
        sent=[]
        def request(url,**kwargs):
            sent.append(json.loads(kwargs['body']))
            return 200,{},exe.json_bytes({'data':{'productUpdate':{'product':{'id':self.scope['product_id']},'userErrors':[]}}})
        c=exe.ShopifyClient('synthetic.myshopify.com','SYNTHETIC TOKEN',request=request)
        c.update_once(self.scope['product_id'],{'title':'exact'})
        self.assertEqual(sent[0]['variables'],{'product':{'id':self.scope['product_id'],'title':'exact'}})
        with self.assertRaises(exe.Hold):c.update_once(self.scope['product_id'],{'status':'ACTIVE'})
        self.assertEqual(len(sent),1)
    def test_transport_timeout_no_retry(self):
        request=Mock(side_effect=TimeoutError('synthetic'))
        c=exe.ShopifyClient('synthetic.myshopify.com','SYNTHETIC TOKEN',request=request)
        with self.assertRaises(TimeoutError):c.update_once(self.scope['product_id'],{'title':'exact'})
        self.assertEqual(request.call_count,1)

    def backend(self,*,artifact_change=None,run_change=None,list_change=None,entries=None):
        p=self.prepare();j=exe.read_json(self.path);buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:
            for k,v in (entries or {'plan.json':exe.json_bytes(p),'journal.json':exe.json_bytes(j)}).items():z.writestr(k,v)
        raw=buffer.getvalue();digest=hashlib.sha256(raw).hexdigest()
        a={'id':90,'name':j['artifact_name'],'expired':False,'digest':'sha256:'+digest,
           'workflow_run':{'id':1234,'head_sha':self.context['code_sha']},
           'created_at':self.now.isoformat(),'expires_at':(self.now+timedelta(days=30)).isoformat()}
        run={'id':1234,'run_attempt':1,'head_sha':self.context['code_sha'],'path':exe.WORKFLOW,
             'event':'workflow_dispatch','status':'in_progress'}
        if artifact_change:artifact_change(a)
        if run_change:run_change(run)
        listing={'total_count':1,'artifacts':[a]}
        if list_change:list_change(listing)
        def request(url,**kwargs):
            if url.endswith('/zip'):return 200,{},raw
            data=listing if '/actions/artifacts?' in url else (run if '/actions/runs/' in url else a)
            return 200,{},exe.json_bytes(data)
        return p,j,exe.GitHubCheckpoint('SYNTHETIC TOKEN','90',digest,request=request)
    def test_checkpoint_valid_and_restore_completed_run(self):
        p,j,b=self.backend();self.assertTrue(b.verify(p,j))
        p,j,b=self.backend(run_change=lambda r:r.update(status='completed'))
        restored,_=b.restore(self.context['repository'],expected_plan_digest=p['plan_digest'],
            expected_shop=self.scope['canonical_shop'],expected_product=self.scope['product_id'])
        self.assertEqual(restored,p)
        with self.assertRaises(exe.Hold):b.verify(p,j)
    def test_checkpoint_invalid_metadata(self):
        for change in (lambda a:a.update(expired=True),lambda a:a.update(name='wrong'),
                       lambda a:a.update(digest='sha256:'+'0'*64),lambda a:a.update(expires_at=self.now.isoformat())):
            p,j,b=self.backend(artifact_change=change)
            with self.assertRaises(exe.Hold):b.verify(p,j)
    def test_checkpoint_history_prior_or_incomplete(self):
        p,j,b=self.backend(list_change=lambda x:x.update(total_count=2,artifacts=x['artifacts']+[{'id':89,'name':exe.PREFIX+exe.operation_id(self.scope)+'-1000-1'}]))
        with self.assertRaises(exe.PriorCheckpoint):b.verify(p,j)
        p,j,b=self.backend(list_change=lambda x:x.update(artifacts=[]))
        with self.assertRaises(exe.Hold):b.verify(p,j)
    def test_checkpoint_bad_zip(self):
        p,j,b=self.backend(entries={'plan.json':b'{}','journal.json':b'{}','extra':b'bad'})
        with self.assertRaises(exe.Hold):b.verify(p,j)
    def test_restore_wrong_target_denied(self):
        p,j,b=self.backend()
        with self.assertRaises(exe.Hold):b.restore(self.context['repository'],expected_plan_digest=p['plan_digest'],
            expected_shop=self.scope['canonical_shop'],expected_product=exe.copy.ALLOWED['1073406'])
    def test_restore_readonly_after_unknown(self):
        p,j,b=self.backend();self.client.error=TimeoutError('synthetic')
        self.run_apply(p)
        restored,_=b.restore(self.context['repository'],expected_plan_digest=p['plan_digest'],
            expected_shop=self.scope['canonical_shop'],expected_product=self.scope['product_id'])
        self.assertEqual(exe.reconcile(restored,self.client)['state'],'verified');self.assertEqual(self.client.writes,1)


if __name__=='__main__':unittest.main()
