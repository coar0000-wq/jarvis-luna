"""Offline transfer fixtures. Never transfer, request credentials or touch live data."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts import repository_identity as identity
from scripts import github_artifact_io as transport
from scripts import daiso_pipeline_inputs as pipeline
from scripts import collect_workflow_status as workflow
from scripts import restore_source_safety as source_restore
from scripts import source_safety_checkpoint as source_safety
import restore_operations_safety as operations_restore
from scripts.repository_identity_fixture import isolate_source, source_policy
from scripts import test_daiso_pipeline_inputs as pipeline_tests
from scripts import test_observe_daiso_pipeline as observer_tests
from scripts import test_source_safety_checkpoint as source_tests
import test_restore_operations_safety as operations_tests


def repository(name):
    return {'id': identity.REPOSITORY_ID, 'full_name': name,
            'owner': {'id': identity.OWNER_IDS[name]}}


def run_for(name, rid=11, attempt=1, commit='a'*40):
    return {'id': rid, 'run_attempt': attempt, 'head_sha': commit,
            'repository': repository(name), 'head_repository': repository(name),
            'head_branch': 'main', 'path': '.github/workflows/daiso-real-collection.yml',
            'html_url': f'https://github.com/{name}/actions/runs/{rid}'}


def artifact_for(run, kind='daiso-attempt', aid=12, digest='sha256:'+'b'*64):
    return {'id': aid, 'name': f"{kind}-{run['id']}-{run['run_attempt']}", 'digest': digest,
            'workflow_run': {'id': run['id'], 'head_sha': run['head_sha'], 'head_branch': 'main',
                             'repository_id': identity.REPOSITORY_ID,
                             'head_repository_id': identity.REPOSITORY_ID}}


def pin_for(run, artifact):
    return {'repository': identity.SOURCE, 'repository_id': identity.REPOSITORY_ID,
            'run_id': run['id'], 'run_attempt': run['run_attempt'], 'head_sha': run['head_sha'],
            'artifact_id': artifact['id'], 'artifact_name': artifact['name'],
            'artifact_digest': artifact['digest']}


def policy_for(pins=None):
    if pins is None:
        run = run_for(identity.SOURCE, rid=999)
        pins = [pin_for(run, artifact_for(run, aid=999))]
    return identity.IdentityPolicy({'schema_version': 1, 'repository_id': identity.REPOSITORY_ID,
            'current_repository': identity.TARGET, 'current_owner_id': identity.OWNER_IDS[identity.TARGET],
            'cutover_head_sha': 'c'*40, 'historical_artifacts': pins})


class IdentityTests(unittest.TestCase):
    def setUp(self):
        isolate_source(self)

    def test_explicit_source_policy_is_source_only(self):
        self.assertEqual(source_policy().current, identity.SOURCE)
        self.assertEqual(identity.POLICY.pins, ())
        with self.assertRaises(ValueError):
            identity.POLICY.run_repository(run_for(identity.TARGET))

    def test_target_current_run_requires_fixed_id_and_exact_namespace(self):
        policy = policy_for()
        current = run_for(identity.TARGET)
        self.assertEqual(policy.run_repository(current), identity.TARGET)
        mutations = [lambda r: r['repository'].update(id=1),
                     lambda r: r['head_repository'].update(id=1),
                     lambda r: r['repository'].pop('id'),
                     lambda r: r['repository']['owner'].update(id=301755647),
                     lambda r: r['repository'].update(full_name=identity.SOURCE),
                     lambda r: r.update(id=True), lambda r: r.update(run_attempt=0)]
        for mutation in mutations:
            changed = copy.deepcopy(current); mutation(changed)
            with self.subTest(run=changed), self.assertRaises(ValueError):
                policy.run_repository(changed)

    def test_historical_alias_needs_exact_tuple_never_blanket_owner(self):
        run = run_for(identity.SOURCE)
        artifact = artifact_for(run)
        policy = policy_for([pin_for(run, artifact)])
        self.assertEqual(policy.artifact_repository(run, artifact), identity.SOURCE)
        # Current API namespace can carry the same old bytes, with the same pin.
        self.assertEqual(policy.artifact_repository(run_for(identity.TARGET), artifact), identity.SOURCE)
        for key, value in [('id', 22), ('run_attempt', 2), ('head_sha', 'd'*40)]:
            changed = dict(run, **{key:value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                policy.artifact_repository(changed, artifact)
        for key, value in [('id', 22), ('name', 'daiso-attempt-11-2'), ('digest', 'sha256:'+'d'*64)]:
            changed = dict(artifact, **{key:value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                policy.artifact_repository(run, changed)
        with self.assertRaises(ValueError):
            policy.run_repository(run)  # Historical permission is never live permission.

    def test_runner_cannot_switch_owner_with_environment(self):
        values = {'GITHUB_ACTIONS':'true', 'GITHUB_REPOSITORY':identity.TARGET,
                  'GITHUB_REPOSITORY_ID':str(identity.REPOSITORY_ID),
                  'GITHUB_REPOSITORY_OWNER_ID':str(identity.OWNER_IDS[identity.TARGET])}
        policy_for().runner(values)
        with self.assertRaises(ValueError): identity.POLICY.runner(values)
        for key in ('GITHUB_REPOSITORY_ID', 'GITHUB_REPOSITORY_OWNER_ID'):
            wrong = dict(values); wrong.pop(key)
            with self.assertRaises(ValueError): policy_for().runner(wrong)
        with self.assertRaises(ValueError): identity.POLICY.runner({'GITHUB_ACTIONS':'true'})

    def test_api_scope_is_one_owner_no_redirect_alias(self):
        target = 'https://api.github.com/repos/'+identity.TARGET+'/actions/artifacts/12/zip'
        source = target.replace(identity.TARGET, identity.SOURCE)
        with patch.object(transport, 'REPOSITORY', identity.TARGET):
            transport._api_url(target, artifact=True)
            with self.assertRaises(transport.ArtifactReadBlocked): transport._api_url(source, artifact=True)
            with self.assertRaises(transport.ArtifactReadBlocked): transport._api_url(target+'?alias=1', artifact=True)

    def test_production_http_metadata_requires_fixed_repository_ids(self):
        run = run_for(identity.SOURCE)
        class Response(io.BytesIO):
            status = 200
            headers = {}
        class Opener:
            def open(self, request, timeout): return Response(json.dumps(run).encode())
        url = 'https://api.github.com/repos/'+identity.SOURCE+'/actions/runs/11'
        with patch.object(transport.urllib.request, 'build_opener', return_value=Opener()):
            self.assertEqual(transport.fetch_github_json(url)['id'], 11)
            del run['repository']['id']
            with self.assertRaises(transport.ArtifactReadBlocked): transport.fetch_github_json(url)

    def transport_fixture(self, values):
        class Response(io.BytesIO):
            status = 200
            headers = {}
        class Opener:
            def open(self, request, timeout):
                value = values(request.full_url)
                return Response(json.dumps(value).encode())
        return patch.object(transport.urllib.request, 'build_opener', return_value=Opener())

    def test_unrelated_fork_main_does_not_poison_source_restore(self):
        fixture = self.fixture(source_tests.SafetyCheckpointTests)
        fixture.lineage['repository'] = identity.SOURCE
        fixture.pack(); fixture.copy_current()
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as z: z.writestr('source-safety.zip', fixture.archive.read_bytes())
        outer = stream.getvalue()
        run = run_for(identity.SOURCE, rid=123, attempt=2); run['status']='completed'
        fork = dict(run_for(identity.SOURCE, rid=9999), path='.github/workflows/preflight.yml',
                    status='in_progress', head_repository={'id':42, 'full_name':'foreign/fork'})
        metadata = artifact_for(run, 'source-safety', aid=200, digest='sha256:'+hashlib.sha256(outer).hexdigest())
        metadata.update(expired=False, archive_download_url=source_restore.BASE+'artifacts/200/zip')
        def values(url):
            return {'workflow_runs':[fork,run]} if '/runs?' in url else {'artifacts':[metadata]}
        with self.transport_fixture(values), patch.object(source_restore, '_git', return_value=subprocess.CompletedProcess([],0,b'',b'')):
            result = source_restore.restore_latest(fixture.target, fetch_json=transport.fetch_github_json, fetch_bytes=lambda u:outer)
            self.assertEqual(result['status'], 'authenticated_source_safety_restored')
            run['repository']['id'] = 42
            with self.assertRaises(ValueError):
                source_restore.restore_latest(fixture.target, fetch_json=transport.fetch_github_json, fetch_bytes=lambda u:outer)

    def test_unrelated_fork_main_does_not_poison_operations_restore(self):
        fixture = self.fixture(operations_tests.RestoreTests)
        fixture.run.update(repository=repository(identity.SOURCE), head_repository=repository(identity.SOURCE))
        fixture.artifact['workflow_run'].update(repository_id=identity.REPOSITORY_ID, head_repository_id=identity.REPOSITORY_ID)
        fork = dict(run_for(identity.SOURCE, rid=9999), path='.github/workflows/preflight.yml',
                    status='in_progress', head_repository={'id':42, 'full_name':'foreign/fork'})
        def values(url):
            return {'workflow_runs':[fork,fixture.run]} if '/runs?' in url else {'total_count':1,'artifacts':[fixture.artifact]}
        with self.transport_fixture(values):
            result = operations_restore.restore_latest(fixture.root, fetch_json=operations_restore.transport.fetch_github_json,
                                                        fetch_bytes=lambda u:fixture.raw)
            self.assertEqual(result['status'], 'authenticated_operations_safety_restored')
            fixture.run['repository']['id'] = 42
            with self.assertRaises(ValueError):
                operations_restore.restore_latest(fixture.root, fetch_json=operations_restore.transport.fetch_github_json,
                                                  fetch_bytes=lambda u:fixture.raw)

    def test_policy_rejects_empty_target_or_ambiguous_pins(self):
        with self.assertRaises(ValueError): policy_for([])
        run = run_for(identity.SOURCE); pin = pin_for(run, artifact_for(run))
        with self.assertRaises(ValueError): policy_for([pin, pin])
        wrong = dict(pin, repository_id=1)
        with self.assertRaises(ValueError): policy_for([wrong])

    def fixture(self, cls):
        value = cls('runTest'); value.setUp(); self.addCleanup(value.doCleanups)
        return value

    def target_fixture(self, *, daily=False, activate=True):
        fixture = self.fixture(observer_tests.ObserverTests if daily else pipeline_tests.InputsTests)
        if daily:
            fixture.daily()
        def git(*args):
            return subprocess.check_output(['git', '-C', str(fixture.root), *args], stderr=subprocess.DEVNULL).decode().strip()
        git('init', '-q'); git('config', 'user.email', 'offline-fixture@example.invalid'); git('config', 'user.name', 'Offline fixture')
        trusted = Path(identity.__file__).resolve().parents[1]
        for name in identity.TRUSTED_PRODUCER_CODE:
            path = fixture.root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((trusted/name).read_bytes())
        config = {'schema_version':1, 'repository_id':identity.REPOSITORY_ID,
                  'current_repository':identity.SOURCE, 'current_owner_id':identity.OWNER_IDS[identity.SOURCE],
                  'cutover_head_sha':None, 'historical_artifacts':[]}
        fixture.write('config/repository_identity.json', config)
        git('add', '.'); git('commit', '-qm', 'Source freeze with reviewed producer code')
        cutover = git('rev-parse', 'HEAD')
        dummy = run_for(identity.SOURCE, rid=999)
        config.update(current_repository=identity.TARGET, current_owner_id=identity.OWNER_IDS[identity.TARGET],
                      cutover_head_sha=cutover, historical_artifacts=[pin_for(dummy, artifact_for(dummy, aid=999))])
        policy = identity.IdentityPolicy(config)
        if activate:
            fixture.write('config/repository_identity.json', config)
            git('add', '.'); git('commit', '-qm', 'Activate reviewed target policy while quiescent')
        head = git('rev-parse', 'HEAD')
        fixture.run.update(run_for(identity.TARGET, commit=head))
        fixture.jobs['jobs'][0]['head_sha'] = head
        context = dict(pipeline_tests.CONTEXT, GITHUB_REPOSITORY=identity.TARGET,
                       GITHUB_REPOSITORY_ID=str(identity.REPOSITORY_ID),
                       GITHUB_REPOSITORY_OWNER_ID=str(identity.OWNER_IDS[identity.TARGET]),
                       GITHUB_WORKFLOW_REF=identity.TARGET+'/.github/workflows/'+pipeline.WORKFLOW+'@refs/heads/main',
                       GITHUB_SHA=head, GITHUB_WORKFLOW_SHA=head)
        with patch.object(identity, 'POLICY', policy), patch.object(pipeline, 'REPOSITORY', identity.TARGET):
            fixture.record(context=context, baseline=getattr(fixture, 'baseline', None))
        report = workflow.build_report({pipeline.WORKFLOW: {'workflow_runs':[fixture.run]}}, pipeline_tests.NOW)
        report.update(repository=identity.TARGET, observation_source='github_rest')
        fixture.report = report; fixture.write(pipeline.REPORT, report)
        metadata, archive = fixture.artifact()
        metadata['workflow_run'].update(repository_id=identity.REPOSITORY_ID, head_repository_id=identity.REPOSITORY_ID)
        return fixture, policy, metadata, archive

    def test_current_target_pipeline_validates_without_transfer(self):
        fixture, policy, metadata, archive = self.target_fixture(daily=True)
        with patch.object(identity, 'POLICY', policy), patch.object(pipeline, 'exact_head', return_value=fixture.baseline):
            result = pipeline.publish_validated_health(fixture.root, fixture.report, fixture.run, fixture.jobs,
                                                       metadata, archive, now=pipeline_tests.NOW)
        self.assertEqual(result['status'], 'success', result['input_errors'])
        self.assertTrue(result['scopes']['overall_workflow']['verified'])

    def test_self_reported_target_proof_on_source_commit_is_rejected(self):
        fixture, policy, metadata, archive = self.target_fixture(activate=False)
        with patch.object(identity, 'POLICY', policy), self.assertRaises(ValueError):
            pipeline.validate_github_artifact(fixture.root, fixture.report, fixture.run, fixture.jobs,
                                              metadata, archive, now=pipeline_tests.NOW)

    def test_target_proof_rejects_missing_history_or_changed_reviewed_code(self):
        fixture, policy, metadata, archive = self.target_fixture()
        entry = [e for e in pipeline.histories(fixture.root, pipeline.HISTORY) if e['kind']=='collector_receipt'][-1]
        with tempfile.TemporaryDirectory() as empty, self.assertRaises(ValueError):
            policy.current_producer(empty, entry, fixture.run)
        with patch.object(identity, 'TRUSTED_PRODUCER_CODE', ('scripts/nonexistent-producer.py',)), self.assertRaises(ValueError):
            policy.current_producer(fixture.root, entry, fixture.run)
        for name, value in [('cutover_head_sha','d'*40),('owner_id',identity.OWNER_IDS[identity.SOURCE]),
                            ('workflow_sha','d'*40),('run_attempt',True)]:
            altered = copy.deepcopy(entry); altered['producer_identity'][name]=value
            with self.subTest(name=name), self.assertRaises(ValueError): policy.current_producer(fixture.root, altered, fixture.run)

    def test_pinned_or_unpinned_legacy_source_archive_never_becomes_current(self):
        fixture = self.fixture(observer_tests.ObserverTests); fixture.daily()
        fixture.run.update(run_for(identity.SOURCE))
        original_report = workflow.build_report({pipeline.WORKFLOW:{'workflow_runs':[fixture.run]}}, pipeline_tests.NOW)
        original_report.update(repository=identity.SOURCE, observation_source='github_rest')
        metadata, archive = fixture.artifact()
        metadata['workflow_run'].update(repository_id=identity.REPOSITORY_ID, head_repository_id=identity.REPOSITORY_ID)
        for pinned in (False, True):
            policy = policy_for([pin_for(fixture.run, metadata)] if pinned else None)
            for rewritten in (False, True):
                run = copy.deepcopy(fixture.run); report = copy.deepcopy(original_report)
                if rewritten:
                    run.update(run_for(identity.TARGET))
                    report = workflow.build_report({pipeline.WORKFLOW:{'workflow_runs':[run]}}, pipeline_tests.NOW)
                    report.update(repository=identity.TARGET, observation_source='github_rest')
                with patch.object(identity, 'POLICY', policy), patch.object(pipeline, 'exact_head', return_value=fixture.baseline):
                    with self.subTest(pinned=pinned, rewritten=rewritten), self.assertRaises(ValueError):
                        pipeline.validate_github_artifact(fixture.root, report, run, fixture.jobs, metadata, archive, now=pipeline_tests.NOW)

    def test_old_saved_source_success_is_never_current_target_success(self):
        fixture = self.fixture(observer_tests.ObserverTests); fixture.daily()
        fixture.run.update(run_for(identity.SOURCE))
        report = workflow.build_report({pipeline.WORKFLOW:{'workflow_runs':[fixture.run]}}, pipeline_tests.NOW)
        report.update(repository=identity.SOURCE, observation_source='github_rest')
        fixture.write(pipeline.REPORT, report)
        metadata, archive = fixture.artifact()
        metadata['workflow_run'].update(repository_id=identity.REPOSITORY_ID, head_repository_id=identity.REPOSITORY_ID)
        with patch.object(pipeline, 'exact_head', return_value=fixture.baseline):
            pipeline.publish_validated_health(fixture.root, report, fixture.run, fixture.jobs, metadata, archive, now=pipeline_tests.NOW)
        with patch.object(identity, 'POLICY', policy_for([pin_for(fixture.run, metadata)])), patch.object(pipeline, 'exact_head', return_value=fixture.baseline):
            result = pipeline.load_pipeline_inputs(fixture.root, now=pipeline_tests.NOW)
        self.assertNotEqual(result['status'], 'success')
        self.assertFalse(result['scopes']['overall_workflow']['verified'])
        self.assertFalse(result['scopes']['collection_publication']['verified'])

    def test_historical_pipeline_replay_preserves_every_original_byte(self):
        fixture = self.fixture(observer_tests.ObserverTests)
        fixture.daily()
        fixture.run.update(run_for(identity.SOURCE))
        fixture.report = workflow.build_report({pipeline.WORKFLOW: {'workflow_runs':[fixture.run]}}, pipeline_tests.NOW)
        fixture.report.update(repository=identity.SOURCE, observation_source='github_rest')
        fixture.record()
        metadata, archive = fixture.artifact()
        metadata['workflow_run'].update(repository_id=identity.REPOSITORY_ID, head_repository_id=identity.REPOSITORY_ID)
        with patch.object(pipeline, 'exact_head', return_value=fixture.baseline):
            pipeline.publish_validated_health(fixture.root, fixture.report, fixture.run, fixture.jobs,
                                               metadata, archive, now=pipeline_tests.NOW)
        saved = [e for e in pipeline.histories(fixture.root, pipeline.HISTORY) if e['kind']=='github_validation'][0]
        before = {str(p.relative_to(fixture.root)):p.read_bytes() for p in fixture.root.rglob('*') if p.is_file()}
        with patch.object(identity, 'POLICY', policy_for([pin_for(fixture.run, metadata)])):
            result = pipeline.historical_publication_receipts(saved, fixture.report, pipeline.clock(pipeline_tests.NOW))
            self.assertTrue(result)
            tampered = copy.deepcopy(saved); tampered['validation']['artifact']['id'] += 1
            with self.assertRaises(ValueError):
                pipeline.historical_publication_receipts(tampered, fixture.report, pipeline.clock(pipeline_tests.NOW))
        self.assertEqual(before, {str(p.relative_to(fixture.root)):p.read_bytes() for p in fixture.root.rglob('*') if p.is_file()})
        with patch.object(identity, 'POLICY', policy_for()):
            with self.assertRaises(ValueError):
                pipeline.historical_publication_receipts(saved, fixture.report, pipeline.clock(pipeline_tests.NOW))

    def test_target_source_restore_preserves_old_manifest_and_exact_bytes(self):
        fixture = self.fixture(source_tests.SafetyCheckpointTests)
        fixture.lineage['repository'] = identity.SOURCE
        fixture.pack(); fixture.copy_current()
        original = fixture.archive.read_bytes()
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as z: z.writestr('source-safety.zip', original)
        outer = stream.getvalue()
        run = run_for(identity.TARGET, rid=123, attempt=2); run['status']='completed'
        metadata = artifact_for(run, 'source-safety', aid=200, digest='sha256:'+hashlib.sha256(outer).hexdigest())
        base = 'https://api.github.com/repos/'+identity.TARGET+'/actions/'
        metadata.update(expired=False, archive_download_url=base+'artifacts/200/zip')
        def fetch(url):
            return {'workflow_runs':[run]} if '/runs?' in url else {'artifacts':[metadata]}
        with patch.object(identity, 'POLICY', policy_for([pin_for(run, metadata)])), \
                patch.object(source_restore, 'REPOSITORY', identity.TARGET), patch.object(source_restore, 'BASE', base), \
                patch.object(source_restore, '_git', return_value=subprocess.CompletedProcess([], 0, b'', b'')):
            result = source_restore.restore_latest(fixture.target, fetch_json=fetch, fetch_bytes=lambda u:outer)
            self.assertEqual(result['status'], 'authenticated_source_safety_restored')
            self.assertEqual(source_safety._snapshot(fixture.root), source_safety._snapshot(fixture.target))
        self.assertEqual(fixture.archive.read_bytes(), original)

    def test_target_normal_operations_restore_needs_no_old_incident_exception(self):
        fixture = self.fixture(operations_tests.RestoreTests)
        fixture.run.update(repository=repository(identity.TARGET), head_repository=repository(identity.TARGET))
        fixture.artifact['workflow_run'].update(repository_id=identity.REPOSITORY_ID, head_repository_id=identity.REPOSITORY_ID)
        base = 'https://api.github.com/repos/'+identity.TARGET+'/actions/'
        fixture.artifact['archive_download_url'] = base+'artifacts/200/zip'
        with patch.object(identity, 'POLICY', policy_for([pin_for(fixture.run, fixture.artifact)])), \
                patch.object(operations_restore, 'REPOSITORY', identity.TARGET), patch.object(operations_restore, 'BASE', base):
            self.assertEqual(fixture.perform()['status'], 'authenticated_operations_safety_restored')


if __name__ == '__main__': unittest.main()
