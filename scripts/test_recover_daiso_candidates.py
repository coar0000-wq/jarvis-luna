"""Offline counter recovery guard tests. No network, resets or production writes."""
from copy import deepcopy
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import recover_daiso_candidates as recovery
from scripts import daiso_pipeline_inputs as proof
from scripts.publish_transaction import overlay, PublishError

POLICY = {'identity_fields': ['pd_no', 'id', 'url']}


class CounterRecoveryTests(unittest.TestCase):
    def fixture(self):
        old_run = {'prefetch_policy': {'skipped': {'candidate_recently_verified': 1}}, 'queue_size': 1}
        new_run = {'prefetch_policy': {'skipped': {'operating_identity': 2},
                   'new_identities': 3, 'revalidation_identities': 1}, 'queue_size': 6}
        base = proof.encode({'last_run': old_run, 'last_attempt': old_run,
                             'last_candidate_success': {'candidate_ids': ['old']}})
        capture = proof.encode({'last_run': new_run, 'last_attempt': new_run,
                                'last_candidate_success': {'candidate_ids': ['new']}})
        manifest = {'schema_version': 1, 'deletions': [{
            'path': proof.STATUS, 'base_sha256': proof.sha(base),
            'replacement_sha256': proof.sha(capture), 'ids': ['old'], 'delete_file': False,
            'policy_ref': 'fixture_prior_snapshot_authorization',
            'reason': 'Prior explicit snapshot identity replacement with retained history.'}]}
        return base, capture, manifest

    def test_original_bytes_stay_bound_and_normal_guard_accepts_narrow_reason(self):
        base, capture, manifest = self.fixture()
        before = deepcopy(manifest)
        with self.assertRaises(PublishError):
            overlay(proof.STATUS, base, capture, base, POLICY, manifest)
        fixed = recovery.counter_manifest(base, capture, manifest, POLICY)
        self.assertEqual(overlay(proof.STATUS, base, capture, base, POLICY, fixed), capture)
        self.assertEqual(manifest, before)
        entry = fixed['deletions'][-1]
        self.assertEqual(entry['ids'], ['candidate_recently_verified', 'old'])
        self.assertEqual(entry['replacement_sha256'], proof.sha(capture))
        self.assertFalse(entry['delete_file'])

    def test_unexpected_field_deletion_never_gets_a_reason_waiver(self):
        base, capture, manifest = self.fixture()
        old = json.loads(base); old['business_required'] = True
        with self.assertRaisesRegex(ValueError, 'outside sparse skip counters'):
            recovery.counter_manifest(proof.encode(old), capture, manifest, POLICY)

    def test_other_identity_removal_without_prior_authorization_is_blocked(self):
        base, capture, _ = self.fixture()
        with self.assertRaisesRegex(ValueError, 'prior exact-base authorization'):
            recovery.counter_manifest(base, capture, {'deletions': []}, POLICY)

    def test_counter_reason_cannot_authorize_changed_capture_bytes(self):
        base, capture, manifest = self.fixture()
        fixed = recovery.counter_manifest(base, capture, manifest, POLICY)
        with self.assertRaises(PublishError):
            overlay(proof.STATUS, base, capture + b' ', base, POLICY, fixed)

    def test_incomplete_tally_cannot_claim_omitted_zero(self):
        base, capture, manifest = self.fixture()
        doc = json.loads(capture); doc['last_run']['queue_size'] += 1
        with self.assertRaisesRegex(ValueError, 'full queue tally evidence'):
            recovery.counter_manifest(base, proof.encode(doc), manifest, POLICY)

    def test_unknown_counter_field_is_not_auto_authorized(self):
        base, capture, manifest = self.fixture()
        doc = json.loads(base); doc['last_run']['prefetch_policy']['skipped']['unknown_reason'] = 1
        with self.assertRaisesRegex(ValueError, 'outside sparse skip counters'):
            recovery.counter_manifest(proof.encode(doc), capture, manifest, POLICY)

    def test_unrelated_nested_same_named_field_is_not_authorized(self):
        base, capture, manifest = self.fixture()
        doc = json.loads(base); doc['business'] = {'candidate_recently_verified': 1}
        new = json.loads(capture); new['business'] = {}
        with self.assertRaisesRegex(ValueError, 'outside sparse skip counters'):
            recovery.counter_manifest(proof.encode(doc), proof.encode(new), manifest, POLICY)


class PreparationTests(unittest.TestCase):
    fixture = CounterRecoveryTests.fixture
    def prepare_fixture(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        base, captured, _ = self.fixture()
        source = json.loads(captured)
        source['last_run'].update(execution_id='11:1:collect', status='candidates_collected',
            operating_updates_enabled=False, ok=0, candidate_count=2, candidates_new=1,
            finished_at='2026-10-11T03:26:00Z')
        source['last_attempt'] = deepcopy(source['last_run'])
        captured = proof.encode(source)
        manifest = {'schema_version': 1, 'deletions': [{
            'path': proof.STATUS, 'base_sha256': proof.sha(base),
            'replacement_sha256': proof.sha(captured), 'ids': ['old'], 'delete_file': False,
            'policy_ref': 'fixture_prior_snapshot_authorization', 'reason': 'Explicit prior snapshot replacement.'}]}
        old_receipt = proof.encode({'kind':'collector_receipt','receipt':{'execution_id':'10:1:collect'}})
        old_name = proof.HISTORY + '/' + proof.sha(old_receipt) + '.json'
        original_receipt = proof.encode({'kind':'collector_receipt','receipt':{'execution_id':'11:1:collect'}})
        new_name = proof.HISTORY + '/' + proof.sha(original_receipt) + '.json'
        old_pool={'schema_version':1,'items':{'old':{'pd_no':'old','price_krw':1000}}}
        new_pool=deepcopy(old_pool); new_pool['items']['new']={'pd_no':'new','price_krw':2000}
        existing = {proof.STATUS:base, proof.POOL:proof.encode(old_pool), proof.OPERATING:b'{"products":[]}', recovery.MANIFEST:proof.encode(manifest),
                    'config/publish_policy.json':proof.encode(POLICY), old_name:old_receipt,
                    proof.INDEX:proof.encode({'schema_version':1,'history_sha256':[proof.sha(old_receipt)],'public_authority':False}),
                    'data/operations/state.json':b'private operation sentinel'}
        for name, raw in existing.items():
            target=root/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(raw)
        members={proof.STATUS:captured, proof.POOL:proof.encode(new_pool),
                 recovery.MANIFEST:proof.encode(manifest),new_name:original_receipt,
                 proof.INDEX:proof.encode({'schema_version':1,'history_sha256':[proof.sha(original_receipt)],'public_authority':False})}
        run={'id':11,'run_attempt':1,'status':'completed','path':'.github/workflows/'+proof.WORKFLOW,
             'head_branch':'main','repository':{'full_name':proof.REPOSITORY},'head_repository':{'full_name':proof.REPOSITORY},
             'event':'workflow_dispatch','head_sha':'a'*40,
             'html_url':'https://github.com/'+proof.REPOSITORY+'/actions/runs/11'}
        return root,base,members,run,old_name,new_name

    def test_preparation_preserves_original_capture_clock_bytes_history_and_operations(self):
        root,base,members,run,old_name,new_name=self.prepare_fixture()
        with patch.object(proof,'exact_head',side_effect=lambda r,n:(Path(r)/n).read_bytes()), \
             patch.object(proof,'verify_bound_entry',return_value=({'mode':'candidates'},None,None)) as verify:
            result=recovery.prepare(root,members,run,{}, {'id':12},'b'*64,
                                    datetime(2026,10,11,4,tzinfo=timezone.utc))
        verify.assert_called_once()
        self.assertEqual((root/proof.STATUS).read_bytes(),members[proof.STATUS])
        self.assertEqual((root/proof.POOL).read_bytes(),members[proof.POOL])
        self.assertTrue((root/old_name).exists()); self.assertEqual((root/new_name).read_bytes(),members[new_name])
        index=json.loads((root/proof.INDEX).read_bytes())
        self.assertEqual(set(index['history_sha256']),{Path(old_name).stem,Path(new_name).stem})
        self.assertEqual((root/'data/operations/state.json').read_bytes(),b'private operation sentinel')
        self.assertEqual(result['record']['original_execution_id'],'11:1:collect')
        self.assertFalse(result['record']['recollected']); self.assertFalse(result['record']['public_authority'])

    def test_operating_capture_cannot_enter_candidate_recovery(self):
        root,base,members,run,_,_=self.prepare_fixture()
        doc=json.loads(members[proof.STATUS]); doc['last_run']['operating_updates_enabled']=True
        members[proof.STATUS]=proof.encode(doc)
        with self.assertRaisesRegex(ValueError,'only candidates-only'):
            recovery.prepare(root,members,run,{}, {'id':12},'b'*64)
        self.assertEqual((root/proof.STATUS).read_bytes(),base)

    def test_snapshot_rotation_cannot_hide_a_lost_candidate_product(self):
        root,base,members,run,_,_=self.prepare_fixture()
        pool=json.loads(members[proof.POOL]); del pool['items']['old']; members[proof.POOL]=proof.encode(pool)
        with patch.object(proof,'exact_head',side_effect=lambda r,n:(Path(r)/n).read_bytes()), \
             self.assertRaisesRegex(ValueError,'prior candidate product was removed or changed'):
            recovery.prepare(root,members,run,{}, {'id':12},'b'*64)
        self.assertEqual((root/proof.STATUS).read_bytes(),base)

    def test_fork_capture_is_rejected_before_writing(self):
        root,base,members,run,_,_=self.prepare_fixture()
        run['head_repository']['full_name']='untrusted/fork'
        with self.assertRaisesRegex(ValueError,'fork or non-main'):
            recovery.prepare(root,members,run,{}, {'id':12},'b'*64)
        self.assertEqual((root/proof.STATUS).read_bytes(),base)

    def test_wrong_capture_execution_cannot_be_relabelled(self):
        root,base,members,run,_,_=self.prepare_fixture()
        doc=json.loads(members[proof.STATUS]); doc['last_run']['execution_id']='99:1:collect'
        members[proof.STATUS]=proof.encode(doc)
        with self.assertRaisesRegex(ValueError,'only candidates-only'):
            recovery.prepare(root,members,run,{}, {'id':12},'b'*64)
        self.assertEqual((root/proof.STATUS).read_bytes(),base)


class RecordedCaptureTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('RECOVERY_TEST_CAPTURE_DIR') and os.environ.get('RECOVERY_TEST_API_DIR'),
                         'optional independently recorded capture fixture not supplied')
    def test_real_recorded_capture_preserves_original_source_bytes(self):
        project=Path(__file__).resolve().parents[1]
        capture=Path(os.environ['RECOVERY_TEST_CAPTURE_DIR']); api=Path(os.environ['RECOVERY_TEST_API_DIR'])
        members={'data/'+p.relative_to(capture).as_posix():p.read_bytes() for p in capture.rglob('*') if p.is_file()}
        run=json.loads((api/'recovery-origin-run.json').read_bytes())
        jobs=json.loads((api/'recovery-origin-jobs.json').read_bytes())
        metadata=json.loads((api/'recovery-origin-artifact.json').read_bytes())
        def head(name):
            result=subprocess.run(['git','-C',str(project),'show','HEAD:'+name],capture_output=True,check=True)
            return result.stdout
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in (proof.STATUS,proof.POOL,proof.OPERATING,proof.INDEX,recovery.MANIFEST,'config/publish_policy.json'):
                target=root/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(head(name))
            for path in (project/proof.HISTORY).iterdir():
                target=root/proof.HISTORY/path.name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(path.read_bytes())
            with patch.object(proof,'exact_head',side_effect=lambda r,n:head(n)):
                result=recovery.prepare(root,members,run,jobs,metadata,metadata['digest'].removeprefix('sha256:'))
            self.assertEqual((root/proof.STATUS).read_bytes(),members[proof.STATUS])
            self.assertEqual((root/proof.POOL).read_bytes(),members[proof.POOL])
            self.assertEqual((root/proof.OPERATING).read_bytes(),head(proof.OPERATING))
            self.assertEqual(result['record']['original_run_id'],run['id'])
            self.assertFalse(result['record']['recollected'])
            self.assertFalse(result['record']['operating_changed'])
            base=head(proof.STATUS); local=members[proof.STATUS]
            policy=json.loads(head('config/publish_policy.json'))
            manifest=json.loads((root/recovery.MANIFEST).read_bytes())
            self.assertEqual(overlay(proof.STATUS,base,local,base,policy,manifest),local)


if __name__ == '__main__':
    unittest.main(verbosity=2)
