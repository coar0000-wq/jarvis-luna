#!/usr/bin/env python3
"""Offline lock integrity and active workflow pinning checks (no network/install)."""
from pathlib import Path
import json
import os
import sys
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
LINE = re.compile(r'^([a-z0-9][a-z0-9-]*)==([0-9][A-Za-z0-9.+-]*)((?: --hash=sha256:[0-9a-f]{64})+)$')
HASH = re.compile(r'--hash=sha256:([0-9a-f]{64})')
SHA = re.compile(r'^[0-9a-f]{40}$')


def parse_lock(text):
    result = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = LINE.fullmatch(line)
        if not match:
            raise ValueError(f'Unpinned/unhashed or unsupported requirement at line {number}')
        name, version, hash_options = match.groups()
        digests = tuple(HASH.findall(hash_options))
        if len(set(digests)) != len(digests):
            raise ValueError(f'Duplicate hash for {name}')
        if name in result:
            raise ValueError(f'Duplicate package {name}')
        result[name] = (version, frozenset(digests))
    if not result:
        raise ValueError('Empty lock file')
    return result


def reconcile_package(name, version, digests, expected):
    """Require every accepted hash to have reviewed manifest evidence.

    sha256 remains the independently downloaded target wheel. Optional artifacts
    describe additional reviewed distributions; accepting arbitrary extra hashes
    merely because the target wheel is among them would weaken the lock.
    """
    if version != expected['version']:
        raise ValueError(f'{name}: lock version differs from manifest; re-resolve for the target runtime')
    approved = {expected['sha256']}
    for artifact in expected.get('artifacts', []):
        digest = artifact['sha256']
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError(f'{name}: invalid artifact SHA-256')
        if not artifact['filename'].endswith(('.whl', '.tar.gz', '.zip')):
            raise ValueError(f'{name}: invalid artifact filename')
        if not artifact['source'].startswith('https://files.pythonhosted.org/'):
            raise ValueError(f'{name}: invalid artifact source')
        approved.add(digest)
    if digests != approved:
        raise ValueError(f'{name}: lock hashes differ from reviewed manifest artifacts')


def approved_action_refs(manifest):
    """Resolve only canonical reviewed Action evidence, never arbitrary SHAs."""
    approved = set()
    rows = manifest.get('actions')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Missing reviewed Action evidence')
    for row in rows:
        repository, tag, digest = (row.get(key, '') for key in ('repository', 'tag', 'sha'))
        if (not isinstance(repository, str) or
                not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or
                not isinstance(tag, str) or not tag or
                not isinstance(digest, str) or not SHA.fullmatch(digest) or
                row.get('type') != 'commit' or row.get('ref') != f'{repository}@{tag}' or
                row.get('source') != f'https://api.github.com/repos/{repository}/git/ref/tags/{tag}'):
            raise ValueError('Noncanonical reviewed Action evidence')
        ref = f'{repository}@{digest}'
        if ref in approved:
            raise ValueError('Duplicate reviewed Action evidence')
        approved.add(ref)
    return approved


def workflow_action_refs(text):
    """Read YAML semantics, including quoted keys, flow maps and composites."""
    document = yaml.safe_load(text)
    if not isinstance(document, dict):
        raise ValueError('Workflow/action must be a YAML mapping')

    def walk(node, ancestors):
        if not isinstance(node, (dict, list)):
            return
        identity = id(node)
        if identity in ancestors:
            raise ValueError('Cyclic YAML aliases are unsupported')
        ancestors = ancestors | {identity}
        if isinstance(node, dict):
            for key, value in node.items():
                if key == 'uses':
                    if not isinstance(value, str) or not value:
                        raise ValueError('Action uses must be a nonempty string')
                    yield value
                else:
                    yield from walk(value, ancestors)
        else:
            for value in node:
                yield from walk(value, ancestors)

    return list(walk(document, set()))


def validate_action_ref(ref, approved):
    if ref.startswith('./'):
        return
    if '@' not in ref or not SHA.fullmatch(ref.rsplit('@', 1)[1]):
        raise ValueError(f'Action is not pinned to a full commit SHA: {ref}')
    if ref not in approved:
        raise ValueError(f'Action lacks matching reviewed manifest evidence: {ref}')


def active_yaml():
    folders = (ROOT / '.github' / 'workflows', ROOT / '.github' / 'actions')
    return sorted(p for folder in folders for p in folder.rglob('*')
                  if p.is_file() and p.suffix.lower() in {'.yml', '.yaml'})


class LockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / 'requirements/lock-manifest.json').read_text(encoding='utf-8'))

    def test_every_profile_has_exact_versions_hashes_and_closed_transitives(self):
        packages = self.manifest['packages']
        self.assertEqual(self.manifest['target']['python'], '3.11')
        self.assertEqual(self.manifest['target']['os'], 'Linux')
        self.assertEqual(self.manifest['target']['architecture'], 'x86_64')
        for name, profile in self.manifest['profiles'].items():
            with self.subTest(profile=name):
                locked = parse_lock((ROOT / profile['file']).read_text(encoding='utf-8'))
                self.assertEqual(set(locked), set(profile['packages']))
                self.assertTrue(set(profile['direct']) <= set(locked))
                for package, (version, digests) in locked.items():
                    expected = packages[package]
                    reconcile_package(package, version, digests, expected)
                    self.assertTrue(set(expected['dependencies']) <= set(locked))
                    self.assertTrue(expected['wheel'].endswith('.whl'))
                    self.assertTrue(expected['source'].startswith('https://files.pythonhosted.org/'))
                    self.assertTrue(expected['pypi'].startswith('https://pypi.org/pypi/'))

    def test_lock_parser_rejects_mutable_unhashed_duplicate_or_empty_inputs(self):
        bad = ('numpy>=2', 'numpy==2.4.6', '-r other.txt', '--extra-index-url https://bad.invalid/',
               'numpy==2.4.6 --hash=sha256:abc', '# comments only')
        for text in bad:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_lock(text)
        good = 'numpy==2.4.6 --hash=sha256:' + '1' * 64
        with self.assertRaises(ValueError):
            parse_lock(good + '\n' + good)

    @unittest.skipUnless(os.environ.get('GITHUB_ACTIONS') == 'true', 'CI runner contract')
    def test_ci_runner_matches_target_and_minimum_patch(self):
        self.assertEqual(sys.version_info[:2], (3, 11))
        minimum = tuple(map(int, self.manifest['target']['minimum_python'].split('.')))
        self.assertGreaterEqual(sys.version_info[:3], minimum)

    def test_lock_parser_accepts_one_or_multiple_sha256_hashes(self):
        first, second = '1' * 64, '2' * 64
        for hashes in ((first,), (first, second), (second, first)):
            text = 'numpy==2.4.6' + ''.join(' --hash=sha256:' + h for h in hashes)
            self.assertEqual(parse_lock(text), {'numpy': ('2.4.6', frozenset(hashes))})

    def test_lock_parser_rejects_bad_extra_hashes_or_options(self):
        good = 'numpy==2.4.6 --hash=sha256:' + '1' * 64
        for extra in (' --hash=sha256:abc', ' --hash=md5:' + '2' * 32,
                      ' --hash=sha256:' + 'z' * 64, ' --hash=sha256:' + '1' * 64,
                      ' --extra-index-url https://bad.invalid/', ' --trusted-host bad.invalid',
                      ' ; python_version >= "3.12"', ' unexpected'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                parse_lock(good + extra)

    def test_reconciliation_requires_matching_version_and_every_hash(self):
        first, second, unknown = '1' * 64, '2' * 64, '3' * 64
        expected = {'version': '1.0', 'sha256': first}
        reconcile_package('example', '1.0', frozenset((first,)), expected)
        for version, hashes in (('2.0', (first,)), ('1.0', (first, second)),
                                ('1.0', (second,)), ('1.0', ())):
            with self.subTest(version=version, hashes=hashes), self.assertRaises(ValueError):
                reconcile_package('example', version, frozenset(hashes), expected)
        expected['artifacts'] = [{'sha256': second, 'filename': 'example-1.0.tar.gz',
                                 'source': 'https://files.pythonhosted.org/example-1.0.tar.gz'}]
        reconcile_package('example', '1.0', frozenset((second, first)), expected)
        for hashes in ((first,), (second,), (first, second, unknown)):
            with self.subTest(hashes=hashes), self.assertRaises(ValueError):
                reconcile_package('example', '1.0', frozenset(hashes), expected)

    def test_reconciliation_rejects_invalid_artifact_evidence(self):
        for field, value in (('sha256', 'bad'), ('filename', 'example.exe'),
                             ('source', 'https://files.pythonhosted.org.evil.invalid/a.whl')):
            artifact = {'sha256': '2' * 64, 'filename': 'example-1.0.whl',
                        'source': 'https://files.pythonhosted.org/example-1.0.whl'}
            artifact[field] = value
            expected = {'version': '1.0', 'sha256': '1' * 64, 'artifacts': [artifact]}
            with self.subTest(field=field), self.assertRaises(ValueError):
                reconcile_package('example', '1.0', frozenset(('1' * 64, '2' * 64)), expected)

    def test_verification_core_and_daiso_do_not_download_legacy_training_stack(self):
        for profile in ('verification', 'core', 'daiso'):
            names = set(self.manifest['profiles'][profile]['packages'])
            self.assertFalse(names & {'torch', 'tensorflow', 'matplotlib', 'google-generativeai'})
        self.assertIn('numpy', self.manifest['profiles']['deep']['packages'])
        self.assertNotIn('torch', self.manifest['profiles']['deep']['packages'])
        self.assertIn('playwright', self.manifest['profiles']['browser']['packages'])

    def test_manifest_action_evidence_is_immutable_and_canonical(self):
        for row in self.manifest['actions']:
            self.assertRegex(row['sha'], SHA)
            self.assertEqual(row['type'], 'commit')
            self.assertEqual(row['source'], f"https://api.github.com/repos/{row['repository']}/git/ref/tags/{row['tag']}")


class ActiveWorkflowTests(unittest.TestCase):
    def test_public_actions_use_commit_sha_not_mutable_tags(self):
        manifest = json.loads((ROOT / 'requirements/lock-manifest.json').read_text(encoding='utf-8'))
        approved = approved_action_refs(manifest)
        for file in active_yaml():
            for ref in workflow_action_refs(file.read_text(encoding='utf-8')):
                with self.subTest(file=file.name, action=ref):
                    validate_action_ref(ref, approved)

    def test_yaml_action_forms_require_reviewed_full_sha(self):
        digest = '1' * 40  # Synthetic fixture, not a production approval.
        row = {'repository': 'actions/checkout', 'tag': 'v4', 'sha': digest,
               'type': 'commit', 'ref': 'actions/checkout@v4',
               'source': 'https://api.github.com/repos/actions/checkout/git/ref/tags/v4'}
        approved = approved_action_refs({'actions': [row]})
        forms = ('jobs:\n  test:\n    steps:\n      - uses: {ref}\n',
                 'jobs:\n  test:\n    steps:\n      - "uses": "{ref}"\n',
                 'jobs: {{test: {{steps: [{{uses: "{ref}"}}]}}}}\n',
                 'jobs: {{reuse: {{uses: "{ref}"}}}}\n',
                 'runs: {{using: composite, steps: [{{uses: "{ref}"}}]}}\n')
        for form in forms:
            for ref in (f'actions/checkout@{digest}', './.github/actions/publish'):
                with self.subTest(form=form, ref=ref):
                    self.assertEqual(workflow_action_refs(form.format(ref=ref)), [ref])
                    validate_action_ref(ref, approved)
            for ref in ('actions/checkout@main', 'actions/checkout@v4',
                        'actions/checkout@' + '2' * 40,
                        'unreviewed/action@' + digest):
                with self.subTest(form=form, ref=ref), self.assertRaises(ValueError):
                    for actual in workflow_action_refs(form.format(ref=ref)):
                        validate_action_ref(actual, approved)
        self.assertEqual(workflow_action_refs('jobs: {test: {steps: [{run: "echo uses: actions/checkout@main"}]}}'), [])

    def test_action_parser_and_manifest_fail_closed(self):
        for text in ('jobs: {test: {uses: true}}', 'jobs: {test: {uses: []}}',
                     'jobs: {test: {uses: null}}', '[]', 'cycle: &cycle {nested: *cycle}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                workflow_action_refs(text)
        row = {'repository': 'actions/checkout', 'tag': 'v4', 'sha': '1' * 40,
               'type': 'commit', 'ref': 'actions/checkout@v4',
               'source': 'https://api.github.com/repos/actions/checkout/git/ref/tags/v4'}
        for field, value in (('sha', 'main'), ('type', 'tag'), ('ref', 'wrong@v4'),
                             ('source', 'https://example.invalid/approval')):
            with self.subTest(field=field), self.assertRaises(ValueError):
                approved_action_refs({'actions': [{**row, field: value}]})
        for rows in ([], [row, row]):
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError):
                approved_action_refs({'actions': rows})

    def test_active_pip_installs_use_locked_hash_checked_profiles(self):
        for file in active_yaml():
            text = file.read_text(encoding='utf-8')
            for line in text.splitlines():
                if not re.search(r'\bpip\s+install\b', line) or line.lstrip().startswith('#'):
                    continue
                with self.subTest(file=file.name, install=line.strip()):
                    self.assertIn('--require-hashes', line)
                    self.assertIn('--only-binary=:all:', line)
                    self.assertRegex(line, r'-r\s+requirements/requirements-[a-z]+\.txt')
                    self.assertNotIn('--upgrade', line)
                    self.assertNotIn('|| true', line)
            if re.search(r'-r\s+requirements/requirements-[a-z]+\.txt', text):
                self.assertRegex(text, r'python-version:\s*[\'"]3\.11(?:\.\d+)?[\'"]')

    def test_archived_disabled_workflows_are_not_active(self):
        for file in active_yaml():
            self.assertNotIn('.disabled', file.name)

    def test_dependabot_reviews_actions_and_locked_profiles(self):
        text = (ROOT / '.github/dependabot.yml').read_text(encoding='utf-8')
        self.assertIn('package-ecosystem: github-actions', text)
        self.assertIn('package-ecosystem: pip', text)
        self.assertIn('directory: /requirements', text)
        self.assertNotIn('auto-merge', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
