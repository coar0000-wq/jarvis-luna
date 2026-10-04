#!/usr/bin/env python3
"""Offline synthetic operations fixtures; never read credentials or build repo dist."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from build_public_site import ROOT, STATIC_FILES, SCHEMAS, OPERATIONS, build, project, encoded

RUNTIME = 'data/dashboard_runtime.json'
STAMP = '2026-10-03T19:30:00+09:00'


def fixture():
    return {
        'schema_version': 1, 'generated_at': STAMP, 'status': 'blocked',
        'organization': '기존 비서실장 > 11팀 팀장 > 전문 기능',
        'engines': [{'id': 'verification', 'name': '로컬 검증', 'status': 'verified', 'detail': '로컬 보고서 검증'}],
        'counts': {'tasks_total': 1, 'local_verified': 1, 'external_verified': 0,
                   'handoffs_accepted': 1, 'watchers_ready': 0, 'watchers_blocked': 11,
                   'events': 3, 'approval_waiting': 1},
        'tasks': [{'task_id': 'task-1', 'team': 'listing', 'kind': 'local_report', 'level': 'L2', 'state': 'verified'}],
        'watchers': [{'team': 'market', 'status': 'blocked', 'reason': '외부 연결 미설정', 'captured_at': STAMP}],
        'business': {'ready': 2, 'total': 5, 'exempt': 1, 'sales_allowed': False,
                     'blockers': ['RP 확인 필요', '안전성 근거 확인 필요', '영문 라벨 확인 필요']},
        'source_recovery': {'schema_version': 1, 'episodes': [{
            'recovery_id': 'recovery_market_000001', 'episode': 1, 'owner': 'market',
            'source_team': 'market', 'status': 'BLOCKED', 'attempts': 0, 'attempt_limit': 2,
            'escalation_code': None, 'receipt_id': None, 'first_detected_at': STAMP,
            'last_detected_at': STAMP, 'next_action': '실제 관찰 복구 후 재검증',
            'execution_enabled': False}]},
        'feedback': {'status': 'verified', 'verified_observations': 1, 'training_performed': False},
        'action_cards': [{'action_id': 'action-1', 'kind': 'external_draft', 'level': 'L4',
                          'status': 'waiting_approval', 'may_approve': False, 'may_execute': False,
                          'reason': '인증 승인 필요', 'member_count': 1, 'payload_hash': 'a' * 64,
                          'target_configured': False, 'before': '초안 없음', 'after': '외부 실행 전 초안'}]
    }


class OperationsPublicProjectionTests(unittest.TestCase):
    def test_contract_survives_without_changing_truth(self):
        source = fixture()
        public = project({'operations': source}, SCHEMAS[RUNTIME])['operations']
        self.assertEqual(public, source)
        self.assertEqual(public['counts']['external_verified'], 0)
        self.assertFalse(public['business']['sales_allowed'])
        self.assertFalse(public['feedback']['training_performed'])
        self.assertEqual(project(public, OPERATIONS), public)

    def test_recursive_extra_credentials_pii_and_execution_material_omitted(self):
        source = fixture()
        forbidden = {'raw_payload': {'credential': 'SECRET_PAYLOAD'}, 'proofs': ['PRIVATE_PROOF'],
                     'raw_goals': 'PRIVATE_GOAL', 'identity': 'PRIVATE_PERSON', 'nonce': 'PRIVATE_NONCE',
                     'target': 'PRIVATE_TARGET', 'private_paths': 'PRIVATE_PATH',
                     'backend_billing': 'PRIVATE_BILLING', 'models': 'PRIVATE_MODEL',
                     'api_key': 'SECRET_KEY', 'email': 'PRIVATE_EMAIL', 'address': 'PRIVATE_ADDRESS'}
        source.update(copy.deepcopy(forbidden))
        for value in (source['counts'], source['business'], source['feedback'], source['engines'][0],
                      source['tasks'][0], source['watchers'][0], source['action_cards'][0],
                      source['source_recovery'], source['source_recovery']['episodes'][0]):
            value.update(copy.deepcopy(forbidden))
        source['action_cards'][0]['before'] = {'raw_payload': 'SECRET_BEFORE'}
        source['action_cards'][0]['after'] = ['PRIVATE_AFTER']
        result = project(source, OPERATIONS)
        text = json.dumps(result)
        for marker in ('SECRET_', 'PRIVATE_'):
            self.assertNotIn(marker, text)
        self.assertIsNone(result['action_cards'][0]['before'])
        self.assertIsNone(result['action_cards'][0]['after'])
        self.assertEqual(set(result), set(OPERATIONS))
        self.assertEqual(project(result, OPERATIONS), result)

    def test_public_projection_cannot_grant_authority(self):
        source = fixture()
        source['action_cards'][0].update(may_approve=True, may_execute=True, approved=True, execute=True)
        card = project(source, OPERATIONS)['action_cards'][0]
        self.assertIs(card['may_approve'], False)
        self.assertIs(card['may_execute'], False)
        self.assertNotIn('approved', card)
        self.assertNotIn('execute', card)
        source['source_recovery']['episodes'][0].update(execution_enabled=True, approved=True,
                                                       nonce='PRIVATE_NONCE', raw_payload='SECRET_PAYLOAD')
        episode = project(source, OPERATIONS)['source_recovery']['episodes'][0]
        self.assertIs(episode['execution_enabled'], False)
        for private in ('approved', 'nonce', 'raw_payload'):
            self.assertNotIn(private, episode)

    def test_private_values_in_allowed_free_text_omitted(self):
        for private in ('owner@example.com', '+82 10 1234 5678', '010-1234-5678',
                        '123 Main Street', r'C:\Users\Private\secret.json', '/home/private/config',
                        'api_key: secretvalue', 'Bearer PRIVATE_TOKEN', 'billing $4',
                        'gpt-4o backend model', 'nonce: 123', 'identity: Alice'):
            with self.subTest(private=private):
                source = fixture()
                source['watchers'][0]['reason'] = private
                source['business']['blockers'] = [private]
                source['action_cards'][0]['before'] = private
                source['source_recovery']['episodes'][0]['next_action'] = private
                result = project(source, OPERATIONS)
                self.assertNotIn(private, json.dumps(result, ensure_ascii=False))

    def test_no_links_private_paths_or_arbitrary_nested_objects(self):
        for value in ('https://example.com/private?token=secret', 'file:///private',
                      'javascript:alert(1)', {'person': 'Alice'}, ['raw proof']):
            source = fixture()
            source['engines'][0]['detail'] = value
            self.assertIsNone(project(source, OPERATIONS)['engines'][0]['detail'])

    def test_single_nested_runtime_payload_no_inventory_growth(self):
        self.assertEqual(len(STATIC_FILES) + len(SCHEMAS), 30)
        self.assertEqual([name for name, schema in SCHEMAS.items() if 'operations' in schema], [RUNTIME])
        with tempfile.TemporaryDirectory(dir=ROOT.parent, prefix='operations-public-') as temp:
            root = Path(temp) / 'source'
            root.mkdir()
            for name in STATIC_FILES:
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b'fixture')
            for name in SCHEMAS:
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(encoded({'operations': fixture()} if name == RUNTIME else {}))
            with mock.patch('build_public_site.subprocess.check_output', side_effect=AssertionError('no git')):
                manifest = build(root, Path(temp) / 'dist', 'a' * 40)
            self.assertEqual(len(manifest['files']), 30)
            self.assertEqual(set(manifest['files']), set(STATIC_FILES) | set(SCHEMAS))
            public = json.loads((Path(temp) / 'dist' / RUNTIME).read_text(encoding='utf-8'))
            self.assertEqual(public['operations'], fixture())
            self.assertFalse((Path(temp) / 'dist/data/operations.json').exists())

    def test_readonly_ui_uses_text_nodes_and_disabled_approval(self):
        html = (ROOT / 'index.html').read_text(encoding='utf-8')
        renderer = html.split('function renderOperations(ops){', 1)[1].split('function renderAgentPlan(plan){', 1)[0]
        self.assertIn('textContent', renderer)
        self.assertNotIn('innerHTML', renderer)
        self.assertNotIn('insertAdjacentHTML', renderer)
        for forbidden in ('fetch(', 'localStorage', 'addEventListener', 'onclick', 'POST'):
            self.assertNotIn(forbidden, renderer)
        self.assertIn('button.disabled=true', renderer)
        self.assertIn('인증 승인 필요', renderer)
        self.assertIn('로컬 보고서 검증', renderer)
        self.assertIn('renderOperations(d.operations)', html)
        for selector in ('operations-engines', 'operations-counts', 'operations-business', 'operations-actions', 'operations-recovery'):
            self.assertIn('id="' + selector + '"', html)
        for team in ('sourcing', 'listing', 'channels', 'institutions', 'market', 'pricing', 'legal',
                     'robotics', 'design', 'knowledge', 'graph', 'secretary'):
            self.assertIn('images/teams/' + team + '.png', html)


if __name__ == '__main__':
    unittest.main(verbosity=2)
