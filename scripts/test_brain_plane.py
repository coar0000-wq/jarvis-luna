"""Bounded, offline brain-plane regression tests.

Only OS-temporary fixtures are written. Git's exclusion query contract is mocked
against each fixture's .git/info/exclude: this suite NEVER invokes Git, production
CLI entrypoints, providers, publication, or public-site build(). This verifies the
adapter and its actual vault bytes, not real-Git behavior or whole-repo coverage.
Run with the installed Python 3.11 interpreter using -E -Xutf8 -B.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import brain_plane as plane
import obsidian_brain as brain
import beauty_category_teams as category
import build_public_site as public

SCRIPTS = Path(__file__).resolve().parent
SOURCE_TIME = "2020-01-02T03:04:05Z"
SCREEN_TIME = "2021-02-03T04:05:06Z"
EXCLUDE_RULE = "/obsidian/JARVIS_LUNA/BrainRuntime/\n"


class BrainPlaneTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="brain-plane-isolated-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write(".git/info/exclude", EXCLUDE_RULE.encode())
        # Real ordinary metadata bytes allow the production lease fingerprint to
        # run unchanged. Only Git's read-only query responses are simulated.
        self.gitdir = self.root / ".git"
        self.write(".git/HEAD", b"ref: refs/heads/fixture\n")
        self.write(".git/refs/heads/fixture", b"0" * 40 + b"\n")
        self.write(".git/config", b"[core]\n\trepositoryformatversion = 0\n\tbare = false\n")
        empty_index = b"DIRC" + (2).to_bytes(4, "big") + (0).to_bytes(4, "big")
        self.write(".git/index", empty_index + hashlib.sha1(empty_index).digest())
        self.git_calls = []
        self.tracked = False
        git = patch.object(brain, "_git", side_effect=self.fixture_git)
        git.start()
        self.addCleanup(git.stop)
        # A regression must not silently start Git, an actual CLI, or a provider.
        processes = patch.object(subprocess, "run", side_effect=AssertionError("subprocess forbidden in bounded suite"))
        processes.start()
        self.addCleanup(processes.stop)
        self.labels = dict(team="agents", task="fixture-analysis", operation="local-analysis")
        self.source = self.write_json("data/input.json", {"observed_at": SOURCE_TIME, "items": [1, 2]})

    def fixture_git(self, root, *args):
        self.assertEqual(Path(root), self.root, "all exclusion queries must stay in this fixture")
        self.git_calls.append(args)
        if args == ("rev-parse", "--show-toplevel"):
            return subprocess.CompletedProcess(args, 0, (str(self.root) + "\n").encode(), b"")
        if args == ("rev-parse", "--absolute-git-dir", "--path-format=absolute", "--git-common-dir"):
            location = str(self.gitdir.resolve()) + "\n"
            return subprocess.CompletedProcess(args, 0, (location + location).encode(), b"")
        if args == ("ls-files", "--", brain.BRAIN.as_posix()):
            return subprocess.CompletedProcess(args, 0, b"tracked-node.json\n" if self.tracked else b"", b"")
        probes = tuple(brain.BRAIN.as_posix() + suffix for suffix in (
            "/", "/payloads/00/probe.bin", "/nodes/00/probe.json", "/notes/00/probe.md"))
        if args in tuple(("check-ignore", "--no-index", "-q", "--", probe) for probe in probes):
            allowed = (self.root / ".git/info/exclude").read_text() == EXCLUDE_RULE
            return subprocess.CompletedProcess(args, 0 if allowed else 1, b"", b"")
        if args == ("check-ignore", "--no-index", "-v", "--", probes[0]):
            allowed = (self.root / ".git/info/exclude").read_text() == EXCLUDE_RULE
            verdict = ".git/info/exclude:1:" + EXCLUDE_RULE.rstrip("\n") + "\t" + probes[0] + "\n"
            return subprocess.CompletedProcess(args, 0 if allowed else 1,
                                               verdict.encode() if allowed else b"", b"")
        self.fail("unexpected Git query contract: " + repr(args))

    def write(self, relative, raw):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return target

    def write_json(self, relative, value):
        return self.write(relative, (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))

    def read_json(self, relative):
        return json.loads((self.root / relative).read_bytes())

    def nodes(self):
        return [json.loads(p.read_bytes()) for p in (self.root / brain.BRAIN / "nodes").glob("*/*.json")]

    def node(self, identifier):
        return self.read_json(brain.BRAIN / "nodes" / identifier[:2] / (identifier + ".json"))

    def payload_for(self, raw):
        digest = hashlib.sha256(raw).hexdigest()
        return self.root / brain.BRAIN / "payloads" / digest[:2] / (digest + ".bin")

    def workload(self):
        value = plane.read_json(self.source, self.root, {})
        result = self.write_json("data/result.json", {"count": len(value["items"]), "source_observed_at": value["observed_at"]})
        return plane.record(result, self.root)

    def test_supported_adapter_reads_verified_bytes_and_records_exact_lineage(self):
        original = self.source.read_bytes()
        mtime = self.source.stat().st_mtime_ns
        verified = brain._verified
        calls = []

        def verify(root, relative, digest):
            calls.append(Path(relative).as_posix())
            return verified(root, relative, digest)

        with patch.object(brain, "_verified", side_effect=verify), brain.execution(self.root, **self.labels) as run:
            proof = self.workload()
            self.assertTrue(proof["input_read_from_vault"])
            self.assertTrue(proof["output_stored"])
            self.assertFalse(proof["business_approval"])
            self.assertEqual(proof["consumed_source_ids"], sorted(run.consumed))
        self.assertGreaterEqual(sum("/payloads/" in x for x in calls), 3)
        inputs = [n for n in self.nodes() if n.get("role") == "input"]
        self.assertEqual(len(inputs), 1)
        source = inputs[0]
        digest = hashlib.sha256(original).hexdigest()
        self.assertEqual(source["source_path"], "data/input.json")
        self.assertEqual(source["sha256"], digest)
        self.assertEqual(source["source_mtime_ns"], mtime)
        self.assertEqual(source["source_timestamps"], {"observed_at": SOURCE_TIME})
        self.assertEqual((self.root / source["payload_path"]).read_bytes(), original)
        execution = self.node(proof["execution_id"])
        consumed = [r for r in execution["relations"] if r["type"] == "consumed"]
        self.assertEqual([r["target"] for r in consumed], proof["consumed_source_ids"])
        self.assertEqual([r["provenance_sha256"] for r in consumed], [digest])
        self.assertEqual(execution["invocation"], run.invocation)
        self.assertEqual(self.node(proof["decision_id"])["decision_kind"], "analysis_evidence_only")
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(self.source.stat().st_mtime_ns, mtime)

    def test_command_finishes_with_supported_workload_proof(self):
        with plane.command(self.root, **self.labels) as run:
            proof = self.workload()
            workload_proof = run.proof()
        summary = self.read_json("data/agents/brain_execution_agents.json")
        self.assertEqual(summary["input_count"], len(workload_proof["consumed_source_ids"]))
        self.assertEqual(summary["output_count"], len(workload_proof["output_artifact_ids"]))
        self.assertEqual(summary["excluded_count"], len(workload_proof["excluded"]))
        self.assertTrue(summary["input_read_from_vault"] and summary["output_stored"])
        self.assertTrue(summary["analysis_only"])
        self.assertFalse(summary["business_approval"] or summary["external_execution"])
        self.assertEqual(summary["scope"], "supported operational JSON only; private inputs excluded")
        self.assertIn(proof["output_artifact_ids"][0], run.outputs)
        self.assertIsNone(brain.current_execution(self.root))
        self.assertFalse((self.root / "obsidian/JARVIS_LUNA/Brain").exists())

    def test_execute_returns_callback_result_and_finishes(self):
        def callback():
            self.workload()
            return 17
        self.assertEqual(plane.execute(self.root, **self.labels, callback=callback), 17)
        self.assertTrue(self.read_json("data/agents/brain_execution_agents.json")["output_stored"])

    def test_no_exclusion_fails_before_callback_or_vault_write(self):
        self.write(".git/info/exclude", b"")
        touched = []
        with self.assertRaisesRegex(brain.BrainError, "brain_git_exclusion_required_before_write"):
            plane.execute(self.root, **self.labels, callback=lambda: touched.append(True))
        self.assertEqual(touched, [])
        self.assertFalse((self.root / brain.BRAIN).exists())

    def test_tracked_brain_fails_before_work(self):
        self.tracked = True
        with self.assertRaisesRegex(brain.BrainError, "brain_must_be_untracked_and_git_excluded"):
            with plane.command(self.root, **self.labels):
                self.fail("command must not start")
        self.assertFalse((self.root / brain.BRAIN).exists())

    def test_exclusion_probes_cover_payloads_nodes_and_notes(self):
        result = brain.audit(self.root)
        probes = [a[4] for a in self.git_calls if a[:4] == ("check-ignore", "--no-index", "-q", "--")]
        self.assertEqual(probes, [brain.BRAIN.as_posix() + suffix for suffix in ("/", "/payloads/00/probe.bin", "/nodes/00/probe.json", "/notes/00/probe.md")])
        self.assertEqual(result["coverage"], "consumed supported operational sources only")
        self.assertFalse(result["cold_note_scan"] or result["business_approval"])
        # git_exclusion_verified is simulated here, never evidence of real Git.
        self.assertTrue(result["git_exclusion_verified"])

    def test_command_without_input_and_output_fails(self):
        with self.assertRaisesRegex(brain.BrainError, "supported_input_and_output_proof_required"):
            with plane.command(self.root, **self.labels):
                pass
        self.assertFalse((self.root / "data/agents/brain_execution_agents.json").exists())
        self.assertIsNone(brain.current_execution(self.root))

    def test_command_with_only_supported_input_fails(self):
        with self.assertRaisesRegex(brain.BrainError, "supported_input_and_output_proof_required"):
            with plane.command(self.root, **self.labels):
                plane.read_json(self.source, self.root, {})
        self.assertFalse((self.root / "data/agents/brain_execution_agents.json").exists())

    def test_record_without_consumed_input_fails(self):
        output = self.write_json("data/result.json", {"count": 2})
        with self.assertRaisesRegex(brain.BrainError, "genuine_consumed_source_required"):
            with plane.command(self.root, **self.labels):
                plane.record(output, self.root)
        self.assertFalse((self.root / "data/agents/brain_execution_agents.json").exists())

    def test_private_input_and_private_output_are_not_supported_proof(self):
        private = self.write_json("data/manual/profile.json", {"private_note": "fixture private marker"})
        with self.assertRaisesRegex(brain.BrainError, "supported_input_and_output_proof_required"):
            with plane.command(self.root, **self.labels) as run:
                self.assertEqual(plane.read_json(private, self.root, {}), {"private_note": "fixture private marker"})
                self.assertIsNone(plane.record(private, self.root))
                self.assertFalse(run.proof()["input_read_from_vault"] or run.proof()["output_stored"])
                self.assertEqual(len(run.excluded), 2)
        self.assertFalse((self.root / brain.BRAIN).exists())

    def test_private_policy_preserves_direct_reads_but_only_counts_exclusions(self):
        manual = self.write_json("data/manual/profile.json", {"private_note": "PRIVATE_MANUAL_MARKER"})
        state = self.write_json("data/operations/state.json", {"private_note": "PRIVATE_STATE_MARKER"})
        checkpoint = self.write_json("data/safety_checkpoint.json", {"private_note": "PRIVATE_CHECKPOINT_MARKER"})
        with plane.command(self.root, **self.labels) as run:
            for file in (manual, state, checkpoint):
                self.assertIn("private_note", plane.read_json(file, self.root, {}))
            self.workload()
            self.assertEqual(len(run.consumed), 1)
            self.assertEqual(len(run.excluded), 3)
        summary = self.read_json("data/agents/brain_execution_agents.json")
        self.assertEqual(summary["excluded_count"], 3)
        self.assertEqual(summary["input_count"], 1)
        vault_bytes = b"".join(p.read_bytes() for p in (self.root / brain.BRAIN).rglob("*") if p.is_file())
        for marker in (b"PRIVATE_MANUAL_MARKER", b"PRIVATE_STATE_MARKER", b"PRIVATE_CHECKPOINT_MARKER"):
            self.assertNotIn(marker, vault_bytes)
        metadata = brain.scan_public_data(self.root)
        self.assertGreaterEqual(metadata["excluded_count"], 3)
        self.assertTrue(all(row["consumed"] is False for row in metadata["entries"]))
        self.assertNotIn("data/operations/state.json", [row["source_path"] for row in metadata["entries"]])

    def test_config_is_explicitly_excluded_not_vault_input(self):
        config = self.write_json("config/daiso_commerce_strategy.json", {"category": "skincare"})
        with brain.execution(self.root, **self.labels) as run:
            self.assertEqual(plane.read_json(config, self.root, {}), {"category": "skincare"})
            self.assertEqual(run.excluded, ["excluded_unsupported_input_path"])
            self.assertFalse(run.consumed)

    def test_missing_invalid_supported_json_default_without_claiming_consumption(self):
        bad = self.write("data/bad.json", b"{invalid")
        with brain.execution(self.root, **self.labels) as run:
            self.assertEqual(plane.read_json(self.root / "data/missing.json", self.root, {"missing": True}), {"missing": True})
            self.assertEqual(plane.read_json(bad, self.root, {"invalid": True}), {"invalid": True})
            self.assertEqual(run.defaults, ["source_missing", "source_invalid_json"])
            self.assertFalse(run.consumed)
            self.assertFalse(run.excluded)

    def test_secret_in_supported_json_raises_not_raw_read_or_default(self):
        # The filename is supported so this exercises the CONTENT policy.
        secret = self.write_json("data/content.json", {"password": "synthetic-do-not-publish"})
        with brain.execution(self.root, **self.labels) as run:
            with self.assertRaisesRegex(brain.PathExcluded, "excluded_credential_field"):
                plane.read_json(secret, self.root, {"fallback": True})
            self.assertFalse(run.consumed)
        self.assertFalse((self.root / brain.BRAIN).exists())

    def test_tampered_payload_fails_closed_without_blanket_fallback(self):
        with brain.execution(self.root, **self.labels):
            plane.read_json(self.source, self.root, {})
            payload = self.payload_for(self.source.read_bytes())
            payload.write_bytes(b'{"tampered":true}')
            with self.assertRaisesRegex(brain.IntegrityError, "vault_hash_mismatch"):
                plane.read_json(self.source, self.root, {"fallback": True})
            self.assertEqual(payload.read_bytes(), b'{"tampered":true}')

    def test_record_rechecks_consumed_payload_integrity(self):
        with brain.execution(self.root, **self.labels) as run:
            plane.read_json(self.source, self.root, {})
            self.payload_for(self.source.read_bytes()).write_bytes(b"changed")
            output = self.write_json("data/result.json", {"count": 2})
            with self.assertRaisesRegex(brain.IntegrityError, "vault_hash_mismatch"):
                plane.record(output, self.root)
            self.assertFalse(run.outputs)
            self.assertFalse(any(n["type"] == "execution" for n in self.nodes()))

    def test_record_rechecks_consumed_node_integrity(self):
        with brain.execution(self.root, **self.labels) as run:
            plane.read_json(self.source, self.root, {})
            identifier = next(iter(run.consumed))
            target = self.root / brain.BRAIN / "nodes" / identifier[:2] / (identifier + ".json")
            target.write_bytes(b"{}")
            output = self.write_json("data/result.json", {"count": 2})
            with self.assertRaisesRegex(brain.IntegrityError, "vault_hash_mismatch"):
                plane.record(output, self.root)
            self.assertFalse(run.outputs)

    def test_invalid_supported_output_cannot_finish_or_claim_storage(self):
        with self.assertRaisesRegex(brain.BrainError, "output_invalid_json"):
            with plane.command(self.root, **self.labels) as run:
                plane.read_json(self.source, self.root, {})
                invalid = self.write("data/result.json", b"{invalid")
                plane.record(invalid, self.root)
        self.assertFalse(run.proof()["output_stored"])
        self.assertFalse((self.root / "data/agents/brain_execution_agents.json").exists())

    def test_path_escape_is_not_an_excluded_raw_read_fallback(self):
        with brain.execution(self.root, **self.labels):
            with self.assertRaisesRegex(brain.PathExcluded, "excluded_path_escape"):
                plane.read_json(self.root.parent / "outside.json", self.root, {})

    def test_callback_exception_is_not_success(self):
        with self.assertRaisesRegex(RuntimeError, "fixture_failure"):
            with plane.command(self.root, **self.labels):
                self.workload()
                raise RuntimeError("fixture_failure")
        self.assertFalse((self.root / "data/agents/brain_execution_agents.json").exists())
        self.assertIsNone(brain.current_execution(self.root))

    def test_runtime_dto_matches_workload_evidence_and_keeps_source_clocks(self):
        runtime_file = self.write_json("data/dashboard_runtime.json", {
            "generated_at": SCREEN_TIME,
            "beauty_category_teams": {"analysis_executed_at": SOURCE_TIME, "subteams": {}},
            "human_activity_at": None,
        })
        before = datetime.now(timezone.utc)
        with plane.command(self.root, **self.labels) as run:
            result = self.workload()
            workload = run.proof()
        after = datetime.now(timezone.utc)
        runtime = json.loads(runtime_file.read_bytes())
        summary = self.read_json("data/agents/brain_execution_agents.json")
        self.assertEqual(runtime["brain_flow"]["executions"]["agents"], summary)
        self.assertEqual(summary["input_count"], len(result["consumed_source_ids"]))
        self.assertEqual(summary["output_count"], len(workload["output_artifact_ids"]))
        completion = datetime.fromisoformat(summary["completed_at"])
        self.assertLessEqual(before, completion)
        self.assertLessEqual(completion, after)
        self.assertNotEqual(summary["completed_at"], SOURCE_TIME)
        self.assertNotEqual(summary["completed_at"], SCREEN_TIME)
        self.assertEqual(runtime["generated_at"], SCREEN_TIME)
        self.assertEqual(runtime["beauty_category_teams"]["analysis_executed_at"], SOURCE_TIME)
        self.assertIsNone(runtime["human_activity_at"])
        self.assertNotIn("human_activity_at", summary)
        projected = public.project(runtime, public.SCHEMAS["data/dashboard_runtime.json"])
        self.assertEqual(projected["brain_flow"]["executions"]["agents"], summary)
        self.assertNotIn("human_activity_at", projected)
        final_digest = hashlib.sha256(runtime_file.read_bytes()).hexdigest()
        self.assertTrue(any(n.get("source_path") == "data/dashboard_runtime.json" and n.get("role") == "output" and n.get("sha256") == final_digest for n in self.nodes()))

    def test_runtime_preserves_prior_team_completion_not_current_screen_clock(self):
        runtime_file = self.write_json("data/dashboard_runtime.json", {"generated_at": SCREEN_TIME})
        with plane.command(self.root, **self.labels):
            self.workload()
        prior = self.read_json("data/agents/brain_execution_agents.json")
        labels = dict(self.labels, team="runtime")
        with plane.command(self.root, **labels):
            self.workload()
        runtime = json.loads(runtime_file.read_bytes())
        executions = runtime["brain_flow"]["executions"]
        self.assertEqual(set(executions), {"agents", "runtime"})
        self.assertEqual(executions["agents"], prior)
        self.assertEqual(executions["runtime"], self.read_json("data/agents/brain_execution_runtime.json"))
        self.assertEqual(executions["agents"]["input_count"], 1)
        self.assertEqual(executions["runtime"]["input_count"], 1)
        self.assertEqual(runtime["generated_at"], SCREEN_TIME)
        self.assertNotEqual(prior["completed_at"], SCREEN_TIME)

    def test_category_reader_uses_active_context_and_tampering_propagates(self):
        relative = "data/daiso_real/shopify_demand_score.json"
        source = self.write_json(relative, {"generated_at": SOURCE_TIME, "grade_summary": {"S": 0}})
        with brain.execution(self.root, **self.labels) as run:
            value, error = category._read(self.root, relative)
            self.assertIsNone(error)
            self.assertEqual(value["grade_summary"], {"S": 0})
            self.assertEqual(len(run.consumed), 1)
            self.payload_for(source.read_bytes()).write_bytes(b"tamper")
            with self.assertRaisesRegex(brain.IntegrityError, "vault_hash_mismatch"):
                category._read(self.root, relative)

    def test_no_context_pure_adapter_compatibility_does_not_claim_vault_proof(self):
        self.assertEqual(plane.read_json(self.source, self.root, {})["items"], [1, 2])
        self.assertIsNone(plane.record(self.source, self.root))
        self.assertFalse((self.root / brain.BRAIN).exists())


class BrainPublicSourceContracts(unittest.TestCase):
    def test_public_flow_drops_private_evidence_and_unknown_teams(self):
        row = {
            "schema_version": 1, "team": "agents", "completed_at": SOURCE_TIME,
            "input_read_from_vault": True, "output_stored": True, "input_count": 1,
            "output_count": 1, "excluded_count": 3, "source_default_count": 0,
            "scope": "supported operational JSON only; private inputs excluded", "analysis_only": True,
            "business_approval": True, "external_execution": True,
            "consumed_source_ids": ["PRIVATE_ID"], "raw_payload": "PRIVATE_RAW",
            "private_path": "PRIVATE_PATH", "identity": "PRIVATE_IDENTITY",
        }
        flow = {"local_only": True, "scope": row["scope"], "business_approval": True,
                "executions": {"agents": row, "unknown_team": {"raw_payload": "PRIVATE_UNKNOWN"}},
                "vault_path": "PRIVATE_VAULT"}
        result = public.project(flow, public.BRAIN_FLOW)
        self.assertEqual(set(result["executions"]), {"agents"})
        clean = result["executions"]["agents"]
        self.assertFalse(clean["business_approval"] or clean["external_execution"])
        self.assertFalse(result["business_approval"])
        self.assertEqual(clean["completed_at"], SOURCE_TIME)
        self.assertNotIn("PRIVATE_", json.dumps(result))
        self.assertNotIn("data/agents/brain_execution_agents.json", public.SCHEMAS)

    def test_public_flow_freeform_values_are_privacy_sanitized(self):
        for text in ("person@example.test", "C:\\Users\\fixture\\private.json", "Bearer synthetic-private-marker", "backend model id"):
            with self.subTest(text=text):
                result = public.project({"scope": text}, public.BRAIN_FLOW)
                self.assertEqual(result["scope"], "[private value omitted]")
        self.assertIsNone(public.project({"scope": "https://private.example/record"}, public.BRAIN_FLOW)["scope"])

    def test_production_main_wiring_is_statically_present_without_invocation(self):
        for filename in ("run_jarvis_agents.py", "generate_dashboard_runtime.py"):
            tree = ast.parse((SCRIPTS / filename).read_text(encoding="utf-8-sig"))
            main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
            calls = [n for n in ast.walk(main) if isinstance(n, ast.Call)]
            matching = [n for n in calls if isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == "brain_plane" and n.func.attr == "execute"]
            self.assertEqual(len(matching), 1, filename)
            self.assertTrue(any(k.arg == "callback" and isinstance(k.value, ast.Name) and k.value.id == "_main" for k in matching[0].keywords), filename)
        tree = ast.parse((SCRIPTS / "run_jarvis_operations.py").read_text(encoding="utf-8-sig"))
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        wrapped = [n for n in ast.walk(main) if isinstance(n, ast.With) and any(isinstance(i.context_expr, ast.Call) and isinstance(i.context_expr.func, ast.Attribute) and isinstance(i.context_expr.func.value, ast.Name) and i.context_expr.func.value.id == "brain_plane" and i.context_expr.func.attr == "command" for i in n.items)]
        self.assertEqual(len(wrapped), 1)
        self.assertTrue(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "run" for n in ast.walk(wrapped[0])))

    def test_ui_reads_schema_fields_and_uses_text_not_html(self):
        source = (SCRIPTS.parent / "index.html").read_text(encoding="utf-8")
        start = source.index("function renderBrainFlow(d)")
        end = source.index("function renderTeams(d)", start)
        renderer = source[start:end]
        self.assertIn("e.textContent=text", renderer)
        self.assertNotIn("innerHTML", renderer)
        self.assertIn("flow.executions", renderer)
        for name in ("input_count", "output_count", "completed_at"):
            self.assertIn("r." + name, renderer)
            self.assertIn(name, public.BRAIN_EXECUTION)
        self.assertIn("t.canonical_s_count", renderer)
        self.assertIn("canonical_s_count", public.CATEGORY_SUBTEAM)
        self.assertIn("eligible_pd_nos", public.CATEGORY_SUBTEAM)
        self.assertNotIn("fmtKST(", renderer, "undefined formatter must not abort renderTeams")
        self.assertIn('timeZone:"Asia/Seoul"', renderer)
        self.assertIn("화면 생성 시각은 팀 실행 시각이 아닙니다", renderer)


if __name__ == "__main__":
    unittest.main()
