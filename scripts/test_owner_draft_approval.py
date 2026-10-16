"""Owner approval is a non-public business decision, not a safety receipt."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import manufacturer_safety
import owner_draft_approval as approvals


def decision_document(pd_no='123'):
    return {'schema_version': 1, 'scope': 'nonpublic_draft_only',
            'source': 'owner_conversation', 'public_sale_authorized': False,
            'safety_evidence_verified': False, 'fda_approval': False,
            'items': {pd_no: {'status': 'OWNER_APPROVED',
                             'decision_type': 'business_decision', 'draft_only': True}}}


class OwnerDraftApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / approvals.PATH
        self.path.parent.mkdir(parents=True)

    def install(self, doc):
        self.path.write_text(json.dumps(doc), encoding='utf-8')

    def test_exact_products_only_and_revocation_is_immediate(self):
        doc = decision_document()
        self.install(doc)
        self.assertTrue(approvals.approved('123', self.root))
        self.assertTrue(approvals.approved(123, self.root))
        self.assertFalse(approvals.approved('456', self.root))
        doc['items']['123']['status'] = 'REVOKED'
        self.install(doc)
        self.assertFalse(approvals.approved('123', self.root))

    def test_owner_approval_never_manufactures_safety_coverage(self):
        self.install(decision_document())
        (self.path.parent / 'mocra_business.json').write_text(
            json.dumps({'safety_substantiation': {'covered_pd_nos': []}}), encoding='utf-8')
        self.assertTrue(approvals.approved('123', self.root))
        self.assertFalse(manufacturer_safety.manufacturer_safety_record('123', self.root)['covered'])

    def test_missing_malformed_and_broader_permissions_fail_closed(self):
        self.assertFalse(approvals.approved('123', self.root))
        for doc in ([], None, {'schema_version': True}, {'items': 'all'}):
            self.install(doc)
            self.assertFalse(approvals.approved('123', self.root))
        for field, value in (('public_sale_authorized', True), ('safety_evidence_verified', True),
                             ('fda_approval', True), ('scope', 'public_sale'),
                             ('source', 'automated_model'), ('schema_version', True)):
            with self.subTest(field=field):
                doc = decision_document()
                doc[field] = value
                self.install(doc)
                self.assertFalse(approvals.approved('123', self.root))
        self.path.write_text('{bad', encoding='utf-8')
        self.assertFalse(approvals.approved('123', self.root))

    def test_false_string_and_wrong_decision_type_are_not_approval(self):
        for field, value in (('draft_only', 'true'), ('status', 'VERIFIED'),
                             ('decision_type', 'safety_certification')):
            doc = decision_document()
            doc['items']['123'][field] = value
            self.install(doc)
            self.assertFalse(approvals.approved('123', self.root))
        for bad in (None, True, False, [], {}, 1.5):
            self.assertFalse(approvals.approved(bad, self.root))


if __name__ == '__main__':
    unittest.main()
