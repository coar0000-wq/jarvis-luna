#!/usr/bin/env python3
"""Rotating collector snapshot manifests: rotation allowed, everything else still blocked."""
import json
import subprocess
import sys
import tempfile
import unittest
import io
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import collector_snapshot_history as csh  # noqa: E402
from scripts import shortlist_observation_history as observer_history  # noqa: E402
from scripts import test_shortlist_observations as observer_fixtures  # noqa: E402
from scripts import publish_transaction as publisher  # noqa: E402
from scripts.publish_transaction import deletion_authorized, overlay, Transaction, PublishError  # noqa: E402

POLICY = json.loads((ROOT / "config/publish_policy.json").read_text(encoding="utf-8"))


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class CollectorSnapshotTests(unittest.TestCase):
    def test_watch_membership_rotates_but_record_fields_and_history_stay_guarded(self):
        rel = 'data/operations/state.json'
        old = {'watch': {'sources': {'pricing': {'semantic_hash': 'old', 'records': {
            'CPold': {'value': {'amount': 1000}}, 'CPkeep': {'value': {'amount': 2000}}}}},
            'seen_events': {'old-event': 'original-clock'}}, 'receipts': {'old-receipt': {'ok': True}}}
        new = json.loads(json.dumps(old))
        del new['watch']['sources']['pricing']['records']['CPold']
        self.assertEqual(csh.allowed_removals(rel, old, new, POLICY), ['CPold'])
        mutations = (
            lambda d: d['watch']['sources']['pricing']['records']['CPkeep']['value'].pop('amount'),
            lambda d: d['watch']['seen_events'].clear(),
            lambda d: d['receipts'].clear(),
            lambda d: d['watch']['sources']['pricing'].pop('semantic_hash'),
            lambda d: d['watch']['sources']['pricing'].pop('records'),
        )
        for mutate in mutations:
            bad = json.loads(json.dumps(new)); mutate(bad)
            with self.assertRaises(ValueError):
                csh.allowed_removals(rel, old, bad, POLICY)
        with self.assertRaises(ValueError):
            csh.allowed_removals('data/product_master.json', old, new, POLICY)
        (self.root / 'data/operations').mkdir()
        base = json.dumps(old).encode(); current = json.dumps(new).encode()
        (self.root / rel).write_bytes(current)
        with patch.object(csh, 'head_bytes', return_value=base):
            report = csh.update(self.root, [rel])
        self.assertIn('authorized 1', report[rel])
        manifest = json.loads((self.root / 'data/publish_deletions.json').read_bytes())
        self.assertTrue(deletion_authorized(rel, base, ['CPold'], manifest, replacement=current))
        self.assertFalse(deletion_authorized(rel, base + b' ', ['CPold'], manifest, replacement=current))

    def test_label_diagnostics_rotate_without_waiving_source_label_protection(self):
        rel = "data/daiso_real/us_label_sync_report.json"
        old = {"current_s_count": 2, "items": {"old": {"missing_fields": ["manufacturer"]},
                                             "keep": {"missing_fields": ["ingredients_inci"]}}}
        new = {"current_s_count": 1, "items": {"keep": {"missing_fields": []}}}
        self.assertEqual(set(csh.allowed_removals(rel, old, new, POLICY)),
                         {"old", "ingredients_inci"})
        with self.assertRaises(ValueError):
            csh.allowed_removals(rel, old, {"items": {}}, POLICY)
        with self.assertRaises(ValueError):
            csh.allowed_removals("data/daiso_real/daiso_us_labels.json", old, new, POLICY)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.invalid")
        git(self.root, "config", "user.name", "t")
        (self.root / "config").mkdir()
        (self.root / "config/publish_policy.json").write_text(json.dumps(POLICY), encoding="utf-8")
        (self.root / "data").mkdir()
        self.rel = "data/amazon_new_products.json"
        self.old = {"count": 2, "products": [{"rank": 1, "url": "https://a/1"}, {"rank": 2, "url": "https://a/2"}]}
        (self.root / self.rel).write_text(json.dumps(self.old), encoding="utf-8")
        (self.root / "data/publish_deletions.json").write_text(json.dumps({"schema_version": 1, "deletions": []}), encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "base")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, doc):
        (self.root / self.rel).write_text(json.dumps(doc), encoding="utf-8")

    def test_rotated_ranking_is_authorized_by_exact_entry(self):
        self.write({"count": 2, "products": [{"rank": 1, "url": "https://a/1"}, {"rank": 2, "url": "https://a/3"}]})
        report = csh.update(self.root, [self.rel])
        self.assertIn("authorized 1", report[self.rel])
        manifest = json.loads((self.root / "data/publish_deletions.json").read_text(encoding="utf-8"))
        base = subprocess.run(["git", "-C", str(self.root), "show", "HEAD:" + self.rel], capture_output=True).stdout
        local = (self.root / self.rel).read_bytes()
        self.assertTrue(deletion_authorized(self.rel, base, ["https://a/2"], manifest, replacement=local))

    def test_field_removal_outside_rotating_list_is_blocked(self):
        self.write({"products": [{"rank": 1, "url": "https://a/1"}, {"rank": 2, "url": "https://a/2"}]})
        with self.assertRaises(ValueError):
            csh.update(self.root, [self.rel])

    def test_undeclared_file_is_blocked(self):
        with self.assertRaises(ValueError):
            csh.update(self.root, ["data/daiso_real/products.json"])

    def test_wildcard_scope_is_single_level(self):
        rel = "data/knowledge/real_sources.json"
        self.assertTrue(csh.rotating(rel, ("sources", "arxiv", "items")))
        self.assertFalse(csh.rotating(rel, ("sources", "arxiv", "provenance", "items")))
        self.assertFalse(csh.rotating(rel, ("sources",)))

    def test_daiso_candidate_ids_rotate_but_other_lists_stay_guarded(self):
        # 2026-10-16 회귀: 매 실행 바뀌는 candidate_ids 때문에 Daiso 수집 워크플로가 10-03 이후 계속 실패했다.
        rel = "data/daiso_real/collection_status.json"
        run = lambda ids, buckets: {"candidate_ids": ids, "prefetch_policy": {"eligible_buckets": buckets}}
        old = {s: run(["A", "B"], ["x", "y"]) for s in ("last_run", "last_attempt", "last_candidate_success")}
        new = {s: run(["B", "C"], ["x", "y"]) for s in old}
        self.assertEqual(sorted(csh.allowed_removals(rel, old, new, POLICY)), ["A", "A", "A"])
        # 2026-10-17: last_* 는 실행 1회 요약이라 다른 칸(버킷·제외 사유)도 통째로 바뀐다. 빠진 값은 매니페스트에 남는다.
        moved = {s: run(["A", "B"], ["x"]) for s in old}
        self.assertEqual(sorted(csh.allowed_removals(rel, old, moved, POLICY)), ["y", "y", "y"])
        # 누적 칸(totals 등)은 요약이 아니라서 계속 막는다.
        old_totals, bad = dict(old, totals={"products": 1, "ok": 2}), dict(new, totals={"ok": 2})
        with self.assertRaises(ValueError):
            csh.allowed_removals(rel, old_totals, bad, POLICY)

    def test_emptied_rotating_container_may_drop_but_other_fields_stay_guarded(self):
        # 2026-10-17: 실패 이력이 모두 해소돼 failed_workflow_history 칸이 통째로 빠지자 Core 발행이 막혔다.
        rel = "data/agents/daiso_pipeline_health.json"
        old = {"failed_workflow_history": [{"run": 1}], "status": "failed", "public_authority": False}
        self.assertEqual(csh.allowed_removals(rel, old, {"status": "success", "public_authority": False}, POLICY),
                         ["failed_workflow_history"])
        with self.assertRaises(ValueError):
            csh.allowed_removals(rel, old, {"failed_workflow_history": [], "status": "success"}, POLICY)

    def test_unchanged_file_writes_nothing(self):
        before = (self.root / "data/publish_deletions.json").read_bytes()
        self.assertEqual(csh.update(self.root, [self.rel])[self.rel], "unchanged")
        self.assertEqual((self.root / "data/publish_deletions.json").read_bytes(), before)


class RestoredObserverPublicationTests(unittest.TestCase):
    save = observer_fixtures.ObserverTests.save
    shortlist = observer_fixtures.ObserverTests.shortlist
    http = observer_fixtures.ObserverTests.http
    run_observe = observer_fixtures.ObserverTests.run_observe

    def setUp(self):
        observer_fixtures.ObserverTests.setUp(self)
        self.run_observe()
        self.base = (self.root / observer_history.OUTPUT).read_bytes()
        self.ledger = (self.root / observer_history.LEDGER).read_bytes()
        self.run_observe(force=True)  # Cached observation: current diagnostic IDs shrink.
        (self.root / 'config').mkdir()
        (self.root / 'config/publish_policy.json').write_text(json.dumps(POLICY), encoding='utf-8')

    def head(self, root, rel):
        return self.base if rel == observer_history.OUTPUT else self.ledger

    def test_all_declared_records_restored_diagnostics_without_new_observation(self):
        current = (self.root / observer_history.OUTPUT).read_bytes()
        output = io.StringIO()
        with patch.object(csh, 'ROOT', self.root), patch.object(csh, 'head_bytes', side_effect=self.head), \
                patch.object(observer_history, 'exact_head', side_effect=self.head), \
                patch.object(csh.sys, 'argv', ['collector_snapshot_history.py', '--all-declared']), \
                patch.object(observer_fixtures.obs, '_http_get', side_effect=AssertionError('no HTTP')), \
                redirect_stdout(output):
            result = csh.main()
        self.assertEqual(result, 0, output.getvalue())
        manifest = json.loads((self.root / observer_history.MANIFEST).read_bytes())
        entry = next(row for row in manifest['deletions'] if row['path'] == observer_history.OUTPUT)
        self.assertEqual(entry['base_sha256'], observer_history.sha(self.base))
        self.assertEqual(entry['replacement_sha256'], observer_history.sha(current))
        self.assertTrue(deletion_authorized(observer_history.OUTPUT, self.base, entry['ids'],
                                            manifest, replacement=current))
        self.assertEqual((self.root / observer_history.OUTPUT).read_bytes(), current)
        self.assertEqual((self.root / observer_history.HISTORY /
                          (observer_history.sha(self.base) + '.json')).read_bytes(), self.base)

    def test_lost_source_capture_is_not_authorized(self):
        path = self.root / observer_history.OUTPUT
        changed = json.loads(path.read_bytes()); changed['capture_history'] = []
        path.write_text(json.dumps(changed), encoding='utf-8')
        with patch.object(csh, 'head_bytes', side_effect=self.head), \
                patch.object(observer_history, 'exact_head', side_effect=self.head), \
                self.assertRaisesRegex(ValueError, 'capture_history_lost'):
            csh.record_restored_observer(self.root)
        self.assertFalse((self.root / observer_history.MANIFEST).exists())

    def test_unchanged_observer_creates_no_archive_or_manifest(self):
        (self.root / observer_history.OUTPUT).write_bytes(self.base)
        with patch.object(csh, 'head_bytes', side_effect=self.head), \
                patch.object(observer_history, 'preserve', side_effect=AssertionError('no mutation')):
            self.assertIsNone(csh.record_restored_observer(self.root))
        self.assertFalse((self.root / observer_history.MANIFEST).exists())


class OwnedScopePublicationTests(unittest.TestCase):
    save = observer_fixtures.ObserverTests.save
    shortlist = observer_fixtures.ObserverTests.shortlist
    http = observer_fixtures.ObserverTests.http
    run_observe = observer_fixtures.ObserverTests.run_observe
    def setUp(self):
        observer_fixtures.ObserverTests.setUp(self)
        self.shortlist(4)
        self.run_observe()
        self.base = (self.root / observer_history.OUTPUT).read_bytes()
        self.ledger = (self.root / observer_history.LEDGER).read_bytes()
        (self.root / 'config').mkdir()
        (self.root / 'config/publish_policy.json').write_text(json.dumps(POLICY), encoding='utf-8')
        git(self.root, 'init', '-q')
        git(self.root, 'config', 'user.email', 'fixture@example.invalid')
        git(self.root, 'config', 'user.name', 'Offline fixture')
        git(self.root, 'add', '-A'); git(self.root, 'commit', '-qm', 'four active members')
        self.shortlist(2)
        self.current, network = self.run_observe()
        network.assert_not_called()

    def preserve(self):
        return observer_history.preserve(self.root, previous_output=self.base, previous_ledger=self.ledger)

    def evidence(self):
        raw = (self.root / observer_history.OUTPUT).read_bytes()
        manifest = json.loads((self.root / observer_history.MANIFEST).read_bytes())
        proof = observer_history.load_scope_evidence(self.root, self.base, raw, POLICY, manifest)
        return raw, manifest, proof

    def test_owned_four_to_two_preserves_exact_capture_ledger_and_publishes(self):
        before = observer_history.owned_inputs(self.root)
        report = self.preserve()
        raw, manifest, proof = self.evidence()
        self.assertEqual(proof['record']['expected_ids_before'], self.cps[:4])
        self.assertEqual(proof['record']['expected_ids_after'], self.cps[:2])
        self.assertEqual(json.loads(self.ledger)['request_history'], json.loads(proof['current_ledger'])['request_history'])
        self.assertEqual(self.current['budget_checkpoint']['total_http_attempts'], 5)
        for row in json.loads(self.base)['products']:
            self.assertIn(row, self.current['capture_history'])
        self.assertEqual(observer_history.owned_inputs(self.root), before)
        self.assertEqual(overlay(observer_history.OUTPUT, self.base, raw, self.base, POLICY,
                                 manifest, observer_evidence=proof), raw)
        self.assertTrue(deletion_authorized(observer_history.OUTPUT, self.base, report['removed_ids'],
                          manifest, replacement=raw, observer_evidence=proof, observer_policy=POLICY))
        tx = Transaction(self.root, 'data', 'fixture', dry_run=True)
        self.assertIsNotNone(tx.observer_evidence)

    def test_manifest_alone_cannot_authorize_scope_change(self):
        self.preserve(); raw, manifest, proof = self.evidence()
        ids = proof['record']['removed_ids']
        self.assertFalse(deletion_authorized(observer_history.OUTPUT, self.base, ids, manifest, replacement=raw))
        with self.assertRaises(PublishError):
            overlay(observer_history.OUTPUT, self.base, raw, self.base, POLICY, manifest)

    def test_package_imports_in_clean_subprocess(self):
        # Observer CLI starts with scripts/daiso, not scripts, on sys.path.
        subprocess.run([sys.executable, '-B', '-c',
                        'from scripts.source_safety_checkpoint import _validate; '
                        'from scripts.shortlist_observation_history import verify_owned_scope'],
                       cwd=ROOT, check=True, capture_output=True)

    def test_restored_scope_is_proved_without_new_observation(self):
        with patch.object(observer_fixtures.obs, '_http_get', side_effect=AssertionError('no HTTP')):
            report = csh.record_restored_observer(self.root)
        self.assertIsNotNone(report)
        self.evidence()

    def test_declared_hashes_without_owned_input_bytes_are_not_evidence(self):
        with self.assertRaisesRegex(ValueError, 'owned_input_evidence_required'):
            observer_history.validate_transition(self.base, (self.root / observer_history.OUTPUT).read_bytes(), POLICY)
        self.assertFalse((self.root / observer_history.MANIFEST).exists())

    def test_forged_hashes_and_membership_are_rejected(self):
        original = (self.root / observer_history.OUTPUT).read_bytes()
        for mutate in (lambda d: d.update(expected_ids=self.cps[:1]),
                       lambda d: d['input_hashes_before'].update({'data/product_master.json': '0'*64}),
                       lambda d: d['input_hashes_after'].pop('data/product_master.json')):
            d = json.loads(original); mutate(d); self.save(observer_history.OUTPUT, d)
            with self.assertRaises(ValueError): self.preserve()
            self.assertFalse((self.root / observer_history.MANIFEST).exists())
        (self.root / observer_history.OUTPUT).write_bytes(original)

    def test_later_input_change_invalidates_candidate(self):
        self.preserve()
        self.shortlist(3)
        with self.assertRaisesRegex(ValueError, 'live_inputs_changed'):
            self.evidence()
        with self.assertRaises(ValueError):
            Transaction(self.root, 'data', 'fixture', dry_run=True)

    def test_capture_attempt_history_and_counter_loss_fail_closed(self):
        original = (self.root / observer_history.OUTPUT).read_bytes()
        for mutate in (lambda d: d.update(capture_history=[]),
                       lambda d: d.update(observation_history=[]),
                       lambda d: d['budget_checkpoint'].update(total_http_attempts=0)):
            d = json.loads(original); mutate(d); self.save(observer_history.OUTPUT, d)
            with self.assertRaises(ValueError): self.preserve()
            self.assertFalse((self.root / observer_history.MANIFEST).exists())
        (self.root / observer_history.OUTPUT).write_bytes(original)

    def test_request_reservations_and_retired_member_attempts_cannot_be_lost(self):
        original = (self.root / observer_history.LEDGER).read_bytes()
        for mutate in (lambda d: d['request_history'][0].update(kind='forged'),
                       lambda d: d.update(total_http_attempts=4),
                       lambda d: d['member_attempts'].pop(self.pds[3])):
            d = json.loads(original); mutate(d); self.save(observer_history.LEDGER, d)
            with self.assertRaises(ValueError): self.preserve()
            self.assertFalse((self.root / observer_history.MANIFEST).exists())
        (self.root / observer_history.LEDGER).write_bytes(original)

    def test_missing_tampered_archive_and_receipt_rejected(self):
        self.preserve(); raw, manifest, proof = self.evidence()
        name = observer_history.HISTORY + '/' + observer_history.sha(self.base) + '.json'
        p = self.root / name
        p.write_bytes(self.base + b' ')
        with self.assertRaises(ValueError): self.evidence()
        p.write_bytes(self.base); p.unlink()
        with self.assertRaises(OSError): self.evidence()

    def test_input_evidence_is_retained_in_publication_paths(self):
        self.preserve()
        with self.assertRaisesRegex(PublishError, 'archive omitted'):
            Transaction(self.root, observer_history.OUTPUT + ' ' + observer_history.LEDGER + ' ' + observer_history.MANIFEST,
                        'fixture', dry_run=True)

    def test_manifest_cannot_be_omitted_from_publication(self):
        self.preserve()
        with self.assertRaisesRegex(PublishError, 'manifest omitted'):
            Transaction(self.root, ' '.join((observer_history.OUTPUT, observer_history.LEDGER,
                        observer_history.HISTORY)), 'fixture', dry_run=True)

    def test_manifest_race_after_delta_capture_is_rejected(self):
        self.preserve()
        original = Transaction.capture
        def raced(tx):
            result = original(tx)
            path = self.root / observer_history.MANIFEST
            doc = json.loads(path.read_bytes())
            doc['deletions'][0]['reason'] += ' changed after capture'
            path.write_text(json.dumps(doc), encoding='utf-8')
            return result
        with patch.object(Transaction, 'capture', raced), self.assertRaisesRegex(PublishError, 'changed after capture'):
            Transaction(self.root, 'data', 'fixture', dry_run=True)

    def test_valid_alternate_ledger_cannot_substitute_actual_git_base(self):
        self.preserve(); raw, manifest, proof = self.evidence()
        alternate = json.loads(proof['base_ledger'])
        alternate['last_result_status'] = 'different historical metadata'
        alternate = json.dumps(alternate).encode()
        record = observer_history.scope_record(self.base, raw, POLICY, proof['inputs'],
                                               alternate, proof['current_ledger'])
        receipt = json.dumps(record).encode()
        for value in (alternate, receipt):
            path = self.root / observer_history.HISTORY / (observer_history.sha(value) + '.json')
            path.write_bytes(value)
        manifest['deletions'][0]['scope_evidence_sha256'] = observer_history.sha(receipt)
        self.save(observer_history.MANIFEST, manifest)
        self.evidence()  # Internally coherent evidence still is not the Git base.
        with self.assertRaisesRegex(PublishError, 'actual base ledger'):
            Transaction(self.root, 'data', 'fixture', dry_run=True)

    def test_final_regeneration_rejects_same_cp_with_different_pd(self):
        self.preserve(); _, _, proof = self.evidence()
        master = json.loads((self.root / 'data/product_master.json').read_bytes())
        a, b = self.pds[0], self.pds[10]
        registry = master['pd_no_to_cp']
        registry[a], registry[b] = registry[b], registry[a]
        for row in master['products']:
            row['canonical_product_id'] = registry[row['pd_no']]
        self.save('data/product_master.json', master)
        shortlist = json.loads((self.root / 'data/shopify_shortlist.json').read_bytes())
        shortlist['active_pd_nos'][0] = b
        shortlist['units'][0]['pd_nos'][0] = b
        self.save('data/shopify_shortlist.json', shortlist)
        self.assertEqual([cp for _, cp in observer_fixtures.obs._members(self.root)], self.cps[:2])
        with self.assertRaisesRegex(ValueError, 'identities changed'):
            observer_history.verify_final_scope(self.root, proof)

    def test_final_manifest_and_archives_are_revalidated(self):
        self.preserve(); _, manifest, proof = self.evidence()
        observer_history.verify_final_scope(self.root, proof)
        self.save(observer_history.MANIFEST, {'schema_version': 1, 'deletions': []})
        with self.assertRaisesRegex(ValueError, 'manifest_changed'):
            observer_history.verify_final_scope(self.root, proof)
        self.save(observer_history.MANIFEST, manifest)
        path = self.root / observer_history.HISTORY / (observer_history.sha(self.base) + '.json')
        path.write_bytes(self.base + b' ')
        with self.assertRaises(ValueError):
            observer_history.verify_final_scope(self.root, proof)

    def transaction_remote(self):
        remote = self.root / 'remote.git'
        git(self.root, 'init', '--bare', str(remote))
        git(self.root, 'branch', '-M', 'main')
        git(self.root, 'remote', 'add', 'origin', str(remote))
        git(self.root, 'push', '-u', 'origin', 'main')
        return remote

    def test_full_transaction_runs_commerce_regeneration_and_preserves_proof(self):
        # The actual coordinator/branching runs against a local bare remote;
        # only individual producer commands are substituted with offline fixtures.
        catalog = json.loads((self.root / 'data/daiso_real/products.json').read_bytes())
        catalog['fixture_revision'] = 2
        self.save('data/daiso_real/products.json', catalog)
        self.current, network = self.run_observe(); network.assert_not_called()
        self.preserve()
        self.transaction_remote()
        shortlist = (self.root / 'data/shopify_shortlist.json').read_bytes()
        before = {p.relative_to(self.root): p.read_bytes() for p in (self.root / 'data').rglob('*') if p.is_file()}
        class OfflineCommands(Transaction):
            def command(tx, work, args):
                if args == ['scripts/build_shopify_shortlist.py']:
                    (work / 'data/shopify_shortlist.json').write_bytes(shortlist)
                tx.executed_commands.append(list(args))
        tx = OfflineCommands(self.root, 'data', 'offline proof', dry_run=True, audit=False)
        self.assertFalse(tx.candidate_only())
        result = tx.run()
        self.assertEqual(result['status'], 'dry_run_validated')
        self.assertIn(['scripts/build_shopify_shortlist.py'], tx.executed_commands)
        self.assertEqual(len([x for x in tx.executed_commands if x[0] == 'scripts/check_release_quality.py']), 2)
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in (self.root / 'data').rglob('*') if p.is_file()})
        self.assertEqual(publisher.git(self.root, 'rev-parse', 'HEAD').stdout,
                         publisher.git(self.root, 'rev-parse', 'refs/remotes/origin/main').stdout)

    def test_candidate_only_transaction_cannot_reuse_unpublished_derived_scope(self):
        self.preserve(); self.transaction_remote()
        class OfflineCommands(Transaction):
            def command(tx, work, args):
                tx.executed_commands.append(list(args))
        tx = OfflineCommands(self.root, 'data', 'offline rejection', dry_run=True, audit=False)
        self.assertTrue(tx.candidate_only())
        with self.assertRaisesRegex(ValueError, 'identities changed'):
            tx.run()
        self.assertNotIn(['scripts/build_shopify_shortlist.py'], tx.executed_commands)

    def test_concurrent_input_change_cannot_publish_manifest(self):
        original = observer_history.atomic_write
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[1].startswith(observer_history.HISTORY): self.shortlist(3)
            return result
        with patch.object(observer_history, 'atomic_write', side_effect=changed), self.assertRaises(ValueError):
            self.preserve()
        self.assertFalse((self.root / observer_history.MANIFEST).exists())

    def test_owned_addition_two_to_four_is_also_proved(self):
        self.base = (self.root / observer_history.OUTPUT).read_bytes()
        self.ledger = (self.root / observer_history.LEDGER).read_bytes()
        git(self.root, 'add', '-A'); git(self.root, 'commit', '-qm', 'two active members')
        self.shortlist(4)
        self.current, _ = self.run_observe()
        self.preserve()
        raw, manifest, proof = self.evidence()
        self.assertEqual(proof['record']['expected_ids_after'], self.cps[:4])
        self.assertEqual(overlay(observer_history.OUTPUT, self.base, raw, self.base, POLICY,
                                manifest, observer_evidence=proof), raw)

    def test_restored_two_member_scope_can_return_to_four_member_git_base(self):
        restored = (self.root / observer_history.OUTPUT).read_bytes()
        restored_ledger = (self.root / observer_history.LEDGER).read_bytes()
        self.shortlist(4)
        self.current, network = self.run_observe()
        network.assert_not_called()
        observer_history.preserve(self.root, previous_output=restored, previous_ledger=restored_ledger)
        for value in (self.base, self.ledger, restored, restored_ledger):
            path = self.root / observer_history.HISTORY / (observer_history.sha(value) + '.json')
            self.assertEqual(path.read_bytes(), value)
        self.assertEqual(self.current['expected_ids'], self.cps[:4])
        self.assertEqual(self.current['budget_checkpoint']['total_http_attempts'], 5)
        self.assertEqual(self.current['products'], json.loads(self.base)['products'])
        self.assertEqual(self.current['new_success_ids'], [])

    def test_reintroduced_member_does_not_accept_conflicting_or_future_capture(self):
        self.shortlist(4)
        original = (self.root / observer_history.OUTPUT).read_bytes()
        for future in (False, True):
            doc = json.loads(original)
            row = dict(doc['retained_previous_products'][0])
            if future:
                row['source'] = dict(row['source'], collected_at='2099-01-01T00:00:00+00:00')
            else:
                row['price_krw'] += 100
            doc['capture_history'].append(row)
            self.save(observer_history.OUTPUT, doc)
            with patch.object(observer_fixtures.obs, '_http_get', side_effect=AssertionError('no HTTP')):
                with self.assertRaises(observer_fixtures.obs.Blocked):
                    observer_fixtures.obs.observe(self.root)
        (self.root / observer_history.OUTPUT).write_bytes(original)

    def test_stale_reintroduced_capture_keeps_clock_and_retry_cooldown(self):
        self.shortlist(4)
        self.advance(observer_fixtures.obs.FRESH_TTL)
        failed, _ = self.run_observe(lambda url: self.http(url) if url.endswith('robots.txt') else (500, b''))
        self.shortlist(2)
        self.run_observe()
        self.shortlist(4)
        restored, network = self.run_observe()
        network.assert_not_called()
        self.assertEqual(restored['products'], json.loads(self.base)['products'])
        self.assertEqual(restored['new_success_ids'], [])
        self.assertEqual(restored['budget_checkpoint']['total_http_attempts'], failed['budget_checkpoint']['total_http_attempts'])
        self.assertTrue(all(a.get('reason') == 'member_retry_cooldown' for a in restored['attempts']))


if __name__ == "__main__":
    unittest.main(verbosity=1)
