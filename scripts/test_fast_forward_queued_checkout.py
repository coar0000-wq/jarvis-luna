"""Queued producer fast-forward (2026-10-18): data-only commits move HEAD; code commits never do."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fast_forward_queued_checkout as ff  # noqa: E402
import restore_operations_safety as restore  # noqa: E402


class Repo:
    def __init__(self, base: Path):
        self.origin, self.work = base / "origin.git", base / "work"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.work)], check=True, capture_output=True)
        for k, v in (("user.name", "t"), ("user.email", "t@t"), ("core.autocrlf", "false")):
            self.git("config", k, v)
        (self.work / "config").mkdir()
        shutil.copy(HERE.parent / "config" / "publish_policy.json", self.work / "config" / "publish_policy.json")
        self.commit({"data/operations/state.json": "{\"sequence\": 1}\n"})

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.work), *args], capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, files):
        for rel, text in files.items():
            p = self.work / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "x")
        self.git("push", "-q", "origin", "HEAD:main")
        return self.git("rev-parse", "HEAD")


class FastForwardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(Path(self.tmp.name))
        self.event = self.repo.git("rev-parse", "HEAD")

    def tearDown(self):
        self.tmp.cleanup()

    def run_ff(self):
        with mock.patch.object(ff, "ROOT", self.repo.work), mock.patch.dict(os.environ, {"GITHUB_SHA": self.event}):
            self.repo.git("checkout", "-q", "--detach", self.event)
            ff.main()
        return self.repo.git("rev-parse", "HEAD")

    def test_data_only_commits_fast_forward_and_restore_accepts(self):
        tip = self.repo.commit({"data/operations/state.json": "{\"sequence\": 2}\n", "data/gosi.json": "{}\n"})
        self.assertEqual(self.run_ff(), tip)
        restore._require_data_only_fast_forward(self.repo.work, self.event, tip)
        restore._require_fresh_checkout(self.repo.work, tip)

    def test_code_commit_never_moves_head_and_restore_refuses(self):
        tip = self.repo.commit({"scripts/x.py": "print(1)\n"})
        self.assertEqual(self.run_ff(), self.event)
        with self.assertRaises(restore.Blocked):
            restore._require_data_only_fast_forward(self.repo.work, self.event, tip)

    def test_fresh_checkout_is_untouched(self):
        self.assertEqual(self.run_ff(), self.event)

    def test_plan_uses_publication_producer_rule(self):
        policy = json.loads((HERE.parent / "config" / "publish_policy.json").read_text(encoding="utf-8"))
        self.assertEqual(ff.plan("a", "b", ["data/x.json"], policy), "fast_forward")
        for name in ("scripts/a.py", "config/b.json", ".github/workflows/c.yml", "requirements/d.txt", "e.py"):
            self.assertEqual(ff.plan("a", "b", [name], policy), "producer_code_changed", name)


if __name__ == "__main__":
    unittest.main()
