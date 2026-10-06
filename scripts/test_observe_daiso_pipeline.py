"""Only injected REST/artifact fixtures; never contacts a provider or GitHub."""
from copy import deepcopy
from unittest.mock import patch
import unittest
import io
import zipfile
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.test_daiso_pipeline_inputs import InputsTests, NOW
from scripts import daiso_pipeline_inputs as p
from scripts import observe_daiso_pipeline as o


class ObserverTests(InputsTests):
    def daily(self, requested=110):
        operating = (self.root / p.OPERATING).read_bytes()
        self.capture.update(status='no_change', requested=requested, ok=0,
            discovery_enabled=True, operating_updates_enabled=False, candidates_new=0, candidates_updated=0,
            operating_before_sha256=p.sha(operating), operating_after_sha256=p.sha(operating))
        self.collection = {k: deepcopy(self.capture) for k in ('last_run', 'last_attempt')}
        self.write(p.STATUS, self.collection)
        self.baseline = p.encode({})
        self.assertEqual(self.record(baseline=self.baseline)['mode'], 'no_change')
        steps = self.jobs['jobs'][0]['steps']
        steps[2]['name'] = p.PUBLICATIONS[1]
        steps.insert(2, self.step(p.PRESERVE, '02:12:00', '02:14:00'))
        self.report['observation_source'] = 'github_rest'
        self.report['observed_at'] = NOW
        self.write(p.REPORT, self.report)

    def boundary(self, mutate=None):
        meta, raw = self.artifact()
        values = {'run': deepcopy(self.run), 'jobs': deepcopy(self.jobs), 'meta': meta,
                  'archive': raw, 'current': deepcopy(self.run), 'report': deepcopy(self.report)}
        if mutate:
            mutate(values)
        calls = []
        def get(url):
            calls.append(url)
            self.assertTrue(url.startswith('https://api.github.com/repos/' + p.REPOSITORY + '/actions/'))
            if '/workflows/' in url:
                return {'workflow_runs': [values['current']]}
            if '/jobs?' in url:
                return values['jobs']
            if '/artifacts?' in url:
                return {'total_count': 1, 'artifacts': [values['meta']]}
            return values['run']
        def download(url):
            calls.append(url)
            return values['archive']
        with patch.object(p, 'exact_head', return_value=self.baseline):
            result = o.observe(self.root, report=values['report'], now=NOW,
                fetch_json=get, fetch_artifact_bytes=download)
        self.assertLessEqual(len(calls), 5)
        return result

    def test_full_daily_publication_success_keeps_operating_stale(self):
        self.daily()
        before = {n: (self.root / n).read_bytes() for n in (p.STATUS, p.OPERATING)}
        health = self.boundary()
        self.assertEqual(health['status'], 'success', health['input_errors'])
        self.assertNotEqual(health['scopes']['operating_capture']['status'], 'success')
        self.assertFalse(health['public_authority'])
        self.assertEqual(before, {n: (self.root / n).read_bytes() for n in before})

    def test_fractional_capture_end_within_reported_second_publishes(self):
        self.daily()
        self.capture['finished_at'] = '2026-10-03T02:11:00.999999Z'
        self.collection = {k: deepcopy(self.capture) for k in ('last_run', 'last_attempt')}
        self.write(p.STATUS, self.collection)
        self.assertEqual(self.record(baseline=self.baseline)['mode'], 'no_change')
        before = (self.root / p.STATUS).read_bytes()
        value = self.boundary()
        self.assertEqual(value['status'], 'success', value['input_errors'])
        self.assertEqual((self.root / p.STATUS).read_bytes(), before)
        self.assertEqual(value['metadata_precision']['capture_clocks'], 'exact_unmodified')

    def test_tiny_daily_never_full_success(self):
        self.daily(1)
        self.failure_history()
        health = self.boundary()
        self.assertEqual(health['status'], 'failed')
        self.assertEqual(health['scopes']['collection_publication']['status'], 'success')

    def test_wrong_boundary_inputs(self):
        self.daily()
        mutations = [
            lambda v: v['run'].update(repository={'full_name': 'attacker/repo'}),
            lambda v: v['run'].update(id=12),
            lambda v: v['run'].update(run_attempt=2),
            lambda v: v['current'].update(id=12),
            lambda v: v['meta'].update(expired=True),
            lambda v: v['meta'].update(digest='sha256:' + '0' * 64),
            lambda v: v['meta'].update(name='daiso-attempt-11-2'),
            lambda v: v['meta']['workflow_run'].update(head_sha='b' * 40),
            lambda v: v['jobs']['jobs'][0].update(head_sha='b' * 40),
            lambda v: v['jobs']['jobs'][0]['steps'][0].update(conclusion='failure'),
            lambda v: v['jobs']['jobs'][0]['steps'][3].update(conclusion='skipped'),
            lambda v: v['jobs']['jobs'][0]['steps'][3].update(conclusion='failure'),
            lambda v: v['jobs']['jobs'][0]['steps'][4].update(conclusion='skipped'),
            lambda v: v['report'].update(observed_at='2026-10-02T00:00:00Z'),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assertNotEqual(self.boundary(mutation)['status'], 'success')

    def test_prior_failure_scope_replayed_from_authenticated_archive(self):
        self.daily()
        failed = dict(self.run, conclusion='failure')
        jobs = deepcopy(self.jobs)
        jobs['jobs'][0]['conclusion'] = 'failure'
        jobs['jobs'][0]['steps'][3]['conclusion'] = 'failure'
        meta, archive = self.artifact()
        saved = p.retain_failed_scope(self.root, failed, jobs, meta, archive, now=NOW)
        self.assertEqual(saved['collection_scope'], p.DAILY_SCOPE)
        with patch.object(p, 'exact_head', return_value=self.baseline):
            health = p.load_pipeline_inputs(self.root, now=NOW)
        self.assertEqual(health['status'], 'failed')
        self.assertEqual(health['failed_workflow_history'][0]['collection_scope'], p.DAILY_SCOPE)
        with self.assertRaises(ValueError):
            p.retain_failed_scope(self.root, dict(failed, run_attempt=2), jobs, meta, archive, now=NOW)
        with self.assertRaises(ValueError):
            p.retain_failed_scope(self.root, failed, jobs, dict(meta, digest='sha256:' + '0' * 64), archive, now=NOW)

    def test_bound_full_daily_replaces_only_known_matching_prior_scope(self):
        self.daily()
        old = dict(self.run, id=10, conclusion='failure',
                   html_url='https://github.com/' + p.REPOSITORY + '/actions/runs/10',
                   created_at='2026-10-03T00:00:00Z', run_started_at='2026-10-03T00:00:00Z',
                   updated_at='2026-10-03T00:31:00Z')
        jobs = json.loads(json.dumps(self.jobs).replace('T02:', 'T00:').replace('T01:59:', 'T00:00:'))
        jobs['jobs'][0].update(run_id=10, conclusion='failure')
        jobs['jobs'][0]['steps'][3]['conclusion'] = 'failure'
        status = json.loads(json.dumps(self.collection).replace('11:1:collect', '10:1:collect').replace('T02:', 'T00:'))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as archive:
            archive.writestr(p.STATUS, p.encode(status))
        raw = buf.getvalue()
        meta = {'id': 10, 'name': 'daiso-attempt-10-1', 'expired': False,
                'workflow_run': {'id': 10, 'head_sha': old['head_sha'], 'head_branch': 'main'},
                'digest': 'sha256:' + p.sha(raw), 'size_in_bytes': len(raw),
                'created_at': '2026-10-03T00:21:30Z'}
        p.retain_failed_scope(self.root, old, jobs, meta, raw, now=NOW)
        self.failure_history()
        health = self.boundary()
        self.assertEqual(health['status'], 'success', health['input_errors'])
        self.assertTrue(all(row['superseded'] for row in health['failed_workflow_history']))

    def test_revalidation_rejects_changed_source_and_stale_capture(self):
        self.daily()
        self.assertEqual(self.boundary()['status'], 'success')
        with patch.object(p, 'exact_head', return_value=self.baseline):
            expired = p.load_pipeline_inputs(self.root, now='2026-10-04T03:00:00Z')
            self.assertNotEqual(expired['status'], 'success')
            target = self.root / p.STATUS
            target.write_bytes(target.read_bytes() + b' ')
            changed = p.load_pipeline_inputs(self.root, now=NOW)
            self.assertNotEqual(changed['status'], 'success')
            self.assertTrue(changed['input_errors'])

    def test_missing_auth_never_calls_transport(self):
        self.daily()
        with patch.dict('os.environ', {}, clear=True), patch.object(o.transport, 'fetch_github_json') as fetch:
            health = o.observe(self.root, report=self.report, now=NOW)
        fetch.assert_not_called()
        self.assertIn('authenticated_github_token_missing', health['input_errors'])


if __name__ == '__main__':
    unittest.main()
