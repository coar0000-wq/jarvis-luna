"""Offline exact-source generated-block cleanup and minimal Shopify read tests."""
import copy
from html import escape
import unittest
from unittest.mock import Mock
import draft_notice_enrichment as d


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.pd = '1060646'
        gid, self.title = d.TITLE_SCOPE[self.pd]
        self.entry = dict(pd_no=self.pd, shopify_id=gid, status='DRAFT', name_kr='더랩 바이 블랑두 클리어 히알 물광 틴티드 커버 크림 40 ml')
        self.intro = '<p>' + escape(self.entry['name_kr']) + " from Daiso Korea's daily beauty picks.</p>"
        self.legacy = '<h4>Product information</h4><ul><li><strong>Net contents:</strong> 또는중량 1.35fl.40ml</li><li><strong>Manufacturer / Distributor (Korea):</strong> 및 판매업자 화장품 Manufacturer 나우코스케이</li></ul>'
        self.footer = '<p><small>Source: Daiso Mall item 1060646.</small></p>'
        self.unrelated = '<p data-owner="yes">Owner note &amp; original photo.</p>'
        self.body = self.unrelated + self.intro + '<p><strong>Category:</strong> Cosmetics</p>' + self.legacy + self.footer
        self.label_html = '<h4>Product information</h4><ul><li><strong>Net contents:</strong> 40 mL</li></ul>'
        self.section = '<div data-jarvis-notice="1060646">' + self.label_html + '</div>'
        self.product = dict(id=gid, title=self.title, status='DRAFT', tags=['daiso-pd-1060646'], descriptionHtml=self.body)
        self.shop = Mock()
        self.shop.read_product.side_effect = lambda _: copy.deepcopy(self.product)
        self.shop.update_draft_content.side_effect = lambda _, html, title: self.product.update(descriptionHtml=html, title=title)
        self.collect = Mock(return_value={'gosi_ok': True})
        self.label = Mock(return_value={'html': self.label_html, 'reasons': []})
        self.save = Mock()
        self.registry = {'items': [self.entry]}
        self.overrides = {self.pd: {'shopify_id': gid, 'title': self.title}}

    def run_enrich(self):
        return d.enrich(self.shop, self.registry, self.collect, self.label, self.save, title_overrides=self.overrides)

    def migration_state(self):
        return dict(state='verified', section=self.section, before_description_html=self.body,
                    after_sha256=d.digest(self.body + self.section), expected_title=self.title)

    def test_initial_cleanup_replaces_only_generated_block_and_exact_intro(self):
        cleaned, audit = d.cleanup_superseded_generated(self.entry, {}, self.body, self.title)
        expected = self.body.replace(self.legacy, '').replace(self.intro, '<p>' + escape(self.title) + " from Daiso Korea's daily beauty picks.</p>")
        self.assertEqual(cleaned, expected)
        self.assertEqual(audit['legacy_block_sha256'], d.digest(self.legacy))
        self.assertEqual(self.run_enrich()[0]['status'], 'enriched_draft')
        self.assertEqual(self.product['descriptionHtml'], expected + self.section)
        self.assertEqual(self.entry['notice_enrichment']['before_description_html'], self.body)
        self.assertEqual(self.product['status'], 'DRAFT')
        self.shop.create.assert_not_called()
        self.shop.publish.assert_not_called()
        self.assertEqual(self.run_enrich()[0]['status'], 'unchanged')
        self.shop.update_draft_content.assert_called_once()

    def test_verified_append_migration_keeps_section_and_history(self):
        state = self.migration_state()
        self.entry['notice_enrichment'] = state
        self.product['descriptionHtml'] = self.body + self.section
        self.assertEqual(self.run_enrich()[0]['status'], 'enriched_draft')
        self.assertNotIn(self.legacy, self.product['descriptionHtml'])
        self.assertEqual(self.product['descriptionHtml'].count(self.section), 1)
        self.assertEqual(self.entry['notice_enrichment_history'], [state])
        self.assertEqual(self.entry['notice_enrichment']['before_description_html'], self.body + self.section)
        self.assertEqual(self.run_enrich()[0]['status'], 'unchanged')
        self.shop.update_draft_content.assert_called_once()

    def test_manual_changes_after_prior_verification_are_not_adopted(self):
        state = self.migration_state()
        self.entry['notice_enrichment'] = state
        self.product['descriptionHtml'] = self.body + self.section + '<p>New manual note</p>'
        before = self.product['descriptionHtml']
        self.assertEqual(d.cleanup_superseded_generated(self.entry, state, before, self.title), (before, None))
        self.assertEqual(self.run_enrich()[0]['status'], 'legacy_cleanup_review_required')
        self.assertEqual(self.product['descriptionHtml'], before)
        self.shop.update_draft_content.assert_not_called()

    def test_wrong_scope_duplicate_block_and_nonexact_generated_fragments_fail_closed(self):
        for body in (self.body + self.legacy, self.body.replace('Source: Daiso Mall item 1060646.', 'Source: Daiso Mall item 1069430.'),
                     self.body.replace(self.intro, '<p>Owner custom introduction</p>'), self.body.replace('<strong>Net contents:</strong>', '<b>Net contents:</b>')):
            with self.subTest(body=body):
                self.assertEqual(d.cleanup_superseded_generated(self.entry, {}, body, self.title), (body, None))
        self.assertEqual(d.cleanup_superseded_generated(self.entry, {}, self.body, 'Unproved title'), (self.body, None))
        self.entry['shopify_id'] = 'gid://shopify/Product/999'
        self.assertEqual(d.cleanup_superseded_generated(self.entry, {}, self.body, self.title), (self.body, None))

    def test_uncertain_cleanup_never_retried_and_accepted_timeout_reconciles(self):
        def accepted(_, html, title):
            self.product.update(descriptionHtml=html, title=title)
            raise RuntimeError('timeout')
        self.shop.update_draft_content.side_effect = accepted
        self.assertTrue(self.run_enrich()[0]['stop_further_writes'])
        self.assertEqual(self.entry['notice_enrichment']['state'], 'reserved')
        self.assertEqual(self.run_enrich()[0]['status'], 'reconciled')
        self.shop.update_draft_content.assert_called_once()
        self.assertTrue(self.entry['notice_enrichment']['cleanup_migration'])

    def test_unaccepted_timeout_stops_without_retry(self):
        self.shop.update_draft_content.side_effect = RuntimeError('timeout')
        self.assertTrue(self.run_enrich()[0]['stop_further_writes'])
        self.assertEqual(self.run_enrich()[0]['status'], 'prior_write_requires_reconciliation')
        self.shop.update_draft_content.assert_called_once()

    def test_fresh_title_or_body_change_blocks_cleanup(self):
        self.shop.read_product.side_effect = [copy.deepcopy(self.product), dict(self.product, title='Owner changed title')]
        self.assertTrue(self.run_enrich()[0]['stop_further_writes'])
        self.shop.update_draft_content.assert_not_called()
        self.shop.read_product.side_effect = [copy.deepcopy(self.product), dict(self.product, descriptionHtml=self.body + 'manual')]
        self.assertTrue(self.run_enrich()[0]['stop_further_writes'])
        self.shop.update_draft_content.assert_not_called()

    def test_only_structural_whitespace_is_allowed_and_preserved_elsewhere(self):
        spaced = self.legacy.replace('</h4><ul>', '</h4>\n<ul>\n  ').replace('</li><li>', '</li>\n  <li>').replace('</li></ul>', '</li>\n</ul>').replace('<li><strong>', '<li>\n<strong>')
        body = self.body.replace(self.legacy, spaced)
        cleaned, audit = d.cleanup_superseded_generated(self.entry, {}, body, self.title)
        self.assertIsNotNone(audit)
        self.assertNotIn('또는중량', cleaned)
        self.assertIn(self.unrelated, cleaned)
        nested = body.replace('또는중량', '<em>또는중량</em>')
        self.assertEqual(d.cleanup_superseded_generated(self.entry, {}, nested, self.title), (nested, None))

    def test_error_diagnostics_do_not_expose_provider_message(self):
        self.shop.read_product.side_effect = RuntimeError('secret URL token must not appear')
        result = self.run_enrich()[0]
        self.assertEqual(result['error_type'], 'RuntimeError')
        self.assertNotIn('secret', str(result))
        self.assertNotIn('error_reason', result)

    def test_minimal_notice_read_has_no_publication_dependency(self):
        import daiso_daily_beauty_to_shopify as daily
        shop = object.__new__(daily.Shopify)
        shop.gql = Mock(return_value={'product': self.product})
        self.assertEqual(shop.read_notice_product(self.entry['shopify_id']), self.product)
        query, variables = shop.gql.call_args.args
        self.assertNotIn('publishedOnPublication', query)
        self.assertNotIn('$pub', query)
        self.assertEqual(variables, {'id': self.entry['shopify_id']})


if __name__ == '__main__':
    unittest.main()
