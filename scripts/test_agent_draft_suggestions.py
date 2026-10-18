"""Only actionable, gate-passing products may produce draft import proposals."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_jarvis_agents as agents

class DraftSuggestionTests(unittest.TestCase):
    def plan(self, rows):
        listing = agents.agent_listing({'recommendations': rows}, {})
        return listing, agents.agent_ops({}, {}, {'s_count': 7}, listing, {})

    def test_all_blocked_does_not_suggest_import(self):
        listing, plan = self.plan([{'pd_no': '1', 'registerable': False}])
        self.assertEqual(listing['registerable_count'], 0)
        self.assertFalse(any(x['action'] == 'import_csv_as_draft' for x in listing['suggestions']))
        self.assertFalse(any('Shopify draft' in x['title'] for x in plan['tasks']))

    def test_only_passing_count_is_advertised(self):
        listing, plan = self.plan([{'pd_no': '1', 'registerable': True}, {'pd_no': '2', 'registerable': False}])
        self.assertEqual([x['pd_no'] for x in listing['items']], ['1'])
        self.assertIn('통과 1건', plan['tasks'][0]['title'])

if __name__ == '__main__':
    unittest.main()
