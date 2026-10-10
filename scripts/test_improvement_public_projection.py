"""Offline synthetic evidence UI contracts. No production data or provider calls."""
import copy
import json
from pathlib import Path
import unittest
from build_public_site import (project, SCHEMAS, STATIC_FILES, OPERATIONS,
                               TEAM_IMPROVEMENT_EVIDENCE)
from team_improvement_evidence import TEAM_IDS

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    row = {'id': 'graph', 'phase': 'shadow_evaluated', 'status': 'rule_imitation_shadow_only',
           'baseline': {'value': 512, 'denominator': 6955, 'clock_field': 'generated_at',
                        'clock_at': '2026-10-03T11:43:28Z', 'captured_at': None},
           'shadow': {'value': 507, 'denominator': 6955, 'clock_field': 'generated_at',
                      'clock_at': '2026-10-03T11:43:28Z', 'captured_at': None},
           'current': None, 'authority': False, 'business_clearance': False,
           'autonomous_change_allowed': False, 'verified_gain': False,
           'blockers': ['no_verified_gain']}
    return {'schema_version': 1, 'generated_at': '2026-10-05T11:30:00Z',
            'teams': {t: dict(copy.deepcopy(row), id=t) for t in TEAM_IDS},
            'summary': {'teams': 11, 'phase_counts': {'monitoring': 6, 'proposal': 0,
                'shadow_evaluated': 1, 'applied': 2, 'verified_gain': 0, 'blocked': 2},
                'verified_gains': 0, 'authority': False, 'business_clearance': False}}


class EvidencePublicTests(unittest.TestCase):
    def test_fixed_eleven_and_no_new_public_file(self):
        value = fixture()
        value['teams']['secretary'] = {'raw_payload': 'PRIVATE'}
        value['teams']['unknown'] = {'identity': 'PRIVATE'}
        result = project(value, TEAM_IMPROVEMENT_EVIDENCE)
        self.assertEqual(set(result['teams']), set(TEAM_IDS))
        self.assertEqual(len(STATIC_FILES) + len(SCHEMAS), 31)
        runtime = project({'team_improvement_evidence': value}, SCHEMAS['data/dashboard_runtime.json'])
        self.assertEqual(runtime['team_improvement_evidence'], result)

    def test_public_flags_cannot_grant_change_approval_or_gain(self):
        value = fixture()
        for row in value['teams'].values():
            row.update(authority=True, business_clearance=True, autonomous_change_allowed=True,
                       verified_gain=True, phase='verified_gain', approved=True)
        value['summary'].update(verified_gains=99, authority=True, business_clearance=True)
        value['summary']['phase_counts']['verified_gain'] = 11
        result = project(value, TEAM_IMPROVEMENT_EVIDENCE)
        for row in result['teams'].values():
            self.assertEqual(row['phase'], 'blocked')
            self.assertFalse(row['authority'])
            self.assertFalse(row['business_clearance'])
            self.assertFalse(row['autonomous_change_allowed'])
            self.assertFalse(row['verified_gain'])
            self.assertNotIn('approved', row)
        self.assertEqual(result['summary']['verified_gains'], 0)
        self.assertEqual(result['summary']['phase_counts']['verified_gain'], 0)

    def test_raw_payload_identity_credentials_and_rationale_omitted(self):
        value = fixture()
        forbidden = {'raw_payload': 'SECRET_VALUE', 'identity': 'PRIVATE_PERSON',
                     'nonce': 'PRIVATE_NONCE', 'proof': 'PRIVATE_PROOF',
                     'reason': 'PRIVATE_RATIONALE', 'email': 'PRIVATE_EMAIL'}
        value.update(forbidden)
        for row in value['teams'].values():
            row.update(forbidden)
        result = project(value, TEAM_IMPROVEMENT_EVIDENCE)
        self.assertNotIn('PRIVATE_', json.dumps(result))
        self.assertNotIn('SECRET_', json.dumps(result))
        audit = project({'audit': {'mode': 'future_only', 'external_authority': True,
            'head': 'PRIVATE_HEAD', 'payloads': forbidden, 'counts': {
                'audited': 5, 'legacy': 1042, 'raw_payload': 'SECRET_VALUE'}}}, OPERATIONS)['audit']
        self.assertFalse(audit['external_authority'])
        self.assertNotIn('PRIVATE_', json.dumps(audit))
        self.assertNotIn('SECRET_', json.dumps(audit))

    def test_unknown_malformed_phase_fails_closed(self):
        for phase in ({'authority': True}, [], True, None, 'auto_execute'):
            value = fixture()
            value['teams']['graph']['phase'] = phase
            self.assertEqual(project(value, TEAM_IMPROVEMENT_EVIDENCE)['teams']['graph']['phase'], 'blocked')

    def test_metadata_clock_never_becomes_source_capture(self):
        row = project(fixture(), TEAM_IMPROVEMENT_EVIDENCE)['teams']['graph']
        self.assertEqual(row['shadow']['clock_field'], 'generated_at')
        self.assertIsNone(row['shadow']['captured_at'])
        self.assertEqual(row['shadow']['value'], 507)

    def test_renderer_is_read_only_and_explains_phases(self):
        html = (ROOT / 'index.html').read_text(encoding='utf8')
        renderer = html.split('function renderTeamImprovement(projection){', 1)[1].split('function renderAgentPlan(plan){', 1)[0]
        self.assertIn('textContent', renderer)
        for forbidden in ('innerHTML', 'fetch(', 'onclick', 'addEventListener', 'localStorage', 'POST'):
            self.assertNotIn(forbidden, renderer)
        for text in ('그림자 검증 보고', '정책 적용 보고', '실측 개선이 아닙니다', '인증된 사람 승인'):
            self.assertIn(text, renderer)
        self.assertIn('renderTeamImprovement(d.team_improvement_evidence)', html)
        self.assertIn('id="operations-audit"', html)
        self.assertIn('id="team-improvement-evidence"', html)


if __name__ == '__main__':
    unittest.main()
