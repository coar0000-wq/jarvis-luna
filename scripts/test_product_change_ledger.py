#!/usr/bin/env python3
"""Isolated policy decreases/restores must preserve source facts and exact hashes."""
from copy import deepcopy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from daiso import exclude_unprofitable as collector
from daiso import product_change_ledger as ledger

ROOT = Path(__file__).resolve().parents[1]


def offer(pd_no, profitable=False, qty=1):
    price=10.0*qty; cost=(5.0 if profitable else 9.0)*qty
    fee=(0.0 if profitable else 1.0)*qty; net=price-cost-fee
    return {'pd_no':pd_no,'qty':qty,'price_usd':price,'unit_price_usd':10.0,
            'landed_cost_total_usd':cost,'fee_usd':fee,'net_profit_usd':net,
            'margin_pct':round(net/price*100,1)}


class ProductChangeProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT.parent,prefix='change-proof-')
        self.root=Path(self.tmp.name)/'repo';self.root.mkdir()
        self.baseline=Path(self.tmp.name)/'baseline'
        self.products={'count':2,'products':[
            {'pd_no':'1','name':'observed loss','price_krw':1000,'url':'https://example.com/1'},
            {'pd_no':'2','name':'observed viable','price_krw':1000,'url':'https://example.com/2'}]}
        self.archive={'count':0,'items':{}}
        self.pricing={'offers_by_product':{
            'single':[offer('1'),offer('2',True)],
            'bundle':[offer('1',qty=2),offer('2',True,2)],'규칙':'same observed facts'}}
        self.rule={'min_margin_pct':15.0,'min_net_profit_usd':1.5}
        self.save(ledger.PRODUCT_PATH,self.products)
        self.save(ledger.ARCHIVE_PATH,self.archive)
        self.save(ledger.PRICING_PATH,self.pricing)
        self.save(ledger.RULE_PATH,self.rule)
        target=self.baseline/ledger.PRODUCT_PATH;target.parent.mkdir(parents=True)
        target.write_bytes((self.root/ledger.PRODUCT_PATH).read_bytes())
        self.git('init','-q');self.git('config','core.autocrlf','false')
        self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid')
        self.commit()
    def tearDown(self):self.tmp.cleanup()
    def git(self,*args):
        result=subprocess.run(['git','-C',str(self.root),*args],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
    def commit(self):self.git('add','data');self.git('commit','-qm','fixture')
    def save(self,name,doc):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(ledger.encode(doc))
    def read(self,name):return ledger.read_json(self.root/name)
    def bytes(self):return {p.relative_to(self.root).as_posix():p.read_bytes() for p in (self.root/'data').rglob('*') if p.is_file()}
    def run_collector(self,*flags):
        paths={'ROOT':self.root,'DATA':self.root/'data','DAISO':self.root/'data/daiso_real',
               'PRICING':self.root/ledger.PRICING_PATH,'PRODUCTS':self.root/ledger.PRODUCT_PATH,
               'EXCLUDED':self.root/ledger.ARCHIVE_PATH,'RULE':self.root/ledger.RULE_PATH}
        with patch.multiple(collector,**paths),patch.object(sys,'argv',['fixture',*flags]),patch.dict('os.environ',{'DAISO_EXECUTION_ID':'fixture:1'}):
            return collector.main()
    def assert_valid(self):
        valid,errors=ledger.validate_removal_evidence(self.root,self.baseline,{'1'})
        self.assertTrue(valid,errors)
    def assert_invalid(self):
        valid,errors=ledger.validate_removal_evidence(self.root,self.baseline,{'1'})
        self.assertFalse(valid);self.assertTrue(errors)

    def test_real_exclusion_records_proof_and_exact_head_manifest(self):
        original=self.bytes();self.assertEqual(self.run_collector('--apply'),0)
        self.assertEqual([p['pd_no'] for p in self.read(ledger.PRODUCT_PATH)['products']],['2'])
        self.assertEqual(self.read(ledger.ARCHIVE_PATH)['items']['1']['원본'],self.products['products'][0])
        self.assert_valid()
        entry=self.read(ledger.MANIFEST_PATH)['deletions'][0]
        self.assertEqual(entry['ids'],['1']);self.assertEqual(entry['base_sha256'],ledger.sha(original[ledger.PRODUCT_PATH]))
        row=self.read(ledger.LEDGER_PATH)['changes'][0]
        self.assertEqual(row['execution_id'],'fixture:1');self.assertEqual(row['action'],'exclude')

    def test_dry_run_writes_nothing(self):
        before=self.bytes();self.assertEqual(self.run_collector(),0);self.assertEqual(before,self.bytes())

    def test_unchanged_rerun_does_not_add_fake_attempt_or_change(self):
        self.run_collector('--apply');before=self.bytes();self.run_collector('--apply');self.assertEqual(before,self.bytes())

    def test_viable_bundle_prevents_exclusion(self):
        self.pricing['offers_by_product']['bundle'][0]=offer('1',True,2);self.save(ledger.PRICING_PATH,self.pricing)
        before=self.bytes();self.run_collector('--apply');self.assertEqual(before,self.bytes())

    def test_exclude_then_restore_other_archived_identity_replays_to_final_hash(self):
        restored={'pd_no':'3','name':'restorable original','price_krw':1000,'url':'https://example.com/3'}
        self.archive={'count':1,'items':{'3':{'원본':restored,'뺀_규칙':ledger.REASON_TAG}}}
        self.save(ledger.ARCHIVE_PATH,self.archive)
        for form,qty in [('single',1),('bundle',2)]:self.pricing['offers_by_product'][form].append(offer('3',True,qty))
        self.save(ledger.PRICING_PATH,self.pricing);self.commit()
        self.run_collector('--apply');self.run_collector('--restore','--apply');self.assert_valid()
        self.assertEqual([p['pd_no'] for p in self.read(ledger.PRODUCT_PATH)['products']],['2','3'])
        records=self.read(ledger.MANIFEST_PATH)['deletions'];restore=next(r for r in records if r['path']==ledger.ARCHIVE_PATH)
        self.assertEqual(restore['ids'],['3']);self.assertNotIn('3',self.read(ledger.ARCHIVE_PATH)['items'])

    def test_restore_dry_run_does_not_mutate_saved_originals(self):
        self.run_collector('--apply')
        for form,qty in [('single',1),('bundle',2)]:self.pricing['offers_by_product'][form][0]=offer('1',True,qty)
        self.save(ledger.PRICING_PATH,self.pricing);before=self.bytes()
        self.run_collector('--restore');self.assertEqual(before,self.bytes())

    def test_boolean_fake_verified_is_not_a_proof(self):
        self.run_collector('--apply');doc=self.read(ledger.LEDGER_PATH);doc['changes'][0]['evidence']={}
        self.save(ledger.LEDGER_PATH,doc);self.assert_invalid()

    def test_omitted_profitable_offer_or_tampered_snapshot_rejected(self):
        self.run_collector('--apply');doc=self.read(ledger.LEDGER_PATH)
        key=next(iter(doc['pricing_sources']));doc['pricing_sources'][key]='{}'
        self.save(ledger.LEDGER_PATH,doc);self.assert_invalid()

    def test_changed_baseline_bytes_rejected(self):
        self.run_collector('--apply');p=self.baseline/ledger.PRODUCT_PATH;p.write_bytes(p.read_bytes()+b'\n');self.assert_invalid()

    def test_changed_after_bytes_rejected(self):
        self.run_collector('--apply');p=self.root/ledger.PRODUCT_PATH;p.write_bytes(p.read_bytes()+b'\n');self.assert_invalid()

    def test_wrong_saved_original_rejected(self):
        self.run_collector('--apply');doc=self.read(ledger.ARCHIVE_PATH);doc['items']['1']['원본']['name']='not the original'
        self.save(ledger.ARCHIVE_PATH,doc);self.assert_invalid()

    def test_changed_policy_rejected(self):
        self.run_collector('--apply');self.rule['min_margin_pct']=20.0;self.save(ledger.RULE_PATH,self.rule);self.assert_invalid()

    def test_missing_batch_record_cannot_explain_other_removal(self):
        self.products['products'].append({'pd_no':'4','name':'another loss','price_krw':1000,'url':'https://example.com/4'})
        self.products['count']=3;self.save(ledger.PRODUCT_PATH,self.products)
        (self.baseline/ledger.PRODUCT_PATH).write_bytes((self.root/ledger.PRODUCT_PATH).read_bytes())
        for form,qty in [('single',1),('bundle',2)]:self.pricing['offers_by_product'][form].append(offer('4',qty=qty))
        self.save(ledger.PRICING_PATH,self.pricing);self.commit();self.run_collector('--apply')
        doc=self.read(ledger.LEDGER_PATH);doc['changes']=doc['changes'][:1];self.save(ledger.LEDGER_PATH,doc)
        self.assertFalse(ledger.validate_removal_evidence(self.root,self.baseline,{'1','4'})[0])

    def test_bad_math_boolean_nan_missing_fee_do_not_modify_products(self):
        for field,value in [('net_profit_usd',100),('price_usd',True),('fee_usd',None),('margin_pct',math.nan)]:
            with self.subTest(field=field):
                pricing=deepcopy(self.pricing);pricing['offers_by_product']['single'][0][field]=value
                p=self.root/ledger.PRICING_PATH;p.write_text(json.dumps(pricing),encoding='utf-8')
                before=self.bytes()
                with self.assertRaises(ValueError):self.run_collector('--apply')
                self.assertEqual(before,self.bytes())

    def test_missing_explicit_policy_or_git_base_fails_without_write(self):
        rule=self.root/ledger.RULE_PATH;rule.unlink();before=self.bytes()
        with self.assertRaises(ValueError):self.run_collector('--apply')
        self.assertEqual(before,self.bytes());self.save(ledger.RULE_PATH,self.rule)
        self.git('update-ref','-d','HEAD');before=self.bytes()
        with self.assertRaises(ValueError):self.run_collector('--apply')
        self.assertEqual(before,self.bytes())

    def test_duplicate_identity_and_malformed_archive_fail_before_write(self):
        doc=deepcopy(self.products);doc['products'].append(deepcopy(doc['products'][0]));self.save(ledger.PRODUCT_PATH,doc)
        before=self.bytes()
        with self.assertRaises(ValueError):self.run_collector('--apply')
        self.assertEqual(before,self.bytes());self.save(ledger.PRODUCT_PATH,self.products);self.save(ledger.ARCHIVE_PATH,{'items':[]})
        before=self.bytes()
        with self.assertRaises(ValueError):self.run_collector('--apply')
        self.assertEqual(before,self.bytes())

    def test_manifest_preserves_other_paths_and_unions_same_base_ids(self):
        other={'schema_version':1,'deletions':[{'path':'data/unrelated.json','ids':['x'],'reason':'unrelated proof'}]}
        first=ledger.deletion_manifest(self.root,other,ledger.PRODUCT_PATH,['1'],'observed policy decision')
        second=ledger.deletion_manifest(self.root,first,ledger.PRODUCT_PATH,['2'],'observed policy decision')
        self.assertEqual(second['deletions'][0],other['deletions'][0]);self.assertEqual(second['deletions'][1]['ids'],['1','2'])
        self.assertEqual(other['deletions'][0]['ids'],['x'])

if __name__=='__main__':unittest.main(verbosity=2)
