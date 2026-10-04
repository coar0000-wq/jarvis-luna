"""Execute actual runtime main with isolated artifacts and bounded metric fixtures."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import generate_dashboard_runtime as rt

class RuntimeOperationsWiring(unittest.TestCase):
    def test_main_loads_verified_board_and_secretary_advisory_without_name_error(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); data=root/'data'; (data/'operations').mkdir(parents=True)
            board={'schema_version':1,'status':'local_only','counts':{'external_verified':0}}
            (data/'operations'/'board.json').write_text(json.dumps(board),encoding='utf-8')
            (data/'typesafe_team_advisory.json').write_text(json.dumps({'teams':{'secretary':{
                'source':'deterministic_local','mode':'local_fallback','enforced':False}}}),encoding='utf-8')
            graph={'notes':1,'links':1,'dangling_links':0,'audit':'passed'}
            training={'accuracy':None,'status':'not_verified','records':0,'experts':0}
            sources={'status':'ok','record_count':1}
            cumulative={'totals':{'records':1},'current_snapshot':{'records':1}}
            cards=[{'id':'sourcing','phase':'now','summary':'fixture'}]
            with patch.multiple(rt,ROOT=root,D=data,OUT=data/'dashboard_runtime.json'), \
                 patch.object(rt,'graph_metrics',return_value=graph), \
                 patch.object(rt,'source_metrics',return_value=sources), \
                 patch.object(rt,'training_metrics',return_value=training), \
                 patch.object(rt,'cumulative_metrics',return_value=cumulative), \
                 patch.object(rt,'team_cards',return_value=cards), \
                 patch.object(rt,'secretary_card',return_value={'id':'secretary'}), \
                 patch.object(rt,'workflow_snapshot',return_value=({},False)), \
                 contextlib.redirect_stdout(io.StringIO()):
                rt.main()
            result=json.loads((data/'dashboard_runtime.json').read_text(encoding='utf-8'))
            self.assertEqual(result['operations'],board)
            self.assertEqual(result['secretary']['jev_advisory']['source'],'deterministic_local')
            self.assertFalse(result['secretary']['jev_advisory']['enforced'])

if __name__=='__main__': unittest.main()
