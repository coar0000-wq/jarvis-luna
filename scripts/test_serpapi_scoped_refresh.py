"""A scoped market refresh must retain the other source and its original clock."""
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parent))
import collect_serpapi_market as collector

class ScopedRefreshTests(unittest.TestCase):
    def test_both_scopes_retain_unrequested_observation(self):
        for selected, retained in [('prices','trends'),('trends','prices')]:
            with self.subTest(selected=selected):
                previous={'generated_at':'2026-10-01T00:00:00Z',retained:{'status':'ok','reason':'kept','items':[{'id':'old'}]}}
                out=Mock()
                with patch.dict(collector.os.environ,{'SERPAPI_KEY':'test'}), patch.object(sys,'argv',['script','--only='+selected]), patch.object(collector,'OUT',out), patch.object(collector,'LEDGER',Mock()), patch.object(collector,'load',return_value=previous), patch.object(collector,'read_ledger',return_value={'used':0,'cap':200,'month':'2026-10','runs':[]}), patch.object(collector,'collect_prices',return_value={'status':'ok','items':[]}) as prices, patch.object(collector,'collect_trends',return_value={'status':'ok','items':[]}) as trends:
                    self.assertEqual(collector.main(),0)
                saved=json.loads(out.write_text.call_args.args[0])
                self.assertEqual(saved[retained],{**previous[retained],'collected_at':previous['generated_at']})
                self.assertEqual((prices if selected=='prices' else trends).call_count,1)
                self.assertEqual((trends if selected=='prices' else prices).call_count,0)

if __name__=='__main__': unittest.main()
