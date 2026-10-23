#!/usr/bin/env python3
"""Offline failures use isolated copied fixtures, never mutate operating sources."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from build_public_site import ROOT, STATIC_FILES, SCHEMAS, build, project, PRODUCT, COMPARISON, encoded, digest, restricted_public_summary
from check_public_site import validate, local_reference


class PublicSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(dir=ROOT.parent, prefix='public-fixtures-')
        cls.root=Path(cls.tmp.name)/'source';cls.root.mkdir()
        for name in (*STATIC_FILES,*SCHEMAS):
            target=cls.root/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((ROOT/name).read_bytes())
        cls.output=Path(cls.tmp.name)/'dist'
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def setUp(self): self.manifest=build(self.root,self.output,'a'*40)

    def restricted_review(self):
        return {'mode':'restricted_gap','continuity':'unresolved_gap',
                'production_recovered':False,'operations_execution_verified':False,
                'status':'RESTRICTED_ANALYSIS_COMPLETE',
                'analyzed_at':'2026-10-23T05:00:00Z'}

    def test_restricted_summary_never_exposes_private_receipts_or_approval(self):
        review=dict(self.restricted_review(), receipt={'nonce':'private'},
                    approval={'message':'private'}, old_run_provider_cost=None,
                    provider_api_key='private', input_digests={'private':'value'})
        self.assertEqual(restricted_public_summary(review),self.restricted_review())
        runtime=project({'continuity_review':review},SCHEMAS['data/dashboard_runtime.json'])
        self.assertEqual(runtime,{'continuity_review':self.restricted_review()})

    def test_restricted_summary_cannot_claim_verified_or_normal_recovery(self):
        for key,value in (('mode','normal'),('continuity','verified'),
                          ('status','RESTRICTED_ANALYSIS_PUBLISHED'),
                          ('production_recovered',True),('operations_execution_verified',True),
                          ('production_recovered',0),('analyzed_at','not a date'),
                          ('analyzed_at','2026-10-23T05:00:00')):
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                restricted_public_summary(dict(self.restricted_review(),**{key:value}))
        for key in self.restricted_review():
            row=self.restricted_review();row.pop(key)
            with self.subTest(missing=key),self.assertRaises(ValueError):restricted_public_summary(row)

    def test_restricted_pending_display_cannot_claim_analysis_already_ran(self):
        pending=dict(self.restricted_review(),status='RESTRICTED_ANALYSIS_PENDING',analyzed_at=None)
        self.assertEqual(restricted_public_summary(pending),pending)
        with self.assertRaises(ValueError):
            restricted_public_summary(dict(pending,analyzed_at='2026-10-23T05:00:00Z'))

    def blocked_pending(self):
        return dict(self.restricted_review(), status='RESTRICTED_ANALYSIS_BLOCKED', analyzed_at=None)

    def test_blocked_pending_has_only_fixed_public_fields_and_no_analysis_clock(self):
        row=dict(self.blocked_pending(), exception='secret /private/path', approval='private', receipts=[1])
        self.assertEqual(restricted_public_summary(row), self.blocked_pending())
        for key,value in (('analyzed_at','2026-10-23T05:00:00Z'),('production_recovered',True),
                          ('operations_execution_verified',True),('continuity','verified'),('mode','normal')):
            with self.subTest(key=key),self.assertRaises(ValueError):
                restricted_public_summary(dict(row,**{key:value}))

    def test_invalid_pending_decision_only_emits_blocked_display_and_preserves_all_inputs(self):
        from continuity_reconciliation import ContinuityError
        decision=self.root/'data/manual/continuity_reconciliation/deep-39893237129-attempt-1.json'
        decision.parent.mkdir(parents=True,exist_ok=True);decision.write_text('{}')
        try:
            before={p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            for error in ('frozen_baseline_changed','code_contract_changed','private /home/runner/token=secret'):
                with self.subTest(error=error),patch('continuity_reconciliation.validate_pending_decision',side_effect=ContinuityError(error)) as pending:
                    manifest=build(self.root,self.output,'a'*40)
                    pending.assert_called_once_with(self.root.resolve())
                public=json.loads((self.output/'data/dashboard_runtime.json').read_text())
                self.assertEqual(public['continuity_review'],self.blocked_pending())
                self.assertEqual(set(manifest['files']),set(self.manifest['files']))
                self.assertNotIn(error,json.dumps(public))
                validate(self.output)
                self.assertEqual(before,{p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
                self.assertFalse((self.root/'data/agents/continuity_review.json').exists())
                # The same validator remains blocked; display projection did not authorize it.
                with patch('continuity_reconciliation.validate_pending_decision',side_effect=ContinuityError(error)):
                    from continuity_reconciliation import validate_pending_decision
                    with self.assertRaises(ContinuityError):validate_pending_decision(self.root)
        finally:decision.unlink()

    def test_valid_pending_still_requires_validator_and_retains_pending_status(self):
        decision=self.root/'data/manual/continuity_reconciliation/deep-39893237129-attempt-1.json'
        decision.parent.mkdir(parents=True,exist_ok=True);decision.write_text('{}')
        expected=dict(self.restricted_review(),status='RESTRICTED_ANALYSIS_PENDING',analyzed_at=None)
        try:
            with patch('continuity_reconciliation.validate_pending_decision',return_value=expected) as pending:
                build(self.root,self.output,'a'*40);pending.assert_called_once()
            self.assertEqual(json.loads((self.output/'data/dashboard_runtime.json').read_text())['continuity_review'],expected)
            with patch('continuity_reconciliation.validate_pending_decision',side_effect=RuntimeError('unexpected')):
                with self.assertRaisesRegex(RuntimeError,'unexpected'):build(self.root,self.output,'a'*40)
        finally:decision.unlink()

    def test_invalid_published_review_cannot_fall_back_to_pending_policy(self):
        from continuity_reconciliation import ContinuityError
        decision=self.root/'data/manual/continuity_reconciliation/deep-39893237129-attempt-1.json'
        decision.parent.mkdir(parents=True,exist_ok=True);decision.write_text('{}')
        review=self.root/'data/agents/continuity_review.json';review.write_text(json.dumps(self.restricted_review()))
        try:
            with patch('continuity_reconciliation.validate_published_review',side_effect=ContinuityError('invalid published')),patch('continuity_reconciliation.validate_pending_decision') as pending:
                with self.assertRaisesRegex(ContinuityError,'invalid published'):build(self.root,self.output,'a'*40)
                pending.assert_not_called()
        finally:review.unlink();decision.unlink()

    def test_missing_published_evidence_cannot_be_downgraded_when_pending_policy_exists(self):
        decision=self.root/'data/manual/continuity_reconciliation/deep-39893237129-attempt-1.json'
        decision.parent.mkdir(parents=True,exist_ok=True);decision.write_text('{}')
        runtime=self.root/'data/dashboard_runtime.json';before=runtime.read_bytes()
        try:
            for review in (self.restricted_review(),self.blocked_pending(),None):
                source=json.loads(before);source['continuity_review']=review;runtime.write_text(json.dumps(source))
                with patch('continuity_reconciliation.validate_pending_decision') as pending:
                    with self.assertRaisesRegex(ValueError,'source evidence missing'):build(self.root,self.output,'a'*40)
                    pending.assert_not_called()
        finally:runtime.write_bytes(before);decision.unlink()

    def test_pending_policy_symlink_fails_instead_of_showing_normal_or_blocked_state(self):
        decision=self.root/'data/manual/continuity_reconciliation/deep-39893237129-attempt-1.json'
        decision.parent.mkdir(parents=True,exist_ok=True);decision.symlink_to(self.root/'absent-private-file')
        try:
            with patch('continuity_reconciliation.validate_pending_decision') as pending:
                with self.assertRaisesRegex(ValueError,'symlink'):build(self.root,self.output,'a'*40)
                pending.assert_not_called()
        finally:decision.unlink()

    def test_restricted_build_injects_public_copy_only_after_validation(self):
        path=self.root/'data/agents/continuity_review.json'
        canonical=self.root/'data/dashboard_runtime.json';before=canonical.read_bytes()
        path.write_text(json.dumps(self.restricted_review()),encoding='utf-8')
        try:
            with patch('continuity_reconciliation.validate_published_review',return_value={}) as validator:
                manifest=build(self.root,self.output,'a'*40)
                validator.assert_called_once()
            self.assertEqual(canonical.read_bytes(),before)
            self.assertEqual(set(manifest['files']),set(self.manifest['files']))
            self.assertEqual(json.loads((self.output/'data/dashboard_runtime.json').read_text())['continuity_review'],self.restricted_review())
            validate(self.output)
            with patch('continuity_reconciliation.validate_published_review',side_effect=ValueError('binding changed')):
                with self.assertRaisesRegex(ValueError,'binding changed'):build(self.root,self.output,'a'*40)
        finally:path.unlink()

    def test_restricted_public_display_tampering_rejected_even_with_rehashed_manifest(self):
        name='data/dashboard_runtime.json';path=self.output/name
        data=json.loads(path.read_text());data['continuity_review']=dict(self.restricted_review(),production_recovered=True)
        path.write_bytes(encoded(data));manifest=self.manifest
        manifest['files'][name]=digest(path.read_bytes());manifest['site_hash']=digest(encoded(manifest['files']))
        (self.output/'deployment.json').write_bytes(encoded(manifest))
        with self.assertRaisesRegex(ValueError,'restricted review'):validate(self.output)

    def test_restricted_browser_label_cannot_turn_green_on_spoofed_mode(self):
        html=(ROOT/'index.html').read_text(encoding='utf-8')
        self.assertIn(".live-indicator[data-continuity-state='restricted']{color:#d29922;}", html)
        self.assertIn(".live-indicator[data-continuity-state='unverified']{color:#f85149;}", html)
        self.assertIn('.live-indicator[data-continuity-state] .live-dot{background:currentColor;box-shadow:none;animation:none;}', html)
        start=html.index('function renderContinuityReview(review){')
        end=html.index('\nasync function loadData(){',start)
        code="""const assert=require('assert');const nodes={};
const indicator={attributes:{},setAttribute(k,v){this.attributes[k]=v;}};
const $=id=>nodes[id]||(nodes[id]={hidden:true,textContent:'',parentElement:indicator});
const set=(id,text)=>{$(id).textContent=text;};const KST=x=>x;
"""+html[start:end]+"\nconst valid="+json.dumps(self.restricted_review())+";"+"""
renderContinuityReview(valid);
assert.equal($('continuity-review-banner').hidden,false);
assert.equal($('live-text').textContent,'제한 운영');
assert.equal(indicator.attributes['data-continuity-state'],'restricted');
assert.equal(indicator.attributes.role,'status');
assert.ok(indicator.attributes['aria-label'].includes('전체 자동화 복구 미완료'));
assert.ok($('continuity-review-title').textContent.includes('전체 자동화 복구 미완료'));
assert.ok($('continuity-review-detail').textContent.includes('Core·Deep의 이 제한 분석'));
assert.ok($('continuity-review-detail').textContent.includes('다른 독립 워크플로'));
assert.ok(!$('continuity-review-detail').textContent.includes('중단된 상태입니다'));
for(const upload of ['success','failure','cancelled','unknown']){
 renderContinuityReview({...valid,artifact_upload_outcome:upload});
 assert.ok($('continuity-review-detail').textContent.includes('후속 보존 업로드 결과는 별도 확인'));
 assert.ok(!$('continuity-review-detail').textContent.includes('보존 완료'));
}
for(const bad of [{...valid,continuity:'verified'},{...valid,production_recovered:true},{...valid,mode:'normal'}]){
 renderContinuityReview(bad);assert.equal($('live-text').textContent,'확인 필요');
 assert.equal(indicator.attributes['data-continuity-state'],'unverified');
 assert.ok(indicator.attributes['aria-label'].includes('정상 운영 확인 불가'));
 assert.ok($('continuity-review-title').textContent.includes('근거 불일치'));
}
renderContinuityReview({...valid,status:'RESTRICTED_ANALYSIS_BLOCKED',analyzed_at:null});
assert.equal($('live-text').textContent,'확인 필요');
assert.equal(indicator.attributes['data-continuity-state'],'unverified');
assert.ok($('continuity-review-title').textContent.includes('근거 불일치'));
assert.ok(!$('continuity-review-detail').textContent.includes('분석 시각:'));
renderContinuityReview(null);assert.equal($('continuity-review-banner').hidden,true);
renderContinuityReview({...valid,status:'RESTRICTED_ANALYSIS_PENDING',analyzed_at:null});
assert.ok($('continuity-review-title').textContent.includes('검증 대기'));
assert.ok(!$('continuity-review-detail').textContent.includes('분석 시각:'));
"""
        result=subprocess.run(['node','-e',code],text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_product_desk_survives_public_projection(self):
        row = {'pd_no': '1072800', 'desk': 'makeup', 'site_category': '베이스메이크업',
               'bucket': '스킨케어', 'private_owner_note': 'not public'}
        public = project(row, PRODUCT)
        self.assertEqual(public['desk'], 'makeup')
        self.assertEqual(public['site_category'], '베이스메이크업')
        self.assertNotIn('private_owner_note', public)

    def test_neighboring_registry_list_is_explicitly_historical(self):
        html=(self.root/'index.html').read_text(encoding='utf-8')
        self.assertIn("sum.textContent='생성 이력 '", html)
        self.assertIn("ACTIVE:'당시 ACTIVE',DRAFT:'당시 DRAFT'", html)
        self.assertIn("meta.textContent='생성 당시 '", html)
        self.assertIn("' · 당시 이미지 '", html)
        self.assertNotIn("var st={ACTIVE:'공개',DRAFT:'초안'", html)

    def test_daily_pipeline_does_not_present_old_or_missing_evidence_as_today_passed(self):
        html=(self.root/'index.html').read_text(encoding='utf-8')
        self.assertIn("kpi('실시간 공개 집계', '조회 안 함')", html)
        # 2026-10-11 사용자 지시: 성공 파랑 · 준비중 노랑(wait) · 에러 빨강. 증적이 없으면 '준비중'이지 통과가 아니다.
        self.assertNotIn("legalBad?'bad':(live?'done':'wait')", html)
        self.assertIn("legalBad?'bad':'wait'", html)
        self.assertIn("graded?'done':'wait'", html)
        self.assertIn(".dp-step.wait i{background:#e3b341", html)
        self.assertIn("it.status==='DRAFT'", html)
        self.assertIn("it.status==='deleted_by_owner'?'삭제 이력'", html)
        self.assertIn("var priced=typeof it.single_usd==='number' && Number.isFinite(it.single_usd) && it.single_usd>0 && it.single_margin_pct!=null;", html)
        self.assertNotIn("legalBad?'bad':'done'", html)
        self.assertNotIn("!(it.images>0)", html)

    def test_beauty_strategy_has_display_only_projection_and_follows_team_section(self):
        html=(self.root/'index.html').read_text(encoding='utf-8')
        self.assertLess(html.index('id="teams"'),html.index('id="daiso"'))
        self.assertLess(html.index('id="daiso"'),html.index('id="operations-system"'))
        strategy=json.loads((self.output/'data/beauty_price_strategy.json').read_text(encoding='utf-8'))
        self.assertTrue(strategy['policy']['margin_is_advisory_only'])
        self.assertFalse(strategy['policy']['grade_changes_allowed'])
        self.assertNotIn('files', strategy['input_coverage'])
        self.assertNotIn('receipts', strategy['team_work_plan'])
        self.assertEqual(set(strategy['categories']), {'skincare','makeup','body'})
        # 2026-10-11 카테고리 전담팀: 스킨케어 S 수는 실제 점수 산출물(스킨케어 전담팀 S)과 같아야 한다.
        desk_s=json.loads((ROOT/'data/daiso_real/shopify_demand_score.json').read_text(encoding='utf-8'))['category_desks']['skincare']['s_count']
        self.assertEqual(strategy['categories']['skincare']['grade_counts']['S'],desk_s)
        self.assertIn('renderBeautyStrategy(beautyJ',html)

    def test_real_display_projection_build_and_check(self):
        self.assertEqual(validate(self.output),self.manifest)
        price=json.loads((self.output/'data/pricing_model.json').read_text(encoding='utf-8'))
        self.assertIn('shipping_unit_usd',price['scenarios']['1개_묶음배송'][0])
        self.assertIn('orders_for_500usd',price['offers']['bundle'])
        self.assertIn('free_shipping',price['offers']['bundle'])

    def test_visible_numeric_and_channel_fields_survive_projection(self):
        market=json.loads((self.output/'data/market_team.json').read_text(encoding='utf-8'))
        original=json.loads((self.root/'data/market_team.json').read_text(encoding='utf-8'))
        self.assertEqual(market['health']['exchange_rate'], original['health']['exchange_rate'])
        self.assertIsInstance(market['health']['exchange_rate'], (int,float))
        self.assertEqual(market['competitor_watch'][0]['us_rank'], original['competitor_watch'][0]['us_rank'])
        runtime=json.loads((self.output/'data/dashboard_runtime.json').read_text(encoding='utf-8'))
        source=json.loads((self.root/'data/dashboard_runtime.json').read_text(encoding='utf-8'))
        for key in ('sources','topics','records'):
            self.assertEqual(runtime['graph'][key], source['graph'][key])
        self.assertEqual(runtime['global_channels']['tiktok_shop_us'][0]['hashtag'], source['global_channels']['tiktok_shop_us'][0]['hashtag'])
        self.assertEqual(runtime['global_channels']['google_trends_us'][0]['badge'], source['global_channels']['google_trends_us'][0]['badge'])

    def test_invalid_public_fx_blocks_even_with_correct_manifest(self):
        name='data/market_team.json'; target=self.output/name
        data=json.loads(target.read_text(encoding='utf-8'));data['health']['exchange_rate']='unverified'
        target.write_bytes(encoded(data))
        m=self.manifest;m['files'][name]=digest(target.read_bytes());m['site_hash']=digest(encoded(m['files']))
        (self.output/'deployment.json').write_bytes(encoded(m))
        with self.assertRaisesRegex(ValueError,'exchange-rate'):validate(self.output)

    def test_missing_graph_counts_block_instead_of_displaying_fake_zero(self):
        name='data/dashboard_runtime.json';target=self.output/name
        data=json.loads(target.read_text(encoding='utf-8'));data['graph'].pop('topics')
        target.write_bytes(encoded(data))
        m=self.manifest;m['files'][name]=digest(target.read_bytes());m['site_hash']=digest(encoded(m['files']))
        (self.output/'deployment.json').write_bytes(encoded(m))
        with self.assertRaisesRegex(ValueError,'graph numeric'):validate(self.output)

    def test_deterministic_same_snapshot_and_commit(self):
        first={p.relative_to(self.output).as_posix():p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        build(self.root,self.output,'a'*40)
        self.assertEqual(first,{p.relative_to(self.output).as_posix():p.read_bytes() for p in self.output.rglob('*') if p.is_file()})

    def test_internal_fields_credentials_and_absolute_paths_are_removed(self):
        projected=project({'name':'public','api_key':'secret','typesafe':{'usage':5},'url':'file:///C:/Users/a','reason':'C:\\Users\\private\\config'},PRODUCT)
        self.assertNotIn('api_key',projected);self.assertNotIn('typesafe',projected)
        self.assertIsNone(projected['url']);self.assertEqual(projected['reason'],'[private value omitted]')
        p=project({'teams':[],'health':{'secret':'x'},'remediation_state':{'secret':'x'},'pipeline_health':{'status':'degraded','errors':['private']}},SCHEMAS['data/dashboard_runtime.json'])
        self.assertNotIn('health',p);self.assertNotIn('remediation_state',p)
        self.assertEqual(p['pipeline_health'],{'status':'degraded'})

    def test_free_text_billing_and_private_manual_paths_are_not_public(self):
        data={'teams':[{'id':'listing','summary':'초안 준비 9/10 · Jev 판정 10건(입력 10,961토큰 · $0.0005, 무료 크레딧) · 영상 학습 40개',
                        'action':'data/manual/inci_overrides.json 확인 대기'}]}
        result=project(data,SCHEMAS['data/dashboard_runtime.json']);summary=result['teams'][0]['summary']
        self.assertEqual(summary,'초안 준비 9/10 · 영상 학습 40개')
        for value in ('Jev','토큰','$0.0005','무료 크레딧','data/manual'):
            self.assertNotIn(value,json.dumps(result,ensure_ascii=False))

    def test_candidate_safety_is_preserved_without_internal_hashes(self):
        p=project({'candidate_count':1,'may_publish':False,'may_replace_operating_products':False,'operating_sha256':'private','items':[]},COMPARISON)
        self.assertFalse(p['may_publish']);self.assertFalse(p['may_replace_operating_products']);self.assertNotIn('operating_sha256',p)

    def test_unallowlisted_file_blocks(self):
        (self.output/'private.json').write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'inventory'): validate(self.output)

    def test_artifact_tampering_blocks(self):
        (self.output/'index.html').write_text('changed',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'hash'): validate(self.output)

    def test_nonpublic_field_blocks_even_if_hash_is_recomputed(self):
        file='data/agents/ops_plan.json';p=self.output/file
        data=json.loads(p.read_text(encoding='utf-8'));data['password']='private';p.write_bytes(encoded(data))
        m=self.manifest;m['files'][file]=digest(p.read_bytes());m['site_hash']=digest(encoded(m['files']));(self.output/'deployment.json').write_bytes(encoded(m))
        with self.assertRaisesRegex(ValueError,'non-public'): validate(self.output)

    def test_traversal_root_path_or_private_scheme_blocks(self):
        for ref in ('../private.json','/data/foo.json','javascript:alert(1)','file:///private'):
            with self.subTest(ref=ref),self.assertRaises(ValueError):local_reference(ref)
        self.assertEqual(local_reference('/jarvis-luna/data/x.json'),'data/x.json')

    def test_destructive_output_or_invalid_commit_rejected(self):
        with self.assertRaises(ValueError):build(self.root,self.root,'a'*40)
        with self.assertRaises(ValueError):build(self.root,self.output,'bad')

    def test_public_symlink_rejected(self):
        link=self.output/'linked.json'
        try:link.symlink_to(self.root/'data/dashboard_runtime.json')
        except OSError:self.skipTest('symlink creation unavailable on this host')
        with self.assertRaisesRegex(ValueError,'symlink'):validate(self.output)

def load_tests(loader, suite, pattern):
    """Existing preflight/Pages entry point also runs the new offline regressions."""
    import importlib.util
    import sys
    for name, relative in (
        ('_daily_pipeline_projection_regression', 'scripts/test_daily_pipeline_projection.py'),
        ('_daily_beauty_regression', 'tests/test_daiso_daily_beauty_to_shopify.py'),
        ('_commerce_policy_regression', 'tests/test_daiso_commerce_strategy.py'),
        ('_price_strategy_regression', 'scripts/test_beauty_price_strategy.py'),
        ('_obsidian_navigation_regression', 'scripts/test_connect_obsidian_orphans.py'),
    ):
        spec=importlib.util.spec_from_file_location(name, ROOT/relative)
        module=importlib.util.module_from_spec(spec)
        sys.modules[name]=module
        spec.loader.exec_module(module)
        suite.addTests(loader.loadTestsFromModule(module))
    return suite

if __name__=='__main__':unittest.main(verbosity=2)
