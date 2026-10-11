#!/usr/bin/env python3
"""Restore latest authenticated completed source-run safety before any actuation.

GitHub transport/metadata, exact digest, main ancestry and allowlisted workflow
lineage are mandatory. Missing post-activation artifacts stop readers rather
than reset a budget. Pre-activation runs cannot have this procedure ledger.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
if str(ROOT/'scripts') not in sys.path: sys.path.insert(0,str(ROOT/'scripts'))
from scripts.github_artifact_io import REPOSITORY, fetch_github_json, fetch_artifact_bytes
from scripts import source_safety_checkpoint as safety

WORKFLOWS = frozenset(('.github/workflows/daiso-real-collection.yml',
 '.github/workflows/JARVIS-Core-Automation.yml', '.github/workflows/JARVIS-Deep-Analysis.yml'))
BASE = 'https://api.github.com/repos/' + REPOSITORY + '/actions/'


def _git(root, *args):
    return subprocess.run(['git','-C',str(root),*args],capture_output=True)


def never_started(run, fetch_json, base):
    """True only for a run GitHub cancelled before creating any job (concurrency supersede).

    Shared group main-publish keeps one pending run; GitHub cancels the older pending
    run. Such a run executed nothing, so it cannot have produced or changed safety
    evidence. Proven per run through the authenticated jobs API; any doubt keeps it.
    """
    if run.get('status') != 'completed' or run.get('conclusion') != 'cancelled':
        return False
    payload = fetch_json(base + f"runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100")
    return (isinstance(payload, dict) and payload.get('total_count') == 0
            and payload.get('jobs') == [])


def verify_current(root):
    if (root/safety.PENDING).exists(): raise ValueError('source_restore_interrupted')
    files = safety._snapshot(root)
    if any(name not in files for name in safety.ALLOWLIST):
        raise ValueError('source_continuity_pair_missing')
    safety._validate(files)
    return files


def _inner(outer):
    with zipfile.ZipFile(io.BytesIO(outer)) as archive:
        entries = archive.infolist()
        if len(entries) != 1 or entries[0].filename != 'source-safety.zip' or entries[0].is_dir() or entries[0].file_size > safety.MAX_ARCHIVE_BYTES:
            raise ValueError('source_safety_outer_members_invalid')
        mode = entries[0].external_attr >> 16
        if mode & 0o170000 not in (0,0o100000): raise ValueError('source_safety_outer_link_denied')
        return archive.read(entries[0])


def restore_latest(root, *, fetch_json=fetch_github_json, fetch_bytes=fetch_artifact_bytes,
                   current_run_id=None):
    root = Path(root).absolute()
    verify_current(root)
    payload = fetch_json(BASE + 'runs?per_page=100')
    runs = payload.get('workflow_runs') if isinstance(payload,dict) else None
    if not isinstance(runs,list): raise ValueError('source_run_history_unavailable')
    candidates = []
    for run in runs:
        if not isinstance(run,dict) or run.get('path') not in WORKFLOWS or str(run.get('id')) == str(current_run_id): continue
        if run.get('head_branch') != 'main' or (run.get('head_repository') or {}).get('full_name') != REPOSITORY: continue
        if run.get('status') != 'completed': continue
        if type(run.get('id')) is not int or type(run.get('run_attempt')) is not int: raise ValueError('source_run_identity_invalid')
        candidates.append(run)
    candidates = [r for r in sorted(candidates, key=lambda r:r['id'], reverse=True)]
    while candidates and never_started(candidates[0], fetch_json, BASE): candidates.pop(0)
    if not candidates: raise ValueError('source_run_history_missing')
    run = candidates[0]
    commit = run.get('head_sha','')
    if not re.fullmatch(r'[0-9a-f]{40}',commit) or _git(root,'merge-base','--is-ancestor',commit,'HEAD').returncode:
        raise ValueError('source_run_not_main_ancestor')
    active = _git(root,'cat-file','-e',commit+':scripts/run_source_procedures.py').returncode == 0
    if not active:
        return {'continuity':'verified','status':'trusted_pre_activation_history','run_id':run['id']}
    response = fetch_json(BASE + f"runs/{run['id']}/artifacts?per_page=100")
    name = f"source-safety-{run['id']}-{run['run_attempt']}"
    artifacts = [a for a in (response.get('artifacts') or []) if isinstance(a,dict) and a.get('name') == name and a.get('expired') is False]
    if len(artifacts) != 1: raise ValueError('latest_source_safety_artifact_missing_or_ambiguous')
    artifact = artifacts[0]
    metadata = artifact.get('workflow_run') or {}
    if metadata.get('id') != run['id'] or metadata.get('head_sha') != commit or metadata.get('head_branch') != 'main':
        raise ValueError('source_artifact_run_binding_invalid')
    identity = artifact.get('id')
    if type(identity) is not int or identity <= 0: raise ValueError('source_artifact_identity_invalid')
    if artifact.get('archive_download_url') != BASE + f'artifacts/{identity}/zip':
        raise ValueError('source_artifact_download_scope_invalid')
    digest = artifact.get('digest')
    if not isinstance(digest,str) or not re.fullmatch(r'sha256:[0-9a-f]{64}',digest):
        raise ValueError('source_artifact_authentic_digest_missing')
    outer = fetch_bytes(artifact['archive_download_url'])
    if hashlib.sha256(outer).hexdigest() != digest.split(':',1)[1]:
        raise ValueError('source_artifact_digest_mismatch')
    inner = _inner(outer)
    with tempfile.TemporaryDirectory(prefix='source-safety-read-',dir=os.environ.get('RUNNER_TEMP') or root.parent) as folder:
        path = Path(folder)/'source-safety.zip'; path.write_bytes(inner)
        expected = safety._lineage(REPOSITORY,run['id'],run['run_attempt'],commit)
        incoming = safety._archive(path, expected)
        current = verify_current(root)
        try:
            safety._nonregression(current, incoming)
        except safety.Blocked:
            # A strictly newer AUTHENTICATED main snapshot is kept, never rolled
            # back to an older artifact. Dirty/unvouched local state is denied.
            if any(_git(root,'show','HEAD:'+n).returncode or _git(root,'show','HEAD:'+n).stdout != body for n,body in current.items()):
                raise ValueError('source_main_snapshot_not_exact_head') from None
            safety._nonregression(incoming,current)
            return {'continuity':'verified','status':'artifact_history_already_preserved_in_main','run_id':run['id']}
        safety.restore(root,path,expected_repository=REPOSITORY,expected_run_id=run['id'],
          expected_run_attempt=run['run_attempt'],expected_commit=commit)
    verify_current(root)
    return {'continuity':'verified','status':'authenticated_source_safety_restored','run_id':run['id']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--verify-current',action='store_true')
    args=parser.parse_args()
    try:
        if args.verify_current:
            verify_current(args.root); result={'continuity':'verified','status':'verified_current'}
        else:
            if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
                raise ValueError('authenticated_github_runner_required')
            result=restore_latest(args.root,current_run_id=os.environ.get('GITHUB_RUN_ID'))
        output=os.environ.get('GITHUB_OUTPUT')
        if output:
            with open(output,'a',encoding='utf-8') as stream: stream.write('continuity=verified\n')
        print('SOURCE_SAFETY_OK ' + json.dumps(result,sort_keys=True))
        return 0
    except (ValueError,OSError,KeyError,TypeError,zipfile.BadZipFile):
        print('SOURCE_SAFETY_BLOCKED authenticated_history_or_checkpoint_reconciliation_required')
        return 1

if __name__=='__main__': raise SystemExit(main())
