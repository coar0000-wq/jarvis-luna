"""Wording screening does not certify safety or overall legal compliance."""
import unittest
from check_legal_products import review_wording


class WordingReviewTests(unittest.TestCase):
    def test_missing_copy_is_not_a_claims_pass(self):
        row = review_wording('  ', ['cure'])
        self.assertEqual(row['status'], 'NOT_REVIEWED_NO_COPY')
        self.assertFalse(row['overall_legal_clearance'])
        self.assertFalse(row['safety_approval'])

    def test_drug_and_false_fda_approval_phrases_are_flagged(self):
        for text, terms in [('Cure acne', ['cure']), ('FDA-approved cream', ['fda-approved']),
                            ('Boosts collagen production', ['boosts collagen production'])]:
            with self.subTest(text=text):
                row = review_wording(text, terms)
                self.assertEqual(row['status'], 'FLAGGED_FOR_REVIEW')
                self.assertEqual(row['flagged_terms'], terms)

    def test_word_boundaries_avoid_manufacturing_a_cure_claim_from_manicure(self):
        row = review_wording('Manicure cream for a moisturized feel', ['cure', 'treat'])
        self.assertEqual(row['status'], 'NO_RULE_HITS')
        self.assertEqual(row['flagged_terms'], [])
        self.assertFalse(row['overall_legal_clearance'])
        self.assertIn('not_official_fda_ban_list', row['rules_authority'])


if __name__ == '__main__':
    unittest.main()
