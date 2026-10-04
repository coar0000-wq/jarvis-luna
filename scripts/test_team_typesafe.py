#!/usr/bin/env python3
"""Offline only. All inference adapters are injected mocks; no credentials/network."""
from __future__ import annotations
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

try:
    from . import evaluate_team_typesafe as team
    from .typesafe_shared import canonical, clean, digest, validate_payload
except ImportError:
    import evaluate_team_typesafe as team
    from typesafe_shared import canonical, clean, digest, validate_payload


class TeamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        cards = [{"id": role, "status": "success", "action_kind": "none",
                  "summary": "cached team count", "action": None, "waiting": None,
                  "collection_freshness": {"status": "success", "data_stale": False,
                    "last_success_at": "2026-10-01T00:00:00Z", "success_age_hours": 2,
                    "captured_at": "2026-10-01T00:00:00Z"}}
                 for role in team.TEAMS]
        self.dashboard = {"generated_at": "clock-A", "teams": cards,
                          "secretary": {"id": "secretary", "status": "warning", "steps": []}}
        self.learning = {"generated_at": "clock-A", "teams": {
            role: {"status": "학습 중", "insights": 1, "videos_available": 1,
                   "last_review": "2026-10-01", "items": [{"confidence": "high",
                   "evidence": {"url": "https://example.invalid/source", "timestamp": "01:00",
                                "summary": "cached evidence summary"}}]} for role in team.TEAMS}}
        self.improved = {"generated_at": "clock-A", "runtime_at": "clock-A", "teams": {
            role: {"status": "success", "state": "진행", "stale": False, "streak": 1,
                   "checked_at": "clock-A", "open_kind": "none"} for role in team.TEAMS}}
        self.save()

    def write(self, name, value):
        target = self.data / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def save(self):
        self.write("dashboard_runtime.json", self.dashboard)
        self.write("team_learning.json", self.learning)
        self.write("team_improvement.json", self.improved)

    def payload(self):
        return team.build_payload(self.root)

    def test_all_roles_single_batch_typed(self):
        payload = self.payload()
        self.assertEqual(set(payload["state"]["teams"]), set(team.TEAMS) | {"secretary"})
        self.assertEqual(len(team.ROLES), 12)
        self.assertEqual(len(payload["questions"]), 24)
        validate_payload(payload)
        answers = team.fallback(payload)
        answers["market_quality"] = {"score": 3, "confidence": .92}
        adapter = Mock(return_value={"source": "typesafe", "mode": "typesafe_advisory",
                       "enforced": False, "answers": answers, "model": "jev-test-revision",
                       "usage": {"input_tokens": 400, "output_tokens": 20}})
        result = team.evaluate(payload, adapter)
        adapter.assert_called_once_with(payload, fallback_answers=team.fallback(payload))
        self.assertEqual(result["teams"]["market"]["quality"], answers["market_quality"])
        self.assertEqual(len(result["teams"]), 12)
        self.assertFalse(result["enforced"])
        self.assertFalse(result["approval"])
        self.assertEqual(result["visibility"], "private")
        self.assertEqual(result["question_version"], "jarvis-teams-v1")
        self.assertEqual(result["model_policy_version"], "jarvis-jev-alias-v1")

    def test_local_labels_never_jev(self):
        payload = self.payload()
        adapter = Mock(return_value={"source": "deterministic_local", "mode": "disabled_local_advisory",
                       "answers": team.fallback(payload), "model": "jev-latest"})
        result = team.evaluate(payload, adapter)
        self.assertEqual(result["source"], "deterministic_local")
        self.assertIsNone(result["model"])
        self.assertIsNone(result["usage"])
        self.assertFalse(result["paid_api_called"])
        for row in result["teams"].values():
            self.assertEqual(row["source"], "deterministic_local")
            self.assertFalse(row["approval"])

    def test_unknown_incomplete_stale_blocked_evidence_review(self):
        self.dashboard["teams"][0]["collection_freshness"] = {}
        self.dashboard["teams"][1]["waiting"] = "approval needed"
        self.dashboard["teams"][2]["collection_freshness"]["data_stale"] = True
        self.learning["teams"]["listing"]["items"] = []
        self.save()
        answers = team.fallback(self.payload())
        for role in ("sourcing", "institutions", "market", "listing", "secretary"):
            self.assertEqual(answers[role + "_quality"]["score"], 1)
            self.assertNotEqual(answers[role + "_next_action"]["choice"], "local")
        self.assertEqual(answers["institutions_next_action"]["choice"], "human_review")
        with tempfile.TemporaryDirectory() as empty:
            answers = team.fallback(team.build_payload(Path(empty)))
            self.assertTrue(all(v["score"] == 1 for k, v in answers.items() if k.endswith("_quality")))

    def test_private_material_excluded_and_input_bounded(self):
        marker = "PRIVATE_CANARY_A_123"
        for card in self.dashboard["teams"]:
            card.update({"personal_notes": marker, "business_address": marker,
                         "manual_file_path": marker, "credentials": marker,
                         "summary": marker * 1000, "action": marker * 1000,
                         "scraped_text": marker * 1000})
        for item in self.learning["teams"]["sourcing"]["items"]:
            item["evidence"]["summary"] = marker * 1000
            item["evidence"]["personal_notes"] = marker
        self.save()
        payload = self.payload()
        text = team.canonical(payload)
        self.assertNotIn(marker, text)
        self.assertNotIn("example.invalid", text)
        self.assertNotIn("personal_notes", text)
        self.assertNotIn("manual_file_path", text)
        self.assertLessEqual(len(text), 12000)
        self.assertLess(len(text.encode("utf-8")), 15000)
        result = team.evaluate(payload, Mock(return_value={"source": "unavailable", "mode": "disabled"}))
        self.assertNotIn(marker, team.canonical(result))

    def test_generation_clocks_stable_actual_capture_invalidates(self):
        old = self.payload()
        self.dashboard["generated_at"] = "clock-B"
        self.dashboard["last_synced"] = "clock-B"
        self.dashboard["teams"][0]["when"] = "clock-B"
        self.dashboard["secretary"]["workflow_observed_at"] = "clock-B"
        self.learning["generated_at"] = "clock-B"
        self.improved["generated_at"] = "clock-B"
        self.improved["runtime_at"] = "clock-B"
        for row in self.improved["teams"].values():
            row["checked_at"] = "clock-B"
        self.save()
        self.assertEqual(digest(old), digest(self.payload()))
        self.dashboard["teams"][0]["collection_freshness"]["captured_at"] = "2026-10-02T00:00:00Z"
        self.save()
        new = self.payload()
        self.assertNotEqual(digest(old), digest(new))
        self.assertIn("source_capture_at", new["state"]["teams"]["sourcing"]["collection_freshness"])
        self.assertNotEqual(digest(clean(old)), digest(clean(new)))

    def test_state_age_schema_full_material_invalidate(self):
        old = self.payload()
        self.dashboard["teams"][0]["collection_freshness"]["success_age_hours"] = 3
        self.save()
        self.assertNotEqual(digest(old), digest(self.payload()))
        old = self.payload()
        self.learning["teams"]["sourcing"]["items"][0]["evidence"]["summary"] = "different cached evidence"
        self.save()
        self.assertNotEqual(digest(old), digest(self.payload()))
        old = self.payload()
        self.dashboard["teams"][0]["status"] = "warning"
        self.save()
        self.assertNotEqual(digest(old), digest(self.payload()))
        changed = copy.deepcopy(old)
        changed["questions"]["sourcing_quality"]["instructions"] += " new rubric"
        self.assertNotEqual(digest(old), digest(changed))

    def test_no_canonical_mutation_and_custom_output(self):
        for name in ("listing_gate.json", "legal_products.json", "inventory.json",
                     "candidates.json", "shopify_export.csv", "product_master.json"):
            (self.data / name).write_bytes(b"DO NOT MUTATE")
        before = {p: p.read_bytes() for p in self.data.rglob("*") if p.is_file()}
        output = self.root / "private" / "advisory.json"
        adapter = Mock(return_value={"source": "unavailable", "mode": "proof_missing_or_invalid"})
        with contextlib.redirect_stdout(io.StringIO()):
            team.main(["--output", str(output)], root=self.root, adapter=adapter)
        adapter.assert_called_once()
        for p, value in before.items():
            self.assertEqual(p.read_bytes(), value)
        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(len(result["teams"]), 12)
        self.assertEqual(result["source"], "deterministic_local")
        self.assertFalse((self.data / "typesafe_team_advisory.json").exists())

    def test_dry_run_no_adapter_no_mutation_exact_reservation(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        adapter = Mock(side_effect=AssertionError("must not invoke"))
        stdout = io.StringIO()
        output = self.root / "absent" / "result.json"
        with contextlib.redirect_stdout(stdout):
            team.main(["--dry-run", "--output", str(output)], root=self.root, adapter=adapter)
        adapter.assert_not_called()
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        self.assertFalse(output.parent.exists())
        estimate = json.loads(stdout.getvalue())
        payload = self.payload()
        wire = {k: v for k, v in payload.items() if k not in {"question_version", "model_policy_version"}}
        self.assertEqual(estimate["reserved_input_tokens"], len(canonical(wire).encode("utf-8")) + 2048)
        self.assertEqual(estimate["calls_reserved"], 1)
        self.assertFalse(estimate["network_called"])
        self.assertFalse(estimate["output_mutated"])

    def test_invalid_mock_answers_and_exception_local_no_retry(self):
        for adapter in (Mock(return_value={"source": "typesafe", "mode": "bad_response", "answers": {}}),
                        Mock(side_effect=RuntimeError("PRIVATE_EXCEPTION"))):
            result = team.evaluate(self.payload(), adapter)
            adapter.assert_called_once()
            self.assertEqual(result["source"], "deterministic_local")
            self.assertNotIn("PRIVATE_EXCEPTION", team.canonical(result))

    def test_output_cannot_overwrite_canonical_data(self):
        target = self.data / "listing_gate.json"
        target.write_bytes(b"canonical")
        adapter = Mock(side_effect=AssertionError("must not invoke"))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            team.main(["--output", str(target)], root=self.root, adapter=adapter)
        adapter.assert_not_called()
        self.assertEqual(target.read_bytes(), b"canonical")

    def test_cache_answers_retain_confidence_no_new_call_claim(self):
        payload = self.payload()
        adapter = Mock(return_value={"source": "typesafe_cache", "mode": "typesafe_cached_advisory",
                       "answers": team.fallback(payload), "model": "jev-test-revision",
                       "usage": {"input_tokens": 20, "output_tokens": 10}})
        result = team.evaluate(payload, adapter)
        self.assertEqual(result["source"], "typesafe_cache")
        self.assertFalse(result["paid_api_called"])
        self.assertEqual(result["teams"]["market"]["quality"]["confidence"], 0.0)

    def test_real_adapter_disabled_offline(self):
        # Exercise the real local path with all env cleared, network impossible.
        with patch.dict("os.environ", {}, clear=True), patch("urllib.request.urlopen", side_effect=AssertionError("network")) as network:
            result = team.evaluate(self.payload())
        network.assert_not_called()
        self.assertEqual(result["source"], "deterministic_local")
        self.assertEqual(result["mode"], "disabled_local_advisory")


if __name__ == "__main__":
    unittest.main(verbosity=2)
