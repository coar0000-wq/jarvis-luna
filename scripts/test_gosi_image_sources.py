"""Synthetic, offline GOSI image selection and access-stop safety regressions."""
import copy
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from test_gosi_recovery_workflow import AuthenticatedGosiFixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, UnidentifiedImageError
from scripts import collect_daiso_gosi as c
from scripts import gosi_image_sources as s
from scripts import gosi_observation_history as h

BASE = 'https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo=1234567'
IMAGE = 'https://cdn.daisomall.co.kr/file/PD/20260402/example.jpg/dims/resize/850/quality/100'
VIDEO = 'https://cdn.daisomall.co.kr/file/PD/20260402/example.mp4/xcdr/preset/_mute_360p'


def pixels(fmt='JPEG'):
    out = io.BytesIO()
    Image.new('RGB', (12, 12), 'white').save(out, format=fmt)
    return out.getvalue()


class Response(io.BytesIO):
    def __init__(self, raw, mime='image/jpeg'):
        super().__init__(raw)
        self.headers = {'Content-Type': mime}


class ImageSelectionTests(AuthenticatedGosiFixture, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('Offline tests prohibit network'))
        cls.network.start()
        cls.addClassCleanup(cls.network.stop)

    def test_video_sources_never_become_image_candidates(self):
        html = f'<img src="{IMAGE}"><video><source src="{VIDEO}"><source src="{VIDEO}/.webm"></video><script src="{IMAGE}"></script><iframe src="{IMAGE}"></iframe>'
        self.assertEqual(s.image_candidates(html, BASE), [IMAGE])
        for path in (VIDEO, VIDEO + '/dims/resize/850', VIDEO.replace('.mp4', '.webm'), VIDEO.replace('.mp4', '%2Emp4')):
            self.assertEqual(s.image_candidates(f'<img src="{path}">', BASE), [])
            with patch.object(c.urllib.request, 'urlopen') as request:
                self.assertIsNone(c.download_image(path, Path('never.jpg')))
                request.assert_not_called()

    def test_lazy_srcset_and_markup_shapes_preserve_exact_url(self):
        large = IMAGE + '?width=1200&quality=90'
        html = f"<IMG SRC='data:image/gif;base64,AAA' DATA-SRC='{large.replace('&', '&amp;')}'><img src={IMAGE}><img src='{IMAGE}'>"
        self.assertEqual(s.image_candidates(html, BASE), [large, IMAGE])
        for attr in ('data-original', 'data-lazy-src'):
            self.assertEqual(s.image_candidates(f'<img {attr}="{IMAGE}" src="/placeholder.gif">', BASE), [IMAGE])
        for attr in ('srcset', 'data-srcset'):
            self.assertEqual(s.image_candidates(f'<img src="/placeholder.gif" {attr}="{IMAGE} 400w, {large.replace("&", "&amp;")} 1200w">', BASE), [large])
        self.assertEqual(s.image_candidates(f'<img srcset="{IMAGE}?x=a,b 2x, {IMAGE} 1x">', BASE), [IMAGE + '?x=a,b'])

    def test_picture_sources_only_and_ordinary_resolution(self):
        self.assertEqual(s.image_candidates(f'<source type="image/jpeg" srcset="{IMAGE}">', BASE), [])
        self.assertEqual(s.image_candidates(f'<picture><source type="image/jpeg" srcset="{IMAGE}"></picture>', BASE), [IMAGE])
        self.assertEqual(s.image_candidates(f'<picture><source type="video/mp4" srcset="{VIDEO}"></picture>', BASE), [])
        self.assertEqual(s.image_candidates('<img src="//cdn.daisomall.co.kr/file/a.jpg"><img src="/images/a.png">', BASE), ['https://cdn.daisomall.co.kr/file/a.jpg', 'https://www.daisomall.co.kr/images/a.png'])
        self.assertEqual(s.image_candidates(f'<picture><source type="image/webp" srcset="{IMAGE.replace(".jpg", ".webp")}"><img src="{IMAGE}"></picture>', BASE), [IMAGE.replace('.jpg', '.webp')])

    def test_encoded_text_is_not_new_markup_and_unsafe_urls_are_rejected(self):
        self.assertEqual(s.image_candidates(f'&lt;img src="{IMAGE}"&gt;', BASE), [])
        for value in ('http://cdn.daisomall.co.kr/a.jpg', 'https://user:password@cdn.daisomall.co.kr/a.jpg', 'https://untrusted.invalid/a.jpg', 'file:///tmp/a.jpg', 'https://cdn.daisomall.co.kr:99/a.jpg', 'https://cdn.daisomall.co.kr/a.svg'):
            self.assertEqual(s.image_candidates(f'<img src="{value}">', BASE), [])

    def test_image_request_retains_rendition_and_decodes_bytes(self):
        for fmt, mime, extension in [('JPEG', 'image/jpeg', '.jpg'), ('PNG', 'image/png', '.png'), ('WEBP', 'image/webp', '.webp')]:
            with self.subTest(fmt=fmt), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                url = IMAGE + '?signature=synthetic-secret'
                with patch.object(c, 'ROOT', root), patch.object(c.urllib.request, 'urlopen', return_value=Response(pixels(fmt), mime)) as request:
                    path, evidence = c.download_image(url, root / 'image.jpg')
                self.assertEqual(request.call_args.args[0].full_url, url)
                self.assertEqual(request.call_count, 1)
                self.assertTrue(path.endswith(extension))
                self.assertTrue((root / path).exists())
                self.assertEqual(evidence['source'], IMAGE)
                self.assertTrue(evidence['source_url_redacted'])
                self.assertNotIn('synthetic-secret', json.dumps(evidence))

    def test_mime_and_decodable_image_both_required(self):
        for raw, mime in [(b'<html>Forbidden</html>' * 50, 'image/jpeg'), (pixels(), 'video/mp4'), (pixels('PNG'), 'image/jpeg'), (pixels(), 'application/octet-stream'), (pixels()[:-2], 'image/jpeg')]:
            with self.subTest(mime=mime), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                with patch.object(c, 'ROOT', root), patch.object(c.urllib.request, 'urlopen', return_value=Response(raw, mime)):
                    self.assertIsNone(c.download_image(IMAGE, root / 'never.jpg'))
                self.assertEqual(list(root.iterdir()), [])

    def test_decode_error_address_is_not_an_http_stop(self):
        for code in (401, 403, 429):
            error = UnidentifiedImageError(
                f'cannot identify image file <_io.BytesIO object at 0x7f6dea{code}530>')
            with self.subTest(code=code), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                with patch.object(c, 'ROOT', root), patch.object(c.urllib.request, 'urlopen', return_value=Response(b'invalid image')) as request, patch.object(Image, 'open', side_effect=error), patch.object(c, 'annotate_denial') as annotate:
                    self.assertIsNone(c.download_image(IMAGE, root / 'never.jpg'))
                request.assert_called_once()
                annotate.assert_not_called()
                self.assertEqual(list(root.iterdir()), [])

    def test_all_http_auth_and_quota_denials_still_stop_without_retry(self):
        for code in (401, 403, 429):
            error = HTTPError(IMAGE, code, 'fixture response', {}, None)
            with self.subTest(code=code), patch.object(c.urllib.request, 'urlopen', side_effect=error) as request:
                with self.assertRaises(h.ProviderStop) as caught:
                    c.download_image(IMAGE, Path('never.jpg'))
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.category, 'quota' if code == 429 else 'auth')
                self.assertEqual(caught.exception.diagnostic['http_status'], code)
                request.assert_called_once()

    def test_denial_is_sanitized_persisted_and_never_retried(self):
        url = IMAGE + '?token=secret-query#secret-fragment'
        error = HTTPError(url, 403, 'private-reason', {'Content-Type': 'text/html; charset=utf-8', 'Set-Cookie': 'secret-cookie', 'Authorization': 'secret-auth', 'Retry-After': '120', 'X-Client-IP': 'private-ip'}, io.BytesIO(b'private-response-body'))
        with patch.object(c.urllib.request, 'urlopen', side_effect=error) as request:
            with self.assertRaises(h.ProviderStop) as caught:
                c.download_image(url, Path('never.jpg'))
        request.assert_called_once()
        stop = caught.exception
        self.assertEqual(stop.code, 403)
        self.assertEqual(stop.diagnostic['http_status'], 403)
        self.assertEqual(stop.diagnostic['url'], IMAGE)
        self.assertEqual(stop.diagnostic['retry_after_seconds'], 120)
        self.assertEqual(error.fp.tell(), 0)
        doc = {'provider_stops': []}
        h.persist_stop(doc, stop)
        with self.assertRaises(h.ProviderStop):
            h.assert_not_stopped(doc, {'daiso'})
        text = json.dumps(doc)
        for secret in ('secret-', 'private-', 'Set-Cookie', 'Authorization'):
            self.assertNotIn(secret, text)

    def test_diagnostic_failures_cannot_swallow_stop(self):
        error = HTTPError(IMAGE, 403, 'Forbidden', {}, None)
        with patch.object(c.urllib.request, 'urlopen', side_effect=error), patch.object(c, 'denial_diagnostic', side_effect=ValueError('private data')):
            with self.assertRaises(h.ProviderStop) as caught:
                c.download_image(IMAGE, Path('never.jpg'))
        self.assertTrue(caught.exception.diagnostic['diagnostic_unavailable'])
        self.assertNotIn('private data', json.dumps(caught.exception.diagnostic))

    def test_api_stop_carries_sanitized_endpoint(self):
        error = HTTPError('unused', 403, 'private reason', {}, None)
        with patch.object(c.urllib.request, 'urlopen', side_effect=error) as request:
            with self.assertRaises(h.ProviderStop) as caught:
                c.post('/pd/pdr/pdDtl/selPdDtlNtfc', '1234567')
        request.assert_called_once()
        self.assertEqual(caught.exception.diagnostic['url'], c.API + '/pd/pdr/pdDtl/selPdDtlNtfc')
        self.assertEqual(caught.exception.diagnostic['http_status'], 403)

    def test_unknown_paths_and_userinfo_are_not_logged(self):
        for url in ('https://cdn.daisomall.co.kr/person@example.com/token', 'https://evil.invalid/secret', 'https://cdn.daisomall.co.kr/[invalid', 'https://cdn.daisomall.co.kr/file/PD/20260402/example.jpg/session=synthetic-secret/192.0.2.1'):
            safe = s.diagnostic_url(url)
            self.assertNotIn('person@', safe)
            self.assertNotIn('token', safe)
            self.assertNotIn('evil', safe)
            self.assertNotIn('synthetic-secret', safe)
            self.assertNotIn('192.0.2.1', safe)
        self.assertEqual(s.diagnostic_url('https://user:secret@cdn.daisomall.co.kr/file/PD/20260402/example.jpg?key=secret'), 'https://cdn.daisomall.co.kr/file/PD/20260402/example.jpg')
        self.assertIsNone(s.denial_diagnostic(h.ProviderStop('daiso', 403), IMAGE, 'GET', 'detail_image', 'clock')['http_status'])

    def test_annotated_stop_publishes_through_real_history_contract(self):
        before = {'items': {}, 'provider_stops': []}
        doc = copy.deepcopy(before)
        error = HTTPError(IMAGE, 403, 'Forbidden', {'Content-Type': 'text/html'}, None)
        stop = h.ProviderStop('daiso', 403, 'auth')
        c.annotate_denial(stop, error, IMAGE + '?token=secret', 'GET', 'detail_image')
        h.persist_stop(doc, stop)
        self.assertTrue(s.valid_denial_diagnostic(doc['provider_stops'][0]['diagnostic']))
        base = (json.dumps(before) + '\n').encode()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'data').mkdir()
            (root / 'config').mkdir()
            (root / 'data/gosi.json').write_bytes(base)
            (root / 'config/publish_policy.json').write_text(json.dumps({'identity_fields': ['pd_no', 'product_id']}))
            with patch.object(h, 'exact_head', return_value=base):
                h.publish_observation(root, doc)
            written = json.loads((root / 'data/gosi.json').read_text())
            self.assertEqual(written['provider_stops'], doc['provider_stops'])
            with self.assertRaises(h.ProviderStop):
                h.assert_not_stopped(written, {'daiso'})
        for update in ({'Authorization': 'secret'}, {'url': IMAGE + '?token=secret'}, {'raw_headers_saved': True}, {'http_status': True}, {'observed_at': 'not a date'}):
            bad = copy.deepcopy(doc)
            bad['provider_stops'][0]['diagnostic'].update(update)
            with self.assertRaises(ValueError):
                h.replacement_ids(before, bad, {'identity_fields': ['pd_no', 'product_id']})

    def test_byte_and_pixel_limits_do_not_write(self):
        for name, limit in [('MAX_IMAGE_BYTES', 20), ('MAX_IMAGE_PIXELS', 10)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                with patch.object(c, name, limit), patch.object(c, 'ROOT', root), patch.object(c.urllib.request, 'urlopen', return_value=Response(pixels())):
                    self.assertIsNone(c.download_image(IMAGE, root / 'never.jpg'))
                self.assertEqual(list(root.iterdir()), [])


    def test_picture_lazy_source_beats_placeholder(self):
        html = f'<picture><source type="image/jpeg" data-srcset="{IMAGE} 2x"><img src="/placeholder.gif"></picture>'
        self.assertEqual(s.image_candidates(html, BASE), [IMAGE])

    def test_evidence_merge_failure_preserves_original_access_stop(self):
        html = f'<img src="{IMAGE}">'
        responses = [None, {'success': True, 'data': {'pdDtlDesc': {'pdDtlDc': html}}}]
        stop = h.ProviderStop('daiso', 403, 'auth')
        with tempfile.TemporaryDirectory() as td, patch.object(c, 'IMGDIR', Path(td)), patch.object(c, 'post', side_effect=responses), patch.object(c.time, 'sleep'), patch.object(c, 'download_image', side_effect=stop), patch.object(c, 'merge_images', side_effect=ValueError('fixture merge failure')):
            with self.assertRaises(h.ProviderStop) as caught:
                c.collect_one('1234567', {})
        self.assertIs(caught.exception, stop)
        with self.assertRaises(ValueError):
            h.validate_document({'items': {'1234567': {'image_observations': []}}})


    def test_partial_evidence_retained_and_no_later_product_after_stop(self):
        row = {'product_id': '1234567', 'maker': 'existing fact'}
        next_image = IMAGE.replace('example.jpg', 'next.jpg')
        html = f'<img src="{IMAGE}"><video><source src="{VIDEO}"></video><img src="{next_image}">'
        responses = [None, {'success': True, 'data': {'pdDtlDesc': {'pdDtlDc': html}}}]
        first = ('data/first.jpg', {'source': IMAGE, 'sha256': 'fixture', 'received_at': 'original'})
        stop = h.ProviderStop('daiso', 403, 'auth')
        with tempfile.TemporaryDirectory() as td, patch.object(c, 'IMGDIR', Path(td)), patch.object(c, 'post', side_effect=responses), patch.object(c.time, 'sleep'), patch.object(c, 'download_image', side_effect=[first, stop]) as download:
            with self.assertRaises(h.ProviderStop):
                c.collect_one('1234567', row)
        self.assertEqual([call.args[0] for call in download.call_args_list], [IMAGE, next_image])
        self.assertEqual(row['gosi_images'], ['data/first.jpg'])
        self.assertEqual(row['image_observations']['data/first.jpg']['received_at'], 'original')
        self.assertEqual(row['maker'], 'existing fact')
        doc = {'items': {'1234567': row, '7654321': {}}}
        with tempfile.TemporaryDirectory() as td:
            self.prepare_continuity_fixture(td, doc)
            with patch.dict(os.environ, self.actions_env), patch.object(c, 'ROOT', self.root), patch.object(c, 'GOSI', self.source), patch.object(c, 'seed_from_s_grade'), patch.object(c, 'collect_one', side_effect=stop) as collect, patch.object(c, 'publish_observation', wraps=h.publish_observation) as publish:
                c.main()
            collect.assert_called_once()
            self.assertEqual(collect.call_args.args[0], '1234567')
            publish.assert_called_once()
            self.assertEqual(publish.call_args.args[0], self.root)
            persisted = json.loads(self.source.read_bytes())
            self.assertEqual(persisted['provider_stops'][0]['code'], 403)
            self.assertEqual(persisted['items']['1234567']['maker'], 'existing fact')
            self.assertEqual(persisted['items']['1234567']['gosi_images'], ['data/first.jpg'])
            self.assertEqual(persisted['items']['1234567']['image_observations']['data/first.jpg']['received_at'], 'original')
            before = self.source.read_bytes()
            with patch.dict(os.environ, self.actions_env), patch.object(c, 'ROOT', self.root), patch.object(c, 'GOSI', self.source), patch.object(c, 'collect_one') as collect, patch.object(c, 'publish_observation') as publish:
                c.main()
            collect.assert_not_called()
            publish.assert_not_called()
            self.assertEqual(self.source.read_bytes(), before)

    def test_missing_actions_proof_blocks_before_source_or_publication(self):
        with tempfile.TemporaryDirectory() as td:
            self.prepare_continuity_fixture(td, {'items': {'1234567': {'maker': 'existing fact'}}})
            (self.root / '.gosi-safety-verified.json').unlink()
            with patch.dict(os.environ, self.actions_env), patch.object(c, 'ROOT', self.root), patch.object(c, 'GOSI', self.source), patch.object(c, 'seed_from_s_grade') as seed, patch.object(c, 'collect_one') as collect, patch.object(c, 'publish_observation') as publish:
                self.assertEqual(c.main(), 1)
            seed.assert_not_called()
            collect.assert_not_called()
            publish.assert_not_called()
            self.assertEqual(self.source.read_bytes(), self.before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
