"""Offline checks: local AEO drafts never imply publication or mutate Shopify."""
import ast
from contextlib import ExitStack, redirect_stdout
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
spec = importlib.util.spec_from_file_location("aeo_inspection", SCRIPTS / "apply_shopify_aeo_and_obsidian.py")
aeo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aeo)
INITIAL_REPORT = copy.deepcopy(aeo.REPORT)


class AeoInspectionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.network = self.stack.enter_context(patch.object(
            aeo.urllib.request, "urlopen", side_effect=AssertionError("offline test: no network")))
        self.stack.enter_context(patch.object(aeo, "APPLY", False))
        self.stack.enter_context(patch.dict(aeo.REPORT, copy.deepcopy(INITIAL_REPORT), clear=True))
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        root = Path(self.temp)
        self.stack.enter_context(patch.object(aeo, "SHOPIFY_EXPORT_DIR", root / "templates_shopify"))
        self.stack.enter_context(patch.object(aeo, "OBSIDIAN_DIR", root / "notes"))
        self.stack.enter_context(patch.object(aeo, "DATA_DIR", root / "data"))
        self.stack.enter_context(patch.object(aeo, "REPORT_PATH", root / "data/report.json"))
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def test_apply_is_blocked_before_auth_or_network(self):
        with patch.object(aeo, "APPLY", True), patch.object(aeo, "resolve_token") as auth:
            with self.assertRaisesRegex(RuntimeError, "live apply is disabled"):
                aeo.deploy_to_shopify_live()
            auth.assert_not_called()
        self.network.assert_not_called()

    def test_apply_blocks_local_assets_too(self):
        with patch.object(aeo, "APPLY", True):
            with self.assertRaisesRegex(RuntimeError, "live apply is disabled"):
                aeo.write_local_assets()
        self.assertEqual(list(Path(self.temp).iterdir()), [])
        self.network.assert_not_called()

    def test_cli_apply_blocks_before_local_files_or_auth(self):
        with patch.dict(os.environ, {"APPLY": "1"}), patch.object(Path, "write_text") as write, patch.object(Path, "mkdir") as mkdir:
            with self.assertRaisesRegex(RuntimeError, "live apply is disabled"):
                runpy.run_path(str(SCRIPTS / "apply_shopify_aeo_and_obsidian.py"), run_name="__main__")
        write.assert_not_called()
        mkdir.assert_not_called()
        self.network.assert_not_called()

    def test_all_mutations_are_blocked_even_if_called_directly(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "post", "put"):
            with self.subTest(method=method), self.assertRaises(RuntimeError):
                aeo.shopify_request(method, "products/1.json", {"product": {"id": 1}})
        for payload in ({"unexpected": True}, {}, []):
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                aeo.shopify_request("GET", "products.json", payload)
        self.network.assert_not_called()

    def test_no_dead_remote_write_or_theme_insert_branches(self):
        tree = ast.parse((SCRIPTS / "apply_shopify_aeo_and_obsidian.py").read_text())
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == "shopify_request"]
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertEqual(ast.literal_eval(call.args[0]), "GET")
            self.assertEqual(len(call.args), 2)
            self.assertEqual(call.keywords, [])
        self.assertNotIn("{% render", (SCRIPTS / "apply_shopify_aeo_and_obsidian.py").read_text())

    def inspect(self, products, layout="<head></head>"):
        def response(method, endpoint, payload=None):
            self.assertEqual(method, "GET")
            self.assertIsNone(payload)
            if endpoint == "themes.json":
                return {"themes": [{"id": 1, "role": "main"}]}
            if endpoint == "themes/1/assets.json?asset[key]=layout/theme.liquid":
                return {"asset": {"value": layout}}
            self.assertEqual(endpoint, "products.json?limit=50")
            return {"products": products}
        before = copy.deepcopy(products)
        with patch.object(aeo, "resolve_token", return_value="fixture-only"), patch.object(aeo, "shopify_request", side_effect=response) as request:
            aeo.deploy_to_shopify_live()
        self.assertEqual(request.call_count, 3)
        self.assertEqual(products, before)
        self.network.assert_not_called()

    def test_inspection_only_uses_reads_and_never_claims_updates(self):
        self.inspect([{"id": 1, "title": "Fixture", "product_type": "Face Serum", "body_html": ""}])
        self.assertEqual(aeo.REPORT["products_changed"], [])
        self.assertEqual(aeo.REPORT["products_already_done"], 0)
        self.assertEqual(aeo.REPORT["assets"], [])
        self.assertEqual(aeo.REPORT["products_review"][0]["status"], "source_review_required")
        self.assertFalse(aeo.REPORT["products_review"][0]["candidate_generated"])
        self.assertFalse(aeo.REPORT["products_review"][0]["facts_verified"])
        self.assertFalse(aeo.REPORT["products_review"][0]["publication_allowed"])
        self.assertEqual(aeo.REPORT["product_scope"], "first_page_only_limit_50")
        self.assertEqual(aeo.REPORT["theme_liquid_patch"], "not_attempted_review_only")
        self.assertFalse(aeo.REPORT["publication_verified"])
        self.assertFalse(aeo.OBSIDIAN_DIR.exists())
        self.assertFalse(aeo.SHOPIFY_EXPORT_DIR.exists())

    def test_legacy_html_and_snippet_reference_do_not_mean_approved_or_installed(self):
        original = '<p>Original</p><div class="ai-semantic-summary">Unreviewed legacy text</div>'
        self.assertEqual(aeo.build_aeo_semantic_block("Fixture", original, "Serum"), original)
        self.inspect([{"id": 2, "title": "Fixture", "body_html": original}], "{% render 'ai-agent-schema' %}")
        self.assertEqual(aeo.REPORT["products_review"][0]["status"], "legacy_content_review_required")
        self.assertEqual(aeo.REPORT["products_already_done"], 0)
        self.assertEqual(aeo.REPORT["products_changed"], [])
        observation = aeo.REPORT["theme_inspection"]
        self.assertTrue(observation["legacy_snippet_reference_observed"])
        self.assertFalse(observation["rendered_schema_verified"])
        self.assertFalse(observation["public_output_verified"])
        self.assertFalse(aeo.OBSIDIAN_DIR.exists())

    def test_existing_safe_draft_is_still_review_required(self):
        html = '<p>Original</p><!-- aeo-review-draft:start --><p>Existing draft</p><!-- aeo-review-draft:end -->'
        self.inspect([{"id": 2, "title": "Fixture", "product_type": "Face Serum", "body_html": html}])
        self.assertEqual(aeo.REPORT["products_review"][0]["status"], "source_review_required")
        self.assertEqual(aeo.REPORT["products_already_done"], 0)

    def test_local_generation_uses_review_only_paths_and_preserves_existing_liquid(self):
        existing = {}
        for rel in ("templates/llms.txt.liquid", "templates/agents.md.liquid", "snippets/ai-agent-schema.liquid"):
            path = aeo.SHOPIFY_EXPORT_DIR / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            existing[path] = b"fixture: preserve exact old bytes\r\n"
            path.write_bytes(existing[path])
        aeo.write_local_assets()
        first = {p.relative_to(aeo.SHOPIFY_EXPORT_DIR): p.read_bytes() for p in aeo.SHOPIFY_EXPORT_DIR.rglob("*") if p.is_file()}
        aeo.write_local_assets()
        self.assertEqual({p.relative_to(aeo.SHOPIFY_EXPORT_DIR): p.read_bytes() for p in aeo.SHOPIFY_EXPORT_DIR.rglob("*") if p.is_file()}, first)
        self.assertEqual(set(aeo.SHOPIFY_EXPORT_DIR.rglob("*.liquid")), set(existing))
        for path, raw in existing.items():
            self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(len(aeo.REPORT["local_review_assets"]), 3)
        self.assertTrue(all(row["status"] == "local_review_only" and not row["deployable"] for row in aeo.REPORT["local_review_assets"]))
        self.assertEqual(aeo.REPORT["assets"], [])
        self.network.assert_not_called()

    def test_fresh_generation_never_creates_active_liquid_or_claims(self):
        aeo.write_local_assets()
        self.assertEqual(list(aeo.SHOPIFY_EXPORT_DIR.rglob("*.liquid")), [])
        docs = list((aeo.SHOPIFY_EXPORT_DIR / "review").glob("*.review.md"))
        self.assertEqual(len(docs), 3)
        for doc in docs:
            text = doc.read_text()
            self.assertIn("DO NOT UPLOAD", text)
            self.assertIn("local_review_only", text)
            for unsafe in ("{%", "{{", "<script", "FDA/MoCRA compliant", "verified reviews", "high-efficacy", "barrier-safe", "5–10", "30-day", "FreeReturn", '"reviewCount"', '"priceValidUntil"', '"mpn"', "/.well-known/ucp", "/api/ucp/mcp"):
                self.assertNotIn(unsafe, text)
        hub = (aeo.OBSIDIAN_DIR / "00_REA_Shopify_AEO_Master_Hub.md").read_text()
        self.assertIn("publication_verified: false", hub)
        self.assertIn("검토 계획", hub)
        for unsupported in ("+15%", "44%", "무료배송", "+2%", "+3%", "UCP-Ready", "AEO-Optimized", "자동 신디케이션", "필수 삽입"):
            self.assertNotIn(unsupported, hub)
        self.assertIn("https://developers.google.com/search/docs/appearance/ai-features", hub)
        self.network.assert_not_called()

    def test_summary_does_not_promote_unverified_identity_or_type(self):
        original = '<p class="human">Exact original &amp; text.</p>\r\n'
        for title, kind in (
            ('Fixture', 'Face Serum'),
            ('Fixture <script>alert("x")</script> & serum', 'Face Serum <b>&</b>'),
            ('FDA-approved serum for sensitive skin', 'Safe for all sensitive skin; use twice daily'),
            ('Verified five-star reviews', 'Free returns and 5-day shipping'),
        ):
            with self.subTest(title=title, kind=kind):
                self.assertEqual(aeo.build_aeo_semantic_block(title, original, kind), original)
                self.assertEqual(aeo.build_aeo_semantic_block(title, '', kind), '')
        self.network.assert_not_called()

    def test_summary_is_idempotent_and_preserves_all_existing_content(self):
        original = ('<p>Human text.</p><!-- aeo-review-draft:start -->'
                    '<p>Unreviewed earlier draft</p><!-- aeo-review-draft:end -->'
                    '<p>Human content after an earlier block.</p>')
        first = aeo.build_aeo_semantic_block("First", original, "Serum")
        self.assertEqual(first, original)
        self.assertEqual(aeo.build_aeo_semantic_block("First", first, "Serum"), original)
        self.assertEqual(aeo.build_aeo_semantic_block("Second", first, "Cream"), original)
        self.assertEqual(aeo.build_aeo_semantic_block("", None), "")

    def test_summary_does_not_infer_directions_suitability_or_policies(self):
        self.assertEqual(aeo.build_aeo_semantic_block("Fixture", "", "Face Serum"), "")
        self.assertEqual(aeo.build_aeo_semantic_block("", "<p>Original</p>"), "<p>Original</p>")
        self.assertEqual(aeo.build_aeo_semantic_block("알 수 없는 상품", "<p>Original</p>"), "<p>Original</p>")

    def test_admin_fields_remain_observations_without_candidate_generation(self):
        product = {"id": 9, "title": "FDA-approved serum for sensitive skin",
                   "product_type": "Safe for all sensitive skin; use twice daily",
                   "body_html": "<p>Existing merchant text.</p>"}
        with patch.object(aeo, "build_aeo_semantic_block", side_effect=AssertionError("no candidate generation")) as builder:
            self.inspect([product])
        builder.assert_not_called()
        row = aeo.REPORT["products_review"][0]
        self.assertEqual(row["status"], "source_review_required")
        self.assertEqual(row["source_fields"], {"title": product["title"], "product_type": product["product_type"]})
        self.assertEqual(row["source"], "admin_api_product_fields_unverified")
        self.assertFalse(row["facts_verified"])
        self.assertFalse(row["candidate_generated"])
        self.assertFalse(row["publication_allowed"])
        self.assertNotIn("faq", row)
        self.assertNotIn("recommendation_target", row)
        self.assertNotIn("description_html", row)

    def test_package_import_without_scripts_path_injection(self):
        result = subprocess.run(
            [sys.executable, "-B", "-c",
             "from scripts.apply_shopify_aeo_and_obsidian import build_aeo_semantic_block; "
             "assert build_aeo_semantic_block('Fixture', '<p>Original</p>', 'Serum') == '<p>Original</p>'"],
            cwd=ROOT, capture_output=True, text=True, check=False,
            env={**os.environ, "PYTHONPATH": "", "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stale_observations_never_survive_as_completed_work(self):
        aeo.REPORT.update(products_already_done=99, products_changed=[{"status": "updated"}],
                          assets=[{"status": "uploaded"}], publication_verified=True)
        self.inspect([{"id": 1, "title": "Fixture"}])
        self.assertEqual(aeo.REPORT["products_already_done"], 0)
        self.assertEqual(aeo.REPORT["products_changed"], [])
        self.assertEqual(aeo.REPORT["assets"], [])
        self.assertFalse(aeo.REPORT["publication_verified"])

    def test_no_credentials_means_no_remote_calls_or_fake_completion(self):
        with patch.object(aeo, "ACCESS_TOKEN", ""), patch.object(aeo, "CLIENT_ID", ""), patch.object(aeo, "CLIENT_SECRET", ""):
            aeo.deploy_to_shopify_live()
        self.network.assert_not_called()
        self.assertEqual(aeo.REPORT["products_seen"], 0)
        self.assertEqual(aeo.REPORT["products_changed"], [])
        self.assertEqual(aeo.REPORT["products_already_done"], 0)
        self.assertIsNone(aeo.REPORT["theme"])

    def test_report_retains_existing_keys_and_separates_observations(self):
        self.inspect([{"id": 1, "title": "Fixture"}])
        aeo.write_report()
        report = json.loads(aeo.REPORT_PATH.read_text())
        self.assertTrue({"store", "apply", "started_at", "finished_at", "theme", "assets", "theme_liquid_patch", "products_seen", "products_changed", "products_already_done", "errors"}.issubset(report))
        self.assertEqual(report["products_changed"], [])
        self.assertEqual(report["products_already_done"], 0)
        self.assertIn("products_review", report)
        self.assertIn("theme_inspection", report)

    def test_workflow_is_main_only_and_inspection_only(self):
        text = (ROOT / ".github/workflows/shopify-aeo-apply.yml").read_text(encoding="utf-8")
        for required in ("if: github.ref == 'refs/heads/main'", "ref: main", "APPLY: '0'", "options: ['0']"):
            self.assertIn(required, text)

    def test_regression_is_registered_in_both_verification_workflows(self):
        for filename in ("preflight.yml", "pages-verified.yml"):
            with self.subTest(workflow=filename):
                text = (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
                self.assertEqual(text.count("scripts/test_shopify_aeo_inspection.py"), 1)


if __name__ == "__main__":
    unittest.main()
