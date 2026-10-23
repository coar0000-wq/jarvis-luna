#!/usr/bin/env python3
"""Isolated fail-closed fixtures for graph expansion of the publish transaction."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_artifact_graph as graph

ROOT = Path(__file__).resolve().parents[1]


class PublishContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT.parent, prefix='publish-graph-contract-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wrapper = (ROOT / 'scripts/publish_transaction.py').read_text(encoding='utf-8')
        self.policy = json.loads((ROOT / 'config/publish_policy.json').read_text(encoding='utf-8'))
        self.action = (ROOT / '.github/actions/publish/action.yml').read_text(encoding='utf-8')
        for command in graph._RUNTIME_CHAIN + graph._COMMERCE_CHAIN + [["scripts/check_release_quality.py"], ["scripts/build_daiso_candidate_comparison.py"]]:
            path = self.root / command[0]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# isolated fixture\n', encoding='utf-8')
        (self.root / 'config').mkdir()
        self.write()
        self.patch = patch.object(graph, 'ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write(self, wrapper=None, policy=None):
        (self.root / 'scripts/publish_transaction.py').write_text(wrapper if wrapper is not None else self.wrapper, encoding='utf-8')
        (self.root / 'config/publish_policy.json').write_text(json.dumps(policy if policy is not None else self.policy), encoding='utf-8')

    def contract(self, action=None):
        return graph.publish_wrapper_contract(action if action is not None else self.action)

    def test_known_wrapper_has_exact_ordered_real_chains(self):
        result = self.contract()
        self.assertEqual(result['runtime_commands'], graph._RUNTIME_CHAIN)
        self.assertEqual(result['commerce_commands'], graph._COMMERCE_CHAIN)
        self.assertEqual(result['commerce_commands'][1], ['scripts/daiso/score_shopify_demand.py'])

    def test_removed_or_reordered_declared_producer_fails_closed(self):
        for key in ('runtime_commands', 'commerce_commands', 'non_operations_runtime_commands'):
            p = deepcopy(self.policy); p[key].pop(0); self.write(policy=p)
            with self.subTest(key=key), self.assertRaises(ValueError): self.contract()
        p = deepcopy(self.policy); p['runtime_commands'].reverse(); self.write(policy=p)
        with self.assertRaises(ValueError): self.contract()

    def test_action_without_actual_wrapper_invocation_fails_closed(self):
        for text in (self.action.replace('python -u scripts/publish_transaction.py', '# python -u scripts/publish_transaction.py'),
                     self.action.replace('python -u scripts/publish_transaction.py', 'python -u scripts/unknown_wrapper.py')):
            with self.subTest(text=text), self.assertRaises(ValueError): self.contract(text)

    def test_missing_function_and_unreachable_cli_fail_closed(self):
        for old, new in (('def regenerate_and_validate(', 'def missing_regeneration('),
                         ('def command(', 'def missing_command('),
                         (').run()', ').not_run()'),
                         ('if __name__ == \'__main__\':', 'if False:')):
            self.assertIn(old, self.wrapper)
            self.write(wrapper=self.wrapper.replace(old, new, 1))
            with self.subTest(old=old), self.assertRaises(ValueError): self.contract()

    def test_declared_but_not_executed_chain_fails_closed(self):
        for old, new in (("for args in self.policy['runtime_commands']:", 'for args in []:'),
                         ('if relevant or self.regenerate_dashboard:', 'if self.regenerate_dashboard:'),
                         ('if commerce:', 'if False:'),
                         ('commerce = not candidate and any(', 'commerce = any(')):
            self.assertIn(old, self.wrapper)
            self.write(wrapper=self.wrapper.replace(old, new, 1))
            with self.subTest(old=old), self.assertRaises(ValueError): self.contract()

    def test_operations_boundaries_cannot_be_removed(self):
        for old,new in (("self.reject_operations_delta(self.delta)", "None"),
                        ("self.reject_operations_delta(names - {''})", "None"),
                        ("self.verify_operations_unchanged(work, operations_before)", "None"),
                        ("for args in self.policy['non_operations_runtime_commands']:", "for args in []:")):
            self.write(wrapper=self.wrapper.replace(old,new,1))
            with self.subTest(old=old),self.assertRaises(ValueError):self.contract()

    def test_command_silent_skip_is_rejected(self):
        self.write(wrapper=self.wrapper.replace('        env = dict(os.environ', "        if args[0] == 'scripts/run_jarvis_operations.py':\n            return\n        env = dict(os.environ", 1))
        with self.assertRaises(ValueError):self.contract()

    def test_non_operations_profile_truthful_graph_coverage(self):
        p=self.profiles('data/notes.json',['data/notes.json'])
        self.assertEqual(p['publication_profile'],'non_operations')
        self.assertEqual(p['operations_producer_status'],'excluded_by_profile')
        self.assertEqual(p['producer_status'],'declared_conditional_not_execution_evidence')
        self.assertNotIn(['scripts/run_jarvis_operations.py'],p['commands'])
        self.assertEqual(p['profile_variants']['full'],graph._RUNTIME_CHAIN)

    def test_verified_profile_declares_full_chain_not_execution_proof(self):
        text=('jobs:\n  fixture:\n    env:\n      JARVIS_OPERATIONS_CONTINUITY: verified\n    steps:\n'
              '      - uses: ./.github/actions/publish\n        with:\n          paths: data/notes.json\n')
        p=graph._transaction_profiles(text,self.contract(),{})[0]
        self.assertEqual(p['publication_profile'],'full')
        self.assertEqual(p['declared_runtime_commands'],graph._RUNTIME_CHAIN)
        self.assertEqual(p['operations_producer_status'],'declared_requires_verified_continuity')

    def test_mandatory_quality_command_and_phase_cannot_be_removed(self):
        for old, new in (("for phase in ('candidate', 'final'):", "for phase in ('candidate',):"),
                         ("'scripts/check_release_quality.py'", "'scripts/not_quality.py'"),
                         ('if p.returncode:', 'if False:')):
            self.assertIn(old, self.wrapper)
            self.write(wrapper=self.wrapper.replace(old, new, 1))
            with self.subTest(old=old), self.assertRaises(ValueError): self.contract()

    def test_quality_must_validate_final_merged_root_not_caller_tree(self):
        self.write(wrapper=self.wrapper.replace("'--root', str(work)", "'--root', str(self.root)", 1))
        with self.assertRaises(ValueError): self.contract()

    def test_missing_policy_checker_or_producer_fails_closed(self):
        for relative in ('config/publish_policy.json', 'scripts/check_release_quality.py', 'scripts/health_check_v2.py'):
            path = self.root / relative; original = path.read_bytes(); path.unlink()
            with self.subTest(relative=relative), self.assertRaises(ValueError): self.contract()
            path.write_bytes(original)

    def profiles(self, paths, produced, *, regenerate=False):
        text = ('name: fixture\njobs:\n  fixture:\n    steps:\n'
                '      - run: python scripts/fixture_source.py\n'
                '      - uses: ./.github/actions/publish\n        with:\n'
                f'          paths: {paths}\n          regenerate-dashboard: "{str(regenerate).lower()}"\n'
                '          audit: "false"\n')
        return graph._transaction_profiles(text, self.contract(), {'scripts/fixture_source.py': {'writes': produced}})[0]

    def test_false_requested_regeneration_cannot_waive_source_runtime(self):
        p = self.profiles('data/notes.json', ['data/notes.json'])
        self.assertFalse(p['commerce_regeneration'])
        self.assertEqual(p['commands'][:len(graph._NON_OPERATIONS_RUNTIME_CHAIN)], graph._NON_OPERATIONS_RUNTIME_CHAIN)
        self.assertEqual(p['commands'][-2:], [['scripts/check_release_quality.py', '--phase', 'candidate'],
                                             ['scripts/check_release_quality.py', '--phase', 'final']])

    def test_source_commerce_chain_is_conditional_ordered_and_before_runtime(self):
        p = self.profiles('data', ['data/daiso_real/products.json'])
        self.assertTrue(p['commerce_regeneration'])
        self.assertEqual(p['commands'][:len(graph._COMMERCE_CHAIN)], graph._COMMERCE_CHAIN)
        self.assertEqual(p['commands'][len(graph._COMMERCE_CHAIN):len(graph._COMMERCE_CHAIN)+len(graph._NON_OPERATIONS_RUNTIME_CHAIN)], graph._NON_OPERATIONS_RUNTIME_CHAIN)
        self.assertEqual(p['commerce_triggers'], ['data/daiso_real/products.json'])

    def test_candidate_only_never_claims_automatic_score_product_or_export(self):
        p = self.profiles('data/daiso_real/candidate_pool.json data/dashboard_runtime.json',
                          ['data/daiso_real/candidate_pool.json', 'data/daiso_real/products.json'])
        self.assertTrue(p['candidate_only'])
        self.assertFalse(p['commerce_regeneration'])
        self.assertEqual(p['commands'][0], ['scripts/build_daiso_candidate_comparison.py'])
        scripts = {command[0] for command in p['commands']}
        self.assertNotIn('scripts/daiso/score_shopify_demand.py', scripts)
        self.assertNotIn('scripts/build_product_master.py', scripts)
        self.assertNotIn('scripts/export_shopify_operational.py', scripts)

    def restricted_workflow(self):
        return ("jobs:\n  fixture:\n    steps:\n"
                "      - name: Publish only the validated restricted review\n"
                "        id: restricted_publication\n"
                "        if: steps.continuity_mode.outputs.mode == 'restricted_gap' && steps.restricted_quality.outcome == 'success'\n"
                "        uses: ./.github/actions/publish\n"
                "        with:\n"
                "          collector-report: ${{ runner.temp }}/restricted/collector.json\n"
                "          execution-id: ${{ github.run_id }}:${{ github.run_attempt }}\n"
                "          paths: data/agents/continuity_review.json data/agents/continuity_review_history\n")

    def test_core_and_deep_restricted_profiles_declare_no_runtime_or_commerce(self):
        policy = self.contract()
        for filename in ('JARVIS-Core-Automation.yml', 'JARVIS-Deep-Analysis.yml'):
            with self.subTest(filename=filename):
                text = (ROOT / '.github/workflows' / filename).read_text()
                profiles = graph._transaction_profiles(text, policy, {})
                restricted = next(p for p in profiles if p['publication_profile'] == 'restricted_gap')
                normal = next(p for p in profiles if p['publication_profile'] != 'restricted_gap')
                self.assertEqual(normal['declared_runtime_commands'], graph._NON_OPERATIONS_RUNTIME_CHAIN)
                for key in ('commands', 'declared_runtime_commands', 'commerce_commands', 'operations_commands', 'provider_commands'):
                    self.assertEqual(restricted[key], [])
                self.assertFalse(restricted['commerce_regeneration'])
                self.assertFalse(restricted['candidate_only'])
                self.assertEqual(restricted['operations_producer_status'], 'quarantined_by_profile')
                self.assertEqual(restricted['producer_status'], 'declared_conditional_not_execution_evidence')
                self.assertIn('validate_publication_freshness', restricted['local_validation_actions'])
                self.assertEqual(restricted['publication_actions'], ['latest_main_fetch', 'exact_output_stage', 'ordinary_non_force_push'])
                self.assertEqual(restricted['profile_variants'], {'restricted_gap': []})

    def test_restricted_workflow_spoofed_guards_paths_report_or_identity_fail_closed(self):
        text = self.restricted_workflow()
        policy = self.contract()
        for old, new in ((graph._RESTRICTED_GUARD, 'true'),
                         ("'restricted_gap'", "'normal'"),
                         ("'restricted_gap'", "'future_mode'"),
                         (" && steps.restricted_quality.outcome == 'success'", ''),
                         (' && ', ' || '),
                         ('data/agents/continuity_review.json ', ''),
                         (' data/agents/continuity_review_history', ''),
                         ('data/agents/continuity_review_history', 'data'),
                         ('data/agents/continuity_review_history', 'data/agents/continuity_review_history data/unknown.json'),
                         ('${{ runner.temp }}/restricted/collector.json', 'data/agents/core_run_results.json'),
                         ('${{ github.run_id }}:${{ github.run_attempt }}', 'fixed:1')):
            with self.subTest(old=old, new=new), self.assertRaises(ValueError):
                graph._transaction_profiles(text.replace(old, new), policy, {})

    def test_restricted_policy_mutations_never_declare_runtime_exclusion(self):
        mutations = {'runtime_commands': [['scripts/health_check_v2.py']],
                     'commerce_commands': [['scripts/build_product_master.py']],
                     'canonical_dashboard_mutable': True, 'max_attempts': 3,
                     'schema_version': True, 'allowed_effects': ['local_analysis', 'operations'],
                     'review_path': 'data/dashboard_runtime.json', 'fixed_local_actions': []}
        for key, value in mutations.items():
            policy = deepcopy(self.policy)
            policy['restricted_gap'][key] = value
            self.write(policy=policy)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.contract()
            with self.subTest(profile_key=key), self.assertRaises(ValueError):
                graph._transaction_profiles(self.restricted_workflow(), policy, {})

    def test_restricted_actual_validation_dispatch_and_exact_stage_cannot_be_removed(self):
        changes = [
            ("doc.get('mode') not in (None, 'normal', 'restricted_gap')", "doc.get('mode') not in (None, 'normal', 'restricted_gap', 'future')"),
            ("if doc.get('mode') == 'restricted_gap':", 'if False:'),
            ("self.policy.get('restricted_gap') != RESTRICTED_POLICY", 'False'),
            ('validate_restricted_capture(doc, root=self.root, identity=self.execution_id)', 'None'),
            ('                    validate_restricted_capture(doc, root=self.root, identity=self.execution_id)',
             '                    if False:\n                        validate_restricted_capture(doc, root=self.root, identity=self.execution_id)'),
            ("any(p.rstrip('/') not in permitted_requests for p in self.paths)", 'False'),
            ('return self.regenerate_restricted(work, remote_changed or self.base, report_dir)', 'return None'),
            ("getattr(self, 'publication_profile', None) == 'restricted_gap'", 'False'),
            ("purpose='publication'", "purpose='analysis'"),
            ("            evidence = continuity.authenticate_evidence(work, execution_id=self.execution_id, purpose='publication')",
             "            if False:\n                evidence = continuity.authenticate_evidence(work, execution_id=self.execution_id, purpose='publication')"),
            ('continuity.reanalyze_for_publication(work, self.restricted_review,', 'continuity.other_analysis(work, self.restricted_review,'),
            ('report = check_restricted(work, aggregate, phase=phase,', 'report = unchecked(work, aggregate, phase=phase,'),
            ("if not report['publish_allowed']:", 'if False:'),
            ('name not in self.restricted_allowed or not (work/name).is_file() or (work/name).is_symlink()', 'False'),
            ('continuity.validate_publication_freshness(work, self.restricted_review,', 'continuity.not_fresh(work, self.restricted_review,'),
            ('self.verify_restricted_freshness(work)\n                    with timed_phase(\'push\'):', 'None\n                    with timed_phase(\'push\'):'),
            ('def regenerate_restricted(self, work, latest, report_dir):',
             "def regenerate_restricted(self, work, latest, report_dir):\n        self.command(work, ['scripts/run_jarvis_operations.py'])")]
        for old, new in changes:
            self.assertIn(old, self.wrapper)
            self.write(wrapper=self.wrapper.replace(old, new, 1))
            with self.subTest(old=old), self.assertRaises(ValueError):
                self.contract()

    def test_restricted_dead_validation_wrong_stage_and_direct_dispatch_fail_closed(self):
        changes = [
            ('verify_restricted_freshness',
             '            result = continuity.validate_publication_freshness(work, self.restricted_review,',
             '            result = {}\n            if False:\n                result = continuity.validate_publication_freshness(work, self.restricted_review,'),
            ('verify_restricted_preserved',
             '            continuity.assert_protected_unchanged(self.restricted_before, continuity.protected_inventory(work))',
             '            if False:\n                continuity.assert_protected_unchanged(self.restricted_before, continuity.protected_inventory(work))'),
            ('stage', "            if self.publication_profile == 'restricted_gap':", '            if False:'),
            ('stage', "            if self.publication_profile == 'restricted_gap':", "            if self.publication_profile == 'full':"),
            ('capture', "            if self.publication_profile == 'restricted_gap':", '            if False:'),
            ('capture', '                if name not in self.restricted_allowed:', '                if False:'),
            ('regenerate_restricted', '        import continuity_reconciliation as continuity',
             "        subprocess.run(['python', 'scripts/run_jarvis_operations.py'], cwd=work, check=True)\n        import continuity_reconciliation as continuity")]
        for method, old, new in changes:
            start = self.wrapper.index('    def ' + method + '(')
            end = self.wrapper.index('\n    def ', start + 5)
            body = self.wrapper[start:end]
            self.assertIn(old, body)
            self.write(wrapper=self.wrapper[:start] + body.replace(old, new, 1) + self.wrapper[end:])
            with self.subTest(method=method, old=old), self.assertRaises(ValueError):
                self.contract()


if __name__ == '__main__':
    unittest.main(verbosity=2)
