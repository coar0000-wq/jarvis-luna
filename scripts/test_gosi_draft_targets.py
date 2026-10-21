"""실제 등록 초안도 수집하고, 실패 후보가 한도를 독점하지 않는다."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('collector', Path(__file__).parent / 'daiso/collect_gosi_alt.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

class DraftTargetsTests(unittest.TestCase):
    def test_role_only_maker_is_still_a_recollection_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'gosi').write_text(json.dumps({'items': {'1033789': dict(
                ingredients='정제수', volume='90g', maker='및 책임판매원', origin='대한민국')}}))
            (root / 'registry').write_text(json.dumps({'items': [dict(pd_no='1033789',
                status='DRAFT', shopify_id='gid://shopify/Product/1')]}))
            (root / 'score').write_text(json.dumps({'all_scored': []}))
            with patch.object(c, 'GOSI', root/'gosi'), patch.object(c, 'REGISTRY', root/'registry'), \
                 patch.object(c, 'SCORE', root/'score'), patch('sys.argv', ['collector']):
                self.assertEqual(c.targets(), ['1033789'])
            (root / 'registry').write_text(json.dumps({'items': []}))
            (root / 'score').write_text(json.dumps({'all_scored': [dict(pd_no='1033789', grade='S')]}))
            with patch.object(c, 'GOSI', root/'gosi'), patch.object(c, 'REGISTRY', root/'registry'), \
                 patch.object(c, 'SCORE', root/'score'), patch('sys.argv', ['collector']):
                self.assertEqual(c.targets(), ['1033789'])

    def test_provider_stop_is_not_a_successful_collection(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'gosi.json'
            path.write_text(json.dumps({'items': {}}))
            with patch.object(c, 'GOSI', path), patch.object(c, 'validate_document', return_value={}), \
                 patch.object(c, 'assert_not_stopped', side_effect=c.ProviderStop('daiso', 403)):
                self.assertEqual(c.main(), 2)

    def test_drafts_and_s_candidates_rotate_without_deleted_or_complete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixtures = {
                'gosi': {'items': {'1': {'observation_attempts': [{'attempted_at': '2026-10-19T00:00:00Z'}]},
                                   '4': dict(ingredients='a', volume='1g', maker='b', origin='KR')}},
                'registry': {'items': [dict(pd_no=str(i), status='deleted_by_owner' if i == 3 else 'DRAFT',
                    shopify_id=f'gid://shopify/Product/{i}') for i in range(1, 5)]},
                'score': {'all_scored': [dict(pd_no='1', grade='S'), dict(pd_no='5', grade='S')]},
            }
            for key, value in fixtures.items():
                (root / key).write_text(json.dumps(value))
            with patch.object(c, 'GOSI', root/'gosi'), patch.object(c, 'REGISTRY', root/'registry'), \
                 patch.object(c, 'SCORE', root/'score'), patch.object(c, 'MAX_ITEMS', 2), patch('sys.argv', ['collector']):
                self.assertEqual(c.targets(), ['2', '5'])
                with patch.object(c, 'MAX_ITEMS', 10):
                    self.assertEqual(c.targets(), ['2', '5', '1'])

if __name__ == '__main__':
    unittest.main()
