"""Native offline tests. python -E -X utf8 -B -m unittest discover -s scripts -p test_team_improvement_evidence.py"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import team_improvement_evidence as m

NOW = '2026-10-05T08:00:00Z'
STAMP = '2026-10-03T11:43:28Z'


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = {}
        cards = {t: {'state': '양호', 'open_kind': '', 'open_action': '',
                     'summary': 'private identity email password NOT FOR OUTPUT'} for t in m.TEAM_IDS}
        for tid, kind in [('sourcing', 'auto_remediable'), ('listing', 'human_approval_required'),
                          ('legal', 'human_approval_required'), ('design', 'external_dependency')]:
            cards[tid].update(state='정체', open_kind=kind, open_action='sensitive customer token')
        self.docs = {
            m.DIAGNOSTIC: {'generated_at': '2026-10-05T07:04:21Z', 'teams': cards,
                'summary': {'teams': 11, '양호': 7, '정체': 4, '개선': 0}},
            m.STATUS: {'generated_at': STAMP, 'loops': {'topics': {
                'metric': 'uncategorized_rate', 'records': 6955,
                'uncategorized_before': 512, 'uncategorized_after_shadow': 507,
                'before': .0736, 'after_shadow': .0729,
                'evaluation': {'mode': 'production_classifier_replay', 'evaluated_records': 6955}}}},
            m.TOPICS: {'updated_at': STAMP, 'generator': 'scripts/self_improve.py'},
            m.SOURCING: {'generator': 'scripts/self_improve.py', 'enabled': True,
                'adopted_at': '2026-09-28T11:12:52Z', 'skip_full_expected_bucket': True,
                'open_buckets_first': True,
                'baseline': {'started_at': '2026-09-20T21:36:32Z', 'requested': 110, 'ok': 3, 'useful_rate': 3/110},
                'observations': [{'started_at': '2026-09-28T23:50:54Z', 'requested': 110, 'ok': 10, 'useful_rate': 10/110}]},
            m.DESIGN: {'generator': 'scripts/self_improve.py', 'updated_at': '2026-09-28T19:14:53Z',
                'enabled': True, 'version': 1, 'feed_caps': {'web.dev': 3}},
            m.BOARD: {'generated_at': '2026-10-04T07:13:43Z', 'references': {
                'quality': {'items': 78, 'relevant': 34, 'relevant_ratio': .436},
                'policy': {'applied': True, 'feed_caps': {'web.dev': 3}, 'policy_version': 1, 'dropped': 7}}},
        }
        self.save_all()

    def tearDown(self):
        self.temp.cleanup()

    def save_all(self):
        for rel, doc in self.docs.items():
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = json.dumps(doc, ensure_ascii=False).encode()
            target.write_bytes(raw)
            self.manifest[rel] = hashlib.sha256(raw).hexdigest()

    def build(self, **kw):
        return m.build(self.root, now=kw.pop('now', NOW), reviewed_sha256=self.manifest, **kw)

    def test_all_eleven_and_pilots(self):
        out = self.build()
        self.assertEqual(set(out['teams']), set(m.TEAM_IDS))
        self.assertEqual(out['summary']['teams'], 11)
        self.assertNotIn('secretary', out['teams'])
        self.assertEqual(out['teams']['graph']['phase'], 'shadow_evaluated')
        self.assertEqual(out['teams']['graph']['baseline']['value'], 512)
        self.assertEqual(out['teams']['graph']['shadow']['value'], 507)
        self.assertEqual(out['teams']['sourcing']['phase'], 'applied')
        self.assertEqual(out['teams']['sourcing']['baseline']['value'], 3)
        self.assertEqual(out['teams']['sourcing']['current']['value'], 10)
        self.assertEqual(out['teams']['design']['phase'], 'applied')
        self.assertIsNone(out['teams']['design']['baseline'])
        self.assertEqual(out['teams']['design']['current']['value'], 34)
        self.assertEqual(out['teams']['design']['existing_bounded_configuration']['dropped_references'], 7)
        self.assertEqual(out['diagnostic_monitoring']['clear'], 7)
        self.assertEqual(out['diagnostic_monitoring']['stuck'], 4)
        self.assertEqual(out['summary']['verified_gains'], 0)

    def test_disappearance_never_gain(self):
        self.docs[m.DIAGNOSTIC]['teams']['listing'].update(state='개선', open_kind='', open_action='')
        self.docs[m.DIAGNOSTIC]['summary']['개선'] = 1
        self.docs[m.DIAGNOSTIC]['summary']['정체'] = 3
        self.save_all()
        out = self.build()
        self.assertEqual(out['summary']['verified_gains'], 0)
        for team in out['teams'].values():
            self.assertFalse(team['verified_gain'])
            self.assertFalse(team['authority'])
            self.assertFalse(team['business_clearance'])
            self.assertFalse(team['autonomous_change_allowed'])
        self.assertNotIn('7 teams improving', json.dumps(out))
        self.assertNotEqual(out['teams']['listing']['phase'], 'verified_gain')

    def test_metadata_is_not_capture_or_evaluation(self):
        out = self.build()
        for team in out['teams'].values():
            for source in team['evidence']:
                self.assertIsNone(source['captured_at'])
                self.assertIsNone(source['evaluated_at'])
                self.assertFalse(source['capture_clock_verified'])
        point = out['teams']['sourcing']['current']
        self.assertEqual(point['clock_field'], 'observations[0].started_at')
        self.assertIsNone(point['captured_at'])
        self.assertIsNone(out['teams']['graph']['shadow']['evaluated_at'])

    def test_explicit_capture_preserved_not_generated(self):
        self.docs[m.BOARD]['captured_at'] = '2026-10-04T06:00:00Z'
        self.save_all()
        point = self.build()['teams']['design']['current']
        self.assertEqual(point['captured_at'], '2026-10-04T06:00:00+00:00')
        self.assertNotEqual(point['captured_at'], point['clock_at'])

    def test_missing_evidence(self):
        (self.root / m.STATUS).unlink()
        out = self.build()
        self.assertEqual(out['teams']['graph']['phase'], 'blocked')
        self.assertIsNone(out['teams']['graph']['shadow'])
        self.assertEqual(out['teams']['sourcing']['phase'], 'applied')

    def test_unknown_team_blocks_all(self):
        self.docs[m.DIAGNOSTIC]['teams']['secretary'] = {'state': '양호', 'open_kind': ''}
        self.save_all()
        self.assertEqual(self.build()['summary']['phase_counts']['blocked'], 11)

    def test_modified_source_and_forged_hash(self):
        doc = self.docs[m.STATUS]
        doc['sha256'] = self.manifest[m.STATUS]
        doc['loops']['topics']['uncategorized_after_shadow'] = 0
        (self.root / m.STATUS).write_text(json.dumps(doc), encoding='utf-8')
        self.assertEqual(self.build()['teams']['graph']['phase'], 'blocked')
        self.assertIsNone(self.build()['teams']['graph']['shadow'])

    def test_unsupported_business_metric(self):
        self.docs[m.STATUS]['loops']['topics']['metric'] = 'sales_conversion_rate'
        self.save_all()
        self.assertEqual(self.build()['teams']['graph']['phase'], 'blocked')
        for team in self.build()['teams'].values():
            self.assertFalse(team['metric']['business_metric'])

    def test_stale_historical_pilot(self):
        # Refresh diagnostics, not the old pilot: new metadata never proves old gain.
        self.docs[m.DIAGNOSTIC]['generated_at'] = '2026-11-01T07:00:00Z'
        self.save_all()
        out = self.build(now='2026-11-01T08:00:00Z')
        for tid in ('graph', 'sourcing', 'design'):
            self.assertEqual(out['teams'][tid]['phase'], 'blocked')
            self.assertFalse(out['teams'][tid]['autonomous_change_allowed'])
        self.assertFalse(out['teams']['sourcing']['evidence'][1]['fresh'])
        self.assertEqual(out['summary']['verified_gains'], 0)

    def test_privacy_and_volume(self):
        self.docs[m.BOARD]['references']['items'] = [{'email': 'PRIVATE@EXAMPLE.COM', 'token': 'SECRET123'}]
        self.save_all()
        raw = json.dumps(self.build())
        for token in ('PRIVATE@EXAMPLE.COM', 'SECRET123', 'sensitive customer', 'private identity', str(self.root)):
            self.assertNotIn(token, raw)
        self.assertLess(len(raw.encode()), m.MAX_OUTPUT_BYTES)

    def test_malformed_and_unknown_sources(self):
        (self.root / m.STATUS).write_bytes(b'{broken')
        self.manifest[m.STATUS] = hashlib.sha256(b'{broken').hexdigest()
        self.assertEqual(self.build()['teams']['graph']['phase'], 'blocked')
        self.manifest['credentials.json'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'unknown_source_path'):
            self.build()

    def test_future_naive_clocks_and_invalid_counts(self):
        self.docs[m.STATUS]['generated_at'] = '2027-01-01T00:00:00Z'
        self.save_all()
        self.assertEqual(self.build()['teams']['graph']['phase'], 'blocked')
        self.docs[m.STATUS]['generated_at'] = '2026-10-03T11:43:28'
        self.save_all()
        self.assertEqual(self.build()['teams']['graph']['phase'], 'blocked')
        self.docs[m.STATUS]['generated_at'] = STAMP
        self.docs[m.STATUS]['loops']['topics']['records'] = True
        self.save_all()
        self.assertEqual(self.build()['teams']['graph']['phase'], 'blocked')

    def test_inconsistent_diagnostics_fail_closed(self):
        self.docs[m.DIAGNOSTIC]['summary']['양호'] = 10
        self.save_all()
        self.assertEqual(self.build()['summary']['phase_counts']['blocked'], 11)

    def test_stale_values_labeled_historical(self):
        self.docs[m.DIAGNOSTIC]['generated_at'] = '2026-10-15T07:00:00Z'
        self.save_all()
        out = self.build(now='2026-10-15T08:00:00Z')
        self.assertEqual(out['teams']['sourcing']['phase'], 'blocked')
        self.assertEqual(out['teams']['sourcing']['current']['value'], 10)
        self.assertTrue(out['teams']['sourcing']['historical_observation_only'])
        self.assertFalse(out['teams']['sourcing']['current']['fresh'])

    def test_read_only_deterministic(self):
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(self.build(), self.build())
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_refresh_monitoring_without_pilot_authority(self):
        out = m.build(self.root, now=NOW)
        self.assertEqual(out['teams']['institutions']['phase'], 'monitoring')
        self.assertEqual(out['diagnostic_monitoring']['clear'], 7)
        self.assertFalse(out['diagnostic_monitoring']['source']['reviewed_exact_bytes'])
        for tid in ('graph', 'sourcing', 'design'):
            self.assertEqual(out['teams'][tid]['phase'], 'blocked')
        self.assertEqual(out['summary']['verified_gains'], 0)


if __name__ == '__main__':
    unittest.main()
