"""Offline tests only: all metadata/gh calls mocked; dummy account and temp files."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from unittest.mock import Mock, patch
import restore_typesafe_receipt as r

IDENTITY = (hashlib.sha256(b'dummy-offline-key').hexdigest(), 'dummy-org')
REPO = 'dummy/repo'
PROTECTED = 'a' * 40
LEGACY = 'b' * 40
CLASSIFICATIONS = {PROTECTED: 'protected', LEGACY: 'legacy'}

def run(identifier=10, workflow='JARVIS-Deep-Analysis.yml'):
    return {'id': identifier, 'run_attempt': 1, 'name': 'Deep' if workflow.startswith('JARVIS') else 'Copy',
            'path': '.github/workflows/' + workflow, 'status': 'completed', 'conclusion': 'failure',
            'head_branch': 'main', 'head_sha': PROTECTED,
            'head_repository': {'id': 5, 'full_name': REPO},
            'created_at': '2026-09-02T00:00:00Z'}

def artifact(identifier=10):
    return {'id': identifier + 100, 'name': f'typesafe-budget-receipt-{identifier}-1',
            'expired': False, 'created_at': f'2026-09-03T00:00:{identifier:02}Z',
            'workflow_run': {'id': identifier, 'head_branch': 'main', 'head_repository_id': 5}}

def state(tokens=100, runs=()):
    budgets = {}
    for item in runs:
        scope = f"{item['name']}:{item['id']}:{item['run_attempt']}"
        budgets[scope] = {**r.shared.DEFAULTS, 'calls': 1, 'charged_input_tokens': tokens,
                         'reserved_input_tokens': 0, 'input_tokens': 1, 'output_tokens': 1,
                         'call_log': [{'ok': True}], 'stopped': ''}
    return {'schema': 1, 'key_sha256': IDENTITY[0], 'org_id': IDENTITY[1],
            'account_limit_usd': 5, 'account_charged_tokens': tokens, 'stopped': '',
            'cache': {}, 'versions': {}, 'workflows': budgets}

def zipped(content, name=r.FILENAME, mode=None, extra=False):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        info = zipfile.ZipInfo(name)
        if mode is not None:
            info.create_system = 3
            info.external_attr = mode << 16
        archive.writestr(info, content)
        if extra:
            archive.writestr('unexpected.txt', 'extra')
    return output.getvalue()

class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = self.root / r.FILENAME
        self.meta = {'repo': REPO, 'protected_release_sha': r.RELEASE_SHA,
                     'head_classifications': CLASSIFICATIONS.copy(),
                     'runs': [run()], 'artifacts': [artifact()]}
        # Even if a developer has real credentials, tests see only dummy values.
        env = {'TYPESAFE_API_KEY': 'dummy-offline-key', 'TYPESAFE_ORG_ID': 'dummy-org',
               'GH_TOKEN': 'dummy-not-a-real-token', 'GITHUB_REPOSITORY': REPO, 'GITHUB_RUN_ID': '99'}
        self.environment = patch.dict(os.environ, env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.process = patch.object(r.subprocess, 'run', side_effect=AssertionError('No real commands in tests'))
        self.process_mock = self.process.start()
        self.addCleanup(self.process.stop)
    def save(self, value, path=None):
        target = path or self.ledger
        target.write_text(json.dumps(value), encoding='utf-8')
        return target
    def restore(self, value=None):
        return r.restore(self.ledger, REPO, '99', IDENTITY, self.meta,
                         lambda a: copy.deepcopy(value if value is not None else state(200, [run()])))
    def test_newest_failed_receipt_restored(self):
        self.save(state(10))
        result = self.restore()
        self.assertEqual(result['account_charged_tokens'], 200)
        self.assertEqual(r.shared.read(self.ledger), result)
    def test_higher_main_never_replaced(self):
        main = state(300, [run()])
        self.save(main)
        self.assertEqual(self.restore(state(200, [run()])), main)
        self.assertEqual(r.shared.read(self.ledger), main)
    def test_missing_receipt_denies_without_reset(self):
        main = state(100)
        self.save(main)
        self.meta['artifacts'] = []
        with self.assertRaises(r.RestoreDenied):
            self.restore()
        self.assertEqual(r.shared.read(self.ledger), main)
    def test_matching_main_scope_allows_missing_receipt(self):
        main = state(200, [run()])
        self.save(main)
        self.meta['artifacts'] = []
        self.assertEqual(self.restore(), main)
    def test_missing_older_receipt_not_excused_by_newer_restore(self):
        self.meta['runs'].append(run(11, 'shopify-listing-copy.yml'))
        self.meta['artifacts'] = [artifact(11)]
        with self.assertRaises(r.RestoreDenied):
            self.restore(state(200, self.meta['runs']))
        self.assertFalse(self.ledger.exists())
    def test_wrong_account_and_schema_rejected(self):
        for field, value in [('key_sha256', '0' * 64), ('org_id', 'another-org'),
                             ('schema', 2), ('account_charged_tokens', -1), ('account_charged_tokens', float('nan'))]:
            candidate = state(200, [run()]); candidate[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(r.RestoreDenied):
                self.restore(candidate)
    def test_branch_workflow_repo_and_current_filtered(self):
        for field, value in [('head_branch', 'feature'), ('path', '.github/workflows/other.yml'),
                             ('head_repository', {'id': 6, 'full_name': 'fork/repo'}), ('id', 99), ('status', 'in_progress')]:
            item = run(); item[field] = value
            self.assertEqual(r.eligible_runs([item], REPO, '99', CLASSIFICATIONS), {})
        item = run(); item['head_sha'] = LEGACY
        self.assertEqual(r.eligible_runs([item], REPO, '99', CLASSIFICATIONS), {})
    def test_exact_artifact_binding_and_newest_selection(self):
        runs = {(10, 1): run(), (11, 1): run(11, 'shopify-listing-copy.yml')}
        self.assertEqual([a['id'] for a in r.select_artifacts([artifact(), artifact(11)], runs)], [111, 110])
        for mutate in (lambda a: a.update(name='typesafe-budget-receipt-10-1-extra'),
                       lambda a: a.update(name='typesafe-budget-receipt-10-2'),
                       lambda a: a.update(expired=True),
                       lambda a: a['workflow_run'].update(head_branch='feature'),
                       lambda a: a['workflow_run'].update(head_repository_id=6)):
            item = artifact(); mutate(item)
            self.assertEqual(r.select_artifacts([item], runs), [])
    def test_counter_regression_blocks(self):
        main = state(100, [run()]); self.save(main)
        candidate = state(200, [run()]); candidate['workflows']['Deep:10:1']['calls'] = 0
        with self.assertRaises(r.RestoreDenied):
            self.restore(candidate)
        self.assertEqual(r.shared.read(self.ledger), main)
    def test_newest_receipt_lower_than_older_denies(self):
        self.meta['runs'].append(run(11, 'shopify-listing-copy.yml'))
        self.meta['artifacts'].append(artifact(11))
        with self.assertRaises(r.RestoreDenied):
            r.restore(self.ledger, REPO, '99', IDENTITY, self.meta,
                      lambda a: state(100 if a['id'] == 111 else 200, self.meta['runs']))
    def test_receipt_requires_matching_workflow_scope(self):
        with self.assertRaises(r.RestoreDenied):
            self.restore(state(200))
    def test_safe_zip_rejects_traversal_symlink_extra_and_nested(self):
        for raw in (zipped(b'{}', '../' + r.FILENAME), zipped(b'{}', 'data/' + r.FILENAME),
                    zipped(b'{}', mode=stat.S_IFLNK | 0o777), zipped(b'{}', extra=True),
                    zipped(b'{}', 'C:\\' + r.FILENAME)):
            with self.assertRaises(r.RestoreDenied):
                r.validate_zip(raw)
        self.assertEqual(r.validate_zip(zipped(b'{}')), b'{}')
    def test_download_only_expected_file_and_argument_arrays(self):
        content = json.dumps(state(200, [run()])).encode()
        calls = []
        gh = Mock(repo=REPO)
        def binary(*args):
            calls.append(args)
            if args[0] == 'api':
                return zipped(content)
            folder = Path(args[args.index('--dir') + 1])
            (folder / r.FILENAME).write_bytes(content)
            return b''
        gh.binary.side_effect = binary
        self.assertEqual(r.download_receipt(artifact(), gh, IDENTITY)['account_charged_tokens'], 200)
        self.assertEqual(calls[1][:6], ('run', 'download', '10', '--repo', REPO, '--name'))
        self.assertNotIn(os.environ['GH_TOKEN'], str(calls))
        def unsafe(*args):
            if args[0] == 'api': return zipped(content)
            folder = Path(args[args.index('--dir') + 1])
            (folder / r.FILENAME).write_bytes(content)
            (folder / 'extra').write_text('unexpected')
            return b''
        gh.binary.side_effect = unsafe
        with self.assertRaises(r.RestoreDenied):
            r.download_receipt(artifact(), gh, IDENTITY)
    def test_bad_zip_never_extracted(self):
        gh = Mock(repo=REPO)
        gh.binary.return_value = zipped(b'{}', '../escape')
        with self.assertRaises(r.RestoreDenied):
            r.download_receipt(artifact(), gh, IDENTITY)
        self.assertEqual(gh.binary.call_count, 1)
    def test_shared_contract_and_duplicate_json_rejected(self):
        self.save(state())
        with patch.object(r.shared, 'read', side_effect=r.shared.SafetyStop('ledger_corrupt')):
            with self.assertRaises(r.shared.SafetyStop): r.read_ledger(self.ledger, IDENTITY)
        self.ledger.write_text('{"schema":1,"schema":1}', encoding='utf-8')
        with self.assertRaises(r.RestoreDenied): r.read_ledger(self.ledger, IDENTITY)
    def test_gh_metadata_commands_mocked_and_paginated(self):
        gh = r.Gh(REPO)
        fake = Mock(returncode=0, stdout=b'[{"total_count":0,"artifacts":[]}]')
        with patch.object(r.subprocess, 'run', return_value=fake) as call:
            self.assertEqual(gh.pages('repos/dummy/repo/actions/artifacts?per_page=100', 'artifacts'), [])
        args = call.call_args.args[0]
        self.assertIsInstance(args, list)
        self.assertEqual(args[:4], ['gh', 'api', '--paginate', '--slurp'])
        self.assertNotIn('dummy-not-a-real-token', str(call.call_args))
        with patch.object(gh, 'json', return_value=[{'total_count': 2, 'artifacts': []}]):
            with self.assertRaises(r.RestoreDenied): gh.pages('fixture', 'artifacts')
    def test_cli_offline_no_subprocess_and_fixed_output(self):
        receipt = self.save(state(200, [run()]), self.root / 'receipt.json')
        self.meta['receipts'] = {'110': str(receipt)}
        fixture = self.save(self.meta, self.root / 'metadata.json')
        args = ['--offline', '--metadata', str(fixture), '--ledger', str(self.ledger)]
        output = io.StringIO()
        with redirect_stdout(output): self.assertEqual(r.main(args), 0)
        self.assertEqual(output.getvalue(), r.READY + '\n')
        self.meta['artifacts'] = []; self.save(self.meta, fixture)
        self.ledger.unlink()
        output = io.StringIO()
        with redirect_stdout(output): self.assertEqual(r.main(args), 1)
        self.assertEqual(output.getvalue(), r.LOCAL_ONLY + '\n')
        self.process_mock.assert_not_called()
    def test_query_failure_fixed_marker_no_credentials_or_url(self):
        output = io.StringIO()
        with patch.object(r, 'metadata', side_effect=RuntimeError('dummy-not-a-real-token https://private.example')), redirect_stdout(output):
            self.assertEqual(r.main(['--ledger', str(self.ledger)]), 1)
        self.assertEqual(output.getvalue(), r.LOCAL_ONLY + '\n')
    def test_metadata_queries_only_consumers(self):
        gh = Mock(repo=REPO)
        gh.json.return_value = {'full_name': REPO}
        gh.pages.return_value = []
        with patch.object(r, 'classify_ancestry', return_value='protected'): r.metadata(gh)
        paths = [call.args[0] for call in gh.pages.call_args_list]
        self.assertEqual(len(paths), 3)
        self.assertTrue(all('status=completed&branch=main' in p for p in paths[:2]))
        self.assertTrue(any('JARVIS-Deep-Analysis.yml' in p for p in paths))
        self.assertTrue(any('shopify-listing-copy.yml' in p for p in paths))

    def test_current_rerun_prior_attempt_missing_receipt_denies(self):
        self.meta['artifacts'] = []
        with self.assertRaises(r.RestoreDenied):
            r.restore(self.ledger, REPO, '10', IDENTITY, self.meta, Mock(), current_run_attempt=2)
        self.assertFalse(self.ledger.exists())
    def test_current_rerun_attempt_metadata_missing_denies(self):
        self.meta['runs'] = []; self.meta['artifacts'] = []
        with self.assertRaises(r.RestoreDenied):
            r.restore(self.ledger, REPO, '10', IDENTITY, self.meta, Mock(), current_run_attempt=2)
    def test_current_rerun_prior_stop_persists(self):
        stopped = state(200, [run()]); stopped['stopped'] = 'request_in_flight_or_ambiguous'
        r.restore(self.ledger, REPO, '10', IDENTITY, self.meta, lambda _: stopped, current_run_attempt=2)
        self.assertEqual(r.shared.read(self.ledger)['stopped'], 'request_in_flight_or_ambiguous')
    def test_all_completed_attempts_require_receipts(self):
        second = run(); second['run_attempt'] = 2
        self.meta['runs'].append(second)
        receipt2 = artifact(); receipt2['id'] = 120; receipt2['name'] = 'typesafe-budget-receipt-10-2'
        self.meta['artifacts'] = [receipt2]
        with self.assertRaises(r.RestoreDenied):
            self.restore(state(300, self.meta['runs']))
    def test_newest_higher_total_missing_older_scope_denies(self):
        self.meta['runs'].append(run(11, 'shopify-listing-copy.yml'))
        self.meta['artifacts'].append(artifact(11))
        older = state(100, [run()])
        newest = state(300, [self.meta['runs'][1]])
        with self.assertRaises(r.RestoreDenied):
            r.restore(self.ledger, REPO, '99', IDENTITY, self.meta,
                      lambda a: newest if a['id'] == 111 else older)
        self.assertFalse(self.ledger.exists())
    def test_newest_higher_total_missing_older_stop_limits_versions_history_denies(self):
        self.meta['runs'].append(run(11, 'shopify-listing-copy.yml'))
        self.meta['artifacts'].append(artifact(11))
        for change in ('global_stop', 'workflow_stop', 'limit', 'version', 'history', 'counter'):
            older = state(100, [run()]); newest = state(300, self.meta['runs'])
            if change == 'global_stop': older['stopped'] = 'transport_failure'
            elif change == 'workflow_stop': older['workflows']['Deep:10:1']['stopped'] = 'pre_request_budget_denied'
            elif change == 'limit': older['account_limit_usd'] = 2
            elif change == 'version': older['versions']['questions:q1'] = 'bound'
            elif change == 'history': newest['workflows']['Deep:10:1']['call_log'] = []
            else: newest['workflows']['Deep:10:1']['charged_input_tokens'] = 50
            with self.subTest(change=change), self.assertRaises(r.RestoreDenied):
                r.restore(self.ledger, REPO, '99', IDENTITY, self.meta,
                          lambda a: newest if a['id'] == 111 else older)
    def test_metadata_expands_current_in_progress_and_prior_attempts(self):
        first = run(); second = run(); second['run_attempt'] = 2
        gh = Mock(repo=REPO); gh.pages.return_value = []
        gh.json.side_effect = [{'full_name': REPO}, first, second]
        with patch.object(r, 'classify_ancestry', return_value='protected'):
            result = r.metadata(gh, '10', 3)
        self.assertEqual({(item['id'], item['run_attempt']) for item in result['runs']}, {(10, 1), (10, 2)})
        paths = [call.args[1] for call in gh.json.call_args_list]
        self.assertIn('repos/dummy/repo/actions/runs/10/attempts/1', paths)
        self.assertIn('repos/dummy/repo/actions/runs/10/attempts/2', paths)
    def test_metadata_expands_completed_latest_attempt(self):
        latest = run(); latest['run_attempt'] = 2
        gh = Mock(repo=REPO)
        gh.json.side_effect = [{'full_name': REPO}, run()]
        gh.pages.side_effect = [[latest], [], [artifact()]]
        with patch.object(r, 'classify_ancestry', return_value='protected'):
            result = r.metadata(gh)
        self.assertEqual(len(result['runs']), 2)
        self.assertEqual(len(r.eligible_runs(result['runs'], REPO, '99', result['head_classifications'])), 2)

    def deny_unchanged(self, current_id='99', current_attempt=1):
        self.save(state(100))
        before = self.ledger.read_bytes()
        loader = Mock(side_effect=AssertionError('No receipt should be loaded'))
        with self.assertRaises(r.RestoreDenied):
            r.restore(self.ledger, REPO, current_id, IDENTITY, self.meta, loader, current_attempt)
        self.assertEqual(self.ledger.read_bytes(), before)
        loader.assert_not_called()

    def test_legacy_after_local_introduction_no_artifact_unchanged(self):
        item = self.meta['runs'][0]
        item.update(head_sha=LEGACY, created_at='2026-10-04T10:00:00Z',
                    run_started_at='2026-10-04T10:01:00Z')
        self.meta['artifacts'] = []
        self.save(state(100)); before = self.ledger.read_bytes()
        loader = Mock(side_effect=AssertionError('Legacy must not load receipts'))
        result = r.restore(self.ledger, REPO, '99', IDENTITY, self.meta, loader)
        self.assertEqual(result, state(100))
        self.assertEqual(self.ledger.read_bytes(), before)
        loader.assert_not_called()

    def test_protected_before_local_introduction_missing_denies_unchanged(self):
        self.meta['runs'][0].update(created_at='2026-08-01T00:00:00Z',
                                    run_started_at='2026-08-01T00:00:00Z')
        self.meta['artifacts'] = []
        self.deny_unchanged()

    def test_malformed_head_shas_deny_unchanged(self):
        for sha in (None, '', 'a' * 39, 'a' * 41, 'A' * 40, 'g' * 40, '--help'):
            with self.subTest(sha=sha):
                self.meta['runs'][0]['head_sha'] = sha
                self.deny_unchanged()

    def test_absent_unknown_and_default_false_classification_deny_unchanged(self):
        for classifications in (None, {}, {PROTECTED: False}, {PROTECTED: None},
                                {PROTECTED: 'unknown'}, {LEGACY: 'legacy'}):
            with self.subTest(classifications=classifications):
                self.meta['head_classifications'] = classifications
                self.deny_unchanged()

    def test_release_pin_missing_or_changed_denies_unchanged(self):
        for release in (None, LEGACY, r.RELEASE_SHA[:7]):
            with self.subTest(release=release):
                self.meta['protected_release_sha'] = release
                self.deny_unchanged()

    def ancestry_results(self, exit_code=0):
        return [Mock(returncode=0, stdout=b'false\n', stderr=b''),
                Mock(returncode=0, stdout=b'commit\n', stderr=b''),
                Mock(returncode=0, stdout=b'commit\n', stderr=b''),
                Mock(returncode=0, stdout=b'full-history\n', stderr=b''),
                Mock(returncode=exit_code, stdout=b'', stderr=b'')]

    def test_online_ancestry_verified_zero_and_one_and_readonly_commands(self):
        for code, expected in ((0, 'protected'), (1, 'legacy')):
            with self.subTest(code=code), patch.object(r.subprocess, 'run', side_effect=self.ancestry_results(code)) as commands:
                self.assertEqual(r.classify_ancestry(PROTECTED), expected)
                args = [call.args[0] for call in commands.call_args_list]
                for command in commands.call_args_list:
                    self.assertEqual(command.kwargs['env']['GIT_NO_LAZY_FETCH'], '1')
                    self.assertEqual(command.kwargs['env']['GIT_OPTIONAL_LOCKS'], '0')
                self.assertEqual(args, [
                    ['git', '--no-replace-objects', 'rev-parse', '--is-shallow-repository'],
                    ['git', '--no-replace-objects', 'cat-file', '-t', r.RELEASE_SHA],
                    ['git', '--no-replace-objects', 'cat-file', '-t', PROTECTED],
                    ['git', '--no-replace-objects', 'rev-list', '--missing=error', r.RELEASE_SHA, PROTECTED],
                    ['git', '--no-replace-objects', 'merge-base', '--is-ancestor', r.RELEASE_SHA, PROTECTED]])

    def test_ancestry_errors_never_classify_legacy(self):
        for code, stderr in ((2, b''), (128, b'fatal'), (1, b'error')):
            results = self.ancestry_results(code); results[-1].stderr = stderr
            with self.subTest(code=code, stderr=stderr), patch.object(r.subprocess, 'run', side_effect=results):
                with self.assertRaises(r.RestoreDenied): r.classify_ancestry(PROTECTED)

    def test_shallow_unknown_commit_and_missing_history_deny(self):
        for index, code, output in ((0, 0, b'true\n'), (0, 128, b''),
                                    (0, 0, b''), (1, 128, b''), (2, 128, b''),
                                    (2, 0, b'tag\n'), (3, 128, b'')):
            results = self.ancestry_results(1)
            results[index] = Mock(returncode=code, stdout=output, stderr=b'')
            with self.subTest(index=index, code=code, output=output), patch.object(r.subprocess, 'run', side_effect=results) as commands:
                with self.assertRaises(r.RestoreDenied): r.classify_ancestry(LEGACY)
                self.assertEqual(commands.call_count, index + 1)

    def test_malformed_online_sha_never_runs_git(self):
        for sha in ('short', None, '--all', 'z' * 40):
            with self.subTest(sha=sha), self.assertRaises(r.RestoreDenied): r.classify_ancestry(sha)
        self.process_mock.assert_not_called()

    def test_online_ancestry_error_cli_denies_preserving_ledger_bytes(self):
        self.save(state(100)); before = self.ledger.read_bytes()
        gh = Mock(repo=REPO); gh.json.return_value = {'full_name': REPO}
        gh.pages.side_effect = [[run()], [], []]
        output = io.StringIO()
        with patch.object(r, 'Gh', return_value=gh), patch.object(r.subprocess, 'run', side_effect=RuntimeError('git unavailable')), redirect_stdout(output):
            self.assertEqual(r.main(['--ledger', str(self.ledger)]), 1)
        self.assertEqual(output.getvalue(), r.LOCAL_ONLY + '\n')
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_mixed_histories_only_protected_scopes_required(self):
        legacy = run(11, 'shopify-listing-copy.yml')
        legacy.update(head_sha=LEGACY, created_at='2026-10-04T11:00:00Z')
        self.meta['runs'].append(legacy)
        self.meta['runs'][0]['created_at'] = '2026-08-01T00:00:00Z'
        self.assertEqual(self.restore()['account_charged_tokens'], 200)
        self.assertNotIn('Copy:11:1', r.shared.read(self.ledger)['workflows'])
        self.ledger.unlink(); self.meta['artifacts'] = []
        self.deny_unchanged()

    def test_metadata_discovers_attempts_before_cutover_and_classifies_own_heads(self):
        prior = run(); prior['head_sha'] = PROTECTED
        latest = run(); latest.update(run_attempt=2, head_sha=LEGACY,
                                     created_at='2026-08-01T00:00:00Z')
        gh = Mock(repo=REPO); gh.json.side_effect = [{'full_name': REPO}, prior]
        gh.pages.side_effect = [[latest], [], []]
        with patch.object(r, 'classify_ancestry', side_effect=lambda sha: CLASSIFICATIONS[sha]) as ancestry:
            self.meta = r.metadata(gh)
        self.assertEqual(set(call.args[0] for call in ancestry.call_args_list), {LEGACY, PROTECTED})
        self.assertEqual(self.meta['head_classifications'], CLASSIFICATIONS)
        self.assertEqual(set(r.eligible_runs(self.meta['runs'], REPO, '99', self.meta['head_classifications'])), {(10, 1)})
        self.deny_unchanged()

    def test_legacy_prior_protected_latest_requires_only_own_receipt(self):
        self.meta['runs'][0]['head_sha'] = LEGACY
        latest = run(); latest['run_attempt'] = 2
        self.meta['runs'].append(latest)
        receipt = artifact(); receipt['name'] = 'typesafe-budget-receipt-10-2'
        self.meta['artifacts'] = [receipt]
        result = self.restore(state(200, [latest]))
        self.assertEqual(set(result['workflows']), {'Deep:10:2'})

    def test_missing_attempt_metadata_denies_even_for_legacy_early_latest(self):
        self.meta['runs'][0].update(run_attempt=2, head_sha=LEGACY,
                                   created_at='2026-08-01T00:00:00Z')
        self.meta['artifacts'] = []
        self.deny_unchanged()

    def test_current_legacy_rerun_requires_metadata_but_not_fake_receipt(self):
        self.meta['runs'][0]['head_sha'] = LEGACY
        self.meta['artifacts'] = []
        self.save(state(100)); before = self.ledger.read_bytes()
        loader = Mock()
        self.assertEqual(r.restore(self.ledger, REPO, '10', IDENTITY, self.meta, loader, 2), state(100))
        self.assertEqual(self.ledger.read_bytes(), before)
        loader.assert_not_called()
        self.meta['runs'] = []
        self.deny_unchanged('10', 2)

    def test_current_retry_incomplete_or_wrong_repo_metadata_denies(self):
        for field, value in (('status', 'in_progress'), ('head_branch', 'feature'),
                             ('head_repository', {'full_name': 'fork/repo'}),
                             ('path', '.github/workflows/other.yml')):
            self.meta['runs'] = [run()]
            self.meta['runs'][0][field] = value
            with self.subTest(field=field): self.deny_unchanged('10', 2)

if __name__ == '__main__':
    unittest.main()
