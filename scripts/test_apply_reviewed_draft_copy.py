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
    def prepare_blistex(self):
        self.fixture.prepare('1076498'); self.snapshot = self.fixture.snapshot
        self.scope.update(pd_no='1076498', product_id=self.snapshot['product']['id'],
                          allowed_fields=['descriptionHtml'])
        self.client = Client(self.snapshot)
    def test_blistex_one_body_write_and_idempotent_restart(self):
        self.prepare_blistex(); original = deepcopy(self.snapshot); plan = self.prepare()
        self.assertEqual(set(plan['copy_plan']['changes']), {'descriptionHtml'})
        self.assertEqual(self.run_apply(plan)['state'], 'verified')
        self.assertEqual(exe.copy.protected(self.client.live), exe.copy.protected(original))
        self.assertEqual(self.run_apply(plan)['state'], 'verified'); self.assertEqual(self.client.writes, 1)
    def test_blistex_scope_cannot_include_title_or_other_fields(self):
        self.prepare_blistex()
        for fields in (['title','descriptionHtml'], ['title'], ['status'], [], ['descriptionHtml','descriptionHtml']):
            self.scope['allowed_fields'] = fields
            with self.assertRaises(exe.Hold): self.plan()
        self.assertEqual(self.client.writes, 0)
    def test_blistex_transport_only_exact_after_body(self):
        self.prepare_blistex(); plan = self.plan(); sent = []
        def request(url, **kwargs):
            sent.append(exe.strict_json(kwargs['body']))
            return 200, {}, exe.json_bytes({'data':{'productUpdate':{
                'product':{'id':self.scope['product_id']},'userErrors':[]}}})
        client = exe.ShopifyClient('synthetic.myshopify.com','SYNTHETIC',request=request)
        for changes in ({'title':'Changed'}, {'descriptionHtml':'4.25 g'},
                        {**plan['copy_plan']['changes'], 'title':exe.copy.BODY_ONLY_TITLE},
                        {'status':'ACTIVE'}, {}):
            with self.assertRaises(exe.Hold): client.update_once(self.scope['product_id'], changes)
        self.assertEqual(sent, [])
        client.update_once(self.scope['product_id'], plan['copy_plan']['changes'])
        self.assertEqual(sent[0]['variables'], {'product':{'id':self.scope['product_id'], **plan['copy_plan']['changes']}})
        self.assertEqual(len(sent), 1)
    def test_blistex_rehashed_plan_cannot_broaden_changes(self):
        self.prepare_blistex(); original = self.plan()
        for changes in ({'title':'Changed'}, {'descriptionHtml':'Unknown new body'}, {}):
            plan = deepcopy(original); plan['copy_plan']['changes'] = changes
            cp = plan['copy_plan']; cp['plan_sha256'] = exe.copy.sha({k:v for k,v in cp.items() if k != 'plan_sha256'})
            plan['plan_digest'] = exe.compute_plan_digest(plan)
            with self.assertRaises(exe.Hold): exe.validate_plan_digest(plan, plan['plan_digest'])
        self.assertEqual(self.client.writes, 0)
    def test_blistex_missing_protection_or_source_hash_holds(self):
        self.prepare_blistex(); original = deepcopy(self.snapshot)
        for field in ('publications','media','variants','options','vendor','productType'):
            self.snapshot = deepcopy(original); self.snapshot['product'].pop(field)
            with self.assertRaises(exe.Hold): self.plan()
        self.snapshot = original
        (self.root/self.fixture.rule['sources'][0]['local_file']).write_bytes(b'changed')
        with self.assertRaises(exe.Hold): self.plan()
        self.assertEqual(self.client.writes, 0)
    def test_blistex_body_drift_and_checkpoint_failure_write_zero(self):
        self.prepare_blistex(); plan = self.prepare()
        self.client.live['product']['descriptionHtml'] += ' '
        with self.assertRaises(exe.Hold): self.run_apply(plan)
        self.assertEqual(self.client.writes, 0)
        self.client = Client(self.snapshot); self.checkpoint.verify.return_value = False
        with self.assertRaises(exe.Hold): self.run_apply(plan)
        self.assertEqual(self.client.writes, 0)
    def test_blistex_timeout_reconciles_without_second_write(self):
        self.prepare_blistex(); plan = self.prepare(); self.client.error = TimeoutError('synthetic')
        self.assertEqual(self.run_apply(plan)['state'], 'write_unknown')
        self.assertEqual(self.run_apply(plan)['state'], 'verified'); self.assertEqual(self.client.writes, 1)
    def test_blistex_postwrite_title_change_remains_pending(self):
        self.prepare_blistex(); self.client.alter_after = lambda s:s['product'].update(title='Changed')
        plan = self.prepare()
        self.assertEqual(self.run_apply(plan)['state'], 'verification_pending')
        self.assertEqual(self.run_apply(plan)['state'], 'verification_pending')
        self.assertEqual(self.client.writes, 1)
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


    def test_extracted_wrappers_use_one_shared_engine(self):
        plan = self.plan()
        with patch.object(exe.transaction, 'execute', return_value={'state':'synthetic'}) as run:
            self.assertEqual(exe.execute(plan, root=self.root,
                expected_plan_digest=plan['plan_digest']), {'state':'synthetic'})
            self.assertIs(run.call_args.args[0], exe._DRAFT_POLICY)
            self.assertIs(run.call_args.kwargs['atomic_write'], exe.atomic_json)
        with patch.object(exe.transaction, 'reconcile', return_value={'state':'synthetic'}) as run:
            self.assertEqual(exe.reconcile(plan, self.client), {'state':'synthetic'})
            run.assert_called_once_with(exe._DRAFT_POLICY, plan, self.client)
        self.assertTrue(issubclass(exe.GitHubCheckpoint, exe.transaction.GitHubCheckpoint))

    def test_shared_engine_has_no_default_or_json_selected_policy(self):
        with self.assertRaises(TypeError):
            exe.transaction.GitHubCheckpoint('SYNTHETIC TOKEN','90','a'*64)
        with self.assertRaises(TypeError):
            exe.GitHubCheckpoint('SYNTHETIC TOKEN','90','a'*64,policy=object())
        plan = self.plan()
        plan['policy_module'] = 'dr_cpu_active_copy'
        plan['scope']['expected_status'] = 'ACTIVE'
        plan['plan_digest'] = exe.compute_plan_digest(plan)
        with self.assertRaises(exe.Hold):
            exe.execute(plan,root=self.root,expected_plan_digest=plan['plan_digest'])
        self.assertEqual(self.client.writes,0)

    def test_exact_draft_allowlist_rejects_active_target(self):
        self.assertEqual(set(exe.copy.ALLOWED), {'1033789','1073406','1076498'})
        self.scope.update(pd_no='1084687',product_id='gid://shopify/Product/9590780723457',
                          expected_status='ACTIVE')
        self.snapshot['product'].update(id=self.scope['product_id'],status='ACTIVE')
        with self.assertRaises(exe.Hold): self.plan()
        self.assertEqual(self.client.writes,0)

    def test_implementation_digest_includes_shared_engine(self):
        initial = exe.implementation_digest()
        original = Path.read_bytes
        def altered(path):
            raw = original(path)
            return raw+b'\n# synthetic changed engine\n' if path.name=='reviewed_copy_transaction.py' else raw
        with patch.object(Path, 'read_bytes', altered):
            self.assertNotEqual(initial, exe.implementation_digest())

    def test_checkpoint_policy_namespace_rejected_before_network(self):
        plan, journal, backend = self.backend()
        wrong = deepcopy(journal)
        wrong['workflow_path'] = '.github/workflows/shopify-reviewed-active-copy.yml'
        backend.request = Mock(side_effect=AssertionError('must fail before any request'))
        with self.assertRaises(exe.Hold): backend.verify(plan,wrong)
        backend.request.assert_not_called()
        wrong = deepcopy(journal)
        wrong['artifact_name'] = 'active-copy-checkpoint-'+plan['operation_id']+'-1234-1'
        with self.assertRaises(exe.Hold): backend.verify(plan,wrong)
        backend.request.assert_not_called()

    def test_other_trusted_namespace_cannot_restore_draft_artifact(self):
        plan, journal, backend = self.backend()
        class OtherNamespace(exe._DraftPolicy):
            WORKFLOW = '.github/workflows/synthetic-other-copy.yml'
            PREFIX = 'synthetic-other-copy-checkpoint-'
        other = exe.transaction.GitHubCheckpoint('SYNTHETIC TOKEN','90',
            backend.expected_digest,policy=OtherNamespace(),request=backend.request)
        with self.assertRaises(exe.Hold):
            other.restore(self.context['repository'],expected_plan_digest=plan['plan_digest'],
                expected_shop=self.scope['canonical_shop'],expected_product=self.scope['product_id'])

    def test_draft_namespace_cannot_restore_other_prefix(self):
        plan = self.prepare()
        journal = exe.read_json(self.path)
        journal['artifact_name'] = 'active-copy-checkpoint-'+plan['operation_id']+'-1234-1'
        plan, _, backend = self.backend(entries={'plan.json':exe.json_bytes(plan),
            'journal.json':exe.json_bytes(journal)})
        with self.assertRaises(exe.Hold):
            backend.restore(self.context['repository'],expected_plan_digest=plan['plan_digest'],
                expected_shop=self.scope['canonical_shop'],expected_product=self.scope['product_id'])

    def test_draft_plan_kind_cannot_be_changed_to_active(self):
        plan = self.prepare()
        plan['kind'] = 'reviewed_dr_cpu_active_copy'
        plan['plan_digest'] = exe.compute_plan_digest(plan)
        with self.assertRaises(exe.Hold): self.run_apply(plan)
        self.assertEqual(self.client.writes,0)
        with self.assertRaises(exe.Hold): exe.reconcile(plan,self.client)
        self.assertEqual(self.client.reads,0)

    def test_restore_checks_original_checkpoint_retention(self):
        plan, _, backend = self.backend(artifact_change=lambda a:a.update(expires_at=self.now.isoformat()))
        with self.assertRaises(exe.Hold):
            backend.restore(self.context['repository'],expected_plan_digest=plan['plan_digest'],
                expected_shop=self.scope['canonical_shop'],expected_product=self.scope['product_id'])

    def test_optional_public_readback_is_readonly_and_journaled(self):
        plan = self.prepare()
        class PublicPolicy(exe._DraftPolicy):
            after_readback = Mock(return_value={'state':'public_verification_pending',
                'admin_readback_verified':True,'public_readback_verified':False})
        policy = PublicPolicy()
        outcome = exe.transaction.execute(policy,plan,root=self.root,
            expected_plan_digest=plan['plan_digest'],client=self.client,journal_path=self.path,
            checkpoint=self.checkpoint,apply=True,now=self.now,atomic_write=exe.atomic_json)
        self.assertEqual(outcome['state'],'public_verification_pending')
        journal = exe.read_json(self.path)
        self.assertEqual(journal['state'],'public_verification_pending')
        self.assertTrue(journal['last_readback']['admin_readback_verified'])
        self.assertFalse(journal['last_readback']['public_readback_verified'])
        self.assertEqual(self.client.writes,1)
        policy.after_readback.return_value = {'state':'verified','admin_readback_verified':True,
                                             'public_readback_verified':True}
        outcome = exe.transaction.execute(policy,plan,root=self.root,
            expected_plan_digest=plan['plan_digest'],client=self.client,journal_path=self.path,
            checkpoint=self.checkpoint,apply=True,now=self.now)
        self.assertEqual(outcome['state'],'verified')
        self.assertEqual(self.client.writes,1)
        self.assertIs(policy.after_readback.call_args.args[2],self.client)
        self.assertEqual(exe.read_json(self.path)['state'],'verified')
        self.assertTrue(exe.read_json(self.path)['last_readback']['public_readback_verified'])

    def test_optional_public_check_runs_only_after_valid_api_readback(self):
        plan = self.prepare()
        class PublicPolicy(exe._DraftPolicy):
            after_readback = Mock(side_effect=AssertionError('must not check public before API'))
        policy = PublicPolicy()
        outcome = exe.transaction.reconcile(policy,plan,self.client)
        self.assertEqual(outcome['state'],'verification_pending')
        policy.after_readback.assert_not_called()
        self.assertEqual(self.client.writes,0)

    def test_optional_public_readback_exception_does_not_retry_write(self):
        plan = self.prepare()
        class PublicPolicy(exe._DraftPolicy):
            after_readback = Mock(side_effect=TimeoutError('synthetic public timeout'))
        policy = PublicPolicy()
        for _ in range(2):
            outcome = exe.transaction.execute(policy,plan,root=self.root,
                expected_plan_digest=plan['plan_digest'],client=self.client,journal_path=self.path,
                checkpoint=self.checkpoint,apply=True,now=self.now)
            self.assertEqual(outcome['state'],'verification_pending')
        self.assertEqual(self.client.writes,1)


    def test_foreign_artifact_prefix_does_not_cross_history_namespace(self):
        plan, journal, backend = self.backend(list_change=lambda listing:listing.update(
            total_count=2,artifacts=listing['artifacts']+[{'id':89,
                'name':'active-copy-checkpoint-'+exe.operation_id(self.scope)+'-1000-1'}]))
        self.assertTrue(backend.verify(plan,journal))

    def test_checkpoint_rejects_run_workflow_head_event_or_attempt_drift(self):
        for change in (lambda r:r.update(path='.github/workflows/shopify-reviewed-active-copy.yml'),
                       lambda r:r.update(head_sha='b'*40),lambda r:r.update(event='push'),
                       lambda r:r.update(run_attempt=2),lambda r:r.update(id=999)):
            plan, journal, backend = self.backend(run_change=change)
            with self.subTest(change=change):
                with self.assertRaises(exe.Hold): backend.verify(plan,journal)
        self.assertEqual(self.client.writes,0)

    def test_checkpoint_rejects_noncanonical_and_duplicate_json(self):
        plan = self.prepare()
        journal = exe.read_json(self.path)
        malformed = (exe.json_bytes(plan)+b'\n', b'{"schema_version":1,"schema_version":1}')
        for raw in malformed:
            plan, journal, backend = self.backend(entries={
                'plan.json':raw,'journal.json':exe.json_bytes(journal)})
            with self.assertRaises(exe.Hold): backend.verify(plan,journal)

    def test_checkpoint_duplicate_or_drifting_artifact_history_holds(self):
        plan, journal, backend = self.backend(list_change=lambda listing:listing.update(
            total_count=2,artifacts=listing['artifacts']*2))
        with self.assertRaises(exe.Hold): backend.verify(plan,journal)
        plan, journal, backend = self.backend()
        original_api = backend.api
        def drifting(path, **kwargs):
            if '/actions/artifacts?' in path:
                if path.endswith('&page=1'):
                    return {'total_count':2,'artifacts':[{'id':90,'name':journal['artifact_name']}]}
                return {'total_count':3,'artifacts':[{'id':91,'name':'unrelated'}]}
            return original_api(path,**kwargs)
        backend.api = drifting
        with self.assertRaisesRegex(exe.Hold,'checkpoint_scan_drift'): backend.verify(plan,journal)

    def test_checkpoint_signed_download_never_forwards_github_authorization(self):
        plan, journal, backend = self.backend()
        original = backend.request
        signed = 'https://synthetic.blob.core.windows.net/checkpoint.zip?signature=synthetic'
        calls = []
        def redirect_request(url, **kwargs):
            calls.append((url,kwargs))
            if url == signed:
                self.assertNotIn('Authorization',kwargs.get('headers',{}))
                return original('https://api.github.com/repos/synthetic/repo/actions/artifacts/90/zip')
            if url.endswith('/zip'):
                return 302, {'location':signed}, b''
            return original(url,**kwargs)
        backend.request = redirect_request
        self.assertTrue(backend.verify(plan,journal))
        self.assertEqual(calls[-1][0],signed)
        self.assertEqual(calls[-1][1]['hosts'],{'synthetic.blob.core.windows.net'})


    def test_hook_enabled_already_after_noop_checks_public_without_writes(self):
        first = self.plan()
        self.snapshot['product'].update(first['copy_plan']['changes'])
        self.client = Client(self.snapshot)
        plan = self.prepare()
        class PublicPolicy(exe._DraftPolicy):
            after_readback = Mock(return_value={'state':'public_verification_pending',
                'admin_readback_verified':True,'public_readback_verified':False})
        policy = PublicPolicy()
        outcome = exe.transaction.execute(policy,plan,root=self.root,
            expected_plan_digest=plan['plan_digest'],client=self.client,journal_path=self.path,
            checkpoint=self.checkpoint,apply=True,now=self.now)
        self.assertEqual(outcome['state'],'public_verification_pending')
        self.assertEqual(self.client.writes,0)
        self.assertTrue(outcome['journal_saved'])
        self.assertEqual(exe.read_json(self.path)['write_attempts'],0)
        self.assertEqual(exe.read_json(self.path)['state'],'public_verification_pending')
        policy.after_readback.assert_called_once()
        self.checkpoint.verify.assert_called_once()
        self.assertEqual(self.client.reads,3)

    def test_hook_started_readback_save_failure_is_readonly(self):
        plan = self.prepare()
        self.assertEqual(self.run_apply(plan)['state'],'verified')
        class PublicPolicy(exe._DraftPolicy):
            after_readback = Mock(return_value={'state':'public_verification_pending',
                'admin_readback_verified':True,'public_readback_verified':False})
        outcome = exe.transaction.execute(PublicPolicy(),plan,root=self.root,
            expected_plan_digest=plan['plan_digest'],client=self.client,journal_path=self.path,
            apply=True,now=self.now,atomic_write=Mock(side_effect=OSError('synthetic fsync failure')))
        self.assertEqual(outcome['state'],'public_verification_pending')
        self.assertFalse(outcome['journal_saved'])
        self.assertEqual(self.client.writes,1)

    def test_real_active_policy_cannot_restore_draft_artifact(self):
        import dr_cpu_active_copy as active
        plan, journal, backend = self.backend()
        other = active.GitHubCheckpoint('SYNTHETIC TOKEN','90',backend.expected_digest,
                                       request=backend.request)
        with self.assertRaises(exe.Hold):
            other.restore(self.context['repository'],expected_plan_digest=plan['plan_digest'],
                expected_shop=self.scope['canonical_shop'],expected_product=self.scope['product_id'])
        self.assertEqual(self.client.writes,0)


    def test_hook_noop_requires_checkpoint_before_public_verification(self):
        first = self.plan()
        self.snapshot['product'].update(first['copy_plan']['changes'])
        self.client = Client(self.snapshot)
        plan = self.prepare()
        class PublicPolicy(exe._DraftPolicy):
            after_readback = Mock(return_value={'state':'verified'})
        policy = PublicPolicy()
        with self.assertRaisesRegex(exe.Hold,'durable_checkpoint_required'):
            exe.transaction.execute(policy,plan,root=self.root,
                expected_plan_digest=plan['plan_digest'],client=self.client,journal_path=self.path,
                apply=True,now=self.now)
        policy.after_readback.assert_not_called()
        self.assertEqual(self.client.writes,0)
        self.assertEqual(exe.read_json(self.path)['state'],'prepared')

    def test_hook_noop_prior_checkpoint_requires_original_reconciliation(self):
        first = self.plan()
        self.snapshot['product'].update(first['copy_plan']['changes'])
        self.client = Client(self.snapshot)
        plan = self.prepare()
        class PublicPolicy(exe._DraftPolicy):
            after_readback = Mock(return_value={'state':'verified'})
        policy = PublicPolicy()
        self.checkpoint.verify.side_effect = exe.PriorCheckpoint({'id':1})
        outcome = exe.transaction.execute(policy,plan,root=self.root,
            expected_plan_digest=plan['plan_digest'],client=self.client,journal_path=self.path,
            checkpoint=self.checkpoint,apply=True,now=self.now)
        self.assertEqual(outcome['state'],'prior_checkpoint_reconcile_required')
        policy.after_readback.assert_not_called()
        self.assertEqual(self.client.writes,0)
        self.assertEqual(self.client.reads,1)

    def test_hook_noop_requires_exact_journal_and_last_moment_snapshot(self):
        first = self.plan()
        self.snapshot['product'].update(first['copy_plan']['changes'])
        self.client = Client(self.snapshot)
        plan = self.prepare()
        class PublicPolicy(exe._DraftPolicy):
            after_readback = Mock(return_value={'state':'verified'})
        policy = PublicPolicy()
        journal = exe.read_json(self.path); journal['unexpected'] = True
        exe.atomic_json(self.path,journal)
        with self.assertRaisesRegex(exe.Hold,'journal_shape_mismatch'):
            exe.transaction.execute(policy,plan,root=self.root,
                expected_plan_digest=plan['plan_digest'],client=self.client,journal_path=self.path,
                checkpoint=self.checkpoint,apply=True,now=self.now)
        self.checkpoint.verify.assert_not_called()
        journal.pop('unexpected'); exe.atomic_json(self.path,journal)
        self.client.reads = 0
        self.client.on_read[2] = lambda snap:snap['product']['variants'][0].update(price='999.00')
        with self.assertRaisesRegex(exe.Hold,'last_moment_drift'):
            exe.transaction.execute(policy,plan,root=self.root,
                expected_plan_digest=plan['plan_digest'],client=self.client,journal_path=self.path,
                checkpoint=self.checkpoint,apply=True,now=self.now)
        policy.after_readback.assert_not_called()
        self.assertEqual(self.client.writes,0)

    def test_hook_new_after_body_baseline_cannot_mask_original_protected_drift(self):
        original = self.prepare()
        self.client.alter_after = lambda snap:snap['product']['variants'][0].update(price='999.00')
        self.assertEqual(self.run_apply(original)['state'],'verification_pending')
        self.assertEqual(self.client.writes,1)
        self.snapshot = deepcopy(self.client.live)
        replacement = self.plan()
        self.assertEqual(replacement['copy_plan']['changes'],{})
        self.assertEqual(replacement['operation_id'],original['operation_id'])
        new_path = self.root/'replacement-journal.json'
        exe.atomic_json(new_path,exe.make_journal(replacement,**self.context))
        class PublicPolicy(exe._DraftPolicy):
            after_readback = Mock(return_value={'state':'verified'})
        policy = PublicPolicy()
        self.checkpoint.verify.side_effect = exe.PriorCheckpoint({'id':1})
        outcome = exe.transaction.execute(policy,replacement,root=self.root,
            expected_plan_digest=replacement['plan_digest'],client=self.client,journal_path=new_path,
            checkpoint=self.checkpoint,apply=True,now=self.now)
        self.assertEqual(outcome['state'],'prior_checkpoint_reconcile_required')
        policy.after_readback.assert_not_called()
        self.assertEqual(exe.reconcile(original,self.client)['state'],'verification_pending')
        self.assertEqual(exe.read_json(self.path)['state'],'verification_pending')
        self.assertEqual(self.client.writes,1)


    def original_checkpoint_backend(self, **kwargs):
        plan, journal, backend = self.backend(**kwargs)
        class OriginalPolicy(exe._DraftPolicy):
            REQUIRE_ORIGINAL_CHECKPOINT = True
        backend = exe.transaction.GitHubCheckpoint('SYNTHETIC TOKEN','90',backend.expected_digest,
            policy=OriginalPolicy(),request=backend.request)
        return plan, journal, backend

    def restore_checkpoint(self, plan, backend):
        return backend.restore(self.context['repository'],expected_plan_digest=plan['plan_digest'],
            expected_shop=self.scope['canonical_shop'],expected_product=self.scope['product_id'])

    def test_original_restore_requires_two_complete_stable_scans(self):
        plan, journal, backend = self.original_checkpoint_backend(list_change=lambda listing:listing.update(
            total_count=2,artifacts=listing['artifacts']+[{'id':91,'expired':False,
                'name':exe.PREFIX+exe.operation_id(self.scope)+'-1001-1'}]))
        request = Mock(side_effect=backend.request); backend.request = request
        restored, _ = self.restore_checkpoint(plan,backend)
        self.assertEqual(restored,plan)
        self.assertEqual(sum('/actions/artifacts?' in c.args[0] for c in request.call_args_list),2)

    def test_original_restore_rejects_valid_later_checkpoint(self):
        plan, journal, backend = self.original_checkpoint_backend(list_change=lambda listing:listing.update(
            total_count=2,artifacts=listing['artifacts']+[{'id':89,'expired':False,
                'name':exe.PREFIX+exe.operation_id(self.scope)+'-1000-1'}]))
        with self.assertRaisesRegex(exe.Hold,'restore_original_checkpoint_required'):
            self.restore_checkpoint(plan,backend)
        self.assertEqual(self.client.writes,0)

    def test_draft_restore_preserves_no_history_enforcement(self):
        plan, journal, backend = self.backend()
        original = backend.request
        def request(url, **kwargs):
            if '/actions/artifacts?' in url:
                raise AssertionError('DRAFT restore must preserve its existing behavior')
            return original(url,**kwargs)
        backend.request = request
        restored, _ = self.restore_checkpoint(plan,backend)
        self.assertEqual(restored,plan)

    def test_original_restore_expired_operation_history_fails_closed(self):
        for prior_id in (89,91):
            plan, journal, backend = self.original_checkpoint_backend(list_change=lambda listing:listing.update(
                total_count=2,artifacts=listing['artifacts']+[{'id':prior_id,'expired':True,
                    'name':exe.PREFIX+exe.operation_id(self.scope)+'-1000-1'}]))
            with self.assertRaisesRegex(exe.Hold,'restore_history_expired_or_missing'):
                self.restore_checkpoint(plan,backend)

    def test_original_restore_unreadable_or_incomplete_history_fails_closed(self):
        for payload in ({'total_count':1,'artifacts':[]},{'total_count':2,'artifacts':[{'id':90}]},
                        {'total_count':1,'artifacts':[{'id':91,'name':'unrelated','expired':False}]}):
            plan, journal, backend = self.original_checkpoint_backend()
            original = backend.api
            def api(path, **kwargs):
                return payload if '/actions/artifacts?' in path else original(path,**kwargs)
            backend.api = api
            with self.assertRaises(exe.Hold): self.restore_checkpoint(plan,backend)
        plan, journal, backend = self.original_checkpoint_backend()
        original = backend.request
        def unreadable(url, **kwargs):
            return (503,{},b'') if '/actions/artifacts?' in url else original(url,**kwargs)
        backend.request = unreadable
        with self.assertRaisesRegex(exe.Hold,'github_checkpoint_api_failed'):
            self.restore_checkpoint(plan,backend)

    def test_original_restore_same_count_history_drift_fails_closed(self):
        plan, journal, backend = self.original_checkpoint_backend()
        original = backend.api; scans = []
        def api(path, **kwargs):
            response = original(path,**kwargs)
            if '/actions/artifacts?' in path:
                scans.append(1)
                response['total_count'] = 2
                response['artifacts'].append({'id':91,'name':'unrelated-'+str(len(scans)),'expired':False})
            return response
        backend.api = api
        with self.assertRaisesRegex(exe.Hold,'checkpoint_scan_drift'):
            self.restore_checkpoint(plan,backend)
        self.assertEqual(len(scans),2)

    def test_original_restore_history_metadata_must_match_selected_artifact(self):
        plan, journal, backend = self.original_checkpoint_backend()
        original = backend.api
        def api(path, **kwargs):
            response = original(path,**kwargs)
            if '/actions/artifacts?' in path:
                response['artifacts'][0]['digest'] = 'sha256:'+'0'*64
            return response
        backend.api = api
        with self.assertRaisesRegex(exe.Hold,'restore_history_metadata_mismatch'):
            self.restore_checkpoint(plan,backend)

    def test_original_restore_history_scan_is_bounded(self):
        plan, journal, backend = self.original_checkpoint_backend()
        original = backend.api; pages = []
        def api(path, **kwargs):
            if '/actions/artifacts?' in path:
                pages.append(1)
                return {'total_count':100,'artifacts':[{'id':len(pages),'name':'unrelated'}]}
            return original(path,**kwargs)
        backend.api = api
        with patch.object(exe.transaction,'MAX_PAGES',2):
            with self.assertRaisesRegex(exe.Hold,'checkpoint_scan_limit'):
                self.restore_checkpoint(plan,backend)
        self.assertEqual(len(pages),2)


    def original_resume_policy(self):
        class OriginalPolicy(exe._DraftPolicy):
            REQUIRE_ORIGINAL_CHECKPOINT = True
            after_readback = Mock(return_value={'state':'verified',
                'admin_readback_verified':True,'public_readback_verified':True})
        return OriginalPolicy()

    def test_strict_resume_requires_checkpoint_before_any_readback(self):
        plan = self.prepare(); prepared = exe.read_json(self.path)
        policy = self.original_resume_policy()
        for state, attempts in [('write_started',1),('unknown',0),('prepared',1),('verified',1)]:
            journal = deepcopy(prepared); journal.update(state=state,write_attempts=attempts)
            exe.atomic_json(self.path,journal)
            with self.assertRaisesRegex(exe.Hold,'original_checkpoint_required_for_resume'):
                exe.transaction.execute(policy,plan,root=self.root,
                    expected_plan_digest=plan['plan_digest'],client=self.client,journal_path=self.path,
                    apply=True,now=self.now)
        self.assertEqual(self.client.reads,0); self.assertEqual(self.client.writes,0)
        policy.after_readback.assert_not_called()

    def test_strict_genuine_resume_restores_exact_original_then_reads_only(self):
        plan = self.prepare(); prepared = exe.read_json(self.path)
        self.assertEqual(self.run_apply(plan)['state'],'verified')
        policy = self.original_resume_policy()
        checkpoint = Mock(); checkpoint.restore.return_value = (deepcopy(plan),deepcopy(prepared))
        outcome = exe.transaction.execute(policy,plan,root=self.root,
            expected_plan_digest=plan['plan_digest'],client=self.client,journal_path=self.path,
            checkpoint=checkpoint,apply=True,now=self.now)
        self.assertEqual(outcome['state'],'verified'); self.assertEqual(outcome['writes'],0)
        self.assertEqual(self.client.writes,1)
        checkpoint.restore.assert_called_once_with(self.context['repository'],
            expected_plan_digest=plan['plan_digest'],expected_shop=self.scope['canonical_shop'],
            expected_product=self.scope['product_id'])
        checkpoint.verify.assert_not_called(); policy.after_readback.assert_called_once()

    def test_strict_resume_rejects_changed_immutable_context(self):
        plan = self.prepare(); prepared = exe.read_json(self.path)
        policy = self.original_resume_policy()
        checkpoint = Mock(); checkpoint.restore.return_value = (deepcopy(plan),deepcopy(prepared))
        for edit in (lambda j:j.update(run_id='999'),lambda j:j.update(artifact_name='wrong'),
                     lambda j:j.update(extra='unrecognized'),
                     lambda j:j['before']['product']['variants'][0].update(price='999.00')):
            journal = deepcopy(prepared); journal.update(state='write_started',write_attempts=1); edit(journal)
            exe.atomic_json(self.path,journal)
            with self.assertRaises(exe.Hold):
                exe.transaction.execute(policy,plan,root=self.root,
                    expected_plan_digest=plan['plan_digest'],client=self.client,journal_path=self.path,
                    checkpoint=checkpoint,apply=True,now=self.now)
        self.assertEqual(self.client.reads,0); self.assertEqual(self.client.writes,0)
        policy.after_readback.assert_not_called()

    def test_strict_resume_rejects_new_after_body_protected_baseline(self):
        original = self.prepare(); original_journal = exe.read_json(self.path)
        self.client.alter_after = lambda snap:snap['product']['variants'][0].update(price='999.00')
        self.assertEqual(self.run_apply(original)['state'],'verification_pending')
        self.snapshot = deepcopy(self.client.live); replacement = self.plan()
        self.assertEqual(replacement['copy_plan']['changes'],{})
        self.assertEqual(replacement['operation_id'],original['operation_id'])
        journal = exe.make_journal(replacement,**self.context)
        journal.update(state='write_started',write_attempts=1)
        new_path = self.root/'replacement-resume.json'; exe.atomic_json(new_path,journal)
        policy = self.original_resume_policy()
        checkpoint = Mock(); checkpoint.restore.return_value = (deepcopy(original),deepcopy(original_journal))
        reads = self.client.reads
        with self.assertRaisesRegex(exe.Hold,'plan_digest_mismatch'):
            exe.transaction.execute(policy,replacement,root=self.root,
                expected_plan_digest=replacement['plan_digest'],client=self.client,journal_path=new_path,
                checkpoint=checkpoint,apply=True,now=self.now)
        checkpoint.restore.assert_called_once(); policy.after_readback.assert_not_called()
        self.assertEqual(self.client.reads,reads); self.assertEqual(self.client.writes,1)
        self.assertEqual(exe.reconcile(original,self.client)['state'],'verification_pending')

    def test_strict_resume_unreadable_restore_does_not_read_or_write_shopify(self):
        plan = self.prepare(); journal = exe.read_json(self.path)
        journal.update(state='write_started',write_attempts=1); exe.atomic_json(self.path,journal)
        policy = self.original_resume_policy()
        checkpoint = Mock(); checkpoint.restore.side_effect = exe.Hold('checkpoint_unreadable')
        with self.assertRaisesRegex(exe.Hold,'checkpoint_unreadable'):
            exe.transaction.execute(policy,plan,root=self.root,
                expected_plan_digest=plan['plan_digest'],client=self.client,journal_path=self.path,
                checkpoint=checkpoint,apply=True,now=self.now)
        self.assertEqual(self.client.reads,0); self.assertEqual(self.client.writes,0)
        policy.after_readback.assert_not_called()

    def test_strict_write_history_rejects_unnamed_rows(self):
        for name in (None,'',9):
            def alter(listing):
                listing.update(total_count=2,artifacts=listing['artifacts']+[{'id':89,'name':name}])
            plan, journal, backend = self.original_checkpoint_backend(list_change=alter)
            with self.assertRaisesRegex(exe.Hold,'checkpoint_scan_identity_missing'):
                backend.verify(plan,journal)
        self.assertEqual(self.client.writes,0)

    def test_strict_write_history_is_checked_twice(self):
        plan, journal, backend = self.original_checkpoint_backend()
        request = Mock(side_effect=backend.request); backend.request = request
        self.assertTrue(backend.verify(plan,journal))
        self.assertEqual(sum('/actions/artifacts?' in c.args[0] for c in request.call_args_list),2)

    def test_strict_write_same_count_history_metadata_drift_holds(self):
        plan, journal, backend = self.original_checkpoint_backend()
        original = backend.api; scans = []
        def api(path, **kwargs):
            response = original(path,**kwargs)
            if '/actions/artifacts?' in path:
                scans.append(1)
                response['artifacts'][0]['updated_at'] = str(len(scans))
            return response
        backend.api = api
        with self.assertRaisesRegex(exe.Hold,'checkpoint_scan_drift'):
            backend.verify(plan,journal)

    def test_strict_write_history_metadata_matches_selected_artifact(self):
        plan, journal, backend = self.original_checkpoint_backend()
        original = backend.api
        def api(path, **kwargs):
            response = original(path,**kwargs)
            if '/actions/artifacts?' in path:
                response['artifacts'][0]['digest'] = 'sha256:'+'0'*64
            return response
        backend.api = api
        with self.assertRaisesRegex(exe.Hold,'checkpoint_history_metadata_mismatch'):
            backend.verify(plan,journal)

    def test_draft_write_preserves_single_history_scan(self):
        plan, journal, backend = self.backend()
        request = Mock(side_effect=backend.request); backend.request = request
        self.assertTrue(backend.verify(plan,journal))
        self.assertEqual(sum('/actions/artifacts?' in c.args[0] for c in request.call_args_list),1)


if __name__=='__main__':unittest.main()
