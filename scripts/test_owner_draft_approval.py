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


def category_document():
    doc = decision_document()
    doc['category_scopes'] = [{
        'category': 'body', 'category_code': approvals.BODY_CATEGORY_CODE,
        'source_url': approvals.BODY_SOURCE_URL, 'status': 'OWNER_APPROVED',
        'decision_type': 'business_decision', 'draft_only': True,
        'selection_condition': 'no_eligible_canonical_s', 'daily_limit': 1,
        'ordering': 'source_category_list_order', 'promote_to_s': False,
        'public_sale_authorized': False, 'safety_evidence_verified': False,
        'fda_approval': False,
    }]
    return doc


class CategoryDraftApprovalTests(unittest.TestCase):
    setUp = OwnerDraftApprovalTests.setUp
    install = OwnerDraftApprovalTests.install

    def category_ok(self):
        return approvals.category_approved(
            approvals.BODY_CATEGORY_CODE, approvals.BODY_SOURCE_URL, self.root)

    def test_category_scope_is_exact_and_not_blanket_product_approval(self):
        self.install(category_document())
        self.assertTrue(self.category_ok())
        self.assertTrue(approvals.approved('123', self.root))
        self.assertFalse(approvals.approved('456', self.root))
        self.assertFalse(approvals.category_approved('CTGR_01114', approvals.BODY_SOURCE_URL, self.root))
        self.assertFalse(approvals.category_approved(approvals.BODY_CATEGORY_CODE, '*', self.root))
        self.assertFalse(approvals.category_approved(None, None, self.root))

    def test_missing_malformed_duplicate_or_revoked_category_fails_closed(self):
        self.assertFalse(self.category_ok())
        for scopes in (None, {}, 'all', [None], [True]):
            doc = decision_document()
            doc['category_scopes'] = scopes
            self.install(doc)
            self.assertFalse(self.category_ok())
        doc = category_document()
        doc['category_scopes'].append(copy.deepcopy(doc['category_scopes'][0]))
        self.install(doc)
        self.assertFalse(self.category_ok())
        doc = category_document()
        doc['category_scopes'][0]['status'] = 'REVOKED'
        self.install(doc)
        self.assertFalse(self.category_ok())
        self.path.write_text('{bad', encoding='utf-8')
        self.assertFalse(self.category_ok())

    def test_broader_category_terms_and_false_strings_are_not_approval(self):
        bad = [('category', 'skincare'), ('category_code', '*'), ('source_url', '*'),
               ('decision_type', 'safety_certification'), ('draft_only', 'true'),
               ('selection_condition', 'all_products'), ('daily_limit', True),
               ('daily_limit', 2), ('ordering', 'sales_score'), ('promote_to_s', True),
               ('public_sale_authorized', True), ('safety_evidence_verified', True),
               ('fda_approval', True)]
        for key, value in bad:
            with self.subTest(field=key):
                doc = category_document()
                doc['category_scopes'][0][key] = value
                self.install(doc)
                self.assertFalse(self.category_ok())
        for key in ('public_sale_authorized', 'safety_evidence_verified', 'fda_approval'):
            doc = category_document()
            doc[key] = True
            self.install(doc)
            self.assertFalse(self.category_ok())

    def test_category_approval_does_not_manufacture_safety_evidence(self):
        self.install(category_document())
        self.assertTrue(self.category_ok())
        self.assertFalse(manufacturer_safety.manufacturer_safety_record('456', self.root)['covered'])


if __name__ == '__main__':
    unittest.main()
