"""Offline exact-byte/attempt/receipt/publication tests; no network or production IO."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import sys
from pathlib import Path as _ScriptPath
sys.path.insert(0,str(_ScriptPath(__file__).resolve().parents[1]))
from scripts import daiso_pipeline_inputs as p
from scripts import collect_workflow_status as w

NOW = '2026-10-03T03:00:00Z'
CONTEXT = {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '11', 'GITHUB_RUN_ATTEMPT': '1',
           'GITHUB_JOB': 'collect', 'GITHUB_WORKFLOW_REF': 'coar0000-wq/jarvis-luna/.github/workflows/daiso-real-collection.yml@refs/heads/main'}


class InputsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.capture = {'execution_id': '11:1:collect', 'status': 'ok', 'collector_version': 2,
                        'collector_completed': True, 'discovery_enabled': False, 'operating_updates_enabled': True, 'requested': 1, 'ok': 1, 'parse_failed': 0,
                        'http_error': 0, 'started_at': '2026-10-03T02:00:00Z', 'finished_at': '2026-10-03T02:10:00Z'}
        self.collection = {k: deepcopy(self.capture) for k in ('last_run', 'last_attempt', 'last_success')}
        self.write(p.STATUS, self.collection)
        self.write(p.OPERATING, {'products': [{'pd_no': '100'}]})
        self.run = {'id': 11, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'success',
                    'event': 'workflow_dispatch', 'created_at': '2026-10-03T01:58:00Z',
                    'run_started_at': '2026-10-03T01:59:00Z', 'updated_at': '2026-10-03T02:31:00Z',
                    'path': '.github/workflows/' + p.WORKFLOW, 'head_branch': 'main',
                    'repository': {'full_name': p.REPOSITORY}, 'head_sha': 'a' * 40, 'html_url': 'https://github.com/coar0000-wq/jarvis-luna/actions/runs/11'}
        self.jobs = {'total_count': 1, 'jobs': [{'name': 'collect', 'run_id': 11, 'run_attempt': 1,
                     'head_sha': 'a' * 40, 'status': 'completed', 'conclusion': 'success', 'started_at': '2026-10-03T01:59:00Z',
                     'completed_at': '2026-10-03T02:30:00Z', 'steps': [
                         self.step(p.COLLECTOR, '02:00:00', '02:11:00'),
                         self.step(p.VALIDATOR, '02:11:00', '02:12:00'),
                         self.step(p.PUBLICATIONS[0], '02:15:00', '02:20:00'),
                         self.step(p.UPLOAD, '02:21:00', '02:22:00')]}]}
        self.report = w.build_report({p.WORKFLOW: {'workflow_runs': [self.run]}}, NOW)
        self.report['repository'] = 'coar0000-wq/jarvis-luna'
        self.write(p.REPORT, self.report)

    def step(self, name, start, finish, outcome='success'):
        return {'name': name, 'status': 'completed', 'conclusion': outcome,
                'started_at': '2026-10-03T' + start + 'Z', 'completed_at': '2026-10-03T' + finish + 'Z'}

    def write(self, name, value):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(p.encode(value))

    def record(self, outcome='success', context=None, now=NOW, baseline=None):
        return p.record_collector(self.root, collector_outcome=outcome, started_after='2026-10-03T02:00:00Z',
                                  context=context or CONTEXT, now=now, baseline_status_bytes=baseline)

    def artifact(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            for name in (p.STATUS, p.INDEX):
                z.writestr(name, (self.root / name).read_bytes())
            for name in (self.root / p.HISTORY).iterdir():
                z.writestr(p.HISTORY + '/' + name.name, name.read_bytes())
        raw = buf.getvalue()
        meta = {'id': 12, 'name': 'daiso-attempt-11-1', 'expired': False,
                'workflow_run': {'id': 11, 'head_branch': 'main', 'head_sha': self.run['head_sha']},
                'digest': 'sha256:' + p.sha(raw), 'size_in_bytes': len(raw),
                'created_at': '2026-10-03T02:21:30Z'}
        return meta, raw

    def publish(self):
        meta, raw = self.artifact()
        return p.publish_validated_health(self.root, self.report, self.run, self.jobs, meta, raw, now=NOW)

    def test_success_and_readers_share_current_proof(self):
        self.assertEqual(self.record()['mode'], 'collected')
        value = self.publish()
        self.assertEqual(value['scopes']['operating_capture']['status'], 'success')
        self.assertEqual(value['scopes']['overall_workflow']['status'], 'unverified')
        self.assertEqual(value['scopes']['collection_publication']['status'], 'success')
        self.assertFalse(value['public_authority'])
        from scripts import generate_dashboard_runtime as dashboard
        from scripts import health_check_v2 as health
        self.assertEqual(dashboard.daiso_pipeline_snapshot(self.root, NOW), value)
        self.assertEqual(health.daiso_pipeline_snapshot(self.root, NOW), value)
        self.assertEqual(w.daiso_pipeline_snapshot(self.root, NOW), value)

    def test_exact_bytes_not_reserialized_equivalence(self):
        self.record()
        self.publish()
        path = self.root / p.STATUS
        path.write_bytes(path.read_bytes() + b' ')
        value = p.load_pipeline_inputs(self.root, now=NOW)
        self.assertEqual(value['scopes']['operating_capture']['status'], 'unverified')
        self.assertEqual(value['scopes']['overall_workflow']['status'], 'unverified')

    def test_stale_and_wrong_attempt_fail_closed(self):
        self.record()
        self.publish()
        self.assertEqual(p.load_pipeline_inputs(self.root, now='2026-10-04T03:00:00Z')['scopes']['operating_capture']['status'], 'unverified')
        meta, raw = self.artifact()
        wrong = dict(self.run, run_attempt=2)
        with self.assertRaises(ValueError):
            p.validate_github_artifact(self.root, self.report, wrong, self.jobs, meta, raw, now=NOW)
        result = self.record(context=dict(CONTEXT, GITHUB_RUN_ATTEMPT='2'))
        self.assertEqual(result['mode'], 'failed')

    def test_fake_receipt_verified_flag_cannot_authorize(self):
        result = self.record()
        entry = json.loads((self.root / result['receipt_path']).read_bytes())
        entry['receipt']['verified'] = True
        entry['receipt']['publication_completed'] = True
        self.write(p.INDEX, {'schema_version': 1, 'receipts': [entry['receipt']], 'validated_receipt_sha256': [p.receipt_sha256(entry['receipt'])], 'public_authority': False})
        value = p.load_pipeline_inputs(self.root, now=NOW)
        self.assertEqual(value['scopes']['operating_capture']['status'], 'unverified')
        self.assertEqual(value['scopes']['overall_workflow']['status'], 'unverified')

    def test_failed_step_retained_without_clock_relabeling(self):
        result = self.record('failure')
        entry = json.loads((self.root / result['receipt_path']).read_bytes())
        self.assertEqual(entry['receipt']['finished_at'], self.capture['finished_at'])
        self.assertNotEqual(entry['recorded_at'], entry['receipt']['finished_at'])
        self.assertFalse(entry['receipt']['completed'])
        self.assertEqual(result['mode'], 'failed')
        self.record()
        self.assertEqual(len(p.histories(self.root, p.HISTORY)), 2)

    def test_no_change_fx_must_already_be_preserved(self):
        raw = (self.root / p.OPERATING).read_bytes()
        self.capture.update(status='no_change', ok=0, operating_before_sha256=p.sha(raw), operating_after_sha256=p.sha(raw))
        self.collection = {k: deepcopy(self.capture) for k in ('last_run', 'last_attempt')}
        self.collection['fx'] = {'USD_KRW': 2000}
        self.write(p.STATUS, self.collection)
        result = self.record(baseline=p.encode({'fx': {'USD_KRW': 1000}}))
        self.assertEqual(result['mode'], 'failed')
        self.collection['fx'] = {'USD_KRW': 1000}
        self.write(p.STATUS, self.collection)
        self.assertEqual(self.record(baseline=p.encode({'fx': {'USD_KRW': 1000}}))['mode'], 'no_change')

    def failure_history(self):
        failed = deepcopy(self.run)
        failed.update(id=10, conclusion='failure', run_started_at='2026-10-03T00:00:00Z', created_at='2026-10-03T00:00:00Z', updated_at='2026-10-03T01:00:00Z')
        report = w.build_report({p.WORKFLOW: {'workflow_runs': [failed]}}, NOW)
        raw = p.encode(report)
        target = self.root / 'data/agents/workflow_status_history' / (p.sha(raw) + '.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)

    def test_failure_history_only_full_publication_supersedes(self):
        self.failure_history()
        self.record()
        self.jobs['jobs'][0]['steps'][2]['conclusion'] = 'skipped'
        value = self.publish()
        self.assertEqual(value['scopes']['operating_capture']['status'], 'success')
        self.assertEqual(value['status'], 'failed')
        self.assertFalse(value['failed_workflow_history'][0]['superseded'])
        self.jobs['jobs'][0]['steps'][2]['conclusion'] = 'success'
        value = self.publish()
        self.assertEqual(value['status'], 'failed')
        self.assertFalse(any(f['superseded'] for f in value['failed_workflow_history']))
        self.assertEqual(value['failed_workflow_history'][0]['coverage_reason'], 'prior_failure_collection_coverage_unknown')

    def test_price_only_and_old_success_never_clear_workflow(self):
        self.failure_history()
        price = {'scope': 'active_shopify_shortlist_only', 'complete': True, 'operating_catalog_mutated': False,
                 'expected_ids': ['CP1'], 'products': [{'canonical_product_id': 'CP1', 'price_krw': 3000,
                 'source': {'collected_at': '2026-10-03T02:00:00Z', 'capture_kind': 'successful_http_parse'},
                 'provenance': {'http_status': 200, 'parse_status': 'exact_pd_no_numeric_price', 'response_sha256': 'a' * 64}}]}
        self.write(p.SHORTLIST, price)
        value = p.load_pipeline_inputs(self.root, now=NOW)
        self.assertEqual(value['scopes']['shortlist_price']['status'], 'success')
        self.assertEqual(value['status'], 'failed')
        self.assertEqual(value['scopes']['overall_workflow']['status'], 'failed')

    def test_publication_unconfirmed_and_archive_digest_tampered(self):
        self.record()
        self.jobs['jobs'][0]['steps'][2]['conclusion'] = 'skipped'
        self.assertEqual(self.publish()['status'], 'unverified')
        meta, raw = self.artifact()
        with self.assertRaises(ValueError):
            p.validate_github_artifact(self.root, self.report, self.run, self.jobs, dict(meta, digest='sha256:' + '0' * 64), raw, now=NOW)

    def test_precision_aware_capture_window_keeps_exact_clocks(self):
        receipt = dict(self.capture, run_id=11, run_attempt=1, job='collect', mode='collected')
        for fraction in ('000001', '419835', '999999'):
            receipt['finished_at'] = '2026-10-03T02:11:00.' + fraction + 'Z'
            before = deepcopy(receipt)
            p.execution_steps(self.run, self.jobs, receipt, p.clock(NOW))
            self.assertEqual(receipt, before)
        receipt['finished_at'] = '2026-10-03T02:11:01Z'
        with self.assertRaisesRegex(ValueError, 'capture outside collector/validator window'):
            p.execution_steps(self.run, self.jobs, receipt, p.clock(NOW))
        wrong = dict(self.run, created_at='2026-10-03T01:59:02Z')
        with self.assertRaisesRegex(ValueError, 'invalid workflow completion times'):
            p.execution_steps(wrong, self.jobs, dict(receipt, finished_at=self.capture['finished_at']), p.clock(NOW))
        inverted = dict(self.run, created_at='2026-10-03T01:59:01Z')
        p.execution_steps(inverted, self.jobs, dict(receipt, finished_at=self.capture['finished_at']), p.clock(NOW))
        self.assertEqual(p.run_metadata_precision(inverted)['created_start_inversion_seconds'], 1)

    def test_known_uniform_upload_artifact_layouts(self):
        payload = {p.STATUS: p.encode(self.collection), p.POOL: p.encode({'fixture': True}),
                   'data/daiso_real/candidate_comparison.json': p.encode({})}
        for layout in ('canonical', 'data_relative', 'flat'):
            with self.subTest(layout=layout):
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, 'w') as z:
                    for name, raw in payload.items():
                        member = name if layout == 'canonical' else name.removeprefix('data/') if layout == 'data_relative' else Path(name).name
                        z.writestr(member, raw)
                raw = buf.getvalue()
                self.record()
                meta, _ = self.artifact()
                meta.update(size_in_bytes=len(raw), digest='sha256:' + p.sha(raw))
                self.assertEqual(p.archive_members(meta, raw, self.run), payload)

    def test_unsafe_mixed_unknown_collision_and_link_layouts(self):
        self.record()
        meta, _ = self.artifact()
        bad = [
            [('collection_status.json', b'{}'), ('data/daiso_real/candidate_pool.json', b'{}')],
            [('daiso_real/collection_status.json', b'{}'), ('collection_status.json', b'{}')],
            [(p.STATUS, b'{}'), ('data/unknown.json', b'{}')],
            [(p.STATUS, b'{}'), ('../collection_status.json', b'{}')],
            [(p.STATUS, b'{}'), ('data//daiso_real/candidate_pool.json', b'{}')],
            [(p.STATUS, b'{}'), ('data/./daiso_real/candidate_pool.json', b'{}')],
            [(p.STATUS, b'{}'), (p.STATUS.upper(), b'{}')],
            [('unexpected/collection_status.json', b'{}')],
        ]
        link = zipfile.ZipInfo(p.STATUS)
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        bad.append([(link, b'../../outside.json')])
        hardlink = zipfile.ZipInfo(p.STATUS)
        hardlink.extra = b'\x0d\x00\x00\x00'
        bad.append([(hardlink, b'{}')])
        for members in bad:
            with self.subTest(members=members):
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, 'w') as z:
                    for name, value in members:
                        z.writestr(name, value)
                raw = buf.getvalue()
                metadata = dict(meta, size_in_bytes=len(raw), digest='sha256:' + p.sha(raw))
                with self.assertRaises(ValueError):
                    p.archive_members(metadata, raw, self.run)

    def test_collector_http_boundary_is_bounded_offline(self):
        self.record()
        meta, raw = self.artifact()
        calls = []
        self.report.update(observation_source='github_rest', observed_at=NOW)
        def fetch(url):
            calls.append(url)
            if '/workflows/' in url:
                return {'workflow_runs': [self.run]}
            if url.endswith('/artifacts?per_page=100'):
                return {'total_count': 1, 'artifacts': [meta]}
            return self.jobs if '/jobs?' in url else self.run
        value = w.collect_pipeline_evidence(self.root, self.report, fetch_json=fetch, fetch_artifact_bytes=lambda url: raw, now=NOW)
        self.assertEqual(len(calls), 4)
        self.assertEqual(value['scopes']['collection_publication']['status'], 'success')


if __name__ == '__main__':
    unittest.main()
