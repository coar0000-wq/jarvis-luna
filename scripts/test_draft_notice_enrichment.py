"""Offline regression: free extraction, rotating existing drafts, uncertain writes."""
import copy
import unittest
from unittest.mock import MagicMock, Mock, patch
import draft_notice_enrichment as d


class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.entry = dict(pd_no='1069430', shopify_id='gid://shopify/Product/1', status='DRAFT')
        self.registry = {'items': [self.entry]}
        self.product = dict(id=self.entry['shopify_id'], status='DRAFT', tags=['daiso-pd-1069430'], descriptionHtml='<p>Original</p>')
        self.shop = Mock()
        self.shop.read_product.side_effect = lambda _: copy.deepcopy(self.product)
        self.shop.update_description.side_effect = lambda _, html: self.product.update(descriptionHtml=html)
        self.collect = Mock(return_value={'gosi_ok': True})
        self.label = Mock(return_value={'html': '<p>Sourced label</p>', 'reasons': []})
        self.save = Mock()

    def run_enrich(self):
        return d.enrich(self.shop, self.registry, self.collect, self.label, self.save)

    def test_reuses_existing_draft_preserves_original_and_never_creates_or_publishes(self):
        self.assertEqual(self.run_enrich()[0]['status'], 'enriched_draft')
        self.assertTrue(self.product['descriptionHtml'].startswith('<p>Original</p>'))
        self.collect.assert_called_once_with('1069430', allow_ai=False)
        self.shop.create.assert_not_called()
        self.shop.publish.assert_not_called()
        self.shop.set_status.assert_not_called()
        self.assertEqual(self.entry['notice_enrichment']['before_description_html'], '<p>Original</p>')
        self.assertEqual(self.run_enrich()[0]['status'], 'unchanged')
        self.shop.update_description.assert_called_once()

    def test_active_and_wrong_source_never_written(self):
        for changes in ({'status': 'ACTIVE'}, {'tags': ['daiso-pd-1069429']}, {'id': 'wrong'}):
            with self.subTest(changes=changes):
                old = copy.deepcopy(self.product)
                self.product.update(changes)
                self.assertEqual(self.run_enrich()[0]['status'], 'identity_or_draft_changed')
                self.product = old
        self.shop.update_description.assert_not_called()

    def test_rotates_created_draft_and_excludes_owner_deleted(self):
        other = dict(self.entry, pd_no='2', shopify_id='gid://shopify/Product/2', status='created_draft')
        self.registry['items'] += [other, dict(self.entry, status='deleted_by_owner')]
        self.registry['notice_enrichment_cursor'] = self.entry['shopify_id']
        self.assertEqual([r['pd_no'] for r in d.candidates(self.registry)], ['2', '1069430'])

    def test_incomplete_or_ocr_only_evidence_never_becomes_label(self):
        self.collect.return_value = {'gosi_ok': False, '_notice_evidence': {'ocr': [{'candidate_fields': {'ingredients': 'unverified'}}]}}
        self.assertEqual(self.run_enrich()[0]['status'], 'source_or_label_review_required')
        self.shop.update_description.assert_not_called()

    def test_ambiguous_write_is_reserved_and_never_retried(self):
        self.shop.update_description.side_effect = RuntimeError('timeout')
        self.assertTrue(self.run_enrich()[0]['stop_further_writes'])
        self.assertEqual(self.entry['notice_enrichment']['state'], 'reserved')
        self.assertEqual(self.run_enrich()[0]['status'], 'prior_write_requires_reconciliation')
        self.shop.update_description.assert_called_once()

    def test_accepted_timeout_reconciles_without_second_write(self):
        def accepted(_, html):
            self.product['descriptionHtml'] = html
            raise RuntimeError('timeout')
        self.shop.update_description.side_effect = accepted
        self.run_enrich()
        self.assertEqual(self.run_enrich()[0]['status'], 'reconciled')
        self.shop.update_description.assert_called_once()

    def test_changed_body_before_write_and_failed_reservation_stop(self):
        self.shop.read_product.side_effect = [copy.deepcopy(self.product), dict(self.product, descriptionHtml='changed')]
        self.assertTrue(self.run_enrich()[0]['stop_further_writes'])
        self.shop.update_description.assert_not_called()
        self.shop.read_product.side_effect = lambda _: copy.deepcopy(self.product)
        self.save.side_effect = RuntimeError('disk full')
        self.assertTrue(self.run_enrich()[0]['stop_further_writes'])
        self.shop.update_description.assert_not_called()

    def test_title_repair_does_not_require_unsafe_partial_inci(self):
        self.product['title'] = 'Korean source title'
        self.entry['draft_reasons'] = ['ingredients_missing', 'english_title_missing', 'owner_category_fallback_draft_only', 'safety_evidence_unverified_owner_draft_only']
        self.label.return_value = {'html': 'partial must not write', 'reasons': ['inci_unresolved:7', 'us_regulatory_review_functional_or_drug_like']}
        self.shop.update_draft_content.side_effect = lambda _, html, title: self.product.update(descriptionHtml=html, title=title)
        result = d.enrich(self.shop, self.registry, self.collect, self.label, self.save,
            title_overrides={'1069430': {'shopify_id': self.entry['shopify_id'], 'title': '46cm Body Wash Refreshing Herbal 225 mL'}})
        self.assertEqual(result[0]['status'], 'title_enriched_label_review_required')
        self.assertEqual(self.product['descriptionHtml'], '<p>Original</p>')
        self.assertNotIn('ingredients_missing', self.entry['draft_reasons'])
        self.assertNotIn('english_title_missing', self.entry['draft_reasons'])
        self.assertIn('inci_unresolved:7', self.entry['draft_reasons'])
        self.assertIn('owner_category_fallback_draft_only', self.entry['draft_reasons'])
        self.assertIn('safety_evidence_unverified_owner_draft_only', self.entry['draft_reasons'])
        self.assertEqual(self.entry['draft_reason_history'][0]['before'][0], 'ingredients_missing')

    def test_exact_inspected_concentration_and_source_footnotes_preserved(self):
        import daiso_daily_beauty_to_shopify as daily
        sg = Mock()
        sg.to_inci.return_value = ('Water, HYDROLYZED SODIUM HYALURONATE', [], [], [])
        raw = '정제수, 하이드롤라이즈드소듐하이알루로네이트(100 ppm)'
        g = dict(ingredients=raw, volume='40 mL', maker='Maker', origin='대한민국')
        with patch.object(daily, '_inci_resolver', return_value=(sg, Mock())):
            result = daily.build_us_label('1060646', 'cream', g)
        self.assertIn('Hydrolyzed Sodium Hyaluronate (100 ppm)', result['html'])
        self.assertEqual(g['ingredients'], raw)
        g['ingredients'] = '정제수, 세린*, 1,2-헥산다이올'
        with patch.object(daily, '_inci_resolver', return_value=(sg, Mock())):
            daily.build_us_label('1069430', 'body', g)
        self.assertEqual(sg.to_inci.call_args.args[0], '정제수, 세린, 1,2-헥산다이올')
        self.assertEqual(g['ingredients'], '정제수, 세린*, 1,2-헥산다이올')

    def test_complete_cached_notice_survives_outage_and_retains_functional_hold(self):
        import json
        import tempfile
        from pathlib import Path
        import daiso_daily_beauty_to_shopify as daily
        facts = dict(ingredients='정제수', volume='225 mL', maker='Maker', origin='대한민국',
                     functional='여드름성 피부 완화 기능성 화장품', expiry='제조일로부터 36개월')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/gosi.json').write_text(json.dumps({'items': {'1069430': facts}}), encoding='utf-8')
            with patch.object(daily, 'ROOT', root), patch.object(daily, 'gosi_from_api', side_effect=AssertionError('no network')) as api:
                gosi = daily.collect_gosi('1069430', allow_ai=False)
            api.assert_not_called()
        self.assertTrue(gosi['gosi_ok'])
        self.assertEqual(gosi['functional'], facts['functional'])
        sg = Mock()
        sg.to_inci.return_value = ('Water', [], [], [])
        with patch.object(daily, '_inci_resolver', return_value=(sg, Mock())):
            label = daily.build_us_label('1069430', 'Body Wash', gosi)
        self.assertIn('us_regulatory_review_functional_or_drug_like', label['reasons'])

    def test_body_fragrance_concentration_is_not_silently_lost(self):
        import daiso_daily_beauty_to_shopify as daily
        sg = Mock()
        sg.to_inci.return_value = ('Water, Fragrance, Glycerin', [], [], [])
        g = dict(ingredients='정제수, 향료(리프레싱 허벌향 1.21%), 글리세린', volume='225 mL', maker='Maker', origin='대한민국')
        with patch.object(daily, '_inci_resolver', return_value=(sg, Mock())):
            result = daily.build_us_label('1069430', 'Body Wash', g)
        self.assertIn('Fragrance (1.21%)', result['html'])

    def test_rendered_capture_expands_and_reaches_stable_bottom(self):
        import daiso_notice_recovery as r
        api = MagicMock()
        page = api.sync_playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_page.return_value
        page.locator.return_value.count.return_value = 1
        page.locator.return_value.evaluate_all.return_value = [
            {'url': 'https://cdn.daisomall.co.kr/description/bottom.jpg', 'alt': '전성분: 정제수'},
            {'url': 'https://cdn.daisomall.co.kr/banner.jpg', 'alt': 'not product notice'}]
        page.evaluate.return_value = [10000, 10000]
        with patch.dict('sys.modules', {'playwright': MagicMock(), 'playwright.sync_api': api}):
            evidence = r.rendered_notice('1069430')
        page.locator.return_value.first.click.assert_called_once()
        self.assertEqual(page.mouse.wheel.call_count, 3)
        self.assertTrue(evidence['reached_bottom'])
        self.assertEqual(len(evidence['images']), 1)
        self.assertEqual(evidence['fields']['ingredients'], '정제수')

    def test_ocr_has_fixed_bounds_and_candidate_only(self):
        import daiso_notice_recovery as r
        fake = Mock()
        fake.download.return_value = b'image'
        fake._tess.return_value = '전성분: 정제수'.encode()
        with patch.dict('sys.modules', {'daiso.localize_detail_images': fake}):
            rows = r.ocr_notice([{'url': str(i)} for i in range(20)], max_images=2)
        self.assertEqual([row['url'] for row in rows], ['19', '18'])
        self.assertTrue(all(row['review_required'] for row in rows))
        self.assertEqual(fake._tess.call_count, 2)


if __name__ == '__main__':
    unittest.main()
