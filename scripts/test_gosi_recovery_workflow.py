#!/usr/bin/env python3
"""Offline tests of Deep's actual GOSI stage and current-run release evidence.

Package installation/browser commands are fixtures. The denied-source case uses
the real collector's persisted-stop path and cannot launch a browser or fetch.
No production data, network, legal approvals or publication are changed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

import collector_result as results

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/JARVIS-Deep-Analysis.yml"


class GosiRecoveryWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        if not cls.bash:
            raise RuntimeError("Bash is required for GOSI orchestration tests")
        cls.steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["deep-analysis"]["steps"]
        cls.stage = next(s for s in cls.steps if s.get("id") == "gosi_recovery")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gosi-workflow-", dir=ROOT.parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        self.source = self.root / "data/gosi.json"
        self.source.write_text(json.dumps({
            "items": {"1041749": {"maker": "retained source fact", "captured_at": "original"}},
            # Missing stop time fails closed without depending on today's clock.
            "provider_stops": [{"provider": "daiso", "code": 403, "category": "auth"}],
        }))
        self.before = self.source.read_bytes()
        self.result_dir = self.root / "release-results"
        self.report = self.root / "report.json"
        self.runtime = self.root / "data/dashboard_runtime.json"
        self.calls = self.root / "fixture-calls"

    def test_gap_detector_counts_role_only_maker_without_mutating_evidence(self):
        stage = next(s for s in self.steps if s.get("id") == "s_gosi_gap")
        code = stage["run"].split("python - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        (self.root / 'data/daiso_real').mkdir()
        (self.root / 'data/daiso_real/shopify_s_recommendations.json').write_text(json.dumps({
            'recommendations': [{'pd_no': '1033789', 'grade': 'S'}]}))
        output = self.root / 'github-output'
        for maker, count in (('및 책임판매원', 1), ('(주)엘지생활건강', 0)):
            with self.subTest(maker=maker):
                self.source.write_text(json.dumps({'items': {'1033789': dict(
                    ingredients='정제수', volume='90g', maker=maker, origin='대한민국')}}))
                before = self.source.read_bytes()
                output.write_text('')
                result = subprocess.run([sys.executable, '-c', code], cwd=self.root,
                    env={**os.environ, 'GITHUB_OUTPUT': str(output), 'PYTHONPATH': str(ROOT),
                         'PYTHONDONTWRITEBYTECODE': '1'}, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output.read_text(), f'count={count}\n')
                self.assertEqual(self.source.read_bytes(), before)

    def run_stage(self, count="1", pip_code=0, browser_code=0, collector_mode="stopped", source_stopped=True):
        if not source_stopped:
            doc = json.loads(self.source.read_bytes())
            doc["provider_stops"] = []
            self.source.write_text(json.dumps(doc))
            self.before = self.source.read_bytes()
        # Execute the workflow shell verbatim. Only external/installation calls
        # are replaced; collector_result.py remains the real subprocess wrapper.
        stopped = "\n".join((
            "from pathlib import Path",
            "import os",
            "from unittest.mock import patch",
            "from scripts.daiso import collect_gosi_alt as collector",
            "collector.GOSI = Path('data/gosi.json')",
            "with patch.dict('sys.modules', {'playwright': None, 'playwright.sync_api': None}):",
            "    raise SystemExit(collector.main(check_access_only=os.getenv('FIXTURE_CHECK_ONLY') == '1'))",
        ))
        script = r'''
python() {
  if [[ "$1" == scripts/collector_result.py ]]; then
    shift
    command "$FIXTURE_PYTHON" "$FIXTURE_REPO/scripts/collector_result.py" "$@"
  elif [[ "$1" == -m && "$2" == pip ]]; then
    printf 'pip\n' >> "$FIXTURE_CALLS"
    return "$FIXTURE_PIP_CODE"
  elif [[ "$1" == -u && "$2" == scripts/daiso/collect_gosi_alt.py ]]; then
    if [[ "${3:-}" == --check-access-only ]]; then
      printf 'access-check\n' >> "$FIXTURE_CALLS"
      FIXTURE_CHECK_ONLY=1 command "$FIXTURE_PYTHON" -c "$FIXTURE_STOPPED_SCRIPT"
      return $?
    fi
    printf 'collector\n' >> "$FIXTURE_CALLS"
    if [[ "$FIXTURE_COLLECTOR_MODE" == stopped ]]; then
      command "$FIXTURE_PYTHON" -c "$FIXTURE_STOPPED_SCRIPT"
    else
      return 0
    fi
  else
    printf 'Unexpected Python command: %s\n' "$*" >&2
    return 97
  fi
}
playwright() {
  printf 'browser-install\n' >> "$FIXTURE_CALLS"
  return "$FIXTURE_BROWSER_CODE"
}
export -f python playwright
'''
        env = dict(os.environ, RUNNER_TEMP=str(self.root), GOSI_GAP_COUNT=count,
                   RELEASE_EXECUTION_ID="gosi-fixture:1", FIXTURE_PYTHON=sys.executable,
                   FIXTURE_REPO=str(ROOT), FIXTURE_CALLS=str(self.calls),
                   FIXTURE_PIP_CODE=str(pip_code), FIXTURE_BROWSER_CODE=str(browser_code),
                   FIXTURE_COLLECTOR_MODE=collector_mode, FIXTURE_STOPPED_SCRIPT=stopped,
                   PYTHONPATH=str(ROOT))
        return subprocess.run([self.bash, "--noprofile", "--norc", "-e", "-o", "pipefail",
                               "-c", script + self.stage["run"]], cwd=self.root,
                              env=env, capture_output=True, text=True, timeout=30)

    def recorded(self):
        return json.loads((self.result_dir / "deep_gosi_alt.json").read_text())

    def independent_required_stage(self, code=0):
        # A downstream local rebuild may proceed after the optional step; its
        # own failure still blocks publication. No real commerce task is run.
        from unittest.mock import patch
        command = [sys.executable, "-c", "from pathlib import Path; "
                   "Path('" + self.runtime.as_posix() + "').write_text('{}'); "
                   f"raise SystemExit({code})"]
        with patch.dict(os.environ, {"RELEASE_EXECUTION_ID": "gosi-fixture:1"}):
            return results.run_stage("independent", True, [str(self.runtime)], command,
                                     self.result_dir / "independent.json")

    def aggregate(self):
        return results.aggregate(self.result_dir,
                                 [("deep_gosi_alt", False), ("independent", True)],
                                 self.report, self.runtime, identity="gosi-fixture:1")

    def test_persisted_403_remains_failed_and_independent_work_can_finish(self):
        process = self.run_stage()
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertIn("GOSI_COLLECTION_BLOCKED: daiso: auth circuit stopped (403)", process.stderr)
        row = self.recorded()
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["process_exit_code"], 2)
        self.assertEqual(row["wrapper_exit_code"], 2)
        self.assertEqual(row["error_code"], "process_exit_2")
        self.assertFalse(row["required"])
        self.assertTrue(row["using_cached_data"])
        self.assertIsNone(row["last_successful_fetch_at"])
        self.assertFalse(row["content_changed"])
        self.assertEqual(row["artifacts"][0]["sha256"], hashlib.sha256(self.before).hexdigest())
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(self.independent_required_stage(), 0)
        self.assertEqual(self.aggregate(), 0)
        report = json.loads(self.report.read_text())
        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["optional_failures"], ["deep_gosi_alt"])
        self.assertEqual(report["required_failures"], [])
        self.assertEqual(report["evidence_errors"], [])
        self.assertEqual(json.loads(self.runtime.read_text())["pipeline_health"]["status"], "degraded")

    def test_required_failure_still_blocks_after_optional_source_failure(self):
        self.assertEqual(self.run_stage().returncode, 2)
        self.assertEqual(self.independent_required_stage(code=7), 7)
        self.assertEqual(self.aggregate(), 1)
        report = json.loads(self.report.read_text())
        self.assertFalse(report["publish_allowed"])
        self.assertEqual(report["required_failures"], ["independent"])

    def test_no_missing_targets_is_recorded_without_install_or_fetch(self):
        process = self.run_stage(count="0", source_stopped=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("GOSI_RECOVERY_NOT_NEEDED", process.stdout)
        self.assertEqual(self.calls.read_text().splitlines(), ["access-check"])
        self.assertEqual(self.source.read_bytes(), self.before)
        row = self.recorded()
        self.assertEqual(row["status"], "success")
        self.assertIsNone(row["last_successful_fetch_at"])
        self.assertEqual(row["fetch_verification"], "not_instrumented")
        self.assertTrue(row["using_cached_data"])
        self.assertEqual(self.independent_required_stage(), 0)
        self.assertEqual(self.aggregate(), 0)
        self.assertEqual(json.loads(self.report.read_text())["status"], "success")

    def test_no_missing_targets_still_respects_persisted_stop(self):
        process = self.run_stage(count="0")
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertEqual(self.calls.read_text().splitlines(), ["access-check"])
        self.assertEqual(self.recorded()["status"], "failed")
        self.assertEqual(self.source.read_bytes(), self.before)

    def test_preparation_failures_are_recorded_before_collection(self):
        for pip_code, browser_code, calls in ((9, 0, ["access-check", "pip"]),
                                               (0, 8, ["access-check", "pip", "browser-install"])):
            with self.subTest(pip=pip_code, browser=browser_code):
                self.calls.unlink(missing_ok=True)
                process = self.run_stage(pip_code=pip_code, browser_code=browser_code, source_stopped=False)
                self.assertEqual(process.returncode, pip_code or browser_code)
                self.assertEqual(self.calls.read_text().splitlines(), calls)
                self.assertEqual(self.recorded()["status"], "failed")
                self.assertEqual(self.source.read_bytes(), self.before)

    def test_invalid_gap_count_never_starts_source_or_installation(self):
        for count in ("", "unknown", "$(touch unexpected)"):
            with self.subTest(count=count):
                self.calls.unlink(missing_ok=True)
                self.assertEqual(self.run_stage(count=count, source_stopped=False).returncode, 1)
                self.assertEqual(self.recorded()["status"], "failed")
                self.assertEqual(self.calls.read_text().splitlines(), ["access-check"])

    def test_missing_current_evidence_still_blocks(self):
        self.assertEqual(self.independent_required_stage(), 0)
        self.assertEqual(self.aggregate(), 1)
        self.assertFalse(json.loads(self.report.read_text())["publish_allowed"])

    def test_successful_process_does_not_claim_source_fetch(self):
        self.assertEqual(self.run_stage(collector_mode="success", source_stopped=False).returncode, 0)
        row = self.recorded()
        self.assertEqual(row["status"], "success")
        self.assertIsNone(row["last_successful_fetch_at"])
        self.assertTrue(row["using_cached_data"])

    def test_failed_gosi_cannot_dispatch_later_network_recovery(self):
        stage = next(s for s in self.steps if s["name"] == "Bounded existing-team source recovery")
        self.assertEqual(stage["env"]["GOSI_RECOVERY_OUTCOME"], "${{ steps.gosi_recovery.outcome }}")
        for outcome in ("failure", "skipped", "cancelled", "", "success"):
            with self.subTest(outcome=outcome):
                env = dict(os.environ, GOSI_RECOVERY_OUTCOME=outcome, GITHUB_WORKSPACE=str(self.root))
                script = 'python() { printf "%s\\n" "$@"; };\n' + stage["run"]
                process = subprocess.run([self.bash, "-e", "-c", script], cwd=self.root,
                                         env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertIn("scripts/run_source_procedures.py", process.stdout)
                self.assertEqual("--allow-source-reads" in process.stdout, outcome == "success")
        observer = next(s for s in self.steps if s["name"] == "Observe active shortlist source prices without operating writes")
        self.assertEqual(observer["if"], "steps.source_safety.outputs.continuity == 'verified' && steps.gosi_recovery.outcome == 'success'")

    def test_workflow_contract_preserves_required_gates_and_standalone_failure(self):
        self.assertTrue(self.stage["continue-on-error"])
        self.assertNotIn("if", self.stage)  # No-gap runs must also leave evidence.
        self.assertEqual(self.stage["env"]["GOSI_GAP_COUNT"], "${{ steps.s_gosi_gap.outputs.count }}")
        self.assertIn("--artifact data/gosi.json", self.stage["run"])
        aggregate = next(s for s in self.steps if s.get("id") == "release_outcomes")
        self.assertIn("--expected deep_gosi_alt:optional", aggregate["run"])
        for name in ("deep_35", "deep_37", "deep_38", "deep_41", "deep_50", "deep_53", "deep_55"):
            self.assertIn(f"--expected {name}:required", aggregate["run"])
            stage = next(s for s in self.steps if f"--name {name} --required" in s.get("run", ""))
            self.assertFalse(stage.get("continue-on-error", False), name)
        publish = next(s for s in self.steps if s.get("uses") == "./.github/actions/publish")
        self.assertEqual(publish["if"], "success() && steps.release_outcomes.outcome == 'success' && steps.release_quality.outcome == 'success'")
        self.assertEqual(publish["with"]["collector-report"], "data/agents/deep_run_results.json")
        standalone = yaml.safe_load((ROOT / ".github/workflows/gosi-alt.yml").read_text())
        collection = next(s for s in standalone["jobs"]["collect"]["steps"]
                          if "python -u scripts/daiso/collect_gosi_alt.py" in s.get("run", ""))
        self.assertFalse(collection.get("continue-on-error", False))
        self.assertIn("python scripts/test_gosi_recovery_workflow.py",
                      (ROOT / ".github/workflows/preflight.yml").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
