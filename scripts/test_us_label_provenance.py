#!/usr/bin/env python3
"""Offline fixtures only: no production writes, network, identity or contact files."""
from __future__ import annotations

import contextlib
from copy import deepcopy
import io
import json
import unittest
from unittest.mock import patch

import check_legal_products as legal
import sync_gosi_to_us_labels as sync
from inci_resolver import InciResolver

STAMP = "2026-10-03T00:00:00+00:00"
MASTER = {"pd_no_to_cp": {"101": "CP000001", "102": "CP000002", "103": "CP000003"},
          "products": [{"pd_no": "101", "grade": "S", "canonical_product_id": "CP000001"},
                       {"pd_no": "102", "grade": "S", "canonical_product_id": "CP000002"}]}
SCORE = {"all_scored": [{"pd_no": "101", "grade": "S"},
                        {"pd_no": "103", "grade": "S"},
                        {"pd_no": "999", "grade": "S"}]}
SOURCE = {"name": "Fixture lotion", "volume": "30 ml", "maker": "Fixture Manufacturer",
          "origin": "한국", "ingredients": "정제수", "verified": True,
          "vision_source": "model", "alt_source": "parsed"}
RESOLVER = InciResolver({"정제수": "Water", "글리세린": "Glycerin"}, {})


def run_sync(labels=None, sources=None):
    return sync.sync_labels({"items": {"101": deepcopy(SOURCE)}} if sources is None else sources,
                            {} if labels is None else labels, SCORE, MASTER, RESOLVER, STAMP)


def complete_label():
    return {"ingredients_inci": "Water", "net_contents": "30 ml",
            "manufacturer": "Fixture Manufacturer", "country_of_origin": "Korea",
            "product_name_en": "Fixture Lotion", "directions_en": "Apply gently.",
            "warnings_en": "For external use only."}


def evidence(source_type):
    return {"product_id": "101", "human_approved": True, "source_type": source_type,
            "evidence_ref": "fixture-artifact-1", "reviewed_by": "fixture-reviewer",
            "reviewed_at": STAMP}


class Sink:
    def __init__(self):
        self.doc = None

    def write_text(self, raw, **kwargs):
        self.doc = json.loads(raw)


def run_legal(labels, old=None, recommendations=None):
    sink = Sink()
    docs = {legal.SCORE: SCORE, legal.MASTER: MASTER, legal.LABELS: labels,
            legal.RECOMMENDATIONS: recommendations or {"recommendations": []},
            legal.COPIES: {"items": []}, legal.RULES: {"banned": {}}, sink: old or {}}
    with patch.object(legal, "OUT", sink), patch.object(legal, "load",
            side_effect=lambda p, d: deepcopy(docs.get(p, d))), contextlib.redirect_stdout(io.StringIO()):
        legal.main()
    return sink.doc


class LabelProvenanceTests(unittest.TestCase):
    def test_legacy_wrapped_and_wrapped_list(self):
        for labels in ({"101": {}}, {"items": {"101": {}}, "signature": "fixture-signature"},
                       {"items": [{"product_id": "101"}], "signature": "fixture-signature"}):
            output, report = run_sync(labels)
            rows = sync.rows_by_id(output)
            self.assertEqual(set(rows), {"101", "102", "103"})
            self.assertEqual(rows["101"]["ingredients_inci"], "Water")
            self.assertEqual(rows["101"]["canonical_product_id"], "CP000001")
            if "items" in labels:
                self.assertEqual(output["signature"], "fixture-signature")
            self.assertEqual(report["current_s_count"], 3)
            self.assertEqual(labels.get("101", {}).get("ingredients_inci"), None)

    def test_placeholder_rejection_for_every_required_field(self):
        placeholders = ("TODO", "TBD", "placeholder", "실제 제품 포장에 기재된 전체 INCI 성분",
                        "실제 포장에 기재된 제조사", "확인 필요", "상세페이지 참조",
                        "N/A", "unknown", "pending", "not verified", "to be filled", "-", True, {}, [])
        for value in placeholders:
            self.assertFalse(sync.real(value), repr(value))
            for field in legal.ENGLISH_LABEL_FIELDS:
                label = complete_label()
                label[field] = value
                self.assertFalse(legal.us_requirements(label, "101")["label_fields"]["ok"])
        self.assertFalse(legal.english_text("제조사"))

    def test_placeholder_can_be_filled_without_human_approval(self):
        output, _ = run_sync({"101": {"manufacturer": "실제 포장에 기재된 제조사"}})
        label = output["101"]
        self.assertEqual(label["manufacturer"], SOURCE["maker"])
        self.assertFalse(label["field_provenance"]["manufacturer"]["human_verified"])
        self.assertNotIn("human_approved", label)
        self.assertFalse(legal.us_requirements(label, "101")["actual_label_review"]["ok"])

    def test_unmarked_human_text_not_reclaimed_by_source_type(self):
        label = complete_label()
        label.update(source_type="daiso_product_notice", ingredients_inci="Manually reviewed INCI",
                     manufacturer="Human manufacturer", ingredients_source="Human source",
                     responsible_person={"name": "Fixture RP", "address": "Fixture address"},
                     responsible_person_address="Fixture address", address="Fixture address")
        original = deepcopy(label)
        output, _ = run_sync({"101": label})
        for key in original:
            self.assertEqual(output["101"][key], original[key], key)
        self.assertNotIn("ingredients_inci_source", output["101"])

    def test_explicit_human_ownership_wins_over_old_machine_marker(self):
        label = complete_label()
        label.update(ingredients_inci_source="kr_notice_via_dictionary", ingredients_source="Human source",
                     _자동으로_채운_칸=["ingredients_inci", "manufacturer", "warnings_en"],
                     field_provenance={"ingredients_inci": {"owner": "human", "human_approved": True},
                                       "manufacturer": {"owner": "human"}},
                     actual_label_evidence=evidence("actual_packaging"),
                     product_safety_evidence=evidence("manufacturer_product_safety"))
        output, _ = run_sync({"101": label}, {"items": {}})
        for field in ("ingredients_inci", "ingredients_source", "ingredients_inci_source",
                      "manufacturer", "warnings_en", "field_provenance", "actual_label_evidence",
                      "product_safety_evidence"):
            self.assertEqual(output["101"][field], label[field], field)
        self.assertNotIn("ingredients_inci_status", output["101"])
        self.assertEqual(output["101"]["_자동으로_채운_칸"], [])

    def test_stale_inci_missing_or_unresolvable_upstream_preserves_fact(self):
        first, _ = run_sync()
        for sources in ({"items": {}}, {"items": {"101": {}}},
                        {"items": {"101": {"ingredients": "unknown"}}},
                        {"items": {"101": {"ingredients": "알수없는성분"}}}):
            result, _ = run_sync(first, sources)
            row = result["101"]
            self.assertEqual(row["ingredients_inci"], "Water")
            self.assertEqual(row["ingredients_source"], "정제수")
            self.assertEqual(row["ingredients_inci_status"], "stale")
            self.assertFalse(row["ingredients_inci_eligible"])
            self.assertFalse(row["gosi_ok"])
            self.assertEqual(row["ingredients_inci_history"][0]["value"], "Water")
            self.assertFalse(sync.field_current(row, "ingredients_inci"))
            self.assertFalse(legal.us_requirements(row, "101")["label_fields"]["ok"])
            again, _ = run_sync(result, sources)
            self.assertEqual(len(again["101"]["ingredients_inci_history"]), 1)

    def test_changed_resolvable_inci_archives_then_recomputes(self):
        first, _ = run_sync()
        source = {**SOURCE, "ingredients": "글리세린"}
        result, _ = run_sync(first, {"items": {"101": source}})
        row = result["101"]
        self.assertEqual(row["ingredients_inci"], "Glycerin")
        self.assertEqual(row["ingredients_inci_history"][0]["value"], "Water")
        self.assertEqual(row["ingredients_source"], "글리세린")
        self.assertEqual(row["ingredients_inci_status"], "current_derived")
        self.assertTrue(sync.field_current(row, "ingredients_inci"))
        self.assertFalse(row["field_provenance"]["ingredients_inci"]["human_verified"])

    def test_current_s_stable_union_no_arbitrary_ids_or_drops(self):
        original_master = deepcopy(MASTER)
        current = sync.current_s_registry(SCORE, MASTER)
        self.assertEqual(current, MASTER["pd_no_to_cp"])
        self.assertNotIn("999", current)
        result, _ = run_sync({"retired": {"signature": "keep"}},
                             {"items": {"999": SOURCE}})
        self.assertEqual(set(result), {"retired", "101", "102", "103"})
        self.assertEqual(result["retired"]["signature"], "keep")
        self.assertEqual(MASTER, original_master)

    def test_approved_actual_artifact_protects_old_machine_text(self):
        first, _ = run_sync()
        first["101"]["actual_label_evidence"] = evidence("actual_packaging")
        result, _ = run_sync(first, {"items": {"101": {**SOURCE, "ingredients": "글리세린"}}})
        self.assertEqual(result["101"]["ingredients_inci"], "Water")
        self.assertEqual(result["101"]["ingredients_source"], "정제수")
        self.assertEqual(result["101"]["actual_label_evidence"], evidence("actual_packaging"))
        self.assertEqual(result["101"]["ingredients_inci_status"], "stale")
        self.assertFalse(result["101"]["ingredients_inci_eligible"])

    def test_missing_registry_fails_closed_and_other_scripts_not_english(self):
        with self.assertRaises(ValueError):
            sync.current_s_registry(SCORE, {})
        self.assertFalse(legal.english_text("Manufacturer 制造商"))
        self.assertFalse(legal.english_text("Manufacturer Производитель"))
        self.assertTrue(legal.english_text("Crème Lotion"))

    def test_gosi_legacy_and_list_wrappers(self):
        for source in ({"101": SOURCE}, {"items": [{"product_id": "101", **SOURCE}]}):
            output, _ = run_sync({}, source)
            self.assertEqual(output["101"]["ingredients_inci"], "Water")

    def test_canonical_mismatch_fails_closed(self):
        bad_score = {"all_scored": [{"pd_no": "101", "grade": "S", "canonical_product_id": "CP999999"}]}
        with self.assertRaises(ValueError):
            sync.current_s_registry(bad_score, MASTER)

    def test_all_current_s_get_legal_rows_without_recommendations(self):
        old = {"items": {"retired": {"status": "pass", "signature": "keep"}}, "authority": "fixture-authority"}
        output = run_legal({"items": {"101": complete_label()}}, old)
        self.assertEqual(set(output["items"]), {"101", "102", "103"})
        self.assertEqual(output["auto_summary"]["checked"], 3)
        self.assertEqual(output["auto_summary"]["pass"], 0)
        self.assertEqual(output["out_of_scope"]["retired"]["row"]["signature"], "keep")
        self.assertEqual(output["authority"], old["authority"])
        self.assertEqual(old["items"]["retired"]["signature"], "keep")
        for row in output["items"].values():
            self.assertTrue(row["hard_block"])
            self.assertFalse(row["effective_legal_pass"])

    def test_manufacturer_not_responsible_person(self):
        label = complete_label()
        label.update(verified=True, human_approved=True, source_type="model")
        checks = legal.us_requirements(label, "101")
        self.assertTrue(checks["label_fields"]["ok"])
        self.assertFalse(checks["responsible_person"]["ok"])
        self.assertFalse(checks["manufacturer_product_safety"]["ok"])
        self.assertFalse(checks["actual_label_review"]["ok"])
        self.assertNotIn("responsible_person", label)

    def test_model_alt_and_cross_product_evidence_not_safety_approval(self):
        for source_type, product_id in (("model", "101"), ("alt_parser", "101"),
                                        ("manufacturer_product_safety", "102")):
            label = complete_label()
            proof = evidence(source_type)
            proof.update(product_id=product_id, verified=True,
                         manufacturer="Fixture Manufacturer", product_specific_basis="Fixture report")
            label["product_safety_evidence"] = proof
            self.assertFalse(legal.us_requirements(label, "101")["manufacturer_product_safety"]["ok"])

    def test_preserves_signed_pass_but_never_effective_pass_without_evidence(self):
        signed = {"status": "pass", "reviewer": "fixture-reviewer", "reviewed_at": STAMP,
                  "signature": "fixture-signature", "authority": "fixture-authority", "note": "Human note"}
        output = run_legal({"101": complete_label()}, {"items": {"101": signed}})
        row = output["items"]["101"]
        for key in signed:
            self.assertEqual(row[key], signed[key])
        self.assertTrue(row["hard_block"])
        self.assertFalse(row["effective_legal_pass"])
        self.assertEqual(output["auto_summary"]["pass"], 0)

    def test_real_evidence_preserved_and_no_automatic_legal_pass(self):
        label = complete_label()
        label.update(responsible_person={"name": "Fixture RP", "address": "Fixture Address"},
                     responsible_person_evidence=evidence("responsible_person_confirmation"),
                     actual_label_evidence=evidence("actual_packaging"),
                     product_safety_evidence={**evidence("manufacturer_product_safety"),
                        "manufacturer": "Fixture Manufacturer", "product_specific_basis": "Fixture product report"})
        self.assertTrue(all(c["ok"] for c in legal.us_requirements(label, "101").values()))
        output = run_legal({"items": {"101": label}})
        row = output["items"]["101"]
        self.assertNotEqual(row["status"], "pass")
        self.assertTrue(row["hard_block"])
        self.assertIn("human_legal_approval", row["auto_blockers"])
        self.assertEqual(label["actual_label_evidence"], evidence("actual_packaging"))


if __name__ == "__main__":
    unittest.main()
