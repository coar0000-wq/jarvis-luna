#!/usr/bin/env python3
"""Isolated, fail-closed normal-push transaction. Never resets the caller tree.

Capture one immutable delta against HEAD. Every attempt uses a fresh latest-main
worktree, merges source identities, regenerates local-only derivatives, validates
candidate and final bytes, and uses an ordinary non-force push. Conflicts never
choose an entire stale file. Production commands cannot be supplied by callers.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import sys
import tempfile

MISSING = object()
PERSISTENT_SOURCE_FILES = frozenset(('data/daiso_real/shortlist_observations.json',
    'data/daiso_real/.shortlist_observation_claim.json',
    'data/agents/source_procedures/source-procedure-state.json',
    'data/agents/source_procedures/checkpoint.json'))
IMMUTABLE_HISTORY_PREFIXES = ('data/agents/workflow_status_history/',
    'data/agents/gemini_escalation_history/', 'data/knowledge/moe_evaluation_history/',
    'data/knowledge/gosi_observation_history/', 'data/agents/daiso_pipeline_history/',
    'data/agents/source_procedures/observer_history/')


class PublishError(RuntimeError):
    pass


def git(root, *args, check=True):
    p = subprocess.run(['git', '-C', str(root), *args], capture_output=True)
    if check and p.returncode:
        # stderr may contain remote credentials; never echo command outputs.
        raise PublishError(f'git {args[0]} failed (exit {p.returncode})')
    return p


def at_ref(root, ref, name):
    p = git(root, 'show', f'{ref}:{name}', check=False)
    return p.stdout if p.returncode == 0 else None


def sha(value):
    return hashlib.sha256(value).hexdigest() if value is not None else None


def path_allowed(name, paths):
    return any(name == p.rstrip('/') or name.startswith(p.rstrip('/') + '/') for p in paths)


def normalize_paths(value):
    paths = shlex.split(value)
    if not paths:
        raise PublishError('publish paths missing')
    for p in paths:
        pure = PurePosixPath(p)
        if (pure.is_absolute() or '\\' in p or '..' in pure.parts
                or pure.parts[0] not in {'data', 'obsidian'} or '*' in p):
            raise PublishError(f'unsafe publish path: {p}')
    return paths


def parse_json(data):
    try:
        return json.loads(data)
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise PublishError('source JSON is invalid') from exc


def identity(rows, fields):
    for field in fields:
        if rows and all(isinstance(r, dict) and r.get(field) not in (None, '') for r in rows):
            return field
    return None


def deletion_authorized(name, base, removed, manifest, *, replacement=None):
    for record in (manifest or {}).get('deletions', []):
        if (isinstance(record, dict) and record.get('path') == name
                and record.get('base_sha256') == sha(base)
                and isinstance(record.get('reason'), str) and len(record['reason'].strip()) >= 8
                and isinstance(record.get('policy_ref'), str) and record['policy_ref'].strip()
                and (('replacement_sha256' not in record and record['policy_ref'] not in {
                    'scripts/moe_evaluation_history.py', 'scripts/diagnostic_evaluation_history.py',
                    'scripts/workflow_status_history.py', 'scripts/gosi_observation_history.py',
                    'scripts/shortlist_observation_history.py'})
                     or (replacement is not None and record.get('replacement_sha256') == sha(replacement)))
                and (record.get('delete_file') is True if removed is None else
                     isinstance(record.get('ids'), list) and set(removed) <= set(map(str, record['ids'])))):
            return True
    return False


def volatile_container(where, policy, *, snapshots_only=False):
    keys = ['volatile_snapshot_containers']
    if not snapshots_only:
        keys.append('volatile_delete_containers')
    scopes = [scope for key in keys for scope in policy.get(key, [])]
    return any(where == scope or where.startswith(scope + '/') for scope in scopes)


def producer_changed(name, policy):
    if any(name.startswith(prefix) for prefix in policy.get('producer_path_prefixes', ['scripts/', 'config/', '.github/', 'requirements/'])):
        return True
    parts = PurePosixPath(name).parts
    if len(parts) != 1:
        return False
    return (any(name.endswith(suffix) for suffix in policy.get('producer_root_suffixes', ['.py']))
            or any(name.startswith(prefix) for prefix in policy.get('producer_root_prefixes', ['requirements', 'constraints']))
            or name in policy.get('producer_root_names', ['pyproject.toml', 'uv.lock', 'poetry.lock', 'Pipfile', 'Pipfile.lock']))


def merge_json(base, local, remote, policy, *, where='', authorize_delete=None):
    """Preserve independent additions; same-identity competing edits fail closed."""
    if local == remote:
        return deepcopy(local)
    if local == base:
        return deepcopy(remote)
    if remote == base:
        return deepcopy(local)
    if volatile_container(where, policy, snapshots_only=True):
        # One execution's report is atomic. Never manufacture a hybrid report
        # from two independently completed runs, even when fields do not overlap.
        raise PublishError(f'competing execution snapshots: {where}')
    if isinstance(local, dict) and isinstance(remote, dict) and isinstance(base, dict):
        result = {}
        for key in sorted(set(base) | set(local) | set(remote)):
            b, l, r = base.get(key, MISSING), local.get(key, MISSING), remote.get(key, MISSING)
            child = f'{where}/{key}'
            if l is MISSING:
                if b is MISSING:
                    result[key] = deepcopy(r)
                elif r is MISSING:
                    continue
                elif (volatile_container(child, policy) or (authorize_delete and authorize_delete([key]))) and r == b:
                    continue
                else:
                    raise PublishError(f'unexplained deletion/conflict: {child}')
                continue
            if r is MISSING:
                if b is MISSING:
                    result[key] = deepcopy(l)
                elif l == b:
                    continue
                else:
                    raise PublishError(f'remote deletion conflicts with local edit: {child}')
                continue
            if key in policy['metadata_timestamps'] and l != b and r != b and l != r:
                try:
                    a = datetime.fromisoformat(str(l).replace('Z', '+00:00'))
                    z = datetime.fromisoformat(str(r).replace('Z', '+00:00'))
                    if a.tzinfo is None or z.tzinfo is None:
                        raise ValueError('naive timestamp')
                    result[key] = l if a >= z else r
                except (ValueError, TypeError):
                    raise PublishError(f'invalid concurrent metadata timestamp: {child}')
            elif key in {'count', 'total'} and l != b and r != b and l != r:
                arrays = [v for v in local.values() if isinstance(v, list)]
                objects = [v for k, v in local.items() if k in {'items', 'observations'} and isinstance(v, dict)]
                if len(arrays) + len(objects) != 1:
                    raise PublishError(f'unknown concurrent count semantics: {child}')
                result[key] = 0  # Recomputed below from the merged container.
            elif where.endswith(('/items', '/observations')) and l != b and r != b and l != r:
                raise PublishError(f'competing same-identity observation: {child}')
            else:
                result[key] = merge_json(b, l, r, policy, where=child, authorize_delete=authorize_delete)
        containers = [v for v in result.values() if isinstance(v, list)]
        containers += [v for k, v in result.items() if k in {'items', 'observations'} and isinstance(v, dict)]
        if len(containers) == 1:
            for key in ('count', 'total'):
                if key in result and isinstance(result[key], int):
                    result[key] = len(containers[0])
        return result
    if isinstance(local, list) and isinstance(remote, list) and isinstance(base, list):
        field = identity(base + local + remote, policy['identity_fields'])
        if field:
            if any(len({str(r[field]) for r in rows}) != len(rows) for rows in (base, local, remote)):
                raise PublishError(f'duplicate source identities: {where}')
            indexes = [{str(r[field]): r for r in rows} for rows in (base, local, remote)]
            b, l, r = indexes
            out = []
            for key in sorted(set(b) | set(l) | set(r)):
                bv, lv, rv = b.get(key, MISSING), l.get(key, MISSING), r.get(key, MISSING)
                if lv is MISSING:
                    if bv is MISSING:
                        out.append(deepcopy(rv))
                    elif rv is MISSING:
                        pass
                    elif authorize_delete and authorize_delete([key]) and rv == bv:
                        pass
                    else:
                        raise PublishError(f'identity deletion conflict: {where}/{key}')
                elif rv is MISSING:
                    if bv is MISSING:
                        out.append(deepcopy(lv))
                    elif lv != bv:
                        raise PublishError(f'remote identity deletion conflicts: {where}/{key}')
                elif lv != bv and rv != bv and lv != rv:
                    raise PublishError(f'competing same-identity edits: {where}/{key}')
                else:
                    out.append(deepcopy(rv if lv == bv else lv))
            return out
        if all(isinstance(v, (str, int, float, bool)) or v is None for v in base + local + remote):
            if all(v in local and v in remote for v in base):
                return list(dict.fromkeys(remote + local))
        raise PublishError(f'unknown concurrent array semantics: {where}')
    raise PublishError(f'competing scalar or unknown source conflict: {where}')


def removed_identities(base, local, policy, *, where=''):
    """Find source removals, exempting only policy-listed transient containers."""
    if volatile_container(where, policy):
        return []
    removed = []
    if isinstance(base, dict) and isinstance(local, dict):
        for key, value in base.items():
            child = f'{where}/{key}'
            if key not in local:
                if not volatile_container(child, policy):
                    removed.append(str(key))
            else:
                removed.extend(removed_identities(value, local[key], policy, where=child))
    elif isinstance(base, list) and isinstance(local, list):
        field = identity(base + local, policy['identity_fields'])
        if field:
            removed.extend(set(str(r[field]) for r in base) - set(str(r[field]) for r in local))
        elif all(isinstance(v, (str, int, float, bool)) or v is None for v in base + local):
            removed.extend(str(v) for v in base if v not in local)
    return removed


BYTE_BOUND_STAGE_FILES = frozenset(('data/daiso_real/collection_status.json',
    'data/daiso_real/candidate_pool.json','data/agents/daiso_pipeline_receipts.json'))


def overlay(name, base, local, remote, policy, manifest):
    # Exact immutable history bytes must never be reformatted, merged or pruned.
    # Their filenames bind SHA256 of the original snapshots, not parsed JSON.
    if name.startswith(IMMUTABLE_HISTORY_PREFIXES):
        stem = PurePosixPath(name).stem
        if local is None or not re.fullmatch(r'[0-9a-f]{64}', stem) or sha(local) != stem:
            raise PublishError(f'immutable history removal/hash mismatch: {name}')
        if remote not in (None, local) or base not in (None, local):
            raise PublishError(f'immutable history conflict: {name}')
        parse_json(local)
        return local
    if name in PERSISTENT_SOURCE_FILES and remote not in (None, base, local):
        raise PublishError(f'competing safety checkpoint requires reconciliation: {name}')
    authorize = lambda ids: deletion_authorized(name, base, ids, manifest, replacement=local)
    if local is None:
        if not deletion_authorized(name, base, None, manifest):
            raise PublishError(f'file deletion requires base-hash reason manifest: {name}')
        if remote not in (None, base):
            raise PublishError(f'concurrent file deletion conflict: {name}')
        return None
    if name.endswith('.json'):
        l = parse_json(local)
        b = parse_json(base) if base is not None else {}
        removed = removed_identities(b, l, policy, where=name)
        if removed and not authorize(removed):
            raise PublishError(f'identity/field removal requires reason manifest: {name}')
        if remote not in (None, base, local):
            r = parse_json(remote)
            l = merge_json(b, l, r, policy, where=name, authorize_delete=authorize)
        elif remote is None and base is not None:
            raise PublishError(f'remote deleted locally edited source: {name}')
        # Counter/checkpoint pairs retain exact caller bytes. Never manufacture
        # a hybrid ledger or destroy its byte-bound failed-run artifact evidence.
        exact_stage = name in BYTE_BOUND_STAGE_FILES and remote in (None, base, local)
        result = local if name in PERSISTENT_SOURCE_FILES or exact_stage else json.dumps(l, ensure_ascii=False, indent=2).encode('utf-8') + b'\n'
        if removed and not deletion_authorized(name, base, removed, manifest, replacement=result):
            raise PublishError(f'replacement snapshot is not authorized after merge: {name}')
        return result
    if remote in (None, base, local):
        if remote is None and base is not None:
            raise PublishError(f'remote deleted locally edited file: {name}')
        return local
    # Existing note rewrites and arbitrary binary files have no safe merge rule.
    if name.startswith('obsidian/') and name.endswith('.md') and base is not None:
        if local.startswith(base) and remote.startswith(base):
            chunks = [remote, local[len(base):]]
            return chunks[0] if not chunks[1] or chunks[1] in chunks[0] else b''.join(chunks)
    raise PublishError(f'no automatic whole-file selection for conflict: {name}')


class Transaction:
    def __init__(self, root, paths, message, regenerate_dashboard=True, audit=True,
                 max_attempts=3, dry_run=False, collector_report=None, execution_id=None):
        self.root = Path(root).resolve()
        self.paths = normalize_paths(paths)
        self.message = message
        self.regenerate_dashboard = regenerate_dashboard
        self.audit = audit
        if not 1 <= max_attempts <= 3:
            raise PublishError('attempt count must be between 1 and 3')
        self.max_attempts, self.dry_run = max_attempts, dry_run
        self.base = git(self.root, 'rev-parse', 'HEAD').stdout.decode().strip()
        self.policy = json.loads((self.root/'config/publish_policy.json').read_text(encoding='utf-8'))
        self.collector_report = Path(collector_report).read_bytes() if collector_report else None
        self.execution_id = execution_id
        self.delta = self.capture()
        p = self.root/self.policy['deletion_manifest']
        self.manifest = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
        self.attempts = []

    def capture(self):
        # Include index, unstaged edits and untracked files, never a blanket add.
        names = set(git(self.root, 'diff', '--name-only', '-z', 'HEAD').stdout.decode().split('\0'))
        names.update(git(self.root, 'ls-files', '--others', '--exclude-standard', '-z').stdout.decode().split('\0'))
        changes = {}
        for name in sorted(names - {''}):
            if not path_allowed(name, self.paths):
                continue
            p = self.root/name
            if p.is_symlink():
                raise PublishError(f'publication symlink not permitted: {name}')
            changes[name] = (at_ref(self.root, self.base, name), p.read_bytes() if p.exists() else None)
        for required in self.paths:
            p = self.root/required
            deleted = any(n == required or n.startswith(required.rstrip('/')+'/') for n, (_, v) in changes.items() if v is None)
            if not p.exists() and not deleted:
                raise PublishError(f'required publication path missing: {required}')
            if p.is_symlink():
                raise PublishError(f'publication path is a symlink: {required}')
        return changes

    def is_derived(self, name):
        return path_allowed(name, self.policy['derived_paths'])

    def candidate_only(self):
        sources = [n for n in self.delta if not self.is_derived(n)]
        status_delta = self.delta.get('data/daiso_real/collection_status.json')
        if status_delta:
            base, local = status_delta
            if base is None or local is None or parse_json(base).get('fx') != parse_json(local).get('fx'):
                return False  # Actual FX input changes require commerce regeneration.
        # Source-price/claim and remediation evidence are observation-only. Their
        # presence must not regenerate or mutate canonical commerce quantities.
        return bool(sources) and all(n == 'data/publish_deletions.json' or n.startswith(('data/daiso_real/candidate_', 'data/daiso_real/collection_status.json', 'data/daiso_real/crawl_state.json', 'data/daiso_real/shortlist_observations.json', 'data/daiso_real/.shortlist_observation_claim.json', 'data/agents/', 'data/knowledge/cumulative_history.json', 'data/health_check_history.jsonl', 'data/typesafe_advisory.json', 'data/typesafe_team_advisory.json', 'data/typesafe_shared_state.json', 'data/typesafe_call_log/')) for n in sources)

    def command(self, work, args):
        env = dict(os.environ, TYPESAFE_ENABLED='0', GEMINI_FALLBACK_ENABLED='0',
                   GEMINI_ENABLED='0', TYPESAFE_ALLOW_PAID='0', PYTHONIOENCODING='utf-8')
        for key in ('TYPESAFE_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY'):
            env.pop(key, None)
        p = subprocess.run([sys.executable, '-B', *args], cwd=work, env=env)
        if p.returncode:
            raise PublishError(f'offline final generation/check failed: {args[0]} ({p.returncode})')

    def reapply_collector(self, work, report_path):
        if self.collector_report is None:
            return []
        report_path.write_bytes(self.collector_report)
        # Sibling collector_result owns this CLI and validates execution evidence.
        args = ['scripts/collector_result.py', 'attach-runtime', '--report', str(report_path),
                '--runtime', 'data/dashboard_runtime.json']
        if self.execution_id:
            args += ['--execution-id', self.execution_id]
        self.command(work, args)
        return ['--collector-report', str(report_path)] + (['--execution-id', self.execution_id] if self.execution_id else [])

    def regenerate_and_validate(self, work, baseline, remote_changed, report_dir):
        candidate = self.candidate_only()
        protected = {}
        if candidate:
            for name in git(work, 'ls-files', '-z').stdout.decode().split('\0'):
                if name and path_allowed(name, self.policy['candidate_protected']):
                    protected[name] = (work/name).read_bytes()
        relevant = set(self.delta)
        if remote_changed:
            relevant.update(git(self.root, 'diff', '--name-only', self.base, remote_changed).stdout.decode().splitlines())
        commerce_outputs = ['data/daiso_real/shopify_demand_score.json', 'data/product_master.json',
                            'data/pricing_model.json', 'data/listing_gate.json', 'data/legal_products.json',
                            'data/legal_full.json', 'data/market_team.json', 'data/shopify_exports/',
                            'data/shopify_action_queue.json', 'data/shopify_shortlist.json']
        commerce = not candidate and any(path_allowed(n, self.policy['commerce_inputs'] + commerce_outputs) for n in relevant)
        if commerce:
            for args in self.policy['commerce_commands']:
                self.command(work, args)
        if candidate and (work/'data/daiso_real/candidate_pool.json').exists():
            self.command(work, ['scripts/build_daiso_candidate_comparison.py'])
        # false means no caller-requested regeneration; it cannot waive a rebase
        # or a source delta's final regeneration.
        if relevant or self.regenerate_dashboard:
            for args in self.policy['runtime_commands']:
                self.command(work, args)
        extra = self.reapply_collector(work, report_dir/'collector-report.json')
        for phase in ('candidate', 'final'):
            self.command(work, ['scripts/check_release_quality.py', '--phase', phase,
                               '--root', str(work), '--baseline', str(baseline),
                               '--report', str(report_dir/f'{phase}.json'), *extra])
        if self.audit:
            self.command(work, ['scripts/audit_team_reports.py'])
        for name, before in protected.items():
            if not (work/name).exists() or (work/name).read_bytes() != before:
                raise PublishError(f'candidate-only publication changed canonical bytes: {name}')

    def stage(self, work):
        names = set(git(work, 'diff', '--name-only', '-z', 'HEAD').stdout.decode().split('\0'))
        names.update(git(work, 'ls-files', '--others', '--exclude-standard', '-z').stdout.decode().split('\0'))
        allowed = self.paths + self.policy['derived_paths'] + self.policy['generated_extra']
        for name in sorted(names - {''}):
            if not path_allowed(name, allowed):
                raise PublishError(f'generator wrote undeclared artifact: {name}')
            git(work, 'add', '-A', '--', name)  # Exact named path, including deletion.
        return git(work, 'diff', '--cached', '--quiet', check=False).returncode != 0

    def push(self, work):
        return git(work, 'push', 'origin', 'HEAD:main', check=False).returncode == 0

    def run(self):
        if not self.delta:
            return {'status': 'no_change', 'base_sha': self.base, 'attempts': []}
        temp_root = Path(os.environ.get('RUNNER_TEMP') or os.environ.get('TEMP') or self.root.parent)
        with tempfile.TemporaryDirectory(prefix='publish-transaction-', dir=temp_root) as folder:
            temp = Path(folder)
            baseline = temp/'baseline'; baseline.mkdir()
            for name in self.policy['baseline_files']:
                value = at_ref(self.root, self.base, name)
                if value is not None:
                    p = baseline/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(value)
            for number in range(1, self.max_attempts+1):
                git(self.root, 'fetch', 'origin', 'main')
                latest = git(self.root, 'rev-parse', 'FETCH_HEAD').stdout.decode().strip()
                # Source files generated by a different code revision may be
                # incompatible. Never combine altered policy/producer code blindly.
                code_changes = git(self.root, 'diff', '--name-only', self.base, latest).stdout.decode().splitlines()
                if any(producer_changed(n, self.policy) for n in code_changes):
                    raise PublishError('main producer/policy code changed during collection; rerun on latest code')
                work = temp/f'work-{number}'
                git(self.root, 'worktree', 'add', '--detach', str(work), latest)
                try:
                    safety_before = None
                    if set(self.delta) & PERSISTENT_SOURCE_FILES:
                        from source_safety_checkpoint import _validate, _nonregression, ALLOWLIST
                        safety_before = {n:(work/n).read_bytes() for n in ALLOWLIST if (work/n).exists()}
                        _validate(safety_before)
                    for name, (base, local) in self.delta.items():
                        if self.is_derived(name):
                            continue  # Regenerate, never reuse stale derivatives.
                        p = work/name
                        remote = p.read_bytes() if p.exists() else None
                        value = overlay(name, base, local, remote, self.policy, self.manifest)
                        if value is None:
                            p.unlink(missing_ok=True)
                        else:
                            p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(value)
                    if set(self.delta) & PERSISTENT_SOURCE_FILES:
                        files = {n:(work/n).read_bytes() for n in ALLOWLIST if (work/n).exists()}
                        try:
                            _validate(files)
                            _nonregression(safety_before, files)
                        except (ValueError, OSError) as exc:
                            raise PublishError('source safety pair validation failed') from exc
                    reports = temp/f'reports-{number}'; reports.mkdir()
                    self.regenerate_and_validate(work, baseline, latest if latest != self.base else None, reports)
                    if safety_before is not None:
                        final_safety = {n:(work/n).read_bytes() for n in ALLOWLIST if (work/n).exists()}
                        _validate(final_safety)
                        _nonregression(safety_before, final_safety)
                        if final_safety != files:
                            raise PublishError('offline generators mutated source safety evidence')
                    self.attempts.append({'attempt': number, 'remote_sha': latest, 'validated': True})
                    if not self.stage(work):
                        return {'status': 'no_change', 'base_sha': self.base, 'attempts': self.attempts}
                    if self.dry_run:
                        return {'status': 'dry_run_validated', 'base_sha': self.base, 'attempts': self.attempts}
                    git(work, 'config', 'user.name', 'JARVIS')
                    git(work, 'config', 'user.email', 'jarvis@luna.bot')
                    git(work, 'commit', '-m', self.message)
                    commit = git(work, 'rev-parse', 'HEAD').stdout.decode().strip()
                    if self.push(work):
                        return {'status': 'published', 'commit_sha': commit, 'base_sha': self.base, 'attempts': self.attempts}
                    self.attempts[-1]['push_rejected'] = True
                finally:
                    git(self.root, 'worktree', 'remove', '--force', str(work))
        raise PublishError(f'normal push rejected after {self.max_attempts} independently validated attempts')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paths', required=True)
    parser.add_argument('--message', required=True)
    parser.add_argument('--regenerate-dashboard', choices=('true', 'false'), default='true')
    parser.add_argument('--audit', choices=('true', 'false'), default='true')
    parser.add_argument('--max-attempts', type=int, default=3)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--collector-report')
    parser.add_argument('--execution-id')
    args = parser.parse_args()
    try:
        result = Transaction(Path.cwd(), args.paths, args.message,
                             args.regenerate_dashboard == 'true', args.audit == 'true',
                             args.max_attempts, args.dry_run, args.collector_report, args.execution_id).run()
        print('PUBLISH_TRANSACTION_OK', json.dumps(result, ensure_ascii=False))
        out = os.environ.get('GITHUB_OUTPUT')
        if out:
            with open(out, 'a', encoding='utf-8') as handle:
                handle.write(f"status={result['status']}\ncommit_sha={result.get('commit_sha', '')}\n")
        return 0
    except (PublishError, ValueError, OSError) as exc:
        print(f'::error::Publication blocked: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
