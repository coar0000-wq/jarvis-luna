#!/usr/bin/env python3
"""Offline regression tests. Only temporary fixtures, no network or Git commits."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import build_shopify_import_csv as builder
from scripts.publish_transaction import PublishError, deletion_authorized, overlay, removed_identities, sha

POLICY = json.loads((ROOT / "config/publish_policy.json").read_text(encoding="utf-8"))
OLD_IDS = ["1049276", "1055167", "1049275", "1067498", "1072554", "1075857", "1049285", "1027327", "1059834", "1042619"]
CURRENT_IDS = ["1049276", "1055167", "1049275", "1067498", "1068721", "1053482", "1074979", "1068733"]
RETIRED = sorted(set(OLD_IDS) - set(CURRENT_IDS))


class ImportReportPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "data/daiso_real").mkdir(parents=True)
        (self.root / "config").mkdir()
        self.write("config/publish_policy.json", POLICY)
        self.write("data/pricing_model.json", {"market_benchmark": {"p25": 15, "median": 22.49}, "scenarios": {}})
        self.write("data/daiso_real/collection_status.json", {"fx": {"usd_to_krw": 1400}})
        self.unrelated = {"path": "data/another_report.json", "base_sha256": "keep", "ids": ["old"], "reason": "Unrelated reason retained", "policy_ref": "another_producer"}
        self.write("data/publish_deletions.json", {"schema_version": 1, "deletions": [self.unrelated]})
        self.build(OLD_IDS)
        self.base = (self.root / builder.REPORT_REL).read_bytes()
        self.build(CURRENT_IDS)
        self.replacement = (self.root / builder.REPORT_REL).read_bytes()

    def write(self, rel, doc):
        (self.root / rel).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    def build(self, ids):
        self.write("data/shopify_listing_copy.json", {"items": [{"pd_no": i, "name_ko": "fixture", "copy": None} for i in ids]})
        self.write("data/listing_gate.json", {"total": len(ids), "ready": 0, "items": [{"pd_no": i, "ready": False, "blocked_by": ["manufacturer_safety_record_missing", "us_label", "owner_deleted"]} for i in ids]})
        with patch.multiple(builder, ROOT=self.root, COPY=self.root / "data/shopify_listing_copy.json", PRICING=self.root / "data/pricing_model.json", STATUS=self.root / "data/daiso_real/collection_status.json", OUT=self.root / "data/shopify_import.csv", REPORT=self.root / builder.REPORT_REL), redirect_stdout(io.StringIO()):
            self.assertEqual(builder.main(), 0)

    def record(self):
        def git_read(args, **kwargs):
            self.assertEqual(args[:3], ["git", "-C", str(self.root)])
            if args[3:] == ["rev-parse", "HEAD"]:
                return SimpleNamespace(stdout="a" * 40 + "\n")
            self.assertEqual(args[3:], ["show", "a" * 40 + ":" + builder.REPORT_REL])
            return SimpleNamespace(stdout=self.base)
        with patch.object(builder.subprocess, "run", side_effect=git_read):
            return builder.record_publication(self.root)

    def manifest(self):
        return json.loads((self.root / "data/publish_deletions.json").read_text(encoding="utf-8"))

    def test_reproduces_failure_then_accepts_exact_report(self):
        ids = removed_identities(json.loads(self.base), json.loads(self.replacement), POLICY, where=builder.REPORT_REL)
        self.assertEqual(sorted(ids), RETIRED)
        with self.assertRaisesRegex(PublishError, "identity/field removal"):
            overlay(builder.REPORT_REL, self.base, self.replacement, self.base, POLICY, {})
        self.assertEqual(self.record()["retired_skipped_ids"], RETIRED)
        self.assertEqual(overlay(builder.REPORT_REL, self.base, self.replacement, self.base, POLICY, self.manifest()), self.replacement)
        entry = self.manifest()["deletions"][-1]
        self.assertEqual(entry["base_sha256"], sha(self.base))
        self.assertEqual(entry["replacement_sha256"], sha(self.replacement))
        self.assertEqual(entry["base_commit"], "a" * 40)
        self.assertFalse(entry["delete_file"])

    def test_eight_still_blocked_and_csv_header_only(self):
        report = json.loads(self.replacement)
        self.assertEqual(report["rows"], 0)
        self.assertEqual(len(report["skipped"]), 8)
        for row in report["skipped"]:
            for reason in ("manufacturer_safety_record_missing", "us_label", "owner_deleted"):
                self.assertIn(reason, row["reason"])
        self.assertEqual(len((self.root / "data/shopify_import.csv").read_text(encoding="utf-8").splitlines()), 1)

    def test_root_and_nested_field_removals_refused_without_manifest_write(self):
        original = (self.root / "data/publish_deletions.json").read_bytes()
        for key in ("vendor", "게시전_확인사항", "market_benchmark"):
            bad = json.loads(self.replacement)
            del bad[key]
            self.write(builder.REPORT_REL, bad)
            with self.assertRaises(ValueError):
                self.record()
        bad = json.loads(self.replacement)
        del bad["market_benchmark"]["p25"]
        self.write(builder.REPORT_REL, bad)
        with self.assertRaises(ValueError):
            self.record()
        self.assertEqual((self.root / "data/publish_deletions.json").read_bytes(), original)

    def test_surviving_row_evidence_and_warning_removals_refused(self):
        for mutate in (lambda doc: doc["skipped"][0].pop("reason"), lambda doc: doc["게시전_확인사항"].pop()):
            bad = json.loads(self.replacement)
            mutate(bad)
            self.write(builder.REPORT_REL, bad)
            with self.assertRaises(ValueError):
                self.record()

    def test_duplicate_or_missing_identity_refused(self):
        for mutate in (lambda doc: doc["skipped"].append(doc["skipped"][0]), lambda doc: doc["skipped"][0].pop("pd_no")):
            bad = json.loads(self.replacement)
            mutate(bad)
            self.write(builder.REPORT_REL, bad)
            with self.assertRaises(ValueError):
                self.record()

    def test_stale_hashes_and_file_delete_rejected(self):
        self.record()
        manifest = self.manifest()
        for base, replacement in ((self.base + b" ", self.replacement), (self.base, self.replacement + b" ")):
            self.assertFalse(deletion_authorized(builder.REPORT_REL, base, RETIRED, manifest, replacement=replacement))
        self.assertFalse(deletion_authorized(builder.REPORT_REL, self.base, None, manifest))

    def test_concurrent_report_replacement_rejected(self):
        self.record()
        remote = json.loads(self.base)
        remote["vendor"] = "concurrent vendor"
        raw = (json.dumps(remote, ensure_ascii=False, indent=2) + "\n").encode()
        with self.assertRaisesRegex(PublishError, "replacement snapshot is not authorized|competing"):
            overlay(builder.REPORT_REL, self.base, self.replacement, raw, POLICY, self.manifest())

    def test_product_label_and_owner_deleted_constraints_not_waived(self):
        self.record()
        for rel in ("data/product_master.json", "data/daiso_real/daiso_us_labels.json", "data/operations/state.json"):
            old = b'{"items":[{"pd_no":"1072554","manufacturer_safety_record":"present","us_label":"present","owner_deleted":true}]}'
            new = b'{"items":[]}'
            with self.assertRaises(PublishError):
                overlay(rel, old, new, old, POLICY, self.manifest())

    def test_idempotent_and_unrelated_entries_preserved(self):
        self.record()
        before = (self.root / "data/publish_deletions.json").read_bytes()
        self.record()
        self.assertEqual((self.root / "data/publish_deletions.json").read_bytes(), before)
        self.assertEqual(self.manifest()["deletions"][0], self.unrelated)

    def test_missing_hash_rejected_for_builder_and_alternate_policy(self):
        self.record()
        for policy_ref in (builder.PUBLICATION_REF, "legacy_report_producer"):
            manifest = self.manifest()
            entry = manifest["deletions"][-1]
            entry.pop("replacement_sha256")
            entry["policy_ref"] = policy_ref
            self.assertFalse(deletion_authorized(builder.REPORT_REL, self.base, RETIRED, manifest, replacement=self.replacement))
            with self.assertRaisesRegex(PublishError, "identity/field removal"):
                overlay(builder.REPORT_REL, self.base, self.replacement, self.base, POLICY, manifest)
        # An earlier alternate entry must not bypass a stale exact entry either.
        manifest = self.manifest()
        alternate = dict(manifest["deletions"][-1])
        alternate.pop("replacement_sha256")
        alternate["policy_ref"] = "legacy_report_producer"
        manifest["deletions"].insert(0, alternate)
        with self.assertRaises(PublishError):
            overlay(builder.REPORT_REL, self.base, self.replacement + b" ", self.base, POLICY, manifest)

    def test_blank_null_and_scalar_type_downgrades_refused(self):
        original = (self.root / "data/publish_deletions.json").read_bytes()
        for value in ("", "  ", None, 0, False):
            bad = json.loads(self.replacement)
            bad["skipped"][0]["reason"] = value
            self.write(builder.REPORT_REL, bad)
            with self.assertRaises(ValueError):
                self.record()
            bad = json.loads(self.replacement)
            bad["pricing_model"] = value
            self.write(builder.REPORT_REL, bad)
            with self.assertRaises(ValueError):
                self.record()
        for value in ("", None, False, "0"):
            bad = json.loads(self.replacement)
            bad["rows"] = value
            self.write(builder.REPORT_REL, bad)
            with self.assertRaises(ValueError):
                self.record()
        self.assertEqual((self.root / "data/publish_deletions.json").read_bytes(), original)

    def test_current_numeric_observations_can_legitimately_be_zero(self):
        bad = json.loads(self.replacement)
        bad["sell_price_usd"] = 0
        bad["market_benchmark"]["p25"] = 0.0
        self.write(builder.REPORT_REL, bad)
        self.record()

    def test_actual_owner_deleted_1049275_cannot_be_removed_by_report_entry(self):
        self.record()
        old = b'{"items":[{"pd_no":"1049275","owner_deleted":true,"manufacturer_safety_record":"missing","us_label":"blocked"}]}'
        new = b'{"items":[]}'
        for rel in ("data/daiso_real/products.json", "data/product_master.json", "data/daiso_real/daiso_us_labels.json"):
            self.assertFalse(deletion_authorized(rel, old, ["1049275"], self.manifest(), replacement=new))
            with self.assertRaises(PublishError):
                overlay(rel, old, new, old, POLICY, self.manifest())
        # The diagnostic itself also cannot blank the blocking reason for 1049275.
        bad = json.loads(self.replacement)
        next(row for row in bad["skipped"] if row["pd_no"] == "1049275")["reason"] = None
        self.write(builder.REPORT_REL, bad)
        with self.assertRaises(ValueError):
            self.record()

    def test_offline_verification_disables_model_paths_only_when_requested(self):
        workflow = (ROOT / ".github/workflows/shopify-listing-copy.yml").read_text(encoding="utf-8")
        self.assertIn("      offline_verification:\n        description:", workflow)
        dispatch_input = workflow.split("      offline_verification:\n", 1)[1].split("  # S등급", 1)[0]
        for required in ("type: boolean", "required: false", "default: false"):
            self.assertIn(required, dispatch_input)
        self.assertIn("TYPESAFE_ENABLED: ${{ github.ref == 'refs/heads/main' && inputs.offline_verification != true && '1' || '0' }}", workflow)
        self.assertIn("GEMINI_FALLBACK_ENABLED: ${{ inputs.offline_verification == true && '0' || '1' }}", workflow)
        direct_copy = workflow.split("      - name: Gemini 영문 카피 생성\n", 1)[1].split("      #", 1)[0]
        self.assertIn("if: ${{ steps.guard.outputs.ready == 'true' && inputs.offline_verification != true }}", direct_copy)
        self.assertIn("python scripts/gemini_listing_copy.py", direct_copy)
        # Offline verification retains local generation, gates, and publication.
        for command in ("python scripts/build_listing_copy_local.py", "python scripts/build_listing_gate.py", "python scripts/build_shopify_import_csv.py", "uses: ./.github/actions/publish"):
            self.assertIn(command, workflow)

    def test_workflow_records_after_generation_before_publish(self):
        workflow = (ROOT / ".github/workflows/shopify-listing-copy.yml").read_text(encoding="utf-8")
        self.assertLess(workflow.index("python scripts/build_shopify_import_csv.py"), workflow.index("--record-publication"))
        self.assertLess(workflow.index("--record-publication"), workflow.index("uses: ./.github/actions/publish"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
