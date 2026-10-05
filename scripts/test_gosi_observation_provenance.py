"""Synthetic offline regression fixtures; never invoke providers."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
from pathlib import Path as _ScriptPath
sys.path.insert(0,str(_ScriptPath(__file__).resolve().parents[1]))
from scripts import gosi_observation_history as h
from scripts import extract_gosi_vision as v
from scripts import collect_daiso_gosi as c
from scripts.daiso import collect_gosi_alt as a
import urllib.error
import io

class ProvenanceTests(unittest.TestCase):
    def test_s_grade_seed_is_identity_only_and_preserves_existing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'recommendations.json'
            src.write_text(json.dumps({'recommendations':[
                {'grade':'S','pd_no':'1049275','name':'known'},
                {'grade':'S','pd_no':'1049276','name':'new observation target'},
                {'grade':'B','pd_no':'1049285','name':'not selected'},
                {'grade':'S','pd_no':'1234567890123456789','name':'wrong long identity'}]}))
            items={'1049275':{'product_id':'1049275','maker':'human evidence','captured_at':'original source clock'}}
            original=copy.deepcopy(items['1049275'])
            with patch.object(c,'S_RECOMMENDATIONS',src), patch.object(c.urllib.request,'urlopen',side_effect=AssertionError('no HTTP')):
                added=c.seed_from_s_grade(items)
            self.assertEqual(added,['1049276'])
            self.assertEqual(items['1049275'],original)
            self.assertFalse(items['1049276']['product_identity_verified'])
            for clock in ('captured_at','observed_at','updated_at','source_received_at'):
                self.assertNotIn(clock,items['1049276'])

    def test_shape_identity(self):
        for doc in ({'items': []}, {'items': {'a': None}}, {'items': {'a': {'pd_no': 'b'}}}, {'items': [{'pd_no': 'a'}, {'pd_no': 'a'}]}):
            with self.assertRaises(ValueError): h.validate_document(doc)
        h.validate_document({'items': {'a': {'unknown': {'opaque': True}}}})

    def test_fill_verification_conflict_empty(self):
        row = {'maker': 'human', 'verified': True}
        self.assertFalse(h.observe_field(row, 'maker', 'machine', {'observed_at': 'real-clock'}))
        self.assertEqual(row['maker'], 'human')
        self.assertTrue(row['reconciliation_blocked'])
        self.assertFalse(h.observe_field(row, 'origin', '', {}))
        self.assertNotIn('origin', row)
        self.assertTrue(h.observe_field(row, 'origin', 'country', {'model': 'fixture', 'image': 'a', 'observed_at': 'clock'}))
        self.assertFalse(row['verified'])
        self.assertFalse(row['field_observations']['origin']['verified'])
        self.assertNotIn('maker', row['field_observations'])

    def test_retention_partial_images(self):
        row = {'gosi_images': ['old'], 'detail_images': ['old-url'], 'gosi_image': 'old', 'field_observations': {'maker': {'observed_at': 'original'}}, 'image_observations': {'old': {'url': 'old-url', 'observed_at': 'original'}}}
        h.mark_stale(row)
        h.merge_images(row, ['new-url'], ['new'], {'new': {'url': 'new-url', 'sha256': 'hash', 'observed_at': 'new'}})
        self.assertEqual(row['gosi_images'], ['old', 'new'])
        self.assertEqual(row['gosi_image'], 'old')
        self.assertEqual(row['image_observations']['old']['observed_at'], 'original')
        self.assertTrue(row['image_observations']['old']['stale'])

    def test_diagnostic_only(self):
        old = {'items': {'a': {'ingredients': 'fact', 'gosi_images': ['old'], '텍스트_미수집': ['origin']}}, 'vision_deferred': ['a'], 'vision_failures': [{'pd_no': 'a', 'reason': 'failure'}]}
        current = copy.deepcopy(old)
        current['vision_deferred'] = []
        current['vision_failures'] = []
        current['items']['a']['텍스트_미수집'] = []
        self.assertTrue(h.replacement_ids(old, current, {'identity_fields': ['pd_no', 'product_id']}))
        for kind in ('fact', 'image', 'id'):
            bad = copy.deepcopy(current)
            if kind == 'fact': del bad['items']['a']['ingredients']
            elif kind == 'image': bad['items']['a']['gosi_images'] = []
            else: del bad['items']['a']
            with self.assertRaises(ValueError): h.replacement_ids(old, bad, {'identity_fields': ['pd_no', 'product_id']})

    def test_groq_only_eager_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / 'fixture.jpg'
            img.write_bytes(b'x' * 600)
            with patch.object(v, 'groq_key', return_value='synthetic'), patch.object(v, 'read_table_groq', return_value=({'origin': 'country', '_model': 'groq:fixture'}, '')):
                got, error = v.read_table('', [], img, 'fixture')
            self.assertEqual(got['_model'], 'groq:fixture')

    def test_typed_stop_and_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / 'fixture.jpg'
            img.write_bytes(b'x' * 600)
            with patch.object(v, 'http_json', side_effect=v.ProviderStop('fixture', 429)) as call, patch.object(v, 'groq_key', return_value='synthetic'):
                with self.assertRaises(v.ProviderStop): v.read_table('synthetic', ['a', 'b'], img)
                self.assertEqual(call.call_count, 1)
            with patch.object(v, 'DEADLINE', 0):
                with self.assertRaises(v.DeadlineStop): v.call_timeout()

    def test_exact_history_offline(self):
        old = {'items': {'a': {'maker': 'fact'}}, 'vision_deferred': ['a']}
        now = copy.deepcopy(old)
        now['vision_deferred'] = []
        base = (json.dumps(old) + '\n').encode()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data').mkdir()
            (root / 'config').mkdir()
            (root / 'data/gosi.json').write_bytes(base)
            (root / 'config/publish_policy.json').write_text(json.dumps({'identity_fields': ['pd_no', 'product_id']}))
            with patch.object(h, 'exact_head', return_value=base): result = h.publish_observation(root, now)
            self.assertEqual(result['baseline_sha256'], h.sha(base))
            self.assertEqual((root / h.HISTORY_PATH / (h.sha(base) + '.json')).read_bytes(), base)
            current = (root / 'data/gosi.json').read_bytes()
            manifest = json.loads((root / h.MANIFEST_PATH).read_bytes())
            self.assertEqual(manifest['deletions'][0]['replacement_sha256'], h.sha(current))
            self.assertFalse((root / h.LOCK_PATH).exists())


    def test_nochange_clocks_and_provider_failure_preserve_oldfacts(self):
        row = {'maker': 'human', 'ingredients': 'old fact', 'captured_at': 'old', 'generated_at': 'old', 'gosi_images': ['old'], '텍스트_미수집': ['volume']}
        before = copy.deepcopy(row)
        with tempfile.TemporaryDirectory() as tmp, patch.object(c, 'IMGDIR', Path(tmp)), patch.object(c, 'post', return_value=None), patch.object(c.time, 'sleep'):
            c.collect_one('fixture', row)
        for key in before: self.assertEqual(row[key], before[key])
        self.assertEqual([x['status'] for x in row['observation_attempts']], ['failed', 'failed'])

    def test_receipt_bytes_and_clock_after_read(self):
        raw = b'{"success":true,"data":[]}'
        with patch.object(c.urllib.request, 'urlopen', return_value=io.BytesIO(raw)), patch.object(h, 'utcnow', return_value='actual-receive'):
            got = c.post('/fixture', 'fixture')
        self.assertEqual(got['_receipt']['received_at'], 'actual-receive')
        self.assertEqual(got['_receipt']['sha256'], h.sha(raw))
        self.assertEqual(got['_receipt']['byte_count'], len(raw))

    def test_field_exact_response_provenance_and_parser_only_scope(self):
        evidence = h.receipt(b'country', 'fixture')
        row = {}
        c.set_if_empty(row, 'origin', 'country', 'api', evidence)
        self.assertEqual(row['field_observations']['origin']['received_at'], evidence['received_at'])
        self.assertEqual(row['field_observations']['origin']['sha256'], evidence['sha256'])
        c.set_if_empty(row, 'volume', '5ml', 'product_name')
        self.assertEqual(row['field_observations']['volume']['capture_scope'], 'local_parser_only')
        self.assertIsNone(row['field_observations']['volume']['source_received_at'])
        self.assertNotIn('received_at', row['field_observations']['volume'])

    def test_placeholders_never_fill_or_replace_facts(self):
        row = {'maker': 'human'}
        for value in ('', '-', '상세페이지 참조', '없음'):
            self.assertFalse(c.set_if_empty(row, 'origin', value, 'fixture'))
        c.set_if_empty(row, 'maker', '', 'fixture')
        self.assertEqual(row['maker'], 'human')
        self.assertNotIn('origin', row)

    def test_network_google_errors_stop_no_fallback_no_retry(self):
        for exc in (urllib.error.URLError('HTTP Error 429'), RuntimeError('RESOURCE_EXHAUSTED'), RuntimeError('API_KEY_INVALID'), urllib.error.HTTPError('https://fixture', 401, 'unauthenticated', {}, io.BytesIO(b'{}'))):
            with patch.object(v.urllib.request, 'urlopen', side_effect=exc) as call:
                with self.assertRaises(h.ProviderStop): v.http_json('https://fixture')
                self.assertEqual(call.call_count, 1)
        with patch.object(v, 'http_json', side_effect=h.ProviderStop('gemini', 403)) as call:
            with self.assertRaises(h.ProviderStop): v.pick_models('synthetic')
            self.assertEqual(call.call_count, 1)

    def test_persisted_stop_force_bypasses_nothing(self):
        doc = {'items': {'a': {}}, 'provider_stops': [{'provider': 'gemini', 'code': 429, 'category': 'quota'}]}
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'gosi.json'; f.write_text(json.dumps(doc))
            with patch.object(v, 'GOSI', f), patch.object(v, 'pick_models') as call, patch.object(v.sys, 'argv', ['vision', '--force']):
                self.assertEqual(v.main(), 0); call.assert_not_called()
            doc['provider_stops'][0]['provider'] = 'daiso'; f.write_text(json.dumps(doc))
            with patch.object(c, 'GOSI', f), patch.object(c, 'collect_one') as call:
                self.assertEqual(c.main(), 0); call.assert_not_called()
            with patch.object(a, 'GOSI', f), patch.object(a.sys, 'argv', ['alt', '--force', 'a']):
                self.assertEqual(a.main(), 0)

    def test_rendered_scope_requires_bound_source_bytes(self):
        alt = '제조국: country'
        row = {}
        self.assertEqual(a.apply_alt(row, alt, [], 'a', 'rendered_alt_partial_page'), [])
        self.assertNotIn('origin', row)
        evidence = h.receipt(alt.encode(), 'fixture', 'browser_response_application_bytes')
        self.assertEqual(a.apply_alt(row, alt, [{'receipt': evidence, 'text': alt}], 'a', 'rendered_alt_partial_page'), ['origin'])
        observed = row['field_observations']['origin']
        self.assertEqual(observed['source_received_at'], evidence['received_at'])
        self.assertFalse(observed['product_identity_verified'])
        self.assertFalse(row['verified'])

    def test_vision_scope_payload_and_unknown_source_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); img = root / 'fixture.jpg'; img.write_bytes(b'x' * 600)
            row = {'volume': '5ml'}
            got = {'origin': 'country', '_provenance': h.receipt(b'fixture-response', 'fixture', 'provider_response_only')}
            with patch.object(v, 'ROOT', root):
                self.assertEqual(v.apply_vision(row, got, img, 'a'), ['origin'])
            observed = row['field_observations']['origin']
            self.assertIsNone(observed['source_received_at'])
            self.assertEqual(observed['capture_scope'], 'single_image_or_crop_model_transcription')
            self.assertEqual(observed['source_image_sha256'], h.sha(img.read_bytes()))
            self.assertFalse(observed['human_verified'])

    def test_empty_field_fill_and_clock_overwrite_rejected(self):
        before = {'items': {'a': {'origin': '', 'captured_at': 'old'}}, 'generated_at': 'old'}
        current = copy.deepcopy(before)
        h.observe_field(current['items']['a'], 'origin', 'country', h.receipt(b'country', 'fixture'))
        h.replacement_ids(before, current, {'identity_fields': ['pd_no', 'product_id']})
        for clock in ('captured_at', 'generated_at'):
            bad = copy.deepcopy(current)
            if clock == 'captured_at': bad['items']['a'][clock] = 'new'
            else: bad[clock] = 'new'
            with self.assertRaises(ValueError): h.replacement_ids(before, bad, {'identity_fields': ['pd_no', 'product_id']})

    def test_image_union_observation_no_refresh(self):
        row = {'detail_images': ['url'], 'gosi_images': ['path'], 'image_observations': {'path': {'received_at': 'original', 'sha256': 'old'}}}
        h.merge_images(row, ['url', 'new-url', 'url'], ['path', 'new', 'path'], {'path': {'received_at': 'fake-new', 'sha256': 'new'}})
        self.assertEqual(row['detail_images'], ['url', 'new-url'])
        self.assertEqual(row['gosi_images'], ['path', 'new'])
        self.assertEqual(row['image_observations']['path']['received_at'], 'original')

    def test_history_update_prior_new_tamper_and_shared_lock(self):
        doc = {'items': {'a': {'maker': 'fact'}}, 'vision_deferred': ['a']}
        base = (json.dumps(doc) + '\n').encode()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'data').mkdir(); (root / 'config').mkdir()
            target = root / 'data/gosi.json'; target.write_bytes(base)
            (root / 'config/publish_policy.json').write_text(json.dumps({'identity_fields': ['pd_no', 'product_id']}))
            current = copy.deepcopy(doc); current['vision_deferred'] = []
            with patch.object(h, 'exact_head', return_value=base): h.publish_observation(root, current)
            prior = target.read_bytes(); h.attempt(current['items']['a'], 'attempt-only', 'fixture', 'failed')
            with patch.object(h, 'exact_head', return_value=base): result = h.publish_observation(root, current)
            self.assertEqual(result['prior_sha256'], h.sha(prior))
            for raw in (base, prior, target.read_bytes()): self.assertEqual((root / h.HISTORY_PATH / (h.sha(raw) + '.json')).read_bytes(), raw)
            manifest = json.loads((root / h.MANIFEST_PATH).read_bytes())
            self.assertEqual(manifest['deletions'][0]['replacement_sha256'], h.sha(target.read_bytes()))
            lock = root / h.LOCK_PATH; lock.write_bytes(b'other-writer')
            with patch.object(h, 'exact_head', return_value=base), self.assertRaises(FileExistsError): h.publish_observation(root, current)
            self.assertEqual(lock.read_bytes(), b'other-writer'); lock.unlink()
            (root / h.HISTORY_PATH / (h.sha(base) + '.json')).write_bytes(b'tampered')
            with patch.object(h, 'exact_head', return_value=base), self.assertRaises(ValueError): h.publish_observation(root, current)
            self.assertFalse(lock.exists())


    def test_provider_response_bytes_fixture(self):
        raw = json.dumps({'candidates': [{'content': {'parts': [{'text': '{"origin":"country"}'}]}}]}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / 'fixture.jpg'; img.write_bytes(b'x' * 600)
            with patch.object(v.urllib.request, 'urlopen', return_value=io.BytesIO(raw)):
                got, err = v.read_table('synthetic', ['fixture'], img)
            self.assertEqual(err, '')
            self.assertEqual(got['_provenance']['sha256'], h.sha(raw))
            self.assertEqual(got['_provenance']['payload_image_sha256'], h.sha(img.read_bytes()))
            self.assertNotIn('synthetic', got['_provenance']['source'])
        raw_groq = json.dumps({'choices': [{'message': {'content': '{"origin":"country"}'}}]}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / 'fixture.jpg'; img.write_bytes(b'x' * 600)
            with patch.object(v.urllib.request, 'urlopen', return_value=io.BytesIO(raw_groq)):
                got, err = v.read_table_groq('synthetic', img, 'fixture')
            self.assertEqual(err, '')
            self.assertEqual(got['_provenance']['sha256'], h.sha(raw_groq))

    def test_current_run_stop_persisted_no_fact_missing_refresh(self):
        doc = {'items': {'a': {'maker': 'human', 'captured_at': 'original', '텍스트_미수집': ['origin']}}}
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'gosi.json'; f.write_text(json.dumps(doc))
            with patch.object(v, 'GOSI', f), patch.object(v.os.environ, 'get', return_value='synthetic'), patch.object(v, 'pick_models', side_effect=h.ProviderStop('gemini', 429)) as call, patch.object(v, 'publish_observation') as publish:
                self.assertEqual(v.main(), 0)
                self.assertEqual(call.call_count, 1)
                saved = publish.call_args.args[1]
                self.assertEqual(saved['provider_stops'][0]['code'], 429)
                self.assertEqual(saved['items'], doc['items'])
                self.assertNotIn('generated_at', saved)

if __name__ == '__main__': unittest.main()
