"""Adversarial fixtures; optional supplied TMP evidence, never production data/GitHub."""
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

    def test_fx_producer_requires_authenticated_history(self):
        self.assertIn('.github/workflows/fx-refresh.yml', restore.WORKFLOWS)
        self.run['path'] = '.github/workflows/fx-refresh.yml'
        self.assertEqual(self.perform()['status'], 'authenticated_operations_safety_restored')

    def test_fx_activated_missing_artifact_stays_blocked(self):
        self.run['path'] = '.github/workflows/fx-refresh.yml'
        self.rows = []
        with self.assertRaises(restore.Blocked):
            self.perform()
        self.assertEqual(restore.verify_current(self.root), self.current)

    def test_fx_workflow_binds_continuity_and_retains_history(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/fx-refresh.yml').read_text(encoding='utf-8')
        self.assertIn('actions: read', workflow)
        self.assertLess(workflow.index('id: operations_safety'), workflow.index('uses: ./.github/actions/publish'))
        self.assertIn("if: steps.operations_safety.outputs.operations_continuity == 'verified'", workflow)
        self.assertIn('JARVIS_OPERATIONS_CONTINUITY: ${{ steps.operations_safety.outputs.operations_continuity }}', workflow)
        self.assertNotIn("JARVIS_OPERATIONS_CONTINUITY: 'verified'", workflow)
        self.assertIn('data/publish_deletions.json data/operations/', workflow)
        self.assertIn('--verify-current', workflow)
        self.assertIn("steps.operations_retention.outputs.operations_continuity == 'verified'", workflow)
        self.assertIn('name: operations-safety-${{ github.run_id }}-${{ github.run_attempt }}', workflow)

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


class AuditContinuationTests(unittest.TestCase):
    def pair(self, state):
        return {restore.STATE: body(state), restore.LEDGER: body({})}

    def test_future_audit_head_can_advance_without_rewriting_records(self):
        before = core.empty_state()
        core.create_task(before, goal='first internal review', team='sourcing')
        after = copy.deepcopy(before)
        core.create_task(after, goal='next internal review', team='graph')
        self.assertNotEqual(before['audit']['head'], after['audit']['head'])
        restore._nonregression(self.pair(before), self.pair(after))
        for key, value in before['events'].items():
            self.assertEqual(value, after['events'][key])

    def test_legacy_activation_is_future_only(self):
        before = core.empty_state()
        core.create_task(before, goal='legacy review', team='legal')
        before.pop('audit')
        for event in before['events'].values():
            event.pop('audit')
        after = copy.deepcopy(before)
        core.create_task(after, goal='future review', team='listing')
        self.assertEqual(after['audit']['start_sequence'], before['sequence'] + 1)
        restore._nonregression(self.pair(before), self.pair(after))

    def test_audit_loss_reactivation_and_rewritten_event_denied(self):
        before = core.empty_state()
        core.create_task(before, goal='protected review', team='market')
        after = copy.deepcopy(before)
        core.create_task(after, goal='another review', team='pricing')
        for mode in ('drop', 'reactivate', 'rewrite'):
            bad = copy.deepcopy(after)
            if mode == 'drop':
                bad.pop('audit')
            elif mode == 'reactivate':
                bad['audit']['start_sequence'] += 1
            else:
                next(iter(bad['events'].values()))['detail'] = {'changed': True}
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                restore._nonregression(self.pair(before), self.pair(bad))



class ReviewedAbortTests(unittest.TestCase):
    write = RestoreTests.write
    perform = RestoreTests.perform
    def setUp(self):
        RestoreTests.setUp(self)
        self.abort = copy.deepcopy(restore._ABORT_RUN)
        self.prior = copy.deepcopy(restore._ABORT_PREDECESSOR)
        repo = {'id':1334276889, 'full_name':restore.REPOSITORY}
        for run in (self.abort, self.prior):
            run.update(repository=repo, head_repository=repo)
        self.job = copy.deepcopy(restore._ABORT_JOB)
        keys = ('number','name','status','conclusion','started_at','completed_at')
        self.job['steps'] = [dict(zip(keys, row)) for row in restore._ABORT_STEPS]
        self.history = [self.abort, self.prior]
        self.jobs = {'total_count':1, 'jobs':[self.job]}
        self.artifact.update(name=f"operations-safety-{self.prior['id']}-1",
                             workflow_run={'id':self.prior['id'], 'head_sha':self.prior['head_sha'], 'head_branch':'main'})
        self.code_bad = False
        # Synthetic code is independently pinned for fixture tests, not read
        # from a production checkout or GitHub. Real pins are never modified.
        pins = {p:restore._sha((p + 'operations-safety-').encode()) for p in restore._ABORT_CODE}
        self.addCleanup(patch.stopall)
        patch.object(restore, '_ABORT_CODE', pins).start()
        patch.object(restore, '_ABORT_ARTIFACT_DIGEST', self.artifact['digest']).start()
        patch.object(restore, '_compact_reviewed_archive', side_effect=lambda raw:(restore._archive(raw), {'fixture':True})).start()

    def git(self, root, *args):
        if args[0] == 'show' and not args[1].startswith('HEAD:'):
            relative = args[1].split(':',1)[1]
            raw = (relative + 'operations-safety-').encode() + (b'changed' if self.code_bad else b'')
            if relative not in restore._ABORT_CODE:
                raw = b'operations-safety-'
            return subprocess.CompletedProcess(args,0,raw,b'')
        return RestoreTests.git(self,root,*args)

    def metadata(self, url):
        if '/runs?' in url:
            return {'workflow_runs':self.history}
        if '/attempts/1/jobs?' in url:
            return self.jobs
        if url == restore.BASE + f"runs/{self.abort['id']}":
            return self.abort
        if url == restore.BASE + f"runs/{self.prior['id']}":
            return self.prior
        if f"runs/{self.abort['id']}/artifacts?" in url:
            return {'total_count':1,'artifacts':[copy.deepcopy(restore._ABORT_SOURCE)]}
        return {'total_count':len(self.rows),'artifacts':self.rows}

    def test_reviewed_abort_restores_immediate_history(self):
        self.assertEqual(self.perform()['run_id'], self.prior['id'])
        self.assertEqual(restore.verify_current(self.root), self.incoming)

    def test_spoof_missing_ambiguous_running_attempt_and_code_denied(self):
        cases = ('missing_steps','extra_job','runtime_executed','publication_executed',
                 'recovery_executed','attempt','branch','repository','window','running','code','prior_missing')
        for case in cases:
            with self.subTest(case=case):
                before = copy.deepcopy((self.abort,self.prior,self.job,self.history,self.jobs))
                if case == 'missing_steps': self.job.pop('steps')
                if case == 'extra_job': self.jobs['jobs'].append(copy.deepcopy(self.job)); self.jobs['total_count']=2
                if case in ('runtime_executed','publication_executed','recovery_executed'):
                    number = {'runtime_executed':12,'publication_executed':15,'recovery_executed':10}[case]
                    next(s for s in self.job['steps'] if s['number']==number)['conclusion']='success'
                if case == 'attempt': self.abort['run_attempt']=2
                if case == 'branch': self.abort['head_branch']='other'
                if case == 'repository': self.abort['repository']={'id':1,'full_name':restore.REPOSITORY}
                if case == 'window': self.abort['updated_at']='2026-10-05T10:53:33Z'
                if case == 'running': self.history.insert(0,{**self.abort,'id':self.abort['id']+1,'status':'in_progress'})
                if case == 'code': self.code_bad=True
                if case == 'prior_missing': self.history.pop()
                with self.assertRaises(ValueError): self.perform()
                self.abort,self.prior,self.job,self.history,self.jobs = before
                self.code_bad=False
                self.assertEqual(restore.verify_current(self.root),self.current)

    def test_normalization_failure_preserves_current_history(self):
        with patch.object(restore,'_compact_reviewed_archive',side_effect=restore.Blocked('fixture_binding_failure')):
            with self.assertRaises(ValueError): self.perform()
        self.assertEqual(restore.verify_current(self.root),self.current)
        self.assertFalse((self.root/restore.PENDING).exists())

    def test_future_retention_requires_verified_restore_not_runtime(self):
        raw=(Path(__file__).resolve().parents[1]/'.github/workflows/JARVIS-Core-Automation.yml').read_text(encoding='utf-8')
        retention=raw[raw.index('      - name: Retain immutable operations safety history'):]
        self.assertIn("steps.operations_safety.outcome == 'success'",retention)
        self.assertIn("steps.operations_retention.outputs.operations_continuity == 'verified'",retention)
        self.assertNotIn('runtime_refresh',retention)



class ZeroGapChainTests(ReviewedAbortTests):
    def setUp(self):
        super().setUp()
        self.cases = copy.deepcopy(restore._ZERO_GAPS)
        repo = {'id':1334276889, 'full_name':restore.REPOSITORY}
        self.gap_runs = {int(k):dict(v['run'], repository=repo, head_repository=repo) for k,v in self.cases.items()}
        keys = ('number','name','status','conclusion','started_at','completed_at')
        self.gap_jobs = {int(k):{'total_count':1,'jobs':[dict(v['job'], steps=[dict(zip(keys,row)) for row in v['steps']])]} for k,v in self.cases.items()}
        self.logs = {}
        for k,v in self.cases.items():
            raw = ('synthetic-log-' + str(v['job']['id'])).encode()
            self.logs[v['job']['id']] = raw
            v['log_bytes'],v['log_sha'] = len(raw),restore._sha(raw)
        self.history = [self.gap_runs[k] for k in restore._ZERO_ORDER[:-2]] + [self.abort,self.prior]
        patch.object(restore, '_ZERO_GAPS', self.cases).start()
        pins = {p:restore._sha((p+'operations-safety-').encode()) for p in restore._ZERO_CODE}
        patch.object(restore, '_ZERO_CODE', pins).start()

    def git(self, root, *args):
        if args[0]=='show' and not args[1].startswith('HEAD:'):
            relative=args[1].split(':',1)[1]
            raw=(relative+'operations-safety-').encode()+(b'changed' if self.code_bad else b'')
            return subprocess.CompletedProcess(args,0,raw,b'')
        return RestoreTests.git(self,root,*args)

    def metadata(self, url):
        if '/runs?' in url:
            return {'workflow_runs':self.history}
        for identity,run in self.gap_runs.items():
            if url==restore.BASE+f'runs/{identity}':
                return run
            if url==restore.BASE+f'runs/{identity}/attempts/1/jobs?per_page=100':
                return self.gap_jobs[identity]
            if url==restore.BASE+f'runs/{identity}/artifacts?per_page=100':
                return copy.deepcopy(self.cases[str(identity)]['artifacts'])
        return super().metadata(url)

    def perform(self):
        with patch.object(restore,'_git',side_effect=self.git):
            return restore.restore_latest(self.root,fetch_json=self.metadata,
                fetch_bytes=lambda _:self.raw,fetch_log=lambda identity:self.logs[identity])

    def test_actual_order_full_topology_returns_only_deep600(self):
        self.assertEqual(self.perform()['run_id'],37287805994)
        self.assertEqual(restore.verify_current(self.root),self.incoming)

    def test_unknown_extra_running_duplicate_and_missing_gap_fail_closed(self):
        original=list(self.history)
        for mode in ('new','extra','running','duplicate','missing'):
            with self.subTest(mode=mode):
                self.history=list(original)
                if mode=='missing': self.history.pop(3)
                elif mode=='duplicate': self.history.insert(0,copy.deepcopy(self.history[0]))
                else:
                    run=copy.deepcopy(self.history[0])
                    run['id']=37450000000 if mode!='extra' else 37401000000
                    if mode=='running': run['status']='in_progress'
                    self.history.insert(0,run)
                with self.assertRaises(ValueError): self.perform()
                self.assertEqual(restore.verify_current(self.root),self.current)
        self.history=original

    def test_each_actual_gap_attempt_job_full_steps_code_and_log_are_bound(self):
        for identity in restore._ZERO_ORDER[:-2]:
            for mode in ('attempt','job','extra_job','steps','window','actuation','log','code','inventory'):
                with self.subTest(identity=identity,mode=mode):
                    saved=copy.deepcopy((self.gap_runs,self.gap_jobs,self.logs,self.cases,self.history))
                    if mode=='attempt': self.gap_runs[identity]['run_attempt']=2
                    if mode=='job': self.gap_jobs[identity]['jobs'][0]['id']+=1
                    if mode=='extra_job': self.gap_jobs[identity]['total_count']=2
                    steps=self.gap_jobs[identity]['jobs'][0]['steps']
                    if mode=='steps': steps.append(dict(steps[-1],number=999))
                    if mode=='window': steps[0]['completed_at']='2026-10-06T23:59:59Z'
                    if mode=='actuation': next(s for s in steps if s['conclusion']=='skipped')['conclusion']='success'
                    if mode=='log': self.logs[self.cases[str(identity)]['job']['id']]+=b'changed'
                    if mode=='code': self.code_bad=True
                    if mode=='inventory':
                        original_metadata=self.metadata
                        def changed(url):
                            value=original_metadata(url)
                            if url==restore.BASE+f'runs/{identity}/artifacts?per_page=100': value['total_count']+=1
                            return value
                    else: changed=self.metadata
                    with patch.object(restore,'_git',side_effect=self.git):
                        with self.assertRaises(ValueError):
                            restore.restore_latest(self.root,fetch_json=changed,fetch_bytes=lambda _:self.raw,fetch_log=lambda j:self.logs[j])
                    self.gap_runs,self.gap_jobs,self.logs,new_cases,self.history=saved
                    self.cases.clear();self.cases.update(new_cases)
                    self.code_bad=False
                    self.assertEqual(restore.verify_current(self.root),self.current)

    def test_actual_deep_gates_not_masked_rest_success(self):
        for identity in (37362386981,37398490984,37439906629):
            rows=self.cases[str(identity)]['steps']
            self.assertEqual(next(r[3] for r in rows if r[0]==7),'success')
            for number in (58,62,65,71,76):
                self.assertEqual(next(r[3] for r in rows if r[0]==number),'skipped')
        self.assertEqual(self.cases['37439906629']['job']['id'],112190829536)


class ActualCapturedZeroGapTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('JARVIS_GAP_EVIDENCE_TMP'), 'actual raw logs stay outside repository')
    def test_genuine_captured_chain_code_and_raw_log_digests(self):
        folder=Path(os.environ['JARVIS_GAP_EVIDENCE_TMP'])
        metadata=folder/'audit-oct6-latest'
        responses={restore.BASE+'runs?per_page=100':json.loads((metadata/'runs-live.json').read_bytes())}
        for identity in restore._ZERO_ORDER:
            for kind,suffix in (('run',''),('jobs','/attempts/1/jobs?per_page=100'),('artifacts','/artifacts?per_page=100')):
                responses[restore.BASE+f'runs/{identity}'+suffix]=json.loads((metadata/f'{identity}-{kind}.json').read_bytes())
        def raw_log(identity):
            matches=list(folder.glob(f'*-job{identity}.log'))
            self.assertEqual(len(matches),1)
            self.assertLessEqual(matches[0].stat().st_size,restore._MAX_GAP_LOG)
            return matches[0].read_bytes()
        root=Path(__file__).resolve().parents[1]
        run,active=restore._latest(root,responses.__getitem__,None)
        self.assertTrue(active)
        self.assertEqual(run['id'],37439906629)
        predecessor=restore._zero_operations_predecessor(root,run,responses.__getitem__,None,raw_log)
        self.assertEqual(predecessor['id'],37287805994)
        artifacts=responses[restore.BASE+'runs/37287805994/artifacts?per_page=100']['artifacts']
        self.assertEqual(next(a['digest'] for a in artifacts if a['name']=='operations-safety-37287805994-1'),restore._ABORT_ARTIFACT_DIGEST)


class WhitespaceCompactionTests(unittest.TestCase):
    def compact(self, raw, **kwargs):
        return restore._whitespace_compact(io.BytesIO(raw), expected_bytes=kwargs.get('size',len(raw)),
                                          expected_sha=kwargs.get('sha',restore._sha(raw)))

    def test_only_outside_string_whitespace_removed(self):
        raw = b' { "text" : "a  b\\t c\\\\ d\\\"e", "n" : 1.00, "order" : [ 2, 1 ] } \n'
        compact = self.compact(raw)
        self.assertIn(b'a  b',compact)
        self.assertIn(b'1.00',compact)
        self.assertEqual(restore._json(raw),restore._json(compact))
        self.assertEqual(compact,b'{"text":"a  b\\t c\\\\ d\\\"e","n":1.00,"order":[2,1]}')

    def test_invalid_json_duplicate_nan_and_original_binding_denied(self):
        for raw in (b'{"a":1,"a":2}',b'{"n":NaN}',b'{"s":"unterminated}',b'{"a":01}'):
            with self.subTest(raw=raw),self.assertRaises(ValueError): self.compact(raw)
        with self.assertRaises(ValueError): self.compact(b'{}',size=3)
        with self.assertRaises(ValueError): self.compact(b'{}',sha='0'*64)
        with patch.object(restore,'MAX_FILE_BYTES',8):
            with self.assertRaises(ValueError): self.compact(b'{"s":"   inside   "}')

    def test_zip_input_reads_are_chunk_bounded(self):
        class Bounded(io.BytesIO):
            def read(self,size=-1):
                self_test.assertLessEqual(size,64*1024)
                self_test.assertGreater(size,0)
                return super().read(size)
        self_test=self
        raw=b' '*70000+b'{"x":" a b "}'
        self.assertEqual(restore._whitespace_compact(Bounded(raw),expected_bytes=len(raw),expected_sha=restore._sha(raw)),b'{"x":" a b "}')

    def test_exact_fixture_zip_compacts_then_ordinary_validator(self):
        state=core.empty_state()
        rawstate=b' '*10000+body(state)
        compact=self.compact(rawstate)
        raw=bundle({restore.STATE:rawstate,restore.LEDGER:b'{}'})
        pins={'_ABORT_ARTIFACT_DIGEST':'sha256:'+restore._sha(raw),
              '_REVIEWED_STATE_BYTES':len(rawstate),'_REVIEWED_STATE_SHA':restore._sha(rawstate),
              '_REVIEWED_COMPACT_BYTES':len(compact),'_REVIEWED_COMPACT_SHA':restore._sha(compact),
              '_REVIEWED_ARCHIVE_MEMBERS':2,'MAX_FILE_BYTES':4096}
        with patch.multiple(restore,**pins):
            with self.assertRaises(ValueError): restore._archive(raw)
            files,evidence=restore._compact_reviewed_archive(raw)
            self.assertEqual(files[restore.STATE],compact)
            self.assertEqual(files[restore.LEDGER],b'{}')
            self.assertTrue(evidence['parsed_object_equal'])
            self.assertEqual(evidence['raw_sha256'],restore._sha(rawstate))
            with self.assertRaises(ValueError): restore._compact_reviewed_archive(raw+b'spoof')
            with patch.object(restore,'_REVIEWED_STATE_SHA','0'*64):
                with self.assertRaises(ValueError): restore._compact_reviewed_archive(raw)
            with patch.object(restore,'MAX_TOTAL_BYTES',100):
                with self.assertRaises(ValueError): restore._compact_reviewed_archive(raw)
            with patch.object(restore,'_REVIEWED_ARCHIVE_MEMBERS',3):
                with self.assertRaises(ValueError): restore._compact_reviewed_archive(raw)


if __name__ == '__main__': unittest.main()
