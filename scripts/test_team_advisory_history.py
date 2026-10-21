"""Offline exact legacy snapshot -> synthetic current transitions, not lost run bytes."""
from copy import deepcopy
import contextlib
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import evaluate_team_typesafe as team, team_advisory_history as hist, publish_transaction as pub
from scripts.immutable_snapshot_store import load_snapshots, _scan

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / 'config/publish_policy.json').read_bytes())
# Exact committed report at 17dca1ce1fd3a3c4df94a1f61d58e2715f491b53,
# generated 2026-10-03. A fixture makes shallow CI independent of Git ancestry.
LEGACY = (ROOT / 'scripts/fixtures/typesafe_team_advisory_legacy.json').read_bytes()


def put(root, name, raw):
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=True).stdout


class OfflineTransaction(pub.Transaction):
    def regenerate_and_validate(self, work, baseline, remote_changed, report_dir):
        # The advisory is a generation-time observation. Later dashboard source
        # refreshes must not make it pretend to be a freshly evaluated result.
        put(work, 'data/dashboard_runtime.json', b'{"teams": []}\n')


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'work'
        self.root.mkdir()
        self.net = patch('urllib.request.urlopen', side_effect=AssertionError('Live provider forbidden'))
        self.net.start(); self.addCleanup(self.net.stop)
        put(self.root, hist.REPORT, LEGACY)
        put(self.root, 'config/publish_policy.json', hist.encode(POLICY))
        git(self.root, 'init', '-b', 'main')
        git(self.root, 'config', 'user.name', 'Offline test')
        git(self.root, 'config', 'user.email', 'offline@example.invalid')
        self.commit()
        self.payload = team.build_payload(self.root)

    def commit(self):
        git(self.root, 'add', '.')
        git(self.root, 'commit', '-m', 'offline fixture')

    def report(self, source='deterministic_local'):
        result = {'source': source, 'mode': 'proof_missing_or_invalid', 'answers': team.fallback(self.payload)}
        if source != 'deterministic_local':
            result.update(mode='typesafe_advisory' if source == 'typesafe' else 'typesafe_cached_advisory',
                          model=team.MODEL, usage={'input_tokens': 50, 'output_tokens': 20})
        return team.evaluate(self.payload, lambda *a, **kw: result)

    def publish(self, source='deterministic_local'):
        return hist.publish_advisory(self.root, self.report(source), self.payload)

    def evidence(self, base=LEGACY):
        current = (self.root / hist.REPORT).read_bytes()
        manifest = hist.parse((self.root / hist.MANIFEST).read_bytes())
        return current, manifest, hist.load_evidence(self.root, base, current, manifest)

    def test_legacy_exact_bytes_and_optional_metadata_removals(self):
        self.publish()
        current, manifest, evidence = self.evidence()
        self.assertEqual(evidence['archives'][hist.sha(LEGACY)], LEGACY)
        self.assertEqual(evidence['archives'][hist.sha(current)], current)
        self.assertEqual(evidence['record']['removed_tokens'], ['legend', 'probabilities', 'type'])
        self.assertEqual(evidence['record']['meaning'], hist.MEANING)
        doc = hist.validate_report(current)
        self.assertIsNone(doc['usage']); self.assertIsNone(doc['model'])
        self.assertFalse(doc['approval']); self.assertFalse(doc['enforced']); self.assertFalse(doc['paid_api_called'])
        self.assertEqual(set(doc['teams']), set(team.ROLES))
        self.assertNotIn('probabilities', doc['teams']['market']['quality'])
        self.assertEqual(pub.overlay(hist.REPORT, LEGACY, current, LEGACY, POLICY, manifest,
                                    team_advisory_evidence=evidence), current)
        pub.Transaction(self.root, 'data', 'offline capture')
        hist.verify_final(self.root, LEGACY, current, evidence)

    def test_remote_cache_local_transitions_keep_all_exact_snapshots(self):
        snapshots = {hist.sha(LEGACY): LEGACY}
        for source in ('typesafe', 'typesafe_cache', 'deterministic_local', 'deterministic_local', 'typesafe_cache'):
            self.publish(source)
            current, manifest, evidence = self.evidence()
            snapshots[hist.sha(current)] = current
            for digest, raw in snapshots.items():
                self.assertEqual(evidence['archives'][digest], raw)
            doc = hist.parse(current)
            self.assertIs(doc['paid_api_called'], source == 'typesafe')
            self.assertIs(doc['approval'], False)
            pub.Transaction(self.root, 'data', 'offline capture')

    def test_new_head_retains_and_validates_prior_transition(self):
        self.publish(); first, _, initial = self.evidence(); self.commit()
        self.publish('typesafe_cache')
        current, manifest, evidence = self.evidence(first)
        self.assertEqual(evidence['record']['baseline_sha256'], hist.sha(first))
        self.assertTrue(initial['archives'].items() <= evidence['archives'].items())
        pub.Transaction(self.root, 'data', 'offline capture')

    def test_authority_role_required_field_and_mirror_deletions_rejected(self):
        mutations = [lambda d: d.update(approval=True), lambda d: d.update(enforced=True),
                     lambda d: d['teams'].pop('legal'), lambda d: d['answers'].pop('legal_quality'),
                     lambda d: d['teams']['market'].pop('source'), lambda d: d.pop('scope'),
                     lambda d: d['teams']['legal'].update(approval=0),
                     lambda d: d['teams']['market']['quality'].update(score=3)]
        for change in mutations:
            doc = self.report(); change(doc)
            with self.subTest(change=change), self.assertRaises((ValueError, KeyError)):
                hist.publish_advisory(self.root, doc, self.payload)
        self.assertEqual((self.root / hist.REPORT).read_bytes(), LEGACY)
        self.assertFalse((self.root / hist.HISTORY).exists())

    def test_false_local_model_usage_and_fallback_answers_rejected(self):
        for key, value in (('model', team.MODEL), ('usage', {'input_tokens': 1}), ('paid_api_called', True)):
            doc = self.report(); doc[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                hist.publish_advisory(self.root, doc, self.payload)
        doc = self.report()
        doc['answers']['market_quality']['score'] = 3  # Aliased role value changes too.
        with self.assertRaisesRegex(ValueError, 'deterministic fallback'):
            hist.publish_advisory(self.root, doc, self.payload)

    def test_current_wrong_remote_model_rejected_legacy_retained(self):
        doc = self.report('typesafe'); doc['model'] = 'jev-1.13.0'
        with self.assertRaisesRegex(ValueError, 'requested model'):
            hist.publish_advisory(self.root, doc, self.payload)
        hist.validate_report(LEGACY)

    def test_generation_payload_must_match_real_sources(self):
        payload = deepcopy(self.payload); payload['state']['teams']['market']['has_waiting'] = True
        doc = team.evaluate(payload, lambda *a, **kw: {'source': 'deterministic_local', 'mode': 'disabled'})
        with self.assertRaisesRegex(ValueError, 'generation-time sources'):
            hist.publish_advisory(self.root, doc, payload)
        self.assertEqual((self.root / hist.REPORT).read_bytes(), LEGACY)

    def test_safe_payload_rejects_private_fields_and_bad_types_independently(self):
        mutations = [lambda p: p['state'].update(notes='private'),
                     lambda p: p['state']['teams']['market'].update(url='https://private.invalid'),
                     lambda p: p['state']['teams']['market'].update(learning={'notes': 'private'}),
                     lambda p: p['state']['teams']['market'].update(status='private text'),
                     lambda p: p['state']['teams']['market'].update(has_waiting='false'),
                     lambda p: p['state']['audits']['collector_audit'].update(personal_note='private')]
        for mutate in mutations:
            payload = deepcopy(self.payload); mutate(payload)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): hist.validate_safe_payload(payload)

    def test_manifest_missing_generic_extra_ids_and_tampered_archive_fail_closed(self):
        self.publish(); current, manifest, evidence = self.evidence()
        for change in (lambda m: m['deletions'].clear(),
                       lambda m: m['deletions'][0].update(policy_ref='scripts/collector_snapshot_history.py'),
                       lambda m: m['deletions'][0]['ids'].append('approval'),
                       lambda m: m['deletions'][0].pop('replacement_sha256')):
            bad = deepcopy(manifest); change(bad)
            self.assertFalse(pub.deletion_authorized(hist.REPORT, LEGACY, ['legend', 'probabilities', 'type'], bad,
                replacement=current, team_advisory_evidence=evidence))
        missing = deepcopy(evidence); missing['archives'].pop(hist.sha(LEGACY))
        with self.assertRaises(pub.PublishError):
            pub.overlay(hist.REPORT, LEGACY, current, LEGACY, POLICY, manifest, team_advisory_evidence=missing)
        digest = next(iter(evidence['archives']))
        _, paths, _, _ = _scan(self.root, hist.HISTORY)
        (self.root / paths[digest]).write_bytes(b'{}')
        with self.assertRaises(ValueError): self.publish()

    def test_usage_field_named_like_answer_metadata_cannot_borrow_waiver(self):
        old = hist.parse(LEGACY); old['usage']['type'] = 1
        base = hist.encode(old)
        with self.assertRaisesRegex(ValueError, 'outside optional answer metadata'):
            hist.transition(base, base, hist.encode(self.report('typesafe')), hist.encode(self.payload))
        # A local fallback legitimately has no current remote usage at all.
        hist.transition(base, base, hist.encode(self.report()), hist.encode(self.payload))

    def test_wrong_path_and_whole_file_delete_never_authorized(self):
        self.publish(); current, manifest, evidence = self.evidence()
        copied = deepcopy(manifest); copied['deletions'][0]['path'] = 'data/typesafe_advisory.json'
        self.assertFalse(pub.deletion_authorized('data/typesafe_advisory.json', LEGACY, ['type'], copied,
            replacement=current, team_advisory_evidence=evidence))
        self.assertFalse(pub.deletion_authorized(hist.REPORT, LEGACY, None, manifest,
            replacement=current, team_advisory_evidence=evidence))

    def test_capture_requires_report_manifest_and_every_archive_path(self):
        self.publish()
        for paths in (hist.REPORT, hist.REPORT + ' ' + hist.MANIFEST, hist.MANIFEST + ' ' + hist.HISTORY):
            with self.subTest(paths=paths), self.assertRaises(pub.PublishError):
                pub.Transaction(self.root, paths, 'offline incomplete capture')
        pub.Transaction(self.root, ' '.join((hist.REPORT, hist.MANIFEST, hist.HISTORY)), 'offline complete capture')

    def test_earlier_uncommitted_transition_and_observation_cannot_disappear(self):
        self.publish(); first, _, initial = self.evidence()
        first_record = hist.sha(hist.encode(initial['record']))
        self.publish('typesafe_cache'); self.publish('deterministic_local')
        _, paths, _, _ = _scan(self.root, hist.HISTORY)
        for digest in (first_record, hist.sha(first)):
            path = self.root / paths[digest]
            raw = path.read_bytes(); path.unlink()
            with self.subTest(digest=digest), self.assertRaises((ValueError, KeyError)): self.evidence()
            with self.assertRaises(pub.PublishError): pub.Transaction(self.root, 'data', 'incomplete chain')
            path.write_bytes(raw)

    def test_history_file_deletion_reformat_and_wrong_shard_fail(self):
        raw = LEGACY; digest = hist.sha(raw)
        for suffix in (digest + '.json', digest[:2] + '/' + digest + '.json'):
            path = hist.HISTORY + '/' + suffix
            self.assertEqual(pub.overlay(path, None, raw, None, POLICY, {}), raw)
            for local in (None, raw + b' '):
                with self.assertRaises(pub.PublishError): pub.overlay(path, raw, local, raw, POLICY, {})
        with self.assertRaises(pub.PublishError):
            pub.overlay(hist.HISTORY + '/zz/' + digest + '.json', None, raw, None, POLICY, {})

    def test_concurrent_advisory_replacement_never_merges(self):
        self.publish(); current, manifest, evidence = self.evidence()
        with self.assertRaises(pub.PublishError):
            pub.overlay(hist.REPORT, LEGACY, current, current + b' ', POLICY, manifest, team_advisory_evidence=evidence)

    def test_final_report_and_history_mutation_rejected(self):
        self.publish(); current, _, evidence = self.evidence()
        put(self.root, hist.REPORT, current + b' ')
        with self.assertRaisesRegex(ValueError, 'final team advisory bytes'): hist.verify_final(self.root, LEGACY, current, evidence)
        put(self.root, hist.REPORT, current)
        _, paths, _, _ = _scan(self.root, hist.HISTORY)
        (self.root / paths[hist.sha(LEGACY)]).unlink()
        with self.assertRaises((ValueError, KeyError)): hist.verify_final(self.root, LEGACY, current, evidence)

    def test_source_race_after_retention_prevents_current_replacement(self):
        retain = hist.retain_snapshots
        def change(*a, **kw):
            value = retain(*a, **kw)
            put(self.root, 'data/dashboard_runtime.json', b'{"teams": [{"id":"market","status":"blocked"}]}')
            return value
        with patch.object(hist, 'retain_snapshots', side_effect=change), self.assertRaisesRegex(ValueError, 'concurrent'):
            self.publish()
        self.assertEqual((self.root / hist.REPORT).read_bytes(), LEGACY)
        self.assertFalse((self.root / hist.MANIFEST).exists())

    def test_local_bare_transaction_preserves_historical_observation_after_regeneration(self):
        remote = Path(self.temp.name) / 'remote.git'
        git(self.root, 'clone', '--bare', str(self.root), str(remote))
        git(self.root, 'remote', 'add', 'origin', str(remote))
        self.publish()
        with contextlib.redirect_stdout(io.StringIO()):
            result = OfflineTransaction(self.root, 'data', 'offline dry run', dry_run=True).run()
        self.assertEqual(result['status'], 'dry_run_validated')
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), git(remote, 'rev-parse', 'HEAD'))

    def test_native_import_and_canonical_cli_path_without_pythonpath(self):
        env = dict(os.environ, PYTHONPATH='', PYTHONDONTWRITEBYTECODE='1')
        command = ('from pathlib import Path; import evaluate_team_typesafe as t; '
                   't.main([],root=Path(__import__("sys").argv[1]),'
                   'adapter=lambda *a,**kw:{"source":"deterministic_local","mode":"proof_missing_or_invalid"})')
        result = subprocess.run([sys.executable, '-B', '-c', command, str(self.root)], cwd=ROOT / 'scripts',
                                env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        current, _, evidence = self.evidence()
        self.assertEqual(hist.parse(current)['source'], 'deterministic_local')

    def test_real_native_cli_provider_disabled_uses_history(self):
        # Copy only import dependencies, never a full repository or live secrets.
        files = ('evaluate_team_typesafe.py', 'build_team_learning.py', 'team_learning_history.py',
                 'document_handoffs.py', 'typesafe_decision_support.py', 'typesafe_shared.py',
                 'team_advisory_history.py', 'candidate_pool_history.py', 'immutable_snapshot_store.py',
                 'moe_evaluation_history.py', 'publish_transaction.py')
        (self.root / 'scripts').mkdir()
        for name in files:
            shutil.copyfile(ROOT / 'scripts' / name, self.root / 'scripts' / name)
        env = {k: v for k, v in os.environ.items() if not k.startswith('TYPESAFE_')}
        env.update(PYTHONPATH='', PYTHONDONTWRITEBYTECODE='1', TYPESAFE_ENABLED='0')
        result = subprocess.run([sys.executable, '-B', 'scripts/evaluate_team_typesafe.py'], cwd=self.root,
                                env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        current, _, evidence = self.evidence()
        doc = hist.parse(current)
        self.assertEqual(doc['mode'], 'disabled_local_advisory')
        self.assertFalse(doc['paid_api_called'])
        self.assertEqual(evidence['archives'][hist.sha(LEGACY)], LEGACY)

    def test_default_evaluator_uses_history_custom_output_stays_isolated(self):
        with contextlib.redirect_stdout(io.StringIO()):
            team.main([], root=self.root, adapter=lambda *a, **kw: {'source': 'deterministic_local', 'mode': 'disabled'})
        self.evidence()

    def test_both_workflows_capture_exact_advisory_history_paths(self):
        deep = (ROOT / '.github/workflows/JARVIS-Deep-Analysis.yml').read_text()
        listing = (ROOT / '.github/workflows/shopify-listing-copy.yml').read_text()
        self.assertIn('paths: data obsidian', deep)
        line = next(s for s in listing.splitlines() if 'paths: data/agents ' in s)
        self.assertIn(hist.REPORT, line.split()); self.assertIn(hist.HISTORY, line.split())
        self.assertNotIn(hist.REPORT, POLICY['derived_paths'])
        self.assertFalse(pub.volatile_container(hist.REPORT, POLICY))


if __name__ == '__main__':
    unittest.main(verbosity=2)
