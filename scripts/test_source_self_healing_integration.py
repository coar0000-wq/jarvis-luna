"""Offline self-healing integration fixtures, never real source/provider calls."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'scripts'))
from scripts import run_source_procedures as r
from scripts import github_artifact_io as gh
from scripts import restore_source_safety as restore
from scripts import run_jarvis_operations as ops
from scripts import discover_channels as channels
from scripts import export_shopify_operational as exporter
from scripts import build_shopify_shortlist as shortlist_builder
from scripts import validate_commerce_architecture as commerce_validator
from scripts import generate_dashboard_runtime as runtime_builder
import gate_signature as signature
from scripts import publish_transaction as pub
from scripts.source_procedure_state import SourceProcedureStore, canonical, failure_fingerprint, _seal
from scripts import source_safety_checkpoint as safety
import test_source_safety_checkpoint as safety_tests


class ProcedureIntegration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for commands in r.COMMANDS.values():
            for command in commands:
                p=self.root/command[0]; p.parent.mkdir(parents=True,exist_ok=True); p.write_text('# fixed offline fixture\n')
        self.rows=[]
        for team in r.TEAMS:
            relative=r.SOURCES[team]
            p=self.root/relative; p.parent.mkdir(parents=True,exist_ok=True); p.write_text('{}')
            self.rows.append({'source_team':team,'source':relative,'status':'BASELINE','blockers':[],
                'source_hash':'a'*64,'source_document_hash':hashlib.sha256(p.read_bytes()).hexdigest(),
                'captured_at':'2026-01-01T00:00:00+00:00','observed_at':'2026-01-01T00:00:00+00:00',
                'observation_kind':'source_capture','required_scope_complete':True,'coverage':{'complete':True}})
        self.store=SourceProcedureStore(self.root/r.DIRECTORY)
        r.atomic(self.root,r.CHECKPOINT,self.store.fresh_init(trusted_caller=True))
        self.calls=[]
        self.net=patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')); self.net.start(); self.addCleanup(self.net.stop)

    def observation(self,root=None,*,now=None):
        rows=copy.deepcopy(self.rows)
        for row in rows: row['observed_at']=now or r.now()
        return {'watchers':rows}

    def blocked(self,team='sourcing'):
        row=next(x for x in self.rows if x['source_team']==team)
        row.update(status='BLOCKED',blockers=['STALE_SOURCE_CAPTURE'],required_scope_complete=False,coverage={'complete':False})

    def call(self,executor,invocation='fixture.one'):
        with patch.object(r.watch,'observe',side_effect=self.observation):
            return r.run(self.root,invocation_id=invocation,source_reads=True,
                observer=lambda:self.observation(),executor=executor)

    def state(self): return json.loads((self.root/r.DIRECTORY/SourceProcedureStore.filename).read_text())

    def test_claim_and_checkpoint_durable_before_fixed_dispatch_exit_zero_not_health(self):
        self.blocked()
        def execute(procedure):
            self.calls.append(procedure)
            state=self.state(); cp=json.loads((self.root/r.CHECKPOINT).read_text())
            self.assertEqual(state['teams']['sourcing']['lifetime'],1)
            self.assertEqual(state['teams']['sourcing']['episodes'][0]['attempts'][0]['status'],'CLAIMED')
            self.assertEqual(cp['table_hash'],state['table_hash'])
            return 0,b'actual fixture stdout, not source proof'
        report=self.call(execute)
        self.assertEqual(self.calls,['daiso_shortlist_observe'])
        attempt=self.state()['teams']['sourcing']['episodes'][0]['attempts'][0]
        self.assertFalse(attempt['outcome']['source_healthy']); self.assertFalse(attempt['outcome']['receipt_verified'])
        self.assertFalse(report['authority']); self.assertFalse(report['business_clearance'])

    def test_real_watcher_kind_normalized_only_after_validated_scope(self):
        row=copy.deepcopy(self.rows[0]); row['observed_at']=r.now()
        self.assertEqual(r.source_proof(row,r.now())['observation_kind'],'actual_source_capture')
        row['required_scope_complete']=False
        self.assertIsNone(r.source_proof(row,r.now()))

    def test_actual_fresh_owned_source_and_bytes_validate(self):
        self.blocked()
        def execute(procedure):
            self.rows[0].update(status='BASELINE',blockers=[],required_scope_complete=True,coverage={'complete':True})
            return 0,b'actual fixed fixture output'
        self.call(execute)
        outcome=self.state()['teams']['sourcing']['episodes'][0]['attempts'][0]['outcome']
        self.assertTrue(outcome['source_healthy']); self.assertFalse(outcome['authority'])

    def test_interrupted_claim_read_reconciliation_no_replay_no_false_exit_zero(self):
        binding={'source_team':'sourcing','fixedprocedure_id':'daiso_shortlist_observe',
          'failure_fingerprint':failure_fingerprint({'source_identity':r.SOURCES['sourcing'],'source_hash':'a'*64,'blocker_codes':['SOURCE_UNAVAILABLE']})}
        self.store.claim(binding,'fixture.old',now='2026-01-01T00:00:00+00:00'); r.atomic(self.root,r.CHECKPOINT,self.store.checkpoint())
        self.call(lambda p:(_ for _ in ()).throw(AssertionError('replay forbidden')))
        team=self.state()['teams']['sourcing']; attempt=team['episodes'][0]['attempts'][0]
        self.assertEqual(team['lifetime'],1); self.assertEqual(attempt['status'],'RECONCILED')
        self.assertIsNone(attempt['outcome']['exit_code']); self.assertFalse(attempt['outcome']['source_healthy'])

    def test_missing_state_or_checkpoint_cannot_bootstrap(self):
        (self.root/r.DIRECTORY/SourceProcedureStore.filename).unlink()
        with self.assertRaises((ValueError,OSError)): self.call(lambda p:(0,b'forbidden'))
        self.assertFalse((self.root/r.DIRECTORY/SourceProcedureStore.filename).exists())

    def test_marker_blocks_source_dispatch(self):
        (self.root/r.PENDING).write_text('interrupted restore')
        with self.assertRaises(ValueError): self.call(lambda p:(0,b'forbidden'))
        self.assertEqual(self.state()['teams']['sourcing']['lifetime'],0)

    def test_typed_robots_and_quota_stops_hold_without_claim(self):
        self.blocked()
        for value in ({'last_attempt':{'code':'robots_denied'}},{'last_attempt':{'http_status':429}},{'reason':'robots denied'}):
            (self.root/r.SOURCES['sourcing']).write_text(json.dumps(value))
            self.call(lambda p:(_ for _ in ()).throw(AssertionError('provider stop bypass')))
            self.assertEqual(self.state()['teams']['sourcing']['lifetime'],0)

    def test_one_network_actuator_per_invocation_and_stable_fingerprint(self):
        self.blocked(); self.blocked('robotics')
        def execute(p): self.calls.append(p); return 1,b'actual transport failure fixture'
        self.call(execute)
        self.assertEqual(self.calls,['daiso_shortlist_observe'])
        row=copy.deepcopy(self.rows[0]); a=r._binding(self.root,row,'daiso_shortlist_observe')
        row['observed_at']=r.now(); row['generated_at']='2099-01-01T00:00:00Z'
        self.assertEqual(a,r._binding(self.root,row,'daiso_shortlist_observe'))


class ResumptionIntegration(unittest.TestCase):
    def test_old_goal_resumption_only_known_idempotent_local_kinds(self):
        for kind in ('read_snapshot','snapshot_report'):
            self.assertTrue(ops.resumable_local_task({'state':'EXECUTING','kind':kind,'goal':'old immutable goal'}))
        for kind in ('shopify_create_draft','payment','data_delete','rebuild_dashboard','unknown'):
            self.assertFalse(ops.resumable_local_task({'state':'EXECUTING','kind':kind,'goal':'old'}))
        self.assertFalse(ops.resumable_local_task({'state':'COMPLETED','kind':'snapshot_report'}))
        source=(ROOT/'scripts/run_jarvis_operations.py').read_text()
        self.assertIn("t['task_id'] in restart_ids",source)

    def test_publication_channel_check_never_reads_or_reclocks_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'channel_candidates.json'
            doc={'generated_at':'2026-01-01T00:00:00Z','tested':1,'candidates':[{'key':channels.CANDIDATES[0]['key'],'verdict':'불가','reason':'robots denied','last_attempt':{'code':'robots_denied'}}]}
            raw=json.dumps(doc).encode();file.write_bytes(raw)
            with patch.object(channels,'OUT',file),patch.object(channels.sys,'argv',['discover_channels.py','--cached-only']),patch.object(channels,'probe',side_effect=AssertionError('network forbidden')):
                self.assertEqual(channels.main(),0)
            self.assertEqual(file.read_bytes(),raw)
        policy=json.loads((ROOT/'config/publish_policy.json').read_text())
        self.assertIn(['scripts/discover_channels.py','--cached-only'],policy['commerce_commands'])

    def test_legal_block_noop_preserves_all_old_draft_bytes_without_clearance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); data=root/'data'; out=data/'shopify_exports';out.mkdir(parents=True)
            (data/'listing_gate.json').write_text(json.dumps({'items':[{'pd_no':'1','ready':False}]}))
            (data/'shopify_shortlist.json').write_text(json.dumps({'active_pd_nos':['1']}))
            old=out/'draft.csv';raw=b'Published,Status,Variant Inventory Qty\nFALSE,draft,0\n';old.write_bytes(raw)
            with patch.object(exporter,'ROOT',root),patch.object(exporter,'D',data),patch.object(exporter,'OUT',out),patch.object(signature,'require_current',return_value=None),patch.object(sys,'argv',['export_shopify_operational.py','--blocked-noop']),patch.object(exporter,'write_csv',side_effect=AssertionError('no export mutation')):
                self.assertEqual(exporter.main(),0)
                sys.argv=['export_shopify_operational.py']
                with self.assertRaisesRegex(RuntimeError,'ready'):exporter.main()
            self.assertEqual(list(out.iterdir()),[old]);self.assertEqual(old.read_bytes(),raw)
        policy=json.loads((ROOT/'config/publish_policy.json').read_text())
        self.assertIn(['scripts/export_shopify_operational.py','--blocked-noop'],policy['commerce_commands'])

    def test_legal_hold_preserves_selected_observation_members_not_eligibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous=Path(tmp)/'shortlist.json'
            previous.write_text(json.dumps({'units':[{'unit_id':'VG-CP000001','status':'active','pd_nos':['1'],'added_at':'2026-01-01T00:00:00Z'}]}))
            ctx={'recs':[{'pd_no':'1','canonical_product_id':'CP000001','name':'Face cream','shopify_score':90,'matched_global':{'similarity':.9,'global_product':'Face cream'}}], 'gate':{'1':{'ready':False,'blocked_by':['required_english_label_human_approval']}},'pm':{'1':{'canonical_product_id':'CP000001'}}}
            with patch.object(shortlist_builder,'OUT',previous),patch.object(shortlist_builder,'MANUAL',Path(tmp)/'absent.json'),patch.object(shortlist_builder,'_context',return_value=ctx):
                doc=shortlist_builder.build()
            self.assertEqual(doc['active_pd_nos'],['1']);self.assertEqual(doc['eligible_pd_nos'],[])
            self.assertFalse(doc['business_authority']);self.assertFalse(doc['units'][0]['business_ready'])
            self.assertEqual(doc['rules']['max_units'],5)
            self.assertEqual(doc['units'][0]['added_at'],'2026-01-01T00:00:00Z')

    def test_legally_blocked_exports_require_exact_committed_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'data/shopify_exports';out.mkdir(parents=True)
            for name in ('products.csv','inventory.csv','images.csv','collections.csv'):(out/name).write_bytes(b'old draft bytes\n')
            result=type('Result',(),{'returncode':0,'stdout':b'old draft bytes\n'})()
            with patch.object(commerce_validator.subprocess,'run',return_value=result):
                commerce_validator.validate_retained_blocked_exports(root,out)
                (out/'products.csv').write_bytes(b'new unauthorized payload\n')
                with self.assertRaisesRegex(AssertionError,'changed'):commerce_validator.validate_retained_blocked_exports(root,out)
            result.returncode=1
            with patch.object(commerce_validator.subprocess,'run',return_value=result),self.assertRaises(AssertionError):commerce_validator.validate_retained_blocked_exports(root,out)

    def test_legally_blocked_exports_accept_only_real_git_checkout_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'data/shopify_exports';out.mkdir(parents=True)
            hooks=root/'empty-hooks';hooks.mkdir()
            subprocess.run(['git','init','-q',str(root)],check=True,capture_output=True)
            (root/'.gitattributes').write_text('data/shopify_exports/*.csv text eol=crlf\n')
            raw=b'old,draft,0\nretained,FALSE,0\n'
            names=('products.csv','inventory.csv','images.csv','collections.csv')
            for name in names:(out/name).write_bytes(raw)
            subprocess.run(['git','-c','core.autocrlf=false','add','--','.gitattributes','data'],cwd=root,check=True,capture_output=True)
            subprocess.run(['git','-c','user.name=Offline Fixture','-c','user.email=fixture@example.invalid',
                            '-c','commit.gpgsign=false','-c',f'core.hooksPath={hooks}',
                            'commit','-qm','retained export fixture'],cwd=root,check=True,capture_output=True)
            checkout=subprocess.check_output(['git','cat-file','--filters','HEAD:data/shopify_exports/products.csv'],cwd=root)
            self.assertEqual(checkout,raw.replace(b'\n',b'\r\n'))
            for name in names:(out/name).write_bytes(checkout)
            commerce_validator.validate_retained_blocked_exports(root,out)
            # Mixed endings have the same Git-normalized content hash, but are
            # neither the committed blob nor the exact checkout byte form.
            (out/'products.csv').write_bytes(raw.replace(b'\n',b'\r\n',1))
            with self.assertRaisesRegex(AssertionError,'changed'):
                commerce_validator.validate_retained_blocked_exports(root,out)
            (out/'products.csv').write_bytes(b'unauthorized,payload,1\r\n')
            with self.assertRaisesRegex(AssertionError,'changed'):
                commerce_validator.validate_retained_blocked_exports(root,out)
            (out/'products.csv').write_bytes(raw)
            commerce_validator.validate_retained_blocked_exports(root,out)

    def test_runtime_rebuild_preserves_only_actual_matching_plan_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d=root/'data/agents';d.mkdir(parents=True)
            run={'ran':True,'generated_at':'2026-01-01T00:00:00Z','risk':'HIGH','task_count':3}
            plan={'generated_at':'2025-12-31T23:59:59Z','risk':'HIGH','task_count':3}
            (d/'last_run.json').write_text(json.dumps(run));(d/'ops_plan.json').write_text(json.dumps(plan))
            self.assertEqual(runtime_builder.agents_plan_heartbeat(root),{'risk':'HIGH','task_count':3,'at':run['generated_at']})
            plan['task_count']=4;(d/'ops_plan.json').write_text(json.dumps(plan))
            self.assertEqual(runtime_builder.agents_plan_heartbeat(root),{})
            (d/'last_run.json').unlink();self.assertEqual(runtime_builder.agents_plan_heartbeat(root),{})

    def test_source_only_publication_cannot_trigger_model_copy_job(self):
        listing=(ROOT/'.github/workflows/shopify-listing-copy.yml').read_text(encoding='utf-8')
        self.assertIn("github.event_name != 'push' || !contains(github.event.head_commit.message, '[source-recovery-offline]')",listing)
        daiso=(ROOT/'.github/workflows/daiso-real-collection.yml').read_text(encoding='utf-8')
        marked=[line for line in daiso.splitlines() if 'message:' in line and '[source-recovery-offline]' in line]
        self.assertEqual(len(marked),2)
        for line in marked:
            self.assertIn("github.event_name == 'workflow_dispatch' && !inputs.refresh_auxiliary_sources",line)

    def test_cumulative_run_history_is_not_pruned_by_display_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'history.json'
            old=[{'at':f'prior assembly {i}','records':1,'notes':1,'links':1,'added':{'records':0,'notes':0,'links':0}} for i in range(100)]
            file.write_text(json.dumps({'baseline':{'recorded_at':'known original baseline'},'totals':{'records':1,'notes':1,'links':1},'last_snapshot':{'records':1,'notes':1,'links':1},'runs':old}))
            with patch.object(runtime_builder,'HISTORY',file):runtime_builder.cumulative_metrics({'notes':1,'links':1},{'record_count':1})
            saved=json.loads(file.read_text())
            self.assertEqual(saved['runs'][:100],old);self.assertEqual(len(saved['runs']),101)
            self.assertEqual(saved['baseline']['recorded_at'],'known original baseline')

    def test_operations_restore_marker_blocks_before_state_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); marker=root/'data/operations/.restore-pending.json'; marker.parent.mkdir(parents=True);marker.write_text('{}')
            with self.assertRaisesRegex(ValueError,'restore_pending'): ops.run(root)
            self.assertFalse((root/'data/operations/state.json').exists())


class TransportIntegration(unittest.TestCase):
    def test_token_removed_on_signed_storage_redirect(self):
        seen=[]
        class Response(io.BytesIO):
            status=200; headers={'Content-Length':'3'}
        class Opener:
            def open(self,request,timeout):
                seen.append(request)
                if len(seen)==1:
                    raise urllib.error.HTTPError(request.full_url,302,'redirect',{'Location':'https://fixture.blob.core.windows.net/a?signed=fixture'},None)
                return Response(b'zip')
        url='https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/123/zip'
        with patch.dict(os.environ,{'GITHUB_TOKEN':'synthetic-fixture-token'}),patch.object(gh.urllib.request,'build_opener',return_value=Opener()):
            self.assertEqual(gh.fetch_artifact_bytes(url),b'zip')
        self.assertIn('Authorization',dict(seen[0].header_items()))
        self.assertNotIn('Authorization',dict(seen[1].header_items()))

    def test_foreign_repo_or_untrusted_redirect_denied(self):
        with self.assertRaises(gh.ArtifactReadBlocked): gh.fetch_artifact_bytes('https://api.github.com/repos/foreign/repo/actions/artifacts/123/zip')
        class Opener:
            def open(self,request,timeout):
                raise urllib.error.HTTPError(request.full_url,302,'redirect',{'Location':'https://evil.example/a'},None)
        with patch.object(gh.urllib.request,'build_opener',return_value=Opener()),self.assertRaises(gh.ArtifactReadBlocked):
            gh.fetch_artifact_bytes('https://api.github.com/repos/coar0000-wq/jarvis-luna/actions/artifacts/123/zip')


class PublicationIntegration(unittest.TestCase):
    def test_target_hash_mandatory_for_all_diagnostic_policy_refs(self):
        base=b'{}'; current=b'{"current":true}'
        for reference in ('scripts/workflow_status_history.py','scripts/gosi_observation_history.py','scripts/shortlist_observation_history.py'):
            record={'path':'data/fixture.json','base_sha256':pub.sha(base),'ids':['old'],'reason':'Exact immutable diagnostic history fixture','policy_ref':reference}
            manifest={'deletions':[record]}
            self.assertFalse(pub.deletion_authorized('data/fixture.json',base,['old'],manifest,replacement=current))
            record['replacement_sha256']=pub.sha(current)
            self.assertTrue(pub.deletion_authorized('data/fixture.json',base,['old'],manifest,replacement=current))
            self.assertFalse(pub.deletion_authorized('data/fixture.json',base,['old'],manifest,replacement=b'{"wrong":true}'))

    def test_collector_stage_bytes_and_git_endings_remain_exact(self):
        raw=b' {"last_attempt" : {"status":"no_change"}}\r\n'
        for name in pub.BYTE_BOUND_STAGE_FILES:
            if name == 'data/daiso_real/candidate_pool.json':
                # Candidate snapshots must satisfy the stronger product/evidence
                # schema even when this fixture only checks exact byte retention.
                pool = {'schema_version':1, 'count':0, 'items':{},
                        'approval_required':True, 'may_publish':False,
                        'may_replace_operating_products':False,
                        'last_run':{'execution_id':'fixture:1:collect',
                            'at':'2026-10-05T08:00:00+00:00', 'new':0,
                            'updated':0, 'collected_ids':[]}}
                base = json.dumps(pool).encode('utf-8')
                exact = b' ' + json.dumps(pool,indent=1).encode('utf-8') + b'\r\n'
                self.assertEqual(pub.overlay(name,base,exact,base,{'identity_fields':[]},{}),exact)
            else:
                self.assertEqual(pub.overlay(name,b'{}',raw,b'{}',{},{}),raw)
            with self.assertRaises(pub.PublishError): pub.overlay(name,b'{"source_fact":1}',raw,b'{"source_fact":1}',{}, {})
        attrs=(ROOT/'.gitattributes').read_text()
        for name in (*pub.BYTE_BOUND_STAGE_FILES,'data/agents/workflow_status_history/**','data/knowledge/gosi_observation_history/**'):
            self.assertIn(name+' -text',attrs)

    def test_history_exact_bytes_not_reformatted_or_pruned(self):
        raw=b'{"z": 1,"a":2}'; name='data/agents/workflow_status_history/'+pub.sha(raw)+'.json'
        self.assertEqual(pub.overlay(name,None,raw,None,{},{}),raw)
        with self.assertRaises(pub.PublishError): pub.overlay(name,raw,None,raw,{}, {})
        with self.assertRaises(pub.PublishError): pub.overlay(name,raw,b'{}',raw,{}, {})

    def test_consistent_resealed_stop_or_budget_regression_is_denied(self):
        fixture=safety_tests.SafetyCheckpointTests('test_roundtrip_exact_bytes_sha_manifest_source_clocks'); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        files=safety._snapshot(fixture.root)
        state=json.loads(files[safety.PROCEDURE]); state['teams']['sourcing']['budget']=4; state['teams']['sourcing']['stopped']=True; _seal(state)
        files[safety.PROCEDURE]=canonical(state).encode(); files[safety.CHECKPOINT]=canonical(fixture.store._checkpoint(state)).encode()
        candidate=copy.deepcopy(files); changed=copy.deepcopy(state)
        changed['teams']['sourcing'].update(budget=256,stopped=False); _seal(changed)
        candidate[safety.PROCEDURE]=canonical(changed).encode(); candidate[safety.CHECKPOINT]=canonical(fixture.store._checkpoint(changed)).encode()
        safety._validate(candidate)
        with self.assertRaises(safety.Blocked): safety._nonregression(files,candidate)
        source=(ROOT/'scripts/publish_transaction.py').read_text()
        self.assertIn('_nonregression(safety_before, files)',source)
        self.assertIn('_nonregression(safety_before, final_safety)',source)

    def test_observer_and_manifest_delta_stays_candidate_only(self):
        tx=object.__new__(pub.Transaction)
        tx.policy={'derived_paths':[]}; tx.is_derived=lambda n:False
        tx.delta={n:(b'{}',b'{}') for n in ('data/daiso_real/shortlist_observations.json','data/daiso_real/.shortlist_observation_claim.json','data/publish_deletions.json','data/agents/source_procedures/report.json')}
        self.assertTrue(tx.candidate_only())
        tx.delta['data/daiso_real/products.json']=(b'{}',b'{}')
        self.assertFalse(tx.candidate_only())

    def test_workflows_restore_before_actuate_and_always_retain(self):
        for name in ('daiso-real-collection.yml','JARVIS-Core-Automation.yml','JARVIS-Deep-Analysis.yml'):
            text=(ROOT/'.github/workflows'/name).read_text(encoding='utf-8')
            self.assertIn('group: main-publish',text)
            self.assertIn("steps.source_safety.outputs.continuity == 'verified'",text)
            self.assertIn('name: Retain source safety checkpoint\n        if: always()',text)
            self.assertIn('name: Retain immutable operations safety history\n        if: always()',text)
            self.assertIn('include-hidden-files: true',text)
        daiso=(ROOT/'.github/workflows/daiso-real-collection.yml').read_text()
        candidate=daiso[daiso.index('- name: 정상 무변경 관측 metadata 발행'):daiso.index('- name: 수집 시도 진단 보존')]
        self.assertIn('data/daiso_real/.shortlist_observation_claim.json',candidate)
        self.assertIn('data/daiso_real/shortlist_observations.json',candidate)
        self.assertIn('data/agents',candidate)
        self.assertIn('data/publish_deletions.json',candidate)
        self.assertLess(daiso.index('- name: Keep canonical product inputs'),daiso.index('- name: Record actual collector stage receipt'))


if __name__=='__main__': unittest.main()
