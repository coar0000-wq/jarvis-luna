"""Bounded authenticated pipeline observer. No providers or source mutations."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import daiso_pipeline_inputs as p
from scripts import github_artifact_io as transport


def observe(root, *, report=None, now=None, fetch_json=None, fetch_artifact_bytes=None):
    root, observed = Path(root).absolute(), p.clock(now)
    report = p.doc(p.read(root, p.REPORT)) if report is None else report
    try:
        injected = fetch_json is not None and fetch_artifact_bytes is not None
        if not injected and not (os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')):
            raise ValueError('authenticated_github_token_missing')
        if report.get('repository') != transport.REPOSITORY or report.get('observation_source') != 'github_rest':
            raise ValueError('authenticated_fixed_repository_report_required')
        age = (observed - p.timestamp(report.get('observed_at'))).total_seconds()
        if not 0 <= age <= 1800:
            raise ValueError('workflow_report_expired_or_future')
        workflow = report.get('workflows', {}).get(p.WORKFLOW, {})
        latest = workflow.get('latest_attempt') or {}
        rid, attempt = latest.get('id'), latest.get('run_attempt')
        if (workflow.get('metadata_verified') is not True or type(rid) is not int
                or type(attempt) is not int or min(rid, attempt) <= 0 or latest.get('status') != 'completed'):
            raise ValueError('completed_run_attempt_binding_missing')
        get = fetch_json or transport.fetch_github_json
        download = fetch_artifact_bytes or transport.fetch_artifact_bytes
        base = transport.API_ORIGIN + '/repos/' + transport.REPOSITORY + '/actions/'
        current = get(base + 'workflows/' + p.WORKFLOW + '/runs?branch=main&per_page=1')
        rows = current.get('workflow_runs')
        if not isinstance(rows, list) or len(rows) != 1 or (rows[0].get('id'), rows[0].get('run_attempt')) != (rid, attempt):
            raise ValueError('report_not_current_workflow_attempt')
        p.execution_identity(rows[0])
        run_base = base + 'runs/' + str(rid)
        run = get(run_base + '/attempts/' + str(attempt))
        jobs = get(run_base + '/attempts/' + str(attempt) + '/jobs?per_page=100')
        artifacts = get(run_base + '/artifacts?per_page=100')
        rows = artifacts.get('artifacts')
        if not isinstance(rows, list) or len(rows) > 100 or artifacts.get('total_count') != len(rows):
            raise ValueError('artifact_coverage_incomplete')
        wanted = 'daiso-attempt-' + str(rid) + '-' + str(attempt)
        selected = [a for a in rows if isinstance(a, dict) and a.get('name') == wanted]
        if len(selected) != 1:
            raise ValueError('exact_artifact_missing_or_ambiguous')
        artifact = selected[0]
        if artifact.get('expired') is not False:
            raise ValueError('artifact_expired')
        if type(artifact.get('id')) is not int or artifact['id'] <= 0:
            raise ValueError('artifact_identity_invalid')
        archive = download(base + 'artifacts/' + str(artifact['id']) + '/zip')
        return p.publish_validated_health(root, report, run, jobs, artifact, archive, now=observed)
    except (ValueError, OSError, KeyError, TypeError, OverflowError) as error:
        health = p.load_pipeline_inputs(root, now=observed, workflow_report=report)
        health['input_errors'].append(str(error))
        if health['status'] != 'failed':
            health['status'] = 'unverified'
            health['scopes']['overall_workflow'] = {'status': 'unverified', 'verified': False,
                                                    'reason': 'current_authenticated_observation_failed'}
        return health


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        health = observe(args.root)
    except (ValueError, OSError, TypeError) as error:
        health = {'status': 'unverified', 'input_errors': [str(error)], 'public_authority': False}
    print(json.dumps(health, ensure_ascii=False, allow_nan=False))
    return 0 if health['status'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
