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
        for key in ('runtime_commands', 'commerce_commands'):
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
        self.assertEqual(p['commands'][:4], graph._RUNTIME_CHAIN)
        self.assertEqual(p['commands'][-2:], [['scripts/check_release_quality.py', '--phase', 'candidate'],
                                             ['scripts/check_release_quality.py', '--phase', 'final']])

    def test_source_commerce_chain_is_conditional_ordered_and_before_runtime(self):
        p = self.profiles('data', ['data/daiso_real/products.json'])
        self.assertTrue(p['commerce_regeneration'])
        self.assertEqual(p['commands'][:12], graph._COMMERCE_CHAIN)
        self.assertEqual(p['commands'][12:16], graph._RUNTIME_CHAIN)
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
