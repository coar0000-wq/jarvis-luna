"""One active GitHub namespace; narrowly pinned, byte-preserving transfer history.

Changing this configuration is a reviewed cutover, never an environment-based
owner switch. Historical pins authorize only an exact artifact tuple, not an
owner, a branch, a successful flag, or new network requests to the old owner.
The consumers still verify authenticated metadata, actual ZIP digests, workflow
steps, ancestry and nonregression. This module cannot replace those checks.
"""
from __future__ import annotations
import json
from pathlib import Path
import re
import subprocess

REPOSITORY_ID = 1334276889
SOURCE = 'coar0000-wq/jarvis-luna'
TARGET = 'coarfamily-cyber/jarvis-luna'
OWNER_IDS = {SOURCE: 301755647, TARGET: 280980688}
TRUSTED_PRODUCER_CODE = (
    'scripts/repository_identity.py', 'scripts/daiso_pipeline_inputs.py',
    '.github/workflows/daiso-real-collection.yml')
_PIN_FIELDS = {'repository', 'repository_id', 'run_id', 'run_attempt', 'head_sha',
               'artifact_id', 'artifact_name', 'artifact_digest'}


def _positive(value):
    return type(value) is int and value > 0


class IdentityPolicy:
    def __init__(self, config):
        if (not isinstance(config, dict) or set(config) != {
                'schema_version', 'repository_id', 'current_repository',
                'current_owner_id', 'cutover_head_sha', 'historical_artifacts'}
                or type(config.get('schema_version')) is not int or config['schema_version'] != 1
                or type(config.get('repository_id')) is not int or config['repository_id'] != REPOSITORY_ID):
            raise ValueError('repository_identity_policy_invalid')
        self.cutover_head_sha = config['cutover_head_sha']
        self.current = config['current_repository']
        if self.current not in OWNER_IDS or config['current_owner_id'] != OWNER_IDS[self.current]:
            raise ValueError('repository_identity_owner_invalid')
        pins = config['historical_artifacts']
        if not isinstance(pins, list) or len(pins) > 256:
            raise ValueError('repository_history_bound_invalid')
        if self.current == SOURCE:
            if config['cutover_head_sha'] is not None or pins:
                raise ValueError('source_policy_cannot_enable_historical_alias')
        elif not isinstance(config['cutover_head_sha'], str) or not re.fullmatch('[0-9a-f]{40}', config['cutover_head_sha']) or not pins:
            raise ValueError('reviewed_cutover_and_exact_history_required')
        normalized = []
        for pin in pins:
            if (not isinstance(pin, dict) or set(pin) != _PIN_FIELDS
                    or pin['repository'] != SOURCE or type(pin['repository_id']) is not int
                    or pin['repository_id'] != REPOSITORY_ID
                    or not all(_positive(pin[k]) for k in ('run_id', 'run_attempt', 'artifact_id'))
                    or not isinstance(pin['head_sha'], str) or not re.fullmatch('[0-9a-f]{40}', pin['head_sha'])
                    or not isinstance(pin['artifact_digest'], str) or not re.fullmatch('sha256:[0-9a-f]{64}', pin['artifact_digest'])
                    or pin['artifact_name'] not in {
                        f"source-safety-{pin['run_id']}-{pin['run_attempt']}",
                        f"operations-safety-{pin['run_id']}-{pin['run_attempt']}",
                        f"daiso-attempt-{pin['run_id']}-{pin['run_attempt']}"}):
                raise ValueError('historical_artifact_pin_invalid')
            if any(p['artifact_id'] == pin['artifact_id'] or (
                    self._key(p) == self._key(pin) and p['artifact_name'] == pin['artifact_name']) for p in normalized):
                raise ValueError('historical_artifact_pin_ambiguous')
            normalized.append(dict(pin))
        self.pins = tuple(normalized)

    @staticmethod
    def _key(pin):
        return pin['run_id'], pin['run_attempt'], pin['head_sha']

    def _pins(self, run):
        key = run.get('id'), run.get('run_attempt'), run.get('head_sha')
        return [p for p in self.pins if self._key(p) == key]

    def runner(self, values, *, fixture=False):
        # Explicit old offline fixtures predate the immutable-ID runner fields.
        # Production entry points never set fixture=True.
        if values.get('GITHUB_ACTIONS') != 'true':
            raise ValueError('authenticated_github_runner_required')
        for field, expected in (('GITHUB_REPOSITORY', self.current),
                                ('GITHUB_REPOSITORY_ID', str(REPOSITORY_ID)),
                                ('GITHUB_REPOSITORY_OWNER_ID', str(OWNER_IDS[self.current]))):
            if fixture and self.current == SOURCE and field not in values:
                continue
            if values.get(field) != expected:
                raise ValueError('fixed_repository_runner_identity_required')

    def producer_identity(self, values, *, workflow, fixture=False):
        """Capture runner identity; only its authenticated archive chain is evidence."""
        self.runner(values, fixture=fixture)
        required = ('GITHUB_REPOSITORY_ID', 'GITHUB_REPOSITORY_OWNER_ID', 'GITHUB_SHA',
                    'GITHUB_WORKFLOW_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT',
                    'GITHUB_JOB', 'GITHUB_WORKFLOW_REF')
        if fixture and self.current == SOURCE and any(k not in values for k in required):
            return None  # Explicit legacy test input only, never a production runner.
        head = values.get('GITHUB_SHA', '')
        run_id, attempt = values.get('GITHUB_RUN_ID', ''), values.get('GITHUB_RUN_ATTEMPT', '')
        job = values.get('GITHUB_JOB', '')
        reference = self.current + '/.github/workflows/' + workflow + '@refs/heads/main'
        if (not re.fullmatch('[0-9a-f]{40}', head) or values.get('GITHUB_WORKFLOW_SHA') != head
                or not re.fullmatch('[1-9][0-9]*', run_id) or not re.fullmatch('[1-9][0-9]*', attempt)
                or not re.fullmatch('[A-Za-z0-9_-]+', job) or values.get('GITHUB_WORKFLOW_REF') != reference):
            raise ValueError('trusted_producer_runner_binding_required')
        return {'schema_version': 1, 'repository': self.current, 'repository_id': REPOSITORY_ID,
                'owner_id': OWNER_IDS[self.current], 'run_id': int(run_id), 'run_attempt': int(attempt),
                'head_sha': head, 'workflow_sha': head, 'workflow_ref': reference, 'job': job,
                'cutover_head_sha': self.cutover_head_sha}

    def current_producer(self, root, entry, run):
        """Current authority requires runner proof AND trusted target-enabled code.

        The caller must already bind entry bytes to the authenticated artifact
        digest/index. A JSON owner claim alone is insufficient: verify the run's
        actual commit/config/workflow/code through the local trusted Git history.
        """
        self.run_repository(run)
        proof = entry.get('producer_identity')
        if proof is None and self.current == SOURCE:
            return  # Existing source-owner archives retain their original checks.
        receipt = entry.get('receipt') or {}
        expected = {'schema_version': 1, 'repository': self.current, 'repository_id': REPOSITORY_ID,
                    'owner_id': OWNER_IDS[self.current], 'run_id': run['id'], 'run_attempt': run['run_attempt'],
                    'head_sha': run['head_sha'], 'workflow_sha': run['head_sha'],
                    'workflow_ref': self.current + '/' + run['path'] + '@refs/heads/main',
                    'job': receipt.get('job'), 'cutover_head_sha': self.cutover_head_sha}
        if (not isinstance(proof, dict) or proof != expected
                or any(type(proof[k]) is not type(v) for k, v in expected.items())):
            raise ValueError('current_producer_identity_required')
        if self.current != TARGET:
            return
        def git(*args):
            try:
                result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                raise ValueError('trusted_target_producer_git_history_required') from None
            if result.returncode:
                raise ValueError('trusted_target_producer_git_history_required')
            return result.stdout
        git('merge-base', '--is-ancestor', self.cutover_head_sha, run['head_sha'])
        git('merge-base', '--is-ancestor', run['head_sha'], 'HEAD')
        captured_policy = IdentityPolicy(json.loads(git('show', run['head_sha'] + ':config/repository_identity.json')))
        if captured_policy.current != TARGET or captured_policy.cutover_head_sha != self.cutover_head_sha:
            raise ValueError('producer_commit_not_target_activated')
        trusted_root = Path(__file__).resolve().parents[1]
        for name in TRUSTED_PRODUCER_CODE:
            if git('show', run['head_sha'] + ':' + name) != (trusted_root / name).read_bytes():
                raise ValueError('producer_code_not_current_reviewed_code')

    def run_repository(self, run, *, historical=False, strict=False):
        if (not isinstance(run, dict) or not _positive(run.get('id')) or not _positive(run.get('run_attempt'))
                or not isinstance(run.get('head_sha'), str) or not re.fullmatch('[0-9a-f]{40}', run['head_sha'])):
            raise ValueError('fixed_run_attempt_commit_required')
        repo = run.get('repository') or run.get('head_repository') or {}
        name = repo.get('full_name')
        if name != self.current and not (historical and self.current == TARGET
                                        and name == SOURCE and self._pins(run)):
            raise ValueError('run_repository_namespace_denied')
        required = strict or self.current == TARGET
        for field in ('repository', 'head_repository'):
            metadata = run.get(field)
            if metadata is None and not required:
                continue
            if not isinstance(metadata, dict) or metadata.get('full_name') != name:
                raise ValueError('fork or non-main repository identity mismatch')
            if (required or 'id' in metadata) and (type(metadata.get('id')) is not int or metadata['id'] != REPOSITORY_ID):
                raise ValueError('fixed_repository_id_required')
            owner = metadata.get('owner')
            if owner is not None and (not isinstance(owner, dict) or type(owner.get('id')) is not int or owner['id'] != OWNER_IDS[name]):
                raise ValueError('fixed_repository_owner_id_required')
        return name

    def artifact_ids(self, artifact, *, strict=False):
        metadata = artifact.get('workflow_run') or {}
        for field in ('repository_id', 'head_repository_id'):
            if strict or self.current == TARGET or field in metadata:
                if type(metadata.get(field)) is not int or metadata[field] != REPOSITORY_ID:
                    raise ValueError('fixed_artifact_repository_id_required')

    def artifact_repository(self, run, artifact):
        """Return the original producer namespace without rewriting any evidence."""
        name = self.run_repository(run, historical=True)
        self.artifact_ids(artifact)
        pins = self._pins(run)
        exact = [p for p in pins if (p['artifact_id'], p['artifact_name'], p['artifact_digest']) ==
                 (artifact.get('id'), artifact.get('name'), artifact.get('digest'))]
        if exact:
            return SOURCE
        if name != self.current or any(p['artifact_name'] == artifact.get('name') for p in pins):
            raise ValueError('historical_artifact_exact_binding_required')
        return self.current


POLICY = IdentityPolicy(json.loads((Path(__file__).resolve().parents[1] /
                                   'config/repository_identity.json').read_text()))
REPOSITORY = POLICY.current
