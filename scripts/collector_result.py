#!/usr/bin/env python3
"""Run local/source stages with truthful, current-execution evidence. Stdlib only."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

METADATA = {'generated_at', 'updated_at', 'collected_at', 'last_synced', 'timestamp',
            'started_at', 'finished_at', 'observed_at', 'at', 'captured_at'}


def now():
    return datetime.now(timezone.utc).isoformat()


def execution_id():
    return os.environ.get('RELEASE_EXECUTION_ID') or ':'.join(
        (os.environ.get('GITHUB_RUN_ID', 'local'), os.environ.get('GITHUB_RUN_ATTEMPT', '1')))


def semantic(value):
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k not in METADATA}
    if isinstance(value, list):
        return [semantic(v) for v in value]
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def artifact(path):
    p = Path(path)
    if not p.is_file() or p.is_symlink():
        return {'path': str(p), 'exists': False, 'sha256': None, 'content_sha256': None}
    raw = p.read_bytes()
    raw_hash = hashlib.sha256(raw).hexdigest()
    result = {'path': str(p), 'exists': True, 'sha256': raw_hash,
              'content_sha256': raw_hash, 'valid_json': False}
    try:
        parsed = json.loads(raw.decode('utf-8-sig'))
        result.update(valid_json=True, content_sha256=digest(semantic(parsed)))
    except (ValueError, UnicodeError):
        pass
    return result


def write(path, value):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def known_rows(path):
    try:
        doc = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if not isinstance(doc, dict): return None
        rows = next((doc[k] for k in ('products', 'all_scored', 'videos') if isinstance(doc.get(k), list)), None)
        if rows is None: return None
        indexed = {}
        for row in rows:
            if not isinstance(row, dict): return None
            key = next((k for k in ('pd_no', 'canonical_product_id', 'video_id') if row.get(k)), None)
            if key is None: return None
            identity = (key, str(row[key]))
            if identity in indexed: return None
            indexed[identity] = digest(semantic(row))
        return indexed
    except (OSError, ValueError, UnicodeError): return None


def run_stage(name, required, paths, command, output, *, skip_reason=None, fetch_evidence=None):
    before = [artifact(p) for p in paths]
    before_rows = [known_rows(p) for p in paths]
    started = now()
    if fetch_evidence:
        Path(fetch_evidence).unlink(missing_ok=True)
    code, error = 0, None
    if skip_reason:
        status = 'skipped'
    else:
        try:
            env = dict(os.environ, RELEASE_EXECUTION_ID=execution_id())
            if fetch_evidence: env['COLLECTOR_FETCH_EVIDENCE'] = str(fetch_evidence)
            code = subprocess.run(command, check=False, env=env).returncode
        except (OSError, ValueError) as exc:
            code, error = 127, type(exc).__name__
        status = 'success' if code == 0 else 'failed'
    process_code = code
    after = [artifact(p) for p in paths]
    invalid = [r['path'] for r in after if not r['exists'] or
               (r['path'].endswith('.json') and not r.get('valid_json'))]
    if not skip_reason and code == 0 and invalid:
        code, status, error = 1, 'failed', 'artifact_missing_or_invalid'
    changed = any(a.get('content_sha256') != b.get('content_sha256')
                  for a, b in zip(before, after))
    unchanged = bool(paths) and not changed and all(r.get('exists') and
        (r.get('valid_json') or not r['path'].endswith('.json')) for r in after)
    result = {'schema_version': 1, 'execution_id': execution_id(), 'name': name,
              'required': bool(required), 'status': status, 'process_exit_code': process_code,
              'wrapper_exit_code': code,
              'last_attempt_at': started, 'finished_at': now(),
              'last_successful_fetch_at': None,
              'fetch_verification': 'not_instrumented' if not skip_reason else 'not_attempted',
              'last_data_changed_at': now() if changed and status == 'success' else None,
              'new_count': 0 if unchanged else None, 'updated_count': 0 if unchanged else None,
              'query_count': None, 'using_cached_data': bool(skip_reason or status == 'failed' or unchanged),
              'content_changed': changed if status == 'success' else False,
              'error_code': error or ('process_exit_' + str(code) if code else None),
              'reason': skip_reason, 'artifacts': after, 'before_artifacts': before}
    if status == 'success':
        after_rows = [known_rows(p) for p in paths]
        if paths and all(r is not None for r in before_rows + after_rows):
            old = {}; current = {}
            for rows in before_rows: old.update(rows)
            for rows in after_rows: current.update(rows)
            result['new_count'] = len(set(current) - set(old))
            result['updated_count'] = sum(k in old and old[k] != value for k, value in current.items())
    if fetch_evidence:
        try:
            evidence = json.loads(Path(fetch_evidence).read_text(encoding='utf-8'))
            if evidence.get('schema_version') != 1 or evidence.get('execution_id') != execution_id():
                raise ValueError('source_evidence_identity_invalid')
            for key in ('query_count', 'succeeded_count', 'failed_count', 'parsed_count'):
                if type(evidence.get(key)) is not int or evidence[key] < 0:
                    raise ValueError('source_evidence_attempt_counts_invalid')
            if evidence['query_count'] != evidence['succeeded_count'] + evidence['failed_count']:
                raise ValueError('source_evidence_attempt_counts_mismatch')
            result.update(query_count=evidence['query_count'], succeeded_count=evidence['succeeded_count'],
                          failed_count=evidence['failed_count'], parsed_count=evidence['parsed_count'])
            if evidence.get('status') == 'skipped' and process_code == 0 and evidence.get('reason'):
                result.update(status='skipped', reason=evidence['reason'], fetch_verification='not_attempted',
                              last_successful_fetch_at=None, new_count=None, updated_count=None,
                              using_cached_data=any(a['exists'] for a in after), error_code=None,
                              wrapper_exit_code=0, content_changed=False, last_data_changed_at=None)
                code = 0
            elif evidence.get('validated') is True and process_code == 0:
                if evidence.get('status') not in {'success', 'degraded'} or evidence.get('artifact_sha256') not in {a.get('sha256') for a in after if a['exists']}:
                    raise ValueError('source_evidence_status_or_artifact_binding_invalid')
                for key in ('query_count', 'succeeded_count', 'failed_count', 'parsed_count', 'new_count', 'updated_count'):
                    if type(evidence.get(key)) is not int or evidence[key] < 0:
                        raise ValueError('source_evidence_count_invalid')
                if evidence['succeeded_count'] < 1 or evidence['query_count'] != evidence['succeeded_count'] + evidence['failed_count']:
                    raise ValueError('source_evidence_feed_counts_invalid')
                captured = datetime.fromisoformat(evidence['last_successful_fetch_at'])
                if captured.tzinfo is None or not datetime.fromisoformat(started) <= captured <= datetime.fromisoformat(now()):
                    raise ValueError('source_evidence_capture_not_current')
                if evidence['new_count'] + evidence['updated_count'] > evidence['parsed_count']:
                    raise ValueError('source_evidence_changes_exceed_rows')
                result.update(fetch_verification='verified_http_parse',
                              last_successful_fetch_at=evidence['last_successful_fetch_at'],
                              query_count=evidence['query_count'], new_count=evidence['new_count'],
                              updated_count=evidence['updated_count'], using_cached_data=False)
                if evidence['failed_count']:
                    result.update(status='degraded', error_code='partial_source_failure', reason=evidence.get('reason'))
            elif process_code == 0:
                raise ValueError('source_evidence_fetch_not_validated')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            code = 1
            result.update(status='failed', error_code='source_evidence_invalid:' + type(exc).__name__, wrapper_exit_code=1)
    # A successful subprocess is not proof of a parsed source fetch. Existing
    # collectors must opt into a future validated source-response adapter.
    write(output, result)
    return code


def attach_runtime(report, runtime_path, identity=None):
    doc = report if isinstance(report, dict) else json.loads(Path(report).read_text(encoding='utf-8'))
    identity = identity or execution_id()
    if (not isinstance(doc, dict) or doc.get('schema_version') != 1 or
        doc.get('execution_id') != identity or doc.get('status') not in {'success', 'degraded', 'failed'}):
        raise ValueError('collector report identity/schema invalid')
    rt = json.loads(Path(runtime_path).read_text(encoding='utf-8'))
    rt['pipeline_health'] = {'execution_id': identity, 'status': doc['status'],
                            'required_failure_count': len(doc['required_failures']),
                            'optional_failure_count': len(doc['optional_failures']),
                            'evidence_error_count': len(doc['evidence_errors']),
                            'using_cached_data': any(r.get('using_cached_data') for r in doc['results'])}
    write(runtime_path, rt)
    return rt['pipeline_health']


def aggregate(results, expected, report, runtime=None, *, identity=None):
    identity = identity or execution_id()
    rows, required_failures, optional_failures, errors = [], [], [], []
    for name, required in expected:
        p = Path(results) / (name + '.json')
        try:
            row = json.loads(p.read_text(encoding='utf-8'))
            if (not isinstance(row, dict) or row.get('schema_version') != 1 or
                row.get('execution_id') != identity or row.get('name') != name or
                row.get('required') is not required or row.get('status') not in {'success', 'degraded', 'failed', 'skipped'} or
                type(row.get('process_exit_code')) is not int):
                raise ValueError('invalid_or_stale_result')
            if row['status'] == 'success' and row['process_exit_code'] != 0:
                raise ValueError('exit_status_mismatch')
            if required and row['status'] != 'success':
                required_failures.append(name)
            elif row['status'] in {'failed', 'degraded'} or row.get('reason'):
                optional_failures.append(name)
            rows.append(row)
        except (OSError, ValueError, TypeError) as exc:
            errors.append({'name': name, 'reason': type(exc).__name__})
            # Missing evidence is never assumed optional success. Missing any
            # expected result blocks publication until the run is accounted for.
    status = 'failed' if required_failures or errors else 'degraded' if optional_failures else 'success'
    doc = {'schema_version': 1, 'execution_id': identity, 'generated_at': now(),
           'status': status, 'publish_allowed': status != 'failed',
           'required_failures': required_failures, 'optional_failures': optional_failures,
           'evidence_errors': errors, 'results': rows}
    write(report, doc)
    if runtime and Path(runtime).is_file():
        attach_runtime(doc, runtime, identity)
    print('RELEASE_OUTCOMES', status, 'required_failures=' + str(len(required_failures)),
          'optional_failures=' + str(len(optional_failures)), 'evidence_errors=' + str(len(errors)))
    return 1 if status == 'failed' else 0


def main():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest='mode', required=True)
    run = subs.add_parser('run')
    run.add_argument('--name', required=True)
    group = run.add_mutually_exclusive_group(required=True)
    group.add_argument('--required', action='store_true'); group.add_argument('--optional', action='store_true')
    run.add_argument('--output', required=True); run.add_argument('--artifact', action='append', default=[])
    run.add_argument('--skip-reason'); run.add_argument('--fetch-evidence')
    run.add_argument('command', nargs=argparse.REMAINDER)
    attach = subs.add_parser('attach-runtime')
    attach.add_argument('--report', required=True); attach.add_argument('--runtime', required=True)
    attach.add_argument('--execution-id')
    agg = subs.add_parser('aggregate')
    agg.add_argument('--results', required=True); agg.add_argument('--report', required=True)
    agg.add_argument('--runtime'); agg.add_argument('--execution-id')
    agg.add_argument('--expected', action='append', required=True)
    args = parser.parse_args()
    if args.mode == 'attach-runtime':
        attach_runtime(args.report, args.runtime, args.execution_id)
        return 0
    if args.mode == 'run':
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        if not command and not args.skip_reason:
            parser.error('command or explicit skip reason required')
        return run_stage(args.name, args.required, args.artifact, command, args.output,
                         skip_reason=args.skip_reason, fetch_evidence=args.fetch_evidence)
    expected = []
    for value in args.expected:
        name, kind = value.rsplit(':', 1)
        if kind not in {'required', 'optional'} or not name or '/' in name or '\\' in name:
            parser.error('expected format name:required|optional')
        expected.append((name, kind == 'required'))
    return aggregate(args.results, expected, args.report, args.runtime, identity=args.execution_id)


if __name__ == '__main__':
    sys.exit(main())
