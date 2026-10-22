#!/usr/bin/env python3
"""Shared reviewed-copy transaction mechanics; no product or mutation authority.

The fixed entrypoint supplies a trusted in-process policy object. Policies are
never selected by a plan, ticket, import path, CLI string, or network response.
The policy validates its exact target, namespace, implementation and content.
All write-capable entrypoints must use the one-attempt journal/checkpoint path.

Policy interface: WORKFLOW, PREFIX, validate_plan_digest(plan, expected),
build_plan(scope, root, snapshot, *, now), fetch_sources(pd_no, root, *, fetch),
verify_readback(copy_plan, snapshot), and result(state, plan, **extra).
An optional after_readback(plan, snapshot, client) returns extra result fields, including
an overriding state, for additional read-only checks such as public readback.
REQUIRE_ORIGINAL_CHECKPOINT=True requires stable, complete retained history and
the oldest operation checkpoint during restore; this flag is trusted code only.
"""
from datetime import timedelta
import hashlib
import io
import re
from urllib.parse import urlsplit
import zipfile

import apply_reviewed_product_gallery as gallery
from apply_reviewed_product_gallery import (Hold, PriorCheckpoint, require, utcnow,
    stamp, read_json, json_bytes, strict_json, atomic_json, journal_lock,
    https_request, SHA1, REPOSITORY, MAX_PAGES)


def make_journal(policy, plan, *, repository, run_id, run_attempt, code_sha, workflow_path):
    require(REPOSITORY.fullmatch(repository or '') and str(run_id).isdigit() and str(run_attempt).isdigit() and
            SHA1.fullmatch(code_sha or '') and workflow_path == policy.WORKFLOW, 'workflow_context_required')
    return {'schema_version':1,'operation_id':plan['operation_id'],'plan_digest':plan['plan_digest'],
            'state':'prepared','repository':repository,'run_id':str(run_id),'run_attempt':str(run_attempt),
            'code_sha':code_sha,'workflow_path':workflow_path,
            'artifact_name':policy.PREFIX+plan['operation_id']+'-'+str(run_id)+'-'+str(run_attempt),
            'before':plan['before'],'changes':plan['copy_plan']['changes'],'write_attempts':0,
            'publication_allowed':False,'upload_allowed':False}


class GitHubCheckpoint:
    """Read-only verification of an uploaded write-ahead artifact and prior history."""
    def __init__(self, token, artifact_id, artifact_digest, *, policy, request=https_request):
        require(isinstance(token, str) and token and str(artifact_id).isdigit(), 'github_checkpoint_credentials_missing')
        require(isinstance(artifact_digest, str) and re.fullmatch(r'(sha256:)?[0-9a-f]{64}', artifact_digest), 'artifact_digest_invalid')
        self.token, self.artifact_id = token, str(artifact_id)
        self.expected_digest = artifact_digest.removeprefix('sha256:')
        self.request = request
        self.policy = policy

    def api(self, path, *, raw=False):
        status, headers, body = self.request('https://api.github.com' + path, hosts={'api.github.com'},
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28'})
        if raw:
            return status, headers, body
        require(status == 200, 'github_checkpoint_api_failed')
        result = strict_json(body)
        require(isinstance(result, dict), 'github_checkpoint_response_invalid')
        return result

    def verify(self, plan, journal):
        self.policy.validate_plan_digest(plan, plan['plan_digest'])
        expected = make_journal(self.policy, plan, **{k:journal.get(k) for k in
                    ('repository','run_id','run_attempt','code_sha','workflow_path')})
        require(json_bytes(expected) == json_bytes(journal), 'checkpoint_policy_namespace_mismatch')
        prefix = '/repos/' + journal['repository']
        current = self.api(prefix + '/actions/artifacts/' + self.artifact_id)
        require(str(current.get('id')) == self.artifact_id and current.get('name') == journal['artifact_name']
                and current.get('expired') is False, 'checkpoint_artifact_identity_mismatch')
        require(str((current.get('workflow_run') or {}).get('id')) == journal['run_id'] and
                (current.get('workflow_run') or {}).get('head_sha') == journal['code_sha'], 'checkpoint_run_mismatch')
        require(stamp(current.get('expires_at')) - stamp(current.get('created_at')) >= timedelta(days=30) - timedelta(minutes=1),
                'checkpoint_retention_under_30_days')
        require(current.get('digest') == 'sha256:' + self.expected_digest, 'checkpoint_metadata_digest_mismatch')
        run = self.api(prefix + '/actions/runs/' + journal['run_id'])
        require(str(run.get('id')) == journal['run_id'] and str(run.get('run_attempt')) == journal['run_attempt']
                and run.get('head_sha') == journal['code_sha'] and run.get('path') == journal['workflow_path']
                and run.get('event') == 'workflow_dispatch' and run.get('status') == 'in_progress', 'checkpoint_workflow_mismatch')
        strict = getattr(self.policy, 'REQUIRE_ORIGINAL_CHECKPOINT', False) is True
        history = (self._stable_artifact_history(journal['repository']) if strict else
                   self._artifact_history(journal['repository']))
        require(any(str(a['id']) == self.artifact_id for a in history), 'checkpoint_absent_from_history')
        if strict:
            selected = next(a for a in history if str(a['id']) == self.artifact_id)
            require(all(selected.get(k) == current.get(k) for k in
                        ('id','name','digest','expired','created_at','expires_at','workflow_run')),
                    'checkpoint_history_metadata_mismatch')
        prior = [a for a in history if
                 (a.get('name') or '').startswith(self.policy.PREFIX + plan['operation_id'] + '-')
                 and str(a['id']) != self.artifact_id]
        if prior:
            raise PriorCheckpoint(sorted(prior, key=lambda a: a['id'])[0])
        found_plan, found_journal = self.download(journal['repository'])
        require(json_bytes(found_plan) == json_bytes(plan) and json_bytes(found_journal) == json_bytes(journal),
                'checkpoint_plan_or_journal_bytes_mismatch')
        return True

    def _artifact_history(self, repository, *, strict=False):
        """One bounded complete scan; callers choose whether stability needs recheck."""
        prefix = '/repos/' + repository
        seen, total, history = set(), None, []
        for page in range(1, MAX_PAGES + 1):
            batch = self.api(prefix + '/actions/artifacts?per_page=100&page=' + str(page))
            require(type(batch.get('total_count')) is int and isinstance(batch.get('artifacts'), list), 'checkpoint_scan_incomplete')
            if total is None:
                total = batch['total_count']
            require(batch['total_count'] == total, 'checkpoint_scan_drift')
            for artifact in batch['artifacts']:
                require(isinstance(artifact, dict) and type(artifact.get('id')) is int and artifact['id'] not in seen,
                        'checkpoint_scan_duplicate')
                require(not strict or (isinstance(artifact.get('name'), str) and bool(artifact['name'])),
                        'checkpoint_scan_identity_missing')
                seen.add(artifact['id'])
                history.append(artifact)
            if len(seen) == total:
                return history
            require(batch['artifacts'] and len(seen) < total, 'checkpoint_scan_incomplete')
        raise Hold('checkpoint_scan_limit')

    def _stable_artifact_history(self, repository):
        # Two full scans detect changing membership/metadata, not just counts.
        history = self._artifact_history(repository, strict=True)
        repeated = self._artifact_history(repository, strict=True)
        require(json_bytes(sorted(history, key=lambda a:a['id'])) ==
                json_bytes(sorted(repeated, key=lambda a:a['id'])), 'checkpoint_scan_drift')
        return history

    def _require_original_checkpoint(self, repository, plan, journal, current):
        # An after-body plan can otherwise bless a new protected-field baseline.
        # Require the first retained checkpoint of this immutable operation.
        history = self._stable_artifact_history(repository)
        namespace = self.policy.PREFIX + plan['operation_id'] + '-'
        matching = [a for a in history if a['name'].startswith(namespace)]
        require(matching and all(a.get('expired') is False for a in matching),
                'restore_history_expired_or_missing')
        selected = next((a for a in matching if str(a['id']) == self.artifact_id), None)
        require(selected is not None, 'checkpoint_absent_from_history')
        require(all(selected.get(k) == current.get(k) for k in
                    ('id','name','digest','expired','created_at','expires_at','workflow_run'))
                and selected['name'] == journal['artifact_name'], 'restore_history_metadata_mismatch')
        require(int(self.artifact_id) == min(a['id'] for a in matching),
                'restore_original_checkpoint_required')

    def download(self, repository):
        require(REPOSITORY.fullmatch(repository or ''), 'checkpoint_repository_invalid')
        prefix = '/repos/' + repository
        status, headers, archive = self.api(prefix + '/actions/artifacts/' + self.artifact_id + '/zip', raw=True)
        if status == 302:
            target = headers.get('location')
            parsed = urlsplit(target or '')
            host = parsed.hostname or ''
            require(host.endswith('.blob.core.windows.net') or host.endswith('.actions.githubusercontent.com'),
                    'checkpoint_download_host_invalid')
            # GitHub authorization header is NEVER forwarded to signed object storage.
            status, _, archive = self.request(target, hosts={host})
        require(status == 200 and hashlib.sha256(archive).hexdigest() == self.expected_digest, 'checkpoint_zip_digest_mismatch')
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
                require(set(zipped.namelist()) == {'plan.json', 'journal.json'} and len(zipped.infolist()) == 2,
                        'checkpoint_zip_members_invalid')
                require(all(i.file_size <= gallery.MAX_BYTES and not i.flag_bits & 1 for i in zipped.infolist()), 'checkpoint_zip_unsafe')
                raw_plan, raw_journal = zipped.read('plan.json'), zipped.read('journal.json')
                plan, journal = strict_json(raw_plan), strict_json(raw_journal)
                require(raw_plan == json_bytes(plan) and raw_journal == json_bytes(journal), 'checkpoint_json_not_canonical')
        except (ValueError, OSError, zipfile.BadZipFile, RuntimeError):
            raise Hold('checkpoint_zip_invalid') from None
        return plan, journal

    def restore(self, repository, *, expected_plan_digest, expected_shop, expected_product):
        require(REPOSITORY.fullmatch(repository or ''), 'checkpoint_repository_invalid')
        current = self.api('/repos/'+repository+'/actions/artifacts/'+self.artifact_id)
        require(str(current.get('id')) == self.artifact_id and current.get('expired') is False and
                current.get('digest') == 'sha256:'+self.expected_digest, 'restore_artifact_invalid')
        require(stamp(current.get('expires_at')) - stamp(current.get('created_at')) >= timedelta(days=30) - timedelta(minutes=1),
                'checkpoint_retention_under_30_days')
        plan, journal = self.download(repository)
        self.policy.validate_plan_digest(plan, expected_plan_digest)
        require(plan['scope']['canonical_shop'] == expected_shop and plan['scope']['product_id'] == expected_product,
                'restore_exact_target_mismatch')
        expected = make_journal(self.policy, plan, **{k:journal.get(k) for k in
                    ('repository','run_id','run_attempt','code_sha','workflow_path')})
        require(json_bytes(expected) == json_bytes(journal) and journal['repository'] == repository and
                current.get('name') == journal['artifact_name'] and
                str((current.get('workflow_run') or {}).get('id')) == journal['run_id'] and
                (current.get('workflow_run') or {}).get('head_sha') == journal['code_sha'], 'restore_journal_mismatch')
        if getattr(self.policy, 'REQUIRE_ORIGINAL_CHECKPOINT', False) is True:
            self._require_original_checkpoint(repository, plan, journal, current)
        run = self.api('/repos/'+repository+'/actions/runs/'+journal['run_id'])
        require(str(run.get('id')) == journal['run_id'] and run.get('event') == 'workflow_dispatch' and
                run.get('head_sha') == journal['code_sha'] and run.get('path') == self.policy.WORKFLOW and
                int(run.get('run_attempt',0)) >= int(journal['run_attempt']), 'restore_run_mismatch')
        return plan, journal


def reconcile(policy, plan, client):
    policy.validate_plan_digest(plan, plan['plan_digest'])
    try:
        after = client.read_snapshot(plan['scope']['product_id'])
        policy.verify_readback(plan['copy_plan'],after)
        extra = policy.after_readback(plan, after, client) if hasattr(policy, 'after_readback') else {}
        require(isinstance(extra, dict), 'readback_result_invalid')
        extra = dict(extra)
        state = extra.pop('state', 'verified')
        require(state in {'verified', 'verification_pending', 'public_verification_pending'}, 'readback_state_invalid')
        return policy.result(state,plan,writes=0,**extra)
    except Exception as exc:
        return policy.result('verification_pending',plan,writes=0,reason=str(exc) if isinstance(exc,Hold) else type(exc).__name__)


def save_after_attempt(path, journal, *, atomic_write=atomic_json):
    try:
        atomic_write(path,journal)
        return True
    except OSError:
        # os.replace may have succeeded; never label this unchanged or retryable.
        return False


def _persist_readback(path, journal, observed, *, atomic_write):
    journal.update(state=observed['state'], last_readback=dict(observed))
    return {**observed, 'journal_saved':save_after_attempt(path,journal,atomic_write=atomic_write)}


def execute(policy, plan, *, root, expected_plan_digest, client=None, journal_path=None,
            checkpoint=None, apply=False, now=None, source_fetch=gallery.fetch_asset,
            atomic_write=atomic_json):
    policy.validate_plan_digest(plan, expected_plan_digest)
    require(type(apply) is bool, 'apply_boolean_required')
    if not apply:
        return policy.result('dry_run',plan,writes=0)
    require(client is not None and journal_path is not None, 'client_and_journal_required')
    with journal_lock(journal_path):
        journal = read_json(journal_path)
        require(journal.get('operation_id') == plan['operation_id'] and
                journal.get('plan_digest') == expected_plan_digest, 'journal_operation_mismatch')
        if journal.get('state') != 'prepared' or journal.get('write_attempts') != 0:
            if getattr(policy, 'REQUIRE_ORIGINAL_CHECKPOINT', False) is True:
                require(checkpoint is not None, 'original_checkpoint_required_for_resume')
                restored_plan, restored_journal = checkpoint.restore(journal.get('repository'),
                    expected_plan_digest=expected_plan_digest,
                    expected_shop=plan['scope']['canonical_shop'],
                    expected_product=plan['scope']['product_id'])
                policy.validate_plan_digest(restored_plan, expected_plan_digest)
                require(json_bytes(restored_plan) == json_bytes(plan), 'resume_original_plan_mismatch')
                expected = make_journal(policy, plan, **{k:journal.get(k) for k in
                            ('repository','run_id','run_attempt','code_sha','workflow_path')})
                require(json_bytes(restored_journal) == json_bytes(expected),
                        'resume_checkpoint_context_mismatch')
                mutable = {'state','write_attempts','error','last_readback'}
                require(json_bytes({k:v for k,v in journal.items() if k not in mutable}) ==
                        json_bytes({k:v for k,v in restored_journal.items() if k not in mutable}),
                        'resume_immutable_journal_mismatch')
            observed = reconcile(policy,plan,client)
            if hasattr(policy, 'after_readback'):
                return _persist_readback(journal_path,journal,observed,atomic_write=atomic_write)
            return observed
        current = client.read_snapshot(plan['scope']['product_id'])
        policy.fetch_sources(plan['scope']['pd_no'],root,fetch=source_fetch)
        rebuilt = policy.build_plan(plan['scope'],root,current,now=now or utcnow())
        require(rebuilt['plan_digest'] == expected_plan_digest, 'preapply_drift')
        if not plan['copy_plan']['changes'] and not hasattr(policy, 'after_readback'):
            return policy.result('no_op',plan,writes=0)
        require(checkpoint is not None, 'durable_checkpoint_required')
        expected = make_journal(policy, plan, **{k:journal.get(k) for k in
                    ('repository','run_id','run_attempt','code_sha','workflow_path')})
        require(json_bytes(journal) == json_bytes(expected), 'journal_shape_mismatch')
        try:
            require(checkpoint.verify(plan,journal) is True,'checkpoint_not_verified')
        except PriorCheckpoint:
            # The original artifact must be explicitly restored; do not retry.
            return policy.result('prior_checkpoint_reconcile_required',plan,writes=0)
        last = client.read_snapshot(plan['scope']['product_id'])
        last_plan = policy.build_plan(plan['scope'],root,last,now=now or utcnow())
        require(last_plan['plan_digest'] == expected_plan_digest,'last_moment_drift')
        if not plan['copy_plan']['changes']:
            # A newly prepared after-body plan cannot replace the original
            # protected baseline. Verify its immutable checkpoint/history before
            # accepting a no-write reconciliation, just as for a write attempt.
            observed = reconcile(policy,plan,client)
            return _persist_readback(journal_path,journal,observed,atomic_write=atomic_write)
        journal.update(state='write_started',write_attempts=1)
        atomic_write(journal_path,journal)  # Any failure stops BEFORE the request.
        try:
            client.update_once(plan['scope']['product_id'],plan['copy_plan']['changes'])
        except BaseException as exc:
            journal.update(state='write_unknown',error=type(exc).__name__)
            saved = save_after_attempt(journal_path,journal,atomic_write=atomic_write)
            if not isinstance(exc,Exception):
                raise
            return policy.result('write_unknown',plan,writes=1,journal_saved=saved,reason=type(exc).__name__)
        journal['state'] = 'verification_pending'
        saved = save_after_attempt(journal_path,journal,atomic_write=atomic_write)
        observed = reconcile(policy,plan,client)
        journal['state'], journal['last_readback'] = observed['state'], observed
        saved = save_after_attempt(journal_path,journal,atomic_write=atomic_write) and saved
        return policy.result(observed['state'],plan,writes=1,journal_saved=saved,readback=observed)
