"""Runtime must see the same ordered commerce chain as final publication."""
from pathlib import Path
import unittest
import yaml
from run_commerce_pipeline import commands, ROOT


class CommercePipelineTests(unittest.TestCase):
    def test_policy_chain_includes_canonical_gate_shortlist_and_exports(self):
        rows = commands()
        names = [row[0] for row in rows]
        self.assertEqual(names[0], 'scripts/build_product_master.py')
        self.assertLess(names.index('scripts/build_shopify_shortlist.py'), names.index('scripts/export_shopify_operational.py'))
        self.assertLess(names.index('scripts/build_mocra_readiness.py'), len(names) - 1 - names[::-1].index('scripts/build_listing_gate.py'))
        self.assertIn(['scripts/export_shopify_operational.py', '--blocked-noop'], rows)
        self.assertIn(['scripts/discover_channels.py', '--cached-only'], rows)

    def test_core_refreshes_after_sources_before_runtime(self):
        text = (ROOT / '.github/workflows/JARVIS-Core-Automation.yml').read_text(encoding='utf-8')
        self.assertLess(text.index('Bounded existing-team source recovery'), text.index('Required canonical source processing'))
        self.assertLess(text.index('scripts/run_commerce_pipeline.py'), text.index('Required current canonical runtime'))

    def test_gosi_exports_keep_zero_ready_products_as_blocked_noop(self):
        expected = ['python', '-u', 'scripts/export_shopify_operational.py', '--blocked-noop']
        for workflow in ('gosi-vision.yml', 'gosi-alt.yml'):
            with self.subTest(workflow=workflow):
                text = (ROOT / '.github/workflows' / workflow).read_text(encoding='utf-8')
                calls = [line.strip().split() for line in text.splitlines()
                         if line.strip().startswith('python -u scripts/export_shopify_operational.py')]
                self.assertEqual(calls, [expected])

    def test_listing_copy_only_triggers_on_main_canonical_updates(self):
        workflow = yaml.load(
            (ROOT / '.github/workflows/shopify-listing-copy.yml').read_text(encoding='utf-8'),
            Loader=yaml.BaseLoader,
        )
        self.assertEqual(workflow['on']['push']['branches'], ['main'])
        self.assertEqual(workflow['on']['push']['paths'],
                         ['data/daiso_real/shopify_s_recommendations.json'])
        self.assertIn('workflow_dispatch', workflow['on'])

    def test_listing_copy_manual_and_push_jobs_are_main_only(self):
        workflow = yaml.load(
            (ROOT / '.github/workflows/shopify-listing-copy.yml').read_text(encoding='utf-8'),
            Loader=yaml.BaseLoader,
        )
        # Preserve the offline source-recovery exclusion inside the main guard.
        self.assertEqual(workflow['jobs']['build']['if'],
            "${{ github.ref == 'refs/heads/main' && (github.event_name != 'push' || "
            "!contains(github.event.head_commit.message, '[source-recovery-offline]')) }}")
        # Preserve trigger-commit provenance, rather than silently checking out main
        # for branch events and mislabelling generated artifacts as branch results.
        checkout = workflow['jobs']['build']['steps'][0]
        self.assertNotIn('ref', checkout.get('with', {}))
        self.assertEqual(workflow['concurrency']['group'], 'main-publish')
        self.assertEqual(workflow['concurrency']['cancel-in-progress'], 'false')

    def test_deep_uses_same_complete_chain(self):
        text = (ROOT / '.github/workflows/JARVIS-Deep-Analysis.yml').read_text(encoding='utf-8')
        stage = text.split("cat > \"$RUNNER_TEMP/deep_41.sh\" <<'RELEASE_STAGE_deep_41'", 1)[1].split('RELEASE_STAGE_deep_41', 1)[0]
        self.assertIn('scripts/run_commerce_pipeline.py', stage)


if __name__ == '__main__':
    unittest.main()
