"""Execution authority stays outside the archive, not outside security gates."""
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
import brain_plane
import obsidian_brain as brain


class AuthPlanExclusion(unittest.TestCase):
    def test_exact_queue_path_is_excluded_without_claiming_vault_consumption(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / '.gitignore').write_text('/obsidian/JARVIS_LUNA/BrainRuntime/\n', encoding='utf-8')
            (root / 'data').mkdir()
            queue = root / 'data/shopify_action_queue.json'
            value = {'draft_actions': [{'authenticated_authorization': False,
                'authorization': {'status': 'not_authorized', 'verifier': 'required'}}]}
            queue.write_text(json.dumps(value), encoding='utf-8')
            with brain.execution(root, task='test', team='runtime', operation='local-analysis') as run:
                self.assertEqual(brain_plane.read_json(queue, root, {}), value)
                self.assertEqual(run.consumed, {})
                self.assertIn('excluded_authorization_plan_path', run.excluded)
                with self.assertRaises(brain.PathExcluded):
                    brain.load_json(queue, root, {})
            self.assertFalse((root / brain.BRAIN / 'payloads').exists())

    def test_public_token_price_is_numeric_only_and_not_a_general_exception(self):
        for price in (0, 0.042, 1):
            brain._check_secrets(json.dumps({'input_token_price_per_mtok_usd': price}).encode(),
                                 {'input_token_price_per_mtok_usd': price})
        for value in ('SYNTHETIC TOKEN', True, {'token': 'SYNTHETIC SECRET'}, -1, float('inf')):
            with self.assertRaises(brain.PathExcluded):
                brain._check_secrets(b'{}', {'input_token_price_per_mtok_usd': value})
        for key in ('api_key', 'token', 'authorization', 'input_token_price', 'token_price_per_mtok_usd'):
            with self.assertRaises(brain.PathExcluded):
                brain._check_secrets(b'{}', {key: 0.042})

    def test_other_authorization_fields_still_fail_closed_without_raw_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / '.gitignore').write_text('/obsidian/JARVIS_LUNA/BrainRuntime/\n', encoding='utf-8')
            (root / 'data').mkdir()
            ordinary = root / 'data/ordinary.json'
            ordinary.write_text(json.dumps({'authorization': 'SYNTHETIC SECRET VALUE'}), encoding='utf-8')
            with brain.execution(root, task='test', team='runtime', operation='local-analysis'):
                with self.assertRaises(brain.PathExcluded):
                    brain_plane.read_json(ordinary, root, {})
            self.assertFalse((root / brain.BRAIN / 'payloads').exists())


if __name__ == '__main__':
    unittest.main()
