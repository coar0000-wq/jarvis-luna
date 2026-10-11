#!/usr/bin/env python3
"""Offline failures use isolated copied fixtures, never mutate operating sources."""
import json
from pathlib import Path
import tempfile
import unittest
from build_public_site import ROOT, STATIC_FILES, SCHEMAS, build, project, PRODUCT, COMPARISON, encoded, digest
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

    def test_daily_pipeline_does_not_present_old_or_missing_evidence_as_today_passed(self):
        html=(self.root/'index.html').read_text(encoding='utf-8')
        self.assertIn("if(it.date===today) live++;", html)
        self.assertIn("legalBad?'bad':null", html)
        self.assertIn("it.grade?'done':null", html)
        self.assertIn("it.status==='DRAFT'", html)
        self.assertIn("it.status==='deleted_by_owner'?'삭제 이력'", html)
        self.assertIn("Number(it.single_margin_pct)>=30", html)
        self.assertNotIn("legalBad?'bad':'done'", html)
        self.assertNotIn("!(it.images>0)", html)

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

if __name__=='__main__':unittest.main(verbosity=2)
