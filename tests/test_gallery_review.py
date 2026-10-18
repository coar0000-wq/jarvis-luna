"""Offline synthetic evidence only. No supplier, Shopify or image network calls."""
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import gallery_review as gallery

NOW = datetime(2026, 10, 18, 15, 0, tzinfo=timezone.utc)


class GalleryReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = {'schema_version': 1, 'pd_no': '123', 'assets': [], 'review_evidence': {}}
        for index, role in enumerate(gallery.ROLES):
            output = self.write('output%d.jpg' % index, b'\x89PNG\r\n\x1a\n' + ('synthetic output %d' % index).encode())
            source = self.write('source%d.jpg' % index, ('synthetic source %d' % index).encode())
            asset = {'pd_no': '123', 'asset_file': output['file'], 'asset_sha256': output['sha256'],
                     'source_file': source['file'], 'source_sha256': source['sha256'],
                     'source_url': 'https://example.test/product/123/image%d' % index}
            receipt = {'kind': 'gallery_asset_review', 'pd_no': '123',
                       'reviewed_at': NOW.isoformat(), 'reviewer': 'synthetic reviewer',
                       'asset_sha256': output['sha256'], 'source_sha256': source['sha256'],
                       'source_url': asset['source_url'], 'roles': [role],
                       'role_evidence': {role: 'Synthetic source covers this role.'},
                       'qa': dict.fromkeys(gallery.QA_CHECKS, 'pass')}
            asset['review_receipt'] = self.write('asset%d.json' % index, receipt)
            self.manifest['assets'].append(asset)
        for kind in ('rights', 'label'):
            evidence = self.write(kind + '-evidence.txt', b'SYNTHETIC SUPPORTING DOCUMENT, NOT REAL PRODUCT EVIDENCE')
            receipt = {'kind': 'gallery_' + kind + '_review', 'pd_no': '123',
                       'reviewed_at': NOW.isoformat(), 'reviewer': 'synthetic reviewer',
                       'disposition': 'confirmed', 'verification_basis': 'actual_package_label',
                       'source_sha256s': [a['source_sha256'] for a in self.manifest['assets']],
                       'permission_scope': ['reproduce', 'adapt', 'store_product_gallery'],
                       'asset_sha256s': [a['asset_sha256'] for a in self.manifest['assets']],
                       'evidence_file': evidence['file'], 'evidence_sha256': evidence['sha256']}
            self.manifest['review_evidence'][kind] = self.write(kind + '.json', receipt)
        self.entry = {'pd_no': '123', 'shopify_id': 'gid://shopify/Product/123',
                      'status': 'DRAFT', 'images': 2, 'gallery_complete': True}
        self.observation = {'id': self.entry['shopify_id'], 'pd_no': '123', 'status': 'DRAFT',
                            'observed_at': NOW.isoformat(), 'complete': True, 'media': []}

    def write(self, name, value):
        raw = json.dumps(value).encode() if isinstance(value, dict) else value
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {'file': name, 'sha256': hashlib.sha256(raw).hexdigest()}

    def change_receipt(self, ref, **changes):
        doc = json.loads((self.root / ref['file']).read_bytes())
        doc.update(changes)
        ref.update(self.write(ref['file'], doc))

    def assess(self, manifest=None, now=NOW):
        return gallery.assess_gallery('123', self.manifest if manifest is None else manifest, self.root, now=now)

    def plan(self, observation=None):
        return gallery.plan_additions(self.entry, self.manifest, self.root,
                                      self.observation if observation is None else observation, now=NOW)

    def media(self, index):
        return {'id': 'gid://shopify/MediaImage/%d' % index, 'mediaContentType': 'IMAGE', 'status': 'READY',
                'content_sha256': self.manifest['assets'][index]['asset_sha256']}

    def test_complete_role_evidence_is_prepared_without_claiming_live_or_legal_completion(self):
        out = self.assess()
        self.assertTrue(out['preparation_complete'])
        self.assertEqual(out['status'], 'prepared')
        self.assertEqual(out['missing_roles'], [])
        self.assertFalse(out['gallery_complete'])
        self.assertFalse(out['publication_allowed'])
        self.assertFalse(out['legal_or_safety_approval'])

    def test_count_and_saved_ok_cannot_replace_evidence(self):
        for manifest in ({}, {'schema_version': 1, 'pd_no': '123', 'status': 'ok',
                             'assets': [], 'gallery_complete': True},
                         {'schema_version': 1, 'pd_no': '123', 'assets': [{'roles': list(gallery.ROLES)}] * 11}):
            with self.subTest(manifest=manifest):
                self.assertFalse(self.assess(manifest)['preparation_complete'])

    def test_one_valid_role_is_partial(self):
        self.manifest['assets'] = self.manifest['assets'][:1]
        out = self.assess()
        self.assertEqual(out['status'], 'partial')
        self.assertEqual(out['covered_roles'], ['representative'])
        self.assertEqual(len(out['missing_roles']), 4)

    def test_eleven_duplicate_images_are_not_complete(self):
        self.manifest['assets'] = [copy.deepcopy(self.manifest['assets'][0]) for _ in range(11)]
        out = self.assess()
        self.assertEqual(len(out['accepted_assets']), 1)
        self.assertEqual(len(out['rejected_assets']), 10)
        self.assertFalse(out['preparation_complete'])

    def test_no_fixed_eleven_minimum(self):
        self.assertEqual(len(self.assess()['accepted_assets']), 5)
        self.assertTrue(self.assess()['preparation_complete'])

    def test_missing_rights_or_actual_label_document_blocks_completion(self):
        for kind in ('rights', 'label'):
            with self.subTest(kind=kind):
                path = self.root / (kind + '-evidence.txt')
                raw = path.read_bytes()
                path.unlink()
                self.assertFalse(self.assess()['preparation_complete'])
                path.write_bytes(raw)

    def test_pending_rights_and_supplier_only_label_not_confirmed(self):
        for kind in ('rights', 'label'):
            self.change_receipt(self.manifest['review_evidence'][kind], disposition='pending')
        out = self.assess()
        self.assertFalse(out['preparation_complete'])
        self.assertEqual((out['rights_review'], out['label_review']), ('unverified', 'unverified'))

    def test_supplier_notice_cannot_substitute_for_actual_package_label_review(self):
        self.change_receipt(self.manifest['review_evidence']['label'], verification_basis='supplier_notice')
        self.assertFalse(self.assess()['preparation_complete'])

    def test_rights_review_requires_exact_sources_and_reuse_edit_scope(self):
        ref = self.manifest['review_evidence']['rights']
        self.change_receipt(ref, permission_scope=['reproduce'])
        self.assertFalse(self.assess()['preparation_complete'])
        self.change_receipt(ref, permission_scope=['reproduce', 'adapt', 'store_product_gallery'],
                            source_sha256s=['0' * 64])
        self.assertFalse(self.assess()['preparation_complete'])

    def test_role_labels_without_bound_rationale_do_not_pass(self):
        self.change_receipt(self.manifest['assets'][0]['review_receipt'], role_evidence={})
        self.assertIn('representative', self.assess()['missing_roles'])

    def test_incomplete_qa_holds_asset(self):
        self.change_receipt(self.manifest['assets'][0]['review_receipt'], qa={'face_check': 'pass'})
        self.assertFalse(self.assess()['preparation_complete'])

    def test_changed_source_or_output_bytes_revokes_preparation(self):
        for key in ('source_file', 'asset_file'):
            path = self.root / self.manifest['assets'][0][key]
            raw = path.read_bytes()
            path.write_bytes(b'changed')
            self.assertFalse(self.assess()['preparation_complete'])
            path.write_bytes(raw)

    def test_wrong_sku_source_url_or_hash_binding_holds_asset(self):
        ref = self.manifest['assets'][0]['review_receipt']
        original = (self.root / ref['file']).read_bytes()
        for changes in ({'pd_no': 'other'}, {'source_url': 'https://example.test/other'},
                        {'source_sha256': '0' * 64}, {'asset_sha256': '0' * 64}):
            with self.subTest(changes=changes):
                ref.update(self.write(ref['file'], original))
                self.change_receipt(ref, **changes)
                self.assertFalse(self.assess()['preparation_complete'])

    def test_expired_future_naive_and_malformed_review_timestamps_fail_closed(self):
        ref = self.manifest['assets'][0]['review_receipt']
        for stamp in ((NOW - timedelta(days=31)).isoformat(), (NOW + timedelta(seconds=1)).isoformat(),
                      NOW.replace(tzinfo=None).isoformat(), None, 123, ''):
            with self.subTest(stamp=stamp):
                self.change_receipt(ref, reviewed_at=stamp)
                self.assertFalse(self.assess()['preparation_complete'])

    def test_time_advance_expires_previously_prepared_gallery(self):
        self.assertTrue(self.assess()['preparation_complete'])
        self.assertFalse(self.assess(now=NOW + timedelta(days=31))['preparation_complete'])

    def test_malformed_review_evidence_never_crashes_or_passes(self):
        for value in ('bad', ['bad'], 123, {'rights': {'file': 1, 'sha256': float('nan')}}):
            self.manifest['review_evidence'] = value
            self.assertFalse(self.assess()['preparation_complete'])

    def test_path_traversal_and_outside_symlink_rejected(self):
        asset = self.manifest['assets'][0]
        for path in ('../outside', '/etc/passwd', 'file:/etc/passwd', r'..\outside'):
            with self.subTest(path=path):
                asset['source_file'] = path
                self.assertFalse(self.assess()['preparation_complete'])
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'private.txt'
            target.write_bytes(b'private')
            (self.root / 'linked').symlink_to(target)
            asset['source_file'] = 'linked'
            asset['source_sha256'] = hashlib.sha256(b'private').hexdigest()
            self.assertFalse(self.assess()['preparation_complete'])

    def test_safe_manifest_loader_and_symlink_protection(self):
        file = gallery.MANIFEST_DIR + '/123.json'
        self.write(file, self.manifest)
        self.assertEqual(gallery.load_manifest(self.root, '123'), self.manifest)
        self.assertEqual(gallery.load_manifest(self.root, '../../etc/passwd'), {})
        (self.root / file).unlink()
        (self.root / file).symlink_to(self.root / 'rights.json')
        self.assertEqual(gallery.load_manifest(self.root, '123'), {})

    def test_reports_do_not_contain_private_paths_or_document_text(self):
        out = json.dumps(self.assess())
        self.assertNotIn('SYNTHETIC SUPPORTING', out)
        self.assertNotIn('synthetic reviewer', out)
        self.assertNotIn(str(self.root), out)
        self.assertNotIn('rights-evidence.txt', out)

    def test_assessment_and_planning_preserve_all_source_bytes(self):
        before = {p: p.read_bytes() for p in self.root.iterdir()}
        self.assess()
        self.plan()
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.iterdir()})

    def test_two_and_three_existing_images_are_preserved_and_only_missing_added(self):
        for count in (2, 3):
            self.observation['media'] = [self.media(i) for i in range(count)]
            out = self.plan()
            self.assertEqual(out['status'], 'additions_prepared')
            self.assertEqual(out['preserve_media_ids'], [m['id'] for m in self.observation['media']])
            self.assertEqual(set(out['add_asset_sha256s']), {a['asset_sha256'] for a in self.manifest['assets'][count:]})
            self.assertFalse(out['gallery_complete'])

    def test_active_archived_unknown_or_stale_state_never_plan_additions(self):
        for changes in ({'status': 'ACTIVE'}, {'status': 'ARCHIVED'}, {'status': None},
                        {'id': 'gid://shopify/Product/456'}, {'pd_no': '456'}, {'complete': False},
                        {'observed_at': (NOW - timedelta(minutes=6)).isoformat()},
                        {'observed_at': (NOW + timedelta(seconds=1)).isoformat()}, {'observed_at': None}):
            with self.subTest(changes=changes):
                obs = {**self.observation, **changes, 'media': [self.media(0)]}
                out = self.plan(obs)
                self.assertEqual(out['add_asset_sha256s'], [])
                self.assertEqual(out['preserve_media_ids'], [self.media(0)['id']])
                self.assertFalse(out['gallery_complete'])

    def test_missing_bytes_incomplete_media_or_duplicates_hold_plan(self):
        for media in ([{**self.media(0), 'content_sha256': None}], [self.media(0)] * 2,
                      [{**self.media(0), 'status': 'PROCESSING'}], [{**self.media(0), 'mediaContentType': 'VIDEO'}],
                      [{'id': []}], None):
            with self.subTest(media=media):
                self.observation['media'] = media
                out = self.plan()
                self.assertEqual(out['add_asset_sha256s'], [])
                self.assertFalse(out['gallery_complete'])

    def test_unknown_existing_image_is_preserved_and_never_reuploaded_to_align_hashes(self):
        self.observation['media'] = [{**self.media(0), 'content_sha256': 'a' * 64}]
        out = self.plan()
        self.assertEqual(out['preserve_media_ids'], [self.media(0)['id']])
        self.assertEqual(out['add_asset_sha256s'], [])
        self.assertEqual(out['reasons'], ['existing_media_asset_binding_unverified'])

    def test_all_exact_assets_observed_is_complete_without_write_or_publication(self):
        self.observation['media'] = [self.media(i) for i in range(5)]
        out = self.plan()
        self.assertEqual(out['status'], 'complete')
        self.assertTrue(out['gallery_complete'])
        self.assertEqual(out['add_asset_sha256s'], [])
        self.assertFalse(out['publication_allowed'])

    def test_saved_approval_and_source_revocation_are_rechecked_before_plan(self):
        self.assertEqual(self.plan()['status'], 'additions_prepared')
        self.manifest['preparation_complete'] = True
        (self.root / self.manifest['assets'][0]['source_file']).unlink()
        out = self.plan()
        self.assertEqual(out['status'], 'review_required')
        self.assertEqual(out['add_asset_sha256s'], [])


if __name__ == '__main__':
    unittest.main()
