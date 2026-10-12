"""Isolated category queue contracts; no provider calls or operating file writes."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import beauty_category_teams as teams

AS_OF = "2026-10-11T09:00:00Z"


class CategoryTeamsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.docs = {
            "category_config": {"categories": [
                {"tag": "skincare", "score_buckets": ["스킨케어", "마스크팩"]},
                {"tag": "makeup", "score_buckets": ["메이크업"]},
                {"tag": "body", "score_buckets": ["바디케어"]}]},
            "demand_score": {"all_scored": [
                {"pd_no": "1", "bucket": "스킨케어", "grade": "S", "source_observed_at": "2026-10-09T00:00:00Z"},
                {"pd_no": "2", "bucket": "메이크업", "grade": "A"},
                {"pd_no": "3", "bucket": "바디케어", "grade": "B"},
                {"pd_no": "4", "bucket": "바디케어", "grade": "C"}]},
            "registry": {"items": []},
            "listing_gate": {"generated_at": AS_OF, "items": [self.gate("1")]},
            "candidate_comparison": {"items": [{"pd_no": "5", "bucket": "메이크업", "score": {"grade": "S"}}]},
            "beauty_strategy": {"products": [{"pd_no": "2", "grade": "S", "category": "skincare", "actual_sales": 88}]},
        }
        self.persist()

    def gate(self, pd):
        return {"pd_no": pd, "ready": True, "public_ready": True, "legal_full_complete": True,
                "manufacturer_safety_record": {"covered": True},
                "price": {"price_evidence_ok": True, "register_blocked": False},
                "legal": {"hard_block": False}}

    def persist(self):
        for key, doc in self.docs.items():
            target = self.root / teams.INPUT_PATHS[key]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def build(self, fresh=True, safety=True):
        self.persist()
        with patch.object(teams, "_gate_freshness", return_value=(fresh, None if fresh else "stale")), \
             patch.object(teams.gate_signature.manufacturer_safety, "manufacturer_safety_record", return_value={"covered": safety}), \
             patch.object(teams.gate_signature.manufacturer_safety, "public_view", side_effect=lambda value: value):
            return teams.build(self.root, AS_OF)

    def test_three_scopes_preserve_canonical_teams_and_shared_roles(self):
        result = self.build()
        self.assertEqual(list(result["subteams"]), ["skincare", "makeup", "body"])
        self.assertEqual(result["canonical_team_ids"], list(teams.CANONICAL_TEAM_IDS))
        self.assertEqual(len(result["canonical_team_ids"]), 11)
        scopes = result["subteams"]
        self.assertEqual(scopes["skincare"]["owned_pd_nos"], ["1"])
        self.assertEqual(scopes["makeup"]["owned_pd_nos"], ["2", "5"])
        self.assertEqual(scopes["body"]["owned_pd_nos"], ["3", "4"])
        for tag, scope in scopes.items():
            self.assertEqual(scope["category_tag"], tag)
            self.assertEqual(scope["role_assignments"], {r: r for r in teams.ROLES})
            self.assertIsNone(scope["secretary_oversight"]["receipt"])

    def test_only_canonical_s_no_comparison_or_strategy_fallback(self):
        result = self.build()["subteams"]
        self.assertEqual(result["skincare"]["eligible_pd_nos"], ["1"])
        for tag in ("makeup", "body"):
            self.assertEqual(result[tag]["registration_queue"], [])
            self.assertEqual(result[tag]["eligible_pd_nos"], [])
            self.assertFalse(result[tag]["lower_grade_fallback"])
            self.assertTrue(all(not r["eligible_for_registration"] for r in result[tag]["source_research_queue"]))
        self.assertEqual(result["makeup"]["source_research_queue"][0]["canonical_grade"], "A")
        self.assertIsNone(result["makeup"]["source_research_queue"][1]["canonical_grade"])

    def test_duplicates_history_and_in_doubt_are_skipped(self):
        self.docs["demand_score"]["all_scored"].append(copy.deepcopy(self.docs["demand_score"]["all_scored"][0]))
        self.docs["candidate_comparison"]["items"].append({"pd_no": "1", "bucket": "스킨케어", "score": {"grade": "S"}})
        self.assertEqual(len(self.build()["subteams"]["skincare"]["registration_queue"]), 1)
        self.docs["registry"] = {"items": [{"pd_no": "1", "status": "deleted_by_owner"}],
                                 "history": [{"pd_no": "2", "status": "DRAFT"}],
                                 "in_doubt": [{"pd_no": "3", "status": "pending_receipt"}]}
        scopes = self.build()["subteams"]
        self.assertEqual(scopes["skincare"]["registration_queue"], [])
        self.assertEqual(scopes["makeup"]["owned_pd_nos"], ["5"])
        self.assertEqual(scopes["body"]["owned_pd_nos"], ["4"])

    def test_conflicting_canonical_rows_cannot_register(self):
        self.docs["demand_score"]["all_scored"].append({"pd_no": "1", "bucket": "스킨케어", "grade": "A"})
        scope = self.build()["subteams"]["skincare"]
        self.assertEqual(scope["registration_queue"], [])
        self.assertIn("conflicting_canonical_rows", scope["source_research_queue"][0]["blockers"])

    def test_fresh_gate_required_even_with_ready_flags(self):
        scope = self.build(fresh=False)["subteams"]["skincare"]
        item = scope["registration_queue"][0]
        self.assertFalse(item["eligible_for_registration"])
        self.assertIn("fresh_gate_required", item["blockers"])
        self.assertTrue(any(t["kind"] == "fresh_gate" for t in scope["evidence_tasks"]))

    def test_real_signature_rejects_changed_inputs_and_old_clock(self):
        gate = self.docs["listing_gate"]
        self.persist()
        module = teams._gate_module(self.root)
        gate["agent_input_signature"] = module.agent_input_signature(module.current_recommendations())
        self.persist()
        self.assertTrue(teams._gate_freshness(self.root, gate, AS_OF)[0])
        self.assertFalse(teams._gate_freshness(self.root, gate, "2026-10-13T09:00:00Z")[0])
        self.docs["category_config"]["extra_policy"] = "changed"
        self.persist()
        self.assertFalse(teams._gate_freshness(self.root, gate, AS_OF)[0])

    def test_zero_s_local_analysis_not_fake_human_work(self):
        result = self.build()
        for tag in ("makeup", "body"):
            scope = result["subteams"][tag]
            self.assertTrue(scope["s_zero"])
            self.assertEqual(scope["status"], "analysis_complete")
            self.assertEqual(scope["analysis_executed_at"], AS_OF)
            self.assertEqual(scope["analysis_proof"]["executed_at"], AS_OF)
            self.assertEqual(scope["analysis_proof"]["analyzed_pd_nos"], scope["owned_pd_nos"])
            self.assertEqual(len(scope["analysis_proof"]["input_sha256"]["demand_score"]), 64)
            self.assertFalse(scope["analysis_proof"]["human_activity_verified"])
            self.assertFalse(scope["analysis_proof"]["research_executed"])
            self.assertEqual(scope["work_status"], "source_research_required")
            self.assertGreater(scope["counts"]["evidence_tasks"], 0)
            self.assertTrue(any(t["owner_team_id"] == "sourcing" for t in scope["evidence_tasks"]))
            for task in scope["evidence_tasks"]:
                self.assertIsNone(task["executed_at"])
                self.assertIsNone(task["handoff_receipt"])
                self.assertIsNone(task["approval_receipt"])
        item = result["subteams"]["skincare"]["registration_queue"][0]
        self.assertNotEqual(item["source_observed_at"], item["analysis_executed_at"])
        self.assertIsNone(item["registration_executed_at"])
        self.assertIsNone(item["publish_executed_at"])

    def test_actual_sales_unknown_not_zero_or_reviews_or_strategy(self):
        self.docs["demand_score"]["all_scored"][0]["review_count"] = 20000
        scopes = self.build()["subteams"]
        for scope in scopes.values():
            for item in scope["registration_queue"] + scope["source_research_queue"]:
                self.assertEqual(item["actual_sales"]["status"], "UNKNOWN")
                self.assertIsNone(item["actual_sales"]["orders"])
                self.assertIsNone(item["actual_sales"]["units"])

    def test_manufacturer_text_or_gate_promise_not_current_proof(self):
        self.docs["listing_gate"]["items"][0]["manufacturer"] = "verified manufacturer"
        item = self.build(safety=False)["subteams"]["skincare"]["registration_queue"][0]
        self.assertFalse(item["eligible_for_registration"])
        self.assertIn("manufacturer_safety_record_required", item["blockers"])
        self.assertEqual(item["manufacturer_safety"]["status"], "not_verified_by_this_analysis")

    def test_build_is_deterministic_read_only_missing_registry_fails_closed(self):
        self.assertEqual(self.build(), self.build())
        self.persist()
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        teams.build(self.root, AS_OF)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        (self.root / teams.INPUT_PATHS["registry"]).unlink()
        with patch.object(teams, "_gate_freshness", return_value=(True, None)):
            item = teams.build(self.root, AS_OF)["subteams"]["skincare"]["registration_queue"][0]
        self.assertFalse(item["eligible_for_registration"])
        self.assertIn("registry_unavailable", item["blockers"])

    def test_unmapped_category_is_not_guessed_from_name(self):
        self.docs["demand_score"]["all_scored"].append({"pd_no": "6", "bucket": "헤어케어", "name": "body makeup skincare", "grade": "S"})
        result = self.build()
        self.assertEqual(result["excluded"], [{"pd_no": "6", "reason": "category_missing_ambiguous_or_out_of_scope"}])

    def test_cli_optional_write_is_only_expected_output(self):
        before = set(p.relative_to(self.root) for p in self.root.rglob("*") if p.is_file())
        self.assertEqual(teams.main(["--root", str(self.root), "--as-of", AS_OF, "--write"]), 0)
        after = set(p.relative_to(self.root) for p in self.root.rglob("*") if p.is_file())
        self.assertEqual(after - before, {Path("data/agents/beauty_category_teams.json")})


if __name__ == "__main__":
    unittest.main()
