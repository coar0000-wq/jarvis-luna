#!/usr/bin/env python3
"""기준선 신선도는 근거 파일 자신의 시각(source_clock)으로 본다 (2026-10-16 회귀)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import team_improvement_evidence as tie  # noqa: E402

NOW = '2026-10-16T12:00:00+00:00'


def team(tid, source_clock, base_at='2026-10-11T00:00:00+00:00', cur_at='2026-10-16T11:00:00+00:00'):
    pt = lambda v, at: {'value': v, 'denominator': 10, 'measured_at': at, 'source_path': 'x', 'source_clock': source_clock}
    return tid, {'metric': 'm', 'unit': 'u', 'direction': 'increase', 'baseline': pt(1, base_at), 'current': pt(2, cur_at)}


class SourceClockTests(unittest.TestCase):
    def run_with(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            (base / 'data/self_improve').mkdir(parents=True)
            (base / tie.BASELINES).write_text(json.dumps({'schema_version': 1, 'teams': dict(rows)}), encoding='utf-8')
            teams = {tid: {'baseline': None, 'metric': {'id': 'm', 'unit': 'u'}} for tid, _ in rows}
            tie._apply_team_baselines(base, teams, tie._clock(NOW), 14)
            return teams

    def test_old_source_is_blocked_even_if_measured_today(self):
        t = self.run_with([team('sourcing', '2026-09-29T00:48:58+00:00')])['sourcing']
        self.assertEqual(t['phase'], 'blocked')
        self.assertEqual(t['blockers'], ['stale_observation'])
        self.assertEqual(t['current']['clock_field'], 'source_clock')
        self.assertFalse(t['current']['fresh'])

    def test_recent_source_is_monitoring(self):
        t = self.run_with([team('design', '2026-10-10T00:00:00+00:00')])['design']
        self.assertEqual(t['phase'], 'monitoring')
        self.assertTrue(t['current']['fresh'])

    def test_missing_source_clock_falls_back_to_measured_at(self):
        tid, row = team('graph', None)
        for k in ('baseline', 'current'):
            row[k].pop('source_clock')
        t = self.run_with([(tid, row)])['graph']
        self.assertEqual(t['current']['clock_field'], 'measured_at')
        self.assertEqual(t['phase'], 'monitoring')


if __name__ == '__main__':
    unittest.main(verbosity=1)
