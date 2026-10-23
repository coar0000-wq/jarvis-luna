"""Offline retention/privacy contracts for bounded immutable operations history."""
import json
from pathlib import Path
import tempfile
import unittest

import yaml

import obsidian_brain as brain
import operations_storage as storage
import restore_operations_safety as restore
from daiso import observe_shortlist as observer


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    'JARVIS-Core-Automation.yml', 'JARVIS-Deep-Analysis.yml',
    'daiso-real-collection.yml', 'fx-refresh.yml',
    'daiso-candidate-recovery.yml',
)
REGRESSIONS = (
    'test_operations_segments.py', 'test_restore_operations_segments.py',
    'test_operations_segment_publication.py', 'test_operations_history_wiring.py',
)


class HistoryWiringTests(unittest.TestCase):
    def test_all_existing_operations_artifacts_keep_state_history_and_reports(self):
        for name in WORKFLOWS:
            with self.subTest(workflow=name):
                workflow = yaml.safe_load((ROOT / '.github/workflows' / name).read_text())
                steps = [step for job in workflow['jobs'].values()
                         for step in job.get('steps', [])
                         if step.get('name') == 'Retain immutable operations safety history']
                self.assertEqual(len(steps), 1)
                step = steps[0]
                self.assertEqual(set(step['with']['path'].split()), {
                    'data/operations/state.json', 'data/operations/state',
                    'data/operations/reports',
                })
                self.assertIs(step['with']['include-hidden-files'], True)
                self.assertEqual(step['with']['if-no-files-found'], 'error')
                self.assertEqual(step['with']['retention-days'], 30)
                if name == 'daiso-candidate-recovery.yml':
                    self.assertNotIn('compression-level', step['with'])
                else:
                    self.assertEqual(step['with']['compression-level'], 9)
                condition = "always() && steps.operations_safety.outputs.operations_continuity == 'verified'"
                if name in ('JARVIS-Core-Automation.yml', 'fx-refresh.yml'):
                    condition = ("always() && steps.operations_safety.outcome == 'success' && "
                                 "steps.operations_retention.outputs.operations_continuity == 'verified'")
                if name in ('JARVIS-Core-Automation.yml', 'JARVIS-Deep-Analysis.yml'):
                    condition = "steps.continuity_mode.outputs.mode == 'normal' && (" + condition + ")"
                self.assertEqual(step['if'], condition)

    def test_new_regressions_run_in_both_exact_head_ci_and_deployment(self):
        for workflow in ('preflight.yml', 'pages-verified.yml'):
            text = (ROOT / '.github/workflows' / workflow).read_text()
            for test in REGRESSIONS:
                with self.subTest(workflow=workflow, test=test):
                    self.assertEqual(text.count('"' + test + '"'), 1)

    def test_limits_are_not_raised_by_storage_format_change(self):
        self.assertEqual(storage.OPS_STATE_MAX_BYTES, 32 * 1024 * 1024)
        self.assertEqual(restore.MAX_FILE_BYTES, 8 * 1024 * 1024)
        self.assertEqual(restore.BASE_TOTAL_BYTES, 96 * 1024 * 1024)
        self.assertEqual(restore.MAX_TOTAL_BYTES, 120 * 1024 * 1024)
        self.assertEqual(restore.MAX_ARCHIVE_BYTES, 64 * 1024 * 1024)
        self.assertEqual(restore.MAX_FILES, 20000)

    def test_segment_and_original_raw_chunks_remain_private_to_the_vault(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for filename in ('segment-' + 'a' * 64 + '.json',
                             'legacy-' + 'b' * 64 + '.bin'):
                name = 'data/operations/state/' + filename
                with self.subTest(name=name):
                    self.assertTrue(brain.note_exclusion(name, root))

    def test_direct_watch_consumer_still_blocks_deleted_observation_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'data/operations/state.json'
            path.parent.mkdir(parents=True)
            # This consumer deliberately examines only the fixed watch field;
            # it must neither follow storage paths nor acquire new authority.
            value = {'watch': {'sources': {'pricing': {'records': {
                'old': {'source': observer.OUTPUT}}}}},
                '_operations_storage': {'schema_version': 2, 'untrusted_path': '/never/read'}}
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(observer.Blocked, 'durable_observation_history_deleted_watch_evidence'):
                observer._deny_reset_with_watch_history(root)


if __name__ == '__main__':
    unittest.main()
