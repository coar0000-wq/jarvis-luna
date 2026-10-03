#!/usr/bin/env python3
"""Offline integration regressions. Only isolated fixture trees are written.

Run: python scripts/test_operational_integration.py
No credentials, models, collectors, real data edits, or network are used.
Git is used only for local fixture HEAD restoration, never for the source repo.
"""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import operational_freshness as freshness
import health_check_v2 as health
import generate_dashboard_runtime as rt
import collect_workflow_status as monitor
import validate_commerce_architecture as architecture

UTC = timezone.utc
NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)
OLD = (NOW - timedelta(days=10)).isoformat()
FRESH = (NOW - timedelta(minutes=20)).isoformat()
FUTURE = (NOW + timedelta(hours=1)).isoformat()
DAISO = REPO / ".github" / "workflows" / "daiso-real-collection.yml"


def steps_from_workflow(text):
    """Read the observed workflow's fixed step indentation, without PyYAML."""
    starts = list(re.finditer(r"^      - name: (.+)$", text, re.M))
    return {m.group(1): text[m.end():starts[i + 1].start() if i + 1 < len(starts) else len(text)]
            for i, m in enumerate(starts)}


def record(status="ok", at=OLD, ok=1):
    return {"status": status, "finished_at": at, "ok": ok, "queue_size": 7}


def collection_doc():
    return {"last_attempt": record("no_change", FRESH, 0),
            "last_success": record(), "fx": {"usd_krw": 1300}}


class FixtureCase(unittest.TestCase):
    def setUp(self):
        # The only tempfile root is the working copy's parent tmp directory.
        self.temp = tempfile.TemporaryDirectory(prefix="ops-integration-", dir=REPO.parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        for obj, attr, value in [(health, "ROOT", self.root), (health, "DATA_DIR", self.data),
                                 (rt, "ROOT", self.root), (rt, "OUT", self.data / "dashboard_runtime.json"),
                                 (rt, "VAULT", self.root / "obsidian"), (rt, "KNOWLEDGE", self.data / "knowledge")]:
            p = patch.object(obj, attr, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(health, "now_utc", return_value=NOW)
        p.start()
        self.addCleanup(p.stop)
        # Inject the clock through the public pure assessments used by runtime.
        for name in ("assess_collection", "assess_heartbeat"):
            fn = getattr(freshness, name)
            p = patch.object(rt, name, side_effect=lambda doc, _fn=fn, **kw: _fn(doc, now=NOW, **kw))
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(rt, "age_channels", side_effect=lambda gcs, **kw: freshness.age_channels(gcs, now=NOW, **kw))
        p.start()
        self.addCleanup(p.stop)
        p = patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network forbidden"))
        p.start()
        self.addCleanup(p.stop)
        self.write("pricing_model.json", {"generated_at": FRESH})
        self.write("market_team.json", {"team": {"updated_at": FRESH}, "s_grade_priority": [{"canonical_product_id": "CP_FIXTURE"}], "keyword_board": [{"trend": 1}]})
        self.write("product_master.json", {"generated_at": FRESH, "products": [{"grade": "S", "canonical_product_id": "CP_FIXTURE"}], "pd_no_to_cp": {"fixture": "CP_FIXTURE"}})
        self.write("legal_full.json", {"generated_at": FRESH, "total": 1, "complete": 1, "blocked": 0, "items": {}})
        self.write("shopify_sync_guard.json", {"generated_at": FRESH, "ok": True, "summary": {}})
        self.write("gosi.json", {"updated_at": FRESH, "items": {}})
        self.write("daiso_real/shopify_demand_score.json", {"updated_at": FRESH, "scores": [], "grade_summary": {"S": 1}})
        self.write("daiso_real/products.json", {"updated_at": FRESH, "count": 1, "products": [{"pd_no": "fixture"}]})
        self.write("daiso_real/collection_status.json", collection_doc())
        self.write("agents/autofix_report.json", {"generated_at": FRESH, "status": "ok"})

    def write(self, relative, doc):
        target = self.data / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
        return target

    def dashboard(self):
        with redirect_stdout(io.StringIO()):
            return health.build_dashboard()

    def check(self, team):
        return next(c for c in health.check_all() if c["team"] == team)

    def snapshot(self, at=FRESH, failed=1):
        doc = {"observed_at": at, "status": "failed" if failed else "success", "failed_actions": failed,
               "checked_workflows": 5, "total_workflows": 5, "workflows": {
                   "JARVIS-Deep-Analysis.yml": {"status": "failed" if failed else "success", "last_success_at": OLD, "reason": "latest_failure"}}}
        self.write("agents/workflow_freshness.json", doc)
        return doc

    def test_missing_health_timestamp_is_unknown(self):
        self.assertEqual(health.freshness_str(None), "unknown")
        self.assertEqual(health.freshness_str("invalid"), "unknown")

    def test_future_health_timestamp_is_unknown(self):
        self.assertEqual(health.freshness_str(FUTURE), "unknown")

    def test_naive_health_timestamp_is_utc(self):
        self.assertEqual(health.parse_iso("2026-10-03T11:00:00"), NOW - timedelta(hours=1))
        self.assertEqual(health.hours_since("2026-10-03T11:00:00"), 1)

    def test_products_mtime_and_updated_at_do_not_prove_collection(self):
        (self.data / "daiso_real/collection_status.json").unlink()
        product = self.data / "daiso_real/products.json"
        os.utime(product, (NOW.timestamp(), NOW.timestamp()))
        check = self.check("daiso")
        self.assertIsNone(check["last_success_at"])
        self.assertIsNone(self.dashboard()["kpi"]["last_success"])
        self.assertNotEqual(check["status"], "success")

    def test_fresh_no_change_preserves_old_success(self):
        check = self.check("daiso")
        self.assertEqual(check["status"], "warning")
        self.assertEqual(check["last_attempt_at"], FRESH)
        self.assertEqual(check["last_success_at"], OLD)
        self.assertFalse(check["attempt_stale"])
        self.assertTrue(check["data_stale"])

    def test_kpi_falls_back_to_actual_collection_success(self):
        result = self.dashboard()
        self.assertEqual(result["kpi"]["last_success"], OLD)
        self.assertNotEqual(result["kpi"]["last_success"], result["generated_at"])

    def test_kpi_uses_real_workflow_success_not_generation(self):
        self.snapshot(failed=0)
        result = self.dashboard()
        self.assertEqual(result["kpi"]["last_success"], OLD)
        self.assertEqual(result["kpi"]["last_success_source"], "github_actions_snapshot")
        self.assertNotEqual(result["kpi"]["last_success"], result["generated_at"])

    def test_failed_jobs_unknown_without_workflow_observation(self):
        self.assertEqual(self.dashboard()["kpi"]["failed_jobs"], "unknown")

    def test_failed_jobs_unknown_after_observation_hold(self):
        self.snapshot(at=(NOW - timedelta(hours=4.6)).isoformat())
        self.assertEqual(self.dashboard()["kpi"]["failed_jobs"], "unknown")

    def test_failed_jobs_unknown_for_future_observation(self):
        self.snapshot(at=FUTURE)
        self.assertEqual(self.dashboard()["kpi"]["failed_jobs"], "unknown")

    def test_actual_one_failed_action_is_one_and_checks_are_separate(self):
        self.snapshot(failed=1)
        self.write("shopify_sync_guard.json", {"ok": False})
        result = self.dashboard()
        self.assertEqual(result["kpi"]["failed_jobs"], 1)
        self.assertGreaterEqual(result["kpi"]["failed_checks"], 2)

    def test_health_and_runtime_leave_source_json_bytes_unchanged(self):
        before = {p: p.read_bytes() for p in self.data.rglob("*.json")}
        self.dashboard()
        rt.secretary_card()
        for p, original in before.items():
            self.assertEqual(p.read_bytes(), original, str(p))

    def test_runtime_age_overlay_is_idempotent(self):
        source = {"fixture": {"status": "ok", "trust": "verified", "collected_at": OLD, "reason": "fixture only"}}
        original = deepcopy(source)
        once = rt.age_channel_status(source)
        self.assertEqual(once, rt.age_channel_status(once))
        self.assertEqual(source, original)
        self.assertEqual(once["fixture"]["status"], "stale")

    def test_runtime_missing_capture_is_unverified(self):
        source = {"fixture": {"status": "ok", "trust": "verified"}}
        result = rt.age_channel_status(source)["fixture"]
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["trust"], "unverified")
        self.assertIsNone(result["age_hours"])

    def test_secretary_when_is_actual_autofix_time(self):
        self.assertEqual(rt.secretary_card()["when"], FRESH)

    def test_secretary_missing_heartbeat_when_is_none(self):
        (self.data / "agents/autofix_report.json").unlink()
        self.assertIsNone(rt.secretary_card()["when"])

    def test_old_failed_heartbeat_remains_failed(self):
        self.write("agents/autofix_report.json", {"generated_at": OLD, "status": "failed"})
        self.assertEqual(rt.secretary_card()["status"], "failed")
        self.assertEqual(self.check("deep_heartbeat")["status"], "failed")

    def test_fresh_deep_workflow_failure_is_failed(self):
        doc = self.snapshot()
        with patch.object(rt, "workflow_snapshot", return_value=(doc, True)):
            self.assertEqual(rt.secretary_card()["status"], "failed")

    def test_no_change_not_claimed_as_new_product_success(self):
        check = self.check("daiso")
        self.assertTrue(check["is_no_change"])
        self.assertIn("새 상품 없음", check["reason"])
        self.assertNotIn("새 상품 있음", check["reason"])
        self.assertNotEqual(check["status"], "success")


class SourcingValidationTests(unittest.TestCase):
    def card(self, *, no_change=False, stale=False, failure=False, action=None):
        return {"notice": "실제 시도 통계", "action": action,
                "status": "failed" if failure else "warning" if no_change or stale else "ok",
                "collection_freshness": {"is_no_change": no_change, "attempt_stale": stale,
                                         "data_stale": stale, "is_failure": failure}}

    def test_fresh_success_statistics_cannot_become_an_action(self):
        architecture.validate_sourcing_card(self.card())
        with self.assertRaises(AssertionError):
            architecture.validate_sourcing_card(self.card(action="110건 받아 봄"))

    def test_no_change_is_warning_notice_not_new_success(self):
        card = self.card(no_change=True)
        architecture.validate_sourcing_card(card)
        card["status"] = "ok"
        with self.assertRaises(AssertionError):
            architecture.validate_sourcing_card(card)

    def test_real_stale_or_failed_evidence_requires_action(self):
        for key in ("stale", "failure"):
            with self.subTest(key=key):
                card = self.card(**{key: True}, action="실제 최신성/실패 재검증")
                architecture.validate_sourcing_card(card)
                card["action"] = None
                with self.assertRaises(AssertionError):
                    architecture.validate_sourcing_card(card)

    def test_failure_cannot_be_hidden_as_warning(self):
        card = self.card(failure=True, action="실패 확인")
        card["status"] = "warning"
        with self.assertRaises(AssertionError):
            architecture.validate_sourcing_card(card)

    def test_observed_actions_failure_is_evidenced_action(self):
        architecture.validate_sourcing_card(self.card(action="관측 실패 확인"), observed_workflow_failure=True)

    def test_missing_boolean_evidence_or_notice_is_blocked(self):
        for key in ("is_failure", "attempt_stale", "data_stale", "is_no_change"):
            card = self.card()
            del card["collection_freshness"][key]
            with self.assertRaises(AssertionError):
                architecture.validate_sourcing_card(card)
        card = self.card()
        card["notice"] = None
        with self.assertRaises(AssertionError):
            architecture.validate_sourcing_card(card)


class PureAssessmentTests(unittest.TestCase):
    def test_naive_collection_and_now_are_utc(self):
        doc = {"last_attempt": record("ok", "2026-10-03T11:00:00"), "last_success": record("ok", "2026-10-03T11:00:00")}
        result = freshness.assess_collection(doc, now=NOW.replace(tzinfo=None))
        self.assertEqual(result["attempt_age_hours"], 1)
        self.assertEqual(result["last_success_at"], "2026-10-03T11:00:00+00:00")

    def test_future_collection_is_not_verified(self):
        result = freshness.assess_collection({"last_attempt": record(at=FUTURE), "last_success": record(at=FUTURE)}, now=NOW)
        self.assertIsNone(result["last_success_at"])
        self.assertIsNone(result["last_attempt_at"])
        self.assertNotEqual(result["status"], "success")

    def test_future_channel_is_unverified_without_mutation(self):
        doc = {"fixture": {"status": "ok", "trust": "verified", "collected_at": FUTURE}}
        before = deepcopy(doc)
        self.assertEqual(freshness.age_channels(doc, now=NOW)["fixture"]["status"], "unverified")
        self.assertEqual(doc, before)

    def test_failed_attempt_keeps_previous_success(self):
        result = freshness.assess_collection({"last_attempt": record("failed", FRESH, 0), "last_success": record()}, now=NOW)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["last_success_at"], OLD)

    def test_mocked_github_fetch_bounded_read_only(self):
        payload = {"workflow_runs": []}
        fetcher = Mock(return_value=payload)
        with patch.object(monitor, "_fetch_json", side_effect=AssertionError("real fetch forbidden")):
            result = monitor.collect_report("fixture/offline", now=NOW, fetch_json=fetcher)
        self.assertEqual(fetcher.call_count, 5)
        for call in fetcher.call_args_list:
            self.assertRegex(call.args[0], r"^https://api\.github\.com/repos/fixture/offline/actions/workflows/[^/]+/runs\?per_page=10&branch=main$")
        self.assertEqual(result["failed_actions"], "unknown")
        self.assertEqual(payload, {"workflow_runs": []})

    def test_actual_mock_snapshot_counts_one_failure(self):
        run = {"id": 1, "status": "completed", "conclusion": "success", "event": "schedule", "created_at": "2026-10-03T11:00:00Z", "run_started_at": "2026-10-03T11:01:00Z", "updated_at": "2026-10-03T11:10:00Z", "html_url": "https://github.com/fixture/offline/actions/runs/1"}
        payload = {name: {"workflow_runs": [deepcopy(run)]} for name in monitor.WORKFLOWS}
        payload["JARVIS-Deep-Analysis.yml"]["workflow_runs"][0]["conclusion"] = "failure"
        original = deepcopy(payload)
        result = monitor.build_report(payload, now=NOW)
        self.assertEqual(result["failed_actions"], 1)
        self.assertEqual(result["checked_workflows"], 5)
        self.assertEqual(result["workflows"]["JARVIS-Core-Automation.yml"]["last_success_at"], "2026-10-03T11:10:00Z")
        self.assertEqual(payload, original)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DAISO.read_text(encoding="utf-8")
        cls.steps = steps_from_workflow(cls.text)

    def test_product_score_prune_export_channels_collected_only(self):
        commands = ("prune_excluded_products.py", "build_product_master.py", "score_shopify_demand.py", "build_legal_full.py", "build_market_team.py", "export_shopify_operational.py", "build_shopify_action_queue.py", "discover_channels.py")
        for command in commands:
            matches = [(name, body) for name, body in self.steps.items() if command in body]
            self.assertTrue(matches, command)
            for name, body in matches:
                self.assertRegex(body, r"(?m)^        if: steps\.collection\.outputs\.mode == 'collected'\s*$", name)

    def test_no_change_publish_paths_are_narrow_metadata_only(self):
        publications = [body for body in self.steps.values() if "uses: ./.github/actions/publish" in body and "mode == 'no_change'" in body]
        self.assertEqual(len(publications), 1)
        paths = re.search(r"          paths: >-\n(.*?)\n          message:", publications[0], re.S).group(1).split()
        self.assertIn("data/daiso_real/collection_status.json", paths)
        self.assertIn("data/health_check.json", paths)
        self.assertNotIn("data/daiso_real", paths)
        for path in paths:
            self.assertFalse(any(x in path for x in ("products", "product_master", "shopify_demand_score", "shopify_exports", "beauty_queue")), path)

    def test_auxiliary_boolean_defaults_true_but_dispatch_can_disable(self):
        stanza = re.search(r"      refresh_auxiliary_sources:\n(.*?)(?=\n\S)", self.text, re.S).group(1)
        self.assertRegex(stanza, r"(?m)^        default: true$")
        self.assertRegex(stanza, r"(?m)^        type: boolean$")
        for name in ("환율 갱신 (USD/KRW)", "뷰티 URL 큐 만들기"):
            self.assertIn("if: github.event_name != 'workflow_dispatch' || inputs.refresh_auxiliary_sources", self.steps[name])
        # The expression leaves schedules enabled and dispatch false disabled.
        for event, flag, expected in (("schedule", False, True), ("workflow_dispatch", False, False), ("workflow_dispatch", True, True)):
            self.assertEqual(event != "workflow_dispatch" or flag, expected)

    def test_monitor_workflows_have_actions_read_permission(self):
        found = 0
        for path in (REPO / ".github/workflows").glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            if "scripts/collect_workflow_status.py" in text:
                found += 1
                permissions = re.search(r"(?m)^permissions:\n((?:[ \t].*\n|\n)+)", text)
                self.assertIsNotNone(permissions, path.name)
                self.assertRegex(permissions.group(1), r"(?m)^  actions: read\s*$", path.name)
        self.assertGreaterEqual(found, 3)

    def test_cadence_preserved_and_off_hour_distributed(self):
        frequencies = {"JARVIS-Core-Automation.yml": 12, "JARVIS-Deep-Analysis.yml": 12, "jarvis-real-knowledge.yml": 4, "daiso-real-collection.yml": 1, "root-collectors.yml": 1}
        minutes = []
        for name, expected in frequencies.items():
            text = (REPO / ".github/workflows" / name).read_text(encoding="utf-8")
            crons = re.findall(r"cron:\s*['\"]([^'\"]+)['\"]", text)
            self.assertEqual(len(crons), 1, name)
            minute, hour, day, month, weekday = crons[0].split()
            self.assertEqual((day, month, weekday), ("*", "*", "*"))
            self.assertTrue(minute.isdigit())
            minutes.append(int(minute))
            slots = set()
            for part in hour.split(","):
                base, _, stride = part.partition("/")
                step = int(stride or 1)
                if base == "*":
                    slots.update(range(0, 24, step))
                elif "-" in base:
                    start, end = map(int, base.split("-"))
                    slots.update(range(start, end + 1, step))
                else:
                    slots.add(int(base))
            self.assertEqual(len(slots), expected, name)
        self.assertTrue(all(0 < m < 60 for m in minutes))
        self.assertEqual(len(set(minutes)), len(minutes))

    def run_restore_fixture(self, tracked_queue=True, baseline_fx=True):
        body = self.steps["Keep canonical product inputs on no_change"]
        inline = re.search(r"          python - <<'PY'\n(.*?)\n          PY", body, re.S)
        self.assertIsNotNone(inline)
        code = textwrap.dedent(inline.group(1))
        # Isolated Git environment: no system/global config, no external hooks,
        # no credential paths, fixture-only identity, explicitly no signing.
        with tempfile.TemporaryDirectory(prefix="ops-git-fixture-", dir=REPO.parent) as directory:
            root = Path(directory)
            data = root / "data/daiso_real"
            data.mkdir(parents=True)
            hooks = root / "empty-hooks"
            hooks.mkdir()
            env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
            env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "Offline Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid", "GIT_COMMITTER_NAME": "Offline Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"})
            prefix = ["git", "-c", "core.hooksPath=" + str(hooks), "-c", "commit.gpgsign=false", "-c", "init.templateDir=" + str(hooks)]
            def git(*args):
                return subprocess.run(prefix + list(args), cwd=root, env=env, check=True, capture_output=True)
            git("init")
            baseline = collection_doc()
            if not baseline_fx:
                baseline.pop("fx")
            status = data / "collection_status.json"
            status.write_text(json.dumps(baseline), encoding="utf-8")
            products = data / "products.json"
            products.write_bytes(b'{"products":[{"fixture":true}]}\n')
            original_products = products.read_bytes()
            queue = data / "beauty_queue.json"
            original_queue = b'{"urls":["fixture://original"]}\n'
            if tracked_queue:
                queue.write_bytes(original_queue)
            git("add", ".")
            git("commit", "-m", "offline fixture only")
            current = deepcopy(baseline)
            current["last_attempt"] = record("no_change", FRESH, 0)
            current["last_attempt"]["execution_id"] = "fixture:new"
            current["last_success"] = record("ok", OLD, 8)
            current["fx"] = {"usd_krw": 9999}
            status.write_text(json.dumps(current), encoding="utf-8")
            queue.write_bytes(b'{"urls":["fixture://new"]}\n')
            # Execute the workflow's exact inline code, no hand-written replacement.
            with patch.dict(os.environ, env, clear=True):
                previous = Path.cwd()
                try:
                    os.chdir(root)
                    with redirect_stdout(io.StringIO()):
                        exec(compile(code, str(DAISO) + "::no_change", "exec"), {"__name__": "__main__"})
                finally:
                    os.chdir(previous)
            result = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(result["last_attempt"], current["last_attempt"])
            self.assertEqual(result["last_success"], current["last_success"])
            if baseline_fx:
                self.assertEqual(result["fx"], baseline["fx"])
            else:
                self.assertNotIn("fx", result)
            if tracked_queue:
                self.assertEqual(queue.read_bytes(), original_queue)
            else:
                self.assertFalse(queue.exists())
            self.assertEqual(products.read_bytes(), original_products)

    def test_inline_no_change_restores_head_fx_and_tracked_queue(self):
        self.run_restore_fixture()

    def test_inline_no_change_removes_new_untracked_queue(self):
        self.run_restore_fixture(tracked_queue=False)

    def test_inline_no_change_removes_fx_absent_from_head(self):
        self.run_restore_fixture(baseline_fx=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
