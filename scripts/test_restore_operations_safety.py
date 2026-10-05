"""Fixture-only adversarial restoration tests. Never read production data/GitHub."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import restore_operations_safety as restore
import jarvis_operations as core
import jarvis_execution as execution
import jarvis_watch as watch


def body(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def bundle(files, prefix=''):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            archive.writestr(prefix + name.removeprefix('data/operations/'), raw)
    return out.getvalue()


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = core.empty_state()
        core.create_task(self.old, goal='fixture safety review', team='legal', payload={})
        self.current = {restore.STATE:body(self.old), restore.LEDGER:body({})}
        self.write(self.current)
        self.new = copy.deepcopy(self.old)
        core.create_task(self.new, goal='fixture next safety review', team='market', payload={})
        self.incoming = {restore.STATE:body(self.new), restore.LEDGER:body({})}
        self.run = {'id':100,'run_attempt':2,'path':sorted(restore.WORKFLOWS)[0],
                    'head_branch':'main','head_repository':{'full_name':restore.REPOSITORY},
                    'status':'completed','head_sha':'a'*40}
        self.raw = bundle(self.incoming)
        self.artifact = {'id':200,'name':'operations-safety-100-2','expired':False,
                         'workflow_run':{'id':100,'head_sha':'a'*40,'head_branch':'main'},
                         'archive_download_url':restore.BASE+'artifacts/200/zip',
                         'digest':'sha256:'+restore._sha(self.raw)}
        self.rows = [self.artifact]
        self.ancestor = True
        self.active = True
        self.head = self.current
        self.git_patch = patch.object(restore, '_git', side_effect=self.git)
        self.git_patch.start()
        self.addCleanup(self.git_patch.stop)

    def write(self, files):
        for name, raw in files.items():
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)

    def git(self, root, *args):
        if args[0] == 'merge-base':
            return subprocess.CompletedProcess(args, 0 if self.ancestor else 1, b'', b'')
        if args[0] == 'show' and args[1].startswith('HEAD:'):
            raw = self.head.get(args[1][5:])
            return subprocess.CompletedProcess(args, 0 if raw is not None else 1, raw or b'', b'')
        return subprocess.CompletedProcess(args, 0, b'name: operations-safety-100-2' if self.active else b'name: legacy\njobs: {}', b'')

    def metadata(self, url):
        if '/runs?' in url:
            return {'workflow_runs':[self.run]}
        return {'total_count':len(self.rows),'artifacts':self.rows}

    def perform(self):
        return restore.restore_latest(self.root, fetch_json=self.metadata,
                                      fetch_bytes=lambda url:self.raw, current_run_id='101')

    def replace_archive(self, files):
        self.raw = bundle(files)
        self.artifact['digest'] = 'sha256:'+restore._sha(self.raw)

    def test_normal_continuation_and_no_history_drop(self):
        self.assertEqual(self.perform()['status'], 'authenticated_operations_safety_restored')
        files = restore.verify_current(self.root)
        self.assertEqual(files, self.incoming)
        state = json.loads(files[restore.STATE])
        self.assertEqual(state['events'][next(iter(self.old['events']))], next(iter(self.old['events'].values())))
        self.assertFalse((self.root/restore.PENDING).exists())

    def test_exact_current_head_ahead_is_retained(self):
        self.write(self.incoming)
        self.head = self.incoming
        self.replace_archive(self.current)
        self.assertEqual(self.perform()['status'], 'artifact_history_already_preserved_in_head')
        self.assertEqual(restore.verify_current(self.root), self.incoming)

    def test_untracked_current_ahead_denied(self):
        self.write(self.incoming)
        self.replace_archive(self.current)
        with self.assertRaises(ValueError): self.perform()

    def test_digest_corruption_missing_and_ambiguous(self):
        self.raw += b'changed'
        with self.assertRaises(ValueError): self.perform()
        self.rows = []
        with self.assertRaises(ValueError): self.perform()
        self.rows = [self.artifact,dict(self.artifact)]
        with self.assertRaises(ValueError): self.perform()

    def test_wrong_attempt_expired_and_lineage(self):
        for field, value in [('name','operations-safety-100-1'),('expired',True),('digest',None),
                             ('archive_download_url','https://invalid.example/archive')]:
            with self.subTest(field=field), patch.dict(self.artifact,{field:value}):
                with self.assertRaises(ValueError): self.perform()
        self.artifact['workflow_run']['head_sha'] = 'b'*40
        with self.assertRaises(ValueError): self.perform()

    def test_ancestor_required(self):
        self.ancestor = False
        with self.assertRaises(ValueError): self.perform()

    def test_event_rewrite_and_drop_denied(self):
        for mutation in ('rewrite','drop'):
            altered = copy.deepcopy(self.new)
            key = next(iter(self.old['events']))
            if mutation == 'rewrite': altered['events'][key]['detail'] = {'changed':True}
            else: del altered['events'][key]
            files = {**self.incoming, restore.STATE:body(altered)}
            self.replace_archive(files)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.perform()
        self.assertEqual(restore.verify_current(self.root), self.current)

    def test_counter_regression_and_budget_reset_denied(self):
        for key in ('lifetime_counter','remaining_budget','stopped','approvals','signatures'):
            before = copy.deepcopy(self.old)
            after = copy.deepcopy(self.new)
            before[key] = {'used':5} if key in ('approvals','signatures') else 5
            after[key] = {'used':4} if key in ('approvals','signatures') else 4
            with self.subTest(key=key), self.assertRaises(ValueError):
                restore._nonregression({**self.current,restore.STATE:body(before)},
                                       {**self.incoming,restore.STATE:body(after)})

    def test_report_exact_bytes_no_deletion_no_rewrite(self):
        name = 'data/operations/reports/old.json'
        raw = b'{ "fixture": true }\n'
        self.current[name] = raw
        self.write({name:raw})
        for value in (None, b'{"fixture":true}\n'):
            files = dict(self.incoming)
            if value is not None: files[name] = value
            self.replace_archive(files)
            with self.subTest(value=value), self.assertRaises(ValueError): self.perform()
        files = {**self.incoming,name:raw}
        self.replace_archive(files)
        self.perform()
        self.assertEqual((self.root/name).read_bytes(), raw)

    def test_zip_paths_symlink_duplicate_compression_and_limits(self):
        for name in ('../state.json','board.json','reports/sub/file.json','/state.json','reports\\x.json'):
            out = io.BytesIO()
            with zipfile.ZipFile(out,'w') as archive: archive.writestr(name,b'{}')
            with self.subTest(name=name), self.assertRaises(ValueError): restore._archive(out.getvalue())
        for kind in ('symlink','duplicate','compression','oversize'):
            out = io.BytesIO()
            with zipfile.ZipFile(out,'w') as archive:
                entry = zipfile.ZipInfo('state.json')
                if kind == 'symlink': entry.external_attr = 0o120777 << 16
                if kind == 'compression': entry.compress_type = zipfile.ZIP_BZIP2
                archive.writestr(entry, b'x'*(restore.MAX_FILE_BYTES+1) if kind=='oversize' else b'{}')
                if kind == 'duplicate': archive.writestr('state.json',b'{}')
            with self.subTest(kind=kind), self.assertRaises(ValueError): restore._archive(out.getvalue())
        self.assertEqual(restore._archive(bundle(self.incoming,'data/operations/')), self.incoming)

    def test_missing_pair_and_duplicate_json_denied(self):
        with self.assertRaises(ValueError): restore._archive(bundle({restore.STATE:body(self.new)}))
        with self.assertRaises(ValueError): restore._json(b'{"a":1,"a":2}')

    def test_first_activation_requires_exact_tracked_head(self):
        self.active = False
        self.assertEqual(self.perform()['status'],'tracked_pre_activation_history')
        self.write(self.incoming)
        with self.assertRaises(ValueError): self.perform()

    def test_pending_marker_and_interrupted_atomic_restore_deny(self):
        original = restore.os.replace
        def interrupted(source, target):
            if Path(target) == self.root/restore.STATE:
                raise OSError('fixture interrupted')
            return original(source,target)
        with patch.object(restore.os,'replace',side_effect=interrupted):
            with self.assertRaises(OSError): self.perform()
        self.assertTrue((self.root/restore.PENDING).exists())
        with self.assertRaises(ValueError): restore.verify_current(self.root)
        with self.assertRaises(ValueError): self.perform()

    def test_verify_cli_output_only_success(self):
        output = self.root/'gha-output'
        with patch.dict(os.environ, {'GITHUB_OUTPUT':str(output)}):
            self.assertEqual(restore.main(['--root',str(self.root),'--verify-current']),0)
            self.assertEqual(output.read_text(),'operations_continuity=verified\n')
            output.unlink()
            (self.root/restore.PENDING).write_bytes(b'pending')
            self.assertEqual(restore.main(['--root',str(self.root),'--verify-current']),1)
            self.assertFalse(output.exists())

    def test_actual_receipt_and_task_transition_continuation(self):
        task_id = next(iter(self.old['tasks']))
        state = copy.deepcopy(self.old)
        for status in ('ROUTED','IN_PROGRESS','VERIFYING','EXECUTING'):
            core.transition(state, task_id, status)
        source = self.root/execution.SOURCES['legal']
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(body({'captured_at':'2026-10-03T12:00:00+00:00','salesAllowed':False}))
        ledger = {}
        receipt = execution.execute(self.root,state['tasks'][task_id],ledger,
                                    now='2026-10-03T12:00:00+00:00',persist=lambda value:None)
        self.assertEqual(receipt['status'],'VERIFIED')
        state['receipts'][receipt['receipt_id']] = receipt
        core.transition(state, task_id, 'COMPLETED',receipt=receipt)
        output = receipt['outputs'][0]['path']
        raw = (self.root/output).read_bytes()
        # Generated output is a candidate fixture, not a current unclaimed file.
        (self.root/output).unlink()
        files = {restore.STATE:body(state),restore.LEDGER:body(ledger),output:raw}
        self.replace_archive(files)
        self.perform()
        self.assertEqual(restore.verify_current(self.root),files)
        # A valid reserialization with a new hash is still an immutable-byte
        # conflict, even if both candidate receipt sets validate independently.
        current = dict(files)
        altered = copy.deepcopy(state)
        ledger_after = copy.deepcopy(ledger)
        changed = body(json.loads(raw)) + b'\n'
        claim = next(iter(ledger_after['claims'].values()))
        changed_receipt = claim['receipt']
        changed_receipt['outputs'][0]['sha256'] = restore._sha(changed)
        changed_receipt['output_evidence'][0]['sha256'] = restore._sha(changed)
        changed_receipt['receipt_hash'] = execution.digest({k:v for k,v in changed_receipt.items() if k != 'receipt_hash'})
        candidate = {**files,output:changed,restore.STATE:body(altered),restore.LEDGER:body(ledger_after)}
        with self.assertRaises(ValueError): restore._nonregression(current,candidate)

    def test_watch_cooldown_and_pending_history_failclosed(self):
        before = watch._cursor(None)
        before['last_emitted']['legal'] = '2026-10-03T12:00:00+00:00'
        after = copy.deepcopy(before)
        after['last_emitted']['legal'] = '2026-10-03T13:00:00+00:00'
        restore._watch_continuation(before,after,{})
        after['last_emitted']['legal'] = '2026-10-03T11:00:00+00:00'
        with self.assertRaises(ValueError): restore._watch_continuation(before,after,{})
        after = copy.deepcopy(before)
        before['seen_events']['b'*64] = '2026-10-03T12:00:00+00:00'
        with self.assertRaises(ValueError): restore._watch_continuation(before,after,{})

    def test_unresolved_execution_claim_stops_restoration(self):
        ledger = {'global_stop':True,'claims':{'fixture':{'action_hash':'a'*64,
                  'claimed_at':'2026-10-03T12:00:00+00:00','status':'RECONCILIATION_REQUIRED'}}}
        self.replace_archive({**self.incoming,restore.LEDGER:body(ledger)})
        with self.assertRaises(ValueError): self.perform()
        self.assertEqual(restore.verify_current(self.root),self.current)

    def test_policy_registry_unchanged(self):
        before = execution.canonical({'registry':execution.REGISTRY,'sources':execution.SOURCES})
        policy = execution.POLICY_HASH
        self.perform()
        self.assertEqual(policy, execution.POLICY_HASH)
        self.assertEqual(before,execution.canonical({'registry':execution.REGISTRY,'sources':execution.SOURCES}))


if __name__ == '__main__': unittest.main()
