"""Synthetic, offline ACTIVE planning boundary tests. No storefront/API calls."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin
import plan_active_product_gallery as plan


class GalleryPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.media = self.root / "media"
        self.source = self.root / "source"
        self.media.mkdir()
        self.source.mkdir()
        a = self.source / "asset.png"
        b = self.media / "cdn.png"
        image = Image.new("RGB", (12, 10), (30, 40, 50))
        image.save(a)
        meta = PngImagePlugin.PngInfo()
        meta.add_text("container", "CDN re-encode")
        image.save(b, pnginfo=meta)
        self.url = "https://cdn.shopify.com/s/files/1/0001/files/photo.png?v=1"
        self.pid = "gid://shopify/Product/1"
        self.mid = "gid://shopify/MediaImage/2"
        self.current = [{"id": self.pid, "status": "ACTIVE", "title": "Serum 30 ml",
                         "images": [{"mediaId": self.mid, "url": self.url, "altText": "Serum"}],
                         "variants": [{"id": "variant-1", "sku": "DS-1-1", "price": "12.00"}],
                         "totalVariants": 1, "currencyCode": "USD"}]
        self.audit = {"products": [{"product_id": self.pid, "pd_no": "1", "status_observed": "ACTIVE",
                      "images_observed": 1, "media": [{"mediaId": self.mid, "index": 1,
                      "path": str(b), "url": self.url, "altText": "Serum", "role_observed": "hero",
                      **plan.fingerprint(b, self.media)}]}]}
        self.reuse = {"products": [{"product_id": self.pid, "pd_no": "1", "assets": [
                      {"pd_no": "1", "file": "asset.png", "sha256": plan.fingerprint(a, self.source)["sha256"],
                       "attached_media_id": self.mid, "attached_image_url": self.url, "role": "usage"}]}]}

    def build(self, **kw):
        return plan.build_plan(self.current, self.audit, media_root=self.media,
                               reuse_manifest=self.reuse, source_root=self.source, **kw)

    def test_pixel_identical_container_change_reuses_id_without_upload(self):
        report = self.build()
        self.assertEqual(report["summary"]["existing_asset_reuse_noops"], 1)
        c = report["products"][0]["reuse_checks"][0]
        self.assertFalse(c["binary_equal"])
        self.assertTrue(c["render_equivalent"])
        self.assertEqual(report["operations"], [])

    def test_existing_identity_order_and_input_fields_preserved(self):
        before = deepcopy((self.current, self.audit, self.reuse))
        report = self.build()
        self.assertEqual((self.current, self.audit, self.reuse), before)
        row = report["products"][0]
        self.assertEqual(row["preserve_media_ids_in_order"], [self.mid])
        self.assertEqual(row["protected_fields"]["variants"], self.current[0]["variants"])
        self.assertFalse(row["protected_fields"]["publications_observed"])

    def test_self_declared_ready_approved_and_executed_are_never_authority(self):
        self.audit.update(apply_authorized=True, github_deployed=True, team_execution_verified=True)
        self.audit["products"][0].update(approved=True, actual_label_verified=True)
        report = self.build(localizations={"1": {"status": "ok", "gallery_status": "ready", "gallery_complete": True}})
        self.assertFalse(report["authority"]["apply_authorized"])
        self.assertFalse(report["lifecycle"]["github_deployed"])
        self.assertFalse(report["lifecycle"]["shopify_applied"])
        self.assertFalse(report["lifecycle"]["admin_readback_verified"])
        self.assertEqual(report["summary"]["writes"], 0)
        self.assertFalse(report["products"][0]["media"][0]["automatic_variant_assignment"])

    def test_translation_ok_cannot_mean_gallery_ready(self):
        result = self.build(localizations={"1": {"status": "ok", "gallery_status": "review_required", "gallery_complete": False}})
        self.assertIn("translation_ok_is_not_gallery_readiness", result["products"][0]["holds"])

    def test_text_only_model_and_campaign_are_not_heroes(self):
        for role in ("marketing_text_only", "model_portrait", "campaign", "ingredient_marketing", "hero_model_campaign"):
            self.audit["products"][0]["media"][0]["role_observed"] = role
            row = self.build()["products"][0]
            self.assertIn("exact_product_hero_missing", row["holds"])
            self.assertFalse(row["apply_authorized"])

    def test_face_before_after_and_range_require_specific_review(self):
        expected = {"before_after_face": "claim_substantiation_review_required",
                    "model_portrait": "final_output_face_review_required",
                    "range_photo_not_included": "other_products_not_eligible_for_hero_or_variant"}
        for role, reason in expected.items():
            self.audit["products"][0]["media"][0]["role_observed"] = role
            self.assertIn(reason, self.build()["products"][0]["media"][0]["holds"])

    def test_comparison_and_staging_never_become_two_pack_variant(self):
        for role in ("pack_comparison", "secondary_two_jar_staging"):
            self.audit["products"][0]["media"][0]["role_observed"] = role
            self.audit["products"][0]["media"][0]["safe_for_automatic_variant_assignment"] = True
            media = self.build()["products"][0]["media"][0]
            self.assertIn("not_count_specific_variant_evidence", media["holds"])
            self.assertFalse(media["automatic_variant_assignment"])

    def test_quantity_conflict_and_trademark_observations_add_holds_only(self):
        r = self.build(findings={"1": {"hold_codes": ["net_quantity_conflict_g_ml"],
                       "media_issue_codes": {self.mid: ["residual_korean_trademark_review"]}, "approved": True}})
        self.assertIn("net_quantity_conflict_g_ml", r["products"][0]["holds"])
        self.assertIn("residual_korean_trademark_review", r["products"][0]["media"][0]["holds"])
        self.assertEqual(r["operations"], [])

    def test_korean_alt_not_silently_translated_or_erased(self):
        self.current[0]["images"][0]["altText"] = "브랜드 Serum"
        self.audit["products"][0]["media"][0]["altText"] = "브랜드 Serum"
        row = self.build()["products"][0]["media"][0]
        self.assertEqual(row["alt"], "브랜드 Serum")
        self.assertIn("english_alt_source_review_required", row["holds"])

    def test_incomplete_or_non_active_scope_rejected(self):
        for status in ("DRAFT", "ARCHIVED", None):
            self.current[0]["status"] = status
            with self.assertRaises(plan.InvalidInput): self.build()
        self.current[0]["status"] = "ACTIVE"
        self.audit["products"][0]["images_observed"] = 2
        with self.assertRaises(plan.InvalidInput): self.build()

    def test_extra_current_product_rejected(self):
        self.current.append({"id": "gid://shopify/Product/99"})
        with self.assertRaises(plan.InvalidInput): self.build()

    def test_duplicate_product_or_media_rejected(self):
        self.audit["products"].append(deepcopy(self.audit["products"][0]))
        with self.assertRaises(plan.InvalidInput): self.build()
        self.audit["products"].pop()
        self.current[0]["images"].append(deepcopy(self.current[0]["images"][0]))
        self.audit["products"][0]["media"].append(deepcopy(self.audit["products"][0]["media"][0]))
        self.audit["products"][0]["images_observed"] = 2
        with self.assertRaises(plan.InvalidInput): self.build()

    def test_snapshot_id_url_alt_drift_rejected(self):
        for key, value in (("mediaId", "gid://shopify/MediaImage/3"), ("url", self.url + "2"), ("altText", "changed")):
            before = deepcopy(self.current)
            self.current[0]["images"][0][key] = value
            with self.assertRaises(plan.InvalidInput): self.build()
            self.current = before

    def test_file_or_pixel_drift_holds_reupload(self):
        Image.new("RGB", (12, 10), (255, 0, 0)).save(self.media / "cdn.png")
        r = self.build()
        self.assertEqual(r["summary"]["held_reuse_candidates"], 1)
        self.assertIn("local_media_bytes_or_pixels_unverified", r["products"][0]["media"][0]["holds"])
        self.assertEqual(r["operations"], [])

    def test_source_hash_scope_and_url_binding_required(self):
        asset = self.reuse["products"][0]["assets"][0]
        for key, value in (("sha256", "a" * 64), ("pd_no", "2"), ("attached_media_id", "gid://shopify/MediaImage/3"),
                           ("attached_image_url", "https://cdn.shopify.com/other.png")):
            old = asset[key]
            asset[key] = value
            self.assertEqual(self.build()["summary"]["held_reuse_candidates"], 1)
            asset[key] = old

    def test_no_path_escape_or_unverified_fingerprint(self):
        self.assertIsNone(plan.fingerprint(self.source / "asset.png", self.media))
        self.assertIsNone(plan.fingerprint("../source/asset.png", self.media))
        self.assertIsNone(plan.fingerprint(None, self.media))
        self.assertFalse(plan.pixel_equal({}, {}))
        self.assertFalse(plan.pixel_equal({"width": 1}, {"width": 1}))

    def test_url_provenance_normalization_is_not_standalone_identity(self):
        self.assertEqual(plan.canonical_url(self.url), plan.canonical_url(self.url.replace("v=1", "v=2")))
        for value in ("http://cdn.shopify.com/a", "https://other.example/a", "https://secret@cdn.shopify.com/a"):
            self.assertIsNone(plan.canonical_url(value))

    def test_network_is_never_used_and_rerun_is_deterministic(self):
        def deny(*a, **kw): raise AssertionError("Network forbidden")
        with patch.object(socket.socket, "connect", deny), patch.object(socket, "create_connection", deny):
            self.assertEqual(self.build(), self.build())

    def test_snapshot_digest_changes_on_protected_price_change(self):
        first = self.build()["products"][0]["snapshot_digest"]
        self.current[0]["variants"][0]["price"] = "13.00"
        self.assertNotEqual(first, self.build()["products"][0]["snapshot_digest"])

    def test_cli_no_apply_flag_and_atomic_invalid_output_preservation(self):
        a, c, out = self.root / "audit.json", self.root / "current.json", self.root / "out.json"
        a.write_text(json.dumps(self.audit)); c.write_text(json.dumps(self.current)); out.write_text("existing")
        self.audit["products"][0]["status_observed"] = "DRAFT"
        a.write_text(json.dumps(self.audit))
        args = ["--current", str(c), "--audit", str(a), "--media-root", str(self.media), "--out", str(out)]
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(plan.main(args), 2)
        self.assertEqual(out.read_text(), "existing")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit): plan.main(args + ["--apply"])

    def test_cli_cannot_replace_input_document_or_asset(self):
        a, c = self.root / "audit.json", self.root / "current.json"
        a.write_text(json.dumps(self.audit)); c.write_text(json.dumps(self.current))
        args = ["--current", str(c), "--audit", str(a), "--media-root", str(self.media)]
        for output in (a, c, self.media / "cdn.png"):
            before = output.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(plan.main(args + ["--out", str(output)]), 2)
            self.assertEqual(output.read_bytes(), before)

    def test_malformed_optional_records_fail_closed(self):
        for options in ({"findings": ["bad"]}, {"localizations": ["bad"]},
                        {"findings": {"1": "bad"}}, {"localizations": {"1": "bad"}},
                        {"findings": {"1": {"hold_codes": "bad"}}},
                        {"findings": {"1": {"media_issue_codes": {self.mid: "bad"}}}}):
            with self.subTest(options=options), self.assertRaises(plan.InvalidInput):
                self.build(**options)

    def test_cli_uses_exclusive_temp_and_preserves_legacy_tmp_symlink(self):
        a, c, out = self.root / "audit.json", self.root / "current.json", self.root / "out.json"
        a.write_text(json.dumps(self.audit)); c.write_text(json.dumps(self.current))
        before = a.read_bytes()
        old_temp = self.root / "out.json.tmp"
        old_temp.symlink_to(a)
        args = ["--current", str(c), "--audit", str(a), "--media-root", str(self.media), "--out", str(out)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(plan.main(args), 0)
        self.assertEqual(a.read_bytes(), before)
        self.assertTrue(old_temp.is_symlink())
        self.assertEqual(json.loads(out.read_text())["operations"], [])

    def test_ci_registration_present(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/preflight.yml").read_text()
        self.assertEqual(workflow.count('python -B -m unittest discover -s scripts -p "test_active_product_gallery_plan.py"'), 1)

    def test_transparency_and_orientation_are_not_discarded(self):
        opaque = self.media / "opaque.png"
        transparent = self.media / "transparent.png"
        Image.new("RGBA", (12, 10), (30, 40, 50, 255)).save(opaque)
        Image.new("RGBA", (12, 10), (30, 40, 50, 0)).save(transparent)
        a, b = (plan.fingerprint(p, self.media) for p in (opaque, transparent))
        self.assertEqual(a["pixel_sha256"], b["pixel_sha256"])
        self.assertFalse(plan.pixel_equal(a, b))
        image = Image.new("RGB", (12, 10), (30, 40, 50))
        exif = image.getexif(); exif[274] = 6
        image.save(transparent, exif=exif)
        rotated = plan.fingerprint(transparent, self.media)
        self.assertEqual(rotated["render_width"], 10)
        self.assertEqual(rotated["render_height"], 12)
        self.assertFalse(plan.pixel_equal(a, rotated))

    def test_localization_changes_are_in_input_digest(self):
        a = self.build(localizations={"1": {"status": "ok", "gallery_status": "review_required"}})
        b = self.build(localizations={"1": {"status": "ok", "gallery_status": "ready", "gallery_complete": True}})
        self.assertNotEqual(a["input_digests"]["localizations"], b["input_digests"]["localizations"])


if __name__ == "__main__":
    unittest.main()
