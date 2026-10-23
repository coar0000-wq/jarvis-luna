#!/usr/bin/env python3
"""Offline tests of Deep's actual GOSI stage and current-run release evidence.

Package installation/browser commands are fixtures. The denied-source case uses
the real collector's persisted-stop path and cannot launch a browser or fetch.
No production data, network, legal approvals or publication are changed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

import yaml

import collector_result as results

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORKFLOW = ROOT / ".github/workflows/JARVIS-Deep-Analysis.yml"


class AuthenticatedGosiFixture:
    """Reusable offline Actions prerequisite for collector entrypoint tests."""

    def prepare_continuity_fixture(self, root, document):
        self.root = Path(root)
        (self.root / "data").mkdir()
        self.source = self.root / "data/gosi.json"
        self.source.write_text(json.dumps(document))
        self.before = self.source.read_bytes()
        # The real CLI derives ROOT from __file__. Copy only that entrypoint;
        # imports still use the checkout's production helpers via PYTHONPATH.
        entrypoint = self.root / "scripts/daiso/collect_gosi_alt.py"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_bytes((ROOT / "scripts/daiso/collect_gosi_alt.py").read_bytes())
        (self.root / "playwright.py").write_text(
            "raise AssertionError('workflow fixture must never import a browser')\n")
        (self.root / "config").mkdir()
        (self.root / "config/publish_policy.json").write_text(json.dumps({"identity_fields": ["product_id"]}))
        for arguments in (("init", "-q"), ("add", "data", "config"),
                          ("-c", "user.name=Offline Fixture", "-c", "user.email=fixture@example.invalid",
                           "commit", "-qm", "isolated workflow fixture")):
            subprocess.run(["git", "-C", str(self.root), *arguments],
                           check=True, capture_output=True)
        self.head = subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        from scripts import gosi_safety_checkpoint as checkpoint
        self.actions_env = dict(GITHUB_ACTIONS="true", GITHUB_REPOSITORY=checkpoint.REPOSITORY,
            GITHUB_RUN_ID="99", GITHUB_RUN_ATTEMPT="1", GITHUB_SHA=self.head,
            GITHUB_WORKSPACE=str(self.root), PYTHONDONTWRITEBYTECODE="1",
            PYTHONPATH=str(self.root) + os.pathsep + str(ROOT))
        self.restore_authenticated_fixture()

    def restore_authenticated_fixture(self):
        """Real restore verification/proof writer; only GitHub transport is fake.

        The ZIP models an authenticated predecessor fixture, not a production
        activation or hand-written current-run continuity proof.
        """
        from scripts import gosi_safety_checkpoint as checkpoint
        workflow = ".github/workflows/JARVIS-Deep-Analysis.yml"
        lineage = dict(repository=checkpoint.REPOSITORY, run_id="11", run_attempt="1", commit=self.head)
        manifest = dict(schema_version=1, lineage=lineage, checkout_commit=self.head,
            base=dict(commit=self.head, history_tree=None,
                      inventory_sha256=hashlib.sha256(b"{}\n").hexdigest(), file_count=0),
            coverage={"11": [1, checkpoint.WORKFLOW_ORDER.index(workflow), self.head]},
            files={"data/gosi.json": dict(sha256=hashlib.sha256(self.before).hexdigest(), size=len(self.before))})
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr(checkpoint.MANIFEST, json.dumps(manifest))
            archive.writestr("data/gosi.json", self.before)
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w") as archive:
            archive.writestr("gosi-safety.zip", payload.getvalue())
        raw = outer.getvalue()
        run = dict(id=11, run_attempt=1, path=workflow, head_branch="main",
            head_repository={"full_name": checkpoint.REPOSITORY}, head_sha=self.head,
            status="completed", conclusion="failure")
        download = checkpoint.BASE + "artifacts/71/zip"
        artifact = dict(id=71, name="gosi-safety-11-1", expired=False,
            workflow_run=dict(id=11, head_sha=self.head, head_branch="main"),
            archive_download_url=download, digest="sha256:" + hashlib.sha256(raw).hexdigest())
        self.restore_requests = []

        def fetch_json(url):
            self.restore_requests.append(url)
            if url == checkpoint.BASE + "runs/99/attempts/1":
                return dict(run, id=99, status="in_progress", conclusion=None)
            if url == checkpoint.BASE + "runs/11/attempts/1":
                return run
            if url in (checkpoint.BASE + "artifacts?per_page=100&page=1",
                       checkpoint.BASE + "runs/11/artifacts?per_page=100"):
                return dict(total_count=1, artifacts=[artifact])
            if url == checkpoint.BASE + "runs/11/attempts/1/jobs?per_page=100":
                return dict(total_count=1, jobs=[dict(completed_at="2026-01-01T00:00:00+00:00")])
            for name in checkpoint.WORKFLOWS:
                if url == checkpoint.BASE + "workflows/" + name.rsplit("/", 1)[1] + "/runs?per_page=100&page=1":
                    return dict(total_count=int(name == workflow), workflow_runs=[run] if name == workflow else [])
            raise AssertionError("Unexpected offline GitHub request: " + url)

        def fetch_bytes(url):
            self.assertEqual(url, download)
            return raw

        with patch.dict(os.environ, self.actions_env):
            restored = checkpoint.restore_latest(self.root, fetch_json=fetch_json,
                fetch_bytes=fetch_bytes, current_run_id="99", current_attempt="1")
            self.assertEqual(restored["status"], "unchanged")
            checkpoint.h.require_continuity(self.root)
        self.assertEqual(self.source.read_bytes(), self.before)


class GosiRecoveryWorkflowTests(AuthenticatedGosiFixture, unittest.TestCase):
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
        self.prepare_continuity_fixture(self.tmp.name, {
            "items": {"1041749": {"maker": "retained source fact", "captured_at": "original"}},
            "provider_stops": [{"provider": "daiso", "code": 403, "category": "auth",
                                "stopped_at": datetime.now(timezone.utc).isoformat()}],
        })
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

    def test_actions_restore_proof_is_bound_to_isolated_cli_root(self):
        proof = json.loads((self.root / '.gosi-safety-verified.json').read_bytes())
        self.assertEqual(self.actions_env['GITHUB_ACTIONS'], 'true')
        self.assertEqual(proof['head'], self.head)
        self.assertEqual(proof['event_sha'], self.actions_env['GITHUB_SHA'])
        self.assertEqual(proof['run_id'], self.actions_env['GITHUB_RUN_ID'])
        self.assertEqual(proof['run_attempt'], self.actions_env['GITHUB_RUN_ATTEMPT'])
        self.assertEqual(proof['source']['run_id'], '11')
        self.assertTrue(any('/artifacts?' in url for url in self.restore_requests))
        process = self.run_stage()
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertIn('auth circuit stopped (403)', process.stderr)
        self.assertEqual(self.calls.read_text().splitlines(), ['access-check'])

    def test_actions_cli_rejects_missing_stale_or_pending_proof_before_setup(self):
        proof_path = self.root / '.gosi-safety-verified.json'
        original = proof_path.read_bytes()
        cases = [("missing", None), ("run_id", "100"), ("run_attempt", "2"),
                 ("repository", "foreign/repository"), ("head", "0" * 40),
                 ("event_sha", "0" * 40),
                 (".gosi-safety-restore.pending", "interrupted"),
                 (".gosi-collection.pending", "interrupted")]
        for key, value in cases:
            with self.subTest(case=key):
                self.calls.unlink(missing_ok=True)
                proof_path.write_bytes(original)
                pending = self.root / key if key.endswith('.pending') else None
                if key == "missing":
                    proof_path.unlink()
                elif pending:
                    pending.write_text(value)
                else:
                    proof = json.loads(original)
                    proof[key] = value
                    proof_path.write_text(json.dumps(proof))
                try:
                    process = self.run_stage()
                    self.assertNotEqual(process.returncode, 0, process.stderr)
                    self.assertIn('gosi ', process.stderr)
                    self.assertNotIn('auth circuit stopped (403)', process.stderr)
                    self.assertEqual(self.calls.read_text().splitlines(), ['access-check'])
                    self.assertEqual(self.recorded()['status'], 'failed')
                    self.assertIsNone(self.recorded()['last_successful_fetch_at'])
                    self.assertEqual(self.source.read_bytes(), self.before)
                finally:
                    if pending:
                        pending.unlink()
                    proof_path.write_bytes(original)

    def run_stage(self, count="1", pip_code=0, browser_code=0, collector_mode="stopped", source_stopped=True, hang_phase="", pip_delay="0", continuity="success", deadline=None):
        if not source_stopped:
            doc = json.loads(self.source.read_bytes())
            doc["provider_stops"] = []
            self.source.write_text(json.dumps(doc))
            self.before = self.source.read_bytes()
        # Execute the workflow shell verbatim. Only external/installation calls
        # are replaced; collector_result.py remains the real subprocess wrapper.
        script = r'''
python() {
  if [[ "$1" == scripts/collector_result.py ]]; then
    shift
    command "$FIXTURE_PYTHON" "$FIXTURE_REPO/scripts/collector_result.py" "$@"
  elif [[ "$1" == -c ]]; then
    command "$FIXTURE_PYTHON" -c "${FIXTURE_CLOCK_PREFIX:-}$2" "${@:3}"
  elif [[ "$1" == -m && "$2" == pip ]]; then
    printf 'pip\n' >> "$FIXTURE_CALLS"
    if [[ "$FIXTURE_PIP_DELAY" != 0 ]]; then sleep "$FIXTURE_PIP_DELAY"; fi
    if [[ "$FIXTURE_HANG_PHASE" == pip_ignore_term ]]; then trap "" TERM; sleep 30; fi
    if [[ "$FIXTURE_HANG_PHASE" == pip_install ]]; then sleep 30; fi
    if [[ "$FIXTURE_HANG_PHASE" == pip_descendant ]]; then command "$FIXTURE_PYTHON" -c "$FIXTURE_STUCK_DESCENDANT"; fi
    return "$FIXTURE_PIP_CODE"
  elif [[ "$1" == -u && "$2" == scripts/daiso/collect_gosi_alt.py ]]; then
    if [[ "${3:-}" == --check-access-only ]]; then
      printf 'access-check\n' >> "$FIXTURE_CALLS"
      command "$FIXTURE_PYTHON" "$@"
      return $?
    fi
    printf 'collector\n' >> "$FIXTURE_CALLS"
    if [[ "$FIXTURE_COLLECTOR_MODE" == hung_worker ]]; then
      command "$FIXTURE_PYTHON" -c "$FIXTURE_HANGING_COLLECTOR"
    elif [[ "$FIXTURE_COLLECTOR_MODE" == stopped ]]; then
      command "$FIXTURE_PYTHON" "$@"
    else
      printf 'GOSI_FIXTURE_COLLECTION_DEADLINE=%s\n' "$DAISO_GOSI_DEADLINE_MONOTONIC"
      return 0
    fi
  else
    printf 'Unexpected Python command: %s\n' "$*" >&2
    return 97
  fi
}
playwright() {
  printf 'browser-install\n' >> "$FIXTURE_CALLS"
  if [[ "$FIXTURE_HANG_PHASE" == chromium_install ]]; then sleep 30; fi
  if [[ "$FIXTURE_HANG_PHASE" == chromium_descendant ]]; then command "$FIXTURE_PYTHON" -c "$FIXTURE_STUCK_DESCENDANT"; fi
  return "$FIXTURE_BROWSER_CODE"
}
export -f python playwright
'''
        clock_environment = {}
        if deadline is None:
            # Ordinary outcome assertions must not compete with Python imports
            # for a subsecond deadline. Only the selected hanging phase gets a
            # short *real* timeout; all earlier setup gets ample probe budget.
            deadline = 1030.0
            phases = dict.fromkeys(("access_precheck", "pip_install",
                                    "chromium_install", "collection"), 1000.0)
            timed_phase = ("pip_install" if hang_phase.startswith("pip") else
                           "chromium_install" if hang_phase.startswith("chromium") else
                           "collection" if collector_mode == "hung_worker" else None)
            if timed_phase:
                phases[timed_phase] = deadline - 0.6
            with self.workflow_clock(1000, **phases):
                clock_environment = {key: os.environ[key] for key in
                                     ("FIXTURE_WORKFLOW_CLOCK", "FIXTURE_CLOCK_PREFIX")}
        env = dict(os.environ, **clock_environment, RUNNER_TEMP=str(self.root), GOSI_GAP_COUNT=count,
                   RELEASE_EXECUTION_ID="gosi-fixture:1", FIXTURE_PYTHON=sys.executable,
                   FIXTURE_REPO=str(ROOT), FIXTURE_CALLS=str(self.calls),
                   FIXTURE_PIP_CODE=str(pip_code), FIXTURE_BROWSER_CODE=str(browser_code),
                   FIXTURE_COLLECTOR_MODE=collector_mode,
                   FIXTURE_HANG_PHASE=hang_phase, FIXTURE_PIP_DELAY=pip_delay,
                   FIXTURE_DESCENDANT_PID=str(self.root/'installer-child.json'),
                   FIXTURE_STUCK_DESCENDANT="\n".join((
                       "import json,os,signal,time",
                       "from pathlib import Path",
                       "pid=os.fork()",
                       "if pid==0:",
                       "    signal.signal(signal.SIGTERM,signal.SIG_IGN)",
                       "    stat=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()",
                       "    Path(os.environ['FIXTURE_DESCENDANT_PID']).write_text(json.dumps({'pid':os.getpid(),'start':stat[19]}))",
                       "    while True: time.sleep(1)",
                       "signal.signal(signal.SIGTERM,signal.SIG_DFL)",
                       "while True: time.sleep(1)",
                   )),
                   # Translate the shell probe's remaining fixture budget to
                   # a real supervisor deadline at collector entry. The runtime
                   # and its child keep their actual monotonic clocks/signals.
                   FIXTURE_HANGING_COLLECTOR="from pathlib import Path; import os,sys,time; from scripts.daiso.gosi_collection_runtime import run_supervised; remaining=float(os.environ['DAISO_GOSI_DEADLINE_MONOTONIC'])-float(Path(os.environ['FIXTURE_WORKFLOW_CLOCK']).read_text()); result=run_supervised([sys.executable, '-c', \"from pathlib import Path; import time; Path('hung-worker-started').write_text('started'); time.sleep(30)\"], journal_dir=Path(os.environ['RUNNER_TEMP'])/'hang-journal', baseline_bytes=Path('data/gosi.json').read_bytes(), deadline=time.monotonic()+remaining, cleanup_seconds=float(os.environ['DAISO_GOSI_CLEANUP_SECONDS']), on_event=lambda event: None); raise SystemExit(result['exit_code'])",
                   GOSI_STAGE_BUDGET_SECONDS="30", GOSI_STAGE_CLEANUP_SECONDS="0.1",
                   GOSI_CONTINUITY_OUTCOME=continuity,
                   DAISO_GOSI_DEADLINE_MONOTONIC=str(deadline),
                   **self.actions_env)
        return subprocess.run([self.bash, "--noprofile", "--norc", "-e", "-o", "pipefail",
                               "-c", script + self.stage["run"]], cwd=self.root,
                              env=env, capture_output=True, text=True, timeout=30)

    def run_restore(self, mode, *, budget="0.6", delay="0"):
        restore = next(s for s in self.steps if s.get("id") == "gosi_safety")
        binary = self.root / "bin"
        binary.mkdir(exist_ok=True)
        fixture = binary / "python"
        fixture.write_text("#!" + sys.executable + "\n" + "\n".join((
            "import os,sys,time",
            "from pathlib import Path",
            "if sys.argv[1] == '-c': os.execv(sys.executable, [sys.executable, '-c', os.environ.get('FIXTURE_CLOCK_PREFIX', '') + sys.argv[2], *sys.argv[3:]])",
            "assert sys.argv[1:4] == ['-u','scripts/gosi_safety_checkpoint.py','restore']",
            "pending=Path('.gosi-safety-restore.pending'); pending.write_text('fixture pending')",
            "if os.environ.get('FIXTURE_WORKFLOW_CLOCK'):",
            "    clock=Path(os.environ['FIXTURE_WORKFLOW_CLOCK'])",
            "    clock.write_text(str(float(clock.read_text())+float(os.environ['FIXTURE_RESTORE_DELAY'])))",
            "else: time.sleep(float(os.environ['FIXTURE_RESTORE_DELAY']))",
            "if os.environ['FIXTURE_RESTORE_MODE']=='hang': time.sleep(30)",
            "pending.unlink()",
        )))
        fixture.chmod(0o700)
        output = self.root / "github-env"
        environment = dict(os.environ, PATH=str(binary)+os.pathsep+os.environ['PATH'],
            GITHUB_ENV=str(output), **self.actions_env,
            GOSI_STAGE_BUDGET_SECONDS=budget, GOSI_STAGE_CLEANUP_SECONDS="0.1",
            FIXTURE_RESTORE_MODE=mode, FIXTURE_RESTORE_DELAY=delay)
        process = subprocess.run([self.bash, "-e", "-o", "pipefail", "-c", restore["run"]],
            cwd=self.root, env=environment, text=True, capture_output=True, timeout=5)
        cutoff = float(output.read_text().strip().split("=",1)[1])
        return process, cutoff

    def test_hanging_restore_keeps_pending_and_records_optional_failure(self):
        started = time.monotonic()
        # Freeze only restore's arithmetic probes; its pending marker and GNU
        # TERM timeout remain real, without losing budget to probe startup.
        with self.workflow_clock(1000):
            restored, _ = self.run_restore("hang")
        self.assertEqual(restored.returncode, 124, restored.stderr)
        self.assertLess(time.monotonic()-started, 1.5)
        self.assertTrue((self.root/'.gosi-safety-restore.pending').exists())
        self.assertEqual(self.run_stage(continuity="failure").returncode, 2)
        self.assertEqual(self.recorded()["status"], "failed")
        self.assertFalse(self.calls.exists())
        self.assertEqual(self.source.read_bytes(), self.before)

    def workflow_clock(self, now, **phase_times):
        """Control only the shell's Python clock probes, never timeout/children.

        Restore advances the shared clock in its fixture process. Subsequent
        probes model time spent between phases without charging Python startup
        and host scheduling against a subsecond arithmetic assertion.
        """
        clock = self.root / "workflow-clock"
        clock.write_text(str(now))
        prefix = ("import os,time; from pathlib import Path; "
                  f"_clock=Path({str(clock)!r}); _phases={phase_times!r}; "
                  "_phase=os.environ.get('GOSI_PHASE');\n"
                  "if _phase in _phases: _clock.write_text(str(_phases[_phase]))\n"
                  "time.monotonic=lambda: float(_clock.read_text());\n")
        return patch.dict(os.environ, FIXTURE_WORKFLOW_CLOCK=str(clock),
                          FIXTURE_CLOCK_PREFIX=prefix)

    def test_restore_time_consumes_same_setup_collection_budget(self):
        with self.workflow_clock(1000, access_precheck=1400, pip_install=1500,
                                 chromium_install=1600, collection=1750):
            restored, cutoff = self.run_restore("success", budget="800", delay="400")
            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertEqual(cutoff, 1800)
            process = self.run_stage(source_stopped=False, collector_mode="success", deadline=cutoff)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        remaining = [(phase, float(value)) for phase, value in re.findall(
            r"GOSI_PHASE_START phase=(\w+) .*remaining_seconds=([0-9.]+)", process.stdout)]
        self.assertEqual(remaining, [("access_precheck", 399.9), ("pip_install", 299.9),
                                     ("chromium_install", 199.9), ("collection", 50.0)])
        self.assertIn("GOSI_FIXTURE_COLLECTION_DEADLINE=1800.0", process.stdout)
        self.assertEqual(self.calls.read_text().splitlines(),
                         ["access-check", "pip", "browser-install", "collector"])
        self.assertEqual(self.recorded()["status"], "success")
        self.assertIsNone(self.recorded()["last_successful_fetch_at"])
        self.assertEqual(self.source.read_bytes(), self.before)

    def test_expired_shared_deadline_prevents_setup_or_collection(self):
        phases = ("access_precheck", "pip_install", "chromium_install", "collection")
        calls = ["access-check", "pip", "browser-install", "collector"]
        for index, expired in enumerate(phases):
            with self.subTest(expired=expired):
                self.calls.unlink(missing_ok=True)
                (self.root / "github-env").unlink(missing_ok=True)
                times = {phase: 1400 + i * 100 if i < index else 1800
                         for i, phase in enumerate(phases)}
                with self.workflow_clock(1000, **times):
                    restored, cutoff = self.run_restore("success", budget="800", delay="400")
                    self.assertEqual(restored.returncode, 0, restored.stderr)
                    self.assertEqual(cutoff, 1800)
                    process = self.run_stage(source_stopped=False, collector_mode="success", deadline=cutoff)
                # An expired budget is rejected before the next child starts;
                # it is exactly 124, distinct from a running group killed (137).
                self.assertEqual(process.returncode, 124, process.stdout + process.stderr)
                self.assertNotIn(f"GOSI_PHASE_START phase={expired}", process.stdout)
                observed = self.calls.read_text().splitlines() if self.calls.exists() else []
                self.assertEqual(observed, calls[:index])
                row = self.recorded()
                self.assertEqual(row["status"], "failed")
                self.assertEqual(row["process_exit_code"], 124)
                self.assertEqual(row["wrapper_exit_code"], 124)
                self.assertIsNone(row["last_successful_fetch_at"])
                self.assertEqual(self.source.read_bytes(), self.before)

    def test_restored_budget_reaches_real_setup_timeout(self):
        # Only clock arithmetic is controlled. GNU timeout, its dedicated Bash
        # process group, TERM/KILL handling and result recorder are all real.
        # Give the real continuity precheck ample time, then exactly 1 second
        # of setup time plus its unchanged 0.1-second cleanup reserve.
        with self.workflow_clock(1000, access_precheck=1400, pip_install=1798.9):
            restored, cutoff = self.run_restore("success", budget="800", delay="400")
            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertEqual(cutoff, 1800)
            process = self.run_stage(source_stopped=False, hang_phase="pip_install", deadline=cutoff)
        self.assertEqual(process.returncode, 137, process.stdout + process.stderr)
        self.assertEqual(self.calls.read_text().splitlines(), ["access-check", "pip"])
        budget = re.search(r"phase=pip_install .*remaining_seconds=([0-9.]+)", process.stdout)
        self.assertIsNotNone(budget, process.stdout)
        self.assertAlmostEqual(float(budget[1]), 1)
        row = self.recorded()
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["process_exit_code"], 137)
        self.assertEqual(row["wrapper_exit_code"], 137)
        self.assertIsNone(row["last_successful_fetch_at"])
        self.assertEqual(self.source.read_bytes(), self.before)

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

    def test_restore_failure_is_recorded_without_source_and_required_gates_run(self):
        for outcome in ("failure", "cancelled", "skipped", ""):
            with self.subTest(outcome=outcome):
                process = self.run_stage(continuity=outcome)
                self.assertEqual(process.returncode, 2, process.stderr)
                self.assertIn("GOSI_CONTINUITY_UNVERIFIED", process.stderr)
                self.assertFalse(self.calls.exists())
                self.assertEqual(self.source.read_bytes(), self.before)
                self.assertEqual(self.recorded()["status"], "failed")
                self.assertIsNone(self.recorded()["last_successful_fetch_at"])
                self.assertEqual(self.independent_required_stage(), 0)
                self.assertEqual(self.aggregate(), 0)
                self.assertEqual(json.loads(self.report.read_text())["status"], "degraded")
                self.assertEqual(self.independent_required_stage(code=7), 7)
                self.assertEqual(self.aggregate(), 1)
                self.assertFalse(json.loads(self.report.read_text())["publish_allowed"])

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

    def test_hanging_setup_is_bounded_and_records_truthful_optional_failure(self):
        import time
        for phase, calls in (("pip_install", ["access-check", "pip"]),
                             ("chromium_install", ["access-check", "pip", "browser-install"])):
            with self.subTest(phase=phase):
                self.calls.unlink(missing_ok=True)
                started = time.monotonic()
                process = self.run_stage(source_stopped=False, hang_phase=phase)
                self.assertLess(time.monotonic() - started, 10)
                self.assertEqual(process.returncode, 137, process.stdout + process.stderr)
                self.assertEqual(self.calls.read_text().splitlines(), calls)
                self.assertIn(f"GOSI_PHASE_START phase={phase}", process.stdout)
                self.assertIn(f"GOSI_PHASE_END phase={phase}", process.stdout)
                self.assertIn("exit_code=137", process.stdout)
                self.assertNotIn("GOSI_PHASE_START phase=collection", process.stdout)
                row = self.recorded()
                self.assertEqual(row["status"], "failed")
                self.assertEqual(row["process_exit_code"], 137)
                self.assertEqual(row["wrapper_exit_code"], 137)
                self.assertEqual(row["error_code"], "process_exit_137")
                self.assertIsNone(row["last_successful_fetch_at"])
                self.assertTrue(row["using_cached_data"])
                self.assertEqual(self.source.read_bytes(), self.before)
                self.assertEqual(self.independent_required_stage(), 0)
                self.assertEqual(self.aggregate(), 0)
                self.assertEqual(json.loads(self.report.read_text())["status"], "degraded")
                self.assertEqual(self.independent_required_stage(code=7), 7)
                self.assertEqual(self.aggregate(), 1)
                self.assertFalse(json.loads(self.report.read_text())["publish_allowed"])

    def test_phase_progress_separates_setup_and_collection(self):
        process = self.run_stage(collector_mode="success", source_stopped=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        for phase in ("pip_install", "chromium_install", "collection"):
            self.assertIn(f"GOSI_PHASE_START phase={phase}", process.stdout)
            self.assertIn(f"GOSI_PHASE_END phase={phase}", process.stdout)
        self.assertIn("phase=collection elapsed_seconds=", process.stdout)
        self.assertIn("remaining_seconds=", process.stdout)
        self.assertNotIn("budget_seconds=none", process.stdout)

    def test_setup_and_collection_consume_one_deadline(self):
        import re
        # Account for phase time deterministically while the final browser
        # fixture still hangs under the real GNU timeout/process-group wrapper.
        with self.workflow_clock(1000, access_precheck=1000, pip_install=1000.15,
                                 chromium_install=1000.30):
            process = self.run_stage(source_stopped=False, hang_phase="chromium_install",
                                     deadline=1000.9)
        self.assertEqual(process.returncode, 137, process.stdout + process.stderr)
        values = [float(x) for x in re.findall(r"remaining_seconds=([0-9.]+)", process.stdout)]
        self.assertEqual(len(values), 3)
        self.assertGreater(values[0], values[1])
        self.assertGreater(values[1] - values[2], 0.1)
        for actual, expected in zip(values, (0.8, 0.65, 0.5)):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(self.calls.read_text().splitlines(), ["access-check", "pip", "browser-install"])

    def test_term_ignoring_setup_still_records_kill_failure(self):
        import time
        started = time.monotonic()
        process = self.run_stage(source_stopped=False, hang_phase="pip_ignore_term")
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(process.returncode, 137, process.stdout + process.stderr)
        self.assertEqual(self.recorded()["process_exit_code"], 137)
        self.assertEqual(self.recorded()["status"], "failed")
        self.assertEqual(self.source.read_bytes(), self.before)

    @unittest.skipUnless(sys.platform=='linux','process-group fixture needs Linux /proc')
    def test_term_ignoring_installer_descendant_is_killed_after_leader_exits(self):
        from scripts.daiso.gosi_collection_runtime import _ProcessTree
        for phase in ('pip_descendant','chromium_descendant'):
            with self.subTest(phase=phase):
                self.calls.unlink(missing_ok=True)
                pidfile=self.root/'installer-child.json'
                pidfile.unlink(missing_ok=True)
                # Adopt/reap only this dedicated fixture's orphan after checking
                # that the workflow's own group KILL already stopped it.
                tree=_ProcessTree()
                try:
                    started=time.monotonic()
                    process=self.run_stage(source_stopped=False,hang_phase=phase)
                    self.assertLess(time.monotonic()-started,3)
                    self.assertEqual(process.returncode,137,process.stderr)
                    identity=json.loads(pidfile.read_bytes())
                    status=Path(f"/proc/{identity['pid']}/stat")
                    if status.exists():
                        fields=status.read_text().rsplit(')',1)[1].split()
                        self.assertTrue(fields[19]!=identity['start'] or fields[0]=='Z',
                                        'installer descendant survived its timeout group')
                    self.assertEqual(self.recorded()['process_exit_code'],137)
                    self.assertEqual(self.recorded()['status'],'failed')
                    self.assertNotIn('collector',self.calls.read_text().splitlines())
                    self.assertEqual(self.source.read_bytes(),self.before)
                    self.assertEqual(self.independent_required_stage(),0)
                    self.assertEqual(self.aggregate(),0)
                    self.assertEqual(self.independent_required_stage(code=7),7)
                    self.assertEqual(self.aggregate(),1)
                finally:
                    self.assertTrue(tree.cleanup(time.monotonic()+1))
                    tree.restore()

    def test_hanging_collector_keeps_result_recorder_alive(self):
        import time
        started = time.monotonic()
        process = self.run_stage(source_stopped=False, collector_mode="hung_worker")
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(process.returncode, 124, process.stdout + process.stderr)
        self.assertEqual(self.calls.read_text().splitlines(),
                         ["access-check", "pip", "browser-install", "collector"])
        self.assertEqual((self.root / 'hung-worker-started').read_text(), 'started')
        row = self.recorded()
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["process_exit_code"], 124)
        self.assertIsNone(row["last_successful_fetch_at"])
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(self.independent_required_stage(), 0)
        self.assertEqual(self.aggregate(), 0)
        self.assertEqual(json.loads(self.report.read_text())["status"], "degraded")
        self.assertEqual(self.independent_required_stage(code=9), 9)
        self.assertEqual(self.aggregate(), 1)

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
        self.assertEqual(observer["if"], "steps.continuity_mode.outputs.mode == 'normal' && (steps.source_safety.outputs.continuity == 'verified' && steps.gosi_recovery.outcome == 'success')")

    def test_hanging_pack_preserves_pending_journal_and_cannot_upload(self):
        pack = next(s for s in self.steps if s.get("id") == "gosi_checkpoint")
        marker = self.root/'.gosi-collection.pending'
        journal = self.root/'journal'
        journal.mkdir()
        stop = journal/'000001.json'
        marker.write_bytes(b'exact pending marker')
        stop.write_bytes(b'exact durable STOP event')
        binary=self.root/'bin';binary.mkdir()
        executable=binary/'python'
        # This is a TERM-ignoring pack fixture, not a Python-startup test.
        # Install its trap before writing the partial artifact or spawning sleep.
        executable.write_text("#!"+self.bash+"\n"+"\n".join((
            'trap "" TERM',
            'printf %s "incomplete fixture ZIP" > "$RUNNER_TEMP/gosi-safety.zip"',
            'sleep 30',
        )))
        executable.chmod(0o700)
        environment=dict(os.environ,PATH=str(binary)+os.pathsep+os.environ['PATH'],
            GITHUB_WORKSPACE=str(self.root),RUNNER_TEMP=str(self.root),
            GITHUB_REPOSITORY='fixture/repository',GITHUB_RUN_ID='1',GITHUB_RUN_ATTEMPT='1',
            GITHUB_SHA='a'*40,GOSI_PACK_BUDGET_SECONDS='0.2',GOSI_PACK_KILL_SECONDS='0.05')
        started=time.monotonic()
        result=subprocess.run([self.bash,'-e','-c',pack['run']],cwd=self.root,
            env=environment,text=True,capture_output=True,timeout=3)
        # Bash may exec its final timeout command, exposing SIGKILL directly;
        # a remaining shell reports the equivalent conventional 128+9 code.
        self.assertIn(result.returncode,(-9,137),result.stderr)
        self.assertLess(time.monotonic()-started,1.5)
        self.assertEqual((self.root/'gosi-safety.zip').read_bytes(), b'incomplete fixture ZIP')
        self.assertEqual(marker.read_bytes(),b'exact pending marker')
        self.assertEqual(stop.read_bytes(),b'exact durable STOP event')
        self.assertEqual(self.source.read_bytes(),self.before)
        upload=next(s for s in self.steps if s.get('name')=='Upload GOSI safety checkpoint')
        self.assertEqual(upload['if'],"steps.continuity_mode.outputs.mode == 'normal' && (always() && steps.gosi_checkpoint.outcome == 'success')")
        self.assertEqual(pack['timeout-minutes'],2)
        self.assertEqual(upload['timeout-minutes'],2)

    def test_single_stage_budget_and_cross_run_preservation_contract(self):
        self.assertEqual(self.stage["env"]["GOSI_STAGE_BUDGET_SECONDS"], "1200")
        self.assertEqual(self.stage["env"]["GOSI_STAGE_CLEANUP_SECONDS"], "20")
        self.assertEqual(self.stage["env"]["DAISO_GOSI_MAX"], "12")
        self.assertNotIn("time.monotonic()+b", self.stage["run"])
        self.assertNotIn("timeout-minutes", self.stage)
        restore = next(s for s in self.steps if s.get("id") == "gosi_safety")
        pack = next(s for s in self.steps if s.get("id") == "gosi_checkpoint")
        upload = next(s for s in self.steps if s.get("name") == "Upload GOSI safety checkpoint")
        self.assertLess(self.steps.index(restore), self.steps.index(self.stage))
        self.assertTrue(restore["continue-on-error"])
        self.assertEqual(restore["run"].count("time.monotonic()+b"), 1)
        self.assertIn('>> "$GITHUB_ENV"', restore["run"])
        self.assertIn("timeout --signal=TERM", restore["run"])
        self.assertEqual(self.stage["env"]["GOSI_CONTINUITY_OUTCOME"], "${{ steps.gosi_safety.outcome }}")
        self.assertEqual(restore["env"]["GITHUB_TOKEN"], "${{ github.token }}")
        self.assertIn("gosi_safety_checkpoint.py restore", restore["run"])
        self.assertEqual(self.steps.index(pack), self.steps.index(self.stage) + 1)
        self.assertEqual(pack["if"], "steps.continuity_mode.outputs.mode == 'normal' && (always())")
        self.assertEqual(pack["timeout-minutes"], 2)
        self.assertEqual(upload["timeout-minutes"], 2)
        self.assertEqual(pack["env"]["GOSI_PACK_BUDGET_SECONDS"], "110")
        self.assertEqual(pack["env"]["GOSI_PACK_KILL_SECONDS"], "5")
        self.assertIn("gosi_safety_checkpoint.py pack", pack["run"])
        self.assertIn("steps.gosi_checkpoint.outcome == 'success'", upload["if"])
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        self.assertEqual(upload["with"]["name"], "gosi-safety-${{ github.run_id }}-${{ github.run_attempt }}")
        preflight = (ROOT / ".github/workflows/preflight.yml").read_text()
        self.assertIn("python -B scripts/test_gosi_alt_runtime.py", preflight)
        self.assertIn("python -B scripts/test_gosi_safety_checkpoint.py", preflight)

    def test_restricted_and_blocked_modes_cannot_upload_normal_safety_prefixes(self):
        import re
        import ast
        def allowed(expression, mode, checkpoint='success'):
            values = {'steps.continuity_mode.outputs.mode': mode,
                      'steps.gosi_checkpoint.outcome': checkpoint}
            def value(match):
                key = match.group(0)
                return repr(values.get(key, 'verified' if 'continuity' in key else 'success'))
            expression = re.sub(r'steps\.[A-Za-z0-9_]+\.(?:outputs\.[A-Za-z0-9_]+|outcome)', value, expression)
            expression = expression.replace('always()', 'True').replace('success()', 'True')
            expression = expression.replace('&&', ' and ').replace('||', ' or ')
            syntax = ast.parse(expression, mode='eval')
            self.assertTrue(all(isinstance(node, (ast.Expression, ast.BoolOp, ast.And, ast.Or,
                ast.Compare, ast.Eq, ast.NotEq, ast.Constant)) for node in ast.walk(syntax)))
            return eval(compile(syntax, '<fixed-workflow-condition>', 'eval'), {'__builtins__': {}})
        prefixes = ('gosi-safety-', 'source-safety-', 'operations-safety-', 'typesafe-budget-receipt-')
        seen = set()
        for filename in ('JARVIS-Core-Automation.yml', 'JARVIS-Deep-Analysis.yml'):
            document = yaml.safe_load((ROOT / '.github/workflows' / filename).read_text())
            for job in document['jobs'].values():
                for step in job['steps']:
                    if 'upload-artifact@' not in step.get('uses', ''):
                        continue
                    name = step['with']['name']
                    if not name.startswith(prefixes):
                        continue
                    seen.add(next(prefix for prefix in prefixes if name.startswith(prefix)))
                    condition = step['if']
                    self.assertIn('always()', condition)
                    for mode in ('normal', 'restricted_gap', 'blocked', ''):
                        with self.subTest(workflow=filename, artifact=name, mode=mode):
                            self.assertEqual(allowed(condition, mode), mode == 'normal')
                    if name.startswith('gosi-safety-'):
                        self.assertFalse(allowed(condition, 'normal', checkpoint='failure'))
        self.assertEqual(seen, set(prefixes))

    def test_workflow_contract_preserves_required_gates_and_standalone_failure(self):
        self.assertTrue(self.stage["continue-on-error"])
        self.assertEqual(self.stage["if"], "steps.continuity_mode.outputs.mode == 'normal'")  # Normal no-gap runs still leave evidence.
        self.assertEqual(self.stage["env"]["GOSI_GAP_COUNT"], "${{ steps.s_gosi_gap.outputs.count }}")
        self.assertIn("--artifact data/gosi.json", self.stage["run"])
        aggregate = next(s for s in self.steps if s.get("id") == "release_outcomes")
        self.assertIn("--expected deep_gosi_alt:optional", aggregate["run"])
        for name in ("deep_35", "deep_37", "deep_38", "deep_41", "deep_50", "deep_53", "deep_55"):
            self.assertIn(f"--expected {name}:required", aggregate["run"])
            stage = next(s for s in self.steps if f"--name {name} --required" in s.get("run", ""))
            self.assertFalse(stage.get("continue-on-error", False), name)
        publish = next(s for s in self.steps if s.get("uses") == "./.github/actions/publish")
        self.assertEqual(publish["if"], "steps.continuity_mode.outputs.mode == 'normal' && (success() && steps.release_outcomes.outcome == 'success' && steps.release_quality.outcome == 'success')")
        self.assertEqual(publish["with"]["collector-report"], "data/agents/deep_run_results.json")
        standalone = yaml.safe_load((ROOT / ".github/workflows/gosi-alt.yml").read_text())
        collection = next(s for s in standalone["jobs"]["collect"]["steps"]
                          if "python -u scripts/daiso/collect_gosi_alt.py" in s.get("run", ""))
        self.assertFalse(collection.get("continue-on-error", False))
        self.assertIn("python scripts/test_gosi_recovery_workflow.py",
                      (ROOT / ".github/workflows/preflight.yml").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
