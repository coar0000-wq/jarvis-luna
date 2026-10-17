"""Offline checks: the imported AEO proposal must never mutate Shopify."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("aeo_inspection", ROOT / "scripts/apply_shopify_aeo_and_obsidian.py")
aeo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aeo)


class AeoInspectionTests(unittest.TestCase):
    def test_apply_is_blocked_before_auth_or_network(self):
        with patch.object(aeo, "APPLY", True), patch.object(aeo, "resolve_token") as auth, patch.object(aeo.urllib.request, "urlopen") as network:
            with self.assertRaisesRegex(RuntimeError, "live apply is disabled"):
                aeo.deploy_to_shopify_live()
            auth.assert_not_called()
            network.assert_not_called()

    def test_all_mutations_are_blocked_even_if_called_directly(self):
        with patch.object(aeo.urllib.request, "urlopen") as network:
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                with self.subTest(method=method), self.assertRaises(RuntimeError):
                    aeo.shopify_request(method, "products/1.json", {"product": {"id": 1}})
            with self.assertRaises(RuntimeError):
                aeo.shopify_request("GET", "products.json", {"unexpected": True})
            network.assert_not_called()

    def test_inspection_only_uses_reads_and_never_claims_updates(self):
        def response(method, endpoint, payload=None):
            self.assertEqual(method, "GET")
            self.assertIsNone(payload)
            if endpoint == "themes.json":
                return {"themes": [{"id": 1, "role": "main"}]}
            if endpoint.startswith("themes/"):
                return {"asset": {"value": "<head></head>"}}
            return {"products": [{"id": 1, "title": "Fixture", "body_html": ""}]}
        with patch.object(aeo, "APPLY", False), patch.object(aeo, "resolve_token", return_value="fixture-only"), patch.object(aeo, "shopify_request", side_effect=response), patch.dict(aeo.REPORT, {"assets": [], "products_changed": [], "errors": []}, clear=False):
            aeo.deploy_to_shopify_live()
            self.assertEqual(aeo.REPORT["products_changed"][0]["status"], "would_update")
            self.assertTrue(all(asset["status"] == "would_upload" for asset in aeo.REPORT["assets"]))

    def test_workflow_is_main_only_and_inspection_only(self):
        text = (ROOT / ".github/workflows/shopify-aeo-apply.yml").read_text(encoding="utf-8")
        self.assertIn("if: github.ref == 'refs/heads/main'", text)
        self.assertIn("ref: main", text)
        self.assertIn("APPLY: '0'", text)
        self.assertIn("options: ['0']", text)


if __name__ == "__main__":
    unittest.main()
