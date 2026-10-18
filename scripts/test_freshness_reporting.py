"""Offline regressions for scope, source clocks and watchdog error visibility."""
import copy
import sys
from datetime import datetime, timezone
import json
import os
import subprocess
import textwrap
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect_us_retail as retail
import collect_workflow_status as monitor
from data_freshness import assess_timestamp
from test_workflow_status import payloads
from workflow_status_history import replacement_ids

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]
OLD = '2026-09-15T11:19:23.782Z'
FRESH = NOW.isoformat()


def entry(rows=None, **kw):
    return dict(rows=rows or [], reason='fixture', label='fixture', url='https://example.org', **kw)


class FreshnessReportingTests(unittest.TestCase):
    def test_iso_unknown_future_and_old_never_fresh(self):
        for stamp, expected in ((OLD, 'stale'), ('2026-10-18T000:00:00.000Z', 'invalid'),
                                (None, 'invalid'), ('2026-10-18T12:00:00', 'invalid'),
                                ('2026-10-19T12:00:00Z', 'future'), (FRESH, 'fresh')):
            result = assess_timestamp(stamp, NOW)
            self.assertEqual(result['status'], expected)
            self.assertEqual(result['source_timestamp'], stamp)
            self.assertEqual(result['is_stale'], expected != 'fresh')

    def test_inventory_covers_fourteen_not_five(self):
        report = monitor.build_report(payloads(), '2026-10-03T12:00:00Z')
        monitor.add_inventory(report, ROOT / '.github/workflows')
        active={p.name for p in (ROOT/'.github/workflows').iterdir() if p.suffix in {'.yml','.yaml'}}
        self.assertEqual(report['active_workflows'], len(active))
        self.assertEqual(report['scheduled_workflows'], 14)
        self.assertEqual(set(report['excluded_event_only_workflows']), active-set(monitor.WORKFLOWS))
        self.assertEqual(len(report['excluded_disabled_workflows']), 12)
        self.assertTrue(report['coverage_complete'])
        self.assertEqual(set(report['workflows']), set(monitor.WORKFLOWS))

    def test_new_schedule_prevents_complete_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            for name in monitor.WORKFLOWS:
                (Path(td)/name).write_text('on:\n  schedule:\n    - cron: x\n')
            (Path(td)/'new.yml').write_text('on:\n    schedule:\n      - cron: x\n')
            report = monitor.build_report(payloads(), '2026-10-03T12:00:00Z')
            monitor.add_inventory(report, td)
            self.assertFalse(report['coverage_complete'])
            self.assertEqual(report['unmonitored_scheduled_workflows'], ['new.yml'])
            self.assertEqual(report['status'], 'warning')

    def test_output_assessment_preserves_input_and_rejects_false_green(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)/'data'; data.mkdir()
            docs = {'walmart_products.json': {'collected_at': OLD, 'is_stale': False, 'count': 39},
                    'us_beauty_products.json': {'count':125, 'collected_at': '2026-10-18T000:00:00.000Z',
                                              'by_store': {'Ulta': {'count':111, 'collected_at': FRESH}, 'Sephora': {'count':14, 'collected_at': OLD}}},
                    'source_health.json': {'generated_at': '2026-10-03T11:53:53Z'}}
            for name, value in docs.items():
                (data/name).write_text(json.dumps(value))
            report = monitor.add_output_freshness({'status':'success'}, td, NOW)
            self.assertEqual(report['status'], 'warning')
            self.assertFalse(report['output_freshness_verified'])
            self.assertEqual(report['output_freshness']['us_beauty_products.json']['status'], 'invalid')
            for name, value in docs.items():
                self.assertEqual(json.loads((data/name).read_text()), value)

    def test_backfill_and_repeated_fallback_preserve_capture(self):
        with tempfile.TemporaryDirectory() as td, patch.object(retail, 'ROOT', Path(td)), patch.object(retail, 'now_iso', return_value=FRESH):
            out=Path(td)/'walmart.json'
            rows=[{'name':'fixture', 'url':'https://example.org/product'}]
            retail.write_catalog(out, entry(rows, assisted=True, assist_at=OLD), '')
            doc=json.loads(out.read_text())
            self.assertTrue(doc['is_stale'])
            self.assertEqual(doc['collected_at'], OLD)
            retail.write_catalog(out, entry(), '')
            again=json.loads(out.read_text())
            self.assertEqual(again['products'], rows)
            self.assertEqual(again['collected_at'], OLD)
            self.assertEqual(again['last_attempt_at'], FRESH)
            self.assertTrue(again['is_stale'])

    def test_assist_without_capture_never_uses_now(self):
        with tempfile.TemporaryDirectory() as td, patch.object(retail, 'ROOT', Path(td)), patch.object(retail, 'now_iso', return_value=FRESH):
            out=Path(td)/'walmart.json'
            retail.write_catalog(out, entry([{'name':'fixture'}], assisted=True), '')
            doc=json.loads(out.read_text())
            self.assertEqual(doc['collected_at'], '')
            self.assertTrue(doc['is_stale'])
            retail.write_catalog(out, entry(), '')
            retained=json.loads(out.read_text())
            self.assertEqual(retained['products'], doc['products'])
            self.assertEqual(retained['collected_at'], '')
            self.assertTrue(retained['is_stale'])

    def test_mixed_beauty_uses_oldest_source_and_retains_store_times(self):
        with tempfile.TemporaryDirectory() as td, patch.object(retail, 'ROOT', Path(td)), patch.object(retail, 'OUT_US_BEAUTY', Path(td)/'beauty.json'), patch.object(retail, 'now_iso', return_value=FRESH):
            rows=[{'name':'fixture'}]
            retail.write_us_beauty(entry(rows), entry(rows, assisted=True, assist_at=OLD))
            doc=json.loads(retail.OUT_US_BEAUTY.read_text())
            self.assertTrue(doc['is_stale'])
            self.assertEqual(doc['by_store']['Ulta']['collected_at'], FRESH)
            self.assertEqual(doc['by_store']['Sephora']['collected_at'], OLD)
            self.assertEqual(assess_timestamp(doc['collected_at'], NOW)['status'], 'stale')
            retail.write_us_beauty(entry(), entry())
            again=json.loads(retail.OUT_US_BEAUTY.read_text())
            self.assertEqual(again['collected_at'], doc['collected_at'])
            self.assertEqual(again['by_store'], doc['by_store'])

    def test_history_accepts_additions_not_removals(self):
        current=monitor.build_report({}, NOW)
        old=copy.deepcopy(current)
        old['workflows']={key: value for key,value in old['workflows'].items() if key in list(monitor.WORKFLOWS)[:5]}
        policy=json.loads((ROOT/'config/publish_policy.json').read_text())
        replacement_ids(old, current, policy)
        with self.assertRaises(ValueError): replacement_ids(current, old, policy)

    def test_inventory_diagnostic_lists_can_change_with_history(self):
        old=monitor.build_report({}, NOW)
        old['excluded_event_only_workflows']=['moved.yml']
        current=copy.deepcopy(old)
        current['excluded_event_only_workflows']=[]
        policy=json.loads((ROOT/'config/publish_policy.json').read_text())
        replacement_ids(old, current, policy)

    def test_recent_clock_does_not_override_explicit_stale_or_empty(self):
        with tempfile.TemporaryDirectory() as td:
            data=Path(td)/'data'; data.mkdir()
            for name in ('walmart_products.json','us_beauty_products.json'):
                (data/name).write_text(json.dumps({'collected_at':FRESH,'is_stale':True,'count':0}))
            (data/'source_health.json').write_text(json.dumps({'generated_at':FRESH}))
            report=monitor.add_output_freshness({'status':'success'},td,NOW)
            self.assertFalse(report['output_freshness_verified'])
            self.assertEqual(report['status'],'warning')

    def test_missing_beauty_source_keeps_publishable_unknown_stores(self):
        with tempfile.TemporaryDirectory() as td:
            data=Path(td)/'data'; data.mkdir()
            beauty=data/'us_beauty_products.json'
            beauty.write_text(json.dumps({'count':2,'collected_at':FRESH,'by_store':{
                'Ulta':{'count':1,'collected_at':FRESH},'Sephora':{'count':1,'collected_at':FRESH}}}))
            before=monitor.add_output_freshness(monitor.build_report({},NOW),td,NOW)
            beauty.write_text('malformed')
            after=monitor.add_output_freshness(monitor.build_report({},NOW),td,NOW)
            policy=json.loads((ROOT/'config/publish_policy.json').read_text())
            replacement_ids(before, after, policy)
            self.assertEqual(after['output_freshness']['us_beauty_products.json:Ulta']['status'],'no_verified_data')

    def test_future_mixed_beauty_never_fresh(self):
        with tempfile.TemporaryDirectory() as td, patch.object(retail,'ROOT',Path(td)), patch.object(retail,'OUT_US_BEAUTY',Path(td)/'beauty.json'), patch.object(retail,'now_iso',return_value=FRESH):
            retail.write_us_beauty(entry([{'name':'fixture'}]),entry([{'name':'fixture'}],assisted=True,assist_at='2026-10-19T12:00:00Z'))
            doc=json.loads(retail.OUT_US_BEAUTY.read_text())
            self.assertTrue(doc['is_stale'])
            self.assertTrue(doc['freshness']['is_stale'])

    def test_malformed_timestamp_type_recovery_is_publishable(self):
        with tempfile.TemporaryDirectory() as td:
            data=Path(td)/'data'; data.mkdir()
            source=data/'walmart_products.json'
            policy=json.loads((ROOT/'config/publish_policy.json').read_text())
            for value in ({'invalid':'clock'}, ['clock']):
                source.write_text(json.dumps({'count':1,'collected_at':value}))
                before=monitor.add_output_freshness(monitor.build_report({},NOW),td,NOW)
                self.assertIsNone(before['output_freshness']['walmart_products.json']['source_timestamp'])
                source.write_text(json.dumps({'count':1,'collected_at':FRESH}))
                after=monitor.add_output_freshness(monitor.build_report({},NOW),td,NOW)
                replacement_ids(before,after,policy)

    def test_watchdog_shell_fixtures(self):
        body=textwrap.dedent((ROOT/'.github/workflows/jarvis-watchdog.yml').read_text().split('        run: |\n',1)[1])
        gh_fixture = """#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
mode = os.environ['FIXTURE_MODE']
if mode == 'api_error': sys.exit(1)
if args[0] == 'api':
    print('disabled_manually' if mode == 'disabled' else 'active')
elif args[:2] == ['workflow', 'run']:
    with open(os.environ['DISPATCH_LOG'], 'a') as f: f.write(args[2] + '\\n')
elif '--json' in args:
    field = args[args.index('--json') + 1]
    if field == 'status': print('1' if mode == 'busy' else '0')
    elif field == 'updatedAt': print('2026-10-18T12:30:00Z' if mode == 'future' else '2026-10-18T11:30:00Z' if mode == 'fresh' else '2026-10-17T00:00:00Z')
    elif field == 'createdAt': print('2026-10-18T11:30:00Z' if mode == 'cooldown' else '2026-10-17T00:00:00Z')
else: sys.exit(2)
"""
        date_fixture = """#!/usr/bin/env python3
import sys
from datetime import datetime, timezone
args=sys.argv[1:]
value=datetime(2026,10,18,12,tzinfo=timezone.utc) if '-d' not in args else datetime.fromisoformat(args[args.index('-d')+1].replace('Z','+00:00'))
print(int(value.timestamp()))
"""
        for mode in ('api_error', 'disabled', 'busy', 'fresh', 'cooldown', 'stale', 'future'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                root=Path(td)
                for name, content in (('gh', gh_fixture), ('date', date_fixture)):
                    target=root/name; target.write_text(content); target.chmod(0o755)
                env=dict(os.environ, PATH=str(root)+os.pathsep+os.environ['PATH'], FIXTURE_MODE=mode,
                         DISPATCH_LOG=str(root/'dispatch'), REPO='fixture/offline', GITHUB_STEP_SUMMARY=str(root/'summary'))
                result=subprocess.run(['bash', '-c', body], env=env, capture_output=True, text=True)
                if mode in ('api_error', 'future'):
                    self.assertNotEqual(result.returncode, 0)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                if mode == 'stale':
                    self.assertEqual((root/'dispatch').read_text().splitlines(), ['JARVIS-Core-Automation.yml'])
                else:
                    self.assertFalse((root/'dispatch').exists())
                if mode == 'cooldown': self.assertIn('WATCHDOG_STALE', result.stdout)

    def test_watchdog_success_not_start_and_api_errors_not_suppressed(self):
        text=(ROOT/'.github/workflows/jarvis-watchdog.yml').read_text()
        self.assertIn('--status success --limit 1 --json updatedAt', text)
        self.assertIn('if [ "$state" != "active" ]', text)
        self.assertIn('--branch main', text)
        self.assertNotIn('--branch main --json status', text)
        self.assertNotIn('|| echo 0', text)
        self.assertNotIn('WATCHDOG_OK', text)
        self.assertIn('3600', text)
        configured=set(text.split('PUBLISH="',1)[1].split('"',1)[0].split())
        expected={p.name for p in (ROOT/'.github/workflows').glob('*.yml') if 'group: main-publish' in p.read_text()}
        self.assertEqual(configured,expected)

if __name__ == '__main__': unittest.main()
