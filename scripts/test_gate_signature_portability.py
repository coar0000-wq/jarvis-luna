"""Cross-checkout text formatting is stable, real legal evidence changes are not."""
import json
from test_manufacturer_safety import synthetic_receipt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import gate_signature as gs

class GateTextPortability(unittest.TestCase):
    def fixture(self,data):
        return patch.multiple(gs,DATA=data,
            PRODUCT_MASTER=data/'product_master.json',GOSI=data/'gosi.json',
            LABELS=data/'daiso_real/daiso_us_labels.json',PRICING=data/'pricing_model.json',
            LEGAL=data/'legal_products.json',RECOMMENDATIONS=data/'daiso_real/shopify_s_recommendations.json')

    def test_windows_linux_newlines_bind_same_meaning(self):
        with tempfile.TemporaryDirectory() as td:
            data=Path(td);(data/'manual').mkdir()
            sop=data/'manual/mocra_adverse_event_sop.md'
            with self.fixture(data):
                sop.write_bytes('Report within 15 days.\n보관 기록\n'.encode('utf-8'))
                lf=gs.agent_input_signature([])
                sop.write_bytes('Report within 15 days.\r\n보관 기록\r\n'.encode('utf-8'))
                self.assertEqual(lf,gs.agent_input_signature([]))

    def test_real_text_change_invalidates_signature(self):
        with tempfile.TemporaryDirectory() as td:
            data=Path(td);(data/'manual').mkdir();sop=data/'manual/mocra_adverse_event_sop.md'
            with self.fixture(data):
                sop.write_bytes(b'Report within 15 days.\n')
                before=gs.agent_input_signature([])
                sop.write_bytes(b'Report within 30 days.\n')
                self.assertNotEqual(before,gs.agent_input_signature([]))

    def test_commerce_policy_change_invalidates_signature(self):
        with tempfile.TemporaryDirectory() as td:
            data=Path(td); policy=data/'strategy.json'
            with self.fixture(data), patch.object(gs, 'COMMERCE_STRATEGY', policy):
                policy.write_text('{"price_policy":{"margin_hard_block":false}}', encoding='utf-8')
                before=gs.agent_input_signature([])
                self.assertIn('config/daiso_commerce_strategy.json', before['semantic_sources'])
                policy.write_text('{"price_policy":{"margin_hard_block":true}}', encoding='utf-8')
                self.assertNotEqual(before, gs.agent_input_signature([]))

    def test_private_coverage_revocation_changes_only_masked_safety_signature(self):
        with tempfile.TemporaryDirectory() as td:
            data=Path(td)/'data';(data/'manual').mkdir(parents=True)
            public=data/'manual/mocra_business.json';private=data/'manual/mocra_profile.json'
            public.write_text('{"safety_substantiation":{"covered_pd_nos":[]}}',encoding='utf-8')
            private.write_text('{"private_identity":"DO_NOT_PUBLISH","safety_substantiation":{"covered_pd_nos":["1"]}}',encoding='utf-8')
            receipt = synthetic_receipt(data.parent, '1')
            private.write_text(json.dumps({'private_identity':'DO_NOT_PUBLISH','safety_substantiation':{'covered_pd_nos':['1'],'evidence_records':[receipt]}}),encoding='utf-8')
            with self.fixture(data):
                before=gs.agent_input_signature([{'pd_no':'1'}])
                private.write_text('{"private_identity":"DO_NOT_PUBLISH","safety_substantiation":{"covered_pd_nos":[]}}',encoding='utf-8')
                after=gs.agent_input_signature([{'pd_no':'1'}])
                self.assertNotEqual(before,after)
                changed=[k for k in before['semantic_sources'] if before['semantic_sources'][k]!=after['semantic_sources'][k]]
                self.assertEqual(changed,['masked/manufacturer_safety_record'])
                self.assertNotIn('DO_NOT_PUBLISH',str(before))
                self.assertNotIn('mocra_profile.json',str(before))

    def test_valid_receipt_and_file_changes_invalidate_masked_signature(self):
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            data=Path(td)/'data';(data/'manual').mkdir(parents=True)
            (data/'manual/mocra_business.json').write_text('{"safety_substantiation":{"covered_pd_nos":[]}}',encoding='utf-8')
            receipt=synthetic_receipt(data.parent,'1')
            ledger=data/'manual/manufacturer_safety_evidence.private.json'
            def write():
                ledger.write_text(json.dumps({'schema_version':1,'records':[receipt]}),encoding='utf-8')
            write()
            with self.fixture(data):
                before=gs.agent_input_signature([{'pd_no':'1'}])
                receipt['manual_review']['reviewed_at']='2026-02-01'
                write()
                after=gs.agent_input_signature([{'pd_no':'1'}])
                self.assertNotEqual(before,after)
                review=data.parent/receipt['manual_review']['adequacy_file']
                review.write_bytes(b'SYNTHETIC TEST revised adequate review')
                receipt['manual_review']['adequacy_sha256']=hashlib.sha256(review.read_bytes()).hexdigest()
                write()
                newer=gs.agent_input_signature([{'pd_no':'1'}])
                self.assertNotEqual(after,newer)
                changed=[k for k in after['semantic_sources'] if after['semantic_sources'][k]!=newer['semantic_sources'][k]]
                self.assertEqual(changed,['masked/manufacturer_safety_record'])
                self.assertNotIn('SYNTHETIC-REVIEWER',str(newer))
                self.assertNotIn('manufacturer_safety_evidence.private.json',str(newer))
                review.unlink()
                self.assertNotEqual(newer,gs.agent_input_signature([{'pd_no':'1'}]))

    def test_missing_and_unreadable_never_impersonate_present_text(self):
        with tempfile.TemporaryDirectory() as td:
            data=Path(td);(data/'manual').mkdir();sop=data/'manual/mocra_adverse_event_sop.md'
            with self.fixture(data):
                missing=gs.agent_input_signature([])
                sop.write_bytes(b'missing_or_unreadable')
                self.assertNotEqual(missing,gs.agent_input_signature([]))
                sop.write_bytes(b'\xff\xfe')
                self.assertEqual(missing,gs.agent_input_signature([]))

if __name__=='__main__':unittest.main()
