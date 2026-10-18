"""Synthetic local fixtures only. No real product evidence or external writes."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import product_accuracy as accuracy
import gemini_listing_copy as gemini
import build_listing_copy_local as local
import gate_signature
import build_shopify_import_csv as csv_builder

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
PRODUCT = {"pd_no": "fixture-1", "name": "Fixture 세럼 30 ml", "brand_english": "Fixture", "net_contents": "30 ml"}
NEUTRAL = {"title": "Fixture Serum 30 ml", "description_html": "<p>Fixture Serum 30 ml.</p>",
           "seo_title": "Fixture Serum 30 ml", "seo_description": "Review the product label before publication.",
           "tags": ["serum"], "product_type": "Serum"}


class ProductAccuracyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binding = {"pd_no": "fixture-1", "retailer_name": PRODUCT["name"],
                        "official_url": "https://manufacturer.example.invalid/products/fixture-1",
                        "official_product_id": "SKU-FIXTURE-1"}
        self.capture = {"source_url": self.binding["official_url"], "official_product_id": "SKU-FIXTURE-1",
                        "captured_at": NOW.isoformat(),
                        "text": "Fixture\nFixture Serum\n30 ml\nSerum\nProvides 24-hour hydration.\nNot organic."}
        self.record = {**self.binding, "capture_file": accuracy.CAPTURE_DIR + "/fixture.json",
                       "facts": {key: {"value": value, "quote": value} for key, value in
                                 (("brand", "Fixture"), ("product_name", "Fixture Serum"), ("net_contents", "30 ml"))},
                       "statements": ["Provides 24-hour hydration."]}

    def put(self, relative, doc):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return target

    def install(self):
        path = self.put(accuracy.CAPTURE_DIR + "/fixture.json", self.capture)
        self.record["capture_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.put(accuracy.REGISTRY, {"schema_version": 1, "products": [self.binding]})
        self.put(accuracy.EVIDENCE, {"schema_version": 1, "products": [self.record]})

    def review(self, candidate=None, product=None):
        return accuracy.review_copy(product or PRODUCT, candidate if candidate is not None else NEUTRAL,
                                    NEUTRAL, self.root, now=NOW)

    def test_missing_evidence_retains_neutral_draft_but_never_approval(self):
        chosen, report = accuracy.select_copy(PRODUCT, NEUTRAL, NEUTRAL, self.root, now=NOW)
        self.assertEqual(chosen, NEUTRAL)
        self.assertFalse(report["fallback_used"])
        self.assertEqual(report["status"], "UNVERIFIED_DRAFT")
        self.assertEqual(report["reasons"], ["official_product_evidence_missing"])
        for field in ("publication_allowed", "safety_approval", "overall_legal_clearance"):
            self.assertIs(report[field], False)
        self.assertTrue(report["human_review_required"])

    def test_unsubstantiated_claims_quantities_and_tags_use_neutral_fallback(self):
        probes = [{"description_html": "<p>" + text + "</p>"} for text in
                  ("Contains 5% niacinamide.", "Provides 24-hour hydration.", "Made with 100% organic ingredients.",
                   "Net contents 100 ml.", "An invented gentle glow for every skin type.")]
        probes += [{"title": "Fixture Serum 100 ml"}, {"tags": ["organic"]},
                   {"seo_description": "Contains 5% niacinamide."}, {"product_type": "Medicine"}]
        for probe in probes:
            with self.subTest(probe=probe):
                candidate = {**NEUTRAL, **probe, "verified": True, "approved": True}
                chosen, report = accuracy.select_copy(PRODUCT, candidate, NEUTRAL, self.root, now=NOW)
                self.assertEqual(chosen, NEUTRAL)
                self.assertTrue(report["fallback_used"])
                self.assertTrue(report["unsupported_fields"])
                self.assertFalse(report["publication_allowed"])

    def test_exact_current_source_statement_is_accepted_without_clearance(self):
        self.install()
        candidate = {**NEUTRAL, "description_html": "<p>Provides 24-hour hydration.</p>"}
        chosen, report = accuracy.select_copy(PRODUCT, candidate, NEUTRAL, self.root, now=NOW)
        self.assertEqual(chosen, candidate)
        self.assertFalse(report["fallback_used"])
        self.assertEqual(report["status"], "SOURCE_BOUND_DRAFT_REVIEW_REQUIRED")
        self.assertEqual(len(report["evidence_digest"]), 64)
        self.assertNotIn("capture_file", json.dumps(report))
        self.assertNotIn("Provides 24", json.dumps(report))
        self.assertFalse(report["publication_allowed"])
        # A paraphrase or added claim is not covered by the exact quote.
        self.assertTrue(self.review({**candidate, "description_html": "<p>Provides 24-hour hydration and brightens skin.</p>"})["unsupported_fields"])

    def test_changed_product_shade_and_duplicate_registry_fail_closed(self):
        self.install()
        self.assertEqual(self.review(product={**PRODUCT, "name": "Fixture 세럼 50 ml"})["reasons"], ["retailer_product_identity_changed"])
        self.assertEqual(self.review(product={**PRODUCT, "pd_no": "other"})["reasons"], ["product_evidence_missing_or_duplicate"])
        self.put(accuracy.REGISTRY, {"schema_version": 1, "products": [self.binding, self.binding]})
        self.assertEqual(self.review()["reasons"], ["product_evidence_missing_or_duplicate"])

    def test_url_product_id_and_capture_binding_must_all_agree(self):
        changes = (("record", "official_url", "https://other.example.invalid/p/1"),
                   ("capture", "source_url", "https://other.example.invalid/p/1"),
                   ("capture", "official_product_id", "OTHER-SHADE"),
                   ("record", "retailer_name", "Other product"))
        for target, key, value in changes:
            with self.subTest(target=target, key=key):
                old = copy.deepcopy(getattr(self, target))
                getattr(self, target)[key] = value
                self.install()
                self.assertEqual(self.review()["evidence_status"], "UNVERIFIED")
                setattr(self, target, old)

    def test_snapshot_bytes_missing_tampering_and_symlinks_fail_closed(self):
        self.install()
        path = self.root / self.record["capture_file"]
        path.write_text(path.read_text() + " ")
        self.assertEqual(self.review()["reasons"], ["capture_hash_mismatch"])
        path.unlink()
        self.assertEqual(self.review()["evidence_status"], "UNVERIFIED")
        outside = self.put("outside.json", self.capture)
        path.symlink_to(outside)
        self.assertEqual(self.review()["reasons"], ["invalid_capture_path"])

    def test_future_stale_and_timezone_free_captures_do_not_pass(self):
        for stamp in ((NOW + timedelta(seconds=1)).isoformat(),
                      (NOW - timedelta(seconds=accuracy.MAX_AGE_SECONDS + 1)).isoformat(), "2026-10-18T12:00:00", "invalid"):
            with self.subTest(stamp=stamp):
                self.capture["captured_at"] = stamp
                self.install()
                self.assertEqual(self.review()["evidence_status"], "UNVERIFIED")

    def test_unquoted_facts_and_partial_negation_are_not_evidence(self):
        for field, value in (("brand", "Unknown Brand"), ("ingredients", "organic")):
            with self.subTest(field=field):
                old = copy.deepcopy(self.record)
                self.record["facts"][field] = {"value": value, "quote": value}
                self.install()
                self.assertEqual(self.review()["reasons"], ["fact_not_an_exact_source_quote"])
                self.record = old
        self.record["statements"] = ["organic"]
        self.install()
        self.assertEqual(self.review()["reasons"], ["statement_not_an_exact_source_quote"])

    def test_brand_and_net_contents_conflict_are_explicit_holds(self):
        self.install()
        for key, value, conflict in (("brand_english", "Bonsep", "brand"), ("net_contents", "100 ml", "net_contents")):
            with self.subTest(key=key):
                report = self.review(product={**PRODUCT, key: value})
                self.assertIn(conflict, report["source_conflicts"])
                self.assertEqual(report["status"], "UNVERIFIED_DRAFT")
        self.assertEqual(self.review(product={**PRODUCT, "net_contents": "30mL"})["source_conflicts"], [])

    def test_harmful_markup_or_appended_unverified_text_is_not_rendered(self):
        for html in ('<p onclick="alert(1)">Fixture Serum 30 ml.</p>',
                     '<script>Fixture Serum 30 ml.</script>', '<p>Fixture Serum 30 ml.</p><img src="x">',
                     '<p>Fixture Serum 30 ml.</p><p>Guaranteed results.</p>'):
            chosen, report = accuracy.select_copy(PRODUCT, {**NEUTRAL, "description_html": html}, NEUTRAL, self.root, now=NOW)
            self.assertEqual(chosen, NEUTRAL)
            self.assertIn("description_html", report["unsupported_fields"])

    def test_invalid_schemas_and_nonfinite_model_output_keep_fallback(self):
        for candidate in (None, [], {}, {**NEUTRAL, "tags": "organic"}, {**NEUTRAL, "title": float("nan")}):
            chosen, report = accuracy.select_copy(PRODUCT, candidate, NEUTRAL, self.root, now=NOW)
            self.assertEqual(chosen, NEUTRAL)
            self.assertTrue(report["fallback_used"])
        self.install()
        for version in (True, 2, "1"):
            self.put(accuracy.REGISTRY, {"schema_version": version, "products": [self.binding]})
            self.assertEqual(self.review()["reasons"], ["invalid_evidence_schema"])

    def test_recheck_ignores_saved_success_and_rebinds_changed_bytes(self):
        self.install()
        first = self.review()
        self.capture["text"] += "\nAn additional recorded fact."
        self.install()
        second = self.review()
        self.assertNotEqual(first["evidence_digest"], second["evidence_digest"])
        candidate = {**NEUTRAL, "description_html": "<p>Unverified new claim.</p>", "product_accuracy": first}
        self.assertTrue(self.review(candidate)["unsupported_fields"])

    def test_gate_signature_rechecks_evidence_bytes_revocation_and_expiry(self):
        self.install()
        data = self.root / "data"
        paths = {key: data / (key.lower() + ".json") for key in
                 ("PRODUCT_MASTER", "GOSI", "LABELS", "PRICING", "LEGAL", "RECOMMENDATIONS")}
        with patch.multiple(gate_signature, DATA=data, COMMERCE_STRATEGY=self.root / "policy.json", **paths), \
             patch.object(gate_signature, "current_recommendations", return_value=[PRODUCT]), \
             patch.object(accuracy, "datetime", wraps=datetime) as clock:
            clock.now.return_value = NOW
            signature = gate_signature.agent_input_signature([PRODUCT])
            gate = {"agent_input_signature": signature}
            self.assertEqual(gate_signature.stale_reason(gate), "")
            self.capture["text"] += "\nChanged current source fact."
            self.install()
            self.assertIn("masked/product_accuracy_evidence", gate_signature.stale_reason(gate))
            gate["agent_input_signature"] = gate_signature.agent_input_signature([PRODUCT])
            self.assertEqual(gate_signature.stale_reason(gate), "")
            clock.now.return_value = NOW + timedelta(seconds=accuracy.MAX_AGE_SECONDS + 1)
            self.assertIn("masked/product_accuracy_evidence", gate_signature.stale_reason(gate))
            clock.now.return_value = NOW
            (self.root / accuracy.EVIDENCE).unlink()
            self.assertIn("masked/product_accuracy_evidence", gate_signature.stale_reason(gate))
            for secret in ("capture_file", "product_accuracy_evidence.private.json", "Provides 24-hour", "manufacturer.example"):
                self.assertNotIn(secret, json.dumps(signature))

    def test_private_evidence_and_captures_are_git_ignored(self):
        repo = Path(__file__).resolve().parents[1]
        for relative in (accuracy.EVIDENCE, accuracy.CAPTURE_DIR + "/fixture.json"):
            checked = subprocess.run(["git", "-C", str(repo), "check-ignore", "--no-index", "-q", relative],
                                     capture_output=True, check=False)
            self.assertEqual(checked.returncode, 0, relative)

    def test_import_csv_never_exports_held_human_text_even_with_old_ready_gate(self):
        source = self.put("copy.json", {"items": [{"pd_no": PRODUCT["pd_no"], "copy_status": "review_required",
                                                   "copy": NEUTRAL}]})
        self.put("data/listing_gate.json", {"items": [{"pd_no": PRODUCT["pd_no"], "ready": True}]})
        report = self.root / "report.json"
        with patch.multiple(csv_builder, ROOT=self.root, COPY=source, PRICING=self.root / "missing.json",
                            STATUS=self.root / "missing.json", OUT=self.root / "out.csv", REPORT=report), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(csv_builder.main(), 0)
        result = json.loads(report.read_text())
        self.assertEqual(result["rows"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "product_accuracy_copy_review_required")

    def test_gemini_main_uses_neutral_draft_after_unsupported_model_output(self):
        src = self.put("source.json", {"recommendations": [PRODUCT]})
        gate = self.put("gate.json", {"agent_input_signature": {}, "items": [{"pd_no": PRODUCT["pd_no"], "agent_ready": True}]})
        output = self.root / "out.json"
        model_copy = {**NEUTRAL, "description_html": "<p>Contains 5% niacinamide.</p>"}
        with patch.multiple(gemini, ROOT=self.root, SRC=src, GATE=gate, FULL=self.root / "missing.json", OUT=output), \
             patch.object(gemini, "_agent_input_signature", return_value={}), \
             patch.object(gemini, "pick_model", return_value=("test-model", "synthetic")), \
             patch.object(gemini, "generate", return_value=(model_copy, "")), \
             patch.object(gemini.time, "sleep"), patch.dict(gemini.os.environ, {"GEMINI_API_KEY": "synthetic-test"}), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(gemini.main(), 0)
        row = json.loads(output.read_text())["items"][0]
        self.assertEqual(row["copy"], local.local_copy(PRODUCT["name"], {"pd_no": PRODUCT["pd_no"], "agent_ready": True}))
        self.assertEqual(row["copy_status"], "ok")
        self.assertTrue(row["product_accuracy"]["fallback_used"])
        self.assertFalse(row["product_accuracy"]["publication_allowed"])

    def test_generators_hold_even_neutral_text_when_source_quantity_conflicts(self):
        self.install()
        src = self.put("source.json", {"recommendations": [PRODUCT]})
        gate_row = {"pd_no": PRODUCT["pd_no"], "agent_ready": True, "us_label": {"net_contents": "100 ml"}}
        gate = self.put("gate.json", {"agent_input_signature": {}, "items": [gate_row]})
        for builder in (local, gemini):
            output = self.root / (builder.__name__ + "-out.json")
            with patch.multiple(builder, ROOT=self.root, SRC=src, GATE=gate, OUT=output), \
                 patch.object(gemini, "FULL", self.root / "missing.json"), \
                 patch.object(gemini, "_agent_input_signature", return_value={}), \
                 patch.object(gemini, "pick_model", return_value=("test-model", "synthetic")), \
                 patch.object(gemini, "generate", return_value=(NEUTRAL, "")), \
                 patch.object(gemini.time, "sleep"), patch.dict(gemini.os.environ, {"GEMINI_API_KEY": "synthetic-test"}), \
                 patch.object(accuracy, "datetime", wraps=datetime) as clock, \
                 redirect_stdout(io.StringIO()):
                clock.now.return_value = NOW
                self.assertEqual(builder.main(), 0)
            doc = json.loads(output.read_text())
            self.assertEqual(doc["items"][0]["copy_status"], "review_required")
            self.assertEqual(doc["items"][0]["product_accuracy"]["source_conflicts"], ["net_contents"])
            self.assertEqual(doc["ok"], 0)
            self.assertEqual(doc["review_required"], 1)


if __name__ == "__main__":
    unittest.main()
