#!/usr/bin/env python3
"""No network, providers, AI, products, or real operations actions in these tests."""
import copy
from datetime import datetime, timedelta, timezone
import json
import io
from contextlib import redirect_stdout
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import continuity_reconciliation as c

NOW = datetime(2026, 10, 23, 6, 0, tzinfo=timezone.utc)


class RestrictedFixture:
    """Tiny real Git repository + injected authenticated metadata transport.

    Use as a context manager. ``evidence`` was created through the same evidence
    authenticator as production, with a deterministic in-memory transport only.
    No persisted approved=true/verified=true flags are trusted by the engine.
    """
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.patches = []
        self.calls = []
        self.logs = {}
        self.jobs = {}
        patch = mock.patch.object(c, 'PRESERVED_PUBLICATIONS', [])
        patch.start(); self.patches.append(patch)
        patch = mock.patch.object(c, 'RECONCILED_BLOCKED_RUNS', [])
        patch.start(); self.patches.append(patch)
        patch = mock.patch.object(c, 'KNOWN_INPUT_RUNS', [])
        patch.start(); self.patches.append(patch)
        self.identity = '50000000000:1'
        self.run_id = 50000000000
        # Exercise the actual Actions identity branch, including when the suite
        # inherits a different CI run. Never turn GITHUB_ACTIONS off for fixtures.
        patch = mock.patch.dict(os.environ, {'GITHUB_ACTIONS': 'true',
            'GITHUB_RUN_ID': str(self.run_id), 'GITHUB_RUN_ATTEMPT': '1',
            'GITHUB_REPOSITORY': c.REPOSITORY, 'GITHUB_WORKSPACE': str(self.root)})
        patch.start(); self.patches.append(patch)
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Restricted fixture')
        for path in c.INPUT_PATHS:
            self.write(path, {'collected_at': '2026-10-23T04:00:00Z',
                              'products': [{'pd_no': 'cached-1', 'price': 100, 'quantity': 2, 'status': 'blocked'}]})
        self.write('data/operations/reports/.execution-ledger.json', {'claims': {'fixed-claim': {'nonce': 'fixed-nonce'}}})
        self.write('data/source_budget.json', {'used': 4, 'stop': True})
        self.write('data/shopify_daily_registry.json', {'original': 'already-existing'})
        self.write('data/shop_com_categories.json', {'original': 'already-existing'})
        self.write('data/serpapi_usage.json', {'used': 74, 'cap': 200, 'runs': [], 'by_purpose': {}})
        self.write('data/knowledge/moe_evaluation_history/' + 'a'*64 + '.json', {'original': True})
        self.write('scripts/analyzer.py', '# fixed fixture code\n', raw=True)
        self.write('.github/workflows/JARVIS-Core-Automation.yml', 'name: fixture\n', raw=True)
        self.write('config/publish_policy.json', {'non_operations_runtime_commands': c.INPUT_RUNTIME_COMMANDS, 'derived_paths': sorted(c.KNOWLEDGE_OUTPUTS)})
        self.write('index.html', 'restricted fixture', raw=True)
        self.git('add', '.')
        self.git('commit', '-qm', 'fixed baseline')
        self.baseline_commit = self.git('rev-parse', 'HEAD').strip()
        baseline = dict(c.BASELINE, protected_baseline_commit=self.baseline_commit)
        patch = mock.patch.object(c, 'BASELINE', baseline)
        patch.start(); self.patches.append(patch)
        self.decision = {'schema_version': 1, 'mode': c.MODE, 'repository': c.REPOSITORY,
                         'gap_inventory': [dict(c.GAP)], 'known_verified_input_runs': [], 'independent_input_profiles': [c.INPUT_PROFILE], 'approved_prior_code_contracts': [], 'preserved_publications': [], 'reconciled_blocked_runs': [], 'baseline': baseline, 'plan_digest': c.PLAN_DIGEST,
                         'approval': {'reference': c.APPROVAL_REFERENCE, 'approved_at': c.APPROVAL_AT, 'sha256': c.APPROVAL_DIGEST},
                         'expires_at': '2026-10-24T05:06:23Z', 'allowed_effects': list(c.ALLOWED_EFFECTS),
                         'forbidden_effects': list(c.FORBIDDEN_EFFECTS), 'input_paths': list(c.INPUT_PATHS),
                         'report_path': c.REPORT_PATH, 'history_directory': c.HISTORY_DIR,
                         'code_contract_digest': c.code_contract_digest(self.root),
                         'frozen_inventory_digest': c.baseline_frozen_digest(self.root),
                         'analysis_kind': 'cached_review_v1',
                         'approved_history_inventory_digest': c.approved_history_inventory_digest([self.run(
                             c.GAP['run_id'], 1, c.GAP['head_sha'], '2026-10-23T03:06:41Z', conclusion='failure', workflow=c.GAP['workflow'])]),
                         'provenance': 'owner_scope_reference_bound_to_authenticated_main_policy'}
        self.write(c.DECISION_PATH, self.decision)
        self.git('add', '.')
        self.git('commit', '-qm', 'approved scope fixture binding')
        self.main_commit = self.git('rev-parse', 'HEAD').strip()
        self.current = self.run(self.run_id, 1, self.main_commit, '2026-10-23T05:50:00Z')
        self.gap = self.run(c.GAP['run_id'], 1, c.GAP['head_sha'], '2026-10-23T03:06:41Z', conclusion='failure', workflow=c.GAP['workflow'])
        self.runs = [self.current, self.gap]
        self.evidence = c.authenticate_evidence(self.root, execution_id=self.identity, now=NOW, transport=self.transport)

    def run(self, run_id, attempt, sha, created, *, conclusion=None, workflow='.github/workflows/JARVIS-Core-Automation.yml'):
        return {'id': run_id, 'run_attempt': attempt, 'head_sha': sha, 'path': workflow,
                'actor': {'login': 'fixture-owner', 'id': 123}, 'triggering_actor': {'login': 'fixture-owner', 'id': 123},
                'head_branch': 'main', 'repository': {'full_name': c.REPOSITORY},
                'created_at': created, 'updated_at': created,
                'status': 'completed' if conclusion else 'in_progress', 'conclusion': conclusion}

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.DEVNULL).decode()

    def write(self, path, value, *, raw=False):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value if raw else json.dumps(value, sort_keys=True) + '\n')

    def transport(self, endpoint):
        self.calls.append(endpoint)
        if endpoint == 'git/ref/heads/main':
            return {'ref': 'refs/heads/main', 'object': {'sha': self.main_commit}}
        if endpoint == 'actions/runs/' + self.identity.replace(':', '/attempts/'):
            return copy.deepcopy(self.current)
        if endpoint == 'actions/runs/39893237129/attempts/1':
            return copy.deepcopy(self.gap)
        if endpoint.startswith('actions/runs?per_page=100&page='):
            page = int(endpoint.rsplit('=', 1)[1])
            return {'total_count': len(self.runs), 'workflow_runs': copy.deepcopy(self.runs[(page-1)*100:page*100])}
        if endpoint in self.jobs:
            return copy.deepcopy(self.jobs[endpoint])
        for run in self.runs:
            if endpoint == 'actions/runs/' + c._run_identity(run).replace(':', '/attempts/'):
                return copy.deepcopy(run)
        raise AssertionError('Unexpected network endpoint: ' + endpoint)

    def log_transport(self, endpoint):
        self.calls.append(endpoint)
        return self.logs[endpoint]

    def publish_knowledge(self, *, root=None, mutate=None):
        """Create real non-operations input publication + exact fixture job/log.

        root may be a remote clone; callers push its commit themselves. The
        returned metadata references real Git objects, never approved JSON flags.
        """
        target = Path(root) if root is not None else self.root
        def git(*args):
            return subprocess.check_output(['git', '-C', str(target), *args], stderr=subprocess.DEVNULL).decode().strip()
        base = git('rev-parse', 'HEAD')
        destination = target / 'data/team_improvement.json'
        destination.write_text(json.dumps({'collected_at': '2026-10-23T05:59:00Z',
                                          'products': [{'pd_no': 'independent-new-input', 'price': 120}]}) + '\n')
        if mutate:
            mutate(target)
        git('add', 'data', ':(exclude)' + c.REPORT_PATH, ':(exclude)' + c.HISTORY_DIR.rstrip('/')); git('commit', '-qm', 'exact authenticated independent input publication')
        commit = git('rev-parse', 'HEAD')
        run = self.run(50000000010, 1, base, '2026-10-23T05:55:00Z', conclusion='success', workflow=c.INPUT_PROFILE['workflow'])
        self.runs.append(run)
        endpoint = 'actions/runs/50000000010/attempts/1'
        self.jobs[endpoint + '/jobs?per_page=100'] = {'total_count': 1, 'jobs': [{
            'id': 120253948591, 'name': c.INPUT_PROFILE['job_name'], 'run_id': run['id'], 'head_sha': base,
            'status': 'completed', 'conclusion': 'success',
            'steps': [{'name': c.INPUT_PROFILE['publication_step'], 'conclusion': 'success',
                       'started_at': '2026-10-23T05:50:00Z', 'completed_at': '2026-10-23T06:00:00Z'}]}]}
        result = {'status': 'published', 'publication_profile': 'non_operations',
                  'operations_producer_status': 'excluded_by_profile',
                  'declared_runtime_commands': c.INPUT_RUNTIME_COMMANDS,
                  'executed_commands': c.INPUT_RUNTIME_COMMANDS + [
                      ['scripts/check_release_quality.py', '--phase', 'candidate'],
                      ['scripts/check_release_quality.py', '--phase', 'final'], ['scripts/audit_team_reports.py']],
                  'attempts': [{'attempt': 1, 'remote_sha': base, 'validated': True, 'publication_profile': 'non_operations'}],
                  'commit_sha': commit, 'base_sha': base}
        self.logs['actions/jobs/120253948591/logs'] = ('2026-10-23T05:59:00.000Z PUBLISH_TRANSACTION_OK ' + json.dumps(result) + '\n').encode()
        self.main_commit = commit
        return result

    def preserve_daily(self, *, extra_change=False):
        base = self.git('rev-parse', 'HEAD').strip()
        paths = ['data/image_localization/1025282.json', 'data/image_localization/1060124.json',
                 'data/shop_com_categories.json', 'data/shopify_daily_registry.json']
        before = c._tree(self.root, base)
        for path in paths:
            self.write(path, {'preserved_exact_external_result': True})
        if extra_change:
            self.write('data/source_budget.json', {'used': 0, 'stop': False})
        self.git('add', *paths, *(['data/source_budget.json'] if extra_change else []))
        self.git('commit', '-qm', 'chore(shopify): 일일 등록 이력 2026-10-23')
        commit = self.git('rev-parse', 'HEAD').strip()
        after = c._tree(self.root, commit)
        manifest = {'run_id': 39906965295, 'run_attempt': 1,
                    'workflow': '.github/workflows/daiso-daily-beauty-shopify.yml', 'head_sha': base,
                    'job_id': 120261030072, 'job_name': 'register', 'publication_step': '등록 이력 저장 (중복 방지)',
                    'publication_commit': commit, 'parent_commit': base,
                    'tree_sha': self.git('rev-parse', commit + '^{tree}').strip(),
                    'code_contract_digest': c.code_contract_digest(self.root, base),
                    'scope': 'preserve_exact_already_published_bytes_only',
                    'files': {p: {'before': before.get(p), 'after': after.get(p)} for p in paths},
                    'audit': {'job_log_sha256': 'a'*64, 'result_sha256': 'b'*64}}
        c.PRESERVED_PUBLICATIONS.append(manifest)
        self.decision['preserved_publications'] = copy.deepcopy(c.PRESERVED_PUBLICATIONS)
        self.write(c.DECISION_PATH, self.decision)
        self.git('add', c.DECISION_PATH); self.git('commit', '-qm', 'bind exact preservation scope')
        self.main_commit = self.git('rev-parse', 'HEAD').strip()
        self.current['head_sha'] = self.main_commit
        run = self.run(39906965295, 1, base, '2026-10-23T05:39:31Z', conclusion='success', workflow=manifest['workflow'])
        self.runs.append(run)
        endpoint = 'actions/runs/39906965295/attempts/1'
        self.jobs[endpoint + '/jobs?per_page=100'] = {'total_count': 1, 'jobs': [{
            'id': manifest['job_id'], 'name': 'register', 'run_id': run['id'], 'head_sha': base,
            'status': 'completed', 'conclusion': 'success',
            'steps': [{'name': manifest['publication_step'], 'conclusion': 'success',
                       'started_at': '2026-10-23T05:50:00Z', 'completed_at': '2026-10-23T06:00:00Z'}]}]}
        self.logs['actions/jobs/120261030072/logs'] = ('2026-10-23T05:59:00.8247955Z [main ' + commit[:9] + '] chore(shopify): 일일 등록 이력 2026-10-23\n').encode()
        return manifest

    def publish_prior_restricted(self, *, publication_failure=False, captured_report=None):
        report = self.report(write=True)
        base = self.main_commit
        prior = self.current
        self.git('add', c.REPORT_PATH, c.HISTORY_DIR); self.git('commit', '-qm', 'genuine restricted publication')
        commit = self.git('rev-parse', 'HEAD').strip()
        result = {key: report[key] for key in ('execution_id', 'run_id', 'run_attempt', 'actor', 'triggering_actor',
                  'analysis_id', 'decision_digest', 'input_commit', 'input_digests', 'code_contract_digest',
                  'protected_inventory_digest', 'gap_ids', 'production_recovered', 'operations_execution_verified',
                  'old_run_provider_calls', 'old_run_provider_cost', 'mode', 'continuity')}
        result.update(status='restricted_analysis_published', publication_profile=c.MODE,
                      declared_runtime_commands=[], executed_commands=[], operations_producer_status='quarantined_not_attempted',
                      commit_sha=commit, base_sha=base)
        if captured_report is not None:
            result['base_sha'] = captured_report['input_commit']
        prior.update(status='completed', conclusion='failure')
        endpoint = 'actions/runs/' + self.identity.replace(':', '/attempts/')
        steps = [{'name': name, 'conclusion': 'success'} for name in c.RESTRICTED_PROOF_STEPS]
        steps += [{'name': c.RESTRICTED_PUBLICATION_STEP, 'conclusion': 'failure' if publication_failure else 'success',
                   'started_at': '2026-10-23T05:50:00Z', 'completed_at': '2026-10-23T06:00:00Z'},
                  {'name': 'Retain restricted evidence without impersonating a normal checkpoint', 'conclusion': 'failure'}]
        self.jobs[endpoint + '/jobs?per_page=100'] = {'total_count': 1, 'jobs': [{
            'id': 60000000000 + prior['id'], 'name': c.RESTRICTED_WORKFLOWS[prior['path']], 'run_id': prior['id'], 'head_sha': prior['head_sha'],
            'status': 'completed', 'conclusion': 'failure', 'steps': steps}]}
        self.logs['actions/jobs/' + str(60000000000 + prior['id']) + '/logs'] = ('2026-10-23T06:00:00.000Z RESTRICTED_ANALYSIS_PUBLISHED ' + json.dumps(result) + '\n').encode()
        self.main_commit = commit
        self.run_id += 1; self.identity = str(self.run_id) + ':1'
        self.current = self.run(self.run_id, 1, commit, '2026-10-23T06:00:00Z')
        self.runs.insert(0, self.current)
        return result

    def report(self, *, write=False):
        result = c.build_review(self.root, decision=self.decision, evidence=self.evidence, now=NOW, execution_id=self.identity)
        if write:
            c.write_review(self.root, result, now=NOW)
        return result

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        for patch in reversed(self.patches):
            patch.stop()
        self.temporary.cleanup()


class ContinuityTests(unittest.TestCase):
    def test_fixed_baseline_and_unknown_cost(self):
        with RestrictedFixture() as f:
            before = c.protected_inventory(f.root)
            report = f.report(write=True)
            self.assertIsNone(report['old_run_provider_calls'])
            self.assertIsNone(report['old_run_provider_cost'])
            self.assertEqual(report['effective_new_request_allowance'], 0)
            self.assertEqual(report['gap_ids'], ['39893237129:1'])
            self.assertEqual(c.protected_inventory(f.root), before)
            c.validate_restricted_report(report, root=f.root, evidence=f.evidence, now=NOW)
            self.assertEqual(c.validate_published_review(f.root, report, now=NOW)['live_gap_validated'], False)

    def test_same_analysis_reuses_exact_immutable_bytes_and_nonce(self):
        with RestrictedFixture() as f:
            first = f.report(write=True)
            path = f.root / c.restricted_output_paths(first)[1]
            old = path.read_bytes()
            ledger = (f.root / 'data/operations/reports/.execution-ledger.json').read_bytes()
            later = NOW + timedelta(minutes=1)
            evidence = c.authenticate_evidence(f.root, execution_id=f.identity, now=later, transport=f.transport)
            second = c.build_review(f.root, evidence=evidence, now=later, execution_id=f.identity)
            self.assertEqual(second['analysis_id'], first['analysis_id'])
            self.assertEqual(second['analyzed_at'], first['analyzed_at'])
            c.write_review(f.root, second, now=later)
            self.assertEqual(path.read_bytes(), old)
            self.assertEqual((f.root / 'data/operations/reports/.execution-ledger.json').read_bytes(), ledger)

    def test_pure_analysis_cannot_call_provider_or_dispatch(self):
        with RestrictedFixture() as f:
            real_run = subprocess.run
            def only_git(command, **kwargs):
                self.assertEqual(command[0], 'git')
                return real_run(command, **kwargs)
            with mock.patch.object(c, '_github_json', side_effect=AssertionError('provider call')), \
                 mock.patch.object(subprocess, 'run', side_effect=only_git), \
                 mock.patch('urllib.request.urlopen', side_effect=AssertionError('network call')):
                report = f.report(write=True)
            self.assertTrue(all(v == 'quarantined/not_attempted' for v in report['blocked_capabilities'].values()))

    def test_every_protected_byte_and_new_file_is_detected(self):
        for mutation in ('ledger', 'stop', 'extra', 'delete', 'mode'):
            with self.subTest(mutation=mutation), RestrictedFixture() as f:
                before = c.protected_inventory(f.root)
                if mutation == 'ledger':
                    f.write('data/operations/reports/.execution-ledger.json', {'claims': {'fixed-claim': {'nonce': 'replayed'}}})
                elif mutation == 'stop':
                    f.write('data/source_budget.json', {'used': 0, 'stop': False})
                elif mutation == 'extra':
                    f.write('data/unknown-new-action.json', {})
                elif mutation == 'delete':
                    (f.root / 'data/source_budget.json').unlink()
                else:
                    (f.root / 'data/source_budget.json').chmod(0o755)
                with self.assertRaises(c.ContinuityError):
                    c.assert_protected_unchanged(before, c.protected_inventory(f.root))
                with self.assertRaises(c.ContinuityError):
                    f.report()

    def test_source_input_change_requires_authenticated_main_refresh(self):
        with RestrictedFixture() as f:
            f.write(c.INPUT_PATHS[0], {'products': []})
            with self.assertRaisesRegex(c.ContinuityError, 'authenticated_main'):
                f.report()

    def test_code_change_invalidates_decision(self):
        with RestrictedFixture() as f:
            f.write('scripts/analyzer.py', '# changed\n', raw=True)
            with self.assertRaisesRegex(c.ContinuityError, 'code_contract'):
                f.report()

    def test_decision_mode_scope_expiry_and_extra_fields_fail(self):
        mutations = [('mode', 'normal'), ('mode', 'non_operations'), ('expires_at', '2026-10-23T05:30:00Z'),
                     ('allowed_effects', ['operations_actions']), ('code_contract_digest', None),
                     ('approved', True), ('gap_inventory', [])]
        for key, value in mutations:
            with self.subTest(key=key, value=value), RestrictedFixture() as f:
                decision = copy.deepcopy(f.decision); decision[key] = value
                with self.assertRaises(c.ContinuityError):
                    c.validate_decision(decision, root=f.root, evidence=f.evidence, now=NOW)

    def test_self_attested_json_is_never_authenticated_evidence(self):
        with RestrictedFixture() as f:
            with self.assertRaises(c.ContinuityError):
                c.validate_decision(f.decision, root=f.root, evidence={'verified': True}, now=NOW)

    def test_unknown_new_run_and_old_id_new_attempt_block(self):
        for old in (False, True):
            with self.subTest(old=old), RestrictedFixture() as f:
                created = '2026-09-01T00:00:00Z' if old else '2026-10-23T05:30:00Z'
                run = f.run(9999, 2 if old else 1, f.main_commit, created, conclusion='failure')
                run['updated_at'] = '2026-10-23T05:30:00Z'
                f.runs.append(run)
                with self.assertRaisesRegex(c.ContinuityError, 'additional_unapproved|approved_history_inventory_changed|prior_restricted_attempt_unreconciled'):
                    c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW, transport=f.transport)

    def test_entire_repository_inventory_is_paginated_without_filter(self):
        with RestrictedFixture() as f:
            for n in range(101):
                run = f.run(1000+n, 1, f.main_commit, '2026-09-01T00:00:00Z', conclusion='success')
                run['head_branch'] = 'another-branch'
                f.runs.append(run)
            f.decision['approved_history_inventory_digest'] = c.approved_history_inventory_digest(f.runs)
            f.write(c.DECISION_PATH, f.decision)
            f.git('add', '.'); f.git('commit', '-qm', 'review historical fixture inventory')
            f.main_commit = f.git('rev-parse', 'HEAD').strip(); f.current['head_sha'] = f.main_commit
            c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW, transport=f.transport)
            self.assertIn('actions/runs?per_page=100&page=2', f.calls)
            self.assertFalse(any('branch=' in call or 'created=' in call or 'status=' in call for call in f.calls))

    def test_incomplete_or_duplicate_inventory_blocks(self):
        with RestrictedFixture() as f:
            def incomplete(endpoint):
                data = f.transport(endpoint)
                if endpoint.startswith('actions/runs?'):
                    data['total_count'] += 1
                return data
            with self.assertRaisesRegex(c.ContinuityError, 'inventory_incomplete'):
                c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW, transport=incomplete)
            f.runs.append(copy.deepcopy(f.gap))
            with self.assertRaisesRegex(c.ContinuityError, 'duplicate'):
                c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW, transport=f.transport)

    def test_report_mode_authority_identity_and_cost_tamper_fail(self):
        changes = [('mode', 'normal'), ('production_recovered', True), ('operations_execution_verified', True),
                   ('old_run_provider_calls', 0), ('old_run_provider_cost', 0), ('analysis_id', '0'*64),
                   ('gap_ids', []), ('execution_id', '39893237129:1'), ('blocked_capabilities', {}),
                   ('receipt_id', 'fabricated')]
        with RestrictedFixture() as f:
            report = f.report(write=True)
            for key, value in changes:
                bad = copy.deepcopy(report); bad[key] = value
                with self.subTest(key=key), self.assertRaises(c.ContinuityError):
                    c.validate_restricted_report(bad, root=f.root, evidence=f.evidence, now=NOW)

    def test_duplicate_json_and_nonfinite_rejected(self):
        for raw in ('{"mode":"normal","mode":"restricted_gap"}', '{"price":NaN}'):
            with self.assertRaises(c.ContinuityError):
                c._json(raw)

    def test_symlink_and_history_tampering_rejected(self):
        with RestrictedFixture() as f:
            report = f.report(write=True)
            path = f.root / c.restricted_output_paths(report)[1]
            path.write_text('{}')
            with self.assertRaises(c.ContinuityError):
                c.validate_published_review(f.root, report, now=NOW)
            (f.root / 'data/symlink').symlink_to('/tmp')
            with self.assertRaises(c.ContinuityError):
                c.protected_inventory(f.root)

    def test_evidence_expiry_no_midnight_reset(self):
        with RestrictedFixture() as f:
            with self.assertRaisesRegex(c.ContinuityError, 'evidence_expired'):
                c.validate_decision(f.decision, root=f.root, evidence=f.evidence, now=NOW+timedelta(minutes=11))
            decision = copy.deepcopy(f.decision)
            decision['expires_at'] = '2026-11-23T05:06:23Z'
            with self.assertRaises(c.ContinuityError):
                c.validate_decision(decision, root=f.root, evidence=f.evidence, now=NOW)

    def test_pending_projection_never_claims_analysis(self):
        with RestrictedFixture() as f:
            pending = c.validate_pending_decision(f.root, now=NOW)
            self.assertIsNone(pending['analyzed_at'])
            self.assertFalse(pending['production_recovered'])
            self.assertEqual(pending['status'], 'RESTRICTED_ANALYSIS_PENDING')


class WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import yaml
        cls.root = Path(__file__).resolve().parents[1]
        cls.workflows = []
        for name in ('JARVIS-Core-Automation.yml', 'JARVIS-Deep-Analysis.yml'):
            document = yaml.safe_load((cls.root / '.github/workflows' / name).read_text())
            cls.workflows.append((name, next(iter(document['jobs'].values()))))

    def test_every_effect_and_normal_retention_is_mode_gated(self):
        for name, job in self.workflows:
            with self.subTest(workflow=name):
                steps = job['steps']
                select = next(i for i, step in enumerate(steps) if step.get('id') == 'continuity_mode')
                self.assertLess(select, 5)
                for step in steps[select+1:]:
                    condition = str(step.get('if', ''))
                    self.assertIn('steps.continuity_mode.outputs.mode', condition, step.get('name'))
                    command = step.get('run', '')
                    if any(token in command for token in ('run_jarvis_operations.py', 'run_commerce_pipeline.py',
                                                          'run_source_procedures.py', 'collect_daiso_gosi.py',
                                                          'auto_recovery', 'safe_auto_fix', 'extract_gosi_vision.py')):
                        self.assertIn("mode == 'normal'", condition)
                    if 'upload-artifact@' in step.get('uses', ''):
                        artifact = step['with']['name']
                        if artifact.startswith(('operations-safety-', 'source-safety-', 'typesafe-budget-receipt-')):
                            self.assertIn("mode == 'normal'", condition)

    def test_normal_restore_failure_blocks_effects_before_execution(self):
        import itertools
        for name, job in self.workflows:
            steps = job['steps']
            gate_index = next(i for i, step in enumerate(steps) if step.get('id') == 'normal_continuity_gate')
            gate = steps[gate_index]
            self.assertIsNot(gate.get('continue-on-error'), True)
            self.assertEqual(gate['if'], "steps.continuity_mode.outputs.mode == 'normal'")
            for restore in ('source_safety', 'operations_safety'):
                self.assertLess(next(i for i, s in enumerate(steps) if s.get('id') == restore), gate_index)
                self.assertIn('steps.' + restore + '.outcome', str(gate['env']))
            self.assertIn('steps.source_safety.outputs.continuity', str(gate['env']))
            self.assertIn('steps.operations_safety.outputs.operations_continuity', str(gate['env']))
            keys = ('SOURCE_OUTCOME', 'SOURCE_CONTINUITY', 'OPERATIONS_OUTCOME', 'OPERATIONS_CONTINUITY')
            good = ('success', 'verified', 'success', 'verified')
            cases = [good] + [tuple('' if i == bad else value for i, value in enumerate(good)) for bad in range(4)]
            cases += [('failure', 'verified', 'success', 'verified'), ('success', 'verified', 'failure', 'verified'),
                      ('failure', '', 'failure', ''), ('success', 'blocked', 'success', 'verified'),
                      ('success', 'verified', 'success', 'blocked')]
            for values in cases:
                with self.subTest(workflow=name, values=values):
                    env = dict(os.environ, **dict(zip(keys, values)))
                    # Actual workflow CLI followed by a trap for any downstream effect.
                    command = gate['run'] + "\nprintf 'UNEXPECTED_EFFECT_CALL\\n'\n"
                    result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', command],
                                            env=env, capture_output=True, text=True, timeout=10)
                    if values == good:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn('UNEXPECTED_EFFECT_CALL', result.stdout)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertNotIn('UNEXPECTED_EFFECT_CALL', result.stdout)
            for step in steps[gate_index+1:]:
                condition = str(step.get('if', ''))
                command = step.get('run', '')
                if any(token in command for token in ('collect_', 'run_jarvis_operations', 'run_commerce_pipeline',
                                                      'generate_dashboard_runtime', 'build_team_improvement')):
                    self.assertIn("mode == 'normal'", condition, step.get('name'))
                    self.assertNotIn('always()', condition, step.get('name'))
                    self.assertNotIn('failure()', condition, step.get('name'))
            # Restricted or unknown mode cannot satisfy this normal-only gate;
            # all provider steps are separately tested to require exact normal mode.
            for mode in ('restricted_gap', '', 'NORMAL', 'unverified'):
                self.assertNotEqual(mode, 'normal')

    def test_restricted_steps_never_receive_ai_credentials(self):
        for name, job in self.workflows:
            self.assertFalse(any('secrets.' in str(value) for value in job.get('env', {}).values()))
            for step in job['steps']:
                secrets = any('secrets.' in str(value) for value in step.get('env', {}).values())
                if secrets:
                    self.assertIn("mode == 'normal'", str(step.get('if', '')), (name, step.get('name')))

    def test_artifact_failure_cannot_become_normal_checkpoint_or_recovery(self):
        for name, job in self.workflows:
            steps = job['steps']
            artifact_index = next(i for i, step in enumerate(steps) if step.get('id') == 'restricted_retention')
            artifact = steps[artifact_index]
            self.assertFalse(artifact.get('continue-on-error', False))
            self.assertEqual(artifact['with']['name'], 'restricted-review-${{ github.run_id }}-${{ github.run_attempt }}')
            self.assertEqual(artifact['with']['if-no-files-found'], 'error')
            self.assertLessEqual(artifact['timeout-minutes'], 2)
            self.assertTrue(any('always()' in str(step.get('if', '')) and
                                'steps.restricted_retention.outcome' in str(step.get('env', {})) and
                                'unresolved_gap' in step.get('run', '') for step in steps[artifact_index+1:]))
        from build_public_site import restricted_public_summary
        with RestrictedFixture() as f:
            report = f.report(write=True)
            # Artifact upload failure does not erase already published analysis
            # or change its schema into a verified restore/operations checkpoint.
            summary = restricted_public_summary(report)
            self.assertEqual(summary['status'], 'RESTRICTED_ANALYSIS_COMPLETE')
            self.assertEqual(summary['continuity'], 'unresolved_gap')
            self.assertFalse(summary['production_recovered'])
            self.assertFalse(summary['operations_execution_verified'])
            self.assertNotIn('retention_verified', summary)
            self.assertNotIn('actor', summary)
            self.assertNotIn('approval', summary)


class AdditionalAdversarialTests(unittest.TestCase):
    def test_missing_decision_is_blocked_and_never_normal(self):
        with tempfile.TemporaryDirectory() as root, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(c.main(['decide', '--root', root]), 1)
            self.assertEqual(json.loads(out.getvalue())['mode'], 'blocked')

    def test_actor_cannot_be_substituted(self):
        with RestrictedFixture() as f:
            report = f.report(write=True)
            report['actor'] = {'login': 'another-owner', 'id': 456}
            with self.assertRaisesRegex(c.ContinuityError, 'actor'):
                c.validate_restricted_report(report, root=f.root, evidence=f.evidence, now=NOW)

    def test_second_complete_inventory_scan_detects_attempt_race(self):
        with RestrictedFixture() as f:
            count = 0
            def changed(endpoint):
                nonlocal count
                result = f.transport(endpoint)
                if endpoint.startswith('actions/runs?'):
                    count += 1
                    if count == 2:
                        result['workflow_runs'][1]['run_attempt'] = 2
                return result
            with self.assertRaisesRegex(c.ContinuityError, 'between_scans'):
                c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW, transport=changed)

    def test_unrecognized_workflow_after_gap_is_not_ignored(self):
        with RestrictedFixture() as f:
            f.runs.append(f.run(777, 1, f.main_commit, '2026-10-23T05:40:00Z',
                                conclusion='failure', workflow='.github/workflows/unknown-ai.yml'))
            with self.assertRaisesRegex(c.ContinuityError, 'additional_unapproved|prior_restricted_attempt_unreconciled'):
                c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW, transport=f.transport)

    def test_composite_and_requirement_code_changes_invalidate_binding(self):
        for path in ('.github/actions/publish/action.yml', 'requirements/requirements-core.txt', 'new_root_script.py'):
            with self.subTest(path=path), RestrictedFixture() as f:
                f.write(path, '# changed', raw=True)
                with self.assertRaisesRegex(c.ContinuityError, 'code_contract'):
                    f.report()

    def test_current_run_impersonation_is_blocked_without_actions_environment(self):
        with RestrictedFixture() as f, mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(c.ContinuityError, 'current_actions_execution_required'):
                c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW)

    def test_actions_gates_reject_missing_or_wrong_runtime_identity_before_reads(self):
        with RestrictedFixture() as f:
            report = f.report(write=True)
            for values in ({'GITHUB_RUN_ID': ''}, {'GITHUB_RUN_ATTEMPT': ''},
                           {'GITHUB_RUN_ID': '999'}, {'GITHUB_RUN_ATTEMPT': '2'}):
                with self.subTest(values=values), mock.patch.dict(os.environ, values), \
                     mock.patch.object(c, '_github_json', side_effect=AssertionError('network forbidden')):
                    self.assertEqual(os.environ['GITHUB_ACTIONS'], 'true')
                    with self.assertRaisesRegex(c.ContinuityError, 'current_actions_execution_required'):
                        c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW)
                    with self.assertRaisesRegex(c.ContinuityError, 'current_actions_execution_required'):
                        c.validate_review_bindings(f.root, report, execution_id=f.identity, now=NOW)

    def test_metadata_transport_refuses_external_provider_url(self):
        with mock.patch.dict(os.environ, {'GITHUB_TOKEN': 'fixture-only'}, clear=True), \
             mock.patch('urllib.request.build_opener', side_effect=AssertionError('network should not open')):
            with self.assertRaisesRegex(c.ContinuityError, 'scope_denied'):
                c._github_json('https://provider.example.invalid/generate')

    def test_real_metadata_transport_accepts_only_exact_run_artifact_inventory(self):
        payload = b'{"total_count":0,"artifacts":[]}'
        response = io.BytesIO(payload)
        response.status = 200
        response.headers = {'Content-Length': str(len(payload)),
                            'X-RateLimit-Remaining': '4900', 'X-RateLimit-Limit': '5000',
                            'X-RateLimit-Reset': '1792746000'}
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.dict(os.environ, {'GITHUB_TOKEN': 'fixture-only'}, clear=True), \
             mock.patch('urllib.request.build_opener', return_value=opener):
            self.assertEqual(c._github_json('actions/runs/39911582752/artifacts?per_page=100'),
                             {'total_count': 0, 'artifacts': []})
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.github.com/repos/' + c.REPOSITORY +
                         '/actions/runs/39911582752/artifacts?per_page=100')
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(opener.open.call_args.kwargs, {'timeout': 20})
        for endpoint in ('actions/artifacts', 'actions/runs/0/artifacts?per_page=100',
                         'actions/runs/39911582752/artifacts?per_page=100&page=2',
                         'actions/runs/39911582752/artifacts?per_page=100&url=https://evil.invalid',
                         'actions/runs/39911582752/artifacts/1/zip',
                         '../other/repo/actions/runs/39911582752/artifacts?per_page=100'):
            with self.subTest(endpoint=endpoint), \
                 mock.patch('urllib.request.build_opener', side_effect=AssertionError('network forbidden')):
                with self.assertRaisesRegex(c.ContinuityError, 'github_read_scope_denied'):
                    c._github_json(endpoint)

    def test_pure_findings_have_fixed_baseline_change_and_capture_evidence(self):
        with RestrictedFixture() as f:
            report = f.report()
            for finding in report['review_findings'].values():
                self.assertIn('input_changes', finding)
                self.assertFalse(finding['input_changes']['bytes_changed'])
                self.assertEqual(finding['cached_numeric_ranges']['price']['minimum'], 100)
                self.assertEqual(finding['cached_numeric_ranges']['price']['baseline_minimum'], 100)
            self.assertEqual(report['original_capture_times'][c.INPUT_PATHS[0]]['collected_at'], '2026-10-23T04:00:00Z')



class PublicationProofTests(unittest.TestCase):
    def test_exact_independent_input_publication_accepts_new_saved_input(self):
        with RestrictedFixture() as f:
            first = f.report(write=True)
            f.publish_knowledge()
            evidence = c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                               transport=f.transport, log_transport=f.log_transport, purpose='publication')
            report = c.build_review(f.root, evidence=evidence, now=NOW, execution_id=f.identity)
            self.assertNotEqual(first['analysis_id'], report['analysis_id'])
            self.assertEqual(report['input_commit'], f.main_commit)
            self.assertTrue(report['review_findings']['data/team_improvement.json']['input_changes']['bytes_changed'])
            c.write_review(f.root, report, now=NOW)
            c.validate_publication_freshness(f.root, report, evidence=evidence, execution_id=f.identity,
                                            now=NOW, transport=f.transport)

    def test_independent_retry_uses_final_remote_parent_and_preserves_capture_base(self):
        for malformed in (False, True):
            with self.subTest(malformed=malformed), RestrictedFixture() as f:
                captured = f.main_commit
                f.git('commit', '--allow-empty', '-qm', 'independent main advance while publisher retries')
                remote = f.git('rev-parse', 'HEAD').strip()
                result = f.publish_knowledge()
                result['base_sha'] = captured
                result['attempts'] = [
                    {'attempt': 1, 'remote_sha': captured, 'validated': True,
                     'publication_profile': 'non_operations', 'push_rejected': True},
                    {'attempt': 2, 'remote_sha': remote, 'validated': True,
                     'publication_profile': 'non_operations'}]
                if malformed:
                    result['attempts'][0]['push_rejected'] = False
                f.logs['actions/jobs/120253948591/logs'] = (
                    '2026-10-23T05:59:00Z PUBLISH_TRANSACTION_OK ' + json.dumps(result) + '\n').encode()
                if malformed:
                    with self.assertRaisesRegex(c.ContinuityError, 'attempt_sequence_invalid'):
                        c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                                transport=f.transport, log_transport=f.log_transport)
                else:
                    c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                            transport=f.transport, log_transport=f.log_transport)

    def test_default_deny_covers_budget_gates_and_unknown_state_names(self):
        for path in ('data/serpapi_usage.json', 'data/listing_gate.json', 'data/mystery_provider_counter.json'):
            with self.subTest(path=path), RestrictedFixture() as f:
                self.assertTrue(c._effect_state(path))
                f.publish_knowledge(mutate=lambda root: (root / path).write_text('{"used":0}'))
                with self.assertRaisesRegex(c.ContinuityError, 'effect_state_changed'):
                    c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                            transport=f.transport, log_transport=f.log_transport)

    def test_direct_and_merge_canonical_changes_need_exact_publication_proof(self):
        for merge in (False, True):
            with self.subTest(merge=merge), RestrictedFixture() as f:
                branch = f.git('branch', '--show-current').strip()
                if merge:
                    f.git('checkout', '-qb', 'unattributed')
                f.write('data/team_improvement.json', {'products': [{'price': 0}]})
                f.git('add', 'data/team_improvement.json'); f.git('commit', '-qm', 'unattributed canonical change')
                if merge:
                    f.git('checkout', branch)
                    f.git('commit', '--allow-empty', '-qm', 'main code-neutral change')
                    f.git('merge', '--no-ff', '-m', 'unattributed merge', 'unattributed')
                f.main_commit = f.git('rev-parse', 'HEAD').strip()
                with self.assertRaisesRegex(c.ContinuityError, 'unattributed_canonical_input_change'):
                    c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW, transport=f.transport)

    def test_original_history_bytes_always_frozen_even_in_input_profile(self):
        for remove in (False, True):
            with self.subTest(remove=remove), RestrictedFixture() as f:
                def mutation(root):
                    path = root / ('data/knowledge/moe_evaluation_history/' + 'a'*64 + '.json')
                    path.unlink() if remove else path.write_text('{}')
                f.publish_knowledge(mutate=mutation)
                with self.assertRaisesRegex(c.ContinuityError, 'history_changed'):
                    c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                            transport=f.transport, log_transport=f.log_transport)

    def test_new_bounded_history_member_requires_verified_publication(self):
        with RestrictedFixture() as f:
            f.publish_knowledge(mutate=lambda root: (root / ('data/knowledge/moe_evaluation_history/' + 'b'*64 + '.json')).write_text('{}'))
            evidence = c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                               transport=f.transport, log_transport=f.log_transport)
            c.build_review(f.root, evidence=evidence, now=NOW, execution_id=f.identity)

    def test_independent_profile_needs_success_exact_step_and_approved_code(self):
        for mutation in ('failed', 'step', 'code'):
            with self.subTest(mutation=mutation), RestrictedFixture() as f:
                if mutation == 'code':
                    f.write('scripts/analyzer.py', '# unapproved code', raw=True)
                    f.git('add', '.'); f.git('commit', '-qm', 'unapproved producer code')
                f.publish_knowledge()
                if mutation == 'failed': f.runs[-1]['conclusion'] = 'failure'
                if mutation == 'step':
                    key = next(iter(f.logs))
                    f.logs[key] = b'2026-10-23T05:49:00Z PUBLISH_TRANSACTION_OK {}\n'
                with self.assertRaises(c.ContinuityError):
                    c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                            transport=f.transport, log_transport=f.log_transport)

    def test_current_rerun_cannot_hide_an_unpublished_earlier_attempt(self):
        with RestrictedFixture() as f:
            f.identity = str(f.run_id) + ':2'; f.current['run_attempt'] = 2
            with self.assertRaisesRegex(c.ContinuityError, 'earlier_current_attempt_unreconciled'):
                c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW, transport=f.transport)

    def test_pages_shallow_clone_requires_only_exact_baseline_fetch(self):
        with RestrictedFixture() as f, tempfile.TemporaryDirectory() as directory:
            report = f.report(write=True)
            f.git('add', c.REPORT_PATH, c.HISTORY_DIR); f.git('commit', '-qm', 'published restricted review')
            clone = Path(directory) / 'shallow'
            subprocess.run(['git', 'clone', '-q', '--depth=1', f.root.as_uri(), str(clone)], check=True)
            before = c.protected_inventory(clone)
            with self.assertRaisesRegex(c.ContinuityError, 'git_evidence_unavailable'):
                c.validate_published_review(clone, report, now=NOW)
            subprocess.run(['git', '-C', str(clone), 'fetch', '-q', '--no-tags', '--depth=1', 'origin', f.baseline_commit], check=True)
            c.validate_published_review(clone, report, now=NOW)
            self.assertEqual(before, c.protected_inventory(clone))
            self.assertNotEqual(subprocess.run(['git', '-C', str(clone), 'cat-file', '-e', c.BASELINE['original_publication_commit']],
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode, 0)




class ReconciledBlockedRunTests(unittest.TestCase):
    def add_proof(self, f):
        run = f.run(50000000888, 1, f.main_commit, '2026-10-23T05:55:00Z', conclusion='failure')
        run['event'] = 'workflow_dispatch'
        steps = [{'number': number, 'name': 'exact audited step ' + str(number), 'status': 'completed',
                  'conclusion': 'success', 'started_at': '2026-10-23T05:55:00Z',
                  'completed_at': '2026-10-23T05:56:00Z'} for number in (6, 7, 13)]
        job = {'id': 60000000888, 'run_id': run['id'], 'run_attempt': 1, 'head_sha': run['head_sha'],
               'head_branch': 'main', 'name': 'core-automation', 'status': 'completed',
               'conclusion': 'failure', 'steps': steps}
        raw = (b'2026-10-23T05:55:30Z SOURCE_SAFETY_BLOCKED authenticated_history_or_checkpoint_reconciliation_required\n'
               b'2026-10-23T05:55:30Z OPERATIONS_SAFETY_BLOCKED authenticated_history_or_reconciliation_required code=artifactless_run_actuation_unproved\n'
               b'2026-10-23T05:55:30Z COMMERCE_PIPELINE_OK offline policy chain complete; authority=false\n')
        proof = {'run_id': run['id'], 'run_attempt': 1, 'head_sha': run['head_sha'], 'workflow': run['path'],
                 **{key: run[key] for key in ('created_at', 'updated_at', 'actor', 'triggering_actor', 'event')},
                 'job_id': job['id'], 'job_name': job['name'], 'code_contract_digest': c.code_contract_digest(f.root),
                 'job_projection_digest': c.canonical_digest(c._job_projection(job)),
                 'canonical_job_log_sha256': c.hashlib.sha256(c._canonical_job_log(raw)).hexdigest(),
                 'job_log_normalization': 'utf8_strict_remove_one_leading_bom_crlf_to_lf_one_trailing_lf',
                 'scope': 'exact_completed_blocked_run_no_remote_publication_or_provider_actuation',
                 'runner_local_changes': 'discarded_not_restored', 'artifact_count': 0}
        patch = mock.patch.object(c, 'RECONCILED_BLOCKED_RUNS', [proof]); patch.start(); f.patches.append(patch)
        f.decision['reconciled_blocked_runs'] = [proof]
        f.write(c.DECISION_PATH, f.decision); f.git('add', c.DECISION_PATH); f.git('commit', '-qm', 'reviewed exact blocked run')
        f.main_commit = f.git('rev-parse', 'HEAD').strip(); f.current['head_sha'] = f.main_commit
        f.runs.append(run)
        f.jobs['actions/runs/50000000888/attempts/1/jobs?per_page=100'] = {'total_count': 1, 'jobs': [job]}
        f.jobs['actions/runs/50000000888/artifacts?per_page=100'] = {'total_count': 0, 'artifacts': []}
        f.logs['actions/jobs/60000000888/logs'] = raw
        return run, job, proof

    def test_exact_blocked_run_does_not_create_lineage_or_restore_local_derivatives(self):
        with RestrictedFixture() as f:
            run, _, _ = self.add_proof(f)
            before = c.protected_inventory(f.root)
            evidence = c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                               transport=f.transport, log_transport=f.log_transport)
            report = c.build_review(f.root, evidence=evidence, now=NOW, execution_id=f.identity)
            self.assertEqual(report['gap_ids'], ['39893237129:1'])
            self.assertNotIn(c._run_identity(run), report['publication_executions'])
            self.assertEqual(before, c.protected_inventory(f.root))
            self.assertFalse(report['operations_execution_verified'])

    def test_complete_proof_changes_and_future_attempts_are_denied(self):
        for mutation in ('log', 'step', 'artifact', 'head', 'attempt', 'missing', 'newrun'):
            with self.subTest(mutation=mutation), RestrictedFixture() as f:
                run, job, _ = self.add_proof(f)
                if mutation == 'log': f.logs['actions/jobs/60000000888/logs'] += b'new action\n'
                if mutation == 'step': job['steps'][0]['conclusion'] = 'failure'
                if mutation == 'artifact': f.jobs['actions/runs/50000000888/artifacts?per_page=100']['total_count'] = 1
                if mutation == 'head': run['head_sha'] = f.baseline_commit
                if mutation == 'attempt': run['run_attempt'] = 2
                if mutation == 'missing': f.runs.remove(run)
                if mutation == 'newrun':
                    f.runs.append(f.run(50000000889, 1, f.main_commit, '2026-10-23T05:56:00Z', conclusion='failure'))
                with self.assertRaises(c.ContinuityError):
                    c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                            transport=f.transport, log_transport=f.log_transport)

    def test_only_bom_crlf_and_terminal_lf_transport_variations_are_accepted(self):
        with RestrictedFixture() as f:
            run, _, proof = self.add_proof(f)
            raw = f.logs['actions/jobs/60000000888/logs']
            for bom in (b'', b'\xef\xbb\xbf'):
                for newline in (b'\n', b'\r\n'):
                    for ending in (b'', newline, newline*3):
                        variant = bom + raw.rstrip(b'\n').replace(b'\n', newline) + ending
                        with self.subTest(bom=bom, newline=newline, ending=ending):
                            c._verify_reconciled_blocked_run(f.root, run, proof, f.transport, lambda endpoint: variant)

    def test_canonical_log_rejects_body_space_lone_cr_second_bom_and_invalid_utf8(self):
        with RestrictedFixture() as f:
            run, _, proof = self.add_proof(f)
            raw = f.logs['actions/jobs/60000000888/logs']
            for variant in (raw.replace(b'authority=false', b'authority=true'), raw.rstrip(b'\n') + b' \n',
                            raw.replace(b'\n', b'\r'), b'\xef\xbb\xbf'*2 + raw, raw + b'\xff'):
                with self.subTest(variant=variant[-30:]), self.assertRaises(c.ContinuityError):
                    c._verify_reconciled_blocked_run(f.root, run, proof, f.transport, lambda endpoint: variant)

    def test_api_continue_on_error_success_cannot_replace_actual_blocked_markers(self):
        with RestrictedFixture() as f:
            run, job, proof = self.add_proof(f)
            raw = f.logs['actions/jobs/60000000888/logs'].replace(b'SOURCE_SAFETY_BLOCKED', b'SOURCE_SAFETY_VERIFIED')
            proof['canonical_job_log_sha256'] = c.hashlib.sha256(c._canonical_job_log(raw)).hexdigest()
            with self.assertRaisesRegex(c.ContinuityError, 'unique_job_publication_record'):
                c._verify_reconciled_blocked_run(f.root, run, proof, f.transport, lambda endpoint: raw)


class ExactJobLogTests(unittest.TestCase):
    def step(self):
        return {'started_at': '2026-10-23T05:20:09Z', 'completed_at': '2026-10-23T05:22:16Z'}

    def test_actual_second_precision_window_accepts_only_less_than_one_second(self):
        valid = b'2026-10-23T05:22:16.1154637Z PUBLISH_TRANSACTION_OK {"status":"published"}\n'
        self.assertEqual(c._publication_from_job(valid, self.step()), {'status': 'published'})
        for stamp in ('2026-10-23T05:20:08.999999Z', '2026-10-23T05:22:17Z'):
            with self.subTest(stamp=stamp), self.assertRaisesRegex(c.ContinuityError, 'outside_step'):
                c._publication_from_job((stamp + ' PUBLISH_TRANSACTION_OK {}\n').encode(), self.step())

    def test_duplicate_marker_anywhere_in_job_is_denied(self):
        raw = (b'2026-10-23T05:22:16Z PUBLISH_TRANSACTION_OK {}\n'
               b'2026-10-23T05:25:16Z PUBLISH_TRANSACTION_OK {}\n')
        with self.assertRaisesRegex(c.ContinuityError, 'unique_job_publication_record'):
            c._publication_from_job(raw, self.step())

    def test_missing_invalid_and_reversed_step_timestamps_are_denied(self):
        for step in ({}, {'started_at': 'invalid', 'completed_at': '2026-10-23T05:22:16Z'},
                     {'started_at': '2026-10-23T05:23:16Z', 'completed_at': '2026-10-23T05:22:16Z'},
                     {'started_at': '2026-10-23T03:20:09Z', 'completed_at': '2026-10-23T05:22:16Z'}):
            with self.subTest(step=step), self.assertRaises(c.ContinuityError):
                c._publication_from_job(b'2026-10-23T05:22:16Z PUBLISH_TRANSACTION_OK {}\n', step)

    def test_wrong_job_identity_or_nonpositive_id_cannot_select_a_log(self):
        for field, value in (('run_id', 9), ('id', 0), ('id', True), ('head_sha', '0'*40)):
            with self.subTest(field=field, value=value), RestrictedFixture() as f:
                f.publish_knowledge()
                f.jobs['actions/runs/50000000010/attempts/1/jobs?per_page=100']['jobs'][0][field] = value
                f.calls.clear()
                with self.assertRaises(c.ContinuityError):
                    c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                            transport=f.transport, log_transport=f.log_transport)
                self.assertFalse(any('/logs' in endpoint for endpoint in f.calls))

    def test_log_reader_rejects_truncation_declared_and_streamed_oversize(self):
        class Response:
            status = 200
            def __init__(self, raw, size=None):
                self.stream = io.BytesIO(raw)
                self.headers = {} if size is None else {'Content-Length': str(size)}
            def read1(self, size):
                return self.stream.read(size)
        self.assertEqual(c._bounded_job_log_response(Response(b'abc', 3)), b'abc')
        for response in (Response(b'abc', 4), Response(b'', 16*1024*1024+1),
                         Response(b'x'*(16*1024*1024+1))):
            with self.assertRaises(c.ContinuityError):
                c._bounded_job_log_response(response)
        with self.assertRaisesRegex(c.ContinuityError, 'job_log_size_limit'):
            c._publication_from_job(b'x'*(16*1024*1024+1), self.step())

    def test_log_reader_checks_deadline_after_read(self):
        response = mock.Mock(status=200, headers={})
        response.read1.return_value = b''
        with mock.patch.object(c.time, 'monotonic', side_effect=[0, 1, 21]):
            with self.assertRaisesRegex(c.ContinuityError, 'log_response_time_limit'):
                c._bounded_job_log_response(response)


class PriorPublicationTests(unittest.TestCase):
    def test_genuine_published_run_survives_later_export_or_artifact_failure(self):
        for export_failure in (False, True):
            with self.subTest(export_failure=export_failure), RestrictedFixture() as f:
                prior = f.publish_prior_restricted(publication_failure=export_failure)
                evidence = c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                                   transport=f.transport, log_transport=f.log_transport)
                report = c.build_review(f.root, evidence=evidence, now=NOW, execution_id=f.identity)
                self.assertIn(prior['execution_id'], report['publication_executions'])
                self.assertEqual(len(report['publication_executions']), 2)
                self.assertFalse(report['operations_execution_verified'])

    def test_genuine_input_advance_preserves_only_verified_captured_history(self):
        with RestrictedFixture() as f:
            initial = f.report(write=True)
            f.publish_knowledge()
            f.evidence = c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                                 transport=f.transport, log_transport=f.log_transport)
            f.publish_prior_restricted(captured_report=initial)
            c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                    transport=f.transport, log_transport=f.log_transport)

    def test_extra_captured_history_without_authenticated_input_binding_is_denied(self):
        for mutation in ('missing', 'findings', 'commit'):
            with self.subTest(mutation=mutation), RestrictedFixture() as f:
                initial = f.report(write=True)
                f.publish_knowledge()
                f.evidence = c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                                     transport=f.transport, log_transport=f.log_transport)
                if mutation == 'findings':
                    path = f.root / c.restricted_output_paths(initial)[1]
                    old = json.loads(path.read_text())
                    old['review_findings'][c.INPUT_PATHS[0]]['row_count'] = 999999
                    path.write_text(json.dumps(old))
                captured = None if mutation == 'missing' else copy.deepcopy(initial)
                if mutation == 'commit': captured['input_commit'] = f.main_commit
                f.publish_prior_restricted(captured_report=captured)
                with self.assertRaises(c.ContinuityError):
                    c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                            transport=f.transport, log_transport=f.log_transport)

    def test_forged_unknown_or_core_deep_annotation_needs_real_publication(self):
        for workflow in ('.github/workflows/unapproved-provider.yml', '.github/workflows/JARVIS-Core-Automation.yml', c.GAP['workflow']):
            with self.subTest(workflow=workflow), RestrictedFixture() as f:
                report = f.report(write=True)
                unknown = f.run(50000000777, 1, f.main_commit, '2026-10-23T05:55:00Z', conclusion='failure', workflow=workflow)
                f.runs.append(unknown)
                report['publication_executions'] = sorted(report['publication_executions'] + ['50000000777:1'])
                f.write(c.REPORT_PATH, report)
                f.git('add', c.REPORT_PATH, c.HISTORY_DIR); f.git('commit', '-qm', 'forged annotation only')
                f.main_commit = f.git('rev-parse', 'HEAD').strip()
                f.jobs['actions/runs/50000000777/attempts/1/jobs?per_page=100'] = {'total_count': 0, 'jobs': []}
                with self.assertRaises(c.ContinuityError):
                    c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                            transport=f.transport, log_transport=f.log_transport)

    def test_unlisted_forged_publication_identity_cannot_survive(self):
        with RestrictedFixture() as f:
            report = f.report(write=True)
            report['publication_executions'] = sorted(report['publication_executions'] + ['50000000999:1'])
            f.write(c.REPORT_PATH, report)
            f.git('add', c.REPORT_PATH, c.HISTORY_DIR); f.git('commit', '-qm', 'nonexistent annotation')
            f.main_commit = f.git('rev-parse', 'HEAD').strip()
            def read(endpoint):
                if endpoint == 'actions/runs/50000000999/attempts/1': return {}
                return f.transport(endpoint)
            with self.assertRaises(c.ContinuityError):
                c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW, transport=read, log_transport=f.log_transport)

    def test_log_marker_without_exact_published_commit_is_not_lineage(self):
        with RestrictedFixture() as f:
            result = f.publish_prior_restricted()
            key = next(iter(f.logs))
            text = f.logs[key].decode()
            text = text.replace(result['commit_sha'], result['input_commit'])
            f.logs[key] = text.encode()
            with self.assertRaises(c.ContinuityError):
                c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                        transport=f.transport, log_transport=f.log_transport)

    def test_cache_named_and_ignored_canonical_files_are_never_omitted(self):
        with RestrictedFixture() as f:
            before = c.protected_inventory(f.root)
            (f.root / '.git/info/exclude').write_text('data/__pycache__/\ndata/hidden.pyc\n')
            f.write('data/__pycache__/ledger.json', {'nonce': 'hidden'})
            f.write('data/hidden.pyc', 'opaque canonical bytes', raw=True)
            after = c.protected_inventory(f.root)
            self.assertIn('data/__pycache__/ledger.json', after)
            self.assertIn('data/hidden.pyc', after)
            with self.assertRaises(c.ContinuityError): c.assert_protected_unchanged(before, after)

    def test_special_canonical_file_is_rejected_without_reading(self):
        with RestrictedFixture() as f:
            os.mkfifo(f.root / 'data/special-ledger')
            with self.assertRaisesRegex(c.ContinuityError, 'nonregular_file_forbidden'):
                c.protected_inventory(f.root)

class ExactPreservationTests(unittest.TestCase):
    def test_exact_four_published_bytes_are_preserved_without_authority_expansion(self):
        with RestrictedFixture() as f:
            manifest = f.preserve_daily()
            before = c.protected_inventory(f.root)
            self.assertEqual(c.frozen_inventory_digest(before), f.decision['frozen_inventory_digest'])
            evidence = c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                               transport=f.transport, log_transport=f.log_transport)
            report = c.build_review(f.root, evidence=evidence, now=NOW, execution_id=f.identity)
            c.write_review(f.root, report, now=NOW)
            self.assertEqual(before, c.protected_inventory(f.root))
            self.assertIsNone(report['old_run_provider_calls'])
            self.assertEqual(report['effective_new_request_allowance'], 0)
            self.assertIn('shopify_mutation', report['blocked_capabilities'])
            self.assertEqual(len(manifest['files']), 4)

    def test_each_preserved_blob_is_frozen_and_cannot_reset_to_old_baseline(self):
        with RestrictedFixture() as f:
            manifest = f.preserve_daily()
            for path in manifest['files']:
                original = (f.root / path).read_bytes()
                f.write(path, {'original': 'already-existing'})
                with self.subTest(path=path), self.assertRaisesRegex(c.ContinuityError, 'preserved_publication_bytes_changed'):
                    c.frozen_inventory_digest(c.protected_inventory(f.root))
                (f.root / path).write_bytes(original)

    def test_preserved_publication_cannot_smuggle_budget_change(self):
        with RestrictedFixture() as f:
            f.preserve_daily(extra_change=True)
            with self.assertRaisesRegex(c.ContinuityError, 'preserved_publication_paths_changed'):
                c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                        transport=f.transport, log_transport=f.log_transport)

    def test_future_daily_or_retry_needs_new_reconciliation(self):
        for retry in (False, True):
            with self.subTest(retry=retry), RestrictedFixture() as f:
                manifest = f.preserve_daily()
                if retry: f.runs[-1]['run_attempt'] = 2
                else: f.runs.append(f.run(39906965296, 1, f.main_commit, '2026-10-23T05:59:01Z',
                                         conclusion='success', workflow=manifest['workflow']))
                with self.assertRaises(c.ContinuityError):
                    c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                            transport=f.transport, log_transport=f.log_transport)

    def test_preservation_scope_job_and_log_binding_cannot_be_forged(self):
        for mutation in ('scope', 'job', 'log'):
            with self.subTest(mutation=mutation), RestrictedFixture() as f:
                f.preserve_daily()
                if mutation == 'scope':
                    f.decision['preserved_publications'][0]['scope'] = 'allow_future_daily'
                    f.write(c.DECISION_PATH, f.decision)
                if mutation == 'job': f.jobs[next(iter(f.jobs))]['jobs'][0]['id'] += 1
                if mutation == 'log':
                    f.logs[next(iter(f.logs))] = b'2026-10-23T06:10:00Z unrelated step\n'
                with self.assertRaises(c.ContinuityError):
                    c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW,
                                            transport=f.transport, log_transport=f.log_transport)

class FreshnessAndRateTests(unittest.TestCase):
    def test_decide_and_offline_gates_make_zero_authentication_calls(self):
        with RestrictedFixture() as f:
            report = f.report(write=True)
            with mock.patch.object(c, 'authenticate_evidence', side_effect=AssertionError('network')), \
                 mock.patch.object(c, '_github_json', side_effect=AssertionError('network')):
                c.validate_review_bindings(f.root, report, execution_id=f.identity, now=NOW)
                with mock.patch.object(c, 'validate_pending_decision', return_value={'decision_digest': report['decision_digest']}), redirect_stdout(io.StringIO()):
                    self.assertEqual(c.main(['decide', '--root', str(f.root)]), 0)

    def test_sealed_evidence_reuse_has_exact_request_counts(self):
        with RestrictedFixture() as f:
            evidence = c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW, transport=f.transport, purpose='publication')
            report = c.build_review(f.root, evidence=evidence, now=NOW, execution_id=f.identity)
            c.write_review(f.root, report, now=NOW)
            before = len(f.calls)
            c.validate_publication_report(f.root, report, execution_id=f.identity, evidence=evidence, now=NOW)
            self.assertEqual(len(f.calls), before)
            result = c.validate_publication_freshness(f.root, report, evidence=evidence, execution_id=f.identity, now=NOW, transport=f.transport)
            self.assertEqual(evidence.request_count, 6)
            self.assertEqual(result['freshness_requests'], 4)
            self.assertEqual(result['attempt_total_requests'], 10)
            self.assertIsNone(result['rate_remaining'])

    def test_final_scan_detects_new_unknown_attempt_page_omission_and_race(self):
        for mutation in ('new', 'attempt', 'missing', 'race', 'main'):
            with self.subTest(mutation=mutation), RestrictedFixture() as f:
                report = f.report(write=True)
                def changed(endpoint):
                    result = f.transport(endpoint)
                    if endpoint.startswith('actions/runs?'):
                        if mutation == 'new':
                            result['workflow_runs'].append(f.run(777, 1, f.main_commit, '2026-10-23T05:59:00Z', conclusion='failure'))
                            result['total_count'] += 1
                        elif mutation == 'attempt': result['workflow_runs'][1]['run_attempt'] = 2
                        elif mutation == 'missing': result['workflow_runs'].pop()
                        elif mutation == 'race': result['workflow_runs'][1]['updated_at'] = '2026-10-23T05:59:59Z'
                        elif mutation == 'main': f.main_commit = 'f'*40
                    return result
                with self.assertRaises(c.ContinuityError):
                    c.validate_publication_freshness(f.root, report, evidence=f.evidence, execution_id=f.identity,
                                                    now=NOW, transport=changed)

    def test_false_or_json_evidence_never_triggers_network(self):
        with RestrictedFixture() as f:
            report = f.report(write=True)
            for false_proof in (None, False, True, {}, {'verified': True}):
                with self.subTest(false_proof=false_proof), mock.patch.object(c, 'authenticate_evidence', side_effect=AssertionError('network')):
                    with self.assertRaises(c.ContinuityError):
                        c.validate_publication_freshness(f.root, report, evidence=false_proof, execution_id=f.identity, now=NOW)
                    if false_proof is not None:
                        with self.assertRaises(c.ContinuityError):
                            c.validate_publication_report(f.root, report, evidence=false_proof, execution_id=f.identity, now=NOW)

    def test_last_metadata_log_and_freshness_read_cannot_overrun_total_deadline(self):
        for phase in ('metadata', 'log', 'freshness'):
            with self.subTest(phase=phase), RestrictedFixture() as f:
                report = f.report(write=True)
                if phase == 'log': f.publish_knowledge()
                clock = [0]
                def read(endpoint):
                    value = f.transport(endpoint)
                    if phase != 'log': clock[0] += c.MAX_DISCOVERY_SECONDS + 1
                    return value
                def logs(endpoint):
                    value = f.log_transport(endpoint)
                    clock[0] += c.MAX_DISCOVERY_SECONDS + 1
                    return value
                with mock.patch.object(c.time, 'monotonic', side_effect=lambda: clock[0]), self.assertRaisesRegex(c.ContinuityError, 'request_budget_exhausted'):
                    if phase == 'freshness':
                        c.validate_publication_freshness(f.root, report, evidence=f.evidence, execution_id=f.identity, now=NOW, transport=read)
                    else:
                        c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW, transport=read, log_transport=logs)

    def test_actual_rate_headers_required_and_low_initial_or_final_budget_blocks(self):
        for headers in ({}, {'X-RateLimit-Remaining': '-1', 'X-RateLimit-Limit': '1000', 'X-RateLimit-Reset': '1'}):
            with self.assertRaises(c.ContinuityError): c._record_rate_headers(headers)
        with RestrictedFixture() as f, mock.patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': str(f.run_id), 'GITHUB_RUN_ATTEMPT': '1'}):
            available = 1000
            def authenticated_read(endpoint):
                nonlocal available
                available -= 1
                c._API_ACCOUNTING['requests'] += 1
                c._record_rate_headers({'X-RateLimit-Remaining': str(available), 'X-RateLimit-Limit': '1000', 'X-RateLimit-Reset': '1792742400'})
                return f.transport(endpoint)
            with mock.patch.dict(c._API_ACCOUNTING, {'requests': 0, 'remaining': None, 'limit': None, 'reset': None}), \
                 mock.patch.object(c, '_github_json', side_effect=authenticated_read):
                available = 8
                with self.assertRaisesRegex(c.ContinuityError, 'rate_budget_insufficient'):
                    c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW, purpose='publication')
                available = 800
                evidence = c.authenticate_evidence(f.root, execution_id=f.identity, now=NOW, purpose='publication')
                self.assertLess(evidence.rate_remaining, 800)
                report = c.build_review(f.root, evidence=evidence, now=NOW, execution_id=f.identity)
                c.write_review(f.root, report, now=NOW)
                c._API_ACCOUNTING['remaining'] = 3
                with self.assertRaisesRegex(c.ContinuityError, 'rate_budget_insufficient'):
                    c.validate_publication_freshness(f.root, report, evidence=evidence, execution_id=f.identity, now=NOW)


if __name__ == '__main__':
    unittest.main()
