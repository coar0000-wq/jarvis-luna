#!/usr/bin/env python3
"""Offline regressions for preflight's real static-analysis boundary."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import preflight as pf


class StaticAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pf-static-", dir=pf.ROOT.parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        for name, value in (("ROOT", self.root), ("FAIL", []), ("WARN", []), ("OK", [])):
            item = patch.object(pf, name, value)
            item.start()
            self.addCleanup(item.stop)

    @staticmethod
    def completed(code=0, stdout="", stderr=""):
        return subprocess.CompletedProcess([], code, stdout, stderr)

    def test_many_long_paths_do_not_expand_subprocess_command(self):
        targets = [self.root / "scripts" / ("long_" * 20 + str(i) + ".py")
                   for i in range(1000)]
        self.assertGreater(len(subprocess.list2cmdline([str(path) for path in targets])), 32767)
        with patch.object(Path, "rglob", return_value=iter(targets)), patch.object(
                pf.subprocess, "run", side_effect=[self.completed(), self.completed()]) as run:
            pf.check_undefined()
        command = run.call_args.args[0]
        self.assertEqual(command, [pf.sys.executable, "-m", "pyflakes", str(self.root / "scripts")])
        self.assertLess(len(subprocess.list2cmdline(command)), 8192)
        self.assertFalse(pf.FAIL)
        self.assertIn("1000", pf.OK[0][1])

    def test_directory_scan_really_covers_root_and_nested_files(self):
        scripts = self.root / "scripts"
        (scripts / "nested").mkdir()
        (scripts / "root.py").write_text("print(missing_at_root)\n", encoding="utf-8")
        (scripts / "nested" / "child.py").write_text("print(missing_nested)\n", encoding="utf-8")
        pf.check_undefined()  # Real local pyflakes, never project code execution.
        diagnostics = "\n".join(message for _, message in pf.FAIL)
        self.assertIn("undefined name 'missing_at_root'", diagnostics)
        self.assertIn("undefined name 'missing_nested'", diagnostics)
        self.assertFalse(pf.OK)

    def test_scan_launch_error_is_failure_not_success_or_uncaught_exception(self):
        (self.root / "scripts" / "file.py").touch()
        with patch.object(pf.subprocess, "run", side_effect=[
                self.completed(), OSError(206, "injected command-line failure")]):
            pf.check_undefined()
        self.assertEqual(len(pf.FAIL), 1)
        self.assertFalse(pf.OK)

    def test_abnormal_tool_exit_is_failure(self):
        (self.root / "scripts" / "file.py").touch()
        with patch.object(pf.subprocess, "run", side_effect=[
                self.completed(), self.completed(2, stderr="injected tool failure")]):
            pf.check_undefined()
        self.assertEqual(len(pf.FAIL), 1)
        self.assertIn("exit 2", pf.FAIL[0][1])
        self.assertFalse(pf.OK)

    def test_non_undefined_warnings_keep_existing_policy(self):
        (self.root / "scripts" / "file.py").touch()
        with patch.object(pf.subprocess, "run", side_effect=[
                self.completed(), self.completed(1, stdout="file.py:1:1: 'os' imported but unused")]):
            pf.check_undefined()
        self.assertFalse(pf.FAIL)
        self.assertEqual(len(pf.OK), 1)

    def test_missing_optional_tool_is_a_visible_warning(self):
        with patch.object(pf.subprocess, "run", return_value=self.completed(1)):
            pf.check_undefined()
        self.assertEqual(len(pf.WARN), 1)
        self.assertFalse(pf.OK)


if __name__ == "__main__":
    unittest.main(verbosity=2)
