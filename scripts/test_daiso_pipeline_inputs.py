"""Offline exact-byte/attempt/receipt/publication tests; no network or production IO."""
from copy import deepcopy
import base64
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
            if (self.root / p.POOL).exists():
                z.writestr(p.POOL, (self.root / p.POOL).read_bytes())
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

    def historical_daily(self, requested=110, candidates=False):
        operating = p.sha((self.root / p.OPERATING).read_bytes())
        self.capture.update(status='no_change', requested=requested, ok=0,
            discovery_enabled=True, operating_updates_enabled=False, candidates_new=0, candidates_updated=0,
            operating_before_sha256=operating, operating_after_sha256=operating)
        if candidates:
            from scripts.daiso_candidate_store import pool_document, canonical_digest
            pool = pool_document({'schema_version': 1, 'items': {'200': {
                'bucket': '스킨케어', 'url': 'https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo=200',
                'observation': {'execution_id': self.capture['execution_id']},
                'collected_at': self.capture['finished_at'], 'may_publish': False, 'may_replace_operating_products': False}}})
            self.write(p.POOL, pool)
            self.capture.update(status='candidates_collected', candidates_new=1, candidate_ids=['200'],
                candidate_pool_digest=canonical_digest(pool), candidate_pool_sha256=p.sha(p.encode(pool)))
        self.collection = {k: deepcopy(self.capture) for k in ('last_run', 'last_attempt')}
        if candidates:
            self.collection['last_candidate_success'] = deepcopy(self.capture)
        self.collection['fx'] = {'USD_KRW': 1000}
        self.write(p.STATUS, self.collection)
        self.baseline = p.encode({'fx': self.collection['fx']})
        self.assertEqual(self.record(baseline=self.baseline)['mode'], 'candidates' if candidates else 'no_change')
        self.jobs['jobs'][0]['steps'][2]['name'] = p.PUBLICATIONS[1]
        self.jobs['jobs'][0]['steps'].insert(2, self.step(p.PRESERVE, '02:12:00', '02:14:00'))
        self.report.update(observation_source='github_rest', observed_at=NOW)
        self.write(p.REPORT, self.report)
        report_raw = json.dumps(self.report, indent=2).encode()
        path = self.root / 'data/agents/workflow_status_history' / (p.sha(report_raw) + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(report_raw)
        with patch.object(p, 'exact_head', return_value=self.baseline):
            self.publish()
        derived = p.doc((self.root / p.DERIVED).read_bytes())
        return p.doc((self.root / derived['history_path']).read_bytes())

    def historical_failure(self):
        old = dict(self.run, id=10, conclusion='failure',
            html_url='https://github.com/' + p.REPOSITORY + '/actions/runs/10',
            created_at='2026-10-03T00:00:00Z', run_started_at='2026-10-03T00:00:00Z', updated_at='2026-10-03T00:31:00Z')
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
            'digest': 'sha256:' + p.sha(raw), 'size_in_bytes': len(raw), 'created_at': '2026-10-03T00:21:30Z'}
        p.retain_failed_scope(self.root, old, jobs, meta, raw, now=NOW)

    def test_historical_publication_replays_original_evidence_without_current_source_authority(self):
        saved = self.historical_daily(candidates=True)
        self.historical_failure()
        for name in (p.STATUS, p.POOL, p.OPERATING, p.REPORT):
            self.write(name, {'changed_after_success': True, 'fx': {'USD_KRW': 2000}})
        before = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        with patch.object(p, 'atomic_write', side_effect=AssertionError('read-only replay')), patch('socket.socket', side_effect=AssertionError('offline replay')):
            receipts = p.historical_publication_receipts(saved, self.report, p.clock('2026-11-03T03:00:00Z'))
            health = p.load_pipeline_inputs(self.root, now='2026-11-03T03:00:00Z')
        self.assertEqual([r['scope'] for r in receipts], ['overall_workflow'])
        self.assertTrue(health['failed_workflow_history'][0]['superseded'])
        self.assertEqual(health['status'], 'unverified')
        self.assertTrue(all(scope['status'] != 'success' for scope in health['scopes'].values()))
        self.assertEqual(before, {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob('*') if path.is_file()})

    def test_historical_publication_preserves_six_hour_current_freshness(self):
        self.historical_daily()
        self.historical_failure()
        with patch.object(p, 'exact_head', return_value=self.baseline):
            fresh = p.load_pipeline_inputs(self.root, now=NOW)
            stale = p.load_pipeline_inputs(self.root, now='2026-10-03T08:31:01Z')
        self.assertEqual(fresh['status'], 'success')
        self.assertEqual(stale['status'], 'unverified')
        self.assertTrue(stale['failed_workflow_history'][0]['superseded'])
        self.assertEqual(stale['scopes']['collection_publication']['status'], 'unverified')

    def test_historical_publication_ignores_saved_receipt_authority(self):
        saved = self.historical_daily()
        expected = p.historical_publication_receipts(saved, self.report, p.clock(NOW))
        saved['validation'].update(receipts=[{'verified': True, 'scope': 'overall_workflow'}], validated_receipt_sha256=['0' * 64])
        self.assertEqual(p.historical_publication_receipts(saved, self.report, p.clock(NOW)), expected)
        saved['validation']['jobs']['jobs'][0]['steps'][3]['conclusion'] = 'skipped'
        self.assertEqual(p.historical_publication_receipts(saved, self.report, p.clock(NOW)), [])

    def test_historical_publication_rejects_metadata_and_archive_tampering(self):
        saved = self.historical_daily(candidates=True)
        mutations = [
            lambda e: e.update(observed_at='2027-01-01T00:00:00Z'),
            lambda e: e.update(observed_at='2026-10-02T03:00:00Z'),
            lambda e: e.update(workflow_report_sha256='0' * 64),
            lambda e: e['validation'].update(archive_sha256='0' * 64),
            lambda e: e['validation'].update(archive_base64=base64.b64encode(b'wrong').decode()),
            lambda e: e['validation']['sources'].update({p.OPERATING: '0' * 64}),
            lambda e: e['validation']['run'].update(run_attempt=2),
            lambda e: e['validation']['run'].update(conclusion='cancelled'),
            lambda e: e['validation']['jobs']['jobs'][0].update(head_sha='b' * 40),
            lambda e: e['validation']['jobs']['jobs'][0]['steps'][1].update(conclusion='failure'),
            lambda e: e['validation']['artifact'].update(created_at='2026-10-03T02:30:00Z'),
            lambda e: e['validation']['entry']['canonical_fx'].update(value={'USD_KRW': 2000}),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                changed = deepcopy(saved)
                mutate(changed)
                try:
                    receipts = p.historical_publication_receipts(changed, self.report, p.clock(NOW))
                except (ValueError, TypeError, KeyError):
                    receipts = []
                self.assertEqual(receipts, [])
        for change in ({'observation_source': 'payload'}, {'observed_at': '2026-10-02T03:00:00Z'},
                       {'observed_at': '2026-10-03T03:00:01Z'}):
            report = dict(self.report, **change)
            changed = dict(saved, workflow_report_sha256=p.sha(p.encode(report)))
            with self.assertRaises(ValueError):
                p.historical_publication_receipts(changed, report, p.clock(NOW))

    def test_historical_publication_requires_original_immutable_report(self):
        self.historical_daily()
        self.historical_failure()
        for path in (self.root / 'data/agents/workflow_status_history').iterdir():
            path.unlink()
        with patch.object(p, 'exact_head', return_value=self.baseline):
            health = p.load_pipeline_inputs(self.root, now='2026-10-04T03:00:00Z')
        self.assertEqual(health['status'], 'failed')
        self.assertIn('historical publication unverified: historical workflow report missing', health['input_errors'])

    def rebind_historical_fixture(self, saved, change):
        """Rehash fixture envelopes so semantic checks, not a stale outer hash, fail."""
        saved = deepcopy(saved)
        v = saved['validation']
        actual = p.archive_members(v['artifact'], base64.b64decode(v['archive_base64']), v['run'])
        old = p.sha(p.encode(v['entry']))
        change(actual, v['entry'])
        new = p.sha(p.encode(v['entry']))
        actual.pop(p.HISTORY + '/' + old + '.json')
        actual[p.HISTORY + '/' + new + '.json'] = p.encode(v['entry'])
        index = p.doc(actual[p.INDEX])
        index['history_sha256'] = [new if digest == old else digest for digest in index['history_sha256']]
        actual[p.INDEX] = p.encode(index)
        v['sources'] = deepcopy(v['entry']['sources'])
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as archive:
            for name, raw in actual.items():
                archive.writestr(name, raw)
        raw = buf.getvalue()
        v.update(archive_base64=base64.b64encode(raw).decode(), archive_sha256=p.sha(raw))
        v['artifact'].update(digest='sha256:' + p.sha(raw), size_in_bytes=len(raw))
        return saved

    def test_historical_rehashed_envelopes_do_not_bypass_source_and_safety_checks(self):
        saved = self.historical_daily(candidates=True)
        def capture_change(actual, entry, patch):
            collection = p.doc(actual[p.STATUS])
            for key in ('last_run', 'last_attempt', 'last_candidate_success'):
                collection[key].update(patch)
            actual[p.STATUS] = p.encode(collection)
            entry['sources'][p.STATUS] = p.sha(actual[p.STATUS])
            entry['receipt']['source_sha256'] = p.sha(actual[p.STATUS])
        def unsafe_pool(actual, entry):
            pool = p.doc(actual[p.POOL])
            pool['may_publish'] = True
            actual[p.POOL] = p.encode(pool)
            entry['sources'][p.POOL] = p.sha(actual[p.POOL])
            capture_change(actual, entry, {'candidate_pool_sha256': p.sha(actual[p.POOL])})
        mutations = [
            lambda a, e: a.pop(p.POOL),
            lambda a, e: a.update({p.POOL: a[p.POOL] + b' '}),
            lambda a, e: e['sources'].update({p.OPERATING: 'bad-digest'}),
            lambda a, e: e['sources'].update({p.OPERATING: '0' * 64}),
            lambda a, e: e['canonical_fx'].update(value={'USD_KRW': 2000}),
            lambda a, e: e.update(baseline_status_sha256=None),
            lambda a, e: e['receipt'].update(workflow='other.yml'),
            lambda a, e: e['receipt'].update(source='payload'),
            lambda a, e: e['receipt'].update(completed=False),
            lambda a, e: e['receipt'].update(execution_id='12:1:collect'),
            lambda a, e: e['receipt'].update(scope='shortlist_price'),
            lambda a, e: capture_change(a, e, {'operating_after_sha256': '0' * 64}),
            lambda a, e: capture_change(a, e, {'parse_failed': 1}),
            lambda a, e: capture_change(a, e, {'candidate_ids': ['300']}),
            unsafe_pool,
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                changed = self.rebind_historical_fixture(saved, mutate)
                with self.assertRaises((ValueError, KeyError, TypeError)):
                    p.historical_publication_receipts(changed, self.report, p.clock(NOW))

    def test_historical_archive_index_and_original_collection_age_are_checked(self):
        saved = self.historical_daily()
        def remove_indexed_receipt(actual, entry):
            index = p.doc(actual[p.INDEX])
            index['history_sha256'] = []
            actual[p.INDEX] = p.encode(index)
        changed = self.rebind_historical_fixture(saved, remove_indexed_receipt)
        with self.assertRaisesRegex(ValueError, 'receipt chain missing'):
            p.historical_publication_receipts(changed, self.report, p.clock(NOW))
        late = '2026-10-03T09:00:00Z'
        report = dict(self.report, observed_at=late)
        changed = dict(saved, observed_at=late, workflow_report_sha256=p.sha(p.encode(report)))
        with self.assertRaisesRegex(ValueError, 'collection validation failed'):
            p.historical_publication_receipts(changed, report, p.clock(late))

    def test_historical_narrow_publication_never_gains_daily_scope(self):
        saved = self.historical_daily(requested=20)
        self.assertEqual(p.historical_publication_receipts(saved, self.report, p.clock(NOW)), [])


if __name__ == '__main__':
    unittest.main()
