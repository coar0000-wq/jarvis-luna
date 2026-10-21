"""Offline structural 8 -> 7 regression. Fixtures are synthetic, not lost run bytes.

The two retired IDs, new ID and removed summary token reproduce the observed
failure shape. No HTS lookup or other network request is permitted in tests.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import legal_export_history as hist, prepare_legal_export as prep, publish_transaction as pub
from scripts.immutable_snapshot_store import load_snapshots

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / 'config/publish_policy.json').read_bytes())
OLD = ['1049276', '1055167', '1067498', '1068721', '1074979', '1049275', '1053482', '1068733']
NEW = OLD[:-2] + ['1072800']
AT = '2026-10-12T00:00:00+00:00'


def sources(keys):
    return {
        hist.LEGAL: {'items': {k: {'name': 'Synthetic ' + k, 'status': 'pending', 'hs_code': '',
                                  'hard_block': True, 'hard_block_reason': 'Human review required'} for k in keys}, 'out_of_scope': {}},
        hist.SOURCES[1]: {'items': {k: {'ingredients': '', 'origin': '한국', 'volume': '', 'maker': ''} for k in keys}},
        hist.SOURCES[2]: {'all_scored': [{'pd_no': k, 'bucket': '스킨케어', 'grade': 'S', 'name': 'Synthetic ' + k} for k in keys]},
        hist.SOURCES[3]: {'items': [{'pd_no': k, 'copy': None} for k in keys]},
    }


def put(root, name, raw):
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=True)
    return result.stdout


class LegalExportHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'work'
        self.root.mkdir()
        self.network = patch('urllib.request.urlopen', side_effect=AssertionError('Live HTS forbidden'))
        self.network.start(); self.addCleanup(self.network.stop)
        self.lookup = patch.object(prep, 'hts_lookup', return_value=[])
        self.lookup.start(); self.addCleanup(self.lookup.stop)
        old = sources(OLD + ['1072800'])
        old[hist.LEGAL]['items'].pop('1072800')
        old[hist.SOURCES[1]]['items']['1053482']['origin'] = ''
        self.base = hist.encode(prep.build_report(old, AT)[0])
        for name, doc in old.items():
            put(self.root, name, hist.encode(doc))
        put(self.root, hist.REPORT, self.base)
        put(self.root, 'config/publish_policy.json', hist.encode(POLICY))
        git(self.root, 'init', '-b', 'main')
        git(self.root, 'config', 'user.name', 'Offline test')
        git(self.root, 'config', 'user.email', 'offline@example.invalid')
        git(self.root, 'add', '.')
        git(self.root, 'commit', '-m', 'synthetic baseline')
        self.docs = deepcopy(old)
        self.docs[hist.LEGAL] = sources(NEW)[hist.LEGAL]
        for key in OLD[-2:]:
            self.docs[hist.LEGAL]['out_of_scope'][key] = {'row': old[hist.LEGAL]['items'][key],
                '왜_뺐나': 'No longer in canonical current S scope', '뺀_시각': '2026-10-17T00:00:00+00:00'}
        self.write_sources()

    def write_sources(self):
        for name, doc in self.docs.items():
            put(self.root, name, hist.encode(doc))

    def publish(self):
        return hist.publish_export(self.root, prep.build_report)

    def evidence(self):
        current = (self.root / hist.REPORT).read_bytes()
        manifest = hist.parse((self.root / hist.MANIFEST).read_bytes())
        evidence = hist.load_evidence(self.root, self.base, current, manifest)
        return current, manifest, evidence

    def test_eight_to_seven_exact_snapshot_and_narrow_manifest(self):
        original = {n: (self.root / n).read_bytes() for n in hist.SOURCES}
        value = self.publish()
        current, manifest, evidence = self.evidence()
        self.assertEqual(value['total'], 7)
        self.assertEqual(evidence['record']['inactive_ids'], ['1053482', '1068733'])
        self.assertEqual(evidence['record']['added_ids'], ['1072800'])
        self.assertEqual(evidence['record']['removed_tokens'], ['1053482', '1068733', '원산지'])
        self.assertEqual(evidence['archives'][hist.sha(self.base)], self.base)
        self.assertEqual(evidence['archives'][hist.sha(current)], current)
        for raw in original.values():
            self.assertEqual(evidence['archives'][hist.sha(raw)], raw)
        legal_after = hist.parse((self.root / hist.LEGAL).read_bytes())
        for key in NEW:
            self.assertEqual(legal_after['items'][key]['status'], 'pending')
            self.assertTrue(legal_after['items'][key]['hard_block'])
        self.assertEqual(legal_after['out_of_scope'], self.docs[hist.LEGAL]['out_of_scope'])
        self.assertEqual(pub.overlay(hist.REPORT, self.base, current, self.base, POLICY, manifest,
                                     export_evidence=evidence), current)
        hist.verify_final(self.root, self.base, current, evidence)
        pub.Transaction(self.root, 'data', 'offline capture')

    def test_unchanged_is_idempotent_and_reentry_retains_inactive_draft(self):
        self.publish()
        before = {p.relative_to(self.root): p.read_bytes() for p in (self.root / 'data').rglob('*.json')}
        self.publish()
        after = {p.relative_to(self.root): p.read_bytes() for p in (self.root / 'data').rglob('*.json')}
        self.assertEqual(before, after)
        first, _, evidence = self.evidence()
        self.docs = {n: hist.parse((self.root / n).read_bytes()) for n in hist.SOURCES}
        legal = self.docs[hist.LEGAL]
        legal['items']['1053482'] = legal['out_of_scope'].pop('1053482')['row']
        for name in hist.SOURCES[1:]:
            extra = sources(['1053482'])[name]
            key = 'all_scored' if name == hist.SOURCES[2] else 'items'
            if isinstance(extra[key], dict): self.docs[name][key].update(extra[key])
            else:
                present = {r['pd_no'] for r in self.docs[name][key]}
                self.docs[name][key].extend(r for r in extra[key] if r['pd_no'] not in present)
        self.write_sources()
        self.publish()
        current, _, second = self.evidence()
        self.assertEqual(hist.parse(current)['total'], 8)
        self.assertEqual(second['archives'][hist.sha(first)], first)
        self.assertTrue(set(evidence['archives']) <= set(second['archives']))
        self.assertEqual(second['record']['inactive_ids'], ['1068733'])

    def test_full_hts_observations_support_label_beyond_visible_six_rows(self):
        observations = [{'htsno': str(i), 'description': 'Synthetic lookup row'} for i in range(6)]
        observations.append({'htsno': '3304.99', 'description': 'Synthetic late matching description'})
        with patch.object(prep, 'hts_lookup', return_value=observations):
            value = self.publish()
        self.assertEqual(value['items'][0]['hs']['label'], 'Synthetic late matching description')
        self.assertEqual(len(value['items'][0]['hs']['official']), 6)
        current, _, evidence = self.evidence()
        self.assertIn(observations, hist.parse(evidence['archives'][evidence['record']['hts_observations_sha256']]).values())
        hist.verify_final(self.root, self.base, current, evidence)
        broken = deepcopy(evidence)
        del broken['archives'][broken['record']['hts_observations_sha256']]
        with self.assertRaises((ValueError, KeyError)): hist.verify_evidence(self.base, current, broken)

    def test_committed_report_can_be_regenerated_on_new_head(self):
        self.publish()
        first = (self.root / hist.REPORT).read_bytes()
        git(self.root, 'add', 'data')
        git(self.root, 'commit', '-m', 'retained generated report')
        self.publish()
        self.assertEqual((self.root / hist.REPORT).read_bytes(), first)
        manifest = hist.parse((self.root / hist.MANIFEST).read_bytes())
        hist.load_evidence(self.root, first, first, manifest)
        tx = pub.Transaction(self.root, 'data', 'unchanged report evidence')
        self.assertNotIn(hist.REPORT, tx.delta)
        self.assertIsNotNone(tx.export_evidence)
        # A subsequent unchanged invocation changes neither report nor evidence.
        retained = load_snapshots(self.root, hist.HISTORY)
        self.publish()
        self.assertEqual(retained, load_snapshots(self.root, hist.HISTORY))

    def test_malformed_missing_empty_and_duplicate_inputs_preserve_good_report(self):
        for name in hist.SOURCES:
            original = (self.root / name).read_bytes()
            for bad in (None, b'{', b'{}', b'{"items":{}}', b'{"items":{},"items":{}}', b'{"n":NaN}'):
                with self.subTest(name=name, bad=bad):
                    if bad is None: (self.root / name).unlink()
                    else: put(self.root, name, bad)
                    with self.assertRaises((ValueError, OSError, TypeError, KeyError)):
                        self.publish()
                    self.assertEqual((self.root / hist.REPORT).read_bytes(), self.base)
                    self.assertFalse((self.root / hist.HISTORY).exists())
                    put(self.root, name, original)
        self.docs[hist.SOURCES[2]]['all_scored'].append(self.docs[hist.SOURCES[2]]['all_scored'][0])
        self.write_sources()
        with self.assertRaises(ValueError): self.publish()

    def test_missing_or_invalid_legal_safety_fields_never_default_to_unblocked(self):
        original = deepcopy(self.docs[hist.LEGAL])
        for key, value in [('hard_block', None), ('hard_block_reason', None), ('status', None),
                           ('hard_block', 'false'), ('hard_block_reason', ''), ('status', 'approved')]:
            self.docs[hist.LEGAL] = deepcopy(original)
            row = self.docs[hist.LEGAL]['items'][NEW[0]]
            if value is None: row.pop(key)
            else: row[key] = value
            self.write_sources()
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): self.publish()
            self.assertEqual((self.root / hist.REPORT).read_bytes(), self.base)
            self.assertFalse((self.root / hist.HISTORY).exists())

    def test_fresh_counter_must_bind_actual_prefill_sources(self):
        self.publish()
        current, manifest, evidence = self.evidence()
        self.assertEqual(hist.parse(current)['hs_filled_this_run'], 7)
        forged = hist.parse(current); forged['hs_filled_this_run'] = 0
        forged = hist.encode(forged)
        with self.assertRaises(ValueError):
            hist.transition(self.base, self.base, forged,
                {n: evidence['archives'][h] for n, h in evidence['record']['source_sha256'].items()},
                evidence['archives'][evidence['record']['published_legal_sha256']],
                evidence['archives'][evidence['record']['hts_observations_sha256']])
        # Claiming that the forged snapshot is also the previous one cannot
        # turn an uncommitted fresh counter into authenticated history.
        with self.assertRaises(ValueError):
            hist.transition(self.base, forged, forged,
                {n: evidence['archives'][h] for n, h in evidence['record']['source_sha256'].items()},
                evidence['archives'][evidence['record']['published_legal_sha256']],
                evidence['archives'][evidence['record']['hts_observations_sha256']])
        # Exact unchanged report keeps its historical count on the next call.
        self.publish()
        self.assertEqual((self.root / hist.REPORT).read_bytes(), current)
        hist.verify_final(self.root, self.base, current, evidence)

    def test_changed_inputs_recompute_counter_and_keep_previous_exact_report(self):
        self.publish()
        first = (self.root / hist.REPORT).read_bytes()
        path = self.root / hist.SOURCES[1]
        doc = hist.parse(path.read_bytes()); doc['extra_observation_note'] = 'new input bytes'
        path.write_bytes(hist.encode(doc))
        self.publish()
        current, _, evidence = self.evidence()
        self.assertEqual(hist.parse(current)['hs_filled_this_run'], 0)
        self.assertEqual(evidence['archives'][hist.sha(first)], first)

    def test_removed_identity_requires_archive_reason_even_when_snapshot_exists(self):
        for bad in ({}, {'row': {}, '왜_뺐나': '', '뺀_시각': AT}):
            self.docs[hist.LEGAL]['out_of_scope']['1053482'] = bad
            self.write_sources()
            with self.assertRaises(ValueError): self.publish()
            self.assertEqual((self.root / hist.REPORT).read_bytes(), self.base)

    def test_missing_forged_manifest_history_hash_and_generic_waivers_rejected(self):
        self.publish()
        current, manifest, evidence = self.evidence()
        for field, replacement in [('base_sha256', '0'*64), ('replacement_sha256', '0'*64),
                ('transition_sha256', '0'*64), ('ids', ['1053482']), ('policy_ref', 'invented'),
                ('delete_file', True)]:
            bad = deepcopy(manifest); bad['deletions'][0][field] = replacement
            with self.subTest(field=field), self.assertRaises(pub.PublishError):
                pub.overlay(hist.REPORT, self.base, current, self.base, POLICY, bad, export_evidence=evidence)
        for bad in (None, {}, dict(evidence, archives={})):
            with self.assertRaises(pub.PublishError):
                pub.overlay(hist.REPORT, self.base, current, self.base, POLICY, manifest, export_evidence=bad)
        bad = deepcopy(evidence); bad['record']['active_ids'] = ['forged']
        with self.assertRaises(pub.PublishError):
            pub.overlay(hist.REPORT, self.base, current, self.base, POLICY, manifest, export_evidence=bad)
        bad = deepcopy(evidence); bad['archives'][hist.sha(self.base)] = b'{}'
        with self.assertRaises(pub.PublishError):
            pub.overlay(hist.REPORT, self.base, current, self.base, POLICY, manifest, export_evidence=bad)
        self.assertFalse(pub.deletion_authorized('data/other.json', self.base,
            evidence['record']['removed_tokens'], {'deletions': [dict(manifest['deletions'][0], path='data/other.json')]}, replacement=current))
        path = next((self.root / hist.HISTORY).glob('*.json')); path.write_bytes(b'{}')
        with self.assertRaises(ValueError): self.publish()

    def test_removed_fields_in_old_or_new_reports_and_forged_projection_rejected(self):
        self.publish()
        current, manifest, evidence = self.evidence()
        for mutate in (lambda d: d.pop('hs_주의'), lambda d: d['items'][0].pop('제조업자'),
                lambda d: d['items'][0]['label']['draft'].pop('warnings'),
                lambda d: d['items'][0].update(hard_block=False),
                lambda d: d['items'][0].update(name='invented'),
                lambda d: d['items'][0]['hs'].update(code='forged'),
                lambda d: d.update(사람이_채워야_하는_칸=[])):
            changed = hist.parse(current); mutate(changed); changed = hist.encode(changed)
            with self.assertRaises((ValueError, KeyError, TypeError)):
                hist.transition(self.base, self.base, changed,
                    {n: evidence['archives'][h] for n, h in evidence['record']['source_sha256'].items()},
                    evidence['archives'][evidence['record']['published_legal_sha256']],
                    evidence['archives'][evidence['record']['hts_observations_sha256']])
        before = hist.parse(self.base); before['extra_field'] = 'must never silently disappear'
        with self.assertRaises(ValueError): hist.validate_report(hist.encode(before))

    def test_captured_evidence_manifest_and_inputs_cannot_be_omitted(self):
        self.docs[hist.SOURCES[1]]['items'][NEW[0]]['volume'] = 'synthetic updated quantity'
        self.write_sources()
        self.publish()
        for paths in (hist.REPORT, hist.REPORT + ' ' + hist.MANIFEST,
                      hist.REPORT + ' ' + hist.HISTORY + ' ' + hist.MANIFEST):
            with self.subTest(paths=paths), self.assertRaises(pub.PublishError):
                pub.Transaction(self.root, paths, 'omitted evidence')
        original = pub.Transaction.capture
        def racing_capture(tx):
            captured = original(tx)
            put(self.root, hist.SOURCES[1], b'{}')
            return captured
        with patch.object(pub.Transaction, 'capture', racing_capture), self.assertRaises(pub.PublishError):
            pub.Transaction(self.root, 'data', 'changed input')

    def test_capture_after_derived_regeneration_rechecks_semantics_and_scope(self):
        self.publish()
        for name, timestamp in ((hist.LEGAL, 'auto_checked_at'), (hist.SOURCES[2], 'generated_at')):
            path = self.root / name
            doc = hist.parse(path.read_bytes()); doc[timestamp] = '2026-10-21T00:00:00+00:00'
            path.write_bytes(hist.encode(doc))
        tx = pub.Transaction(self.root, 'data', 'after offline commerce regeneration')
        self.assertIsNotNone(tx.export_evidence)
        for name, mutation in ((hist.LEGAL, lambda d: d['items'][NEW[0]].update(hard_block=False)),
                (hist.SOURCES[2], lambda d: d['all_scored'][0].update(grade='A')),
                (hist.LEGAL, lambda d: d['out_of_scope'].pop('1053482'))):
            path = self.root / name; original = path.read_bytes()
            doc = hist.parse(original); mutation(doc); path.write_bytes(hist.encode(doc))
            with self.subTest(name=name), self.assertRaises(pub.PublishError):
                pub.Transaction(self.root, 'data', 'changed derived semantics')
            path.write_bytes(original)
        # Non-derived source updates still require fresh producer evidence,
        # even when they affect only metadata and leave the projection unchanged.
        path = self.root / hist.SOURCES[1]
        doc = hist.parse(path.read_bytes()); doc['generated_at'] = AT
        path.write_bytes(hist.encode(doc))
        with self.assertRaises(pub.PublishError): pub.Transaction(self.root, 'data', 'stale raw evidence')

    def test_concurrent_producer_inputs_manifest_head_report_fail_closed(self):
        original = hist.retain_snapshots
        for name in (*hist.SOURCES, hist.MANIFEST, hist.REPORT):
            with self.subTest(name=name):
                self.write_sources(); put(self.root, hist.REPORT, self.base)
                (self.root / hist.MANIFEST).unlink(missing_ok=True)
                def racing(*args, **kwargs):
                    result = original(*args, **kwargs)
                    put(self.root, name, b'{"concurrent":"must survive"}')
                    return result
                with patch.object(hist, 'retain_snapshots', racing), self.assertRaises(ValueError): self.publish()
                self.assertEqual((self.root / name).read_bytes(), b'{"concurrent":"must survive"}')
                if name != hist.REPORT: self.assertEqual((self.root / hist.REPORT).read_bytes(), self.base)
        self.write_sources(); put(self.root, hist.REPORT, self.base)
        (self.root / hist.MANIFEST).unlink(missing_ok=True)
        with patch.object(hist, 'revision', side_effect=[b'old', b'new']), self.assertRaises(ValueError): self.publish()
        put(self.root, hist.LOCK, b'busy')
        with self.assertRaises(FileExistsError): self.publish()

    def test_concurrent_remote_export_and_immutable_deletion_blocked(self):
        self.publish()
        current, manifest, evidence = self.evidence()
        for remote in (None, b' ' + self.base, b' ' + current):
            with self.assertRaises(pub.PublishError):
                pub.overlay(hist.REPORT, self.base, current, remote, POLICY, manifest, export_evidence=evidence)
        name = hist.HISTORY + '/' + hist.sha(self.base) + '.json'
        for local, remote in ((None, self.base), (b'{}', self.base), (self.base, b' ' + self.base)):
            with self.assertRaises(pub.PublishError): pub.overlay(name, self.base, local, remote, POLICY, manifest)
        for bad in ('wrong/', 'aa/bb/', '00/'):
            if bad == hist.sha(self.base)[:2] + '/': continue
            with self.assertRaises(pub.PublishError):
                pub.overlay(hist.HISTORY + '/' + bad + hist.sha(self.base) + '.json', None, self.base, None, POLICY, {})

    def test_final_canonical_changes_and_lost_history_blocked(self):
        self.publish()
        current, _, evidence = self.evidence()
        gosi_path = self.root / hist.SOURCES[1]
        original = gosi_path.read_bytes()
        changed = hist.parse(original); changed['items'][NEW[0]]['origin'] = 'different'
        gosi_path.write_bytes(hist.encode(changed))
        with self.assertRaises(ValueError): hist.verify_final(self.root, self.base, current, evidence)
        gosi_path.write_bytes(original)
        path = next((self.root / hist.HISTORY).glob('*.json')); path.unlink()
        with self.assertRaises((ValueError, KeyError)): hist.verify_final(self.root, self.base, current, evidence)

    def test_actual_transaction_offline_final_validation_and_history_union(self):
        remote = Path(self.temp.name) / 'remote.git'
        git(self.root, 'init', '--bare', str(remote))
        git(self.root, 'remote', 'add', 'origin', str(remote))
        git(self.root, 'push', '-u', 'origin', 'main')
        self.publish()
        # Derived canonical sources are regenerated by the real publisher. Use
        # captured fixture bytes instead of invoking live/large commerce work.
        raws = {n: (self.root / n).read_bytes() for n in hist.SOURCES}
        def offline_regeneration(tx, work, baseline, remote_changed, report_dir):
            for n, raw in raws.items(): put(work, n, raw)
        other = Path(self.temp.name) / 'other'
        git(self.root, 'clone', '--branch', 'main', str(remote), str(other))
        git(other, 'config', 'user.name', 'Offline concurrent writer')
        git(other, 'config', 'user.email', 'offline@example.invalid')
        remote_history = b' ' + self.base
        remote_path = hist.HISTORY + '/' + hist.sha(remote_history) + '.json'
        put(other, remote_path, remote_history)
        git(other, 'add', 'data'); git(other, 'commit', '-m', 'independent retained draft')
        git(other, 'push', 'origin', 'main')
        original_verify = hist.verify_final
        def verify_union(work, *args):
            self.assertEqual((work / remote_path).read_bytes(), remote_history)
            return original_verify(work, *args)
        with patch.object(pub.Transaction, 'regenerate_and_validate', offline_regeneration), patch.object(hist, 'verify_final', verify_union):
            tx = pub.Transaction(self.root, 'data', 'offline dry run', dry_run=True)
            result = tx.run()
        self.assertEqual(result['status'], 'dry_run_validated')
        self.assertTrue(result['attempts'][0]['validated'])


if __name__ == '__main__':
    unittest.main()
