"""Offline canonical-copy migration fixtures; no live writes, model calls or Git commits."""
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import build_listing_copy_local as local
from scripts.publish_transaction import overlay, deletion_authorized, removed_identities, PublishError, sha
POLICY = json.loads((ROOT/'config/publish_policy.json').read_bytes())

# Constructed test-only historical/public migration shape, not current commerce
# data or approval. Keep this regression stable after live publication replaces
# the old ten-row copy artifact with eight current rows.
LEGACY_IDS = ('1049276', '1055167', '1049275', '1067498', '1072554',
              '1075857', '1049285', '1059834', '1027327', '1042619')
CANONICAL_IDS = ('1049276', '1055167', '1049275', '1067498',
                 '1068721', '1053482', '1074979', '1068733')


def migration_fixture_documents(legacy_ids=LEGACY_IDS, canonical_ids=CANONICAL_IDS):
    def product(pd_no):
        return {'pd_no': pd_no, 'name': 'Fixture cosmetic ' + pd_no,
                'bucket': 'S', 'price_krw': 3000, 'rating': 4.5,
                'review_count': 100, 'shopify_score': 80,
                'url': 'https://example.invalid/products/' + pd_no,
                'image_url': 'https://example.invalid/images/' + pd_no + '.jpg'}

    legacy_items = []
    for pd_no in legacy_ids:
        facts = product(pd_no)
        positive = pd_no != '1027327'
        legacy_items.append({
            'canonical_product_id': 'fixture-' + pd_no, 'pd_no': pd_no,
            'name_ko': facts['name'], 'bucket': facts['bucket'],
            'price_krw': facts['price_krw'], 'rating': facts['rating'],
            'review_count': facts['review_count'], 'shopify_score': facts['shopify_score'],
            'source_url': facts['url'], 'image_url': facts['image_url'],
            'copy': ({'title': 'Historical fixture draft ' + pd_no,
                      'description_html': '<p>Historical fixture, not approval.</p>',
                      'seo_title': 'Historical fixture draft',
                      'seo_description': 'Historical fixture, not approval.',
                      'tags': ['test-only'], 'product_type': 'Cosmetic'} if positive else None),
            'copy_status': 'ok' if positive else 'skipped_prerequisite',
            'generation_mode': 'fixture_historical_draft' if positive else 'none',
            'agent_blocked_by': [] if positive else ['us_label'],
            'error': '' if positive else 'ontology 선행 게이트 미통과: us_label',
        })
    previous = {
        'generated_at': '2026-10-02T22:21:17+00:00',
        'generator': 'scripts/build_listing_copy_local.py',
        'model': 'none_local_deterministic', 'paid_api_called': False,
        'source': local.SOURCE_REL,
        'note': 'Constructed historical regression fixture, never current approval.',
        'total': len(legacy_items), 'eligible': sum(r['copy'] is not None for r in legacy_items),
        'ok': sum(r['copy'] is not None for r in legacy_items), 'failed': 0,
        'skipped_prerequisite': sum(r['copy'] is None for r in legacy_items),
        'carried_forward': sum(r['copy'] is not None for r in legacy_items),
        'generated_local': 0, 'items': legacy_items,
    }
    source = {
        'generated_at': '2026-10-11T00:00:00+00:00',
        'canonical': True, 'source': 'test_only_constructed_fixture',
        'count': len(canonical_ids), 'agent_ready_count': 0, 'registerable_count': 0,
        'recommendations': [product(pd_no) for pd_no in canonical_ids],
    }
    gate_items = []
    for pd_no in canonical_ids:
        blockers = ['manufacturer_safety_record_missing', 'us_label']
        if pd_no == '1049275':
            blockers += ['price', 'legal', 'owner_deleted']
        gate_items.append({
            'pd_no': pd_no, 'canonical_product_id': 'fixture-' + pd_no,
            'agent_ready': False, 'ready': False,
            'agent_blocked_by': blockers, 'blocked_by': list(blockers),
            'owner_deleted': pd_no == '1049275',
        })
    gate = {'generated_at': '2026-10-11T00:00:00+00:00',
            'total': len(gate_items), 'ready': 0, 'agent_ready': 0, 'items': gate_items}
    return previous, source, gate


class ListingCopyPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'data/daiso_real').mkdir(parents=True)
        (self.root/'config').mkdir()
        (self.root/'config/publish_policy.json').write_text(json.dumps(POLICY),encoding='utf-8')
        self.generate(*migration_fixture_documents())

    def generate(self, legacy, canonical, gate):
        self.base=self.encode(legacy)
        self.source=self.encode(canonical)
        self.gate=self.encode(gate)
        for rel,raw in ((local.COPY_REL,self.base),(local.SOURCE_REL,self.source),(local.GATE_REL,self.gate)):
            (self.root/rel).write_bytes(raw)
        with patch.multiple(local,ROOT=self.root,DATA=self.root/'data',SRC=self.root/local.SOURCE_REL,GATE=self.root/local.GATE_REL,OUT=self.root/local.COPY_REL), redirect_stdout(io.StringIO()):
            self.assertEqual(local.main(),0)
        self.generated=(self.root/local.COPY_REL).read_bytes()
        self.evidence=(self.source,self.gate)
        self.retired=sorted(set(str(r['pd_no']) for r in json.loads(self.base)['items'])-set(str(r['pd_no']) for r in json.loads(self.source)['recommendations']))

    def record(self):
        def git(args,**kwargs):
            self.assertEqual(args[:3],['git','-C',str(self.root)])
            if args[3:]==['rev-parse','HEAD']:
                return SimpleNamespace(stdout='a'*40+'\n')
            self.assertEqual(args[3:],['show','a'*40+':'+local.COPY_REL])
            return SimpleNamespace(stdout=self.base)
        with patch.object(subprocess,'run',side_effect=git):
            result=local.record_publication(self.root)
        self.new=(self.root/local.COPY_REL).read_bytes()
        self.manifest=json.loads((self.root/'data/publish_deletions.json').read_bytes())
        return result

    def encode(self,doc):
        return (json.dumps(doc,ensure_ascii=False,indent=2)+'\n').encode()

    def test_frozen_ten_to_eight_retired_ids_exact_overlay_and_history(self):
        old = json.loads(self.base)
        canonical = json.loads(self.source)
        gate = json.loads(self.gate)
        self.assertEqual((old['total'], old['eligible'], old['ok']), (10, 9, 9))
        canonical_ids = {row['pd_no'] for row in canonical['recommendations']}
        survivors = [row for row in old['items'] if row['pd_no'] in canonical_ids]
        self.assertEqual(len(survivors), 4)
        self.assertTrue(all(isinstance(row['copy'], dict) for row in survivors))
        self.assertTrue(all(not row['agent_ready'] and not row['ready'] for row in gate['items']))
        owner_deleted = next(row for row in gate['items'] if row['pd_no'] == '1049275')
        self.assertTrue(owner_deleted['owner_deleted'])
        self.assertIn('owner_deleted', owner_deleted['agent_blocked_by'])
        self.assertEqual(self.retired,['1027327','1042619','1049285','1059834','1072554','1075857'])
        self.assertEqual(sorted(removed_identities(json.loads(self.base),json.loads(self.generated),POLICY)),self.retired)
        with self.assertRaises(PublishError):
            overlay(local.COPY_REL,self.base,self.generated,self.base,POLICY,{},copy_evidence=self.evidence)
        self.assertEqual(self.record()['retired_ids'],self.retired)
        self.assertEqual(overlay(local.COPY_REL,self.base,self.new,self.base,POLICY,self.manifest,copy_evidence=self.evidence),self.new)
        doc=json.loads(self.new)
        self.assertEqual((doc['total'],doc['eligible'],doc['ok']),(8,0,0))
        self.assertEqual(len(doc['items']),8)
        self.assertTrue(all(row['copy'] is None for row in doc['items']))
        historical=doc[local.HISTORY_KEY][sha(self.base)]
        self.assertTrue(historical['historical_not_approval'])
        self.assertEqual(historical['snapshot'],json.loads(self.base))
        self.assertEqual(len(historical['snapshot']['items']),10)
        self.assertTrue(any(r['pd_no']=='1049275' and r['copy'] for r in historical['snapshot']['items']))

    def test_deep_blocked_scope_rotation_requires_history_before_publication(self):
        # Structural reproduction of Deep 39563679590, not recovered run bytes.
        # Committed copy had seven blocked rows; the log lists eight new S rows.
        old_ids = ('1049276', '1055167', '1049275', '1067498', '1068721', '1074979', '1072800')
        new_ids = ('1049276', '1053482', '1055167', '1061918', '1067498', '1062781', '1074979', '1072800')
        previous, source, gate = migration_fixture_documents(old_ids, new_ids)
        for row in previous['items']:
            row.update(copy=None, copy_status='skipped_prerequisite', generation_mode='none',
                       agent_blocked_by=['us_label'], error='ontology 선행 게이트 미통과: us_label')
        previous.update(eligible=0, ok=0, skipped_prerequisite=7, carried_forward=0)
        # Previously retained history must survive even when no current copy has text.
        previous[local.HISTORY_KEY] = {'existing-fixture-history': {
            'historical_not_approval': True, 'snapshot': {'note': 'Previously retained fixture.'}}}
        self.generate(previous, source, gate)
        current = json.loads(self.generated)
        self.assertEqual((current['total'], current['eligible'], current['ok']), (8, 0, 0))
        self.assertEqual(current['skipped_prerequisite'], 8)
        self.assertEqual(local.verify_current(current, source, gate), set(new_ids))
        with self.assertRaisesRegex(ValueError, 'prior copy snapshot not preserved'):
            local.verify_copy_replacement(self.base, self.generated, *self.evidence)
        with self.assertRaisesRegex(PublishError, 'listing copy canonical/history evidence invalid'):
            overlay(local.COPY_REL, self.base, self.generated, self.base, POLICY, {},
                    copy_evidence=self.evidence)
        self.assertEqual(self.record()['retired_ids'], ['1049275', '1068721'])
        self.assertEqual(overlay(local.COPY_REL, self.base, self.new, self.base, POLICY,
                                 self.manifest, copy_evidence=self.evidence), self.new)
        published = json.loads(self.new)
        self.assertEqual(published['items'], current['items'])
        self.assertTrue(all(r['copy'] is None and r['copy_status'] == 'skipped_prerequisite'
                            for r in published['items']))
        retained = published[local.HISTORY_KEY]
        self.assertEqual(retained['existing-fixture-history'], previous[local.HISTORY_KEY]['existing-fixture-history'])
        self.assertTrue(retained[sha(self.base)]['historical_not_approval'])
        self.assertEqual(retained[sha(self.base)]['snapshot'],
                         {k: v for k, v in previous.items() if k != local.HISTORY_KEY})
        before = self.new
        self.record()
        self.assertEqual(self.new, before)

    def test_record_rejects_changed_gate_without_writing_candidate_or_manifest(self):
        self.record()
        original_copy = (self.root/local.COPY_REL).read_bytes()
        original_manifest = (self.root/'data/publish_deletions.json').read_bytes()
        changed = json.loads(self.gate)
        changed['items'][0]['agent_ready'] = True
        (self.root/local.GATE_REL).write_bytes(self.encode(changed))
        with self.assertRaises(ValueError):
            self.record()
        self.assertEqual((self.root/local.COPY_REL).read_bytes(), original_copy)
        self.assertEqual((self.root/'data/publish_deletions.json').read_bytes(), original_manifest)

    def test_equal_count_scope_replacement_still_requires_history(self):
        # Same identity transition as committed f47 data; all values below are
        # synthetic so this regression does not depend on future live products.
        old_ids = ('1049276', '1055167', '1049275', '1067498', '1068721', '1074979', '1072800')
        new_ids = tuple('1061918' if pd_no == '1049275' else pd_no for pd_no in old_ids)
        previous, source, gate = migration_fixture_documents(old_ids, new_ids)
        for row in previous['items']:
            row.update(copy=None, copy_status='skipped_prerequisite', generation_mode='none',
                       agent_blocked_by=['us_label'], error='ontology 선행 게이트 미통과: us_label')
        previous.update(eligible=0, ok=0, skipped_prerequisite=7, carried_forward=0)
        self.generate(previous, source, gate)
        self.assertEqual(json.loads(self.generated)['total'], previous['total'])
        with self.assertRaisesRegex(ValueError, 'prior copy snapshot not preserved'):
            local.verify_copy_replacement(self.base, self.generated, *self.evidence)
        self.assertEqual(self.record()['retired_ids'], ['1049275'])
        self.assertEqual(overlay(local.COPY_REL, self.base, self.new, self.base, POLICY,
                                 self.manifest, copy_evidence=self.evidence), self.new)

    def test_modern_accuracy_field_loss_remains_fail_closed(self):
        # Separate pre-existing limitation, not the observed all-blocked Deep
        # baseline. Wiring history recording must not silently waive row schema.
        previous, source, gate = migration_fixture_documents()
        previous['items'][0]['product_accuracy'] = {
            'schema_version': 1, 'status': 'UNVERIFIED_DRAFT',
            'human_review_required': True, 'publication_allowed': False,
            'safety_approval': False, 'overall_legal_clearance': False,
        }
        self.generate(previous, source, gate)
        generated = (self.root/local.COPY_REL).read_bytes()
        self.assertNotIn('product_accuracy', json.loads(generated)['items'][0])
        with self.assertRaisesRegex(ValueError, 'surviving copy row schema field removed'):
            self.record()
        self.assertEqual((self.root/local.COPY_REL).read_bytes(), generated)
        self.assertFalse((self.root/'data/publish_deletions.json').exists())

    def test_missing_forged_or_edited_history_rejected(self):
        self.record()
        for mode in ('missing','forged','snapshot_digest','approval'):
            bad=json.loads(self.new)
            entry=bad[local.HISTORY_KEY][sha(self.base)]
            if mode=='missing': del bad[local.HISTORY_KEY]
            elif mode=='forged': entry['snapshot']['items'][0]['copy']=None
            elif mode=='snapshot_digest': entry['snapshot_sha256']='0'*64
            else: entry['historical_not_approval']=False
            with self.assertRaises(PublishError):
                overlay(local.COPY_REL,self.base,self.encode(bad),self.base,POLICY,self.manifest,copy_evidence=self.evidence)

    def test_canonical_gate_changes_blank_evidence_and_legacy_approval_rejected(self):
        self.record()
        source=json.loads(self.source);source['recommendations'].pop()
        gate=json.loads(self.gate);gate['items'][0]['agent_ready']=True
        for evidence in ((self.encode(source),self.gate),(self.source,self.encode(gate)),None):
            with self.assertRaises(PublishError):
                overlay(local.COPY_REL,self.base,self.new,self.base,POLICY,self.manifest,copy_evidence=evidence)
        for field,value in (('note',''),('source',None)):
            bad=json.loads(self.new);bad[field]=value
            with self.assertRaises(PublishError):
                overlay(local.COPY_REL,self.base,self.encode(bad),self.base,POLICY,self.manifest,copy_evidence=self.evidence)
        bad=json.loads(self.new)
        row=next(r for r in bad['items'] if str(r['pd_no'])=='1049275')
        row['copy']=next(r['copy'] for r in json.loads(self.base)['items'] if str(r['pd_no'])=='1049275')
        row['copy_status']='ok'
        with self.assertRaises(PublishError):
            overlay(local.COPY_REL,self.base,self.encode(bad),self.base,POLICY,self.manifest,copy_evidence=self.evidence)

    def test_missing_or_stale_hash_cannot_use_alternate_manifest(self):
        self.record()
        for mode in ('missing','stale','alternate'):
            manifest=copy.deepcopy(self.manifest);entry=manifest['deletions'][-1]
            if mode=='missing':entry.pop('replacement_sha256')
            elif mode=='stale':entry['replacement_sha256']='0'*64
            else:entry['policy_ref']='legacy_rotator'
            self.assertFalse(deletion_authorized(local.COPY_REL,self.base,self.retired,manifest,replacement=self.new,copy_evidence=self.evidence))
        self.assertFalse(deletion_authorized(local.COPY_REL,self.base+b' ',self.retired,self.manifest,replacement=self.new,copy_evidence=self.evidence))

    def test_record_idempotent_clock_only_and_prior_history_preserved(self):
        self.record();first=self.new
        self.record();self.assertEqual(self.new,first)
        prior=json.loads(first);next_doc=copy.deepcopy(prior);next_doc['generated_at']='later clock'
        local.archive_previous(next_doc,prior,first)
        self.assertEqual(next_doc[local.HISTORY_KEY],prior[local.HISTORY_KEY])
        local.verify_copy_replacement(first,self.encode(next_doc),*self.evidence)
        bad=copy.deepcopy(next_doc);bad[local.HISTORY_KEY]={}
        with self.assertRaises(ValueError):local.verify_copy_replacement(first,self.encode(bad),*self.evidence)

    def test_other_product_safety_owner_deletion_not_authorized(self):
        self.record()
        old=b'{"items":[{"pd_no":"1049275","owner_deleted":true,"us_label":"blocked","manufacturer_safety_record":"missing"}]}'
        for rel in ('data/daiso_real/products.json','data/product_master.json','data/daiso_real/daiso_us_labels.json'):
            with self.assertRaises(PublishError):overlay(rel,old,b'{"items":[]}',old,POLICY,self.manifest)

    def test_import_reader_ignores_historical_drafts(self):
        self.record()
        from scripts import build_shopify_import_csv as report
        with patch.multiple(report,ROOT=self.root,COPY=self.root/local.COPY_REL,PRICING=self.root/'data/pricing_model.json',STATUS=self.root/'data/daiso_real/collection_status.json',OUT=self.root/'data/shopify_import.csv',REPORT=self.root/'data/shopify_import_report.json'),redirect_stdout(io.StringIO()):
            self.assertEqual(report.main(),0)
        doc=json.loads((self.root/'data/shopify_import_report.json').read_bytes())
        self.assertEqual((doc['rows'],len(doc['skipped'])),(0,8))
        self.assertEqual(len((self.root/'data/shopify_import.csv').read_text().splitlines()),1)

if __name__=='__main__':unittest.main(verbosity=2)
