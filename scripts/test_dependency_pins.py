#!/usr/bin/env python3
"""Offline lock integrity and active workflow pinning checks (no network/install)."""
from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
LINE = re.compile(r'^([a-z0-9][a-z0-9-]*)==([0-9][A-Za-z0-9.+-]*) --hash=sha256:([0-9a-f]{64})$')
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
        name, version, digest = match.groups()
        if name in result:
            raise ValueError(f'Duplicate package {name}')
        result[name] = (version, digest)
    if not result:
        raise ValueError('Empty lock file')
    return result


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
                for package, (version, digest) in locked.items():
                    expected = packages[package]
                    self.assertEqual(version, expected['version'])
                    self.assertEqual(digest, expected['sha256'])
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
        for file in active_yaml():
            for ref in re.findall(r'(?m)^\s*-?\s*uses:\s*([^\s#]+)', file.read_text(encoding='utf-8')):
                if ref.startswith('./'):
                    continue
                with self.subTest(file=file.name, action=ref):
                    self.assertIn('@', ref)
                    self.assertRegex(ref.rsplit('@', 1)[1], SHA)

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
