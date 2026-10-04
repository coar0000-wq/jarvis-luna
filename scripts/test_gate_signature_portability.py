"""Cross-checkout text formatting is stable, real legal evidence changes are not."""
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
