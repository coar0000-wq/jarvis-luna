"""Offline tests; no actual store or source writes."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import plan_draft_product_copy as planner
import test_apply_reviewed_product_gallery as existing


class CopyPlanTests(unittest.TestCase):
    def setUp(self):
        self.fixture = existing.ExecutorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.snapshot = deepcopy(self.fixture.snapshot)
        self.now, self.root = self.fixture.now, self.fixture.root
        self.policy = planner.read_json(planner.POLICY)
        self.original_policy = deepcopy(self.policy)
        for rule in self.policy['products']:
            for i, source in enumerate(rule['sources']):
                p = self.root / source['local_file']; p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(('synthetic source ' + rule['pd_no'] + str(i)).encode())
                source['sha256'] = hashlib.sha256(p.read_bytes()).hexdigest()
        self.mock = patch.object(planner, 'read_json', return_value=self.policy)
        self.mock.start(); self.addCleanup(self.mock.stop)
        self.prepare('1033789')

    def prepare(self, pid):
        self.pid = pid
        rule = next(r for r in self.policy['products'] if r['pd_no'] == pid)
        self.rule = rule
        self.snapshot['shop']['id'] = self.policy['shop_id']
        p = self.snapshot['product']
        p.update(id=rule['product_id'], title=rule['old_title'], status='DRAFT',
                 tags=['daiso-pd-' + pid], publishedAt=None, publications=[])
        template = deepcopy(p['variants'][0])
        p['variants'] = []
        for identity in rule['variant_identity']:
            variant = deepcopy(template); variant.update(identity); p['variants'].append(variant)
        p['descriptionHtml'] = '<p>' + rule['replacements'][0]['old'] + '</p>'
        p['descriptionHtml'] += ''.join('<li>' + r['old'] + '</li>' for r in rule['replacements'][1:])
        p['descriptionHtml'] += '<p>Preserve existing directions, warnings, ingredients and custom content.</p>'

    def plan(self):
        return planner.build_plan(self.snapshot, self.pid, self.root, now=self.now)

    def held(self):
        before = deepcopy(self.snapshot)
        with self.assertRaises(planner.Hold): self.plan()
        self.assertEqual(before, self.snapshot)

    def test_both_products_exact_minimal_changes(self):
        for pid in planner.ALLOWED:
            self.prepare(pid); before = deepcopy(self.snapshot); result = self.plan()
            self.assertEqual(before, self.snapshot)
            self.assertEqual(set(result['changes']), {'title','descriptionHtml'})
            self.assertIn('Preserve existing directions',result['changes']['descriptionHtml'])
            self.assertTrue(all(result[k] is False for k in planner.FLAGS))
            self.assertFalse(result['apply_allowed'])

    def test_idempotent(self):
        result = self.plan(); self.snapshot['product'].update(result['changes'])
        again = self.plan(); self.assertEqual(again['state'],'no_op'); self.assertEqual(again['changes'],{})

    def test_readback_protected_everything(self):
        plan = self.plan(); after = deepcopy(self.snapshot); after['product'].update(plan['changes'])
        self.assertEqual(planner.verify_readback(plan,after,now=self.now)['state'],'copy_readback_verified')
        for field,value in [('status','ACTIVE'),('handle','different'),('totalInventory',999),('vendor','Changed'),('publications',[{'publication':{'id':'gid://shopify/Publication/7'},'isPublished':True,'publishDate':self.now.isoformat()}])]:
            changed=deepcopy(after); changed['product'][field]=value
            with self.assertRaises(planner.Hold): planner.verify_readback(plan,changed,now=self.now)
        for field,value in [('price','99.00'),('sku','wrong'),('inventoryQuantity',99),('selectedOptions',[{'name':'Size','value':'different'}])]:
            changed=deepcopy(after); changed['product']['variants'][0][field]=value
            with self.assertRaises(planner.Hold): planner.verify_readback(plan,changed,now=self.now)

    def test_active_rejected(self): self.snapshot['product']['status']='ACTIVE'; self.held()
    def test_wrong_shop(self): self.snapshot['shop']['id']='gid://shopify/Shop/3'; self.held()
    def test_wrong_product(self): self.snapshot['product']['id']='gid://shopify/Product/3'; self.held()
    def test_wrong_pd_tag(self): self.snapshot['product']['tags']=['daiso-pd-1073406']; self.held()
    def test_extra_pd_tag(self): self.snapshot['product']['tags'].append('daiso-pd-5'); self.held()
    def test_variant_identity_changed(self): self.snapshot['product']['variants'][0]['sku']='bad'; self.held()
    def test_unknown_title(self): self.snapshot['product']['title']='Custom revised'; self.held()
    def test_missing_body(self): self.snapshot['product'].pop('descriptionHtml'); self.held()
    def test_missing_snapshot_channel(self): self.snapshot['product'].pop('publications'); self.held()
    def test_stale_snapshot(self): self.snapshot['observed_at']=(self.now-timedelta(minutes=6)).isoformat(); self.held()
    def test_incomplete_snapshot(self): self.snapshot['complete']=False; self.held()
    def test_missing_replacement(self): self.snapshot['product']['descriptionHtml']='Something else'; self.held()
    def test_duplicate_replacement(self): self.snapshot['product']['descriptionHtml']*=2; self.held()
    def test_conflicting_copy(self): self.snapshot['product']['descriptionHtml']+=self.rule['replacements'][0]['new']; self.held()
    def test_source_tamper(self): (self.root/self.rule['sources'][0]['local_file']).write_bytes(b'changed'); self.held()
    def test_missing_source(self): (self.root/self.rule['sources'][0]['local_file']).unlink(); self.held()
    def test_unsafe_source(self): self.rule['sources'][0]['local_file']='../../outside'; self.held()
    def test_flags_not_promoted(self):
        for flag in planner.FLAGS:
            self.policy[flag]=True; self.held(); self.policy[flag]=False
    def test_lg_weight_and_manufacturer(self):
        body=self.plan()['changes']['descriptionHtml']
        self.assertIn('90 g including moisture; 72 g when dry (per bar)',body)
        self.assertIn('LG Household &amp; Health Care Ltd.',body)
        self.assertNotIn('및 책임판매원',body)
    def test_partial_already_correct(self):
        self.snapshot['product']['title']=self.rule['title_en']
        self.assertEqual(set(self.plan()['changes']),{'descriptionHtml'})
    def test_plan_tamper(self):
        p=self.plan(); p['changes']['status']='ACTIVE'
        with self.assertRaises(planner.Hold): planner.verify_readback(p,self.snapshot,now=self.now)
    def test_original_policy_approval_flags_false(self):
        self.assertTrue(all(self.original_policy[k] is False for k in planner.FLAGS))
    def test_cli_hold_preserves_existing_output(self):
        output = self.root / 'old-plan.json'; output.write_bytes(b'prior output')
        argv = ['plan', '--snapshot', str(self.root/'missing.json'), '--pd-no', self.pid,
                '--evidence-root', str(self.root), '--output', str(output)]
        with patch('sys.argv', argv), patch.object(planner, 'build_plan', side_effect=planner.Hold('held')):
            with self.assertRaises(SystemExit) as error: planner.main()
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(output.read_bytes(), b'prior output')

    def test_output_fsync_error_may_follow_replacement(self):
        output = self.root / 'output.json'; output.write_bytes(b'prior output')
        argv = ['plan', '--snapshot', str(self.root/'snapshot.json'), '--pd-no', self.pid,
                '--evidence-root', str(self.root), '--output', str(output)]
        result = self.plan()
        with patch('sys.argv', argv), patch.object(planner, 'build_plan', return_value=result), \
             patch.object(existing.executor.os, 'fsync', side_effect=[None, OSError('directory fsync failed')]):
            with self.assertRaises(SystemExit) as error: planner.main()
        self.assertEqual(error.exception.code, 2)
        # HELD is not a claim that the old file survived an output I/O failure.
        self.assertEqual(json.loads(output.read_text()), result)

    def test_no_remote_executor(self):
        source=Path(planner.__file__).read_text()
        self.assertNotIn('productUpdate(',source); self.assertNotIn('append_once(',source)

if __name__ == '__main__': unittest.main()
