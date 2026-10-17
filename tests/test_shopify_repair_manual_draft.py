"""Offline-only deterministic repair tests. Socket operations fail for entire suite."""
import copy
import json
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import shopify_repair_manual_draft as repair


class FakeGraphQL:
    def __init__(self, local):
        self.calls = []
        self.mutations = []
        self.reads = 0
        self.hook = None
        self.reject_update = False
        self.reject_unpublish = False
        self.ignore_description = False
        self.ignore_unpublish = False
        self.state = {
            "shop": {"myshopifyDomain": repair.STORE},
            "currentAppInstallation": {"accessScopes": [{"handle": s} for s in sorted(repair.SCOPES)]},
            "publications": self.connection([{"id": "gid://shopify/Publication/10"},
                                             {"id": "gid://shopify/Publication/20"}]),
            "product": {"id": repair.PRODUCT, "status": "DRAFT", "tags": [repair.TAG],
                        "vendor": "Dr.CPU+", "productType": "Skincare", "descriptionHtml": "<p>Old copy</p>",
                        "variants": self.connection([{"id": i, "title": title, "price": "0.00",
                                                      "inventoryItem": {"tracked": False}}
                                                     for i, title in repair.VARIANTS.items()]),
                        "media": self.connection([{"id": f"gid://shopify/MediaImage/{i}",
                                                   "mediaContentType": "IMAGE", "status": "READY",
                                                   "image": {"url": "https://cdn.shopify.com/files/" + name.replace(".png", "_800x800.png")}}
                                                  for i, name in enumerate(local["files"], 1)]),
                        "resourcePublicationsV2": self.connection([
                            {"isPublished": True, "publication": {"id": "gid://shopify/Publication/10"}},
                            {"isPublished": False, "publication": {"id": "gid://shopify/Publication/20"}}])}}

    @staticmethod
    def connection(rows):
        return {"nodes": rows, "pageInfo": {"hasNextPage": False}}

    def gql(self, query, variables=None):
        self.calls.append((query, copy.deepcopy(variables)))
        if query == repair.STATUS:
            return {"product": {k: self.state["product"][k] for k in ("id", "status")}}
        if query == repair.READ:
            self.reads += 1
            if self.hook:
                self.hook(self)
            return copy.deepcopy(self.state)
        self.mutations.append((query, copy.deepcopy(variables)))
        if query == repair.UPDATE:
            if self.reject_update:
                return {"productUpdate": {"userErrors": [{"message": "rejected"}], "product": None}}
            if not self.ignore_description:
                self.state["product"]["descriptionHtml"] = variables["p"]["descriptionHtml"]
            return {"productUpdate": {"userErrors": [], "product": {"id": repair.PRODUCT}}}
        if query == repair.UNPUBLISH:
            if self.reject_unpublish:
                raise RuntimeError("sensitive fake token must never leak")
            if not self.ignore_unpublish:
                for publication in self.state["product"]["resourcePublicationsV2"]["nodes"]:
                    publication["isPublished"] = False
            return {"publishableUnpublish": {"userErrors": []}}
        raise AssertionError("Unexpected GraphQL operation")


class RepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.socket_block = patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden"))
        cls.connection_block = patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden"))
        cls.socket_block.start()
        cls.connection_block.start()

    @classmethod
    def tearDownClass(cls):
        cls.connection_block.stop()
        cls.socket_block.stop()

    def setUp(self):
        self.manifest = json.loads((ROOT / repair.MANIFEST).read_text(encoding="utf-8-sig"))
        self.registry = json.loads((ROOT / "data/shopify_daily_registry.json").read_text(encoding="utf-8-sig"))
        self.local = repair.local_guard(self.manifest, self.registry)
        self.client = FakeGraphQL(self.local)
        self.saved = []

    def run_repair(self, dry_run=False, expected=None):
        return repair.repair(self.client, self.local, dry_run=dry_run,
                             expected_before_sha256=expected or repair.sha("<p>Old copy</p>"),
                             writer=lambda p, d: self.saved.append((p, copy.deepcopy(d))))

    def blocked(self, code):
        result = self.run_repair()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], code)
        self.assertEqual(self.client.mutations, [])
        return result

    def test_dryrun_has_zero_mutations_and_backup(self):
        result = self.run_repair(dry_run=True)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["remote_writes"], 0)
        self.assertEqual(self.client.mutations, [])
        self.assertEqual(self.saved[0][1]["before"]["descriptionHtml"], "<p>Old copy</p>")
        self.assertEqual(self.saved[0][1]["before"]["before_sha256"], result["before_sha256"])

    def test_apply_only_two_exact_safe_mutations(self):
        result = self.run_repair()
        self.assertEqual(result["status"], "verified_api_accessible_draft")
        self.assertEqual(self.client.mutations, [
            (repair.UPDATE, {"p": {"id": repair.PRODUCT, "descriptionHtml": self.local["target"]}}),
            (repair.UNPUBLISH, {"id": repair.PRODUCT, "input": [
                {"publicationId": "gid://shopify/Publication/10"},
                {"publicationId": "gid://shopify/Publication/20"}]})])
        self.assertFalse(result["global_channel_removal_verified"])
        self.assertEqual(result["after"]["status"], "DRAFT")
        self.assertEqual(len(self.saved), 2)

    def test_wrong_store(self):
        self.client.state["shop"]["myshopifyDomain"] = "other.myshopify.com"
        self.blocked("wrong_store")

    def test_wrong_product(self):
        self.client.state["product"]["id"] = "gid://shopify/Product/999"
        self.blocked("wrong_product")

    def test_active_status(self):
        self.client.state["product"]["status"] = "ACTIVE"
        self.blocked("not_draft")

    def test_wrong_tag(self):
        self.client.state["product"]["tags"] = ["daiso-pd-123"]
        self.blocked("wrong_tag")

    def test_extra_pd_tag(self):
        self.client.state["product"]["tags"].append("daiso-pd-123")
        self.blocked("wrong_tag")

    def test_wrong_vendor(self):
        self.client.state["product"]["vendor"] = "other"
        self.blocked("wrong_vendor_type")

    def test_nonzero_price(self):
        self.client.state["product"]["variants"]["nodes"][0]["price"] = "0.01"
        self.blocked("nonzero_prices")

    def test_invalid_price(self):
        self.client.state["product"]["variants"]["nodes"][0]["price"] = "NaN"
        self.blocked("nonzero_prices")

    def test_wrong_variant_id(self):
        self.client.state["product"]["variants"]["nodes"][0]["id"] = "gid://shopify/ProductVariant/1"
        self.blocked("wrong_variants")

    def test_wrong_variant_title(self):
        self.client.state["product"]["variants"]["nodes"][0]["title"] = "New"
        self.blocked("wrong_variants")

    def test_variant_pagination(self):
        self.client.state["product"]["variants"]["pageInfo"]["hasNextPage"] = True
        self.blocked("variants_incomplete")

    def test_inventory_on(self):
        self.client.state["product"]["variants"]["nodes"][0]["inventoryItem"]["tracked"] = True
        self.blocked("inventory_tracking")

    def test_media_count(self):
        self.client.state["product"]["media"]["nodes"].pop()
        self.blocked("wrong_media")

    def test_media_order(self):
        self.client.state["product"]["media"]["nodes"].reverse()
        self.blocked("wrong_media_filenames")

    def test_media_filename(self):
        self.client.state["product"]["media"]["nodes"][0]["image"]["url"] = "https://cdn.shopify.com/01-fake-en.png"
        self.blocked("wrong_media_filenames")

    def test_media_pagination(self):
        self.client.state["product"]["media"]["pageInfo"]["hasNextPage"] = True
        self.blocked("media_incomplete")

    def test_scope_denied(self):
        self.client.state["currentAppInstallation"]["accessScopes"] = []
        self.blocked("missing_scopes")

    def test_write_only_scopes_prove_read_access_and_allow_apply(self):
        self.client.state["currentAppInstallation"]["accessScopes"] = [
            {"handle": "write_products"}, {"handle": "write_publications"}]
        result = self.run_repair()
        self.assertEqual(result["status"], "verified_api_accessible_draft")
        self.assertEqual(len(self.client.mutations), 2)

    def test_explicit_read_handles_remain_accepted(self):
        self.client.state["currentAppInstallation"]["accessScopes"].extend([
            {"handle": "read_products"}, {"handle": "read_publications"}])
        self.assertEqual(self.run_repair()["status"], "verified_api_accessible_draft")

    def test_each_missing_write_is_denied_despite_read_handles(self):
        for missing in ("write_products", "write_publications"):
            with self.subTest(missing=missing):
                self.client = FakeGraphQL(self.local)
                handles = {"read_products", "read_publications", "write_products", "write_publications"} - {missing}
                self.client.state["currentAppInstallation"]["accessScopes"] = [
                    {"handle": h} for h in sorted(handles)]
                self.blocked("missing_scopes")

    def test_malformed_scope_data_denied(self):
        for rows in (None, "write_products", {}, [{}], ["write_products"], [{"handle": None}]):
            with self.subTest(rows=rows):
                self.client = FakeGraphQL(self.local)
                self.client.state["currentAppInstallation"]["accessScopes"] = rows
                self.blocked("malformed_scopes")
        self.client = FakeGraphQL(self.local)
        self.client.state["currentAppInstallation"] = None
        self.blocked("malformed_scopes")

    def test_write_only_does_not_allow_incomplete_read(self):
        self.client.state["currentAppInstallation"]["accessScopes"] = [
            {"handle": "write_products"}, {"handle": "write_publications"}]
        self.client.state["publications"].pop("pageInfo")
        self.blocked("publication_view_incomplete")

    def test_write_only_does_not_allow_missing_product(self):
        self.client.state["product"] = None
        self.blocked("wrong_product")

    def test_incomplete_publications(self):
        self.client.state["publications"]["pageInfo"]["hasNextPage"] = True
        self.blocked("publication_view_incomplete")

    def test_incomplete_product_publications(self):
        self.client.state["product"]["resourcePublicationsV2"]["pageInfo"]["hasNextPage"] = True
        self.blocked("product_publications_incomplete")

    def test_publication_outside_store_view(self):
        self.client.state["product"]["resourcePublicationsV2"]["nodes"][0]["publication"]["id"] = "gid://shopify/Publication/999"
        self.blocked("publication_state_unavailable")

    def test_wrong_expected_sha(self):
        result = self.run_repair(expected="0" * 64)
        self.assertEqual(result["reason"], "expected_sha_mismatch")
        self.assertEqual(self.client.mutations, [])

    def test_missing_expected_sha(self):
        with self.assertRaisesRegex(repair.Blocked, "expected_sha_required"):
            repair.repair(self.client, self.local, dry_run=False, writer=lambda *a: None)
        self.assertEqual(self.client.calls, [])

    def test_external_edit_between_reads(self):
        self.client.hook = lambda c: c.state["product"].update(descriptionHtml="external edit") if c.reads == 2 else None
        self.blocked("expected_sha_mismatch")

    def test_external_media_edit_between_reads(self):
        def edit(c):
            if c.reads == 2:
                c.state["product"]["media"]["nodes"][0]["id"] = "gid://shopify/MediaImage/999"
        self.client.hook = edit
        self.blocked("protected_fields_changed")

    def test_verification_mismatch(self):
        self.client.ignore_description = True
        result = self.run_repair()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["reason"], "description_verification_failed")
        self.assertEqual(len(self.client.mutations), 1)

    def test_unpublish_mismatch(self):
        self.client.ignore_unpublish = True
        result = self.run_repair()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["reason"], "publication_verification_failed")

    def test_permission_failure_sanitized_and_draft_rechecked(self):
        self.client.reject_unpublish = True
        result = self.run_repair()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["last_observed_status"], "DRAFT")
        self.assertNotIn("sensitive fake token", json.dumps(self.saved, default=str))
        self.assertFalse(result["global_channel_removal_verified"])

    def test_update_rejected(self):
        self.client.reject_update = True
        result = self.run_repair()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["reason"], "description_mutation_rejected")
        self.assertEqual(len(self.client.mutations), 1)

    def test_idempotent_repeated_apply(self):
        self.assertEqual(self.run_repair()["status"], "verified_api_accessible_draft")
        count = len(self.client.mutations)
        result = self.run_repair(expected=repair.sha(self.local["target"]))
        self.assertEqual(result["status"], "verified_api_accessible_draft")
        self.assertEqual(result["remote_writes"], 0)
        self.assertEqual(len(self.client.mutations), count)
        self.assertNotEqual(self.saved[0][0], self.saved[2][0])

    def test_html_serialization_whitespace(self):
        html = self.local["target"].replace("</p><", "</p>\n  <")
        self.client.state["product"]["descriptionHtml"] = html
        result = self.run_repair(expected=repair.sha(html))
        self.assertEqual(result["status"], "verified_api_accessible_draft")
        self.assertTrue(all(q == repair.UNPUBLISH for q, _ in self.client.mutations))

    def test_local_owner_approval(self):
        row = next(r for r in self.registry["items"] if r["pd_no"] == repair.PD)
        row["owner_requested_nonpublic_draft"] = False
        with self.assertRaisesRegex(repair.Blocked, "local_owner_nonpublic_approval"):
            repair.local_guard(self.manifest, self.registry)

    def test_local_identity(self):
        row = next(r for r in self.registry["items"] if r["pd_no"] == repair.PD)
        row["shopify_id"] = "gid://shopify/Product/123"
        with self.assertRaisesRegex(repair.Blocked, "local_identity"):
            repair.local_guard(self.manifest, self.registry)

    def test_local_duplicate_approval(self):
        self.registry["items"].append(copy.deepcopy(next(r for r in self.registry["items"] if r["pd_no"] == repair.PD)))
        with self.assertRaisesRegex(repair.Blocked, "registry_exact_unique_item"):
            repair.local_guard(self.manifest, self.registry)

    def test_target_tampering(self):
        self.manifest["desired_description_html"] += "<p>unverified</p>"
        with self.assertRaisesRegex(repair.Blocked, "desired_html_source"):
            repair.local_guard(self.manifest, self.registry)

    def test_local_source_guard(self):
        row = next(r for r in self.registry["items"] if r["pd_no"] == repair.PD)
        row["source"] = "canonical"
        with self.assertRaisesRegex(repair.Blocked, "local_owner_nonpublic_approval"):
            repair.local_guard(self.manifest, self.registry)

    def test_manifest_nonpublic_hold(self):
        self.manifest["registration"]["public_sale_authorized"] = True
        with self.assertRaisesRegex(repair.Blocked, "manifest_nonpublic_hold"):
            repair.local_guard(self.manifest, self.registry)

    def test_manifest_order_guard(self):
        self.manifest["outputs"].reverse()
        with self.assertRaisesRegex(repair.Blocked, "manifest_ordered_english_images"):
            repair.local_guard(self.manifest, self.registry)

    def test_socket_block_is_active(self):
        with self.assertRaisesRegex(AssertionError, "network forbidden"):
            socket.create_connection(("127.0.0.1", 1))


if __name__ == "__main__":
    unittest.main()
