"""Offline tests. No Shopify writes or live Daiso calls."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/daiso_daily_beauty_to_shopify.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("daily", SCRIPT)
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)


class DailySafetyTests(unittest.TestCase):
    def test_skincare_s_only_makeup_body_s_then_a(self):
        skin = daily.s_ranked(daily.CATEGORIES[0])
        self.assertTrue(skin and all(x["grade"] == "S" for x in skin))
        for cat in daily.CATEGORIES[1:]:
            rows = daily.s_ranked(cat)
            self.assertTrue(rows)
            self.assertTrue(all(x["grade"] in ("S", "A") for x in rows))
            self.assertEqual([x["grade"] for x in rows], sorted(x["grade"] for x in rows))  # S 가 항상 먼저
        self.assertEqual(daily.grade_label(daily.CATEGORIES[0]), "S")
        self.assertEqual(daily.grade_label(daily.CATEGORIES[2]), "S/A")

    def test_pick_never_promotes_lower_grade_or_recommendations(self):
        rows = [{"pd_no": "1", "grade": "S", "shopify_score": 99}]
        with patch.object(daily, "daiso_lookup", return_value=None), patch.object(daily, "fetch_daiso") as recommendations:
            self.assertIsNone(daily.pick(daily.CATEGORIES[0], None, set(), set(), {"items": []}, rows))
            recommendations.assert_not_called()

    def test_duplicates_cover_deleted_registry_family_shop_title_tag_and_sku(self):
        p = {"pdNo": "101", "pdNm": "태그 슬림브로우펜슬(3호_브라운)"}
        reg = {"items": [{"pd_no": "99", "name_kr": "태그 슬림브로우펜슬(2호_애쉬브라운)",
                          "title": "Taeg Slim Brow Pencil", "date": "yesterday"}]}
        self.assertTrue(daily.already_registered(p, reg, set(), set()))
        self.assertTrue(daily.already_registered({"pdNo": "99", "pdNm": "Other"}, reg, set(), set()))
        names, ids = daily.shop_keys([{"title": "VT Reedle Shot 300", "tags": ["daiso-pd-101"],
                                      "variants": {"nodes": [{"sku": "DS-789-1"}]}}])
        self.assertTrue(daily.already_registered(p, {"items": []}, names, ids))
        self.assertTrue(daily.already_registered({"pdNo": "789", "pdNm": "Other"}, {"items": []}, names, ids))
        self.assertTrue(daily.already_registered({"pdNo": "2", "pdNm": "Other"}, {"items": []}, names, ids,
                                                 "VT Reedle Shot 300"))
        shade_names, _ = daily.shop_keys([{"title": "Taeg Slim Brow Pencil 2 Ash Brown", "tags": [],
                                           "variants": {"nodes": []}}])
        self.assertTrue(daily.already_registered({"pdNo": "3", "pdNm": "태그 슬림브로우펜슬(3호)"},
                                                 {"items": []}, shade_names, set(),
                                                 "Taeg Slim Brow Pencil 3 Brown"))

    def test_pick_skips_duplicate_s_and_uses_next_s(self):
        rows = [{"pd_no": "1", "grade": "S"}, {"pd_no": "2", "grade": "S"}]
        def lookup(pd):
            return {"pdNo": pd, "pdNm": "Product " + pd, "pdPrc": "3000", "soldOutYn": "N",
                    "exhYn": "Y", "onlStckQy": 1, "pdImgUrl": "/x"}
        with patch.object(daily, "daiso_lookup", side_effect=lookup):
            p = daily.pick(daily.CATEGORIES[0], None, set(), {"1"}, {"items": []}, rows)
            self.assertEqual(p["pdNo"], "2")
            self.assertEqual(p["_grade"], "S")

    def test_invalid_registry_fails_closed_and_atomic_save(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(daily, "REGISTRY", Path(folder)/"registry.json"):
            daily.REGISTRY.write_text("{bad", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                daily.load_registry()
            daily.save_registry({"items": [{"pd_no": "101", "status": "create_reserved"}]})
            self.assertEqual(daily.load_registry()["items"][0]["pd_no"], "101")

    def test_create_always_draft_and_persists_id_before_variant_update(self):
        shop = daily.Shopify.__new__(daily.Shopify)
        calls = []
        def gql(query, variables=None):
            if "productCreate(product:" in query:
                self.assertEqual(variables["product"]["status"], "DRAFT")
                return {"productCreate": {"product": {"id": "gid://shopify/Product/1", "handle": "h",
                                                   "variants": {"nodes": [{"id": "gid://shopify/ProductVariant/1"}]}},
                                          "userErrors": []}}
            self.assertEqual(calls, ["gid://shopify/Product/1"])
            return {"productVariantsBulkUpdate": {"userErrors": [{"message": "fail"}]}}
        shop.gql = gql
        item = {"title": "T", "description_html": "x", "vendor": "V", "product_type": "Skincare",
                "category": "category", "tags": [], "status": "ACTIVE", "images": [],
                "variants": [{"name": "Single", "price": 9.99, "sku": "DS-1-1"}]}
        with self.assertRaises(RuntimeError):
            shop.create(item, lambda prod: calls.append(prod["id"]))
        self.assertEqual(calls, ["gid://shopify/Product/1"])

    def test_verification_requires_images_variants_and_publication(self):
        shop = daily.Shopify.__new__(daily.Shopify)
        p = {"id": "p", "title": "Title", "status": "DRAFT", "publishedOnPublication": False,
             "variants": {"nodes": [{"sku": "DS-1-1", "price": "9.99"}]},
             "media": {"nodes": [{"mediaContentType": "IMAGE", "status": "PROCESSING"}]}}
        shop.read_product = lambda product_id, pub: p
        item = {"title": "Title", "variants": [{"sku": "DS-1-1", "price": 9.99}], "images": ["image"]}
        with self.assertRaisesRegex(RuntimeError, "image"):
            daily.verify_product(shop, "p", item, "publication")
        p["media"]["nodes"][0]["status"] = "READY"
        self.assertEqual(daily.verify_product(shop, "p", item, "publication"), p)
        with self.assertRaisesRegex(RuntimeError, "status/publication"):
            daily.verify_product(shop, "p", item, "publication", published=True)

    def test_uncertain_create_reservation_blocks_remaining_categories(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cwd = os.getcwd()
            os.chdir(root)
            try:
                shop = MagicMock()
                shop.store = "test.myshopify.com"
                shop.existing_products.return_value = []
                shop.exists.return_value = False
                shop.online_store_publication.return_value = "pub"
                shop.create.side_effect = TimeoutError("unknown productCreate result")
                candidate = {"pdNo": "123", "pdNm": "본셉 세럼 30 ml", "brndNm": "본셉",
                             "pdPrc": "3000", "_grade": "S", "_source": "jarvis_s_list"}
                pricing = {"single": {"price_usd": 14.99, "margin_pct": 30},
                           "pack": {"ok": True, "price_usd": 25.99, "margin_pct": 30,
                                    "compare_at_usd": 29.98}, "basis": "test", "shop_compare": {}}
                with patch.object(daily, "DRY_RUN", False), patch.object(daily, "ONLY", set()), \
                     patch.object(daily, "BACKFILL_BANNER", False), \
                     patch.object(daily, "QUARANTINE_BLOCKED_PUBLIC", False), \
                     patch.object(daily, "REGISTRY", root/"registry.json"), \
                     patch.object(daily, "Shopify", return_value=shop), \
                     patch.object(daily, "s_ranked", return_value=[{"pd_no": "123", "grade": "S"}]) as ranked, \
                     patch.object(daily, "pick", return_value=candidate) as pick, \
                     patch.object(daily, "gemini_copy", return_value=None), \
                     patch.object(daily, "fallback_copy", return_value=("Bonsep Serum 30 ml", "<p>Serum.</p>")), \
                     patch.object(daily, "jarvis_price", return_value={"price_usd": 14.99}), \
                     patch.object(daily, "final_prices", return_value=pricing), \
                     patch.object(daily, "collect_gosi", return_value={"volume": "30 ml", "gosi_ok": True,
                                                                            "missing": [], "ingredients": "INCI"}), \
                     patch.object(daily, "build_us_label", return_value={"html": "<p>INCI.</p>",
                                                                               "reasons": [], "label": {}}), \
                     patch.object(daily, "canonical_public_gate", return_value={
                         "public_ready": False, "reasons": ["listing_gate_legal_hard_block"]}), \
                     patch.object(daily, "has_claims", return_value=False), \
                     patch.object(daily, "prepare_images", return_value={"source_urls": ["source"],
                                                                               "resource_urls": ["resource"],
                                                                               "skipped": []}), \
                     patch.dict(os.environ, {"SHOPIFY_STORE": "test.myshopify.com", "SHOPIFY_ADMIN_TOKEN": "test"}):
                    self.assertEqual(daily.main(), 1)
                    ranked.assert_called_once()
                    pick.assert_called_once()
                result = json.loads((root/"out/daiso_daily_beauty_result.json").read_text(encoding="utf-8"))
                self.assertEqual([x["status"] for x in result["results"]],
                                 ["failed", "skipped_prior_write_uncertain", "skipped_prior_write_uncertain"])
                self.assertEqual(json.loads((root/"registry.json").read_text(encoding="utf-8"))["items"][0]["status"],
                                 "create_reserved")
                shop.create.assert_called_once()
            finally:
                os.chdir(cwd)

    def test_daily_cap_cannot_be_forced_and_no_s_is_reported(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            cwd = os.getcwd()
            os.chdir(folder)
            try:
                with patch.object(daily, "DRY_RUN", True), patch.object(daily, "kst_today", return_value="2026-10-10"), \
                     patch.object(daily, "load_registry", return_value={"items": [
                         {"date": "2026-10-10", "category": "skincare", "pd_no": "1"}]}), \
                     patch.object(daily, "daiso_lookup", return_value=None) as lookup, \
                     patch.dict(os.environ, {"FORCE": "1", "SHOPIFY_STORE": "", "SHOPIFY_ADMIN_TOKEN": "", "SHOPIFY_CLIENT_SECRET": ""}):
                    self.assertEqual(daily.main(), 0)
                    # 스킨케어는 오늘 이미 등록 -> 조회 없음. 메이크업·바디는 S/A 후보를 조회하지만 없으면 건너뛴다.
                    self.assertTrue(all(c.args[0] not in {r["pd_no"] for r in daily.s_ranked(daily.CATEGORIES[0])}
                                        for c in lookup.call_args_list))
                result = json.loads(Path("out/daiso_daily_beauty_result.json").read_text(encoding="utf-8"))
                self.assertEqual(result["results"][0]["status"], "skipped_already_today")
                self.assertEqual(result["results"][0]["s_candidates"], 10)
                self.assertEqual([r["status"] for r in result["results"][1:]],
                                 ["skipped_no_eligible_s_grade", "skipped_no_eligible_s_grade"])
                self.assertEqual([r["grade_required"] for r in result["results"]], ["S", "S/A", "S/A"])
            finally:
                os.chdir(cwd)

    def test_public_gate_fail_closed_missing_stale_blocked_and_incomplete(self):
        import gate_signature
        signature = gate_signature.agent_input_signature(gate_signature.current_recommendations())
        with tempfile.TemporaryDirectory() as folder, patch.object(daily, "ROOT", Path(folder)):
            data = Path(folder)/"data"
            data.mkdir()
            self.assertEqual(daily.canonical_public_gate("123")["reasons"],
                             ["listing_gate_missing_or_unreadable"])
            gate = {"agent_input_signature": signature, "items": [
                {"pd_no": "123", "legal": {"hard_block": True}, "ready": True,
                 "public_ready": False, "legal_full_complete": True, "public_blocked_by": ["legal"]}]}
            file = data/"listing_gate.json"
            file.write_text(json.dumps(gate), encoding="utf-8")
            blocked = daily.canonical_public_gate("123")
            self.assertFalse(blocked["public_ready"])
            self.assertIn("listing_gate_legal_hard_block", blocked["reasons"])
            self.assertIn("listing_gate_public_not_ready", blocked["reasons"])
            self.assertEqual(daily.canonical_public_gate("999")["reasons"],
                             ["listing_gate_product_missing_or_ambiguous"])
            gate["items"][0]["legal"]["hard_block"] = False
            file.write_text(json.dumps(gate), encoding="utf-8")
            self.assertIn("listing_gate_public_not_ready", daily.canonical_public_gate("123")["reasons"])
            gate["items"][0].update(public_ready=True, legal_full_complete=False, public_blocked_by=[])
            file.write_text(json.dumps(gate), encoding="utf-8")
            self.assertIn("listing_gate_legal_full_incomplete", daily.canonical_public_gate("123")["reasons"])
            gate["items"][0]["legal_full_complete"] = True
            file.write_text(json.dumps(gate), encoding="utf-8")
            self.assertTrue(daily.canonical_public_gate("123")["public_ready"])
            gate["agent_input_signature"] = {"schema_version": 2, "semantic_sources": {}}
            file.write_text(json.dumps(gate), encoding="utf-8")
            self.assertTrue(daily.canonical_public_gate("123")["reasons"][0].startswith("listing_gate_stale:"))

    def test_complete_local_gosi_never_overrides_canonical_public_gate(self):
        import os
        import gate_signature
        signature = gate_signature.agent_input_signature(gate_signature.current_recommendations())
        candidate = {"pdNo": "123", "pdNm": "본셉 세럼 30 ml", "brndNm": "본셉", "pdPrc": "3000",
                     "_grade": "S", "_source": "jarvis_s_list"}
        pricing = {"single": {"price_usd": 14.99, "margin_pct": 30},
                   "pack": {"ok": True, "price_usd": 25.99, "margin_pct": 30,
                            "compare_at_usd": 29.98}, "basis": "test", "shop_compare": {}}
        for scenario, expected_reason in [
            ("missing", "listing_gate_missing_or_unreadable"),
            ("stale", "listing_gate_stale:"),
            ("hard_block", "listing_gate_legal_hard_block"),
            ("not_ready", "listing_gate_public_not_ready")]:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root/"data").mkdir()
                if scenario != "missing":
                    gate = {"agent_input_signature": signature,
                            "items": [{"pd_no": "123", "legal": {"hard_block": scenario == "hard_block"},
                                       "ready": True, "public_ready": scenario == "hard_block",
                                       "legal_full_complete": True, "public_blocked_by": []}]}
                    if scenario == "stale":
                        gate["agent_input_signature"] = {"schema_version": 2, "semantic_sources": {}}
                    (root/"data/listing_gate.json").write_text(json.dumps(gate), encoding="utf-8")
                shop = MagicMock()
                shop.store = "test.myshopify.com"
                shop.existing_products.return_value = []
                shop.exists.return_value = False
                shop.online_store_publication.return_value = "gid://shopify/Publication/1"
                def create(item, on_created):
                    self.assertEqual(item["status"], "DRAFT")
                    prod = {"id": "gid://shopify/Product/123", "handle": "bonsep-serum"}
                    on_created(prod)
                    return prod
                shop.create.side_effect = create
                shop.read_product.return_value = {
                    "id": "gid://shopify/Product/123", "handle": "bonsep-serum",
                    "title": "Bonsep Serum 30 ml", "status": "DRAFT", "publishedOnPublication": False,
                    "variants": {"nodes": [{"sku": "DS-123-1", "price": "14.99"},
                                           {"sku": "DS-123-2", "price": "25.99"}]},
                    "media": {"nodes": [{"mediaContentType": "IMAGE", "status": "READY"}]}}
                cwd = os.getcwd()
                os.chdir(root)
                try:
                    with patch.object(daily, "ROOT", root), patch.object(daily, "REGISTRY", root/"data/registry.json"), \
                         patch.object(daily, "DRY_RUN", False), patch.object(daily, "ONLY", {"skincare"}), \
                         patch.object(daily, "Shopify", return_value=shop), \
                         patch.object(daily, "s_ranked", return_value=[{"pd_no": "123", "grade": "S"}]), \
                         patch.object(daily, "pick", return_value=candidate), \
                         patch.object(daily, "gemini_copy", return_value=None), \
                         patch.object(daily, "fallback_copy", return_value=("Bonsep Serum 30 ml", "<p>Serum.</p>")), \
                         patch.object(daily, "jarvis_price", return_value={"price_usd": 14.99}), \
                         patch.object(daily, "final_prices", return_value=pricing), \
                         patch.object(daily, "collect_gosi", return_value={"volume": "30 ml", "gosi_ok": True,
                                                                            "missing": [], "ingredients": "INCI"}), \
                         patch.object(daily, "build_us_label", return_value={"html": "<p>INCI.</p>",
                                                                               "reasons": [], "label": {}}), \
                         patch.object(daily, "has_claims", return_value=False), \
                         patch.object(daily, "prepare_images", return_value={"source_urls": ["source"],
                                                                               "resource_urls": ["resource"],
                                                                               "skipped": []}), \
                         patch.dict(os.environ, {"SHOPIFY_STORE": "test.myshopify.com", "SHOPIFY_ADMIN_TOKEN": "test"}):
                        self.assertEqual(daily.main(), 0)
                    result = json.loads((root/"out/daiso_daily_beauty_result.json").read_text(encoding="utf-8"))
                    record = result["results"][0]
                    self.assertEqual(record["status"], "created_draft")
                    self.assertTrue(any(r.startswith(expected_reason) for r in record["draft_reasons"]))
                    self.assertEqual(record["verified_status"], "DRAFT")
                    self.assertFalse(record["published_on_online_store"])
                    shop.set_status.assert_not_called()
                    shop.publish.assert_not_called()
                    self.assertEqual(json.loads((root/"data/registry.json").read_text(encoding="utf-8"))["items"][0]["status"], "DRAFT")
                finally:
                    os.chdir(cwd)

    def test_existing_products_paginates_or_fails_closed(self):
        shop = daily.Shopify.__new__(daily.Shopify)
        seen = []
        def gql(query, variables):
            seen.append(variables["after"])
            row = {"id": "id" + str(len(seen)), "title": "Title", "descriptionHtml": "",
                   "tags": [], "variants": {"nodes": [], "pageInfo": {"hasNextPage": False}}}
            return {"products": {"nodes": [row], "pageInfo": {
                "hasNextPage": len(seen) == 1, "endCursor": "next"}}}
        shop.gql = gql
        self.assertEqual(len(shop.existing_products()), 2)
        self.assertEqual(seen, [None, "next"])
        shop.gql = lambda query, variables: {"products": {"nodes": [{"id": "x", "variants": {
            "nodes": [], "pageInfo": {"hasNextPage": True}}}],
            "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        with self.assertRaisesRegex(RuntimeError, "variant pagination incomplete"):
            shop.existing_products()
        def with_variants(query, variables):
            if "product(id:$id)" in query:
                return {"product": {"variants": {"nodes": [{"sku": "DS-789-2"}],
                                                 "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
            return {"products": {"nodes": [{"id": "x", "title": "Title", "tags": [],
                                             "variants": {"nodes": [{"sku": "DS-789-1"}],
                                                          "pageInfo": {"hasNextPage": True,
                                                                      "endCursor": "v1"}}}],
                                 "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        shop.gql = with_variants
        names, ids = daily.shop_keys(shop.existing_products())
        self.assertIn("789", ids)

    def test_quarantine_only_current_explicit_hard_block_exact_ids(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(daily, "REGISTRY", Path(folder)/"registry.json"):
            registry = {"items": [{"pd_no": "101", "shopify_id": "registered", "status": "ACTIVE",
                                   "family": "keep-family", "date": "yesterday"}]}
            products = [{"id": "registered", "tags": [], "descriptionHtml": "A"},
                        {"id": "tagged", "tags": ["daiso-pd-102"], "descriptionHtml": "B"},
                        {"id": "source", "tags": [], "descriptionHtml": "Source: Daiso Mall item 103."},
                        {"id": "unrelated", "tags": [], "descriptionHtml": "Other"}]
            state = {r["id"]: {"id": r["id"], "title": r["id"], "tags": r["tags"],
                                  "descriptionHtml": r["descriptionHtml"], "status": "ACTIVE",
                                  "publishedOnPublication": True,
                                  "variants": {"nodes": [{"sku": r["id"], "price": "9.99"}]}}
                     for r in products}
            shop = MagicMock()
            shop.read_product.side_effect = lambda id, pub: json.loads(json.dumps(state[id]))
            def draft(id, status):
                self.assertEqual(status, "DRAFT")
                state[id]["status"] = "DRAFT"
                state[id]["publishedOnPublication"] = False
            shop.set_status.side_effect = draft
            def gate(pd):
                if pd == "103":
                    return {"public_ready": False, "reasons": ["listing_gate_stale"],
                            "legal_hard_block": None}
                return {"public_ready": False, "reasons": ["listing_gate_legal_hard_block"],
                        "legal_hard_block": True}
            with patch.object(daily, "canonical_public_gate", side_effect=gate):
                result = daily.quarantine_blocked_public(shop, products, registry, "publication", [])
            self.assertEqual([x["status"] for x in result],
                             ["quarantined_draft", "quarantined_draft",
                              "skipped_no_explicit_current_legal_block"])
            self.assertEqual([c.args[0] for c in shop.set_status.call_args_list], ["registered", "tagged"])
            self.assertEqual(registry["items"][0]["family"], "keep-family")
            self.assertEqual(registry["items"][0]["date"], "yesterday")
            self.assertEqual(registry["items"][0]["status"], "DRAFT")
            self.assertEqual(registry["items"][1]["pd_no"], "102")
            self.assertEqual(daily.load_registry()["items"][0]["shopify_id"], "registered")
            self.assertEqual(state["source"]["status"], "ACTIVE")
            self.assertEqual(state["unrelated"]["status"], "ACTIVE")
            shop.read_product.assert_any_call("registered", "publication")
            self.assertNotIn("unrelated", [c.args[0] for c in shop.read_product.call_args_list])

    def test_quarantine_reserves_identity_before_uncertain_mutation(self):
        row = {"id": "p", "tags": ["daiso-pd-1"], "descriptionHtml": "x"}
        before = {"id": "p", "title": "T", "tags": ["daiso-pd-1"], "descriptionHtml": "x",
                  "status": "ACTIVE", "publishedOnPublication": True,
                  "variants": {"nodes": [], "pageInfo": {"hasNextPage": False}}}
        shop = MagicMock()
        shop.read_product.return_value = before
        shop.set_status.side_effect = TimeoutError("uncertain")
        with tempfile.TemporaryDirectory() as folder, patch.object(daily, "REGISTRY", Path(folder)/"registry.json"), \
             patch.object(daily, "canonical_public_gate", return_value={
                 "legal_hard_block": True, "reasons": ["listing_gate_legal_hard_block"]}):
            results = []
            with self.assertRaises(TimeoutError):
                daily.quarantine_blocked_public(shop, [row], {"items": []}, "pub", results)
            self.assertEqual(results[0]["status"], "quarantine_mutation_uncertain")
            self.assertEqual(daily.load_registry()["items"][0]["status"], "quarantine_requested")
            self.assertEqual(daily.load_registry()["items"][0]["pd_no"], "1")

    def test_quarantine_does_not_change_archived_or_ambiguous_products(self):
        products = [{"id": "archived", "tags": ["daiso-pd-1"], "descriptionHtml": "x"},
                    {"id": "conflict", "tags": ["daiso-pd-2"],
                     "descriptionHtml": "Source: Daiso Mall item 3."}]
        shop = MagicMock()
        shop.read_product.return_value = {"id": "archived", "title": "T", "tags": ["daiso-pd-1"],
                                          "descriptionHtml": "x", "status": "ARCHIVED",
                                          "publishedOnPublication": False, "variants": {"nodes": []}}
        with patch.object(daily, "canonical_public_gate", return_value={
            "legal_hard_block": True, "reasons": ["listing_gate_legal_hard_block"]}):
            results = daily.quarantine_blocked_public(shop, products, {"items": []}, "pub", [])
        self.assertEqual([x["status"] for x in results],
                         ["already_not_public", "skipped_identity_ambiguous"])
        shop.set_status.assert_not_called()
        shop.read_product.assert_called_once_with("archived", "pub")

    def test_quarantine_fails_if_readback_alters_identity_variants_or_publication(self):
        base = {"id": "p", "title": "T", "tags": ["daiso-pd-1"], "descriptionHtml": "x",
                "status": "ACTIVE", "publishedOnPublication": True,
                "variants": {"nodes": [{"sku": "DS-1-1", "price": "9.99"}]}}
        for change in ("title", "variants", "publishedOnPublication"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder, \
                 patch.object(daily, "REGISTRY", Path(folder)/"registry.json"), \
                 patch.object(daily, "canonical_public_gate", return_value={
                     "legal_hard_block": True, "reasons": ["listing_gate_legal_hard_block"]}):
                state = json.loads(json.dumps(base))
                shop = MagicMock()
                shop.read_product.side_effect = lambda id, pub: json.loads(json.dumps(state))
                def draft(id, status):
                    state["status"] = "DRAFT"
                    if change == "title": state["title"] = "Changed"
                    if change == "variants": state["variants"]["nodes"][0]["price"] = "8.99"
                    if change != "publishedOnPublication": state["publishedOnPublication"] = False
                shop.set_status.side_effect = draft
                results = []
                with self.assertRaisesRegex(RuntimeError, "read-back/publication mismatch"):
                    daily.quarantine_blocked_public(shop, [base], {"items": []}, "publication", results)
                self.assertEqual(results[0]["status"], "quarantine_readback_failed")
                self.assertTrue(results[0]["manual_reconciliation_required"])

    def test_banner_backfill_is_idempotent_text_only_and_scoped(self):
        products = [{"id": "registered", "tags": []},
                    {"id": "tagged", "tags": ["daiso-pd-77"]},
                    {"id": "unrelated", "tags": ["other"]}]
        state = {x: {"id": x, "title": x, "tags": ["daiso-pd-77"] if x == "tagged" else [], "status": "ACTIVE" if x == "registered" else "DRAFT",
                     "publishedOnPublication": x == "registered", "descriptionHtml": "<p>Original.</p>"}
                 for x in ("registered", "tagged", "unrelated")}
        shop = MagicMock()
        shop.read_product.side_effect = lambda id, pub: dict(state[id])
        shop.update_description.side_effect = lambda id, html: state[id].update(descriptionHtml=html)
        registry = {"items": [{"shopify_id": "registered"}]}
        first = daily.backfill_banner(shop, products, registry, "pub")
        self.assertEqual([x["status"] for x in first], ["prefixed", "prefixed"])
        self.assertTrue(state["registered"]["descriptionHtml"].startswith(daily.TAGLINE_HTML))
        self.assertTrue(state["tagged"]["descriptionHtml"].startswith(daily.TAGLINE_HTML))
        self.assertEqual(state["unrelated"]["descriptionHtml"], "<p>Original.</p>")
        second = daily.backfill_banner(shop, products, registry, "pub")
        self.assertEqual([x["status"] for x in second], ["already_prefixed", "already_prefixed"])
        self.assertEqual(shop.update_description.call_count, 2)
        self.assertEqual(state["registered"]["status"], "ACTIVE")
        self.assertTrue(state["registered"]["publishedOnPublication"])
        shop.read_product.assert_any_call("registered", "pub")
        self.assertNotIn("unrelated", [call.args[0] for call in shop.read_product.call_args_list])

    def test_banner_backfill_rejects_publication_state_drift(self):
        state = {"id": "p", "title": "T", "tags": ["daiso-daily"], "status": "DRAFT",
                 "publishedOnPublication": False, "descriptionHtml": "<p>Old</p>"}
        shop = MagicMock()
        shop.read_product.side_effect = lambda id, pub: dict(state)
        def altered(id, html):
            state["descriptionHtml"] = html
            state["status"] = "ACTIVE"
        shop.update_description.side_effect = altered
        with self.assertRaisesRegex(RuntimeError, "state mismatch"):
            daily.backfill_banner(shop, [{"id": "p", "tags": ["daiso-daily"]}], {"items": []}, "pub")
        with self.assertRaisesRegex(RuntimeError, "publication state"):
            daily.backfill_banner(shop, [{"id": "p", "tags": ["daiso-daily"]}], {"items": []}, None)

    def test_opt_in_quarantine_precedes_backfill_and_daily_cap(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            cwd = os.getcwd()
            os.chdir(folder)
            try:
                shop = MagicMock()
                shop.existing_products.return_value = []
                shop.online_store_publication.return_value = "publication"
                registry = {"items": [{"date": "2026-10-10", "category": c[0]} for c in daily.CATEGORIES]}
                calls = []
                def quarantine(shop, products, reg, publication, results):
                    calls.append("quarantine")
                    results.append({"shopify_id": "p", "status": "quarantined_draft"})
                def backfill(shop, products, reg, publication):
                    calls.append("backfill")
                    return [{"shopify_id": "p", "status": "prefixed"}]
                with patch.object(daily, "DRY_RUN", False), patch.object(daily, "BACKFILL_BANNER", True), \
                     patch.object(daily, "QUARANTINE_BLOCKED_PUBLIC", True), \
                     patch.object(daily, "Shopify", return_value=shop), \
                     patch.object(daily, "load_registry", return_value=registry), \
                     patch.object(daily, "quarantine_blocked_public", side_effect=quarantine), \
                     patch.object(daily, "backfill_banner", side_effect=backfill), \
                     patch.object(daily, "kst_today", return_value="2026-10-10"), \
                     patch.dict(os.environ, {"SHOPIFY_STORE": "test.myshopify.com", "SHOPIFY_ADMIN_TOKEN": "test"}):
                    self.assertEqual(daily.main(), 0)
                self.assertEqual(calls, ["quarantine", "backfill"])
                result = json.loads(Path("out/daiso_daily_beauty_result.json").read_text(encoding="utf-8"))
                self.assertEqual(result["quarantine_blocked_public"][0]["status"], "quarantined_draft")
                self.assertTrue(all(x["status"] == "skipped_already_today" for x in result["results"]))
            finally:
                os.chdir(cwd)

    def test_backfill_runs_before_daily_cap(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            cwd = os.getcwd()
            os.chdir(folder)
            try:
                shop = MagicMock()
                shop.existing_products.return_value = []
                shop.online_store_publication.return_value = "pub"
                registry = {"items": [{"date": "2026-10-10", "category": c[0]} for c in daily.CATEGORIES]}
                with patch.object(daily, "DRY_RUN", False), patch.object(daily, "BACKFILL_BANNER", True), \
                     patch.object(daily, "Shopify", return_value=shop), \
                     patch.object(daily, "load_registry", return_value=registry), \
                     patch.object(daily, "backfill_banner", return_value=[{"shopify_id": "p", "status": "prefixed"}]) as backfill, \
                     patch.object(daily, "kst_today", return_value="2026-10-10"), \
                     patch.dict(os.environ, {"SHOPIFY_STORE": "test.myshopify.com", "SHOPIFY_ADMIN_TOKEN": "test"}):
                    self.assertEqual(daily.main(), 0)
                    backfill.assert_called_once_with(shop, [], registry, "pub")
                result = json.loads(Path("out/daiso_daily_beauty_result.json").read_text(encoding="utf-8"))
                self.assertEqual(result["banner_backfill"][0]["status"], "prefixed")
                self.assertTrue(all(r["status"] == "skipped_already_today" for r in result["results"]))
            finally:
                os.chdir(cwd)

    def test_workflow_tests_before_write_and_retains_registry_recovery(self):
        workflow = (SCRIPT.parents[1]/".github/workflows/daiso-daily-beauty-shopify.yml").read_text(encoding="utf-8")
        test_command = "python -B -m unittest discover -s tests -p test_daiso_daily_beauty_to_shopify.py"
        write_command = "run: python scripts/daiso_daily_beauty_to_shopify.py"
        self.assertLess(workflow.index(test_command), workflow.index(write_command))
        self.assertIn("path: |\n            out/daiso_daily_beauty_result.json\n            data/shopify_daily_registry.json", workflow)
        self.assertIn("quarantine_blocked_public:", workflow)

    def test_price_unfit_reason_excludes_bad_margin(self):
        ok = {"single": {"price_usd": 14.99, "net_profit_usd": 4.0, "margin_pct": 33.6},
              "pack": {"ok": True, "margin_pct": 48.7}, "min_margin": 0.30}
        self.assertIsNone(daily.price_unfit_reason(3000, ok))
        low = {**ok, "single": {"price_usd": 14.99, "net_profit_usd": 3.0, "margin_pct": 24.0}}
        self.assertTrue(daily.price_unfit_reason(3000, low).startswith("single_margin_below_floor"))
        self.assertEqual(daily.price_unfit_reason(3000, {**ok, "pack": {"ok": False, "margin_pct": 10}}), "bundle_margin_not_ok")
        self.assertEqual(daily.price_unfit_reason(0, ok), "no_cost_price")
        neg = {**ok, "single": {"price_usd": 9.0, "net_profit_usd": -1.0, "margin_pct": -5.0}}
        self.assertEqual(daily.price_unfit_reason(3000, neg), "single_unprofitable")
        est = {**ok, "min_margin": 0.35, "single": {"price_usd": 14.99, "net_profit_usd": 4.0, "margin_pct": 33.6}}
        self.assertTrue(daily.price_unfit_reason(3000, est).startswith("single_margin_below_floor"))

    def test_banner_exact_prefix(self):
        self.assertEqual(daily.TAGLINE_HTML, "<p><strong>한국여성들이 즐겨찾는 제품</strong></p>")


if __name__ == "__main__":
    unittest.main()
