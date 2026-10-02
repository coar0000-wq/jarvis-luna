#!/usr/bin/env python3
"""Offline tests of the actual shell helper, with Python/tee subprocess fixtures.

Bash is required: missing tools are failures, not skipped regression tests.
No project script, network, key, collector, LLM or paid API is invoked.
"""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/preflight_workflow.sh"
GRAPH_KEYS = ("mermaid", "self_improve", "replay", "team_learning", "shortlist", "graph_check")
COMMANDS = ("test_build_artifact_graph_mermaid.py", "test_self_improve.py",
            "test_self_improve_replay.py", "test_team_learning.py",
            "test_shopify_shortlist_guard.py", "build_artifact_graph.py")
GOOD = dict(REPAIR_OUTCOME="success", REGRESSION_OUTCOME="success", PF_OUTCOME="success", PF_COMPLETED="true",
            PF_RC="0", PF_RAW_RC="0", PF_TEE_RC="0", PF_LOG_OK="1",
            GRAPH_OUTCOME="success", GRAPH_COMPLETED="true", GRAPH_RC="0",
            SUMMARY_OUTCOME="success")


def find_bash():
    found = shutil.which("bash")
    if not found and os.name == "nt":
        git = shutil.which("git")
        if git:
            candidate = Path(git).resolve().parents[1] / "bin/bash.exe"
            if candidate.is_file():
                found = str(candidate)
    if not found:
        raise RuntimeError("Bash required; installation is not attempted")
    return found


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bash = find_bash()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pf-workflow-", dir=ROOT.parent)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.output = self.base / "output"
        self.summary = self.base / "summary"
        self.calls = self.base / "calls"
        self.env = os.environ.copy()
        self.env.update(RUNNER_TEMP=self.base.as_posix(),
                        GITHUB_OUTPUT=self.output.as_posix(),
                        GITHUB_STEP_SUMMARY=self.summary.as_posix(),
                        FIXTURE_CALLS=self.calls.as_posix())
        for key in GOOD:
            self.env.pop(key, None)

    def run_mode(self, mode, codes=None, silent=False, tee_error=False, env=None):
        cases = " ".join(f"*{shlex.quote(name)}) return {code} ;;"
                         for name, code in (codes or {}).items())
        fixture = """
python() {
  printf '%s\\n' "$*" >> "$FIXTURE_CALLS"
  if [[ "$FIXTURE_SILENT" != 1 ]]; then printf 'fixture output: %s\\n' "$*"; fi
  case "$1" in __CASES__ esac
  return 0
}
tee() { command tee "$@"; if [[ "$FIXTURE_TEE_ERROR" == 1 ]]; then return 7; fi; }
export -f python tee
source "$1" "$2"
""".replace("__CASES__", cases)
        actual_env = dict(self.env, FIXTURE_SILENT=str(int(silent)),
                          FIXTURE_TEE_ERROR=str(int(tee_error)))
        actual_env.update(env or {})
        return subprocess.run([self.bash, "--noprofile", "--norc", "-e", "-o",
                               "pipefail", "-c", fixture, "fixture",
                               HELPER.as_posix(), mode], env=actual_env,
                              capture_output=True, text=True, timeout=30)

    def outputs(self):
        if not self.output.exists():
            return {}
        return dict(line.split("=", 1) for line in self.output.read_text().splitlines())

    def test_preflight_pass(self):
        self.assertEqual(self.run_mode("preflight").returncode, 0)
        self.assertEqual(self.outputs()["preflight_rc"], "0")
        self.assertEqual(self.outputs()["completed"], "true")

    def test_preflight_fail_records_exit_under_errexit_pipefail(self):
        self.assertEqual(self.run_mode("preflight", {"preflight.py": 1}).returncode, 1)
        self.assertEqual(self.outputs()["preflight_rc"], "1")
        self.assertEqual(self.outputs()["rc"], "1")
        self.assertEqual(self.outputs()["completed"], "true")

    def test_preflight_warning_only_advisory(self):
        self.assertEqual(self.run_mode("preflight", {"preflight.py": 2}).returncode, 0)
        self.assertEqual(self.outputs()["preflight_rc"], "2")
        self.assertEqual(self.outputs()["rc"], "0")

    def test_preflight_unexpected_exit_fails(self):
        self.assertEqual(self.run_mode("preflight", {"preflight.py": 127}).returncode, 1)
        self.assertEqual(self.outputs()["preflight_rc"], "127")

    def test_preflight_missing_output_fails(self):
        self.assertEqual(self.run_mode("preflight", silent=True).returncode, 1)
        self.assertEqual(self.outputs()["preflight_log_ok"], "0")

    def test_preflight_tee_failure_preserves_both_exits(self):
        self.assertEqual(self.run_mode("preflight", {"preflight.py": 2}, tee_error=True).returncode, 1)
        self.assertEqual(self.outputs()["preflight_rc"], "2")
        self.assertEqual(self.outputs()["preflight_tee_rc"], "7")

    def test_missing_output_destination_fails(self):
        self.assertNotEqual(self.run_mode("preflight", env={"GITHUB_OUTPUT": ""}).returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_graph_pass_records_every_exit(self):
        self.assertEqual(self.run_mode("graph").returncode, 0)
        for key in GRAPH_KEYS:
            self.assertEqual(self.outputs()[key + "_rc"], "0")
        self.assertEqual(len(self.calls.read_text().splitlines()), 6)

    def test_each_graph_failure_survives_later_success(self):
        for name, key in zip(COMMANDS, GRAPH_KEYS):
            with self.subTest(command=name):
                self.output.unlink(missing_ok=True)
                self.calls.unlink(missing_ok=True)
                self.assertEqual(self.run_mode("graph", {name: 1}).returncode, 1)
                self.assertEqual(self.outputs()[key + "_rc"], "1")
                self.assertEqual(self.outputs()["rc"], "1")
                self.assertEqual(self.outputs()["completed"], "true")
                self.assertEqual(len(self.calls.read_text().splitlines()), 6)

    def test_graph_exit_two_is_not_warning_policy(self):
        self.assertEqual(self.run_mode("graph", {COMMANDS[0]: 2}).returncode, 1)

    def test_graph_multiple_exits_preserved(self):
        self.assertEqual(self.run_mode("graph", {COMMANDS[0]: 3, COMMANDS[2]: 9}).returncode, 1)
        self.assertEqual(self.outputs()["mermaid_rc"], "3")
        self.assertEqual(self.outputs()["replay_rc"], "9")
        self.assertEqual(self.outputs()["graph_check_rc"], "0")

    def test_graph_tee_failure_fails(self):
        self.assertEqual(self.run_mode("graph", tee_error=True).returncode, 1)
        for key in GRAPH_KEYS:
            self.assertEqual(self.outputs()[key + "_tee_rc"], "7")

    def test_graph_missing_output_fails(self):
        self.assertEqual(self.run_mode("graph", silent=True).returncode, 1)

    def test_summary_records_failed_check_and_all_later_checks(self):
        self.run_mode("preflight", {"preflight.py": 1})
        self.run_mode("graph", {COMMANDS[0]: 1})
        self.assertEqual(self.run_mode("summary", env={"REGRESSION_OUTCOME": "failure", "REPAIR_OUTCOME": "failure"}).returncode, 0)
        text = self.summary.read_text()
        self.assertIn("exit=1 tee=0", text)
        self.assertIn("Workflow regression tests: failure", text)
        self.assertIn("Operational repair tests: failure", text)
        for key in GRAPH_KEYS:
            self.assertIn("#### " + key, text)

    def test_summary_missing_checks_records_and_fails(self):
        self.assertEqual(self.run_mode("summary").returncode, 1)
        self.assertEqual(self.summary.read_text().count("NOT RUN / MISSING OUTPUT"), 7)

    def test_summary_write_failure(self):
        self.assertNotEqual(self.run_mode("summary", env={"GITHUB_STEP_SUMMARY": self.base.as_posix()}).returncode, 0)

    def test_gate_pass_and_warning_pass(self):
        for raw in ("0", "2"):
            with self.subTest(raw=raw):
                self.assertEqual(self.run_mode("gate", env=dict(GOOD, PF_RAW_RC=raw)).returncode, 0)

    def test_gate_every_missing_field_fails(self):
        for key in GOOD:
            with self.subTest(key=key):
                self.assertEqual(self.run_mode("gate", env=dict(GOOD, **{key: ""})).returncode, 1)

    def test_gate_failed_skipped_cancelled_checks_fail(self):
        for key in ("REPAIR_OUTCOME", "REGRESSION_OUTCOME", "PF_OUTCOME", "GRAPH_OUTCOME", "SUMMARY_OUTCOME"):
            for value in ("failure", "skipped", "cancelled"):
                with self.subTest(key=key, value=value):
                    self.assertEqual(self.run_mode("gate", env=dict(GOOD, **{key: value})).returncode, 1)

    def test_gate_invalid_status_fails(self):
        for key, value in (("PF_RAW_RC", "1"), ("PF_RAW_RC", "127"), ("PF_RC", "1"),
                           ("GRAPH_RC", "2"), ("PF_TEE_RC", "7"), ("PF_LOG_OK", "0"),
                           ("PF_COMPLETED", "false"), ("GRAPH_COMPLETED", "false")):
            with self.subTest(key=key, value=value):
                self.assertEqual(self.run_mode("gate", env=dict(GOOD, **{key: value})).returncode, 1)

    def test_end_to_end_gate_from_real_helper_outputs(self):
        scenarios = (({}, {}, False, False, 0),
                     ({"preflight.py": 2}, {}, False, False, 0),
                     ({"preflight.py": 1}, {}, False, False, 1),
                     ({}, {COMMANDS[0]: 1}, False, False, 1),
                     ({}, {}, True, False, 1),
                     ({}, {}, False, True, 1))
        for pf_codes, graph_codes, silent, tee_error, expected in scenarios:
            with self.subTest(pf=pf_codes, graph=graph_codes, silent=silent, tee=tee_error):
                self.output.unlink(missing_ok=True)
                pf = self.run_mode("preflight", pf_codes, silent=silent, tee_error=tee_error)
                pf_outputs = self.outputs()
                self.output.unlink(missing_ok=True)
                graph = self.run_mode("graph", graph_codes)
                graph_outputs = self.outputs()
                summary = self.run_mode("summary", env={"REGRESSION_OUTCOME": "success", "REPAIR_OUTCOME": "success"})
                values = dict(GOOD,
                              PF_OUTCOME="success" if pf.returncode == 0 else "failure",
                              PF_COMPLETED=pf_outputs.get("completed", ""),
                              PF_RC=pf_outputs.get("rc", ""),
                              PF_RAW_RC=pf_outputs.get("preflight_rc", ""),
                              PF_TEE_RC=pf_outputs.get("preflight_tee_rc", ""),
                              PF_LOG_OK=pf_outputs.get("preflight_log_ok", ""),
                              GRAPH_OUTCOME="success" if graph.returncode == 0 else "failure",
                              GRAPH_COMPLETED=graph_outputs.get("completed", ""),
                              GRAPH_RC=graph_outputs.get("rc", ""),
                              SUMMARY_OUTCOME="success" if summary.returncode == 0 else "failure")
                self.assertEqual(self.run_mode("gate", env=values).returncode, expected)

    def test_workflow_wiring_always_and_outcomes(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/preflight.yml").read_text(encoding="utf-8"))
        steps = {s["id"]: s for s in workflow["jobs"]["verify"]["steps"] if "id" in s}
        for key in ("repairs", "regression", "pf", "graph", "summary", "gate"):
            self.assertEqual(steps[key]["if"], "always()")
        self.assertEqual(steps["regression"]["run"], "python scripts/test_preflight_workflow.py")
        for key in ("regression", "pf", "graph"):
            self.assertTrue(steps[key]["continue-on-error"])
        self.assertNotIn("continue-on-error", steps["repairs"])
        self.assertNotIn("continue-on-error", steps["gate"])
        self.assertNotIn("continue-on-error", steps["summary"])
        for mode in ("preflight", "graph", "summary", "gate"):
            key = "pf" if mode == "preflight" else mode
            self.assertEqual(steps[key]["run"], "bash scripts/preflight_workflow.sh " + mode)
        expected = {
            "REPAIR_OUTCOME": "steps.repairs.outcome",
            "REGRESSION_OUTCOME": "steps.regression.outcome", "PF_OUTCOME": "steps.pf.outcome",
            "PF_COMPLETED": "steps.pf.outputs.completed", "PF_RC": "steps.pf.outputs.rc",
            "PF_RAW_RC": "steps.pf.outputs.preflight_rc", "PF_TEE_RC": "steps.pf.outputs.preflight_tee_rc",
            "PF_LOG_OK": "steps.pf.outputs.preflight_log_ok", "GRAPH_OUTCOME": "steps.graph.outcome",
            "GRAPH_COMPLETED": "steps.graph.outputs.completed", "GRAPH_RC": "steps.graph.outputs.rc",
            "SUMMARY_OUTCOME": "steps.summary.outcome",
        }
        self.assertEqual(steps["gate"]["env"], {k: '${{ ' + v + ' }}' for k, v in expected.items()})


if __name__ == "__main__":
    unittest.main(verbosity=2)
