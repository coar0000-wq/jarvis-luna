"""Mandatory CLI bridge for supported local evidence, not business authority.

Pure functions retain fixture compatibility. Production CLI entry points always
bind an invocation. Excluded private files stay on their original path and are
explicitly not counted as vault-consumed input. Integrity failures never fall back.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import obsidian_brain as brain

TEAMS = ('runtime', 'agents', 'operations')


def read_json(path, root, default=None):
    root, path = Path(root), Path(path)
    run = brain.current_execution(root)
    if run is not None and not brain.note_exclusion(path, root):
        return brain.load_json(path, root, default)
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, ValueError):
        return default


def record(path, root):
    root, path = Path(root), Path(path)
    run = brain.current_execution(root)
    if run is None or brain.note_exclusion(path, root):
        return None
    return brain.record_output(path, root, run.task, run.team, run.operation)


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def _finish(root, run):
    proof = run.proof()
    if not proof['input_read_from_vault'] or not proof['output_stored']:
        raise brain.BrainError('supported_input_and_output_proof_required')
    summary = {
        'schema_version': 1, 'team': run.team,
        'completed_at': datetime.now(timezone.utc).isoformat(),
        'input_read_from_vault': True, 'output_stored': True,
        'input_count': len(proof['consumed_source_ids']),
        'output_count': len(proof['output_artifact_ids']),
        'excluded_count': len(proof['excluded']),
        'source_default_count': len(proof['default_reasons']),
        'scope': 'supported operational JSON only; private inputs excluded',
        'analysis_only': True, 'business_approval': False, 'external_execution': False,
    }
    target = root / 'data/agents' / ('brain_execution_' + run.team + '.json')
    _write(target, summary)
    record(target, root)
    runtime_path = root / 'data/dashboard_runtime.json'
    runtime = read_json(runtime_path, root, None)
    if isinstance(runtime, dict):
        executions = {}
        for team in TEAMS:
            document = read_json(root / 'data/agents' / ('brain_execution_' + team + '.json'), root, {})
            if isinstance(document, dict) and document.get('team') == team:
                executions[team] = document
        runtime['brain_flow'] = {
            'local_only': True, 'scope': summary['scope'],
            'business_approval': False, 'executions': executions,
        }
        _write(runtime_path, runtime)
        record(runtime_path, root)
    return summary


@contextmanager
def command(root, *, team, task, operation):
    root = Path(root)
    brain.audit(root)
    with brain.execution(root, task=task, team=team, operation=operation) as run:
        yield run
        _finish(root, run)


def execute(root, *, team, task, operation, callback):
    with command(root, team=team, task=task, operation=operation):
        return callback()
