"""Offline pure regressions with synthetic source authority, never real data."""
import copy
import unittest
from unittest.mock import patch

import ai_shopping_copy as shopping
import gemini_listing_copy as gemini
import build_listing_copy_local as local


def evidence(field, text):
    return {field: {'pd_no': '1', 'field': field, 'verified': True,
                    'source_type': 'product_label', 'source_ref': 'fixture:label:1',
                    'source_quote': text, 'text': text, 'language': 'en'}}


class ShoppingTest(unittest.TestCase):
    def test_identity_type_size_and_missing_authority(self):
        value = shopping.build_shopping_copy('Example', 'Face Serum', '30 ml')
        self.assertEqual(value['recommendation_target'], 'For shoppers looking for face serum.')
        self.assertEqual(value['usage_scenario'], '')
        self.assertEqual(value['not_recommended_conditions'], '')
        self.assertEqual(len(value['omission_reasons']), 2)
        self.assertEqual([f['answer'] for f in value['faq']], ['Example', 'Face Serum', '30 ml'])
        empty = shopping.build_shopping_copy('')
        self.assertEqual(empty['faq'], [])
        self.assertEqual(len(empty['omission_reasons']), 3)

    def test_no_skin_or_application_inference(self):
        gate = {'agent_ready': True, 'pd_no': '1',
                'us_label': {'ingredients_inci': 'Retinol', 'directions': 'Apply nightly'},
                'owner_verified': True}
        value = local.local_copy('VT 레티놀 세럼 30 ml', gate)['ai_shopping_copy']
        self.assertEqual(value['usage_scenario'], '')
        self.assertEqual(value['not_recommended_conditions'], '')
        self.assertNotIn('sensitive', str(value))

    def test_exact_product_field_quotation_required(self):
        source = evidence('directions', 'Apply one drop.')
        source.update(evidence('warnings', 'Do not use on broken skin.'))
        result = shopping.build_shopping_copy('Example', pd_no='1', field_evidence=source)
        self.assertEqual(result['usage_scenario'], 'Apply one drop.')
        self.assertEqual(result['not_recommended_conditions'], 'Do not use on broken skin.')
        for key, bad in (('pd_no', '2'), ('field', 'ingredients'), ('verified', False),
                         ('source_type', 'owner_declaration'), ('source_ref', ''),
                         ('source_quote', 'Different text'), ('language', 'ko')):
            with self.subTest(key=key):
                changed = copy.deepcopy(source)
                changed['directions'][key] = bad
                value = shopping.build_shopping_copy('Example', pd_no='1', field_evidence=changed)
                self.assertEqual(value['usage_scenario'], '')

    def test_english_tag_does_not_authorize_korean_quote(self):
        for field, slot in (('directions', 'usage_scenario'),
                            ('warnings', 'not_recommended_conditions')):
            for quote in ('매일 바르세요.', 'Apply 매일.', '\u1100\u1161', '&#47588;&#51068;'):
                with self.subTest(field=field, quote=quote):
                    value = shopping.build_shopping_copy(
                        'Accepted English Title', pd_no='1',
                        field_evidence=evidence(field, quote))
                    self.assertEqual(value[slot], '')
                    self.assertIn(slot, value['omission_reasons'])
                    self.assertFalse(any(faq['answer'] == quote for faq in value['faq']))

    def test_accepted_english_identity_preserves_canonical_evidence_binding(self):
        product = {'pd_no': '1', 'name': 'VT 레티놀 세럼 30 ml'}
        authority = evidence('directions', 'Apply one drop.')
        authority.update(evidence('warnings', 'Do not use on broken skin.'))
        gate = {'pd_no': '1', 'agent_ready': True, 'field_evidence': authority}
        response = {'title': 'Accepted English Serum 30 ml',
                    'description_html': '<p>Accepted English copy.</p>',
                    'seo_title': 'Serum', 'seo_description': 'English',
                    'tags': ['serum'], 'product_type': 'Serum'}
        before = copy.deepcopy((product, gate, response))
        with patch.object(gemini, 'generate', return_value=(response, '')) as model:
            generated, error = gemini.new_copy('', '', product, gate)
            wrong_gate = copy.deepcopy(gate)
            for record in wrong_gate['field_evidence'].values():
                record['pd_no'] = '2'
            wrong, _ = gemini.new_copy('', '', product, wrong_gate)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(error, '')
        local_result = local.local_copy(product['name'], gate)
        for result in (generated, local_result):
            semantic = result['ai_shopping_copy']
            self.assertFalse(any('\u1100' <= c <= '\u11ff' or '\uac00' <= c <= '\ud7ff'
                                 for text in shopping.text_values(semantic) for c in text))
            self.assertEqual(semantic['faq'][0]['answer'], result['title'])
            self.assertEqual(semantic['usage_scenario'], 'Apply one drop.')
            self.assertEqual(semantic['not_recommended_conditions'], 'Do not use on broken skin.')
            self.assertNotIn(product['name'], result['description_html'])
        self.assertEqual(wrong['ai_shopping_copy']['usage_scenario'], '')
        self.assertEqual(wrong['ai_shopping_copy']['not_recommended_conditions'], '')
        self.assertEqual((product, gate, response), before)

    def test_unknown_korean_identity_and_size_are_not_invented_as_english(self):
        name = 'Unknown 이름 세럼'
        result = local.local_copy(name, {'us_label': {'net_contents': '10매'}})
        self.assertEqual(result['title'], name)
        semantic = result['ai_shopping_copy']
        self.assertIn('faq_identity', semantic['omission_reasons'])
        self.assertIn('faq_size', semantic['omission_reasons'])
        for value in shopping.text_values(semantic['faq']):
            self.assertFalse(any('\uac00' <= char <= '\ud7ff' for char in value))

    def test_html_escaped_idempotent_and_inputs_unchanged(self):
        base = {'title': 'Existing', 'description_html': '<p>Original</p>', 'tags': ['one']}
        authority = evidence('directions', 'Use <one> & "two".')
        before = copy.deepcopy((base, authority))
        kwargs = dict(pd_no='1', field_evidence=authority)
        result = shopping.append_shopping_copy(base, 'Name <b>X</b>', 'Face Serum', '30 ml & 2', **kwargs)
        self.assertTrue(result['description_html'].startswith(base['description_html']))
        self.assertIn('&lt;one&gt; &amp; &quot;two&quot;', result['description_html'])
        self.assertNotIn('<b>', result['description_html'])
        self.assertNotIn('Not recommended conditions', result['description_html'])
        self.assertEqual(result, shopping.append_shopping_copy(result, 'Name <b>X</b>', 'Face Serum', '30 ml & 2', **kwargs))
        self.assertEqual((base, authority), before)
        result['tags'].append('two')
        self.assertEqual(base['tags'], ['one'])

    def test_recursive_banned_checks_every_new_field(self):
        paths = [lambda s: {'recommendation_target': s}, lambda s: {'usage_scenario': s},
                 lambda s: {'not_recommended_conditions': s},
                 lambda s: {'faq': [{'question': s, 'answer': 'fine'}]},
                 lambda s: {'faq': [{'question': 'fine', 'answer': s}]},
                 lambda s: {'omission_reasons': {'usage': s}},
                 lambda s: {'unknown': [{'nested': [s]}]}]
        with patch.object(gemini, 'BANNED', ['forbidden']):
            for make in paths:
                self.assertEqual(gemini.find_banned(make('FoRbIdDeN')), ['forbidden'])
            self.assertEqual(gemini.find_banned({'x': 'forbidd&#101;n'}), ['forbidden'])
            with self.assertRaises(ValueError):
                local.local_copy('Forbidden 세럼', {})

    def test_gemini_success_only_one_existing_call_and_no_model_advice(self):
        response = {'title': 'Model title', 'description_html': '<p>Base.</p>',
                    'seo_title': 'Title', 'seo_description': 'Description', 'tags': ['serum'],
                    'product_type': 'Invented cream',
                    'ai_shopping_copy': {'usage_scenario': 'Apply nightly for sensitive skin.'}}
        product = {'pd_no': '1', 'name': 'VT 세럼 30 ml'}
        gate = {'pd_no': '1', 'agent_ready': True}
        original = copy.deepcopy((response, product, gate))
        with patch.object(gemini, 'generate', return_value=(response, '')) as model, \
                patch.object(gemini, 'http_json', side_effect=AssertionError('network')):
            result, error = gemini.new_copy('', '', product, gate)
        model.assert_called_once()
        self.assertEqual(error, '')
        self.assertIn('face serum', result['ai_shopping_copy']['recommendation_target'])
        self.assertIn('30 ml', result['description_html'])
        self.assertNotIn('Apply nightly', result['description_html'])
        self.assertEqual((response, product, gate), original)

    def test_blocked_and_failed_generation_are_not_enriched(self):
        with patch.object(gemini, 'generate', side_effect=AssertionError('blocked provider')):
            self.assertIsNone(gemini.new_copy('', '', {}, {'agent_ready': False})[0])
        with patch.object(gemini, 'generate', return_value=(None, 'failure')):
            self.assertEqual(gemini.new_copy('', '', {}, {'agent_ready': True}), (None, 'failure'))

    def test_carried_copy_untouched_and_blocked_previous_still_empty(self):
        for mode in ('manual_verified', 'gemini', local.LOCAL_MODE):
            previous = {'copy_status': 'ok', 'generation_mode': mode,
                        'copy': {'title': 'Old', 'description_html': '<p>Exact old.</p>',
                                 'metadata': {'reviewed': True}}}
            snapshot = copy.deepcopy(previous)
            with patch.object(gemini, 'generate', side_effect=AssertionError('provider')), \
                    patch.object(gemini, 'append_shopping_copy', side_effect=AssertionError('enrichment')):
                result, error = gemini.new_copy('', '', {}, {'agent_ready': True}, previous=previous)
                self.assertEqual(result, previous['copy'])
                self.assertEqual(error, '')
                self.assertIsNone(gemini.new_copy('', '', {}, {'agent_ready': False}, previous=previous)[0])
            self.assertEqual(previous, snapshot)

    def test_generate_rejects_nested_banned_model_faq_offline(self):
        import json
        response = dict.fromkeys(gemini.REQUIRED, 'safe')
        response['faq'] = [{'answer': {'deep': ['Forbidden']}}]
        payload = {'candidates': [{'content': {'parts': [{'text': json.dumps(response)}]}}]}
        with patch.object(gemini, 'BANNED', ['forbidden']), \
                patch.object(gemini, 'http_json', return_value=payload) as network, \
                patch.object(gemini.time, 'sleep'), patch.object(gemini, 'RETRIES', 1):
            result, error = gemini.generate('fixture', 'fixture', {})
        self.assertIsNone(result)
        self.assertIn('forbidden', error)
        network.assert_called_once()

    def test_new_evidence_banned_rejects_entire_copy(self):
        response = dict.fromkeys(gemini.REQUIRED, 'safe')
        source = evidence('warnings', 'Forbidden warning')
        with patch.object(gemini, 'BANNED', ['forbidden']), \
                patch.object(gemini, 'generate', return_value=(response, '')):
            result, error = gemini.new_copy('', '', {'pd_no': '1', 'name': 'VT 세럼'},
                                            {'agent_ready': True, 'field_evidence': source})
        self.assertIsNone(result)
        self.assertIn('forbidden', error)


class ShoppingAccuracyFlowTest(unittest.TestCase):
    """Run entry points only against isolated files and mocked providers."""

    def run_gemini_fixture(self, *, previous=None, unsupported=(), conflicts=()):
        import io
        import json
        import tempfile
        from contextlib import ExitStack, redirect_stdout
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            product = {'pd_no': '1', 'name': 'VT PDRN 크림 50 ml'}
            gate = {'pd_no': '1', 'agent_ready': True,
                    'us_label': {'net_contents': '50 ml'}}
            source, gate_path, out = (root / name for name in ('source.json', 'gate.json', 'copy.json'))
            signature = {'fixture': True}
            source.write_text(json.dumps({'recommendations': [product]}), encoding='utf-8')
            gate_path.write_text(json.dumps({'agent_input_signature': signature, 'items': [gate]}), encoding='utf-8')
            if previous is not None:
                out.write_text(json.dumps({'items': [previous]}), encoding='utf-8')
            for key, value in (('ROOT', root), ('SRC', source), ('GATE', gate_path),
                               ('OUT', out), ('FULL', root / 'absent.json')):
                stack.enter_context(patch.object(gemini, key, value))
            stack.enter_context(patch.object(gemini, '_agent_input_signature', return_value=signature))
            stack.enter_context(patch.dict(gemini.os.environ, {'GEMINI_API_KEY': 'fixture-not-a-real-key'}))
            stack.enter_context(patch.object(gemini.time, 'sleep'))
            network = stack.enter_context(patch.object(gemini, 'http_json', side_effect=AssertionError('network')))
            pick = stack.enter_context(patch.object(gemini, 'pick_model', return_value=('fixture', 'mocked')))
            model = stack.enter_context(patch.object(gemini, 'new_copy', return_value=(
                {'title': 'Unsupported model wording', 'description_html': '<p>Untrusted.</p>'}, '')))
            report = {'unsupported_fields': list(unsupported), 'source_conflicts': list(conflicts),
                      'human_review_required': True, 'publication_allowed': False}
            review = stack.enter_context(patch.object(gemini.product_accuracy, 'review_copy', return_value=report))
            select = stack.enter_context(patch.object(
                gemini.product_accuracy, 'select_copy',
                side_effect=lambda product, candidate, fallback, root: (copy.deepcopy(fallback), dict(report))))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(gemini.main(), 0)
            payload = json.loads(out.read_text(encoding='utf-8'))
            calls = {'network': network.call_count, 'pick': pick.call_count,
                     'model': model.call_count, 'review': review.call_count, 'select': select.call_count}
            return payload, calls

    def test_cached_text_never_carries_an_old_accuracy_approval(self):
        text = {'title': 'Human copy', 'description_html': '<p>Exact human text.</p>',
                'review_metadata': {'reviewed': True}}
        for old_status in ('ok', 'review_required'):
            for unsupported, conflicts in ((('title',), ()), ((), ('net_contents',))):
                with self.subTest(old_status=old_status, unsupported=unsupported, conflicts=conflicts):
                    payload, calls = self.run_gemini_fixture(
                        previous={'pd_no': '1', 'copy_status': old_status, 'copy': text},
                        unsupported=unsupported, conflicts=conflicts)
                    self.assertEqual(payload['items'][0]['copy'], text)
                    self.assertEqual(payload['items'][0]['copy_status'], 'review_required')
                    self.assertEqual(payload['review_required'], 1)
                    self.assertEqual(payload['ok'], 0)
                    self.assertEqual(calls, {'network': 0, 'pick': 0, 'model': 0, 'review': 1, 'select': 0})

    def test_new_model_still_passes_through_upstream_neutral_selection(self):
        payload, calls = self.run_gemini_fixture(unsupported=('description_html',))
        self.assertEqual(calls['select'], 1)
        self.assertEqual(calls['model'], 1)
        self.assertEqual(calls['network'], 0)
        row = payload['items'][0]
        self.assertEqual(row['copy_status'], 'ok')
        self.assertIn('Product FAQ', row['copy']['description_html'])
        self.assertNotIn('Untrusted', row['copy']['description_html'])
        self.assertFalse(row['product_accuracy']['publication_allowed'])

    def test_source_conflict_holds_new_draft_after_selection(self):
        payload, calls = self.run_gemini_fixture(conflicts=('net_contents',))
        self.assertEqual(calls['select'], 1)
        self.assertEqual(payload['items'][0]['copy_status'], 'review_required')
        self.assertEqual(payload['review_required'], 1)
        self.assertEqual(payload['ok'], 0)

    def test_neutral_faq_markup_is_admitted_without_weakening_accuracy(self):
        import tempfile
        from pathlib import Path
        product = {'pd_no': '1', 'name': 'VT PDRN 크림 50 ml'}
        neutral = local.local_copy(product['name'], {'pd_no': '1', 'us_label': {'net_contents': '50 ml'}})
        with tempfile.TemporaryDirectory() as directory:
            report = gemini.product_accuracy.review_copy(product, neutral, neutral, Path(directory))
        self.assertEqual(report['unsupported_fields'], [])
        self.assertFalse(report['publication_allowed'])
        self.assertTrue(report['human_review_required'])
        self.assertNotIn('<!--', neutral['description_html'])
        self.assertNotIn('<h3>', neutral['description_html'])
        updated = shopping.append_shopping_copy(neutral, neutral['title'], neutral['product_type'], '100 ml')
        self.assertEqual(updated['description_html'].count('Product FAQ'), 1)
        self.assertNotIn('>50 ml</p>', updated['description_html'])


if __name__ == '__main__':
    unittest.main()
