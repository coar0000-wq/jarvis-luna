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
    def test_disjoint_manifest_updates_preserve_exact_records_and_removals(self):
        a = {'path': 'data/a.json', 'base_sha256': 'old', 'reason': 'old'}
        newer = dict(a, base_sha256='new')
        c = {'path': 'data/c.json', 'base_sha256': 'c', 'reason': 'replacement'}
        def raw(records):
            return json.dumps({'schema_version': 1, 'deletions': records}).encode()
        result = pub.overlay('data/publish_deletions.json', raw([a]), raw([newer]), raw([a,c]), POLICY, {})
        self.assertEqual(json.loads(result)['deletions'], [newer,c])
        result = pub.overlay('data/publish_deletions.json', raw([a]), raw([]), raw([a,c]), POLICY, {})
        self.assertEqual(json.loads(result)['deletions'], [c])
        with self.assertRaises(pub.PublishError):
            pub.overlay('data/publish_deletions.json', raw([a]), raw([newer]), raw([dict(a,reason='revoked')]), POLICY, {})

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

    def test_shared_quality_report_takes_publishing_execution_whole(self):
        # 2026-10-17: Core 발행 동안 대기한 Deep 이 같은 품질 보고서 때문에 발행에 실패했다.
        old={'execution_id':'old','status':'warning','checks':[{'id':'a','ok':False}]}
        local={'execution_id':'deep','status':'passed','checks':[{'id':'a','ok':True}]}
        remote={'execution_id':'core','status':'warning','checks':[{'id':'b','ok':False}],'extra':1}
        for name in ('data/agents/release_quality_candidate.json','data/agents/release_quality_final.json'):
            with self.subTest(name=name):self.assertEqual(self.apply(name,old,local,remote),local)
        with self.assertRaises(pub.PublishError):
            self.apply('data/agents/core_run_results.json',old,local,remote)

    def test_cumulative_history_keeps_remote_for_regeneration(self):
        # 2026-10-18: 두 실행이 각자 덧붙인 누적 이력은 합치지 않는다(합계 중복). 원격을 두고 재생성이 1회 덧붙인다.
        old={'totals':{'a':1},'last_snapshot':{'a':1,'recorded_at':'t0'},'runs':[{'at':'t0'}]}
        local={'totals':{'a':2},'last_snapshot':{'a':2,'recorded_at':'t1'},'runs':[{'at':'t0'},{'at':'t1'}]}
        remote={'totals':{'a':3},'last_snapshot':{'a':3,'recorded_at':'t2'},'runs':[{'at':'t0'},{'at':'t2'}]}
        self.assertEqual(self.apply('data/knowledge/cumulative_history.json',old,local,remote),remote)

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

    def test_unverified_operations_delta_rejected_before_overlay(self):
        for name in ('data/operations/state.json', 'data/operations/reports/private/board/evidence.bin'):
            with self.subTest(name=name), patch.dict(os.environ, {'GITHUB_ACTIONS':'true', 'JARVIS_OPERATIONS_CONTINUITY':''}):
                p=self.local/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'forbidden')
                with patch.object(pub, 'overlay') as overlay, self.assertRaises(pub.PublishError):
                    self.transaction().run()
                overlay.assert_not_called()
                p.unlink()

    def test_generated_extra_operations_delta_rejected_before_any_stage(self):
        self.add_local()
        with patch.dict(os.environ, {'GITHUB_ACTIONS':'true', 'JARVIS_OPERATIONS_CONTINUITY':''}):
            tx=self.transaction()
        dump(self.other,'data/operations/reports/private/board/new.json',{'bad':True})
        # generated_extra permits this prefix for full publication, not this profile.
        with patch.object(pub, 'git', wraps=pub.git) as calls, self.assertRaises(pub.PublishError):
            tx.stage(self.other)
        self.assertFalse(any('add' in c.args for c in calls.call_args_list))

    def test_non_operations_profile_preserves_all_fetched_remote_bytes(self):
        names={'data/operations/state.bin':b'\x00\xffremote\r\n',
               'data/operations/reports/private/board/latest.json':b'{ "unmodified": true }\n'}
        for name,value in names.items():
            p=self.other/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)
        pub.git(self.other,'add','data');pub.git(self.other,'commit','-m','remote operations fixture');pub.git(self.other,'push','origin','main')
        self.add_local()
        with patch.dict(os.environ, {'GITHUB_ACTIONS':'true', 'JARVIS_OPERATIONS_CONTINUITY':''}):
            result=self.transaction().run()
        self.assertEqual(result['publication_profile'],'non_operations')
        self.assertEqual(result['operations_producer_status'],'excluded_by_profile')
        self.assertNotIn(['scripts/run_jarvis_operations.py'],result['declared_runtime_commands'])
        self.assertEqual(result['executed_commands'],[])  # fixture override is not execution evidence
        for name,value in names.items():self.assertEqual(pub.at_ref(self.remote,'main',name),value)

    def test_non_operations_generator_mutation_fails_closed(self):
        class BadGenerator(FixtureTransaction):
            def regenerate_and_validate(self,work,*args):
                dump(work,'data/operations/reports/private/board/extra.json',{'bad':True})
        self.add_local();before=self.tip()
        with patch.dict(os.environ, {'GITHUB_ACTIONS':'true', 'JARVIS_OPERATIONS_CONTINUITY':''}):
            with self.assertRaises(pub.PublishError):self.transaction(BadGenerator).run()
        self.assertEqual(self.tip(),before)

    def test_profile_runtime_dispatch_and_actual_producer_status(self):
        self.add_local()
        for env,profile,expected in (({'GITHUB_ACTIONS':'true','JARVIS_OPERATIONS_CONTINUITY':''},'non_operations',POLICY['non_operations_runtime_commands']),
                                     ({'GITHUB_ACTIONS':'true','JARVIS_OPERATIONS_CONTINUITY':'verified'},'full',POLICY['runtime_commands']),
                                     ({'GITHUB_ACTIONS':'false','JARVIS_OPERATIONS_CONTINUITY':''},'full',POLICY['runtime_commands'])):
            with self.subTest(profile=profile,env=env), patch.dict(os.environ,env):
                tx=pub.Transaction(self.local,'data','fixture',audit=False)
                reports=self.folder/'reports';reports.mkdir(exist_ok=True)
                with patch.object(pub.subprocess,'run') as run:
                    run.return_value.returncode=0
                    tx.regenerate_and_validate(self.other,self.local,None,reports)
                self.assertEqual(tx.executed_commands[:len(expected)],expected)
                self.assertEqual(tx.result()['operations_producer_status'],'executed' if profile=='full' else 'excluded_by_profile')
                self.assertEqual(tx.executed_commands[-2:],[['scripts/check_release_quality.py','--phase',phase,'--root',str(self.other),'--baseline',str(self.local),'--report',str(reports/f'{phase}.json')] for phase in ('candidate','final')])

    def test_operations_command_never_silently_skips(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS':'true', 'JARVIS_OPERATIONS_CONTINUITY':''}):
            tx=self.transaction()
            with patch.object(pub.subprocess,'run') as run:
                run.return_value.returncode=17
                with self.assertRaises(pub.PublishError):tx.command(self.other,['scripts/run_jarvis_operations.py'])
            run.assert_called_once()
            self.assertEqual(tx.executed_commands,[])

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


class RestrictedTransactionTests(unittest.TestCase):
    """Real local Git transaction; deterministic authenticated-engine boundary fixture.

    The engine's transport/decision adversaries are exercised in its own suite;
    these tests trap every generator and exercise final-tree isolation/races.
    """
    setUpGit = GitTransactionTests.setUp
    tearDown = GitTransactionTests.tearDown
    tip = GitTransactionTests.tip
    add_remote = GitTransactionTests.add_remote

    def setUp(self):
        import sys
        from types import SimpleNamespace
        self.setUpGit()
        self.engine = SimpleNamespace(protected_inventory=self.inventory,
            assert_protected_unchanged=self.unchanged,
            restricted_output_paths=self.outputs,
            validate_review_bindings=self.validate,
            validate_restricted_report=self.validate_sealed,
            authenticate_evidence=self.authenticate,
            validate_publication_freshness=self.freshness,
            validate_history_member=lambda root, path: None,
            reanalyze_for_publication=self.reanalyze,
            write_review=self.write_review)
        engine_patch = patch.dict(sys.modules, {'continuity_reconciliation': self.engine})
        engine_patch.start(); self.addCleanup(engine_patch.stop)
        self.reanalyses = []
        self.authentication_calls = []
        self.freshness_calls = []
        self.proofs = {}
        self.new_gap = False
        self.review = self.make_review(self.local)
        self.write_review(self.local, self.review)
        self.collector = self.folder / 'collector.json'
        self.save_aggregate()

    def inventory(self, root):
        root = Path(root)
        return {p.relative_to(root).as_posix(): pub.sha(p.read_bytes())
                for p in (root / 'data').rglob('*') if p.is_file()
                and p.relative_to(root).as_posix() != pub.RESTRICTED_POLICY['review_path']
                and not p.relative_to(root).as_posix().startswith(pub.RESTRICTED_POLICY['history_prefix'])}

    def unchanged(self, before, after):
        if before != after: raise ValueError('protected full inventory changed')

    def outputs(self, review):
        return [pub.RESTRICTED_POLICY['review_path'],
                pub.RESTRICTED_POLICY['history_prefix'] + review['analysis_id'] + '.json']

    def make_review(self, root):
        inventory = self.inventory(root)
        digest = pub.sha(json.dumps(inventory, sort_keys=True).encode())
        return {'mode': 'restricted_gap', 'continuity': 'unresolved_gap',
            'production_recovered': False, 'operations_execution_verified': False,
            'old_run_provider_calls': None, 'old_run_provider_cost': None,
            'execution_id': 'fixture:1', 'run_id': 1, 'run_attempt': 1,
            'actor': {'login': 'fixture', 'id': 1}, 'triggering_actor': {'login': 'fixture', 'id': 1},
            'decision_digest': 'd' * 64,
            'gap_ids': ['39893237129:1'], 'input_commit': pub.git(root, 'rev-parse', 'HEAD').stdout.decode().strip(),
            'input_digests': inventory, 'code_contract_digest': 'c' * 64,
            'analysis_id': pub.sha(('decision-code-' + digest).encode()),
            'protected_inventory_digest': digest}

    def validate(self, root, report, *, execution_id, before_inventory=None, now=None):
        if report != self.make_review(root) or execution_id != 'fixture:1':
            raise ValueError('fixture authenticated input/decision/run mismatch')
        if before_inventory is not None: self.unchanged(before_inventory, self.inventory(root))
        return {}

    def reanalyze(self, root, prior_report, *, input_commit, execution_id, evidence=None):
        if evidence not in self.proofs: raise ValueError('sealed in-process proof required')
        fresh = self.make_review(root)
        if fresh['input_commit'] != input_commit or execution_id != 'fixture:1':
            raise ValueError('latest-main identity mismatch')
        self.reanalyses.append(fresh)
        return fresh

    def authenticate(self, root, *, execution_id, purpose):
        self.assertEqual(purpose, 'publication')
        self.assertEqual(execution_id, 'fixture:1')
        token = object()
        self.proofs[token] = self.make_review(root)
        self.authentication_calls.append(token)
        return token

    def validate_sealed(self, report, *, root, evidence, before_inventory=None, now=None):
        if evidence not in self.proofs or report != self.proofs[evidence]:
            raise ValueError('invalid sealed proof')
        return self.validate(root, report, execution_id=report['execution_id'], before_inventory=before_inventory)

    def freshness(self, root, report, *, evidence, execution_id):
        if evidence not in self.proofs or self.new_gap:
            raise ValueError('new gap or invalid proof')
        if report != self.proofs[evidence] or self.inventory(root) != report['input_digests']:
            raise ValueError('changed final tree')
        if self.tip() != report['input_commit'] or execution_id != 'fixture:1':
            raise ValueError('main/current attempt changed before push')
        self.freshness_calls.append(evidence)
        return {'metadata_requests': 4, 'inventory_passes': 1}

    def write_review(self, root, review):
        archive = {k: v for k, v in review.items() if k not in ('execution_id', 'input_commit')}
        archive_path = self.outputs(review)[1]
        existing = Path(root) / archive_path
        if existing.exists() and read(root, archive_path) != archive:
            raise ValueError('immutable review history conflict')
        dump(root, archive_path, archive)
        dump(root, self.outputs(review)[0], review)

    def save_aggregate(self):
        from collector_result import restricted_aggregate
        self.collector.write_text(json.dumps(restricted_aggregate(self.review, root=self.local, identity='fixture:1')))

    def transaction(self, cls=pub.Transaction, **kwargs):
        return cls(self.local, pub.RESTRICTED_POLICY['review_path'] + ' ' +
                   pub.RESTRICTED_POLICY['history_prefix'], 'restricted fixture',
                   collector_report=self.collector, execution_id='fixture:1', **kwargs)

    def test_dry_run_is_restricted_and_never_mutates_caller_or_remote(self):
        before = self.tip(); inventory = self.inventory(self.local)
        with patch('socket.create_connection', side_effect=AssertionError('provider trap')), \
             patch('urllib.request.urlopen', side_effect=AssertionError('provider trap')), \
             patch.object(pub.Transaction, 'command', side_effect=AssertionError('action dispatch trap')):
            result = self.transaction(dry_run=True).run()
        self.assertEqual(result['status'], 'restricted_dry_run_validated')
        self.assertEqual(result['publication_profile'], 'restricted_gap')
        self.assertEqual(result['executed_commands'], [])
        self.assertEqual(result['operations_producer_status'], 'quarantined_not_attempted')
        self.assertFalse(result['production_recovered'])
        self.assertFalse(result['operations_execution_verified'])
        self.assertIsNone(result['old_run_provider_calls'])
        self.assertEqual(self.tip(), before)
        self.assertEqual(self.inventory(self.local), inventory)

    def test_data_only_main_advance_is_reanalyzed_without_stale_overlay(self):
        old_analysis = self.review['analysis_id']
        self.add_remote()
        protected = self.inventory(self.other)
        result = self.transaction().run()
        self.assertEqual(result['status'], 'restricted_analysis_published')
        fresh = json.loads(pub.at_ref(self.remote, 'main', pub.RESTRICTED_POLICY['review_path']))
        self.assertNotEqual(fresh['analysis_id'], old_analysis)
        self.assertEqual(fresh['input_digests'], protected)
        for name, digest in protected.items(): self.assertEqual(pub.sha(pub.at_ref(self.remote, 'main', name)), digest)
        changes = pub.git(self.remote, 'diff', '--name-only', 'main^', 'main').stdout.decode().splitlines()
        self.assertTrue(all(n in set(self.outputs(fresh)) | set(self.outputs(self.review)) for n in changes))
        self.assertEqual(fresh['execution_id'], 'fixture:1')

    def test_protected_nonce_stop_budget_and_old_receipts_preserved_exactly(self):
        artifacts = {'data/operations/receipts.bin': b'2007 original receipts\x00\xff',
            'data/operations/nonces.json': b'{ "nonce": "must-not-replay" }\n',
            'data/agents/source_procedures/checkpoint.json': b'{"STOP":true,"calls":17}',
            'data/typesafe_shared_state.json': b'{"remaining":0,"unknown_spend":null}'}
        for name, raw in artifacts.items():
            p = self.other / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
        pub.git(self.other, 'add', 'data'); pub.git(self.other, 'commit', '-m', 'protected state')
        pub.git(self.other, 'push', 'origin', 'main')
        self.transaction().run()
        for name, raw in artifacts.items(): self.assertEqual(pub.at_ref(self.remote, 'main', name), raw)

    def test_unknown_caller_path_blocked_even_outside_requested_paths(self):
        for name in ('data/unknown.json', 'data/operations/state.json', 'data/dashboard_runtime.json'):
            with self.subTest(name=name):
                path = self.local / name; old = path.read_bytes() if path.exists() else None
                dump(self.local, name, {'forbidden': True})
                self.review = self.make_review(self.local); self.write_review(self.local, self.review); self.save_aggregate()
                with self.assertRaises(pub.PublishError): self.transaction()
                if old is None: path.unlink()
                else: path.write_bytes(old)

    def test_unknown_mode_and_relabelled_restricted_report_block(self):
        doc = json.loads(self.collector.read_text())
        for mode in ('unknown', 'normal', None):
            changed = dict(doc, mode=mode, status='success')
            self.collector.write_text(json.dumps(changed))
            with self.assertRaises(pub.PublishError): self.transaction()

    def test_tampered_aggregate_binding_and_missing_stages_block(self):
        original = json.loads(self.collector.read_text())
        for field, value in [('decision_digest', 'x' * 64), ('input_commit', 'x' * 40),
                             ('restricted_stages', []), ('old_run_provider_cost', 0)]:
            self.collector.write_text(json.dumps(dict(original, **{field: value})))
            with self.assertRaises(pub.PublishError): self.transaction()

    def test_fixed_policy_and_broad_paths_cannot_expand_scope(self):
        with self.assertRaises(pub.PublishError):
            pub.Transaction(self.local, 'data', 'bad scope', collector_report=self.collector, execution_id='fixture:1')
        policy = deepcopy(POLICY); policy['restricted_gap']['runtime_commands'] = [['scripts/run_jarvis_operations.py']]
        dump(self.local, 'config/publish_policy.json', policy)
        with self.assertRaises(pub.PublishError): self.transaction()

    def test_unknown_new_history_and_protected_generator_mutation_fail(self):
        original = self.engine.write_review
        for name in ('data/agents/continuity_review_history/' + '0' * 64 + '.json',
                     'data/operations/new_action.json', 'data/typesafe_shared_state.json'):
            def bad_write(root, review):
                original(root, review); dump(root, name, {'forbidden': True})
            before = self.tip()
            with patch.object(self.engine, 'write_review', side_effect=bad_write), self.assertRaises(pub.PublishError):
                self.transaction().run()
            self.assertEqual(self.tip(), before)

    def test_concurrent_code_changes_block_before_reanalysis(self):
        p = self.other / 'scripts/new.py'; p.parent.mkdir(); p.write_text('print("changed")')
        pub.git(self.other, 'add', 'scripts'); pub.git(self.other, 'commit', '-m', 'new code')
        pub.git(self.other, 'push', 'origin', 'main')
        before = self.tip()
        with self.assertRaises(pub.PublishError): self.transaction().run()
        self.assertEqual(self.tip(), before); self.assertEqual(self.reanalyses, [])

    def test_concurrent_immutable_history_conflict_is_not_overwritten(self):
        name = self.outputs(self.review)[1]; dump(self.other, name, {'tampered': True})
        pub.git(self.other, 'add', 'data'); pub.git(self.other, 'commit', '-m', 'history collision')
        pub.git(self.other, 'push', 'origin', 'main'); before = self.tip()
        with self.assertRaises(pub.PublishError): self.transaction().run()
        self.assertEqual(self.tip(), before)

    def test_push_race_reauthenticates_and_reanalyzes_latest(self):
        outer = self
        class Race(pub.Transaction):
            def push(self, work):
                if len(self.attempts) == 1:
                    outer.add_remote('raced'); return False
                return super().push(work)
        result = self.transaction(Race).run()
        self.assertEqual(len(result['attempts']), 2)
        self.assertEqual(len(self.reanalyses), 2)
        self.assertNotEqual(self.reanalyses[0]['analysis_id'], self.reanalyses[1]['analysis_id'])
        self.assertEqual(result['status'], 'restricted_analysis_published')

    def test_retention_records_actual_final_reanalysis_not_stale_caller_review(self):
        self.add_remote()
        tx = self.transaction(retain_restricted_evidence=True)
        result = tx.run()
        self.assertNotIn('retention_error', result)
        metadata = read(self.folder, 'restricted/publication-result.json')
        retained = read(self.folder, 'restricted/published-review.json')
        self.assertEqual(retained, self.reanalyses[-1])
        self.assertNotEqual(retained['analysis_id'], self.review['analysis_id'])
        self.assertTrue(metadata['remote_publication_verified'])
        self.assertEqual(metadata['commit_sha'], self.tip())
        self.assertEqual(metadata['review_sha256'], pub.sha((self.folder / 'restricted/published-review.json').read_bytes()))

    def test_dryrun_retention_never_claims_remote_publication(self):
        tx = self.transaction(dry_run=True)
        metadata = tx.export_restricted_evidence(tx.run())
        self.assertFalse(metadata['remote_publication_verified'])
        self.assertEqual(metadata['review_file'], 'validated-review.json')
        self.assertFalse((self.folder / 'restricted/published-review.json').exists())
        with patch.dict(os.environ, {'RUNNER_TEMP': str(self.local)}), self.assertRaises(pub.PublishError):
            tx.export_restricted_evidence(tx.result(status='dry_run_validated'))

    def restricted_cli(self, *options):
        import contextlib
        import io
        output = io.StringIO()
        args = ['publish_transaction.py', '--paths', pub.RESTRICTED_POLICY['review_path'] + ' ' +
                pub.RESTRICTED_POLICY['history_prefix'], '--message', 'local CLI fixture',
                '--collector-report', str(self.collector), '--execution-id', 'fixture:1', *options]
        with patch.object(pub.Path, 'cwd', return_value=self.local), \
             patch.object(pub.sys, 'argv', args), contextlib.redirect_stdout(output):
            code = pub.main()
        text = output.getvalue()
        line = next(line for line in text.splitlines() if line.startswith('RESTRICTED_'))
        label, raw = line.split(' ', 1)
        return code, label, json.loads(raw), text

    def test_cli_retention_failure_keeps_published_commit_and_fails_job(self):
        before = self.tip()
        with patch.object(pub.Transaction, 'export_restricted_evidence', side_effect=OSError('private failure detail')) as export:
            code, label, result, text = self.restricted_cli()
        self.assertEqual(code, 1)
        self.assertEqual(label, 'RESTRICTED_ANALYSIS_PUBLISHED')
        self.assertEqual(result['status'], 'restricted_analysis_published')
        self.assertEqual(result['commit_sha'], self.tip())
        self.assertNotEqual(self.tip(), before)
        self.assertEqual(result['retention_error'], 'OSError')
        self.assertIn('Transaction already ended with status restricted_analysis_published', text)
        self.assertNotIn('Publication blocked', text)
        self.assertNotIn('private failure detail', text)
        self.assertNotIn('PUBLISH_TRANSACTION_OK', text)
        export.assert_called_once()

    def test_cli_dryrun_retains_validation_without_publication_claim(self):
        before = self.tip()
        code, label, result, unused_text = self.restricted_cli('--dry-run')
        self.assertEqual(code, 0)
        self.assertEqual(label, 'RESTRICTED_DRY_RUN_VALIDATED')
        self.assertEqual(result['status'], 'restricted_dry_run_validated')
        self.assertNotIn('retention_error', result)
        self.assertEqual(self.tip(), before)
        metadata = read(self.folder, 'restricted/publication-result.json')
        self.assertFalse(metadata['remote_publication_verified'])
        self.assertEqual(metadata['review_file'], 'validated-review.json')
        self.assertFalse((self.folder / 'restricted/published-review.json').exists())

    def test_retention_optin_does_not_change_default_or_normal_result(self):
        restricted = self.transaction(dry_run=True)
        normal = pub.Transaction(self.other, 'data', 'normal unchanged', retain_restricted_evidence=True)
        with patch.object(pub.Transaction, 'export_restricted_evidence', side_effect=AssertionError('unexpected retention')) as export:
            self.assertEqual(restricted.run()['status'], 'restricted_dry_run_validated')
            self.assertEqual(normal.run()['status'], 'no_change')
        export.assert_not_called()

    def test_one_authentication_per_attempt_and_one_freshness_scan(self):
        tx = self.transaction(dry_run=True)
        self.assertEqual(self.authentication_calls, [])
        result = tx.run()
        self.assertEqual(len(self.authentication_calls), 1)
        self.assertEqual(self.freshness_calls, self.authentication_calls)
        self.assertEqual(result['publication_freshness_checks'], [{'metadata_requests': 4, 'inventory_passes': 1}])

    def test_restricted_retry_cap_two_preserves_normal_default_three(self):
        class Rejected(pub.Transaction):
            def push(self, work): return False
        tx = self.transaction(Rejected, max_attempts=3)
        self.assertEqual(tx.max_attempts, 2)
        before = self.tip()
        with self.assertRaisesRegex(pub.PublishError, 'restricted push rejected after 2'):
            tx.run()
        self.assertEqual(len(self.authentication_calls), 2)
        self.assertEqual(len(self.freshness_calls), 2)
        self.assertEqual(self.tip(), before)
        normal = pub.Transaction(self.local, 'data', 'normal default')
        self.assertEqual(normal.max_attempts, 3)

    def test_new_gap_between_final_quality_and_push_blocks(self):
        outer = self
        class LateGap(pub.Transaction):
            def stage(self, work):
                changed = super().stage(work)
                outer.new_gap = True
                return changed
        before = self.tip(); tx = self.transaction(LateGap)
        with patch.object(tx, 'push') as push, self.assertRaisesRegex(pub.PublishError, 'freshness'):
            tx.run()
        push.assert_not_called()
        self.assertEqual(self.tip(), before)

    def test_main_advance_immediately_before_push_blocks_stale_publication(self):
        outer = self
        class LateMain(pub.Transaction):
            def stage(self, work):
                changed = super().stage(work)
                outer.add_remote('after-quality')
                return changed
        tx = self.transaction(LateMain)
        with patch.object(tx, 'push') as push, self.assertRaisesRegex(pub.PublishError, 'freshness'):
            tx.run()
        push.assert_not_called()
        self.assertIn(b'after-quality', pub.at_ref(self.remote, 'main', 'data/source.json'))
        self.assertIsNone(pub.at_ref(self.remote, 'main', pub.RESTRICTED_POLICY['review_path']))

    def test_initial_or_final_rate_budget_failure_never_pushes(self):
        for method in ('authenticate_evidence', 'validate_publication_freshness'):
            with self.subTest(method=method), patch.object(self.engine, method, side_effect=ValueError('rate reserve insufficient')):
                tx = self.transaction()
                before = self.tip()
                with patch.object(tx, 'push') as push, self.assertRaises(pub.PublishError): tx.run()
                push.assert_not_called()
                self.assertEqual(self.tip(), before)

    def test_subprocess_provider_and_operations_dispatch_are_forbidden(self):
        tx = self.transaction()
        for args in POLICY['runtime_commands'] + POLICY['commerce_commands'] + [['scripts/fetch.py']]:
            with patch.object(pub.subprocess, 'run') as run, self.assertRaises(pub.PublishError):
                tx.command(self.local, args)
            run.assert_not_called()


class AuthenticatedRestrictedPublisherTests(unittest.TestCase):
    """Complete production publisher/engine with only GitHub transport substituted."""
    def setUp(self):
        import continuity_reconciliation as continuity
        import check_release_quality as quality
        from test_continuity_reconciliation import RestrictedFixture, NOW
        from datetime import datetime
        self.continuity = continuity
        self.now = NOW
        real_time = continuity._time
        clock_patch = patch.object(continuity, '_time', side_effect=lambda value=None: NOW if value is None else real_time(value))
        clock_patch.start(); self.addCleanup(clock_patch.stop)
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None): return NOW
        quality_clock = patch.object(quality, 'datetime', FixedDateTime)
        quality_clock.start(); self.addCleanup(quality_clock.stop)
        self.fixture = RestrictedFixture()
        self.addCleanup(self.fixture.__exit__, None, None, None)
        f = self.fixture
        f.git('branch', '-M', 'main')
        # Bind the real checked-in policy before approval's final fixture commit.
        f.write('config/publish_policy.json', POLICY)
        f.decision['code_contract_digest'] = continuity.code_contract_digest(f.root)
        f.write(continuity.DECISION_PATH, f.decision)
        f.git('add', '.')
        f.git('commit', '-qm', 'bind real publisher policy')
        f.main_commit = f.git('rev-parse', 'HEAD').strip()
        f.current['head_sha'] = f.main_commit
        self.folder_context = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder_context.cleanup)
        self.folder = Path(self.folder_context.name)
        self.remote = self.folder / 'remote.git'
        pub.git(self.folder, 'init', '--bare', str(self.remote))
        f.git('remote', 'add', 'origin', str(self.remote))
        f.git('push', '-u', 'origin', 'main')
        real_authenticate = continuity.authenticate_evidence
        def authenticated(root, **kwargs):
            kwargs['transport'] = f.transport
            kwargs['log_transport'] = f.log_transport
            return real_authenticate(root, **kwargs)
        auth_patch = patch.object(continuity, 'authenticate_evidence', side_effect=authenticated)
        self.auth_mock = auth_patch.start(); self.addCleanup(auth_patch.stop)
        real_freshness = continuity.validate_publication_freshness
        def freshness(root, report, **kwargs):
            kwargs['transport'] = f.transport
            return real_freshness(root, report, **kwargs)
        freshness_patch = patch.object(continuity, 'validate_publication_freshness', side_effect=freshness)
        self.freshness_mock = freshness_patch.start(); self.addCleanup(freshness_patch.stop)
        f.evidence = authenticated(f.root, execution_id=f.identity, now=NOW)
        self.review = f.report(write=True)
        from collector_result import restricted_aggregate
        self.collector = self.folder / 'collector.json'
        self.collector.write_text(json.dumps(restricted_aggregate(self.review, root=f.root, identity=f.identity)))

    def transaction(self, cls=pub.Transaction):
        c, f = self.continuity, self.fixture
        return cls(f.root, c.REPORT_PATH + ' ' + c.HISTORY_DIR, 'authenticated offline dryrun',
                   dry_run=True, collector_report=self.collector, execution_id=f.identity)

    def test_full_publisher_dryrun_revalidates_real_engine_and_exact_tree(self):
        c, f = self.continuity, self.fixture
        before = c.protected_inventory(f.root)
        initial_tip = pub.git(self.remote, 'rev-parse', 'main').stdout
        captured = {}
        class InspectedTransaction(pub.Transaction):
            def stage(self, work):
                result = super().stage(work)
                captured['protected'] = c.protected_inventory(work)
                captured['paths'] = pub.git(work, 'diff', '--cached', '--name-only').stdout.decode().splitlines()
                captured['review'] = read(work, c.REPORT_PATH)
                return result
        with patch('socket.create_connection', side_effect=AssertionError('network forbidden')), \
             patch.object(pub.Transaction, 'command', side_effect=AssertionError('provider/action forbidden')):
            result = self.transaction(InspectedTransaction).run()
        self.assertEqual(result['status'], 'restricted_dry_run_validated')
        self.assertEqual(captured['protected'], before)
        self.assertEqual(set(captured['paths']), set(c.restricted_output_paths(captured['review'])))
        self.assertEqual(pub.git(self.remote, 'rev-parse', 'main').stdout, initial_tip)
        self.assertEqual(c.protected_inventory(f.root), before)
        self.assertEqual(captured['review']['gap_ids'], ['39893237129:1'])
        self.assertIsNone(captured['review']['old_run_provider_cost'])
        self.assertEqual(self.auth_mock.call_count, 1)
        self.assertEqual(self.freshness_mock.call_count, 1)
        self.assertEqual(len(result['publication_freshness_checks']), 1)

    def test_complete_paginated_discovery_is_reused_without_repeated_api_passes(self):
        import collector_result as collector
        c, f = self.continuity, self.fixture
        for path in c.restricted_output_paths(self.review):
            (f.root / path).unlink()
        f.runs.extend(f.run(1000 + i, 1, f.main_commit, '2026-10-01T01:00:00Z', conclusion='success')
                      for i in range(201))
        f.decision['approved_history_inventory_digest'] = c.approved_history_inventory_digest(f.runs)
        f.write(c.DECISION_PATH, f.decision)
        f.git('add', c.DECISION_PATH); f.git('commit', '-qm', 'bind complete old run inventory')
        f.main_commit = f.git('rev-parse', 'HEAD').strip(); f.current['head_sha'] = f.main_commit
        f.git('push', 'origin', 'main')
        f.evidence = c.authenticate_evidence(f.root, execution_id=f.identity, purpose='analysis')
        self.review = f.report(write=True)
        self.collector.write_text(json.dumps(collector.restricted_aggregate(self.review, root=f.root, identity=f.identity)))
        analysis_requests = f.evidence.request_count
        f.calls.clear(); self.auth_mock.reset_mock(); self.freshness_mock.reset_mock()
        result = self.transaction().run()
        counts = result['publication_freshness_checks'][0]
        self.assertEqual(self.auth_mock.call_count, 1)
        self.assertEqual(self.freshness_mock.call_count, 1)
        self.assertEqual(counts['inventory_count'], 203)
        self.assertEqual(counts['authentication_requests'], 10)  # two full three-page scans + four bindings
        self.assertEqual(counts['freshness_requests'], 6)  # one full three-page scan + three bindings
        self.assertEqual(analysis_requests + counts['attempt_total_requests'], 26)
        self.assertEqual(len(f.calls), counts['attempt_total_requests'])

    def test_actual_postcommit_freshness_and_local_push_retry_reuse_one_proof_per_attempt(self):
        c, f = self.continuity, self.fixture
        initial = pub.git(self.remote, 'rev-parse', 'main').stdout.decode().strip()
        class RetryOnce(pub.Transaction):
            def push(self, work):
                if len(self.attempts) == 1:
                    return False
                return super().push(work)
        tx = self.transaction(RetryOnce)
        tx.dry_run = False  # Local temporary bare repository only.
        f.calls.clear()
        result = tx.run()
        tip = pub.git(self.remote, 'rev-parse', 'main').stdout.decode().strip()
        self.assertEqual(result['status'], 'restricted_analysis_published')
        self.assertEqual(result['commit_sha'], tip)
        self.assertNotEqual(tip, initial)
        self.assertEqual(self.auth_mock.call_count, 2)
        self.assertEqual(self.freshness_mock.call_count, 2)
        self.assertEqual(len(result['attempts']), 2)
        self.assertTrue(result['attempts'][0]['push_rejected'])
        self.assertEqual([row['attempt_total_requests'] for row in result['publication_freshness_checks']], [10, 10])
        self.assertEqual(len(f.calls), 20)
        changed = pub.git(self.remote, 'diff', '--name-only', initial, tip).stdout.decode().splitlines()
        self.assertEqual(set(changed), set(c.restricted_output_paths(tx.restricted_review)))

    def test_actual_final_scan_rejects_new_run_and_old_attempt_retry(self):
        import copy
        c, f = self.continuity, self.fixture
        original_runs = copy.deepcopy(f.runs)
        for kind in ('new_run', 'old_retry'):
            with self.subTest(kind=kind):
                f.runs = copy.deepcopy(original_runs)
                class ChangedAfterQuality(pub.Transaction):
                    def stage(self, work):
                        changed = super().stage(work)
                        if kind == 'new_run':
                            f.runs.append(f.run(50000000001, 1, f.main_commit, '2026-10-23T05:58:00Z', conclusion='failure'))
                        else:
                            next(row for row in f.runs if row['id'] == c.GAP['run_id'])['run_attempt'] = 2
                        return changed
                tx = self.transaction(ChangedAfterQuality)
                with patch.object(tx, 'push') as push, self.assertRaisesRegex(pub.PublishError, 'run_inventory_changed_before_push'):
                    tx.run()
                push.assert_not_called()
                self.assertIsNone(pub.at_ref(self.remote, 'main', c.REPORT_PATH))

    def test_authenticated_knowledge_advance_reanalyzes_without_stale_overlay(self):
        c, f = self.continuity, self.fixture
        other = self.folder / 'other'
        pub.git(self.folder, 'clone', '-b', 'main', str(self.remote), str(other))
        for key, value in [('user.name', 'Fixture'), ('user.email', 'fixture@example.invalid')]:
            pub.git(other, 'config', key, value)
        proof = f.publish_knowledge(root=other)
        pub.git(other, 'push', 'origin', 'main')
        expected = c.protected_inventory(other)
        captured = {}
        class InspectedTransaction(pub.Transaction):
            def stage(self, work):
                result = super().stage(work)
                captured['protected'] = c.protected_inventory(work)
                captured['paths'] = pub.git(work, 'diff', '--cached', '--name-only').stdout.decode().splitlines()
                captured['review'] = read(work, c.REPORT_PATH)
                captured['original_history'] = (work / c.restricted_output_paths(self.source_review)[1]).read_bytes()
                return result
        tx = self.transaction(InspectedTransaction)
        tx.source_review = self.review
        original_history = (f.root / c.restricted_output_paths(self.review)[1]).read_bytes()
        with patch('socket.create_connection', side_effect=AssertionError('network forbidden')), \
             patch.object(pub.Transaction, 'command', side_effect=AssertionError('provider/action forbidden')):
            result = tx.run()
        fresh = captured['review']
        self.assertEqual(result['status'], 'restricted_dry_run_validated')
        self.assertEqual(captured['protected'], expected)
        self.assertEqual(fresh['input_commit'], proof['commit_sha'])
        self.assertNotEqual(fresh['analysis_id'], self.review['analysis_id'])
        for key in ('decision_digest', 'gap_ids', 'code_contract_digest', 'execution_id', 'actor'):
            self.assertEqual(fresh[key], self.review[key])
        self.assertEqual(captured['original_history'], original_history)
        self.assertEqual(set(captured['paths']), set(c.restricted_output_paths(self.review)) | set(c.restricted_output_paths(fresh)))
        self.assertEqual(self.auth_mock.call_count, 1)
        self.assertEqual(self.freshness_mock.call_count, 1)
        self.assertEqual(f.calls.count('actions/jobs/120253948591/logs'), 1)
        self.assertEqual(pub.git(self.remote, 'rev-parse', 'main').stdout.decode().strip(), proof['commit_sha'])

    def test_unattributed_main_data_change_blocked_by_actual_engine(self):
        c, f = self.continuity, self.fixture
        other = self.folder / 'other'
        pub.git(self.folder, 'clone', '-b', 'main', str(self.remote), str(other))
        for key, value in [('user.name', 'Fixture'), ('user.email', 'fixture@example.invalid')]:
            pub.git(other, 'config', key, value)
        dump(other, c.INPUT_PATHS[0], {'collected_at': '2026-10-23T05:59:00Z',
                                     'products': [{'pd_no': 'independent-new-input', 'price': 120}]})
        pub.git(other, 'add', c.INPUT_PATHS[0]); pub.git(other, 'commit', '-m', 'independent saved input')
        pub.git(other, 'push', 'origin', 'main')
        f.main_commit = pub.git(other, 'rev-parse', 'HEAD').stdout.decode().strip()
        with self.assertRaises(pub.PublishError): self.transaction().run()
        self.assertIsNone(pub.at_ref(self.remote, 'main', c.REPORT_PATH))

    def test_offline_aggregate_and_prequality_make_no_api_calls(self):
        import collector_result as collector
        import check_release_quality as quality
        c, f = self.continuity, self.fixture
        before = len(f.calls)
        with patch.object(c, 'authenticate_evidence', side_effect=AssertionError('offline gate started discovery')):
            doc = collector.restricted_aggregate(self.review, root=f.root, identity=f.identity)
            report = quality.check_restricted(f.root, doc, phase='candidate', execution_id=f.identity, now=self.now)
        self.assertTrue(report['publish_allowed'])
        self.assertEqual(report['validation_scope'], 'offline_bindings')
        self.assertEqual(len(f.calls), before)

    def test_json_flags_cannot_substitute_sealed_evidence_or_trigger_reauth(self):
        import collector_result as collector
        c, f = self.continuity, self.fixture
        doc = json.loads(self.collector.read_text())
        for false_proof in (False, True, {}, {'verified': True}):
            with self.subTest(false_proof=false_proof), \
                 patch.object(c, 'authenticate_evidence', side_effect=AssertionError('invalid proof triggered discovery')):
                with self.assertRaises(c.ContinuityError):
                    collector.validate_restricted_aggregate(doc, root=f.root, identity=f.identity,
                                                           evidence=false_proof, now=self.now)

    def test_zero_delta_still_authenticates_new_gap_before_reporting_success(self):
        c, f = self.continuity, self.fixture
        f.git('add', c.REPORT_PATH, c.HISTORY_DIR)
        f.git('commit', '-qm', 'already present restricted output')
        f.git('push', 'origin', 'main')
        f.main_commit = f.git('rev-parse', 'HEAD').strip()
        f.runs.append(f.run(50000000001, 1, f.main_commit, '2026-10-23T05:58:00Z', conclusion='failure'))
        tx = self.transaction()
        self.assertEqual(tx.delta, {})
        with self.assertRaises(pub.PublishError): tx.run()

    def test_new_ambiguous_gap_blocks_actual_publisher_before_output(self):
        c, f = self.continuity, self.fixture
        f.runs.append(f.run(50000000001, 1, f.main_commit, '2026-10-23T05:58:00Z', conclusion='failure'))
        before = pub.git(self.remote, 'rev-parse', 'main').stdout
        with self.assertRaises((pub.PublishError, c.ContinuityError)):
            self.transaction().run()
        self.assertEqual(pub.git(self.remote, 'rev-parse', 'main').stdout, before)


class TimingAndBudgetTests(unittest.TestCase):
    def capture(self, callback):
        import contextlib
        import io
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            callback()
        return [json.loads(line.split(' ', 1)[1]) for line in output.getvalue().splitlines()]

    def test_timing_success_has_elapsed_and_no_payload(self):
        def operation():
            with pub.timed_phase('push'):
                pass
        with patch.object(pub.time, 'monotonic', side_effect=[10, 12.25]):
            rows = self.capture(operation)
        self.assertEqual(rows, [{'phase': 'push', 'event': 'start'},
            {'phase': 'push', 'event': 'end', 'outcome': 'completed', 'elapsed_seconds': 2.25}])

    def test_timing_preserves_exception_without_logging_sensitive_text(self):
        def operation():
            error = RuntimeError('secret-token-in-error')
            try:
                with pub.timed_phase('command', command_index=2):
                    raise error
            except RuntimeError as caught:
                self.assertIs(caught, error)
        rows = self.capture(operation)
        self.assertEqual(rows[-1]['outcome'], 'interrupted')
        self.assertEqual(rows[-1]['command_index'], 2)
        self.assertNotIn('secret', json.dumps(rows))

    def test_untrusted_labels_rejected_before_logging(self):
        for phase, index in [('secret-token', None), ('command', 'secret-token'), ('command', True)]:
            with self.assertRaises(ValueError):
                with pub.timed_phase(phase, command_index=index):
                    self.fail('invalid timer entered')

    def test_failed_command_still_blocks_and_has_no_success_receipt(self):
        from types import SimpleNamespace
        tx = object.__new__(pub.Transaction)
        tx.executed_commands = []
        def operation():
            with self.assertRaises(pub.PublishError):
                tx.command(ROOT, ['scripts/run_jarvis_operations.py', '--secret-argument'])
        with patch.object(pub.subprocess, 'run', return_value=SimpleNamespace(returncode=9)):
            rows = self.capture(operation)
        self.assertEqual(tx.executed_commands, [])
        self.assertEqual(rows[-1]['outcome'], 'interrupted')
        self.assertNotIn('secret', json.dumps(rows))

    def test_core_budget_preserves_safety_and_both_runtime_passes(self):
        import yaml
        text = (ROOT/'.github/workflows/JARVIS-Core-Automation.yml').read_text(encoding='utf-8')
        workflow = yaml.load(text, Loader=yaml.BaseLoader)
        self.assertEqual(workflow['jobs']['core-automation']['timeout-minutes'], '60')
        self.assertEqual(workflow['concurrency'], {'group': 'main-publish', 'cancel-in-progress': 'false'})
        steps = workflow['jobs']['core-automation']['steps']
        source = next(s for s in steps if s.get('name') == 'Bounded existing-team source recovery')
        self.assertEqual(source['timeout-minutes'], '12')
        runtime = next(s for s in steps if s.get('id') == 'runtime_refresh')
        self.assertIn("operations_continuity == 'verified'", runtime['if'])
        self.assertIn('scripts/run_jarvis_operations.py', runtime['run'])
        self.assertIn(['scripts/run_jarvis_operations.py'], POLICY['runtime_commands'])
        for name in ('Retain source safety checkpoint', 'Retain immutable operations safety history'):
            retention = next(s for s in steps if s.get('name') == name)
            self.assertIn('always()', retention['if'])
            self.assertIn("== 'verified'", retention['if'])
        self.assertIn("for phase in ('candidate', 'final'):", (ROOT/'scripts/publish_transaction.py').read_text())


if __name__=='__main__':unittest.main(verbosity=2)
