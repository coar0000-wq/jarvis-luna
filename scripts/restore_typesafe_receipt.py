"""Restore receipts once before batches; deny missing evidence, including killed runs.

Not a distributed budget guarantee. Caller must remove billing proof on failure.
GH_TOKEN is inherited, never logged or passed in arguments. Offline uses fixtures.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
import zipfile
try:
    from . import typesafe_shared as shared
except ImportError:
    import typesafe_shared as shared

LOCAL_ONLY = 'TYPESAFE_RECEIPT_LOCAL_ONLY'
READY = 'TYPESAFE_RECEIPT_READY'
CONSUMERS = frozenset(('JARVIS-Deep-Analysis.yml', 'shopify-listing-copy.yml'))
RECEIPT = re.compile(r'typesafe-budget-receipt-([1-9][0-9]*)-([1-9][0-9]*)\Z')
FILENAME = 'typesafe_shared_state.json'
MAX_BYTES = 32 * 1024 * 1024
RELEASE_SHA = 'caa10c73d581b163102a5fa69bdb49912a85a1f7'
FULL_SHA = re.compile(r'[a-f0-9]{40}\Z')

class RestoreDenied(ValueError):
    pass

def require(condition):
    if not condition:
        raise RestoreDenied('receipt_safety_check_failed')

def timestamp(value):
    require(isinstance(value, str))
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.tzinfo is not None)
    return result.astimezone(timezone.utc)

def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out)
            out[key] = value
        return out
    def constant(_):
        raise RestoreDenied('invalid_json')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)

def validate_state(state, identity):
    """Pure schema/account validation, matching shared.read's contract."""
    require(isinstance(state, dict) and type(state.get('schema')) is int and state['schema'] == 1)
    require(isinstance(state.get('stopped'), str))
    require(all(isinstance(state.get(k), dict) for k in ('cache', 'versions', 'workflows')))
    require(all(shared.number(state.get(k)) for k in ('account_limit_usd', 'account_charged_tokens')))
    require(state.get('key_sha256') == identity[0] and state.get('org_id') == identity[1])
    require(bool(re.fullmatch(r'[a-f0-9]{64}', identity[0])) and bool(identity[1]))
    for scope, budget in state['workflows'].items():
        require(isinstance(scope, str) and isinstance(budget, dict))
        require(all(shared.number(budget.get(k)) for k in (
            'calls', 'charged_input_tokens', 'reserved_input_tokens', 'input_tokens', 'output_tokens', *shared.DEFAULTS)))
        require(isinstance(budget.get('call_log'), list) and isinstance(budget.get('stopped', ''), str))
    return copy.deepcopy(state)

def read_ledger(path, identity, missing_ok=False):
    path = Path(path)
    if missing_ok and not path.exists() and not path.is_symlink():
        return None
    require(not path.is_symlink() and stat.S_ISREG(path.lstat().st_mode))
    require(path.stat().st_size <= MAX_BYTES)
    state = strict_json(path.read_text(encoding='utf-8'))
    require(shared.read(path) == state)
    return validate_state(state, identity)

def workflow_filename(run):
    return str(run.get('path', '')).split('@', 1)[0].rsplit('/', 1)[-1]

def eligible_runs(runs, repo, current_run_id, head_classifications, current_run_attempt=1):
    """Filter by release ancestry, never by creation/start timestamps."""
    require(isinstance(head_classifications, dict))
    result = {}
    for run in runs:
        if (run.get('status') != 'completed' or run.get('head_branch') != 'main'
                or run.get('head_repository', {}).get('full_name', '').lower() != repo.lower()
                or workflow_filename(run) not in CONSUMERS):
            continue
        require(type(run.get('id')) is int and run['id'] > 0)
        require(type(run.get('run_attempt')) is int and run['run_attempt'] > 0)
        require(isinstance(run.get('name'), str) and bool(run['name']))
        if str(run['id']) == str(current_run_id) and run['run_attempt'] >= current_run_attempt:
            continue
        if classify_head(run.get('head_sha'), head_classifications) == 'legacy':
            continue
        key = (run['id'], run['run_attempt'])
        require(key not in result or result[key] == run)
        result[key] = run
    return result

def select_artifacts(artifacts, runs):
    """Newest first; exact name/run/attempt/branch/repository binding."""
    selected = []
    for artifact in artifacts:
        match = RECEIPT.fullmatch(str(artifact.get('name', '')))
        if not match or artifact.get('expired') is not False:
            continue
        wr = artifact.get('workflow_run', {})
        run = runs.get((int(match[1]), int(match[2])))
        if wr.get('id') != int(match[1]):
            continue
        if run is None:
            continue
        if (int(match[1]) != run['id'] or int(match[2]) != run['run_attempt']
                or wr.get('head_branch') != 'main'
                or wr.get('head_repository_id') != run['head_repository'].get('id')
                or wr.get('head_repository_id') is None):
            continue
        require(type(artifact.get('id')) is int and artifact['id'] > 0)
        timestamp(artifact['created_at'])
        selected.append(artifact)
    return sorted(selected, key=lambda a: (timestamp(a['created_at']), a['id']), reverse=True)

def contains_run(state, run):
    scope = run['name'] + ':' + str(run['id']) + ':' + str(run['run_attempt'])
    return state is not None and scope in state['workflows']

def assert_dominates(main, candidate):
    """Pure monotonic chain validation, including stops and all workflow scopes."""
    require(candidate['account_charged_tokens'] >= main['account_charged_tokens'])
    require(candidate['account_limit_usd'] <= main['account_limit_usd'])
    require(not main['stopped'] or candidate['stopped'] == main['stopped'])
    for key, value in main['versions'].items():
        require(candidate['versions'].get(key) == value)
    for scope, budget in main['workflows'].items():
        other = candidate['workflows'].get(scope)
        require(isinstance(other, dict))
        for key in ('calls', 'charged_input_tokens', 'reserved_input_tokens', 'input_tokens', 'output_tokens'):
            require(other.get(key, -1) >= budget[key])
        for key in shared.DEFAULTS:
            require(other.get(key, float('inf')) <= budget[key])
        require(not budget.get('stopped') or other.get('stopped') == budget['stopped'])
        require(other['call_log'][:len(budget['call_log'])] == budget['call_log'])

def retain_highest(main, candidate):
    """Retain the highest charge ledger only if it dominates the other state."""
    if candidate is None:
        return copy.deepcopy(main)
    if main is None:
        return copy.deepcopy(candidate)
    if candidate['account_charged_tokens'] < main['account_charged_tokens']:
        assert_dominates(candidate, main)
        return copy.deepcopy(main)
    assert_dominates(main, candidate)
    return copy.deepcopy(candidate)

def validate_zip(raw):
    """Preflight before extraction: exactly one flat regular expected file."""
    require(len(raw) <= MAX_BYTES)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries) == 1)
        info = entries[0]
        require(info.filename == FILENAME and PurePosixPath(info.filename).parts == (FILENAME,))
        require(not info.is_dir() and not info.flag_bits & 1 and info.file_size <= MAX_BYTES)
        mode = info.external_attr >> 16
        require(stat.S_IFMT(mode) in (0, stat.S_IFREG))
        content = archive.read(info)
        require(len(content) <= MAX_BYTES)
        return content

def download_receipt(artifact, gh, identity):
    # gh follows the private redirect internally; URLs/errors are never logged.
    raw = gh.binary('api', 'repos/' + gh.repo + '/actions/artifacts/' + str(artifact['id']) + '/zip')
    expected = validate_zip(raw)
    with tempfile.TemporaryDirectory(prefix='typesafe-receipt-') as folder:
        gh.binary('run', 'download', str(artifact['workflow_run']['id']), '--repo', gh.repo,
                  '--name', artifact['name'], '--dir', folder)
        entries = list(Path(folder).iterdir())
        require(len(entries) == 1 and entries[0].name == FILENAME)
        state = read_ledger(entries[0], identity)
        require(entries[0].read_bytes() == expected)
        return state

class Gh:
    def __init__(self, repo):
        self.repo = repo
    def binary(self, *args):
        result = subprocess.run(['gh', *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=False, timeout=180)
        require(result.returncode == 0)
        return result.stdout
    def json(self, *args):
        return strict_json(self.binary(*args).decode('utf-8'))
    def pages(self, endpoint, member):
        pages = self.json('api', '--paginate', '--slurp', endpoint)
        require(isinstance(pages, list) and bool(pages))
        result = []
        for page in pages:
            require(isinstance(page, dict) and isinstance(page.get(member), list))
            result.extend(page[member])
        # Detect truncation (filtered run search may be capped at 1000).
        require(all(type(p.get('total_count')) is int and p['total_count'] == len(result) for p in pages))
        return result

def classify_head(head_sha, classifications):
    """Offline classifications are explicit evidence, not default-false hints."""
    require(isinstance(head_sha, str) and FULL_SHA.fullmatch(head_sha) is not None)
    require(isinstance(classifications, dict) and head_sha in classifications)
    result = classifications[head_sha]
    require(result in ('protected', 'legacy'))
    return result

def git_read(*args):
    """Read-only git plumbing; never fetch, mutate refs, or write objects."""
    env = dict(os.environ, GIT_NO_LAZY_FETCH='1', GIT_OPTIONAL_LOCKS='0')
    return subprocess.run(['git', '--no-replace-objects', *args],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          check=False, timeout=30, env=env)

def classify_ancestry(head_sha):
    """Only a verified negative ancestor result proves legacy code."""
    require(isinstance(head_sha, str) and FULL_SHA.fullmatch(head_sha) is not None)
    shallow = git_read('rev-parse', '--is-shallow-repository')
    require(shallow.returncode == 0 and shallow.stdout.strip() == b'false')
    for sha in (RELEASE_SHA, head_sha):
        commit = git_read('cat-file', '-t', sha)
        require(commit.returncode == 0 and commit.stdout.strip() == b'commit')
    # Verify complete reachable history before accepting exit 1 as legacy.
    history = git_read('rev-list', '--missing=error', RELEASE_SHA, head_sha)
    require(history.returncode == 0)
    result = git_read('merge-base', '--is-ancestor', RELEASE_SHA, head_sha)
    require(result.returncode in (0, 1) and not result.stdout and not result.stderr)
    return 'protected' if result.returncode == 0 else 'legacy'

def metadata(gh, current_run_id=None, current_run_attempt=1):
    info = gh.json('api', 'repos/' + gh.repo)
    require(info.get('full_name', '').lower() == gh.repo.lower())
    runs = []
    for workflow in sorted(CONSUMERS):
        endpoint = ('repos/' + gh.repo + '/actions/workflows/' + workflow
                    + '/runs?status=completed&branch=main&per_page=100')
        runs.extend(gh.pages(endpoint, 'workflow_runs'))
    # List-runs exposes only the latest attempt. Fetch each preceding attempt,
    # including previous attempts of the currently in-progress run.
    attempts = {(item['id'], item['run_attempt']): item for item in runs}
    required = set()
    for item in runs:
        require(type(item.get('id')) is int and item['id'] > 0)
        require(type(item.get('run_attempt')) is int and item['run_attempt'] > 0)
        required.update((item['id'], n) for n in range(1, item['run_attempt']))
    if current_run_id is not None:
        required.update((int(current_run_id), n) for n in range(1, current_run_attempt))
    for identifier, attempt in sorted(required):
        if (identifier, attempt) in attempts:
            continue
        item = gh.json('api', 'repos/' + gh.repo + '/actions/runs/' + str(identifier)
                       + '/attempts/' + str(attempt))
        require(item.get('id') == identifier and item.get('run_attempt') == attempt)
        require(item.get('status') == 'completed')
        attempts[(identifier, attempt)] = item
    runs = list(attempts.values())
    artifacts = gh.pages('repos/' + gh.repo + '/actions/artifacts?per_page=100', 'artifacts')
    classifications = {}
    for item in runs:
        sha = item.get('head_sha')
        require(isinstance(sha, str) and FULL_SHA.fullmatch(sha) is not None)
        if sha not in classifications:
            classifications[sha] = classify_ancestry(sha)
    return {'repo': info['full_name'], 'protected_release_sha': RELEASE_SHA,
            'head_classifications': classifications, 'runs': runs, 'artifacts': artifacts}

def restore(ledger, repo, current_run_id, identity, meta, loader, current_run_attempt=1):
    require(meta.get('repo', '').lower() == repo.lower())
    require(meta.get('protected_release_sha') == RELEASE_SHA)
    classifications = meta.get('head_classifications')
    require(isinstance(classifications, dict) and isinstance(meta.get('runs'), list))
    seen = {}
    for item in meta['runs']:
        require(type(item.get('id')) is int and item['id'] > 0)
        require(type(item.get('run_attempt')) is int and item['run_attempt'] > 0)
        classify_head(item.get('head_sha'), classifications)
        key = (item['id'], item['run_attempt'])
        require(key not in seen or seen[key] == item)
        seen[key] = item
    require(all((int(current_run_id), n) in seen for n in range(1, current_run_attempt)))
    for item in meta['runs']:
        require(all((item['id'], n) in seen for n in range(1, item['run_attempt'])))
        if str(item['id']) == str(current_run_id) and item['run_attempt'] < current_run_attempt:
            require(item.get('status') == 'completed' and item.get('head_branch') == 'main'
                    and item.get('head_repository', {}).get('full_name', '').lower() == repo.lower()
                    and workflow_filename(item) in CONSUMERS)
    runs = eligible_runs(meta['runs'], repo, current_run_id, classifications, current_run_attempt)
    artifacts = select_artifacts(meta['artifacts'], runs)
    with shared.lock(Path(ledger)):
        main = read_ledger(ledger, identity, missing_ok=True)
        states = {}
        for artifact in artifacts:
            match = RECEIPT.fullmatch(artifact['name'])
            run = runs[(int(match[1]), int(match[2]))]
            state = loader(artifact)
            validate_state(state, identity)
            require(contains_run(state, run) or contains_run(main, run))
            states[artifact['id']] = state
        for run in runs.values():
            require(contains_run(main, run) or any(
                a['workflow_run']['id'] == run['id'] and int(RECEIPT.fullmatch(a['name'])[2]) == run['run_attempt']
                and a['id'] in states and contains_run(states[a['id']], run)
                for a in artifacts))
        candidate = states.get(artifacts[0]['id']) if artifacts else None
        if candidate is not None:
            # Serialized receipts cannot regress relative to older receipts.
            for state in states.values():
                assert_dominates(state, candidate)
        result = retain_highest(main, candidate)
        if result is not None and result != main:
            shared.write(Path(ledger), result)
        return result

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', default='data/typesafe_shared_state.json')
    parser.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY', ''))
    parser.add_argument('--current-run-id', default=os.environ.get('GITHUB_RUN_ID', ''))
    parser.add_argument('--current-run-attempt', default=os.environ.get('GITHUB_RUN_ATTEMPT', '1'))
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--metadata', help='offline JSON fixture; receipts maps artifact IDs to local files')
    args = parser.parse_args(argv)
    try:
        require(bool(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo)))
        require(bool(re.fullmatch(r'[1-9][0-9]*', str(args.current_run_id))))
        require(bool(re.fullmatch(r'[1-9][0-9]*', str(args.current_run_attempt))))
        current_attempt = int(args.current_run_attempt)
        key = os.environ.get('TYPESAFE_API_KEY', '').strip()
        org = os.environ.get('TYPESAFE_ORG_ID', '').strip()
        require(bool(key) and bool(org))
        identity = (hashlib.sha256(key.encode('utf-8')).hexdigest(), org)
        if args.offline:
            require(bool(args.metadata))
            meta = strict_json(Path(args.metadata).read_text(encoding='utf-8'))
            loader = lambda a: read_ledger(meta['receipts'][str(a['id'])], identity)
        else:
            require(not args.metadata and bool(os.environ.get('GH_TOKEN', '').strip()))
            gh = Gh(args.repo)
            meta = metadata(gh, args.current_run_id, current_attempt)
            loader = lambda a: download_receipt(a, gh, identity)
        restore(Path(args.ledger), args.repo, args.current_run_id, identity, meta, loader, current_attempt)
        print(READY)
        return 0
    except Exception:
        print(LOCAL_ONLY)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
