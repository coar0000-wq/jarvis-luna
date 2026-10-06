#!/usr/bin/env python3
"""Offline failure/conflict injection. Only temporary local bare Git remotes."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import publish_transaction as pub

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT/'config/publish_policy.json').read_text(encoding='utf-8'))


def dump(root, name, value):
    p = Path(root)/name; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def read(root, name):
    return json.loads((Path(root)/name).read_text(encoding='utf-8'))


class FixtureTransaction(pub.Transaction):
    """Test-only Python override; production CLI has no command injection hooks."""
    validations = None
    def regenerate_and_validate(self, work, baseline, remote_changed, report_dir):
        if self.validations is None: self.validations = []
        source = read(work, 'data/source.json')
        dump(work, 'data/dashboard_runtime.json', {'identities': sorted(r['id'] for r in source['items'])})
        self.validations.append({'remote_changed': bool(remote_changed), 'identities': read(work, 'data/dashboard_runtime.json')['identities']})


class MergeTests(unittest.TestCase):
    def test_candidate_history_exact_bytes_and_shard_contract(self):
        value = b'{"items": {}}\n'
        digest = pub.sha(value)
        prefix = 'data/daiso_real/candidate_pool_history/'
        for suffix in (digest + '.json', digest[:2] + '/' + digest + '.json'):
            name = prefix + suffix
            self.assertEqual(pub.overlay(name, None, value, None, POLICY, {}), value)
            for local, remote in ((None, value), (b' ' + value, value), (value, b' ' + value)):
                with self.assertRaises(pub.PublishError):
                    pub.overlay(name, value, local, remote, POLICY, {})
        for suffix in ('wrong/' + digest + '.json', 'aa/bb/' + digest + '.json', 'zz/' + digest + '.json'):
            with self.assertRaises(pub.PublishError):
                pub.overlay(prefix + suffix, None, value, None, POLICY, {})

    def test_candidate_policy_cannot_authorize_other_source(self):
        before, after = b'{"items":["old"]}', b'{"items":[]}'
        manifest = {'deletions': [{'path': 'data/other.json', 'base_sha256': pub.sha(before),
                    'replacement_sha256': pub.sha(after), 'ids': ['old'], 'reason': 'not valid outside canonical pool',
                    'policy_ref': 'scripts/candidate_pool_history.py'}]}
        self.assertFalse(pub.deletion_authorized('data/other.json', before, ['old'], manifest, replacement=after))

    def test_candidate_observability_history_stays_canonical_protected(self):
        tx=object.__new__(pub.Transaction);tx.policy=POLICY
        before=json.dumps({'fx':{'usd_to_krw':1300},'last_run':{'status':'ok'}}).encode()
        after=json.dumps({'fx':{'usd_to_krw':1300},'last_run':{'status':'no_change'}}).encode()
        tx.delta={'data/daiso_real/collection_status.json':(before,after),
                  'data/health_check_history.jsonl':(b'old\n',b'old\nnew\n')}
        self.assertTrue(tx.candidate_only())

    def test_actual_fx_delta_requires_commerce_not_candidate_only(self):
        tx=object.__new__(pub.Transaction);tx.policy=POLICY
        before=json.dumps({'fx':{'usd_to_krw':1300}}).encode()
        after=json.dumps({'fx':{'usd_to_krw':1400}}).encode()
        tx.delta={'data/daiso_real/collection_status.json':(before,after)}
        self.assertFalse(tx.candidate_only())
        self.assertIn('data/daiso_real/collection_status.json',POLICY['commerce_inputs'])

    def test_distinct_product_id_additions_preserved_and_count_recomputed(self):
        b={'count':1,'products':[{'pd_no':'base','name':'original'}]}
        l=deepcopy(b); r=deepcopy(b)
        l['products'].append({'pd_no':'local','name':'new local'}); l['count']=2
        r['products'].append({'pd_no':'remote','name':'new remote'}); r['count']=2
        actual=pub.merge_json(b,l,r,POLICY)
        self.assertEqual({x['pd_no'] for x in actual['products']},{'base','local','remote'})
        self.assertEqual(actual['count'],3)

    def test_same_identity_competing_evidence_blocks(self):
        b=[{'id':'x','name':'before'}]
        with self.assertRaises(pub.PublishError):
            pub.merge_json(b,[{'id':'x','name':'local'}],[{'id':'x','name':'remote'}],POLICY)

    def test_keyed_accumulative_records_preserve_both(self):
        b={'items':{'base':{'value':1}},'count':1}
        l={'items':dict(b['items'],local={'value':2}),'count':2}
        r={'items':dict(b['items'],remote={'value':3}),'count':2}
        merged=pub.merge_json(b,l,r,POLICY)
        self.assertEqual(set(merged['items']),{'base','local','remote'})
        self.assertEqual(merged['count'],3)

    def test_unknown_scalar_conflict_blocks(self):
        with self.assertRaises(pub.PublishError):
            pub.merge_json({'value':1},{'value':2},{'value':3},POLICY)

    def test_naive_concurrent_timestamp_blocks(self):
        with self.assertRaises(pub.PublishError):
            pub.merge_json({'updated_at':'old'}, {'updated_at':'2026-10-03T01:00:00'}, {'updated_at':'2026-10-03T02:00:00'}, POLICY)

    def test_latest_valid_metadata_timestamp_not_whole_file_overwrite(self):
        b={'items':{},'updated_at':'2026-10-01T00:00:00Z'}
        l={'items':{'a':1},'updated_at':'2026-10-03T00:00:00Z'}
        r={'items':{'b':2},'updated_at':'2026-10-02T00:00:00Z'}
        m=pub.merge_json(b,l,r,POLICY)
        self.assertEqual(m['updated_at'],l['updated_at']); self.assertEqual(set(m['items']),{'a','b'})

    def test_duplicate_identity_list_blocks(self):
        with self.assertRaises(pub.PublishError):
            pub.merge_json([{'id':'x'}],[{'id':'x'},{'id':'x','v':2}],[{'id':'x'},{'id':'z'}],POLICY)

    def test_append_only_scalars_union_without_deletions(self):
        self.assertEqual(pub.merge_json(['x'],['x','a'],['x','b'],POLICY),['x','b','a'])
        with self.assertRaises(pub.PublishError): pub.merge_json(['x'],['a'],['x','b'],POLICY)

    def test_unknown_binary_conflict_blocks(self):
        with self.assertRaises(pub.PublishError): pub.overlay('data/model.bin',b'base',b'local',b'remote',POLICY,{})

    def test_append_only_note_preserves_both_sections(self):
        merged=pub.overlay('obsidian/note.md',b'base\n',b'base\nlocal\n',b'base\nremote\n',POLICY,{})
        self.assertIn(b'local\n',merged); self.assertIn(b'remote\n',merged)

    def test_unexplained_identity_deletion_fails_without_remote_conflict(self):
        b=json.dumps({'items':[{'id':'a'},{'id':'b'}]}).encode()
        l=json.dumps({'items':[{'id':'a'}]}).encode()
        with self.assertRaises(pub.PublishError): pub.overlay('data/source.json',b,l,b,POLICY,{})
        manifest={'deletions':[{'path':'data/source.json','base_sha256':pub.sha(b),'ids':['b'],'reason':'Policy removal reviewed','policy_ref':'config/test-policy'}]}
        self.assertEqual(len(json.loads(pub.overlay('data/source.json',b,l,b,POLICY,manifest))['items']),1)
        manifest['deletions'][0]['base_sha256']='wrong'
        with self.assertRaises(pub.PublishError): pub.overlay('data/source.json',b,l,b,POLICY,manifest)

    def test_file_deletion_requires_exact_hash_and_reason(self):
        manifest={'deletions':[{'path':'data/a.json','base_sha256':pub.sha(b'base'),'delete_file':True,'reason':'Explicit policy removal','policy_ref':'config/test-policy'}]}
        self.assertIsNone(pub.overlay('data/a.json',b'base',None,b'base',POLICY,manifest))
        with self.assertRaises(pub.PublishError): pub.overlay('data/a.json',b'base',None,b'changed',POLICY,manifest)

    def test_invalid_json_is_not_a_successful_no_change(self):
        with self.assertRaises(pub.PublishError): pub.overlay('data/a.json',b'{}',b'<html>blocked',b'{}',POLICY,{})

    def test_unsafe_code_config_absolute_and_traversal_paths_block(self):
        for p in ('scripts/x.py','config/x.json','../data','/data','data/../config','data/*'):
            with self.subTest(p=p),self.assertRaises(pub.PublishError):pub.normalize_paths(p)


class VolatilePolicyTests(unittest.TestCase):
    def encoded(self, value):return json.dumps(value).encode()
    def apply(self, name, baseline, current, remote=None):
        b=self.encoded(baseline); l=self.encoded(current)
        return json.loads(pub.overlay(name,b,l,self.encoded(remote) if remote is not None else b,POLICY,{}))

    def test_daiso_zero_to_candidate_snapshot_schema_change_needs_no_manifest(self):
        success={'status':'ok','execution_id':'old-good','ok':10}
        old={'last_success':success,'last_run':{'status':'no_change','ok':0,'max_items':0,'prefetch_policy':{'open_buckets':['skin'],'legacy_field':True}},'last_attempt':{'status':'no_change','max_items':0,'old_field':True}}
        new={'last_success':success,'last_run':{'status':'candidates_collected','ok':0,'candidates_new':1,'candidate_ids':['123'],'prefetch_policy':{'mode':'candidate_discovery'}},'last_attempt':{'status':'candidates_collected','candidates_new':1}}
        actual=self.apply('data/daiso_real/collection_status.json',old,new)
        self.assertEqual(actual,new);self.assertEqual(actual['last_success'],success)

    def test_candidate_to_no_change_drops_current_run_fields_not_last_success(self):
        good={'status':'ok','execution_id':'operating-good','ok':10}
        cg={'status':'candidates_collected','execution_id':'candidate-good','candidate_ids':['123']}
        old={'last_success':good,'last_candidate_success':cg,'last_run':dict(cg,detail_trace={'price':3000}),'last_attempt':dict(cg,detail_trace={'price':3000})}
        new={'last_success':good,'last_candidate_success':cg,'last_run':{'status':'no_change','candidates_new':0},'last_attempt':{'status':'no_change','candidates_new':0}}
        actual=self.apply('data/daiso_real/collection_status.json',old,new)
        self.assertEqual(actual,new);self.assertEqual(actual['last_candidate_success'],cg)

    def test_crawl_failed_recovery_clears_transient_ids_preserves_history(self):
        old={'visited':['accepted'],'failed':{'retry':{'reason':'timeout'}},'last_run':{'legacy_failure_field':1}}
        new={'visited':['accepted','new'],'failed':{},'last_run':{'status':'success'}}
        actual=self.apply('data/daiso_real/crawl_state.json',old,new)
        self.assertEqual(actual,new)

    def test_crawl_failure_recovery_preserves_other_run_new_failure(self):
        old={'visited':['accepted'],'failed':{'retry':{'reason':'timeout'}}}
        local={'visited':['accepted'],'failed':{}}
        remote={'visited':['accepted','remote'],'failed':{'retry':{'reason':'timeout'},'other':{'reason':'http'}}}
        actual=self.apply('data/daiso_real/crawl_state.json',old,local,remote)
        self.assertEqual(actual['failed'],{'other':{'reason':'http'}})
        self.assertEqual(actual['visited'],['accepted','remote'])

    def test_competing_retry_failure_evidence_not_silently_deleted(self):
        old={'failed':{'retry':{'reason':'timeout'}},'visited':['accepted']}
        local={'failed':{},'visited':['accepted']}
        remote={'failed':{'retry':{'reason':'new_error'}},'visited':['accepted']}
        with self.assertRaises(pub.PublishError):self.apply('data/daiso_real/crawl_state.json',old,local,remote)

    def test_per_run_collector_report_fields_can_change(self):
        old={'execution_id':'old','status':'degraded','results':[{'id':'old-result','error_code':'x'}],'optional_failures':1}
        new={'execution_id':'new','status':'success','results':[{'id':'new-result'}]}
        for name in ('data/agents/core_run_results.json','data/agents/deep_run_results.json','data/agents/release_quality_candidate.json'):
            with self.subTest(name=name):self.assertEqual(self.apply(name,old,new),new)

    def test_two_execution_reports_are_atomic_not_hybrid_merged(self):
        old={'last_attempt':{'execution_id':'old','status':'no_change'}}
        local={'last_attempt':{'execution_id':'local','status':'candidates_collected'}}
        remote={'last_attempt':{'execution_id':'remote','status':'failed'}}
        with self.assertRaises(pub.PublishError):self.apply('data/daiso_real/collection_status.json',old,local,remote)

    def test_last_good_records_cannot_be_dropped_with_volatile_waiver(self):
        old={'last_success':{'execution_id':'good'},'last_attempt':{'old':1}}
        new={'last_attempt':{'status':'no_change'}}
        with self.assertRaises(pub.PublishError):self.apply('data/daiso_real/collection_status.json',old,new)
        old={'last_candidate_success':{'candidate_ids':['accepted']},'last_attempt':{'old':1}}
        new={'last_candidate_success':{'candidate_ids':[]},'last_attempt':{'status':'no_change'}}
        with self.assertRaises(pub.PublishError):self.apply('data/daiso_real/collection_status.json',old,new)

    def test_cumulative_candidates_products_and_visited_removals_still_require_manifest(self):
        cases=[('data/daiso_real/candidate_pool.json',{'items':{'accepted':{'pd_no':'accepted'}}},{'items':{}}),('data/daiso_real/products.json',{'products':[{'pd_no':'accepted'}]},{'products':[]}),('data/daiso_real/crawl_state.json',{'visited':['accepted'],'failed':{}},{'visited':[],'failed':{}}),('data/source.json',{'last_attempt':{'source_field':'keep'}},{'last_attempt':{}})]
        for name,old,new in cases:
            with self.subTest(name=name),self.assertRaises(pub.PublishError):self.apply(name,old,new)

    def test_producer_guard_includes_root_code_and_dependency_locks(self):
        for name in ('main.py','sync_channels.py','product_discovery.py','requirements/verify.lock','requirements/core.lock','requirements.txt','requirements-deep.txt','requirements.lock','constraints.txt','pyproject.toml','uv.lock','poetry.lock','Pipfile.lock','scripts/gate.py','config/policy.json','.github/workflows/core.yml'):
            with self.subTest(name=name):self.assertTrue(pub.producer_changed(name,POLICY))
        for name in ('README.md','docs/requirements-explanation.md','data/requirements.json','obsidian/main.py-notes.md'):
            with self.subTest(name=name):self.assertFalse(pub.producer_changed(name,POLICY))


class GitTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='publish-isolation-',dir=ROOT.parent)
        self.folder=Path(self.tmp.name); self.remote=self.folder/'remote.git'; self.local=self.folder/'local'; self.other=self.folder/'other'
        self.env=patch.dict(os.environ, {'RUNNER_TEMP':str(self.folder),'TEMP':str(self.folder),'TMP':str(self.folder)})
        self.env.start()
        pub.git(self.folder,'init','--bare',str(self.remote))
        pub.git(self.folder,'init','-b','main',str(self.local))
        for k,v in [('user.name','Test'),('user.email','test@example.invalid')]:pub.git(self.local,'config',k,v)
        dump(self.local,'config/publish_policy.json',POLICY)
        dump(self.local,'data/source.json',{'items':[{'id':'base','v':1}],'count':1})
        dump(self.local,'data/dashboard_runtime.json',{'identities':['base']})
        dump(self.local,'data/unrelated.json',{'value':'baseline'})
        pub.git(self.local,'add','config','data');pub.git(self.local,'commit','-m','fixture baseline')
        pub.git(self.local,'remote','add','origin',str(self.remote));pub.git(self.local,'push','-u','origin','main')
        pub.git(self.folder,'clone','-b','main',str(self.remote),str(self.other))
        for k,v in [('user.name','Test'),('user.email','test@example.invalid')]:pub.git(self.other,'config',k,v)
        self.base=pub.git(self.local,'rev-parse','HEAD').stdout.decode().strip()

    def tearDown(self):
        self.env.stop();self.tmp.cleanup()

    def add_local(self):
        s=read(self.local,'data/source.json');s['items'].append({'id':'local','v':2});s['count']=2;dump(self.local,'data/source.json',s)
        dump(self.local,'data/dashboard_runtime.json',{'identities':['STALE-LOCAL']})

    def add_remote(self, name='remote'):
        s=read(self.other,'data/source.json');s['items'].append({'id':name,'v':3});s['count']=len(s['items']);dump(self.other,'data/source.json',s)
        dump(self.other,'data/unrelated.json',{'value':'preserve remote'})
        pub.git(self.other,'add','data');pub.git(self.other,'commit','-m','remote fixture change');pub.git(self.other,'push','origin','main')

    def tip(self):return pub.git(self.remote,'rev-parse','refs/heads/main').stdout.decode().strip()
    def transaction(self, cls=FixtureTransaction, **kwargs):return cls(self.local,'data','fixture publication',**kwargs)

    def test_distinct_products_and_unrelated_remote_changes_preserved(self):
        self.add_local();self.add_remote();tx=self.transaction();result=tx.run()
        self.assertEqual(result['status'],'published')
        source=json.loads(pub.at_ref(self.remote,'main','data/source.json'))
        self.assertEqual({x['id'] for x in source['items']},{'base','local','remote'})
        runtime=json.loads(pub.at_ref(self.remote,'main','data/dashboard_runtime.json'))
        self.assertEqual(runtime['identities'],['base','local','remote'])
        self.assertEqual(json.loads(pub.at_ref(self.remote,'main','data/unrelated.json'))['value'],'preserve remote')
        self.assertEqual(pub.git(self.local,'rev-parse','HEAD').stdout.decode().strip(),self.base)
        self.assertIn('STALE-LOCAL',(self.local/'data/dashboard_runtime.json').read_text())

    def test_dry_run_never_pushes_or_changes_callers_dirty_tree(self):
        self.add_local();before=self.tip();bytes_before=(self.local/'data/source.json').read_bytes()
        tx=self.transaction(dry_run=True);self.assertEqual(tx.run()['status'],'dry_run_validated')
        self.assertEqual(self.tip(),before);self.assertEqual((self.local/'data/source.json').read_bytes(),bytes_before)

    def test_remote_code_or_policy_change_blocks_without_overwrite(self):
        self.add_local();(self.other/'scripts').mkdir();(self.other/'scripts/new.py').write_text('safe new code')
        pub.git(self.other,'add','scripts');pub.git(self.other,'commit','-m','code changed');pub.git(self.other,'push','origin','main')
        before=self.tip()
        with self.assertRaises(pub.PublishError):self.transaction().run()
        self.assertEqual(self.tip(),before)

    def test_root_python_and_requirements_change_blocks_without_overwrite(self):
        self.add_local()
        for name in ('root_producer.py','requirements/profile.lock','requirements.txt'):
            with self.subTest(name=name):
                p=self.other/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('new producer or locked dependency')
                pub.git(self.other,'add','--',name);pub.git(self.other,'commit','-m','producer/dependency changed');pub.git(self.other,'push','origin','main')
                before=self.tip()
                with self.assertRaises(pub.PublishError):self.transaction().run()
                self.assertEqual(self.tip(),before)

    def test_audit_false_cannot_waive_candidate_and_final_quality(self):
        dump(self.local,'data/daiso_real/candidate_pool.json',{'schema_version':1,'items':{}})
        tx=pub.Transaction(self.local,'data/daiso_real/candidate_pool.json','test',regenerate_dashboard=False,audit=False)
        folder=self.folder/'quality-check';folder.mkdir()
        with patch.object(tx,'command') as commands:
            tx.regenerate_and_validate(self.other,self.local,None,folder)
        scripts=[call.args[1] for call in commands.call_args_list]
        quality=[args for args in scripts if args[0]=='scripts/check_release_quality.py']
        self.assertEqual([args[args.index('--phase')+1] for args in quality],['candidate','final'])
        self.assertFalse(any(args[0]=='scripts/audit_team_reports.py' for args in scripts))
        self.assertTrue(any(args[0]=='scripts/generate_dashboard_runtime.py' for args in scripts))

    def test_same_id_competing_product_evidence_blocks_push(self):
        dump(self.local,'data/source.json',{'items':[{'id':'base','v':2}],'count':1})
        dump(self.other,'data/source.json',{'items':[{'id':'base','v':3}],'count':1})
        pub.git(self.other,'add','data');pub.git(self.other,'commit','-m','same id remote');pub.git(self.other,'push','origin','main');before=self.tip()
        with self.assertRaises(pub.PublishError):self.transaction().run()
        self.assertEqual(self.tip(),before)

    def test_quality_failure_preserves_last_good_remote(self):
        class BadQuality(FixtureTransaction):
            def regenerate_and_validate(self,*args):raise pub.PublishError('injected quality failure')
        self.add_local();before=self.tip()
        with self.assertRaises(pub.PublishError):self.transaction(BadQuality).run()
        self.assertEqual(self.tip(),before)

    def test_push_rejection_reapplies_immutable_delta_and_revalidates_latest(self):
        outer=self
        class Race(FixtureTransaction):
            def push(self,work):
                if len(self.attempts)==1:outer.add_remote('raced');return False
                return super().push(work)
        self.add_local();tx=self.transaction(Race);result=tx.run()
        self.assertEqual(result['status'],'published');self.assertEqual(len(tx.validations),2)
        self.assertEqual(tx.validations[1]['identities'],['base','local','raced'])
        self.assertTrue(tx.validations[1]['remote_changed'])

    def test_retry_limit_failure_explicit_and_last_good_preserved(self):
        class AlwaysRejected(FixtureTransaction):
            def push(self,work):return False
        self.add_local();before=self.tip();tx=self.transaction(AlwaysRejected,max_attempts=2)
        with self.assertRaises(pub.PublishError):tx.run()
        self.assertEqual(len(tx.validations),2);self.assertEqual(self.tip(),before)

    def test_missing_required_path_fails_not_silently_skipped(self):
        with self.assertRaises(pub.PublishError):FixtureTransaction(self.local,'data/not-created.json','test')

    def test_staging_failure_does_not_push(self):
        class BadStage(FixtureTransaction):
            def stage(self,work):raise pub.PublishError('injected git add failure')
        self.add_local();before=self.tip()
        with self.assertRaises(pub.PublishError):self.transaction(BadStage).run()
        self.assertEqual(self.tip(),before)

    def test_zero_delta_is_no_change_without_push(self):
        before=self.tip();self.assertEqual(self.transaction().run()['status'],'no_change');self.assertEqual(self.tip(),before)


if __name__=='__main__':unittest.main(verbosity=2)
