"""Synthetic scoped documents only, never production safety approval."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import build_mocra_readiness as mocra
from test_manufacturer_safety import synthetic_receipt


class MocraScopedSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        (self.data / 'manual').mkdir(parents=True)
        self.put('manual/mocra_business.json', {'annual_revenue_usd': 0,
            'safety_substantiation': {'covered_pd_nos': ['1'], 'scope': 'all_daiso_products',
                'verified_by': 'SYNTHETIC OWNER', 'verified_at': '2026-01-01',
                'status': 'verified', 'basis': 'ISO9001/CCM; future document promise'}})
        self.put('listing_gate.json', {'items': [{'pd_no': '1'}]})
        self.put('product_master.json', {'products': [{'pd_no': '1', 'name_ko': 'SYNTHETIC CREAM'}]})
        self.put('legal_full.json', {'items': {}})
        replacements = dict(ROOT=self.root, D=self.data, OUT=self.data/'mocra_readiness.json',
            PROFILE=self.data/'manual/mocra_profile.json', RP_FILE=self.data/'manual/legal_responsible_person.json',
            BUSINESS=self.data/'manual/mocra_business.json', RP_STATUS=self.data/'manual/legal_rp_status.json')
        for name, value in replacements.items():
            fixture = patch.object(mocra, name, value)
            fixture.start()
            self.addCleanup(fixture.stop)

    def put(self, relative, value):
        (self.data / relative).write_text(json.dumps(value), encoding='utf-8')

    def safety_check(self):
        self.assertEqual(mocra.main(), 0)
        result = json.loads(mocra.OUT.read_text(encoding='utf-8'))
        return next(row for row in result['checks'] if row['id'] == 'safety_substantiation')

    def test_owner_quality_declaration_is_not_ready(self):
        self.assertEqual(self.safety_check()['status'], 'not_ready')

    def test_actual_scoped_files_and_adequacy_receipt_are_required(self):
        record = synthetic_receipt(self.root, '1')
        self.put('manual/manufacturer_safety_evidence.private.json', {'schema_version': 1, 'records': [record]})
        self.assertEqual(self.safety_check()['status'], 'ready')
        (self.root / record['file']).write_bytes(b'changed synthetic dossier')
        self.assertEqual(self.safety_check()['status'], 'not_ready')


if __name__ == '__main__':
    unittest.main()
