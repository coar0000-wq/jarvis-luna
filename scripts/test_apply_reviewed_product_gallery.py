"""Synthetic offline fixtures only. No Shopify, GitHub, supplier or paid API I/O."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image

import apply_reviewed_product_gallery as executor


class MockCheckpoint:
    def __init__(self, answer=True):
        self.answer, self.calls = answer, 0

    def verify(self, plan, journal):
        self.calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class MockClient:
    def __init__(self, snapshot, raw):
        self.live, self.raw = deepcopy(snapshot), raw
        self.writes, self.reads, self.fetches = 0, 0, 0
        self.after_append_error = None
        self.before_append_error = None
        self.change_on_read = {}

    def read_snapshot(self, product_id):
        self.reads += 1
        if self.reads in self.change_on_read:
            self.change_on_read[self.reads](self.live)
        return deepcopy(self.live)

    def fetch(self, url, hosts):
        self.fetches += 1
        return self.raw

    def append_once(self, product_id, assets):
        self.writes += 1
        if self.before_append_error:
            raise self.before_append_error
        for index, asset in enumerate(assets):
            self.live['product']['media'].append({
                'id': 'gid://shopify/MediaImage/' + str(1000 + index), 'alt': asset['alt_text'],
                'status': 'READY', 'mediaContentType': 'IMAGE',
                'image': {'url': 'https://cdn.shopify.com/s/files/1/new' + str(index) + '.png',
                          'width': asset['fingerprint']['width'], 'height': asset['fingerprint']['height']},
                'fingerprint': deepcopy(asset['fingerprint'])})
        self.live['product']['updatedAt'] = executor.utcnow().isoformat()
        if self.after_append_error:
            raise self.after_append_error


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = executor.utcnow()
        self.source = self.png('source.png', 'red')
        self.asset = self.png('asset.png', 'red')
        self.existing = self.png('existing.png', 'blue')
        self.snapshot = {'schema_version': 1, 'complete': True, 'observed_at': self.now.isoformat(),
            'shop': {'id': 'gid://shopify/Shop/1', 'myshopifyDomain': 'synthetic.myshopify.com'},
            'product': {'id': 'gid://shopify/Product/123', 'handle': 'synthetic-123', 'title': 'Synthetic 20 ml',
                'status': 'ACTIVE', 'tags': ['daiso-pd-123', 'synthetic'], 'updatedAt': self.now.isoformat(),
                'totalInventory': 4, 'publishedAt': self.now.isoformat(),
                'options': [{'id': 'gid://shopify/ProductOption/1', 'name': 'Size', 'position': 1, 'values': ['20 ml']}],
                'media': [{'id': 'gid://shopify/MediaImage/1', 'alt': 'Original alt', 'status': 'READY',
                    'mediaContentType': 'IMAGE', 'image': {'url': 'https://cdn.shopify.com/s/files/1/original.png',
                    'width': 8, 'height': 8}, 'fingerprint': executor.fingerprint('existing.png', self.root)}],
                'variants': [{'id': 'gid://shopify/ProductVariant/1', 'sku': 'DAISO-123-20ML',
                    'selectedOptions': [{'name': 'Size', 'value': '20 ml'}], 'price': '10.00', 'compareAtPrice': None,
                    'inventoryQuantity': 4, 'inventoryPolicy': 'DENY', 'media': [{'id': 'gid://shopify/MediaImage/1'}],
                    'inventoryItem': {'id': 'gid://shopify/InventoryItem/1', 'tracked': True, 'inventoryLevels': [
                        {'id': 'gid://shopify/InventoryLevel/1?inventory_item_id=1', 'location': {'id': 'gid://shopify/Location/1'},
                         'quantities': [{'name': name, 'quantity': 4 if name in {'on_hand', 'available'} else 0}
                                        for name in executor.QUANTITIES]}]}}],
                'publications': [{'publication': {'id': 'gid://shopify/Publication/1'}, 'isPublished': True,
                                  'publishDate': self.now.isoformat()}]}}
        self.identity = executor.snapshot_identity(self.snapshot, '123')
        self.scope = {'identity': deepcopy(self.identity), 'expected_status': 'ACTIVE',
                      'transport_shop': 'synthetic-transport.myshopify.com',
                      'execution_ticket': 'SYNTHETIC-TEST-ONLY', 'authorized_at': self.now.isoformat(),
                      'expires_at': (self.now + timedelta(hours=1)).isoformat(),
                      'asset_sha256s': [self.asset['sha256']], 'allowed_source_hosts': ['raw.githubusercontent.com']}
        url = 'https://raw.githubusercontent.com/synthetic/review/' + 'a' * 40 + '/asset.png'
        asset = {'pd_no': '123', 'asset_file': 'asset.png', 'asset_sha256': self.asset['sha256'],
                 'source_file': 'source.png', 'source_sha256': self.source['sha256'],
                 'source_url': 'https://example.test/synthetic-original', 'asset_url': url,
                 'alt_text': 'Synthetic red square, test only'}
        review = {'kind': 'gallery_asset_review', 'pd_no': '123', 'reviewer': 'SYNTHETIC TEST FIXTURE',
                  'reviewed_at': self.now.isoformat(), 'asset_sha256': self.asset['sha256'],
                  'source_sha256': self.source['sha256'], 'source_url': asset['source_url'], 'asset_url': url,
                  'alt_text': asset['alt_text'],
                  'roles': ['representative'], 'role_evidence': {'representative': 'Synthetic red image fixture only.'},
                  'qa': dict.fromkeys(executor.gallery_review.QA_CHECKS, 'pass'), 'execution_identity': deepcopy(self.identity)}
        asset['review_receipt'] = self.write('asset-review.json', review)
        self.manifest = {'schema_version': 1, 'pd_no': '123', 'execution_identity': deepcopy(self.identity),
                         'assets': [asset], 'review_evidence': {}}
        for kind in ('rights', 'label'):
            evidence = self.write(kind + '-support.txt', b'SYNTHETIC TEST ONLY; NO ACTUAL PRODUCT OR AUTHORIZATION')
            doc = {'kind': 'gallery_' + kind + '_review', 'pd_no': '123', 'reviewer': 'SYNTHETIC TEST FIXTURE',
                   'reviewed_at': self.now.isoformat(), 'disposition': 'confirmed',
                   'verification_basis': 'actual_package_label', 'source_sha256s': [self.source['sha256']],
                   'permission_scope': ['reproduce', 'adapt', 'store_product_gallery'],
                   'asset_sha256s': [self.asset['sha256']], 'evidence_file': evidence['file'],
                   'evidence_sha256': evidence['sha256'], 'execution_identity': deepcopy(self.identity)}
            self.manifest['review_evidence'][kind] = self.write(kind + '.json', doc)
        self.journal_path = self.root / 'journal.json'
        self.context = {'repository': 'synthetic/repo', 'run_id': '1234', 'run_attempt': '1',
                        'code_sha': 'b' * 40, 'workflow_path': '.github/workflows/gallery.yml'}
        self.client = MockClient(self.snapshot, (self.root / 'asset.png').read_bytes())
        self.checkpoint = MockCheckpoint()

    def write(self, name, value):
        raw = executor.json_bytes(value) if isinstance(value, dict) else value
        (self.root / name).write_bytes(raw)
        return {'file': name, 'sha256': hashlib.sha256(raw).hexdigest()}

    def png(self, name, color, *, compression=6):
        image = Image.new('RGB', (8, 8), color)
        buffer = io.BytesIO()
        image.save(buffer, format='PNG', compress_level=compression)
        return self.write(name, buffer.getvalue())

    def change_receipt(self, ref, **changes):
        doc = json.loads((self.root / ref['file']).read_bytes())
        doc.update(changes)
        ref.update(self.write(ref['file'], doc))

    def plan(self):
        return executor.build_reviewed_plan(self.scope, self.manifest, self.root, self.snapshot, now=self.now)

    def prepare(self):
        plan = self.plan()
        executor.atomic_json(self.journal_path, executor.make_journal(plan, **self.context))
        return plan

    def run_apply(self, plan=None, **kwargs):
        if plan is None:
            plan = self.prepare()
        return executor.execute_reviewed_plan(plan, manifest=self.manifest, root=self.root,
            expected_plan_digest=plan['plan_digest'], client=self.client, journal_path=self.journal_path,
            checkpoint=self.checkpoint, apply=True, now=self.now, pause=lambda _: None, **kwargs)

    def assert_plan_hold(self, reason=None):
        with self.assertRaises(executor.Hold) as error:
            self.plan()
        if reason:
            self.assertIn(reason, str(error.exception))
        self.assertEqual(self.client.writes, 0)

    def test_default_dry_run_has_zero_reads_fetches_writes(self):
        plan = self.prepare()
        output = executor.execute_reviewed_plan(plan, manifest=self.manifest, root=self.root,
            expected_plan_digest=plan['plan_digest'], client=self.client, journal_path=self.journal_path)
        self.assertEqual(output['state'], 'dry_run')
        self.assertEqual((self.client.reads, self.client.fetches, self.client.writes), (0, 0, 0))

    def test_live_observation_timestamps_without_injected_clock_can_apply(self):
        plan = self.prepare()
        original = self.client.read_snapshot
        def fresh_read(product_id):
            snapshot = original(product_id)
            snapshot['observed_at'] = executor.utcnow().isoformat()
            return snapshot
        self.client.read_snapshot = fresh_read
        output = executor.execute_reviewed_plan(plan, manifest=self.manifest, root=self.root,
            expected_plan_digest=plan['plan_digest'], client=self.client, journal_path=self.journal_path,
            checkpoint=self.checkpoint, apply=True, pause=lambda _: None)
        self.assertEqual(output['state'], 'verified')
        self.assertEqual(self.client.reads, 3)
        self.assertEqual(self.client.writes, 1)

    def test_partial_role_can_append_without_gallery_or_sales_approval(self):
        plan = self.prepare()
        self.assertEqual(len(plan['missing_roles']), 4)
        output = self.run_apply(plan)
        self.assertEqual(output['state'], 'verified')
        self.assertEqual(self.client.writes, 1)
        for key in ('gallery_complete', 'publication_allowed', 'legal_or_safety_approval'):
            self.assertIs(output[key], False)

    def test_active_status_and_every_original_media_field_preserved(self):
        self.run_apply()
        self.assertEqual(self.client.live['product']['status'], 'ACTIVE')
        self.assertEqual(self.client.live['product']['media'][0], self.snapshot['product']['media'][0])
        self.assertEqual(executor.protection(self.client.live, include_media=False),
                         executor.protection(self.snapshot, include_media=False))

    def test_draft_is_preserved_without_touching_old_gate(self):
        self.snapshot['product']['status'] = 'DRAFT'
        self.scope['expected_status'] = 'DRAFT'
        self.client.live = deepcopy(self.snapshot)
        self.assertEqual(self.run_apply()['state'], 'verified')
        self.assertEqual(self.client.live['product']['status'], 'DRAFT')
        old = executor.gallery_review.observation_error({'pd_no': '123', 'shopify_id': self.identity['product_id']},
                {'id': self.identity['product_id'], 'pd_no': '123', 'status': 'ACTIVE', 'complete': True,
                 'observed_at': self.now.isoformat(), 'media': []}, now=self.now)
        self.assertEqual(old, 'current_exact_draft_observation_required')

    def test_no_fake_true_flags_replace_rights(self):
        for flag in (True, 'true', 'confirmed', False):
            with self.subTest(flag=flag):
                self.manifest['rights_verified'] = flag
                self.manifest['review_evidence']['rights'] = flag
                self.assert_plan_hold('rights_and_actual_label')

    def test_missing_actual_label_evidence_holds(self):
        (self.root / 'label-support.txt').unlink()
        self.assert_plan_hold('rights_and_actual_label')

    def test_supplier_notice_instead_of_actual_label_holds(self):
        self.change_receipt(self.manifest['review_evidence']['label'], verification_basis='supplier_notice')
        self.assert_plan_hold('rights_and_actual_label')

    def test_false_string_true_or_missing_disposition_cannot_authorize(self):
        for flag in (True, 'true', False, None):
            self.change_receipt(self.manifest['review_evidence']['rights'], disposition=flag)
            self.assert_plan_hold()

    def test_missing_asset_receipt_holds(self):
        self.manifest['assets'][0].pop('review_receipt')
        self.assert_plan_hold()

    def test_each_final_qa_check_required_and_cannot_be_true(self):
        for check in executor.gallery_review.QA_CHECKS:
            for value in (True, 'true', False, 'fail', None):
                with self.subTest(check=check, value=value):
                    qa = dict.fromkeys(executor.gallery_review.QA_CHECKS, 'pass')
                    qa[check] = value
                    self.change_receipt(self.manifest['assets'][0]['review_receipt'], qa=qa)
                    self.assert_plan_hold()

    def test_output_bytes_changed_after_review_hold(self):
        self.png('asset.png', 'green')
        self.assert_plan_hold()

    def test_source_bytes_changed_after_review_hold(self):
        self.png('source.png', 'green')
        self.assert_plan_hold()

    def test_exact_product_sku_capacity_and_shop_conflicts_hold(self):
        for location, key, value in ((('identity',), 'product_id', 'gid://shopify/Product/9'),
                (('identity',), 'pd_no', '999'), (('identity',), 'title', 'Synthetic 30 ml'),
                (('identity', 'shop'), 'myshopifyDomain', 'other.myshopify.com')):
            with self.subTest(key=key):
                original = deepcopy(self.scope)
                target = self.scope
                for part in location:
                    target = target[part]
                target[key] = value
                self.assert_plan_hold()
                self.scope = original
        for field, value in (('sku', 'OTHER-123'), ('selectedOptions', [{'name': 'Size', 'value': '30 ml'}])):
            original = deepcopy(self.scope)
            self.scope['identity']['variants'][0][field] = value
            self.assert_plan_hold('identity_mismatch')
            self.scope = original

    def test_asset_and_label_receipt_exact_identity_binding(self):
        for ref in (self.manifest['assets'][0]['review_receipt'], self.manifest['review_evidence']['label']):
            original = (self.root / ref['file']).read_bytes()
            self.change_receipt(ref, execution_identity={'pd_no': '123'})
            self.assert_plan_hold('identity_unverified')
            ref.update(self.write(ref['file'], original))

    def test_ambiguous_or_missing_pd_tag_holds(self):
        for tags in ([], ['daiso-pd-999'], ['daiso-pd-123', 'daiso-pd-999']):
            self.snapshot['product']['tags'] = tags
            self.assert_plan_hold('pd_no_tag')

    def test_archived_and_wrong_expected_status_hold(self):
        self.snapshot['product']['status'] = 'ARCHIVED'
        self.assert_plan_hold()
        self.snapshot['product']['status'] = 'ACTIVE'
        self.scope['expected_status'] = 'DRAFT'
        self.assert_plan_hold('status_mismatch')

    def test_scope_expiry_future_and_over_24h_hold(self):
        for changes in ({'expires_at': self.now.isoformat()},
                        {'authorized_at': (self.now + timedelta(seconds=1)).isoformat()},
                        {'expires_at': (self.now + timedelta(hours=25)).isoformat()}):
            original = deepcopy(self.scope)
            self.scope.update(changes)
            self.assert_plan_hold('scope_expired_or_over_24h')
            self.scope = original

    def test_complete_string_true_is_not_complete(self):
        for value in ('true', True, False):
            self.snapshot['complete'] = value
            if value is True:
                self.plan()
            else:
                self.assert_plan_hold('complete_snapshot')

    def test_stale_or_future_snapshot_holds(self):
        for age in (-1, 301):
            self.snapshot['observed_at'] = (self.now - timedelta(seconds=age)).isoformat()
            self.assert_plan_hold('snapshot_stale_or_future')

    def test_unready_or_unverified_existing_media_holds(self):
        self.snapshot['product']['media'][0]['status'] = 'PROCESSING'
        self.assert_plan_hold()
        self.snapshot['product']['media'][0]['status'] = 'READY'
        self.snapshot['product']['media'][0].pop('fingerprint')
        self.assert_plan_hold()

    def test_missing_variant_price_inventory_or_publications_holds(self):
        for key in ('price', 'compareAtPrice', 'inventoryQuantity', 'inventoryItem', 'media'):
            old = self.snapshot['product']['variants'][0].pop(key)
            self.assert_plan_hold()
            self.snapshot['product']['variants'][0][key] = old
        self.snapshot['product'].pop('publications')
        self.assert_plan_hold()

    def test_inventory_quantities_cannot_be_truncated(self):
        self.snapshot['product']['variants'][0]['inventoryItem']['inventoryLevels'][0]['quantities'].pop()
        self.assert_plan_hold('quantities_incomplete')

    def test_different_png_encoding_same_pixels_is_noop(self):
        existing = self.png('existing.png', 'red', compression=0)
        self.assertNotEqual(existing['sha256'], self.asset['sha256'])
        self.snapshot['product']['media'][0]['fingerprint'] = executor.fingerprint('existing.png', self.root)
        self.client.live = deepcopy(self.snapshot)
        plan = self.prepare()
        self.assertEqual(plan['additions'], [])
        self.assertEqual(plan['noops'][0]['decision'], 'reuse_existing_noop')
        self.assertEqual(self.run_apply(plan)['state'], 'noop')
        self.assertEqual((self.client.writes, self.client.fetches, self.checkpoint.calls), (0, 0, 0))

    def test_media_id_or_url_claim_without_equal_pixels_holds(self):
        self.manifest['assets'][0].update(attached_media_id='gid://shopify/MediaImage/1',
            attached_image_url=self.snapshot['product']['media'][0]['image']['url'])
        self.assert_plan_hold('id_url_pixel_binding')

    def test_mutable_cdn_source_cannot_authorize_new_append(self):
        asset = self.manifest['assets'][0]
        url = 'https://cdn.shopify.com/s/files/1/reviewed.png?v=123'
        self.scope['allowed_source_hosts'] = ['cdn.shopify.com']
        asset['asset_url'] = url
        self.change_receipt(asset['review_receipt'], asset_url=url)
        self.assert_plan_hold('new_asset_immutable_commit_source_required')
        self.assertEqual(self.client.writes, 0)

    def test_manifest_url_must_bind_final_output_receipt(self):
        self.manifest['assets'][0]['asset_url'] = self.manifest['assets'][0]['asset_url'].replace('asset.png', 'other.png')
        self.assert_plan_hold('url_receipt_binding')

    def test_disallowed_private_credentials_branch_redirect_urls_hold(self):
        urls = ['http://cdn.shopify.com/s/files/1/x.png', 'https://127.0.0.1/x.png',
                'https://user:pass@cdn.shopify.com/s/files/1/x.png',
                'https://raw.githubusercontent.com/synthetic/repo/main/x.png',
                'https://raw.githubusercontent.com/synthetic/repo/' + 'a' * 40 + '/x.png?secret=1',
                'https://cdn.shopify.com:444/s/files/1/x.png', 'https://evil.test/x.png']
        for url in urls:
            with self.subTest(url=url):
                with self.assertRaises(executor.Hold):
                    executor.asset_url(url, list(executor.SOURCE_HOSTS))

    def test_commit_source_has_no_path_normalization_escape(self):
        base = 'https://raw.githubusercontent.com/synthetic/repo/' + 'a' * 40
        for suffix in ('/../main/asset.png', '/folder/../../main/asset.png',
                       '/%2e%2e/main/asset.png', '/%252e%252e/main/asset.png',
                       '//asset.png', '/./asset.png', '/folder%2Fasset.png', '/folder/'):
            with self.subTest(suffix=suffix), self.assertRaises(executor.Hold):
                executor.asset_url(base + suffix, ['raw.githubusercontent.com'])
        safe = base + '/review-123/assets/output_01.png'
        self.assertEqual(executor.asset_url(safe, ['raw.githubusercontent.com']), safe)

    def test_arbitrary_scope_host_cannot_expand_fixed_allowlist(self):
        self.scope['allowed_source_hosts'].append('evil.test')
        self.assert_plan_hold('allowlist_invalid')

    def test_transport_shop_is_explicit_and_bound_to_plan_digest(self):
        first = self.plan()
        self.scope['transport_shop'] = 'another-transport.myshopify.com'
        self.assertNotEqual(first['plan_digest'], self.plan()['plan_digest'])
        for value in (None, '', 'https://synthetic-transport.myshopify.com', 'attacker.test'):
            self.scope['transport_shop'] = value
            self.assert_plan_hold('explicit_transport_shop_required')

    def test_transport_alias_does_not_relax_live_canonical_identity(self):
        self.assertNotEqual(self.scope['transport_shop'], self.scope['identity']['shop']['myshopifyDomain'])
        self.assertEqual(self.run_apply()['state'], 'verified')
        self.snapshot['shop']['myshopifyDomain'] = 'wrong-canonical.myshopify.com'
        with self.assertRaisesRegex(executor.Hold, 'identity_mismatch'):
            self.plan()
        self.assertEqual(self.client.writes, 1)

    def test_exact_remote_bytes_verified_before_mutation(self):
        self.client.raw = (self.root / 'existing.png').read_bytes()
        with self.assertRaisesRegex(executor.Hold, 'public_final_asset_bytes_mismatch'):
            self.run_apply()
        self.assertEqual(self.client.writes, 0)

    def test_expected_plan_digest_is_required_and_exact(self):
        plan = self.prepare()
        for expected in (None, '', '0' * 64):
            with self.assertRaises(executor.Hold):
                executor.execute_reviewed_plan(plan, manifest=self.manifest, root=self.root,
                    expected_plan_digest=expected, client=self.client, apply=True)
        self.assertEqual(self.client.writes, 0)

    def test_plan_tamper_with_preserved_digest_holds(self):
        plan = self.prepare()
        plan['additions'][0]['asset_url'] += 'changed'
        with self.assertRaisesRegex(executor.Hold, 'plan_digest_mismatch'):
            self.run_apply(plan)
        self.assertEqual(self.client.writes, 0)

    def test_apply_true_string_never_enables_writes(self):
        plan = self.prepare()
        with self.assertRaisesRegex(executor.Hold, 'apply_must_be_boolean'):
            executor.execute_reviewed_plan(plan, manifest=self.manifest, root=self.root,
                expected_plan_digest=plan['plan_digest'], apply='true')

    def test_initial_or_last_moment_drift_holds_with_zero_mutations(self):
        for read_number in (1, 2):
            with self.subTest(read=read_number):
                self.client = MockClient(self.snapshot, (self.root / 'asset.png').read_bytes())
                self.client.change_on_read[read_number] = lambda s: s['product']['variants'][0].update(price='11.00')
                with self.assertRaisesRegex(executor.Hold, 'snapshot_drift'):
                    self.run_apply()
                self.assertEqual(self.client.writes, 0)

    def test_evidence_changed_after_prepare_holds(self):
        plan = self.prepare()
        self.change_receipt(self.manifest['review_evidence']['rights'], disposition='pending')
        with self.assertRaises(executor.Hold):
            self.run_apply(plan)
        self.assertEqual(self.client.writes, 0)

    def test_durable_checkpoint_required_false_string_true_cannot_pass(self):
        for answer in (False, 'true', None):
            self.checkpoint = MockCheckpoint(answer)
            with self.assertRaisesRegex(executor.Hold, 'durable_checkpoint_not_verified'):
                self.run_apply()
            self.assertEqual(self.client.writes, 0)

    def test_write_ahead_saved_before_the_only_mutation(self):
        original = self.client.append_once
        def inspect(*args):
            journal = executor.read_json(self.journal_path)
            self.assertEqual(journal['state'], 'write_started')
            self.assertEqual(journal['write_attempts'], 1)
            self.assertEqual(journal['before'], self.snapshot)
            self.assertIn('expected_after', journal)
            return original(*args)
        self.client.append_once = inspect
        self.assertEqual(self.run_apply()['state'], 'verified')

    def test_timeout_after_commit_stops_unknown_then_reconciles_without_retry(self):
        self.client.after_append_error = TimeoutError('lost response')
        plan = self.prepare()
        self.assertEqual(self.run_apply(plan)['state'], 'write_unknown')
        self.assertEqual(executor.read_json(self.journal_path)['state'], 'write_unknown')
        self.assertEqual(self.run_apply(plan)['state'], 'reconciled_noop')
        self.assertEqual(self.client.writes, 1)

    def test_timeout_before_commit_never_blind_retries(self):
        self.client.before_append_error = TimeoutError('unknown result')
        plan = self.prepare()
        self.assertEqual(self.run_apply(plan)['state'], 'write_unknown')
        self.assertEqual(self.run_apply(plan)['state'], 'verification_pending')
        self.assertEqual(self.client.writes, 1)

    def test_duplicate_execution_is_readonly_reconciliation(self):
        plan = self.prepare()
        self.assertEqual(self.run_apply(plan)['state'], 'verified')
        self.assertEqual(self.run_apply(plan)['state'], 'reconciled_noop')
        self.assertEqual(self.client.writes, 1)

    def test_readback_price_status_inventory_publication_or_alt_drift_is_pending(self):
        changes = [lambda s: s['product'].update(status='DRAFT'),
                   lambda s: s['product']['variants'][0].update(price='90.00'),
                   lambda s: s['product']['variants'][0].update(inventoryQuantity=3),
                   lambda s: s['product']['publications'][0].update(isPublished=False),
                   lambda s: s['product']['media'][0].update(alt='changed')]
        for change in changes:
            self.client = MockClient(self.snapshot, (self.root / 'asset.png').read_bytes())
            self.client.change_on_read[3] = change
            self.assertEqual(self.run_apply()['state'], 'verification_pending')
            self.assertEqual(self.client.writes, 1)

    def test_readback_media_deleted_reordered_extra_or_wrong_pixels_pending(self):
        changes = [lambda s: s['product']['media'].pop(0),
                   lambda s: s['product']['media'].reverse(),
                   lambda s: s['product']['media'].append(deepcopy(s['product']['media'][-1])),
                   lambda s: s['product']['media'][-1].update(fingerprint=s['product']['media'][0]['fingerprint'])]
        for change in changes:
            self.client = MockClient(self.snapshot, (self.root / 'asset.png').read_bytes())
            self.client.change_on_read[3] = change
            self.assertEqual(self.run_apply()['state'], 'verification_pending')
            self.assertEqual(self.client.writes, 1)

    def test_poll_unready_media_is_bounded_and_zero_additional_writes(self):
        self.client.change_on_read[3] = lambda s: s['product']['media'][-1].update(status='PROCESSING')
        self.assertEqual(self.run_apply(polls=2)['state'], 'verification_pending')
        self.assertEqual((self.client.writes, self.client.reads), (1, 4))

    def test_same_operation_id_independent_of_observed_media_time(self):
        first = self.plan()['operation_id']
        self.snapshot['observed_at'] = (self.now - timedelta(seconds=1)).isoformat()
        self.assertEqual(self.plan()['operation_id'], first)

    def test_digest_stable_across_fresh_observation_times(self):
        first = self.plan()
        self.snapshot['observed_at'] = (self.now - timedelta(seconds=1)).isoformat()
        second = self.plan()
        self.assertNotEqual(first['before']['observed_at'], second['before']['observed_at'])
        self.assertEqual(first['plan_digest'], second['plan_digest'])
        self.assertEqual(first['implementation_digest'], executor.implementation_digest())

    def test_new_alt_is_required_review_bound_and_has_no_control_characters(self):
        for alt in (None, '', '   ', 'changed', 'bad\nalt', 'a' * 513):
            self.manifest['assets'][0]['alt_text'] = alt
            self.assert_plan_hold('reviewed_new_asset_alt_required')

    def test_new_alt_readback_mismatch_is_verification_pending(self):
        self.client.change_on_read[3] = lambda s: s['product']['media'][-1].update(alt='unreviewed')
        self.assertEqual(self.run_apply()['state'], 'verification_pending')
        self.assertEqual(self.client.writes, 1)

    def test_journal_or_operation_tampering_holds(self):
        plan = self.prepare()
        journal = executor.read_json(self.journal_path)
        journal['expected_after']['protected']['product']['status'] = 'DRAFT'
        executor.atomic_json(self.journal_path, journal)
        with self.assertRaisesRegex(executor.Hold, 'journal_shape'):
            self.run_apply(plan)
        self.assertEqual(self.client.writes, 0)

    def test_snapshot_reader_collects_all_protected_connections(self):
        client = executor.ShopifyClient('synthetic.myshopify.com', 'SYNTHETIC TOKEN',
            fetch=lambda url, hosts: (self.root / 'existing.png').read_bytes())
        product = self.snapshot['product']
        base = {'shop': self.snapshot['shop'], 'product': {k: v for k, v in product.items()
                if k not in {'media', 'variants', 'publications'}}}
        calls = []
        def gql(query, variables):
            calls.append(query)
            if query == executor.BASE_QUERY:
                return deepcopy(base)
            field, rows, parent = {
                executor.MEDIA_QUERY: ('media', [{k: v for k, v in m.items() if k != 'fingerprint'} for m in product['media']], 'product'),
                executor.VARIANTS_QUERY: ('variants', product['variants'], 'product'),
                executor.VARIANT_MEDIA_QUERY: ('media', product['variants'][0]['media'], 'node'),
                executor.INVENTORY_QUERY: ('inventoryLevels', product['variants'][0]['inventoryItem']['inventoryLevels'], 'node'),
                executor.PUBLICATIONS_QUERY: ('resourcePublications', product['publications'], 'product')}[query]
            return {parent: {'id': variables['id'], field: {'nodes': deepcopy(rows),
                'pageInfo': {'hasNextPage': False, 'endCursor': None}}}}
        client.gql = gql
        snapshot = client.read_snapshot(product['id'])
        self.assertIs(executor.validate_snapshot(snapshot)['complete'], True)
        self.assertEqual(executor.protection(snapshot), executor.protection(self.snapshot))
        self.assertEqual(len(calls), 7)

    def test_duplicate_json_keys_and_nonfinite_values_rejected(self):
        for raw in (b'{"approved":false,"approved":true}', b'{"quantity":NaN}', b'{"quantity":Infinity}'):
            with self.assertRaises(executor.Hold):
                executor.strict_json(raw)


class TransportTests(unittest.TestCase):
    def test_import_does_not_construct_network_client(self):
        with patch.object(executor, 'https_request', side_effect=AssertionError('network forbidden')):
            executor.ShopifyClient('synthetic.myshopify.com', 'SYNTHETIC TOKEN')

    def test_mutation_has_id_and_new_media_only(self):
        sent = []
        def request(url, **kwargs):
            sent.append(json.loads(kwargs['body']))
            return 200, {}, executor.json_bytes({'data': {'productUpdate': {'product': {'id': 'gid://shopify/Product/1'}, 'userErrors': []}}})
        client = executor.ShopifyClient('synthetic.myshopify.com', 'SYNTHETIC TOKEN', request=request)
        client.append_once('gid://shopify/Product/1', [{'asset_url': 'https://cdn.shopify.com/s/files/1/new.png', 'alt_text': 'Reviewed alt'}])
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['variables'], {'product': {'id': 'gid://shopify/Product/1'},
            'media': [{'originalSource': 'https://cdn.shopify.com/s/files/1/new.png', 'mediaContentType': 'IMAGE', 'alt': 'Reviewed alt'}]})

    def test_transport_timeout_never_retries(self):
        mock = unittest.mock.Mock(side_effect=TimeoutError('network synthetic'))
        client = executor.ShopifyClient('synthetic.myshopify.com', 'SYNTHETIC TOKEN', request=mock)
        with self.assertRaises(TimeoutError):
            client.append_once('gid://shopify/Product/1', [{'asset_url': 'https://cdn.shopify.com/s/files/1/new.png', 'alt_text': 'Reviewed alt'}])
        self.assertEqual(mock.call_count, 1)

    def test_redirect_image_fetch_is_rejected(self):
        with patch.object(executor, 'https_request', return_value=(302, {'location': 'https://evil.test'}, b'')):
            with self.assertRaisesRegex(executor.Hold, 'redirect'):
                executor.fetch_asset('https://cdn.shopify.com/s/files/1/a.png', {'cdn.shopify.com'})

    def test_existing_client_credentials_exchange_is_single_and_memory_only(self):
        calls = []
        def request(url, **kwargs):
            calls.append((url, kwargs))
            return 200, {}, b'{"access_token":"SYNTHETIC SHORT LIVED TOKEN"}'
        client = executor.ShopifyClient('synthetic.myshopify.com', client_id='SYNTHETIC ID',
            client_secret='SYNTHETIC SECRET', request=request)
        self.assertEqual(client.token, 'SYNTHETIC SHORT LIVED TOKEN')
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][0].endswith('/admin/oauth/access_token'))
        self.assertIn(b'grant_type=client_credentials', calls[0][1]['body'])

    def test_environment_transport_mismatch_or_missing_has_zero_requests(self):
        for configured in (None, '', 'other.myshopify.com', 'http://synthetic-transport.myshopify.com',
                           ' https://synthetic-transport.myshopify.com',
                           'https://synthetic-transport.myshopify.com/path',
                           'https://synthetic-transport.myshopify.com?x=1'):
            with self.subTest(configured=configured):
                env = {'SHOPIFY_CLIENT_ID': 'SYNTHETIC ID', 'SHOPIFY_CLIENT_SECRET': 'SYNTHETIC SECRET'}
                if configured is not None:
                    env['SHOPIFY_STORE'] = configured
                fake_request = unittest.mock.Mock(side_effect=AssertionError('network forbidden'))
                with patch.dict(os.environ, env, clear=True), self.assertRaises(executor.Hold):
                    executor.ShopifyClient.from_environment('synthetic-transport.myshopify.com', request=fake_request)
                fake_request.assert_not_called()

    def test_environment_transport_exact_normalization_allows_separate_canonical_shop(self):
        fake_request = unittest.mock.Mock(return_value=(200, {}, b'{"access_token":"SYNTHETIC TOKEN"}'))
        env = {'SHOPIFY_STORE': 'https://synthetic-transport.myshopify.com/',
               'SHOPIFY_CLIENT_ID': 'SYNTHETIC ID', 'SHOPIFY_CLIENT_SECRET': 'SYNTHETIC SECRET'}
        with patch.dict(os.environ, env, clear=True):
            client = executor.ShopifyClient.from_environment('synthetic-transport.myshopify.com', request=fake_request)
        self.assertEqual(client.shop, 'synthetic-transport.myshopify.com')
        self.assertEqual(fake_request.call_count, 1)
        self.assertEqual(fake_request.call_args.args[0],
                         'https://synthetic-transport.myshopify.com/admin/oauth/access_token')

    def test_admin_token_cannot_be_routed_to_scope_domain(self):
        fake_request = unittest.mock.Mock(side_effect=AssertionError('network forbidden'))
        with patch.dict(os.environ, {'SHOPIFY_STORE': 'synthetic-transport.myshopify.com',
                        'SHOPIFY_ADMIN_TOKEN': 'SYNTHETIC TOKEN'}, clear=True):
            with self.assertRaisesRegex(executor.Hold, 'transport_mismatch'):
                executor.ShopifyClient.from_environment('attacker.myshopify.com', request=fake_request)
        fake_request.assert_not_called()

    def test_private_loopback_linklocal_reserved_dns_never_connects(self):
        for address in ('127.0.0.1', '10.0.0.1', '169.254.169.254', '192.0.2.1', '::1', 'fc00::1', '224.0.0.1'):
            rows = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))]
            with patch.object(socket, 'getaddrinfo', return_value=rows), patch.object(socket, 'socket') as connect:
                with self.assertRaisesRegex(executor.Hold, 'non_public_network'):
                    executor.PinnedHTTPSConnection('cdn.shopify.com').connect()
                connect.assert_not_called()

    def test_paginated_reader_collects_every_page(self):
        client = executor.ShopifyClient('synthetic.myshopify.com', 'SYNTHETIC TOKEN')
        client.gql = unittest.mock.Mock(side_effect=[
            {'product': {'id': 'p', 'media': {'nodes': [{'id': 'm1'}], 'pageInfo': {'hasNextPage': True, 'endCursor': 'c1'}}}},
            {'product': {'id': 'p', 'media': {'nodes': [{'id': 'm2'}], 'pageInfo': {'hasNextPage': False, 'endCursor': 'c2'}}}}])
        self.assertEqual(client.connection('synthetic', 'p', 'media'), [{'id': 'm1'}, {'id': 'm2'}])
        self.assertEqual(client.gql.call_args.args[1]['after'], 'c1')

    def test_missing_pageinfo_string_true_repeated_cursor_duplicate_and_empty_page_hold(self):
        bad = [ {'nodes': [{'id': 'm'}]},
                {'nodes': [{'id': 'm'}], 'pageInfo': {'hasNextPage': 'true', 'endCursor': 'c'}},
                {'nodes': [], 'pageInfo': {'hasNextPage': True, 'endCursor': 'c'}},
                {'nodes': [{'id': 'm'}, {'id': 'm'}], 'pageInfo': {'hasNextPage': False, 'endCursor': 'c'}},
                {'nodes': [{'id': 'm'}], 'pageInfo': {'hasNextPage': True, 'endCursor': None}} ]
        for page in bad:
            client = executor.ShopifyClient('synthetic.myshopify.com', 'SYNTHETIC TOKEN')
            client.gql = lambda *args: {'product': {'id': 'p', 'media': page}}
            with self.assertRaises(executor.Hold):
                client.connection('synthetic', 'p', 'media')


class GitHubCheckpointTests(ExecutorTests):
    # Use the same fixture without duplicating its inherited test methods.
    def build_backend(self, *, mutate_artifact=None, mutate_run=None, list_payload=None, zip_entries=None):
        plan = self.prepare()
        journal = executor.read_json(self.journal_path)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            for name, raw in (zip_entries or {'plan.json': executor.json_bytes(plan), 'journal.json': executor.json_bytes(journal)}).items():
                archive.writestr(name, raw)
        raw = buffer.getvalue()
        digest = hashlib.sha256(raw).hexdigest()
        artifact = {'id': 90, 'name': journal['artifact_name'], 'expired': False, 'digest': 'sha256:' + digest,
                    'workflow_run': {'id': 1234, 'head_sha': self.context['code_sha']},
                    'created_at': self.now.isoformat(), 'expires_at': (self.now + timedelta(days=30)).isoformat()}
        run = {'id': 1234, 'run_attempt': 1, 'head_sha': self.context['code_sha'],
               'path': self.context['workflow_path'], 'event': 'workflow_dispatch', 'status': 'in_progress'}
        if mutate_artifact:
            mutate_artifact(artifact)
        if mutate_run:
            mutate_run(run)
        calls = []
        def request(url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith('/zip'):
                return 200, {}, raw
            if '/actions/artifacts?' in url:
                data = list_payload or {'total_count': 1, 'artifacts': [artifact]}
            elif '/actions/runs/' in url:
                data = run
            else:
                data = artifact
            return 200, {}, executor.json_bytes(data)
        return plan, journal, executor.GitHubCheckpoint('SYNTHETIC TOKEN', '90', digest, request=request), calls

    def test_checkpoint_validates_metadata_full_scan_and_exact_zip(self):
        plan, journal, backend, calls = self.build_backend()
        self.assertIs(backend.verify(plan, journal), True)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(call[1].get('method', 'GET') == 'GET' for call in calls))

    def test_artifact_expired_wrong_run_sha_name_digest_or_retention_holds(self):
        mutations = [lambda a: a.update(expired=True), lambda a: a.update(name='wrong'),
                     lambda a: a.update(digest='sha256:' + '0' * 64),
                     lambda a: a['workflow_run'].update(id=999),
                     lambda a: a['workflow_run'].update(head_sha='c' * 40),
                     lambda a: a.update(expires_at=(self.now + timedelta(days=29)).isoformat())]
        for mutation in mutations:
            plan, journal, backend, _ = self.build_backend(mutate_artifact=mutation)
            with self.assertRaises(executor.Hold):
                backend.verify(plan, journal)

    def test_wrong_workflow_run_attempt_event_or_code_hold(self):
        for field, value in (('event', 'push'), ('run_attempt', 2), ('head_sha', 'c' * 40),
                             ('path', '.github/workflows/other.yml'), ('status', 'completed')):
            plan, journal, backend, _ = self.build_backend(mutate_run=lambda run: run.update({field: value}))
            with self.assertRaisesRegex(executor.Hold, 'workflow_mismatch'):
                backend.verify(plan, journal)

    def test_prior_operation_artifact_blocks_new_write(self):
        plan, journal, backend, _ = self.build_backend()
        prior = {'id': 89, 'name': 'gallery-checkpoint-' + plan['operation_id'] + '-1000-1'}
        original = backend.api
        current = original('/repos/synthetic/repo/actions/artifacts/90')
        backend.api = lambda path, **kwargs: ({'total_count': 2, 'artifacts': [prior, current]} if '?' in path else original(path, **kwargs))
        with self.assertRaisesRegex(executor.Hold, 'prior_operation_checkpoint_reconcile_only'):
            backend.verify(plan, journal)

    def test_incomplete_artifact_scan_fails_closed(self):
        plan, journal, backend, _ = self.build_backend(list_payload={'total_count': 1, 'artifacts': []})
        with self.assertRaisesRegex(executor.Hold, 'scan_incomplete'):
            backend.verify(plan, journal)

    def test_zip_requires_exact_plan_and_journal_and_no_extra_files(self):
        for entries in ({'plan.json': b'{}', 'journal.json': b'{}'},
                        {'../plan.json': b'{}', 'journal.json': b'{}'},
                        {'plan.json': b'{}', 'journal.json': b'{}', 'extra': b'123'}):
            plan, journal, backend, _ = self.build_backend(zip_entries=entries)
            with self.assertRaises(executor.Hold):
                backend.verify(plan, journal)

    def test_checkpoint_api_failure_never_falls_back_to_local_marker(self):
        plan, journal, backend, _ = self.build_backend()
        backend.request = lambda *args, **kwargs: (403, {}, b'{}')
        with self.assertRaisesRegex(executor.Hold, 'api_failed'):
            backend.verify(plan, journal)

    def test_restore_completed_run_is_readonly_and_exact_target_bound(self):
        plan, journal, backend, _ = self.build_backend(mutate_run=lambda run: run.update(status='completed', run_attempt=2))
        restored, original_journal = backend.restore('synthetic/repo', expected_plan_digest=plan['plan_digest'],
            expected_shop='synthetic.myshopify.com', expected_product='gid://shopify/Product/123')
        self.assertEqual(restored, plan)
        self.assertEqual(original_journal, journal)
        self.assertEqual(executor.reconcile(restored, self.client)['state'], 'verification_pending')
        self.assertEqual(self.client.writes, 0)
        with self.assertRaisesRegex(executor.Hold, 'exact_target_mismatch'):
            backend.restore('synthetic/repo', expected_plan_digest=plan['plan_digest'],
                expected_shop='other.myshopify.com', expected_product='gid://shopify/Product/123')

    def test_restore_rejects_fake_expected_digest(self):
        _, _, backend, _ = self.build_backend()
        with self.assertRaisesRegex(executor.Hold, 'plan_digest_mismatch'):
            backend.restore('synthetic/repo', expected_plan_digest='0' * 64,
                expected_shop='synthetic.myshopify.com', expected_product='gid://shopify/Product/123')


def load_tests(loader, tests, pattern):
    # Avoid running ExecutorTests twice merely to share fixture helpers.
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(ExecutorTests))
    suite.addTests(loader.loadTestsFromTestCase(TransportTests))
    for name in sorted(GitHubCheckpointTests.__dict__):
        if name.startswith('test_'):
            suite.addTest(GitHubCheckpointTests(name))
    return suite


if __name__ == '__main__':
    unittest.main()
