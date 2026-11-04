"""Explicit offline source-identity fixtures, independent of deployed owner.

Imported by tests only. There is no production environment switch or bypass.
"""
import sys
from unittest.mock import patch
from scripts import repository_identity as identity


def source_policy():
    return identity.IdentityPolicy({'schema_version': 1, 'repository_id': identity.REPOSITORY_ID,
        'current_repository': identity.SOURCE, 'current_owner_id': identity.OWNER_IDS[identity.SOURCE],
        'cutover_head_sha': None, 'historical_artifacts': []})


def isolate_source(test):
    replacements = [(identity, 'POLICY', source_policy()), (identity, 'REPOSITORY', identity.SOURCE)]
    for name in ('github_artifact_io', 'daiso_pipeline_inputs', 'restore_source_safety', 'restore_operations_safety'):
        for module_name in (name, 'scripts.' + name):
            module = sys.modules.get(module_name)
            if module is None:
                continue
            replacements.append((module, 'REPOSITORY', identity.SOURCE))
            if hasattr(module, 'BASE'):
                replacements.append((module, 'BASE', 'https://api.github.com/repos/' + identity.SOURCE + '/actions/'))
    for module, key, value in replacements:
        fixture = patch.object(module, key, value)
        fixture.start(); test.addCleanup(fixture.stop)
