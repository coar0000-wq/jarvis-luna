"""Offline tests. No Shopify writes or live Daiso calls."""
import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/daiso_daily_beauty_to_shopify.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("daily", SCRIPT)
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)
REAL_SAFETY = daily.manufacturer_safety_record  # setUp 은 기본으로 '덮임' 으로 대체한다. 실제 함수는 이 참조로 검증한다.
SAFETY_COVERED = {"pd_no": "123", "covered": True, "reason": None}

# 가격 근거가 통과한 상태의 최소 픽스처 (price_unfit_reason 은 근거 필드가 없으면 통과시키지 않는다).
EVIDENCE_OK = {"ok": True, "source": "serpapi_google_shopping", "reasons": []}


class DailySafetyTests(unittest.TestCase):
    def setUp(self):
        # These are mocked Shopify runs. Never leave a fictitious product in
        # the repository's real price observation ledger.
        price_log = patch.object(daily, "log_price_position")
        price_log.start()
        self.addCleanup(price_log.stop)
        covered = patch.object(daily, "manufacturer_safety_record", return_value=dict(SAFETY_COVERED))
        covered.start()
        self.addCleanup(covered.stop)

    def test_all_categories_s_only_without_a_fallback(self):
        skin = daily.s_ranked(daily.CATEGORIES[0])
        self.assertTrue(skin and all(x["grade"] == "S" for x in skin))
        for cat in daily.CATEGORIES:
            self.assertTrue(all(x["grade"] == "S" for x in daily.s_ranked(cat)))
            self.assertEqual(daily.grade_label(cat), "S")
            fixture={"all_scored":[{"pd_no":"a","bucket":cat[1],"grade":"A","shopify_score":99}]}
            with patch.object(Path, "read_text", return_value=json.dumps(fixture)):
                self.assertEqual(daily.s_ranked(cat), [])

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
                                    "compare_at_usd": 29.98}, "basis": "test", "shop_compare": {},
                    "evidence": dict(EVIDENCE_OK)}
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
                self.assertEqual(result["results"][0]["s_candidates"], len(daily.s_ranked(daily.CATEGORIES[0])))
                # 2026-10-11 카테고리 전담팀: 메이크업·바디도 S 후보가 생길 수 있다. 조회가 막히면 '적격 S 없음'.
                expected = ["skipped_no_eligible_s_grade" if daily.s_ranked(cat) else "skipped_no_s_grade"
                            for cat in daily.CATEGORIES[1:]]
                self.assertEqual([r["status"] for r in result["results"][1:]], expected)
                self.assertEqual([r["grade_required"] for r in result["results"]], ["S", "S", "S"])
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
                            "compare_at_usd": 29.98}, "basis": "test", "shop_compare": {},
                    "evidence": dict(EVIDENCE_OK)}
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

    # ------------------------------------------------------------------
    # 가격/마진 정책 (2026-10-11 사용자 승인): 마진은 경고, 가격 근거는 필수
    # ------------------------------------------------------------------
    def _pr(self, **over):
        pr = {"single": {"price_usd": 9.99, "net_profit_usd": -3.0, "margin_pct": -30.0},
              "pack": {"ok": True, "margin_pct": -40.0}, "min_margin": 0.30, "evidence": dict(EVIDENCE_OK)}
        pr.update(over)
        return pr

    def test_price_unfit_reason_ignores_margin_but_keeps_real_price_gates(self):
        loss = self._pr()
        self.assertIsNone(daily.price_unfit_reason(3000, loss))  # 적자여도 근거가 있으면 등록
        self.assertIsNone(daily.price_unfit_reason(3000, self._pr(single={"price_usd": 9.99, "net_profit_usd": 0.0, "margin_pct": 0.0})))
        self.assertEqual(daily.price_unfit_reason(0, loss), "no_cost_price")
        self.assertEqual(daily.price_unfit_reason(None, loss), "no_cost_price")
        missing = self._pr()
        del missing["evidence"]
        self.assertEqual(daily.price_unfit_reason(3000, missing), "price_evidence_invalid:price_evidence_missing")
        stale = self._pr(evidence={"ok": False, "reasons": ["price_evidence_stale:40.0d>30d"]})
        self.assertEqual(daily.price_unfit_reason(3000, stale), "price_evidence_invalid:price_evidence_stale:40.0d>30d")
        self.assertTrue(daily.price_unfit_reason(3000, self._pr(evidence={"ok": "yes"})).startswith("price_evidence_invalid"))
        for bad in (None, 0, -1, True, float("nan"), "9.99"):
            with self.subTest(price=bad):
                self.assertEqual(daily.price_unfit_reason(3000, self._pr(single={"price_usd": bad})), "single_price_invalid")
        self.assertEqual(daily.price_unfit_reason(3000, self._pr(pack={"ok": False})), "bundle_price_invalid")

    def _final(self, shop, base_price=None, base_evidence=None, landed1=8.0, landed2=14.0, weight_source="gosi_volume",
               name="테스트 세럼 50 ml", title="Test Serum 50 ml"):
        import pricing_model as pm
        row = {"weight_source": weight_source, "weight_g_est": 100, "shipping_unit_usd": 5.0, "tariff_usd": 1.0}
        with patch.object(daily, "_landed", side_effect=lambda pd, n, krw, qty: ((landed1 if qty == 1 else landed2), pm, row)), \
             patch.object(daily, "shop_compare", return_value=shop), \
             patch.object(daily, "fx_rate", return_value={"rate": 1400, "live": None, "saved": 1400}):
            return daily.final_prices("1", name, 3000, title, base_price, base_evidence)

    def _serp_evidence(self, days_old=1, query="Test Serum 50 ml", n=10, median=20.0):
        stamp = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
        return {"source": "serpapi_google_shopping", "median_usd": median, "sample_n": n, "query": query, "collected_at": stamp}

    def test_final_prices_follow_shop_com_evidence_below_breakeven_with_warnings(self):
        shop = {"lowest_usd": 6.5, "match_count": 3, "matches": [{"title": "Test Serum 50 ml", "usd": 6.5}]}
        pr = self._final(shop)
        self.assertEqual(pr["single"]["price_usd"], 5.99)  # 최저가보다 낮게, 원가 바닥 없음
        self.assertTrue(pr["evidence"]["ok"])
        self.assertEqual(pr["evidence"]["source"], "shop_com_live_comparable")
        self.assertLess(pr["single"]["net_profit_usd"], 0)
        self.assertIn("single:price_at_or_below_breakeven", pr["profit_warnings"])
        self.assertTrue(any(w.startswith("pack:margin_below_target") for w in pr["profit_warnings"]))
        self.assertFalse(pr["profitability_blocks_registration"])
        self.assertTrue(pr["pack"]["ok"])
        self.assertIsNone(daily.price_unfit_reason(3000, pr))

    def test_final_prices_reject_shop_com_volume_mismatch_and_use_fresh_serp(self):
        shop = {"lowest_usd": 6.5, "match_count": 1, "matches": [{"title": "Test Serum 100 ml", "usd": 6.5}]}
        evidence = self._serp_evidence()
        pr = self._final(shop, 18.99, evidence)
        self.assertEqual(pr["evidence"]["source"], "serpapi_google_shopping")
        self.assertEqual(pr["single"]["price_usd"], 18.99)
        self.assertTrue(any("price_evidence_volume_mismatch" in r for x in pr["evidence"]["rejected"] for r in x["reasons"]))
        self.assertIsNone(daily.price_unfit_reason(3000, pr))

    def test_final_prices_have_no_price_without_valid_evidence(self):
        none = {"lowest_usd": None, "matches": []}
        for label, evidence in (("none", None), ("stale", self._serp_evidence(days_old=90)),
                                ("small", self._serp_evidence(n=2)), ("volume", self._serp_evidence(query="Test Serum 100 ml")),
                                ("future", self._serp_evidence(days_old=-30))):
            with self.subTest(case=label):
                pr = self._final(none, 18.99, evidence)
                self.assertIsNone(pr["single"]["price_usd"])
                self.assertFalse(pr["evidence"]["ok"])
                self.assertTrue(daily.price_unfit_reason(3000, pr).startswith("price_evidence_invalid:price_evidence_missing"))
        unknown = self._final({"lowest_usd": 6.5, "match_count": 1, "matches": [{"title": "Test Serum", "usd": 6.5}]},
                              None, None, name="테스트 세럼", title="Test Serum")
        self.assertIsNone(unknown["single"]["price_usd"])
        self.assertTrue(any("volume_unverified_product" in r for x in unknown["evidence"]["rejected"] for r in x["reasons"]))

    def test_jarvis_price_uses_only_fresh_product_level_evidence_never_cost_plus(self):
        import pricing_model as pm
        now = datetime.now(timezone.utc).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        serp = {"1": {"median": 24.5, "n": 20, "query": "VT Reedle 2ml x 6"}}
        with patch.object(pm, "SERP", serp), patch.object(pm, "SERP_COLLECTED_AT", now):
            fresh = daily.jarvis_price("1", "VT 리들샷 2 ml*6개입", 3000)
            self.assertEqual(fresh["price_usd"], 23.99)
            self.assertTrue(fresh["evidence_assessment"]["ok"])
            self.assertIsNone(daily.jarvis_price("1", "VT 리들샷 50 ml", 3000)["price_usd"])  # 총량 불일치
            self.assertIsNone(daily.jarvis_price("2", "VT 리들샷 2 ml*6개입", 3000)["price_usd"])  # 근거 없음
        with patch.object(pm, "SERP", serp), patch.object(pm, "SERP_COLLECTED_AT", old):
            self.assertIsNone(daily.jarvis_price("1", "VT 리들샷 2 ml*6개입", 3000)["price_usd"])  # 낡음
        with patch.object(pm, "SERP", serp), patch.object(pm, "SERP_COLLECTED_AT", None):
            self.assertIsNone(daily.jarvis_price("1", "VT 리들샷 2 ml*6개입", 3000)["price_usd"])  # 수집 시각 불명

    def test_strategy_defines_three_s_only_categories_and_cannot_be_loosened(self):
        import copy
        import pricing_model as pm
        self.assertEqual([c[0] for c in daily.CATEGORIES], ["skincare", "makeup", "body"])
        self.assertEqual(daily.ALLOWED_GRADES, {"skincare": ("S",), "makeup": ("S",), "body": ("S",)})
        self.assertEqual(daily.STRATEGY["price_policy"]["mode"], "evidence_based_price")
        self.assertIs(daily.STRATEGY["price_policy"]["margin_hard_block"], False)
        doc = json.loads(pm.STRATEGY_PATH.read_text(encoding="utf-8"))
        pm.validate_strategy(copy.deepcopy(doc))
        loosen = {
            "grade A": lambda d: d["categories"][0].update(allowed_grades=["S", "A"]),
            "grade fallback": lambda d: d["grade_policy"].update(lower_grade_fallback=True),
            "category removed": lambda d: d.update(categories=d["categories"][:2]),
            "mode": lambda d: d["price_policy"].update(mode="cost_plus"),
            "margin hard block": lambda d: d["price_policy"].update(margin_hard_block=True),
            "evidence optional": lambda d: d["price_policy"]["price_evidence"].update(required=False),
            "cost plus evidence": lambda d: d["price_policy"]["price_evidence"].update(cost_plus_counts_as_evidence=True),
            "category benchmark allowed": lambda d: d["price_policy"]["price_evidence"]["sources"]["oliveyoung_us_benchmark"].update(allowed=True),
            "no freshness": lambda d: d["price_policy"]["price_evidence"]["sources"]["serpapi_google_shopping"].update(max_age_days=0),
            "volume optional": lambda d: d["price_policy"]["volume_comparison"].update(required=False),
            "volume loose": lambda d: d["price_policy"]["volume_comparison"].update(tolerance=0.5),
            "unknown volume accepted": lambda d: d["price_policy"]["volume_comparison"].update(on_unknown_product_volume="accept"),
            "serp claimed as market minimum": lambda d: d["price_policy"]["price_evidence"]["sources"]["serpapi_google_shopping"].update(price_claim="market_minimum"),
            "safety record optional": lambda d: d["price_policy"]["manufacturer_safety_record"].update(required=False),
            "safety deferred plan counts": lambda d: d["price_policy"]["manufacturer_safety_record"].update(deferred_plans_count_as_coverage=True),
            **{f"non-canonical allowlist path {bad}": (lambda b: lambda d: d["image_policy"]["reviewed_product_only_allowlist"].update(
                {"1": [{"path": b, "sha256": "a" * 64, "reviewed_by": "x", "reviewed_at": "2026-10-11"}]}))(bad)
               for bad in ("https://evil.example/a.jpg", "//evil.example/a.jpg", "a.jpg", "/a/../b.jpg", "/a.jpg?x=1", "/a.jpg#f", "/dir/", "")},
            "allowlist off": lambda d: d["image_policy"].update(require_allowlist=False),
            "face check off": lambda d: d["image_policy"].update(retain_face_verification=False),
            "faces allowed": lambda d: d["image_policy"].update(human_faces_prohibited=False),
            "unreviewed allowlist entry": lambda d: d["image_policy"]["reviewed_product_only_allowlist"].update(
                {"1": [{"path": "/a.jpg", "sha256": "abc"}]}),
        }
        for label, mutate in loosen.items():
            with self.subTest(label=label):
                bad = copy.deepcopy(doc)
                mutate(bad)
                with self.assertRaises(ValueError):
                    pm.validate_strategy(bad)

    def test_volume_parsers_agree_and_profitability_never_blocks(self):
        import pricing_model as pm
        for text in ("2ml*6개입", "2 ml x 6 ea", "90g", "1.69 fl oz", "3 x 90g", "Serum 30 ml", "no size", "", None):
            with self.subTest(text=text):
                self.assertEqual(daily.parse_size(text), pm.parse_volume(text))
        loss = pm.profitability_advisory(5.0, 8.0)
        self.assertEqual(loss["status"], "loss")
        self.assertFalse(loss["blocks_registration"])
        self.assertEqual(pm.profitability_advisory(100.0, 10.0)["warnings"], [])

    def test_images_only_from_reviewed_allowlist_with_hash_and_face_check_retained(self):
        import hashlib
        import daiso_images

        def digest(data):
            return hashlib.sha256(data).hexdigest()
        good, changed, unlisted = b"reviewed-bytes", b"replaced-bytes", b"never-reviewed"
        entry = {"reviewed_by": "tester", "reviewed_at": "2026-10-11"}
        policy = {"reviewed_product_only_allowlist": {"55": [
            {"path": "/img/a.jpg", "sha256": digest(good), **entry},
            {"path": "/img/b.jpg", "sha256": digest(good), **entry}]}}
        cdn = daily.DAISO_CDN
        payloads = {cdn + "/img/a.jpg": good, cdn + "/img/b.jpg": changed, cdn + "/img/c.jpg": unlisted}

        class Response:
            def __init__(self, data):
                self.data = data
            def read(self):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        opened, selected = [], []
        def fake_open(request, timeout=0):
            opened.append(request.full_url)
            return Response(payloads[request.full_url])
        def fake_select(blobs):
            selected.append(list(blobs))
            return list(blobs), []
        product = {"pdNo": "55", "pdImgUrl": "/img/a.jpg", "pdImgUrlList": ["/img/a.jpg", "/img/b.jpg", "/img/c.jpg"]}
        with patch.object(daily, "IMAGE_POLICY", policy), patch.object(daily.urllib.request, "urlopen", fake_open), \
             patch.object(daiso_images, "select_images", fake_select):
            out = daily.prepare_images(product, None)
        self.assertEqual(out["source_urls"], [cdn + "/img/a.jpg"])
        self.assertEqual(selected, [[(cdn + "/img/a.jpg", good)]])  # 얼굴 검증 단계는 허용된 이미지에도 그대로 거친다
        reasons = {d["url"]: d["reason"] for d in out["skipped"]}
        self.assertEqual(reasons[cdn + "/img/b.jpg"], "reviewed_image_hash_mismatch")
        self.assertEqual(reasons[cdn + "/img/c.jpg"], "not_in_reviewed_product_only_allowlist")
        self.assertNotIn(cdn + "/img/c.jpg", opened)  # 허용 목록 밖은 내려받지도 않는다
        # 얼굴 검증이 거부하면 허용 목록에 있어도 쓰지 않는다
        with patch.object(daily, "IMAGE_POLICY", policy), patch.object(daily.urllib.request, "urlopen", fake_open), \
             patch.object(daiso_images, "select_images", lambda blobs: ([], [{"url": blobs[0][0], "reason": "face_detected:1"}])):
            vetoed = daily.prepare_images(product, None)
        self.assertEqual(vetoed["source_urls"], [])
        self.assertIn("face_detected:1", [d["reason"] for d in vetoed["skipped"]])
        # 허용 목록이 비어 있으면 어떤 이미지도 쓰지 않고 내려받지도 않는다
        opened.clear()
        with patch.object(daily, "IMAGE_POLICY", {"reviewed_product_only_allowlist": {}}), \
             patch.object(daily.urllib.request, "urlopen", fake_open):
            empty = daily.prepare_images(product, None)
        self.assertEqual((empty["source_urls"], opened), ([], []))
        self.assertTrue(all(d["reason"] == "not_in_reviewed_product_only_allowlist" for d in empty["skipped"]))

    def test_allowlisted_paths_are_fetched_even_when_not_advertised_with_hash_and_face_veto(self):
        import hashlib
        import daiso_images
        cdn = daily.DAISO_CDN
        thumb2, thumb3, raw = b"thumb-00-02", b"thumb-00-03", b"raw-advertised"
        reviewer = "Aside automated visual inspection (not human approval)"
        entry = lambda path, data: {"path": path, "sha256": hashlib.sha256(data).hexdigest(),  # noqa: E731
                                    "reviewed_by": reviewer, "reviewed_at": "2026-10-11"}
        policy = {"reviewed_product_only_allowlist": {"77": [entry("/t/850_00_02.jpg", thumb2), entry("/t/850_00_03.jpg", thumb3)]}}
        payloads = {cdn + "/t/850_00_02.jpg": thumb2, cdn + "/t/850_00_03.jpg": thumb3, cdn + "/r/raw_00_01.jpg": raw}

        class Response:
            def __init__(self, data):
                self.data = data
            def read(self):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        opened, selected = [], []
        def fake_open(request, timeout=0):
            opened.append(request.full_url)
            return Response(payloads[request.full_url])
        def fake_select(blobs):
            selected.append([u for u, _ in blobs])
            return list(blobs), []
        product = {"pdNo": "77", "pdImgUrl": "/r/raw_00_01.jpg", "pdImgUrlList": ["/r/raw_00_01.jpg"]}  # 광고는 원본 1장뿐
        with patch.object(daily, "IMAGE_POLICY", policy), patch.object(daily.urllib.request, "urlopen", fake_open), \
             patch.object(daiso_images, "select_images", fake_select):
            out = daily.prepare_images(product, None)
        self.assertEqual(out["source_urls"], [cdn + "/t/850_00_02.jpg", cdn + "/t/850_00_03.jpg"])
        self.assertEqual(selected, [out["source_urls"]])  # 얼굴 검증은 허용 목록 이미지에도 그대로
        self.assertNotIn(cdn + "/r/raw_00_01.jpg", opened)  # 광고됐어도 허용 목록에 없으면 받지 않는다
        self.assertEqual(out["skipped"], [{"url": cdn + "/r/raw_00_01.jpg", "reason": "not_in_reviewed_product_only_allowlist"}])
        self.assertEqual(out["total"], 3)
        # 광고 목록과 허용 목록이 겹치면 한 번만 받는다
        opened.clear()
        both = {"pdNo": "77", "pdImgUrl": "/t/850_00_02.jpg", "pdImgUrlList": ["/t/850_00_02.jpg", "/t/850_00_03.jpg"]}
        with patch.object(daily, "IMAGE_POLICY", policy), patch.object(daily.urllib.request, "urlopen", fake_open), \
             patch.object(daiso_images, "select_images", fake_select):
            daily.prepare_images(both, None)
        self.assertEqual(sorted(opened), sorted(set(opened)))
        # 해시가 다르면 쓰지 않는다 / YuNet 거부도 유지된다
        payloads[cdn + "/t/850_00_03.jpg"] = b"swapped"
        with patch.object(daily, "IMAGE_POLICY", policy), patch.object(daily.urllib.request, "urlopen", fake_open), \
             patch.object(daiso_images, "select_images", lambda blobs: (list(blobs)[:1], [{"url": "v", "reason": "face_detected:1"}])):
            out = daily.prepare_images(product, None)
        self.assertEqual(out["source_urls"], [cdn + "/t/850_00_02.jpg"])
        self.assertEqual(sorted(d["reason"] for d in out["skipped"]),
                         ["face_detected:1", "not_in_reviewed_product_only_allowlist", "reviewed_image_hash_mismatch"])

    def _run_main(self, pricing, pick_effect, price_evidence=None, safety=None, safety_files=None):
        import os
        candidate = {"pdNo": "123", "pdNm": "본셉 세럼 30 ml", "brndNm": "본셉", "pdPrc": "3000",
                     "_grade": "S", "_source": "jarvis_s_list"}
        state = {"status": "DRAFT", "published": False}
        shop = MagicMock()
        shop.store = "test.myshopify.com"
        shop.existing_products.return_value = []
        shop.exists.return_value = False
        shop.online_store_publication.return_value = "gid://shopify/Publication/1"
        def create(item, on_created):
            prod = {"id": "gid://shopify/Product/123", "handle": "bonsep-serum"}
            on_created(prod)
            return prod
        shop.create.side_effect = create
        shop.read_product.side_effect = lambda pid, pub: {
            "id": "gid://shopify/Product/123", "handle": "bonsep-serum", "title": "Bonsep Serum 30 ml",
            "status": state["status"], "publishedOnPublication": state["published"],
            "variants": {"nodes": [{"sku": "DS-123-1", "price": f"{pricing['single']['price_usd'] or 0:.2f}"},
                                    {"sku": "DS-123-2", "price": f"{pricing['pack']['price_usd'] or 0:.2f}"}]},
            "media": {"nodes": [{"mediaContentType": "IMAGE", "status": "READY"}]}}
        shop.set_status.side_effect = lambda pid, status: state.update(status=status)
        shop.publish.side_effect = lambda pid, pub: state.update(published=True)
        shop.publish_channels.return_value = {}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"data").mkdir()
            for relative, document in (safety_files or {}).items():
                target = root/"data/manual"/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(document), encoding="utf-8")
            safety_fn = REAL_SAFETY if safety_files is not None else (safety or MagicMock(return_value=dict(SAFETY_COVERED)))
            cwd = os.getcwd()
            os.chdir(root)
            safety_patch = patch.object(daily, "manufacturer_safety_record", safety_fn)  # with 중첩 한도(20) 때문에 분리
            safety_patch.start()
            try:
                effect = pick_effect(candidate)
                # Python 3.11 has a 20-block compiler limit; mock lifetimes stay identical.
                with ExitStack() as stack:
                    contexts = (patch.object(daily, "ROOT", root), patch.object(daily, "REGISTRY", root/"data/registry.json"), \
                     patch.object(daily, "DRY_RUN", False), patch.object(daily, "ONLY", {"skincare"}), \
                     patch.object(daily, "BACKFILL_BANNER", False), patch.object(daily, "QUARANTINE_BLOCKED_PUBLIC", False), \
                     patch.object(daily, "Shopify", return_value=shop), \
                     patch.object(daily, "s_ranked", return_value=[{"pd_no": "123", "grade": "S"}]), \
                     patch.object(daily, "pick", side_effect=effect), \
                     patch.object(daily, "gemini_copy", return_value=None), \
                     patch.object(daily, "fallback_copy", return_value=("Bonsep Serum 30 ml", "<p>Serum.</p>")), \
                     patch.object(daily, "jarvis_price", return_value={"price_usd": 9.99, "evidence": price_evidence}), \
                     patch.object(daily, "final_prices", return_value=pricing), \
                     patch.object(daily, "collect_gosi", return_value={"volume": "30 ml", "gosi_ok": True,
                                                                        "missing": [], "ingredients": "INCI"}), \
                     patch.object(daily, "build_us_label", return_value={"html": "<p>INCI.</p>", "reasons": [], "label": {}}), \
                     patch.object(daily, "canonical_public_gate", return_value={"public_ready": True, "reasons": []}), \
                     patch.object(daily, "has_claims", return_value=False), \
                     patch.object(daily, "prepare_images", return_value={"source_urls": ["source"], "resource_urls": ["resource"],
                                                                        "skipped": []}), \
                     patch.dict(os.environ, {"SHOPIFY_STORE": "test.myshopify.com", "SHOPIFY_ADMIN_TOKEN": "test"}))
                    for context in contexts:
                        stack.enter_context(context)
                    code = daily.main()
                result = json.loads((root/"out/daiso_daily_beauty_result.json").read_text(encoding="utf-8"))
                registry_file = root/"data/registry.json"
                registry = json.loads(registry_file.read_text(encoding="utf-8")) if registry_file.exists() else {"items": []}
            finally:
                safety_patch.stop()
                os.chdir(cwd)
        return code, result, registry, shop

    def test_loss_making_but_evidenced_s_product_registers_with_warning(self):
        warnings = ["single:price_at_or_below_breakeven", "pack:margin_below_target:-25.0%<40.0%"]
        pricing = {"single": {"price_usd": 9.99, "margin_pct": -20.0, "net_profit_usd": -2.0},
                   "pack": {"ok": True, "price_usd": 16.99, "margin_pct": -25.0, "net_profit_usd": -4.0, "compare_at_usd": 19.98},
                   "basis": "test", "shop_compare": {}, "evidence": dict(EVIDENCE_OK), "profit_warnings": warnings}
        code, result, registry, shop = self._run_main(pricing, lambda candidate: [candidate])
        self.assertEqual(code, 0)
        record = result["results"][0]
        self.assertEqual(record["status"], "created")  # 건너뛰기도 초안도 아니다
        self.assertEqual(record["draft_reasons"], [])
        self.assertEqual(record["profitability_warnings"], warnings)
        self.assertEqual(registry["items"][0]["status"], "ACTIVE")
        self.assertEqual(registry["items"][0]["profitability_warnings"], warnings)
        shop.set_status.assert_called_with("gid://shopify/Product/123", "ACTIVE")

    # ------------------------------------------------------------------
    # 제조사 안전성 기록 게이트 (안전 게이트, 마진과 무관)
    # ------------------------------------------------------------------
    def _profile_root(self, folder, public=None, private=None, labels=None):
        root = Path(folder)
        manual = root/"data/manual"
        manual.mkdir(parents=True)
        if public is not None:
            (manual/"mocra_business.json").write_text(json.dumps(public), encoding="utf-8")
        if private is not None:
            (manual/"mocra_profile.json").write_text(private if isinstance(private, str) else json.dumps(private), encoding="utf-8")
        if labels is not None:
            (root/"data/daiso_real").mkdir(parents=True)
            (root/"data/daiso_real/daiso_us_labels.json").write_text(json.dumps(labels), encoding="utf-8")
        return root

    def test_safety_record_requires_this_pd_no_in_covered_list_per_product(self):
        reason = "manufacturer_safety_record_missing:pd_no_not_in_safety_substantiation.covered_pd_nos"
        public = {"safety_substantiation": {"covered_pd_nos": ["1067498"], "note": "n"}}
        with tempfile.TemporaryDirectory() as folder, patch.object(daily, "ROOT", self._profile_root(folder, public)):
            covered = REAL_SAFETY("1067498")
            self.assertTrue(covered["covered"])
            self.assertIsNone(covered["reason"])
            self.assertTrue(REAL_SAFETY(1067498)["covered"])  # 숫자 pdNo 도 같은 기록
            other = REAL_SAFETY("1059834")  # 다른 상품은 이 상품의 기록으로 덮이지 않는다
            self.assertFalse(other["covered"])
            self.assertEqual(other["reason"], reason)

    def test_safety_record_ignores_deferred_plans_and_label_evidence(self):
        labels = {"1067498": {"product_safety_evidence": {"human_approved": True, "source_type": "manufacturer_product_safety",
                                                           "product_id": "1067498", "note": "obtain docs after first sale"}}}
        public = {"safety_substantiation": {"covered_pd_nos": [], "note": "plan only"}}
        with tempfile.TemporaryDirectory() as folder, patch.object(daily, "ROOT", self._profile_root(folder, public, labels=labels)):
            result = REAL_SAFETY("1067498")
        self.assertFalse(result["covered"])
        self.assertTrue(result["reason"].startswith("manufacturer_safety_record_missing:"))

    def test_safety_record_private_overlay_wins_and_is_never_exposed(self):
        public = {"safety_substantiation": {"covered_pd_nos": ["1"]}}
        secret = "PRIVATE-CONTACT-DO-NOT-LEAK"
        private = {"owner_note": secret, "safety_substantiation": {"covered_pd_nos": ["2"]}}
        with tempfile.TemporaryDirectory() as folder, patch.object(daily, "ROOT", self._profile_root(folder, public, private)):
            added, replaced = REAL_SAFETY("2"), REAL_SAFETY("1")
        self.assertTrue(added["covered"])  # 비공개가 공개 위에 엹힌다
        self.assertFalse(replaced["covered"])  # 같은 키는 비공개가 이긴다 (build_mocra_readiness 와 같은 규칙)
        self.assertNotIn(secret, json.dumps([added, replaced]))
        self.assertEqual(added["private_profile"], "present")

    def test_safety_record_fails_closed_on_unreadable_or_malformed_profile(self):
        good = {"safety_substantiation": {"covered_pd_nos": ["1"]}}
        cases = {
            "public missing": (None, None, "profile_unreadable"),
            "public not an object": ([], None, "profile_unreadable"),
            "private unparseable": (good, "{broken", "profile_unreadable"),
            "no substantiation block": ({"role": "reseller"}, None, "safety_substantiation_malformed"),
            "covered not a list": ({"safety_substantiation": {"covered_pd_nos": "1"}}, None, "safety_substantiation_malformed"),
        }
        for label, (public, private, reason) in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as folder, \
                 patch.object(daily, "ROOT", self._profile_root(folder, public, private)):
                result = REAL_SAFETY("1")
                self.assertFalse(result["covered"])
                self.assertEqual(result["reason"], "manufacturer_safety_record_missing:" + reason)

    def _ok_pricing(self):
        return {"single": {"price_usd": 9.99, "margin_pct": -20.0, "net_profit_usd": -2.0},
                "pack": {"ok": True, "price_usd": 16.99, "margin_pct": -25.0, "net_profit_usd": -4.0, "compare_at_usd": 19.98},
                "basis": "test", "shop_compare": {}, "evidence": dict(EVIDENCE_OK)}

    def test_registration_runs_only_for_a_covered_product(self):
        covered = {"mocra_business.json": {"safety_substantiation": {"covered_pd_nos": ["123"]}}}
        code, result, registry, shop = self._run_main(self._ok_pricing(), lambda c: [c], safety_files=covered)
        self.assertEqual(code, 0)
        self.assertEqual(result["results"][0]["status"], "created")
        shop.create.assert_called_once()

    def test_registration_fails_closed_before_creation_when_record_absent_or_deferred(self):
        for label, files in (("empty list", {"mocra_business.json": {"safety_substantiation": {"covered_pd_nos": []}}}),
                             ("other product only", {"mocra_business.json": {"safety_substantiation": {"covered_pd_nos": ["999"]}}}),
                             ("no profile", {})):
            with self.subTest(case=label):
                code, result, registry, shop = self._run_main(self._ok_pricing(), lambda c: [c, None], safety_files=files)
                record = result["results"][0]
                self.assertEqual(record["status"], "skipped_no_eligible_s_grade")
                self.assertTrue(record["safety_excluded"][0]["reason"].startswith("manufacturer_safety_record_missing:"))
                self.assertEqual(record["safety_excluded"][0]["pd_no"], "123")
                shop.create.assert_not_called()
                shop.set_status.assert_not_called()
                shop.publish.assert_not_called()
                self.assertEqual(registry["items"], [])

    def test_uncovered_product_does_not_block_a_covered_one(self):
        covered = {"mocra_business.json": {"safety_substantiation": {"covered_pd_nos": ["123"]}}}
        code, result, registry, shop = self._run_main(
            self._ok_pricing(), lambda c: [{**c, "pdNo": "999", "pdNm": "다른 세럼 30 ml"}, c], safety_files=covered)
        self.assertEqual(code, 0)
        record = result["results"][0]
        self.assertEqual(record["status"], "created")
        self.assertEqual(record["daiso_pdNo"], "123")
        shop.create.assert_called_once()

    def test_coverage_lost_before_create_blocks_creation_and_before_publish_keeps_draft(self):
        lost = {"pd_no": "123", "covered": False, "reason": "manufacturer_safety_record_missing:test"}
        code, result, registry, shop = self._run_main(
            self._ok_pricing(), lambda c: [c], safety=MagicMock(side_effect=[dict(SAFETY_COVERED), lost]))
        record = result["results"][0]
        self.assertEqual(record["status"], "blocked_manufacturer_safety_record_missing")
        shop.create.assert_not_called()
        code, result, registry, shop = self._run_main(
            self._ok_pricing(), lambda c: [c], safety=MagicMock(side_effect=[dict(SAFETY_COVERED), dict(SAFETY_COVERED), lost]))
        record = result["results"][0]
        self.assertEqual(record["status"], "created_draft")
        self.assertIn("manufacturer_safety_record_missing:test", record["draft_reasons"])
        shop.set_status.assert_not_called()
        shop.publish.assert_not_called()

    def test_serp_evidence_is_a_reference_basis_never_a_market_minimum_claim(self):
        none = {"lowest_usd": None, "matches": []}
        pr = self._final(none, 18.99, self._serp_evidence())
        self.assertEqual(pr["evidence"]["detail"]["price_claim"], "reference_price_basis_only_not_market_minimum")
        self.assertIn("시장 최저가 아님", pr["basis"])
        shop = {"lowest_usd": 6.5, "match_count": 3, "matches": [{"title": "Test Serum 50 ml", "usd": 6.5}]}
        verified = self._final(shop)
        self.assertEqual(verified["evidence"]["detail"]["price_claim"], "undercuts_lowest_verified_same_item_comparator")
        # 검증에서 탈락한 shop.com 최저가는 장부에 최저가로 남기지 않는다 (SerpApi 가격이 채택된 경우)
        rejected_shop = {"lowest_usd": 6.5, "match_count": 1, "matches": [{"title": "Test Serum 100 ml", "usd": 6.5}]}
        pricing = {**self._ok_pricing(), "shop_compare": rejected_shop,
                   "evidence": {"ok": True, "source": "serpapi_google_shopping", "reasons": [],
                                "detail": {"price_claim": "reference_price_basis_only_not_market_minimum"}}}
        code, result, registry, _ = self._run_main(pricing, lambda c: [c])
        entry = registry["items"][0]
        self.assertIsNone(entry["shop_com_lowest_usd"])
        self.assertEqual(entry["price_position"], "no_comparison")
        self.assertEqual(entry["price_claim"], "reference_price_basis_only_not_market_minimum")
        pricing["evidence"] = {"ok": True, "source": "shop_com_live_comparable", "reasons": [],
                               "detail": {"price_claim": "undercuts_lowest_verified_same_item_comparator"}}
        code, result, registry, _ = self._run_main(pricing, lambda c: [c])
        self.assertEqual(registry["items"][0]["shop_com_lowest_usd"], 6.5)

    # ------------------------------------------------------------------
    # 상업 우선순위 (build_beauty_price_strategy, 오프라인) - 순서만 바꾸고 게이트·등급은 건드리지 않는다
    # ------------------------------------------------------------------
    def _priority_root(self, folder, market_hours=1.0, config=True, market=True, own_hours=1.0):
        """S 두 개(S1 점수 90, S2 점수 86)와 검증된 가격 우위를 가질 수 있는 S2, A 하나(A1 점수 99)를 만든다."""
        root = Path(folder)
        data = root/"data"
        stamp = lambda hours: (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()  # noqa: E731
        def row(pd, name, grade, score, **extra):
            base = {"pd_no": pd, "name": name, "bucket": "스킨케어", "grade": grade, "shopify_score": score, "price_krw": 5000,
                    "s_rule": "strong_form" if grade == "S" else "score_below_82",
                    "best_global_match": {"channel": "x", "similarity": 0.7, "matched_tokens": ["serum"]},
                    "score_breakdown": {"penalty": 0}, "canonical_product_id": "CP" + pd}
            base.update(extra)
            return base
        def write(rel, value):
            target = data/rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(value), encoding="utf-8")
        write("daiso_real/shopify_demand_score.json", {"generated_at": stamp(0), "s_slot_limit": 10, "s_slot_open": 8, "all_scored": [
            row("S1", "테스트 세럼 30 ml", "S", 90, s_rank=1), row("S2", "테스트 앩플 30 ml", "S", 86, s_rank=2),
            row("A1", "테스트 크림 30 ml", "A", 99)]})
        # TEST FIXTURE ONLY: an independently timed own-price observation, never a date-only production backfill.
        write("shopify_daily_registry.json", {"snapshot_at": stamp(own_hours) if own_hours is not None else None, "items": [
            {"pd_no": "S2", "status": "ACTIVE", "title": "Acme Glow Ampoule 30 ml", "single_usd": 10.0, "date": "2026-10-10"},
            {"pd_no": "A1", "status": "ACTIVE", "title": "Acme Glow Cream 30 ml", "single_usd": 1.0, "date": "2026-10-10"}]})
        write("daiso_real/candidate_comparison.json", {"excluded_market_sources": {}})
        write("pricing_model.json", {"exchange_rate": {"usd_to_krw": 1341.69},
                                 "cost_basis": {"payment_fee": "Shopify 3.9% + 3.5% = 7.4%"}, "scenarios": {}})
        write("daiso_real/profitability_rule.json", {"min_margin_pct": 15.0, "min_net_profit_usd": 1.5})
        if market:
            def item(title, price, ship):
                return {"product_id": "id-" + title[:8], "product": title, "brand": "Acme", "price_usd": price,
                        "currency": "USD", "is_soldout": False, "shipping_usd": ship}
            write("oliveyoung_us_products.json", {"collected_at": stamp(market_hours), "is_stale": False, "products": [
                item("Acme Glow Ampoule 1.01 fl. oz.(30ml)", 30.0, 0.0), item("Acme Glow Cream 30ml", 30.0, 0.0)]})
        if config is True:
            (root/"config").mkdir()
            (root/"config/daiso_commerce_strategy.json").write_text(
                (SCRIPT.parents[1]/"config/daiso_commerce_strategy.json").read_text(encoding="utf-8"), encoding="utf-8")
        elif isinstance(config, str):
            (root/"config").mkdir()
            (root/"config/daiso_commerce_strategy.json").write_text(config, encoding="utf-8")
        return root

    def _ranked(self, root, shipping="3.0"):
        import os
        env = {"OWN_SHIPPING_USD": shipping} if shipping is not None else {}
        with patch.object(daily, "ROOT", root), patch.dict(os.environ, env):
            if shipping is None:
                os.environ.pop("OWN_SHIPPING_USD", None)
            return daily.s_ranked(daily.CATEGORIES[0])

    def test_verified_price_advantage_ranks_s_first_with_transparent_components(self):
        with tempfile.TemporaryDirectory() as folder:
            rows = self._ranked(self._priority_root(folder))
        self.assertEqual([r["pd_no"] for r in rows], ["S2", "S1"])  # 정본 순서는 S1(90) -> S2(86)
        top, other = rows[0]["_priority"], rows[1]["_priority"]
        self.assertEqual(top["status"], "live_strategy")
        self.assertEqual(top["evidence_status"], "verified_price_advantage")
        self.assertTrue(top["price_position_verified"])
        self.assertEqual(top["price_position"], "verified_below")
        self.assertAlmostEqual(top["components"]["demand_score_x0.6"], 51.6, places=2)
        self.assertGreater(top["components"]["verified_price_points"], 20)
        self.assertAlmostEqual(top["score"], top["components"]["demand_score_x0.6"] + top["components"]["verified_price_points"], places=2)
        self.assertEqual(top["canonical_index"], 1)
        self.assertIn("0.6*shopify_score", top["formula"])
        self.assertEqual(other["evidence_status"], "unknown_price_evidence")
        self.assertEqual(other["components"]["verified_price_points"], 0)
        self.assertAlmostEqual(other["score"], 54.0, places=2)
        self.assertTrue(all(r["grade"] == "S" for r in rows))

    def test_a_grade_is_never_upgraded_or_added_by_a_price_advantage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self._priority_root(folder)
            rows = self._ranked(root)
            import os
            with patch.object(daily, "ROOT", root), patch.dict(os.environ, {"OWN_SHIPPING_USD": "3.0"}):
                report_priority = daily.live_s_priority()
        # A1 도 검증된 가격 우위가 있지만(점수 99) 후보가 되거나 S 로 승격되지 않는다
        self.assertEqual(report_priority["by_pd"]["A1"]["price_position"], "verified_below")
        self.assertNotIn("A1", [r["pd_no"] for r in rows])
        self.assertTrue(all(r["grade"] == "S" for r in rows))
        # 등급은 정본 점수표가 정한다: 전략 리포트가 등급을 바꾸면 정본 순서로 되돌아간다
        with tempfile.TemporaryDirectory() as folder3:
            root = self._priority_root(folder3)
            import build_beauty_price_strategy as bps
            real_build = bps.build_strategy
            def upgrade(*args, **kwargs):
                report = real_build(*args, **kwargs)
                for prod in report["products"]:
                    if prod["pd_no"] == "A1":
                        prod["grade"] = "S"
                return report
            with patch.object(bps, "build_strategy", upgrade), patch.object(daily, "ROOT", root):
                fallback = daily.live_s_priority()
            self.assertEqual(fallback["status"], "fallback_canonical_order")
            self.assertEqual(fallback["reason"], "strategy_grade_differs_from_canonical")
            self.assertEqual(fallback["by_pd"], {})

    def test_unknown_stale_or_unshipped_evidence_earns_no_price_points(self):
        with tempfile.TemporaryDirectory() as folder:
            stale = self._ranked(self._priority_root(folder, market_hours=24 * 30))
        with tempfile.TemporaryDirectory() as folder:
            no_shipping = self._ranked(self._priority_root(folder), shipping=None)
        with tempfile.TemporaryDirectory() as folder:
            no_market = self._ranked(self._priority_root(folder, market=False))
        with tempfile.TemporaryDirectory() as folder:
            stale_own = self._ranked(self._priority_root(folder, own_hours=30.0))
        with tempfile.TemporaryDirectory() as folder:
            missing_own_clock = self._ranked(self._priority_root(folder, own_hours=None))
        for label, rows in ("stale", stale), ("own shipping unknown", no_shipping), ("no market", no_market), ("own price stale", stale_own), ("own price observation missing", missing_own_clock):
            with self.subTest(case=label):
                self.assertEqual([r["pd_no"] for r in rows], ["S1", "S2"])  # 정본 순서 유지
                for r in rows:
                    self.assertEqual(r["_priority"]["components"]["verified_price_points"], 0)
                    self.assertFalse(r["_priority"]["price_position_verified"])
                    self.assertNotEqual(r["_priority"]["evidence_status"], "verified_price_advantage")
                    self.assertAlmostEqual(r["_priority"]["score"], r["shopify_score"] * 0.6, places=2)
        # 배송비를 모르면 포지션은 provisional 이고 점수에 세지 않는다
        s2 = next(r for r in no_shipping if r["pd_no"] == "S2")["_priority"]
        self.assertEqual(s2["evidence_status"], "provisional_not_counted")
        self.assertGreater(s2["components"]["provisional_price_points_not_counted"], 0)

    def test_bad_strategy_or_inputs_fall_back_to_canonical_order_without_fake_scores(self):
        import build_beauty_price_strategy as bps
        cases = {
            "malformed config": (dict(config="{not json"), "strategy_config_missing_invalid_or_mismatched"),
            "missing config": (dict(config=False), "strategy_config_missing_invalid_or_mismatched"),
            "policy id mismatch": (dict(config=json.dumps({**json.loads((SCRIPT.parents[1]/"config/daiso_commerce_strategy.json")
                                                                       .read_text(encoding="utf-8")), "policy_id": "other"})),
                                   "strategy_config_missing_invalid_or_mismatched"),
        }
        for label, (kwargs, reason) in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as folder:
                rows = self._ranked(self._priority_root(folder, **kwargs))
                self.assertEqual([r["pd_no"] for r in rows], ["S1", "S2"])
                for r in rows:
                    meta = r["_priority"]
                    self.assertEqual(meta["status"], "fallback_canonical_order")
                    self.assertEqual(meta["reason"], reason)
                    self.assertIsNone(meta["score"])
                    self.assertIsNone(meta["components"])
        # 계산 중 예외 / 비정상 리포트
        broken = {
            "builder raises": (RuntimeError("boom"), "strategy_error:RuntimeError"),
            "unsafe policy flags": ("flags", "strategy_policy_flags_unsafe"),
            "grade changes reported": ("changes", "strategy_changed_grades"),
        }
        for label, (effect, reason) in broken.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as folder:
                root = self._priority_root(folder)
                real_build = bps.build_strategy
                def fake(*args, _effect=effect, **kwargs):
                    if isinstance(_effect, Exception):
                        raise _effect
                    report = real_build(*args, **kwargs)
                    if _effect == "flags":
                        report["policy"]["network_calls"] = True
                    else:
                        report["s_preservation"]["grade_changes"] = ["S1"]
                    return report
                with patch.object(bps, "build_strategy", fake):
                    rows = self._ranked(root)
                self.assertEqual([r["pd_no"] for r in rows], ["S1", "S2"])
                self.assertTrue(all(r["_priority"]["status"] == "fallback_canonical_order" and r["_priority"]["score"] is None
                                    and r["_priority"]["reason"] == reason for r in rows))
        # 정본 점수표가 깨지면 순서를 지어내지 않고 오류로 멈춘다
        with tempfile.TemporaryDirectory() as folder:
            root = self._priority_root(folder)
            (root/"data/daiso_real/shopify_demand_score.json").write_text("{broken", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                self._ranked(root)

    def test_priority_is_offline_and_only_reorders_never_adds_or_removes(self):
        import socket
        import urllib.request
        with tempfile.TemporaryDirectory() as folder:
            root = self._priority_root(folder)
            with patch.object(socket.socket, "connect", side_effect=AssertionError("network used")), \
                 patch.object(urllib.request, "urlopen", side_effect=AssertionError("network used")):
                rows = self._ranked(root)
            canonical_ids = ["S1", "S2"]
            self.assertEqual(sorted(r["pd_no"] for r in rows), canonical_ids)
            self.assertEqual(rows[0]["_priority"]["status"], "live_strategy")
        # pick 은 우선순위 메타를 상품에 실어 기록하고, 상품 조회·판매 가능·중복 검사는 그대로 거친다
        lookup = lambda pd: {"pdNo": pd, "pdNm": "Product " + pd, "pdPrc": "3000", "soldOutYn": "N",  # noqa: E731
                             "exhYn": "Y", "onlStckQy": 1, "pdImgUrl": "/x"}
        with patch.object(daily, "daiso_lookup", side_effect=lookup):
            picked = daily.pick(daily.CATEGORIES[0], None, set(), {"S2"}, {"items": []}, rows)  # 중복이면 다음 후보
        self.assertEqual(picked["pdNo"], "S1")
        self.assertEqual(picked["_priority"]["status"], "live_strategy")
        self.assertEqual(picked["_priority"]["canonical_index"], 0)

    def test_missing_price_evidence_still_skips_the_candidate(self):
        pricing = {"single": {"price_usd": None}, "pack": {"ok": False, "price_usd": None}, "basis": "근거 없음",
                   "shop_compare": {}, "evidence": {"ok": False, "reasons": ["price_evidence_missing"]}}
        code, result, registry, shop = self._run_main(pricing, lambda candidate: [candidate, None])
        self.assertEqual(code, 0)
        record = result["results"][0]
        self.assertEqual(record["status"], "skipped_no_eligible_s_grade")
        self.assertTrue(record["price_excluded"][0]["reason"].startswith("price_evidence_invalid:price_evidence_missing"))
        shop.create.assert_not_called()
        self.assertEqual(registry["items"], [])

    def test_banner_exact_prefix(self):
        self.assertEqual(daily.TAGLINE_HTML, "<p><strong>한국여성들이 즐겨찾는 제품</strong></p>")


if __name__ == "__main__":
    unittest.main()
