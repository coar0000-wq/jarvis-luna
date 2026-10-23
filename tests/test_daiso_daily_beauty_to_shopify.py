"""Offline tests. No Shopify writes or live Daiso calls."""
import importlib.util
import copy
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

# Isolate ambient workflow values before the registrar captures them at import time.
_AMBIENT_ENV = ("BODY_FALLBACK_CATALOG_PATH", "DRY_RUN", "ONLY_CATEGORIES")
_SAVED_ENV = {key: os.environ.pop(key) for key in _AMBIENT_ENV if key in os.environ}


def tearDownModule():
    os.environ.update(_SAVED_ENV)


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/daiso_daily_beauty_to_shopify.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("daily", SCRIPT)
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)
from test_manufacturer_safety import synthetic_receipt
from test_owner_draft_approval import decision_document


REAL_SAFETY = daily.manufacturer_safety_record  # setUp 은 기본으로 '덮임' 으로 대체한다. 실제 함수는 이 참조로 검증한다.
SAFETY_COVERED = {"pd_no": "123", "covered": True, "reason": None}

# 가격 근거가 통과한 상태의 최소 픽스처 (price_unfit_reason 은 근거 필드가 없으면 통과시키지 않는다).
EVIDENCE_OK = {"ok": True, "source": "serpapi_google_shopping", "reasons": []}


class DailySafetyTests(unittest.TestCase):
    def setUp(self):
        # These tests isolate price, safety, public-gate and priority behavior.
        # Actual source/time rechecks have dedicated offline integration fixtures
        # in test_current_s_eligibility.py; no production evidence is changed.
        current = patch.object(daily.current_s_eligibility, "assess_current",
            side_effect=lambda rows, root, **kwargs: {
                str(r.get("pd_no") or ""): {"eligible": True, "reasons": []} for r in rows})
        current.start()
        self.addCleanup(current.stop)
        recommendations = patch.object(daily.gate_signature, "current_recommendations",
                                       return_value=[{"pd_no": "123", "grade": "S"}])
        recommendations.start()
        self.addCleanup(recommendations.stop)
        # These are mocked Shopify runs. Never leave a fictitious product in
        # the repository's real price observation ledger.
        price_log = patch.object(daily, "log_price_position")
        price_log.start()
        self.addCleanup(price_log.stop)
        covered = patch.object(daily, "manufacturer_safety_record", return_value=dict(SAFETY_COVERED))
        covered.start()
        self.addCleanup(covered.stop)

    def test_all_categories_s_only_without_a_fallback(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(daily, "ROOT", Path(folder)):
            path = Path(folder)/"data/daiso_real/shopify_demand_score.json"
            path.parent.mkdir(parents=True)
            for cat in daily.CATEGORIES:
                fixture = {"all_scored": [
                    {"pd_no": "s", "desk": cat[0], "grade": "S", "shopify_score": 90},
                    {"pd_no": "a", "desk": cat[0], "grade": "A", "shopify_score": 99}]}
                path.write_text(json.dumps(fixture), encoding="utf-8")
                rows = daily.s_ranked(cat, priority={})
                self.assertEqual([row["pd_no"] for row in rows], ["s"])
                self.assertEqual(daily.grade_label(cat), "S")
                fixture["all_scored"].pop(0)
                path.write_text(json.dumps(fixture), encoding="utf-8")
                self.assertEqual(daily.s_ranked(cat, priority={}), [])

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
            original = daily.REGISTRY.read_bytes()
            # Reproduce the intermittent Windows failure without relying on a
            # scanner/file-lock race. Only the same atomic rename is retried.
            for winerror in (5, 32, 33):
                denied = PermissionError("temporary destination lock")
                denied.winerror = winerror
                with self.subTest(winerror=winerror), patch.object(daily.os, "name", "nt"), \
                     patch.object(daily.os, "replace", side_effect=[denied, denied, None]) as replace, \
                     patch.object(daily.time, "sleep") as wait:
                    daily.save_registry({"items": [{"pd_no": "102", "status": "create_reserved"}]})
                    self.assertEqual(replace.call_count, 3)
                    self.assertEqual(len({call.args for call in replace.call_args_list}), 1)
                    self.assertEqual([call.args[0] for call in wait.call_args_list], [0.02, 0.04])
                self.assertEqual(daily.REGISTRY.read_bytes(), original)
            denied = PermissionError("persistent destination lock")
            denied.winerror = 5
            with patch.object(daily.os, "name", "nt"), \
                 patch.object(daily.os, "replace", side_effect=denied) as replace, \
                 patch.object(daily.time, "sleep") as wait:
                with self.assertRaises(PermissionError):
                    daily.save_registry({"items": [{"pd_no": "102", "status": "create_reserved"}]})
                self.assertEqual(replace.call_count, 5)
                self.assertEqual(wait.call_count, 4)
            self.assertEqual(daily.REGISTRY.read_bytes(), original)
            self.assertEqual(list(daily.REGISTRY.parent.glob(".shopify_daily_*")), [])
            # Other permission failures do not receive a broad retry/bypass.
            with patch.object(daily.os, "replace", side_effect=PermissionError("not a Windows lock")) as replace, \
                 patch.object(daily.time, "sleep") as wait:
                with self.assertRaises(PermissionError):
                    daily.save_registry({"items": []})
                replace.assert_called_once()
                wait.assert_not_called()
            self.assertEqual(daily.REGISTRY.read_bytes(), original)

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
                     patch.object(daily, "fetch_makeup_ranking", return_value=[]) as ranking, \
                     patch.dict(os.environ, {"FORCE": "1", "SHOPIFY_STORE": "", "SHOPIFY_ADMIN_TOKEN": "", "SHOPIFY_CLIENT_SECRET": ""}):
                    self.assertEqual(daily.main(), 0)
                    # 2026-10-16: 메이크업만 S 가 없을 때 실시간 랭킹을 본다(테스트는 네트워크 없이 빈 랭킹).
                    ranking.assert_called_once()
                    # 스킨케어는 오늘 이미 등록 -> 조회 없음. 메이크업·바디는 S/A 후보를 조회하지만 없으면 건너뛴다.
                    self.assertTrue(all(c.args[0] not in {r["pd_no"] for r in daily.s_ranked(daily.CATEGORIES[0])}
                                        for c in lookup.call_args_list))
                result = json.loads(Path("out/daiso_daily_beauty_result.json").read_text(encoding="utf-8"))
                self.assertEqual(result["results"][0]["status"], "skipped_already_today")
                self.assertEqual(result["results"][0]["s_candidates"], len(daily.s_ranked(daily.CATEGORIES[0])))
                # 2026-10-11 카테고리 전담팀: 메이크업·바디도 S 후보가 생길 수 있다. 조회가 막히면 '적격 S 없음'.
                expected = ["skipped_no_eligible_s_or_ranking" if daily.ranking_enabled(cat)
                            else "skipped_no_eligible_s_grade" if daily.s_ranked(cat) else "skipped_no_s_grade"
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

    def test_banner_backfill_preserves_draft_active_and_human_text_without_calls(self):
        products = [{"id": "registered", "tags": [], "status": "ACTIVE",
                     "descriptionHtml": "<p>Human-reviewed active description.</p>"},
                    {"id": "tagged", "tags": ["daiso-pd-77"], "status": "DRAFT",
                     "descriptionHtml": "<p>Human-reviewed draft FAQ.</p>"},
                    {"id": "unrelated", "tags": ["other"], "status": "DRAFT",
                     "descriptionHtml": "<p>Unrelated human text.</p>"}]
        original = copy.deepcopy(products)
        shop = MagicMock()
        registry = {"items": [{"shopify_id": "registered"}]}
        for publication in ("pub", None):
            result = daily.backfill_banner(shop, products, registry, publication)
            self.assertEqual([x["shopify_id"] for x in result], ["registered", "tagged"])
            self.assertTrue(all(x["status"] == "skipped_automatic_banner_disabled" for x in result))
            self.assertEqual(products, original)
        self.assertEqual(shop.mock_calls, [])

    def test_banner_backfill_does_not_remove_existing_human_description(self):
        body = "<p><strong>한국여성들이 즐겨찾는 제품</strong></p><p>Owner text.</p>"
        products = [{"id": "p", "tags": ["daiso-daily"], "descriptionHtml": body}]
        shop = MagicMock()
        daily.backfill_banner(shop, products, {"items": []}, None)
        self.assertEqual(products[0]["descriptionHtml"], body)
        self.assertEqual(shop.mock_calls, [])

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
                    return [{"shopify_id": "p", "status": "skipped_automatic_banner_disabled"}]
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

    def test_old_enabled_banner_flag_preserves_existing_bodies_in_main(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            cwd = os.getcwd()
            os.chdir(folder)
            try:
                shop = MagicMock()
                products = [{"id": "draft", "tags": ["daiso-daily"], "status": "DRAFT",
                             "descriptionHtml": "<p>Human-reviewed draft FAQ.</p>"},
                            {"id": "active", "tags": ["daiso-daily"], "status": "ACTIVE",
                             "descriptionHtml": "<p>Human-reviewed active description.</p>"}]
                original = copy.deepcopy(products)
                shop.existing_products.return_value = products
                shop.online_store_publication.return_value = "pub"
                registry = {"items": [{"date": "2026-10-10", "category": c[0]} for c in daily.CATEGORIES]}
                with patch.object(daily, "DRY_RUN", False), patch.object(daily, "BACKFILL_BANNER", True), \
                     patch.object(daily, "Shopify", return_value=shop), \
                     patch.object(daily, "load_registry", return_value=registry), \
                     patch.object(daily, "BACKFILL_DRAFT_IMAGES", False), \
                     patch.object(daily, "QUARANTINE_BLOCKED_PUBLIC", False), \
                     patch.object(daily, "kst_today", return_value="2026-10-10"), \
                     patch.dict(os.environ, {"SHOPIFY_STORE": "test.myshopify.com", "SHOPIFY_ADMIN_TOKEN": "test"}):
                    self.assertEqual(daily.main(), 0)
                self.assertEqual(products, original)
                shop.update_description.assert_not_called()
                shop.set_status.assert_not_called()
                shop.publish.assert_not_called()
                result = json.loads(Path("out/daiso_daily_beauty_result.json").read_text(encoding="utf-8"))
                self.assertEqual(len(result["banner_backfill"]), 2)
                self.assertTrue(all(r["status"] == "skipped_automatic_banner_disabled"
                                    for r in result["banner_backfill"]))
                self.assertTrue(all(r["status"] == "skipped_already_today" for r in result["results"]))
            finally:
                os.chdir(cwd)

    def test_gallery_uncertainty_blocks_later_daily_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            cwd = os.getcwd()
            os.chdir(folder)
            try:
                shop = MagicMock()
                shop.existing_products.return_value = []
                shop.online_store_publication.return_value = "pub"
                with patch.object(daily, "DRY_RUN", False), patch.object(daily, "ONLY", set()), \
                        patch.object(daily, "BACKFILL_BANNER", False), \
                        patch.object(daily, "BACKFILL_DRAFT_IMAGES", True), \
                        patch.object(daily, "QUARANTINE_BLOCKED_PUBLIC", False), \
                        patch.object(daily, "Shopify", return_value=shop), \
                        patch.object(daily, "load_registry", return_value={"items": []}), \
                        patch.object(daily, "s_ranked") as ranked, \
                        patch.object(daily, "backfill_draft_images", return_value=[{"status": "verification_pending", "stop_further_writes": True}]), \
                        patch.dict(os.environ, {"SHOPIFY_STORE": "test.myshopify.com", "SHOPIFY_ADMIN_TOKEN": "test"}):
                    daily.main()
                ranked.assert_not_called()
                shop.create.assert_not_called()
                shop.set_status.assert_not_called()
                shop.publish.assert_not_called()
                result = json.loads(Path("out/daiso_daily_beauty_result.json").read_text())
                self.assertTrue(all(r["status"] == "skipped_prior_write_uncertain" for r in result["results"]))
            finally:
                os.chdir(cwd)

    def test_reserved_gallery_blocks_creation_even_when_backfill_is_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            cwd = os.getcwd()
            os.chdir(folder)
            try:
                shop = MagicMock()
                shop.existing_products.return_value = []
                registry = {"items": [{"status": "ACTIVE", "image_backfill": {"state": "append_reserved"}}]}
                with patch.object(daily, "DRY_RUN", False), patch.object(daily, "ONLY", set()), \
                        patch.object(daily, "BACKFILL_BANNER", False), \
                        patch.object(daily, "BACKFILL_DRAFT_IMAGES", False), \
                        patch.object(daily, "QUARANTINE_BLOCKED_PUBLIC", True), \
                        patch.object(daily, "Shopify", return_value=shop), \
                        patch.object(daily, "load_registry", return_value=registry), \
                        patch.object(daily, "quarantine_blocked_public") as quarantine, \
                        patch.object(daily, "s_ranked") as ranked, \
                        patch.dict(os.environ, {"SHOPIFY_STORE": "test.myshopify.com", "SHOPIFY_ADMIN_TOKEN": "test"}):
                    daily.main()
                ranked.assert_not_called()
                quarantine.assert_not_called()
                shop.create.assert_not_called()
                shop.gql.assert_not_called()
            finally:
                os.chdir(cwd)

    def test_workflow_tests_before_write_and_retains_registry_recovery(self):
        workflow = (SCRIPT.parents[1]/".github/workflows/daiso-daily-beauty-shopify.yml").read_text(encoding="utf-8")
        test_command = "('tests', 'test_daiso_daily_beauty_to_shopify.py')"
        write_command = "run: python scripts/daiso_daily_beauty_to_shopify.py"
        self.assertLess(workflow.index(test_command), workflow.index(write_command))
        self.assertLess(workflow.index('loader.discover(folder, pattern=pattern, top_level_dir=folder)'), workflow.index(write_command))
        self.assertIn('if not result.wasSuccessful():', workflow)
        self.assertIn('raise SystemExit(1)', workflow)
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
        # 2026-10-18 사업주: 원가+배송+카드수수료 기준 최소 마진 30% 아래로 팔지 않는다 -> 하한가로 올린다.
        self.assertEqual(pr["single"]["price_usd"], 11.99)
        self.assertTrue(pr["single"]["margin_floor_applied"])
        self.assertGreaterEqual(pr["single"]["margin_pct"], 30)
        self.assertGreaterEqual(pr["pack"]["margin_pct"], 30)
        self.assertTrue(pr["evidence"]["ok"])
        self.assertEqual(pr["evidence"]["source"], "shop_com_live_comparable")
        self.assertGreater(pr["single"]["net_profit_usd"], 0)
        self.assertNotIn("single:price_at_or_below_breakeven", pr["profit_warnings"])
        self.assertFalse(any("margin_below_minimum" in w for w in pr["profit_warnings"]))
        self.assertIn("최소 마진 하한", pr["basis"])
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

    def test_final_prices_use_cost_based_draft_without_valid_market_evidence(self):
        none = {"lowest_usd": None, "matches": []}
        for label, evidence in (("none", None), ("stale", self._serp_evidence(days_old=90)),
                                ("small", self._serp_evidence(n=2)), ("volume", self._serp_evidence(query="Test Serum 100 ml")),
                                ("future", self._serp_evidence(days_old=-30))):
            with self.subTest(case=label):
                pr = self._final(none, 18.99, evidence)
                self.assertGreater(pr["single"]["price_usd"], 0)
                self.assertTrue(pr["draft_only"])
                self.assertFalse(pr["evidence"]["ok"])
                self.assertIsNone(daily.price_unfit_reason(3000, pr))
                tampered = copy.deepcopy(pr)
                tampered["single"]["price_usd"] = 0.01
                self.assertIsNotNone(daily.price_unfit_reason(3000, tampered))
        unknown = self._final({"lowest_usd": 6.5, "match_count": 1, "matches": [{"title": "Test Serum", "usd": 6.5}]},
                              None, None, name="테스트 세럼", title="Test Serum")
        self.assertTrue(unknown["draft_only"])
        self.assertGreater(unknown["single"]["price_usd"], 0)
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

    def test_detail_localization_is_off_by_default_and_review_only_when_on(self):
        # Conversion success is preparation only; existing reviewed image paths remain separate.
        product = {"pdNo": "88", "pdImgUrl": "/x.jpg", "pdImgUrlList": ["/x.jpg"]}
        empty_policy = {"reviewed_product_only_allowlist": {}}
        self.assertFalse(daily.LOCALIZE_DETAIL_IMAGES)       # 환경변수 없이는 켜지지 않는다
        with patch.object(daily, "IMAGE_POLICY", empty_policy):
            off = daily.prepare_images(product, None, title="Cream")
        self.assertIsNone(off["localization"])
        ok = {"status": "ok", "summary": {"used": 2}, "reasons": [], "translator": "stub",
              "_files": ["/tmp/01-a-en.jpg", "/tmp/02-b-en.jpg"], "_alts": ["Cream — A", "Cream — B"],
              "_resource_urls": []}
        with patch.object(daily, "IMAGE_POLICY", empty_policy), patch.object(daily, "localized_images", return_value=ok):
            on = daily.prepare_images(product, None, title="Cream")
        self.assertEqual(on["source_urls"], [])
        self.assertEqual(on["alts"], [])
        self.assertFalse(on["localization"]["upload_allowed"])
        self.assertIn("detail_localization_requires_gallery_review", [d["reason"] for d in on["skipped"]])
        self.assertEqual(on["localization"]["manifest"], "data/image_localization/88.json")
        failed = {"status": "failed", "reasons": ["translator_unavailable"], "summary": None}
        with patch.object(daily, "IMAGE_POLICY", empty_policy), patch.object(daily, "localized_images", return_value=failed):
            fb = daily.prepare_images(product, None, title="Cream")
        self.assertEqual(fb["source_urls"], [])
        self.assertIn("detail_localization_failed:translator_unavailable", [d["reason"] for d in fb["skipped"]])

    def test_localizer_conversion_never_reads_or_uploads_output_files(self):
        product = {"pdNo": "88"}
        for forged in (False, True):
            converted = {"status": "ok", "product_id": "88", "summary": {"used": 1}, "reasons": [],
                         "gallery_status": "prepared" if forged else "review_required",
                         "gallery_complete": forged, "preparation_complete": forged,
                         "outputs": [{"file": "missing-or-corrupt.jpg", "sha256": "a" * 64}],
                         "_files": ["/missing.jpg"], "_alts": ["unreviewed claim"],
                         "_resource_urls": ["https://unverified.invalid/asset.jpg"], "_output_sha256s": ["a" * 64]}
            original = copy.deepcopy(converted)
            localizer, shop = MagicMock(), MagicMock()
            localizer.localize_product.return_value = converted
            with patch.dict(sys.modules, {"localize_detail_images": localizer}), \
                 patch.object(daily, "LOCALIZE_DETAIL_IMAGES", True), patch.object(daily, "DRY_RUN", False), \
                 patch.object(Path, "read_bytes", side_effect=AssertionError("converter bytes must not be read for upload")):
                result = daily.localized_images(product, shop, "Cream")
            self.assertEqual(converted, original)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["gallery_status"], "review_required")
            self.assertFalse(result["gallery_complete"])
            self.assertFalse(result["upload_allowed"])
            for key in ("_files", "_alts", "_resource_urls", "_output_sha256s"):
                self.assertNotIn(key, result)
            shop.upload_jpeg.assert_not_called()
            shop.upload_product_image.assert_not_called()
            shop.gql.assert_not_called()
            localizer.write_manifest.assert_called_once_with(result)

    def test_converter_prepared_and_internal_urls_never_merge(self):
        product = {"pdNo": "88", "pdImgUrl": "/x.jpg", "pdImgUrlList": ["/x.jpg"]}
        converted = {"status": "ok", "gallery_status": "prepared", "gallery_complete": True,
                     "preparation_complete": True, "upload_allowed": True,
                     "_files": ["/not-reviewed.jpg"], "_resource_urls": ["https://unverified.invalid/asset.jpg"],
                     "_alts": ["Never cakes"], "_output_sha256s": ["a" * 64]}
        shop = MagicMock()
        with patch.object(daily, "IMAGE_POLICY", {"reviewed_product_only_allowlist": {}}), \
             patch.object(daily, "localized_images", return_value=converted), patch.object(daily, "DRY_RUN", False):
            result = daily.prepare_images(product, shop, title="Cream")
        for key in ("source_urls", "resource_urls", "alts", "output_sha256s"):
            self.assertEqual(result[key], [])
        self.assertEqual(result["localization"]["status"], "ok")
        self.assertFalse(result["localization"]["upload_allowed"])
        self.assertIn("detail_localization_requires_gallery_review", [x["reason"] for x in result["skipped"]])
        shop.upload_jpeg.assert_not_called()
        shop.upload_product_image.assert_not_called()
        shop.gql.assert_not_called()

    def test_review_only_localization_preserves_existing_allowlist_upload(self):
        import hashlib
        import io
        import daiso_images
        source, output = b"reviewed source fixture", b"converted reviewed allowlist fixture"
        policy = {"reviewed_product_only_allowlist": {"88": [{"path": "/x.jpg",
                    "sha256": hashlib.sha256(source).hexdigest(), "reviewed_by": "synthetic review",
                    "reviewed_at": "2026-10-20"}]}}
        product = {"pdNo": "88", "pdImgUrl": "/x.jpg", "pdImgUrlList": ["/x.jpg"]}
        converted = {"status": "ok", "gallery_status": "review_required", "gallery_complete": False,
                     "_resource_urls": ["https://unverified.invalid/asset.jpg"], "_files": ["/bad.jpg"], "_alts": ["bad"]}
        shop = MagicMock(); shop.upload_jpeg.return_value = "https://fixture.invalid/reviewed.jpg"
        with patch.object(daily, "IMAGE_POLICY", policy), patch.object(daily, "DRY_RUN", False), \
             patch.object(daily, "localized_images", return_value=converted), \
             patch.object(daily.urllib.request, "urlopen", return_value=io.BytesIO(source)), \
             patch.object(daiso_images, "select_images", side_effect=lambda blobs: (blobs, [])) as selected, \
             patch.object(daiso_images, "to_square_jpeg", return_value=output):
            result = daily.prepare_images(product, shop, title="Reviewed Cream")
        selected.assert_called_once_with([(daily.DAISO_CDN + "/x.jpg", source)])
        shop.upload_jpeg.assert_called_once_with(output, "daiso-88-1.jpg")
        shop.upload_product_image.assert_not_called()
        self.assertEqual(result["source_urls"], [daily.DAISO_CDN + "/x.jpg"])
        self.assertEqual(result["resource_urls"], ["https://fixture.invalid/reviewed.jpg"])
        self.assertEqual(result["alts"], ["Reviewed Cream"])
        self.assertEqual(result["output_sha256s"], [hashlib.sha256(output).hexdigest()])
        self.assertFalse(result["gallery_complete"])

    def test_localizer_disabled_or_dry_run_never_writes_manifest_or_uploads(self):
        localizer, shop = MagicMock(), MagicMock()
        localizer.localize_product.return_value = {"status": "ok", "outputs": [], "reasons": []}
        with patch.dict(sys.modules, {"localize_detail_images": localizer}), \
             patch.object(daily, "LOCALIZE_DETAIL_IMAGES", False):
            self.assertIsNone(daily.localized_images({"pdNo": "88"}, shop, "Cream"))
        localizer.localize_product.assert_not_called()
        with patch.dict(sys.modules, {"localize_detail_images": localizer}), \
             patch.object(daily, "LOCALIZE_DETAIL_IMAGES", True), patch.object(daily, "DRY_RUN", True):
            self.assertEqual(daily.localized_images({"pdNo": "88"}, shop, "Cream")["status"], "ok")
        localizer.write_manifest.assert_not_called()
        shop.upload_jpeg.assert_not_called()
        shop.upload_product_image.assert_not_called()

    def test_localizer_failure_stays_failure_without_upload(self):
        localizer, shop = MagicMock(), MagicMock()
        localizer.localize_product.side_effect = RuntimeError("synthetic failure")
        with patch.dict(sys.modules, {"localize_detail_images": localizer}), \
             patch.object(daily, "LOCALIZE_DETAIL_IMAGES", True), patch.object(daily, "DRY_RUN", False):
            result = daily.localized_images({"pdNo": "88"}, shop, "Cream")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reasons"], ["localize_exception:RuntimeError"])
        localizer.write_manifest.assert_not_called()
        shop.upload_jpeg.assert_not_called()
        shop.upload_product_image.assert_not_called()

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
                if relative == "_synthetic_receipt_pd_no":
                    continue
                target = root/"data/manual"/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(document), encoding="utf-8")
            if safety_files is not None and safety_files.get("_synthetic_receipt_pd_no"):
                receipt = synthetic_receipt(root, safety_files["_synthetic_receipt_pd_no"])
                (root/"data/manual/manufacturer_safety_evidence.private.json").write_text(
                    json.dumps({"schema_version": 1, "records": [receipt]}), encoding="utf-8")
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

    def test_current_s_evidence_expiry_immediately_before_create_blocks_write(self):
        expired = {"eligible": False, "reasons": ["product_observation_stale"]}
        with patch.object(daily.current_s_eligibility, "assess_current", return_value={"123": expired}):
            _, result, registry, shop = self._run_main(self._ok_pricing(), lambda candidate: [candidate])
        self.assertEqual(result["results"][0]["status"], "skipped_current_s_evidence_expired")
        self.assertEqual(result["results"][0]["current_s_eligibility"], expired)
        self.assertEqual(registry["items"], [])
        shop.create.assert_not_called()
        shop.set_status.assert_not_called()
        shop.publish.assert_not_called()

    def test_loss_making_but_evidenced_s_product_registers_with_warning(self):
        warnings = ["single:price_at_or_below_breakeven", "pack:margin_below_target:-25.0%<40.0%"]
        pricing = {"single": {"price_usd": 9.99, "margin_pct": -20.0, "net_profit_usd": -2.0},
                   "pack": {"ok": True, "price_usd": 16.99, "margin_pct": -25.0, "net_profit_usd": -4.0, "compare_at_usd": 19.98},
                   "basis": "test", "shop_compare": {}, "evidence": dict(EVIDENCE_OK), "profit_warnings": warnings}
        code, result, registry, shop = self._run_main(pricing, lambda candidate: [candidate])
        self.assertEqual(code, 0)
        record = result["results"][0]
        self.assertEqual(record["status"], "created_draft")  # Margins remain advisory; owner activates.
        self.assertEqual(record["draft_reasons"], [daily.product_accuracy.HOLD_REASON])
        self.assertEqual(record["profitability_warnings"], warnings)
        self.assertEqual(registry["items"][0]["status"], "DRAFT")
        self.assertEqual(registry["items"][0]["profitability_warnings"], warnings)
        shop.set_status.assert_not_called()
        shop.publish.assert_not_called()
        self.assertFalse(record["product_accuracy"]["publication_allowed"])

    def test_final_copy_review_binds_actual_label_quantity_and_stays_draft(self):
        evidence = {"status": "RECORDED_SOURCE_BOUND", "reasons": [], "statements": [],
                    "facts": {"product_name": "Bonsep Serum", "net_contents": "100 ml"}}
        with patch.object(daily.product_accuracy, "source_evidence", return_value=evidence):
            code, result, registry, shop = self._run_main(self._ok_pricing(), lambda candidate: [candidate])
        self.assertEqual(code, 0)
        record = result["results"][0]
        review = record["product_accuracy"]
        self.assertEqual(review["source_conflicts"], ["net_contents"])
        self.assertEqual(review["input_copy_review"]["source_conflicts"], [])
        self.assertEqual(review["selected_copy_sha256"], daily.product_accuracy._copy_digest(
            {"title": "Bonsep Serum 30 ml", "description_html": "<p>Serum.</p>"}))
        self.assertEqual(review["excluded_sections"], ["us_label", "retailer_source_marker"])
        self.assertEqual(record["status"], "created_draft")
        shop.set_status.assert_not_called()
        shop.publish.assert_not_called()

    def test_scraped_label_values_cannot_inject_markup_after_copy_review(self):
        resolver = MagicMock()
        resolver.to_inci.return_value = ("Water", [], [], [])
        with tempfile.TemporaryDirectory() as folder, patch.object(daily, "ROOT", Path(folder)), \
             patch.object(daily, "_inci_resolver", return_value=(resolver, None)):
            label = daily.build_us_label("123", "Serum 30 ml", {
                "ingredients": "Water", "maker": '<img src="x" onerror="alert(1)">',
                "origin": "한국", "volume": "30 ml"})
        self.assertNotIn("<img", label["html"])
        self.assertIn("&lt;img", label["html"])

    # ------------------------------------------------------------------
    # 제조사 안전성 기록 게이트 (안전 게이트, 마진과 무관)
    # ------------------------------------------------------------------
    def test_owner_approved_missing_safety_creates_only_nonpublic_draft(self):
        pricing = {"single": {"price_usd": 14.99, "margin_pct": 30},
                   "pack": {"ok": True, "price_usd": 25.99, "margin_pct": 30,
                            "compare_at_usd": 29.98}, "basis": "test", "shop_compare": {},
                   "evidence": dict(EVIDENCE_OK)}
        files = {"mocra_business.json": {"safety_substantiation": {"covered_pd_nos": []}},
                 "owner_draft_approvals.json": decision_document()}
        code, result, registry, shop = self._run_main(
            pricing, lambda candidate: [candidate], safety_files=files)
        self.assertEqual(code, 0)
        row = result["results"][0]
        self.assertEqual(row["status"], "created_draft")
        self.assertTrue(row["owner_approved_nonpublic_draft"])
        self.assertFalse(row["safety_record"]["covered"])
        self.assertIn("safety_evidence_unverified_owner_draft_only", row["draft_reasons"])
        self.assertEqual(registry["items"][0]["status"], "DRAFT")
        self.assertEqual(shop.create.call_args.args[0]["status"], "DRAFT")
        shop.set_status.assert_not_called()
        shop.publish.assert_not_called()
        shop.publish_channels.assert_not_called()

    def test_owner_draft_approval_revoked_before_create_blocks_write(self):
        pricing = {"single": {"price_usd": 14.99, "margin_pct": 30},
                   "pack": {"ok": True, "price_usd": 25.99, "margin_pct": 30,
                            "compare_at_usd": 29.98}, "basis": "test", "shop_compare": {},
                   "evidence": dict(EVIDENCE_OK)}
        missing = {"covered": False, "reason": "manufacturer_safety_record_missing:test"}
        with patch.object(daily, "owner_approved_draft", side_effect=[True, False]):
            code, result, registry, shop = self._run_main(
                pricing, lambda candidate: [candidate], safety=lambda pd: dict(missing))
        self.assertEqual(code, 0)
        self.assertEqual(result["results"][0]["status"], "blocked_manufacturer_safety_record_missing")
        self.assertEqual(registry["items"], [])
        shop.create.assert_not_called()
        shop.publish.assert_not_called()

    def test_owner_draft_approval_never_recreates_owner_deleted_identity(self):
        with patch.object(daily, "owner_approved_draft", return_value=True):
            self.assertTrue(daily.already_registered(
                {"pdNo": "1049275", "pdNm": "Deleted owner product"},
                {"items": [{"pd_no": "1049275", "status": "deleted_by_owner"}]}, set(), set()))

    def _profile_root(self, folder, public=None, private=None, labels=None, synthetic_pd_no=None):
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
        if synthetic_pd_no is not None:
            receipt = synthetic_receipt(root, synthetic_pd_no)
            profile_path = manual/("mocra_profile.json" if private is not None else "mocra_business.json")
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["safety_substantiation"]["evidence_records"] = [receipt]
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
        return root

    def test_safety_record_requires_this_pd_no_in_covered_list_per_product(self):
        reason = "manufacturer_safety_record_missing:scoped_evidence_missing"
        public = {"safety_substantiation": {"covered_pd_nos": ["1067498"], "note": "n"}}
        with tempfile.TemporaryDirectory() as folder, patch.object(daily, "ROOT", self._profile_root(folder, public, synthetic_pd_no="1067498")):
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
        with tempfile.TemporaryDirectory() as folder, patch.object(daily, "ROOT", self._profile_root(folder, public, private, synthetic_pd_no="2")):
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
        covered = {"mocra_business.json": {"safety_substantiation": {"covered_pd_nos": ["123"]}}, "_synthetic_receipt_pd_no": "123"}
        code, result, registry, shop = self._run_main(self._ok_pricing(), lambda c: [c], safety_files=covered)
        self.assertEqual(code, 0)
        self.assertEqual(result["results"][0]["status"], "created_draft")
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
        covered = {"mocra_business.json": {"safety_substantiation": {"covered_pd_nos": ["123"]}}, "_synthetic_receipt_pd_no": "123"}
        code, result, registry, shop = self._run_main(
            self._ok_pricing(), lambda c: [{**c, "pdNo": "999", "pdNm": "다른 세럼 30 ml"}, c], safety_files=covered)
        self.assertEqual(code, 0)
        record = result["results"][0]
        self.assertEqual(record["status"], "created_draft")
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
        # 최저가가 마진 하한보다 낮으면 하한가로 올리고 '최저가보다 저렴' 주장을 하지 않는다.
        self.assertEqual(verified["evidence"]["detail"]["price_claim"], "margin_floor_price_above_evidence")
        roomy = self._final({"lowest_usd": 30.0, "match_count": 3, "matches": [{"title": "Test Serum 50 ml", "usd": 30.0}]})
        self.assertEqual(roomy["evidence"]["detail"]["price_claim"], "undercuts_lowest_verified_same_item_comparator")
        self.assertFalse(roomy["single"]["margin_floor_applied"])
        self.assertLess(roomy["single"]["price_usd"], 30.0)
        self.assertEqual(daily.bundle_variant_name(10.0, 17.0), "2-Pack (Save 15%)")
        self.assertEqual(daily.bundle_variant_name(14.99, 25.99), "2-Pack (Save 13%)")
        self.assertEqual(daily.bundle_variant_name(10.0, 19.99), "2-Pack")
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
    def _priority_root(self, folder, market_hours=1.0, config=True, market=True, own_hours=1.0, synthetic_checkout=False):
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
        if synthetic_checkout:
            # Complete arithmetic fixtures only. HTTPS and JSON fields never
            # authenticate these quotes in the production normalization path.
            def quote(item_id, price, shipping, hours):
                return {"item_id": item_id, "item_price_usd": price, "shipping_usd": shipping,
                        "tax_usd": 0, "mandatory_fees_usd": 0, "currency": "USD", "market": "US",
                        "quantity": 1, "shipping_method": "standard", "destination_key": "us_synthetic",
                        "observed_at": stamp(hours) if hours is not None else None,
                        "source_url": "https://example.com/synthetic-quote"}
            registry_path = data/"shopify_daily_registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            for entry in registry["items"]:
                entry["checkout_quote"] = quote(entry["pd_no"], entry["single_usd"], 3.0, own_hours)
            write("shopify_daily_registry.json", registry)
            if market:
                market_path = data/"oliveyoung_us_products.json"
                market_doc = json.loads(market_path.read_text(encoding="utf-8"))
                for entry in market_doc["products"]:
                    entry["checkout_quote"] = quote(entry["product_id"], entry["price_usd"],
                                                    entry["shipping_usd"], market_hours)
                write("oliveyoung_us_products.json", market_doc)
        if config is True:
            (root/"config").mkdir()
            (root/"config/daiso_commerce_strategy.json").write_text(
                (SCRIPT.parents[1]/"config/daiso_commerce_strategy.json").read_text(encoding="utf-8"), encoding="utf-8")
        elif isinstance(config, str):
            (root/"config").mkdir()
            (root/"config/daiso_commerce_strategy.json").write_text(config, encoding="utf-8")
        return root

    @contextmanager
    def _synthetic_checkout_trust(self):
        # Algorithm branch fixture, scoped only to the two positive tests.
        # There is no trusted producer in production. The unpatched ingress
        # regression below proves raw quotes cannot grant themselves trust.
        import build_beauty_price_strategy as bps
        original = bps.checkout_total_evidence

        def trusted_synthetic_record(*args, **kwargs):
            result = original(*args, **kwargs)
            result["source_verified"] = result["known"]
            result["source_reasons"] = [] if result["known"] else ["checkout_source_provenance_unverified"]
            return result

        with patch.object(bps, "checkout_total_evidence", side_effect=trusted_synthetic_record):
            yield

    def _ranked(self, root, shipping="3.0"):
        import os
        env = {"OWN_SHIPPING_USD": shipping} if shipping is not None else {}
        with patch.object(daily, "ROOT", root), patch.dict(os.environ, env):
            if shipping is None:
                os.environ.pop("OWN_SHIPPING_USD", None)
            return daily.s_ranked(daily.CATEGORIES[0])

    def test_verified_price_advantage_ranks_s_first_with_transparent_components(self):
        with tempfile.TemporaryDirectory() as folder, self._synthetic_checkout_trust():
            rows = self._ranked(self._priority_root(folder, synthetic_checkout=True))
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
        with tempfile.TemporaryDirectory() as folder, self._synthetic_checkout_trust():
            root = self._priority_root(folder, synthetic_checkout=True)
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

    def test_priority_production_ingress_never_trusts_https_or_self_reported_quotes(self):
        import build_beauty_price_strategy as bps
        for claims in ({}, {"source_verified": True, "known": True, "verified": True,
                           "reviewed": True, "status": "approved", "evidence_sha256": "a" * 64}):
            with self.subTest(claims=claims), tempfile.TemporaryDirectory() as folder:
                root = self._priority_root(folder, synthetic_checkout=True)
                for rel, rows_key in (("shopify_daily_registry.json", "items"),
                                      ("oliveyoung_us_products.json", "products")):
                    path = root/"data"/rel
                    doc = json.loads(path.read_text(encoding="utf-8"))
                    for entry in doc[rows_key]:
                        entry["checkout_quote"].update(claims)
                    path.write_text(json.dumps(doc), encoding="utf-8")
                before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                # No trust patch: exercise the real registrar -> strategy path.
                rows = self._ranked(root)
                self.assertEqual([row["pd_no"] for row in rows], ["S1", "S2"])
                for row in rows:
                    self.assertEqual(row["grade"], "S")
                    self.assertFalse(row["_priority"]["price_position_verified"])
                    self.assertEqual(row["_priority"]["components"]["verified_price_points"], 0)
                docs, statuses = bps.load_inputs(root/"data")
                report = bps.build_strategy(docs, statuses, datetime.now(timezone.utc), own_shipping_usd=3.0)
                for item in report["products"]:
                    self.assertFalse(item["price_position"]["verified"])
                    self.assertEqual(item["priority"]["components"]["verified_price_points"], 0)
                    if item["pd_no"] in ("S2", "A1"):
                        own = item["own_price"]["checkout_evidence"]
                        self.assertTrue(own["known"])
                        self.assertFalse(own["source_verified"])
                        self.assertIn("checkout_source_provenance_unverified", own["source_reasons"])
                        self.assertEqual(item["market"]["tier_counts"]["qualified"], 0)
                        self.assertGreater(item["market"]["tier_counts"]["provisional"], 0)
                        market = item["market"]["provisional_lowest"]["checkout_evidence"]
                        self.assertTrue(market["known"])
                        self.assertFalse(market["source_verified"])
                        self.assertIn("checkout_source_provenance_unverified", market["source_reasons"])
                self.assertEqual(before, {p.relative_to(root): p.read_bytes()
                                          for p in root.rglob("*") if p.is_file()})

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

    def test_new_draft_does_not_reinsert_unsupported_popularity_banner(self):
        code, result, registry, shop = self._run_main(self._ok_pricing(), lambda c: [c])
        self.assertEqual(code, 0)
        created = shop.create.call_args.args[0]
        self.assertNotIn("한국여성들이 즐겨찾는 제품", created["description_html"])
        self.assertTrue(created["description_html"].startswith("<p>Serum.</p>"))
        self.assertEqual(result["results"][0]["status"], "created_draft")
        shop.set_status.assert_not_called()
        shop.publish.assert_not_called()


class BodyCategoryFallbackIntegrationTests(unittest.TestCase):
    """Real pick/queue/reservation logic; isolated files and mocked network."""

    def setUp(self):
        # Optional-path fixtures must opt in explicitly. No shipped config is changed.
        policy = copy.deepcopy(daily.STRATEGY)
        policy["grade_policy"][daily.BODY_RESEARCH_DRAFT_OPT_IN] = True
        guard = patch.object(daily.pricing_model, "load_commerce_strategy", return_value=policy)
        guard.start()
        self.addCleanup(guard.stop)

    def test_absent_false_or_nonboolean_policy_denies_even_with_approval(self):
        # The deployment may explicitly opt in. Missing/invalid policy must still
        # fail closed independently of the current production business choice.
        absent = copy.deepcopy(daily.STRATEGY)
        absent["grade_policy"].pop(daily.BODY_RESEARCH_DRAFT_OPT_IN, None)
        policies = [absent]
        for value in (False, None, "true", 1):
            policy = copy.deepcopy(absent)
            policy["grade_policy"][daily.BODY_RESEARCH_DRAFT_OPT_IN] = value
            policies.append(policy)
        for policy in policies:
            with self.subTest(policy=policy["grade_policy"]), patch.object(
                    daily.pricing_model, "load_commerce_strategy", return_value=policy):
                _, row, registry, shop = self.run_body(approved=True)
                self.assertEqual(row["fallback_reason"], "body_category_research_draft_policy_not_enabled")
                self.assertEqual(registry, {"items": []})
                shop.create.assert_not_called()

    def test_policy_read_failure_denies_category_permission(self):
        with patch.object(daily.pricing_model, "load_commerce_strategy", side_effect=ValueError("invalid")), \
             patch.object(daily.owner_draft_approval, "category_approved", return_value=True):
            self.assertFalse(daily.body_category_draft_approved())

    def test_mixed_source_creates_only_numeric_draft_with_original_index(self):
        _, row, registry, shop = self.run_body(ids=("PD20261016001", "9001", "P100002", "9002"))
        self.assertEqual(row["daiso_pdNo"], "9001")
        self.assertEqual(row["selection_provenance"]["source_index"], 1)
        audit = row["selection_provenance"]["unsupported_listing_products"]
        self.assertEqual([r["pd_no"] for r in audit], ["PD20261016001", "P100002"])
        self.assertEqual(registry[daily.body_fallback.QUEUE_KEY]["ordered_pd_nos"], ["9001", "9002"])
        self.assertEqual(shop.create.call_args.args[0]["status"], "DRAFT")
        shop.publish.assert_not_called()

    def run_body(self, s_rows=None, ids=("9001", "9002"), registry=None, approved=True,
                 source_change=None, detail_change=None, price_block=(), safety_block=(),
                 dry=False, uncertain=False, revoke=False, invalidate=False, category="body",
                 shop_products=None, gosi_data=None, revoke_policy=False):
        import os
        import copy
        bf = daily.body_fallback
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"data/daiso_real").mkdir(parents=True)
            source = {"code": bf.CATEGORY_CODE, "url": bf.SOURCE_URL,
                      "fetch_status": "ok", "complete": True,
                      "fetched_at": datetime.now(timezone.utc).isoformat(),
                      "listing_products": [{"pd_no": pd, "name": "Body " + pd,
                                            "small_category_code": bf.CATEGORY_CODE,
                                            "url": daily.DAISO_ITEM + pd} for pd in ids]}
            if source_change:
                source_change(source)
            catalog = root/"data/daiso_real/desk_catalog.json"
            def write_catalog():
                catalog.write_text(json.dumps({"desks": {"body": {"categories": [source]}}}), encoding="utf-8")
            write_catalog()
            reg = copy.deepcopy(registry if registry is not None else {"items": []})
            registry_file = root/"registry.json"
            registry_file.write_text(json.dumps(reg), encoding="utf-8")
            approval = {"value": approved}
            shop = MagicMock()
            shop.store = "test.myshopify.com"
            shop.existing_products.return_value = shop_products or []
            shop.exists.return_value = False
            shop.online_store_publication.return_value = "pub"
            shop.publish_channels.return_value = {}
            last = [None]
            def lookup(pd):
                last[0] = str(pd)
                p = {"pdNo": str(pd), "pdNm": "Body " + str(pd), "brndNm": "도브",
                     "pdPrc": "3000", "soldOutYn": "N", "exhYn": "Y", "onlStckQy": 2,
                     "pdImgUrl": "/body.jpg", "_current_detail_available": True}
                return detail_change(p) if detail_change else p
            pricing = {"single": {"price_usd": 14.99, "margin_pct": 30},
                       "pack": {"ok": True, "price_usd": 25.99, "margin_pct": 30,
                                "compare_at_usd": 29.98}, "basis": "test", "shop_compare": {},
                       "evidence": dict(EVIDENCE_OK)}
            def images(p, unused_shop, title=None):  # 2026-10-17 prepare_images(..., title=) 시그니처
                if revoke_policy:
                    daily.pricing_model.load_commerce_strategy.return_value["grade_policy"][daily.BODY_RESEARCH_DRAFT_OPT_IN] = False
                if revoke:
                    approval["value"] = False
                if invalidate:
                    source["listing_products"] = []
                    write_catalog()
                return {"source_urls": ["source"], "resource_urls": ["resource"], "skipped": []}
            def create(item, callback):
                if uncertain:
                    raise TimeoutError("unknown create outcome")
                prod = {"id": "gid://shopify/Product/9001", "handle": "body"}
                callback(prod)
                return prod
            shop.create.side_effect = create
            cwd = os.getcwd()
            os.chdir(root)
            try:
                with ExitStack() as stack:
                    for name, value in {"ROOT": root, "REGISTRY": registry_file, "DRY_RUN": dry,
                                        "ONLY": {category}, "BACKFILL_BANNER": False,
                                        "QUARANTINE_BLOCKED_PUBLIC": False}.items():
                        stack.enter_context(patch.object(daily, name, value))
                    stack.enter_context(patch.dict(os.environ, {"SHOPIFY_STORE": "test.myshopify.com",
                        "SHOPIFY_ADMIN_TOKEN": "test", "GITHUB_STEP_SUMMARY": ""}))
                    stack.enter_context(patch.object(daily, "Shopify", return_value=shop))
                    stack.enter_context(patch.object(daily, "s_ranked", return_value=s_rows or []))
                    # 메이크업 실시간 랭킹 대체(2026-10-16)는 테스트에서 네트워크를 타지 않게 빈 랭킹으로 막는다.
                    stack.enter_context(patch.object(daily, "fetch_makeup_ranking", return_value=[]))
                    stack.enter_context(patch.object(daily.owner_draft_approval, "category_approved",
                                                    side_effect=lambda *args: approval["value"]))
                    stack.enter_context(patch.object(daily, "owner_approved_draft", return_value=False))
                    stack.enter_context(patch.object(daily, "daiso_lookup", side_effect=lookup))
                    stack.enter_context(patch.object(daily, "manufacturer_safety_record", side_effect=lambda pd:
                        {"covered": str(pd) not in safety_block, "reason": "missing" if str(pd) in safety_block else None}))
                    gemini = stack.enter_context(patch.object(daily, "gemini_copy", return_value=None))
                    stack.enter_context(patch.object(daily, "fallback_copy", side_effect=lambda p, cat: ("Dove " + p["pdNo"], "<p>Body.</p>")))
                    stack.enter_context(patch.object(daily, "jarvis_price", return_value={"price_usd": 14.99}))
                    stack.enter_context(patch.object(daily, "final_prices", return_value=pricing))
                    real_reason = daily.price_unfit_reason
                    stack.enter_context(patch.object(daily, "price_unfit_reason", side_effect=lambda krw, pr:
                        "test_price_missing" if last[0] in price_block else real_reason(krw, pr)))
                    gosi = stack.enter_context(patch.object(daily, "collect_gosi", return_value=(
                        gosi_data if gosi_data is not None else {"gosi_ok": True, "missing": [], "ingredients": "INCI"})))
                    stack.enter_context(patch.object(daily, "build_us_label", return_value={"html": "<p>Label.</p>", "reasons": [], "label": {}}))
                    stack.enter_context(patch.object(daily, "canonical_public_gate", return_value={"public_ready": True, "reasons": []}))
                    stack.enter_context(patch.object(daily, "prepare_images", side_effect=images))
                    stack.enter_context(patch.object(daily, "log_price_position"))
                    stack.enter_context(patch.object(daily, "verify_product", return_value={
                        "variants": {"nodes": [{}, {}]}, "media": {"nodes": [{}]},
                        "status": "DRAFT", "publishedOnPublication": False}))
                    stack.enter_context(patch.object(daily, "log"))
                    code = daily.main()
                    self.assertTrue(all(call.args[0].get("_source") != bf.SELECTION_SOURCE
                                        for call in gemini.call_args_list))
                    if shop.create.called:
                        selected_fallback = "draft-only-category-fallback" in shop.create.call_args.args[0]["tags"]
                        if selected_fallback:
                            self.assertEqual(gosi.call_args.kwargs, {"allow_ai": False})
                        else:
                            self.assertEqual(gosi.call_args.kwargs, {})
                    if not s_rows:
                        gemini.assert_not_called()
                    elif shop.create.called and "jarvis-grade-s" in shop.create.call_args.args[0]["tags"]:
                        gemini.assert_called()
                result = json.loads((root/"out/daiso_daily_beauty_result.json").read_text(encoding="utf-8"))
                saved = json.loads(registry_file.read_text(encoding="utf-8"))
                return code, result["results"][0], saved, shop
            finally:
                os.chdir(cwd)

    def test_s_first_does_not_prepare_fallback_queue(self):
        _, row, reg, shop = self.run_body(s_rows=[{"pd_no": "8001", "grade": "S"}])
        self.assertEqual(row["daiso_pdNo"], "8001")
        self.assertEqual(row["grade"], "S")
        self.assertNotIn(daily.body_fallback.QUEUE_KEY, reg)
        self.assertEqual(row["s_candidates"], 1)

    def test_no_s_forced_draft_even_safety_and_public_gates_covered(self):
        _, row, reg, shop = self.run_body()
        self.assertEqual(row["status"], "created_draft", row)
        self.assertEqual(row["grade"], "-")
        self.assertEqual(row["selection_source"], daily.body_fallback.SELECTION_SOURCE)
        self.assertEqual(row["selection_provenance"]["source_index"], 0)
        self.assertEqual(row["selection_provenance"]["category_code"], daily.body_fallback.CATEGORY_CODE)
        self.assertIn("owner_category_fallback_draft_only", row["draft_reasons"])
        self.assertIn(daily.body_fallback.QUEUE_KEY, reg)
        self.assertEqual(shop.create.call_args.args[0]["status"], "DRAFT")
        self.assertNotIn("jarvis-grade-s", shop.create.call_args.args[0]["tags"])
        shop.set_status.assert_not_called()
        shop.publish.assert_not_called()
        shop.publish_channels.assert_not_called()

    def test_exhausted_s_stock_duplicates_price_and_safety_use_fallback(self):
        rows = [{"pd_no": str(i), "grade": "S"} for i in range(8001, 8005)]
        def change(p):
            if p["pdNo"] == "8001":
                p["soldOutYn"] = "Y"
            return p
        _, row, _, _ = self.run_body(s_rows=rows, detail_change=change,
            price_block=("8003",), safety_block=("8004",),
            registry={"items": [{"pd_no": "8002", "name_kr": "previous", "status": "deleted_by_owner"}]})
        self.assertEqual(row["daiso_pdNo"], "9001")
        self.assertEqual(row["s_candidates"], 4)

    def test_one_per_kst_day_cap(self):
        _, row, reg, shop = self.run_body(registry={"items": [
            {"pd_no": "7001", "category": "body", "date": daily.kst_today(), "status": "DRAFT"}]})
        self.assertEqual(row["status"], "skipped_already_today")
        shop.create.assert_not_called()
        self.assertNotIn(daily.body_fallback.QUEUE_KEY, reg)

    def test_missing_or_nonboolean_category_approval_fail_closed(self):
        for approved in (False, "true", 1, None):
            with self.subTest(approved=approved):
                _, row, reg, shop = self.run_body(approved=approved)
                self.assertIn("approval_missing_or_revoked", row["fallback_reason"])
                self.assertEqual(reg, {"items": []})
                shop.create.assert_not_called()

    def test_revoked_policy_before_reservation_has_no_write_or_queue_advance(self):
        _, row, registry, shop = self.run_body(revoke_policy=True)
        self.assertEqual(row["status"], "skipped_body_category_fallback_invalidated")
        self.assertEqual(registry, {"items": []})
        shop.create.assert_not_called()

    def test_revoked_approval_before_reservation_has_no_write_or_queue_advance(self):
        _, row, reg, shop = self.run_body(revoke=True)
        self.assertEqual(row["status"], "skipped_body_category_fallback_invalidated")
        self.assertEqual(reg, {"items": []})
        shop.create.assert_not_called()

    def test_source_invalidated_before_reservation_has_no_write(self):
        _, row, reg, shop = self.run_body(invalidate=True)
        self.assertEqual(row["fallback_reason"], "body_category_source_membership_missing")
        self.assertEqual(reg, {"items": []})
        shop.create.assert_not_called()

    def test_stale_wrong_and_partial_source_fail_closed(self):
        mutations = [lambda s: s.update(fetched_at=(datetime.now(timezone.utc)-timedelta(hours=25)).isoformat()),
                     lambda s: s.update(url="https://example.com/wrong"),
                     lambda s: s.update(complete=False),
                     lambda s: s["listing_products"][0].update(small_category_code="wrong")]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                _, row, reg, shop = self.run_body(source_change=mutation)
                self.assertTrue(row["fallback_reason"])
                self.assertEqual(reg, {"items": []})
                shop.create.assert_not_called()

    def test_current_detail_unavailable_never_uses_source_price_or_stock(self):
        for change in (lambda p: None, lambda p: dict(p, _current_detail_available=False),
                       lambda p: dict(p, pdPrc="0"), lambda p: dict(p, onlStckQy=0)):
            with self.subTest(change=change):
                _, row, reg, shop = self.run_body(detail_change=change)
                self.assertEqual(row["fallback_reason"], "no_eligible_body_category_fallback")
                self.assertEqual(reg, {"items": []})
                shop.create.assert_not_called()

    def test_deleted_and_shopify_duplicate_identity_are_skipped(self):
        _, row, _, _ = self.run_body(ids=("1049275", "9001", "9002"),
            shop_products=[{"title": "Existing", "tags": ["daiso-pd-9001"], "variants": {"nodes": []}}])
        self.assertEqual(row["daiso_pdNo"], "9002")
        _, row, _, _ = self.run_body(registry={"items": [
            {"pd_no": "9001", "name_kr": "Body 9002", "status": "deleted_by_owner"}]})
        self.assertEqual(row["fallback_reason"], "no_eligible_body_category_fallback")

    def test_dry_run_does_not_write_queue(self):
        _, row, reg, shop = self.run_body(dry=True)
        self.assertEqual(row["status"], "dry_run")
        self.assertEqual(reg, {"items": []})
        shop.create.assert_not_called()

    def test_scope_only_bypasses_safety_for_nonpublic_fallback(self):
        _, row, _, shop = self.run_body(safety_block=("9001",))
        self.assertEqual(row["status"], "created_draft")
        self.assertFalse(row["safety_record"]["covered"])
        self.assertIn("safety_evidence_unverified_owner_draft_only", row["draft_reasons"])
        shop.publish.assert_not_called()

    def test_no_fallback_for_skincare_or_makeup(self):
        # 바디 카테고리 대체는 바디만. 메이크업은 2026-10-16 사업주 지시로 실시간 랭킹 대체(비공개 초안)가 따로 있다.
        # 여기서는 랭킹이 비어 있으니 아무것도 만들지 않아야 한다.
        expected = {"skincare": "skipped_no_s_grade", "makeup": "skipped_no_eligible_s_or_ranking"}
        for category, status in expected.items():
            _, row, reg, shop = self.run_body(category=category)
            self.assertEqual(row["status"], status)
            self.assertNotIn("fallback_reason", row)
            self.assertEqual(reg, {"items": []})
            shop.create.assert_not_called()

    def test_fallback_missing_gosi_remains_a_draft_hold(self):
        _, row, _, shop = self.run_body(gosi_data={"gosi_ok": False, "missing": ["ingredients", "maker", "origin"]})
        self.assertEqual(row["status"], "created_draft", row)
        self.assertIn("gosi_missing:ingredients,maker,origin", row["draft_reasons"])
        shop.set_status.assert_not_called()
        shop.publish.assert_not_called()

    def test_gosi_ai_disabled_with_key_preserves_cache_api_and_makes_no_gemini_request(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"data").mkdir()
            (root/"data/gosi.json").write_text(json.dumps({"items": {"9001": {"ingredients": "Cached INCI"}}}), encoding="utf-8")
            with patch.object(daily, "ROOT", root), \
                 patch.dict(os.environ, {"GEMINI_API_KEY": "offline-test-key"}), \
                 patch.object(daily, "http_json", return_value=(200, {"data": [
                     {"ntfcIemCd": "1", "ntfcIemCn": "30 ml"}]})) as requests, \
                 patch.object(daily, "detail_image_urls") as detail_images, \
                 patch.object(daily, "vision_read") as vision, \
                 patch.object(daily.urllib.request, "urlopen") as direct_requests:
                gosi = daily.collect_gosi("9001", allow_ai=False)
            self.assertEqual(gosi["ingredients"], "Cached INCI")
            self.assertEqual(gosi["volume"], "30 ml")
            self.assertFalse(gosi["gosi_ok"])
            self.assertEqual(gosi["missing"], ["maker", "origin"])
            self.assertEqual(requests.call_count, 1)
            self.assertTrue(all(call.args[0].startswith("https://fapi.daisomall.co.kr/")
                                for call in requests.call_args_list))
            self.assertFalse(any("generativelanguage" in call.args[0] for call in requests.call_args_list))
            detail_images.assert_not_called()
            vision.assert_not_called()
            direct_requests.assert_not_called()

    def test_rendered_alt_fills_only_missing_gosi_fields_without_ai(self):
        # 2026-10-17 1042249: gosi.json 밖 후보는 고시가 늘 비었다. alt 원문으로 빈칸만 채운다.
        import os
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"data").mkdir()
            (root/"data/gosi.json").write_text(json.dumps({"items": {"9001": {"volume": "30 ml"}}}), encoding="utf-8")
            alt = {"volume": "99 ml", "maker": "지본코스메틱"}
            with patch.object(daily, "ROOT", root), patch.object(daily, "GOSI_RENDERED_ALT", True), \
                 patch.dict(os.environ, {"GEMINI_API_KEY": ""}), \
                 patch.object(daily, "gosi_from_api", return_value={"origin": "한국"}), \
                 patch.object(daily, "gosi_from_rendered_alt", return_value=alt) as rendered, \
                 patch.object(daily, "vision_read") as vision:
                gosi = daily.collect_gosi("9001", allow_ai=False)
            rendered.assert_called_once_with("9001")
            vision.assert_not_called()
            self.assertEqual(gosi["volume"], "30 ml")            # 정본 값은 덮지 않는다
            self.assertEqual(gosi["maker"], "지본코스메틱")
            self.assertEqual(gosi["missing"], ["ingredients"])   # alt 에 없는 전성분은 지어내지 않는다
            with patch.object(daily, "ROOT", root), patch.object(daily, "GOSI_RENDERED_ALT", False), \
                 patch.object(daily, "gosi_from_api", return_value={}), \
                 patch.object(daily, "gosi_from_rendered_alt") as off:
                daily.collect_gosi("9001", allow_ai=False)
            off.assert_not_called()

    def test_gosi_default_keeps_canonical_ai_extraction_behavior(self):
        import os
        with tempfile.TemporaryDirectory() as folder, patch.object(daily, "ROOT", Path(folder)), \
             patch.dict(os.environ, {"GEMINI_API_KEY": "offline-test-key"}), \
             patch.object(daily, "gosi_from_api", return_value={}), \
             patch.object(daily, "detail_image_urls", return_value=["image"]) as images, \
             patch.object(daily, "vision_read", return_value={
                 "ingredients": "INCI", "volume": "30 ml", "maker": "Maker", "origin": "Korea"}) as vision:
            gosi = daily.collect_gosi("9001")
        self.assertTrue(gosi["gosi_ok"])
        images.assert_called_once_with("9001")
        vision.assert_called_once()

    def test_non_quantity_is_missing_across_cached_api_alt_and_vision_sources(self):
        import os
        facts = {"ingredients": "정제수", "maker": "Fixture Manufacturer", "origin": "한국"}
        for source in ("cache", "api", "alt", "vision"):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root / "data").mkdir()
                retained = dict(facts, **({"volume": "의 스틱형"} if source == "cache" else {}))
                (root / "data/gosi.json").write_text(json.dumps({"items": {"1076498": retained}}))
                with patch.object(daily, "ROOT", root), \
                     patch.object(daily, "GOSI_RENDERED_ALT", source == "alt"), \
                     patch.dict(os.environ, {"GEMINI_API_KEY": "offline-test-key" if source == "vision" else ""}), \
                     patch.object(daily, "gosi_from_api", return_value={"volume": "의 스틱형"} if source == "api" else {}), \
                     patch.object(daily, "gosi_from_rendered_alt", return_value={"volume": "의 스틱형"}), \
                     patch("daiso_notice_recovery.rendered_notice", return_value={"fields": {}, "images": []}), \
                     patch("daiso_notice_recovery.ocr_notice", return_value={}), \
                     patch.object(daily, "detail_image_urls", return_value=["fixture"]), \
                     patch.object(daily, "vision_read", return_value={"volume": "의 스틱형"}), \
                     patch.object(daily.time, "sleep"):
                    gosi = daily.collect_gosi("1076498", allow_ai=source == "vision")
                self.assertFalse(gosi["gosi_ok"])
                self.assertEqual(gosi["missing"], ["volume"])
                self.assertNotIn("volume", gosi)
                self.assertEqual(gosi["maker"], facts["maker"])

    def test_label_does_not_render_invalid_quantity_or_infer_it_from_title(self):
        for raw in ("의 스틱형", "", "0 g", "30"):
            with self.subTest(raw=raw):
                label = daily.build_us_label("1076498", "Fixture lip balm 99g", {
                    "ingredients": "정제수", "volume": raw, "maker": "Fixture Manufacturer", "origin": "한국"})
                self.assertNotIn("net_contents", label["label"])
                self.assertIn("net_contents_missing_or_invalid", label["reasons"])
                self.assertIn("Source verification pending.", label["html"])
                self.assertNotIn("의 스틱형", label["html"])
                self.assertNotIn("99g", label["html"])

    def test_real_lookup_requires_positive_current_detail_not_search_defaults(self):
        hit = {"pdNo": "9001", "pdNm": "Body 9001", "pdPrc": "3000", "soldOutYn": "N",
               "ONL_STCK_QY": 10, "pdImgUrl": "/body.jpg"}
        for detail, expected in (({}, False), ({"pdPrc": 3000, "stckQy": 0}, False),
                                 ({"pdPrc": 0, "stckQy": 10}, False),
                                 ({"pdPrc": 3000, "stckQy": 10, "exhYn": "N"}, False),
                                 ({"pdPrc": 3000, "stckQy": 10}, True)):
            with self.subTest(detail=detail):
                response = MagicMock()
                response.__enter__.return_value.read.return_value = json.dumps(hit).encode()
                with patch.object(daily.urllib.request, "urlopen", return_value=response), \
                     patch.object(daily, "daiso_post", return_value={"data": detail}):
                    product = daily.daiso_lookup("9001")
                self.assertIs(product["_current_detail_available"], expected)

    def test_missing_category_source_fails_closed_without_registry_change(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(daily, "ROOT", Path(folder)), \
             patch.object(daily.owner_draft_approval, "category_approved", return_value=True):
            reg = {"items": []}
            rows, reason, queue = daily.body_fallback_rows(reg)
            self.assertEqual(rows, [])
            self.assertEqual(reason, "body_category_source_missing_or_unreadable")
            self.assertIsNone(queue)
            self.assertEqual(reg, {"items": []})

    def test_catalog_override_reads_only_explicit_repo_source_and_records_hash(self):
        import os
        bf = daily.body_fallback
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/"out/body_shower_catalog.json"
            source.parent.mkdir()
            catalog = {"desks": {"body": {"categories": [{
                "code": bf.CATEGORY_CODE, "url": bf.SOURCE_URL, "fetch_status": "ok", "complete": True,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "listing_products": [{"pd_no": "9001", "name": "Body", "url": daily.DAISO_ITEM + "9001"}]
            }]}}}
            raw = json.dumps(catalog).encode("utf-8")
            source.write_bytes(raw)
            with patch.object(daily, "ROOT", root), \
                 patch.object(daily.owner_draft_approval, "category_approved", return_value=True), \
                 patch.dict(os.environ, {"BODY_FALLBACK_CATALOG_PATH": "out/body_shower_catalog.json"}):
                reg = {"items": []}
                rows, reason, queue = daily.body_fallback_rows(reg)
                self.assertIsNone(reason)
                self.assertEqual(rows[0]["pd_no"], "9001")
                self.assertEqual(rows[0]["_priority"]["catalog_path"], "out/body_shower_catalog.json")
                self.assertEqual(rows[0]["_priority"]["catalog_sha256"], daily.hashlib.sha256(raw).hexdigest())
                self.assertIsNotNone(queue)
                self.assertEqual(reg, {"items": []})

    def test_explicit_catalog_override_invalid_or_missing_never_uses_default(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            default = root/"data/daiso_real/desk_catalog.json"
            default.parent.mkdir(parents=True)
            default.write_text("{}", encoding="utf-8")
            overrides = ("", "../outside.json", str(root/"absolute.json"), "C:relative.json", "out/missing.json")
            for override in overrides:
                with self.subTest(override=override), patch.object(daily, "ROOT", root), \
                     patch.object(daily.owner_draft_approval, "category_approved", return_value=True), \
                     patch.dict(os.environ, {"BODY_FALLBACK_CATALOG_PATH": override}):
                    rows, reason, queue = daily.body_fallback_rows({"items": []})
                    self.assertEqual(rows, [])
                    self.assertIn(reason, {"body_category_catalog_path_invalid", "body_category_source_missing_or_unreadable"})
                    self.assertIsNone(queue)

    def test_uncertain_created_id_also_blocks_future_fallback(self):
        registry = {"items": [{"pd_no": "9001", "category": "body", "date": "yesterday",
                              "status": "created_unverified", "shopify_id": "gid://shopify/Product/9001",
                              "source": daily.body_fallback.SELECTION_SOURCE}]}
        _, row, saved, shop = self.run_body(registry=registry)
        self.assertEqual(row["fallback_reason"], "uncertain_fallback_outcome")
        self.assertEqual(saved, registry)
        shop.create.assert_not_called()

    def test_uncertain_create_durably_blocks_next_day_fallback(self):
        code, row, reg, shop = self.run_body(uncertain=True)
        self.assertEqual(code, 1)
        self.assertEqual(reg["items"][0]["status"], "create_reserved")
        self.assertEqual(reg["items"][0]["source"], daily.body_fallback.SELECTION_SOURCE)
        reg["items"][0]["date"] = "yesterday"
        _, row, saved, shop = self.run_body(registry=reg)
        self.assertEqual(row["fallback_reason"], "uncertain_fallback_outcome")
        self.assertEqual(saved, reg)
        shop.create.assert_not_called()


class DraftImageBackfillTests(unittest.TestCase):
    """Gallery review includes partial drafts but cannot mutate Shopify or sources."""

    def setUp(self):
        manifest = patch.object(daily.gallery_review, "load_manifest", return_value={})
        manifest.start()
        self.addCleanup(manifest.stop)
        saved = patch.object(daily, "save_registry")
        saved.start()
        self.addCleanup(saved.stop)

    def reg(self):
        return {"items": [
            {"pd_no": "1", "status": "DRAFT", "images": 0, "title": "Original human body",
             "shopify_id": "gid://shopify/Product/1", "single_usd": 15.99,
             "draft_reasons": ["no_usable_product_images", "listing_gate_public_not_ready"]},
            {"pd_no": "2", "status": "DRAFT", "images": 2, "title": "한글 제목", "shopify_id": "gid://shopify/Product/2"},
            {"pd_no": "3", "status": "ACTIVE", "images": 3, "title": "Active", "shopify_id": "gid://shopify/Product/3"},
            {"pd_no": "4", "status": "DRAFT", "images": 3, "title": "Has images", "shopify_id": "gid://shopify/Product/4",
             "gallery_complete": True},
        ]}

    def observation(self, product_id):
        pd = product_id.rsplit("/", 1)[-1]
        return {"id": product_id, "pd_no": pd, "status": "DRAFT", "complete": True,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "media": [{"id": "gid://shopify/MediaImage/" + pd, "status": "READY", "mediaContentType": "IMAGE"}]}

    def test_rechecks_zero_two_three_image_drafts_without_automatic_upload(self):
        reg, shop = self.reg(), MagicMock()
        before = copy.deepcopy(reg)
        shop.read_gallery.side_effect = self.observation
        with patch.object(daily, "daiso_lookup") as lookup, \
                patch.object(daily, "prepare_images") as prep, \
                patch.object(daily, "save_registry") as save:
            out = daily.backfill_draft_images(shop, reg)
        self.assertEqual([r["pd_no"] for r in out], ["1", "2", "4"])
        self.assertTrue(all(r["status"] == "review_required" and not r["gallery_complete"] for r in out))
        self.assertEqual(out[1]["preserve_media_ids"], ["gid://shopify/MediaImage/2"])
        self.assertEqual(shop.read_gallery.call_count, 3)
        lookup.assert_not_called()
        prep.assert_not_called()
        save.assert_called_once()
        shop.gql.assert_not_called()
        shop.upload_jpeg.assert_not_called()
        self.assertEqual(reg["items"], before["items"])
        self.assertEqual(reg["gallery_review_cursor"], "gid://shopify/Product/4")

    def test_actual_active_status_blocks_even_if_registry_says_draft(self):
        shop, reg = MagicMock(), self.reg()
        shop.read_gallery.side_effect = lambda pid: {**self.observation(pid), "status": "ACTIVE"}
        out = daily.backfill_draft_images(shop, reg)
        self.assertTrue(all(r["add_asset_sha256s"] == [] and not r["gallery_complete"] for r in out))
        self.assertTrue(all(r["reasons"] == ["current_exact_draft_observation_required"] for r in out))
        shop.gql.assert_not_called()

    def test_read_failures_leave_registry_unchanged_and_do_not_leak_raw_errors(self):
        reg, shop = self.reg(), MagicMock()
        before = copy.deepcopy(reg)
        shop.read_gallery.side_effect = RuntimeError("private-token-and-file-path")
        with patch.object(daily, "save_registry") as save:
            out = daily.backfill_draft_images(shop, reg)
        self.assertTrue(all(r["status"] == "review_required" for r in out))
        self.assertNotIn("private-token", json.dumps(out))
        save.assert_called_once()
        self.assertEqual(reg["items"], before["items"])

    def test_read_budget_does_not_hide_remaining_review_candidates(self):
        shop = MagicMock()
        shop.read_gallery.side_effect = self.observation
        with patch.object(daily, "BACKFILL_DRAFT_IMAGES_LIMIT", 1):
            out = daily.backfill_draft_images(shop, self.reg())
        self.assertEqual(len(out), 3)
        self.assertEqual(shop.read_gallery.call_count, 1)
        self.assertEqual(out[2]["reasons"], ["current_inventory_read_deferred"])
        self.assertFalse(out[2]["gallery_complete"])

    def test_bounded_reviews_rotate_durably_instead_of_starving_later_drafts(self):
        reg, shop = self.reg(), MagicMock()
        reg["items"].append({"pd_no": "5", "status": "DRAFT", "images": 2, "shopify_id": "gid://shopify/Product/5"})
        shop.read_gallery.side_effect = self.observation
        with patch.object(daily, "BACKFILL_DRAFT_IMAGES_LIMIT", 3):
            daily.backfill_draft_images(shop, reg)
            self.assertEqual(reg["gallery_review_cursor"], "gid://shopify/Product/4")
            shop.read_gallery.reset_mock()
            daily.backfill_draft_images(shop, reg)
        self.assertEqual(shop.read_gallery.call_args_list[0].args[0], "gid://shopify/Product/5")
        self.assertEqual(shop.read_gallery.call_count, 3)

    def test_read_gallery_is_query_only_and_never_invents_content_hashes(self):
        shop = object.__new__(daily.Shopify)
        product = {"id": "gid://shopify/Product/1", "status": "DRAFT", "tags": ["daiso-pd-1"],
                   "media": {"nodes": [{"id": "m1", "status": "READY", "mediaContentType": "IMAGE"}],
                             "pageInfo": {"hasNextPage": False}}}
        shop.gql = MagicMock(return_value={"product": product})
        result = shop.read_gallery(product["id"])
        self.assertEqual(result["pd_no"], "1")
        self.assertTrue(result["complete"])
        self.assertNotIn("content_sha256", result["media"][0])
        self.assertTrue(shop.gql.call_args.args[0].startswith("query("))
        self.assertNotIn("mutation", shop.gql.call_args.args[0])

    def test_read_gallery_requires_exact_unique_product_tag_and_complete_inventory(self):
        shop = object.__new__(daily.Shopify)
        for tags in ([], ["daiso-pd-1", "daiso-pd-2"]):
            shop.gql = MagicMock(return_value={"product": {
                "id": "gid://shopify/Product/1", "status": "DRAFT", "tags": tags,
                "media": {"nodes": [], "pageInfo": {"hasNextPage": True}}}})
            result = shop.read_gallery("gid://shopify/Product/1")
            self.assertIsNone(result["pd_no"])
            self.assertFalse(result["complete"])

    def test_slow_media_download_cannot_refresh_old_product_observation_time(self):
        shop = object.__new__(daily.Shopify)
        shop.gql = MagicMock(return_value={"product": {"id": "gid://shopify/Product/1", "status": "DRAFT",
            "tags": ["daiso-pd-1"], "media": {"nodes": [], "pageInfo": {"hasNextPage": False}}}})
        first = datetime.now(timezone.utc) - timedelta(minutes=10)
        with patch.object(daily, "datetime") as clock:
            clock.now.side_effect = [first, datetime.now(timezone.utc)]
            observed = shop.read_gallery("gid://shopify/Product/1")
        self.assertEqual(observed["observed_at"], first.isoformat())
        self.assertEqual(clock.now.call_count, 1)
        self.assertIsNotNone(daily.gallery_review.observation_error({"pd_no": "1", "shopify_id": observed["id"]}, observed))

    def test_missing_media_pagination_cannot_be_complete(self):
        shop = object.__new__(daily.Shopify)
        shop.gql = MagicMock(return_value={"product": {"id": "gid://shopify/Product/1", "status": "DRAFT",
                                                      "tags": ["daiso-pd-1"], "media": {"nodes": []}}})
        self.assertFalse(shop.read_gallery("gid://shopify/Product/1")["complete"])


class GalleryRepairExecutionTests(unittest.TestCase):
    """All upload/mutation/network operations mocked; state races are synthetic."""

    def setUp(self):
        fixture_spec = importlib.util.spec_from_file_location(
            "gallery_review_fixture", SCRIPT.parents[1] / "tests/test_gallery_review.py")
        fixture_module = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(fixture_module)
        self.fixture = fixture_module.GalleryReviewTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        for asset in self.fixture.manifest["assets"]:
            self.fixture.change_receipt(asset["review_receipt"], reviewed_at=datetime.now(timezone.utc).isoformat())
        for ref in self.fixture.manifest["review_evidence"].values():
            self.fixture.change_receipt(ref, reviewed_at=datetime.now(timezone.utc).isoformat())
        self.entry = {**self.fixture.entry, "title": "Human title", "description_html": "Human body", "single_usd": 15.99}
        self.registry = {"items": [self.entry]}
        self.shop = MagicMock()
        self.state = {**self.fixture.observation, "media": [self.fixture.media(0), self.fixture.media(1)]}
        self.shop.read_gallery.side_effect = self.observe
        self.shop.upload_product_image.side_effect = lambda data, name, mime: "staged-" + name
        self.shop.gql.side_effect = self.append
        self.new_hashes = [a["asset_sha256"] for a in self.fixture.manifest["assets"][2:]]
        for obj, attr, value in ((daily, "ROOT", self.fixture.root),
                                 (daily.gallery_review, "load_manifest", MagicMock(return_value=self.fixture.manifest)),
                                 (daily, "DRY_RUN", False), (daily, "save_registry", MagicMock())):
            patcher = patch.object(obj, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def observe(self, product_id):
        return {**copy.deepcopy(self.state), "observed_at": datetime.now(timezone.utc).isoformat()}

    def append(self, query, variables):
        self.assertIn("product:{id:$id}", query)
        self.assertNotIn("status:", query)
        self.assertEqual(set(variables), {"id", "media"})
        for index, digest in enumerate(self.new_hashes):
            self.state["media"].append({"id": "new%d" % index, "mediaContentType": "IMAGE", "status": "READY",
                                        "content_sha256": digest})
        return {"productUpdate": {"product": {"id": self.entry["shopify_id"], "status": "DRAFT"}, "userErrors": []}}

    def test_partial_gallery_adds_only_missing_assets_and_preserves_human_content(self):
        before = copy.deepcopy(self.entry)
        out = daily.backfill_draft_images(self.shop, self.registry)[0]
        self.assertEqual(out["status"], "attached")
        self.assertTrue(out["gallery_complete"])
        self.assertEqual(out["preserve_media_ids"], [self.fixture.media(i)["id"] for i in (0, 1)])
        self.assertEqual(self.shop.upload_product_image.call_count, 3)
        self.shop.gql.assert_called_once()
        self.assertEqual(self.entry["image_backfill"]["state"], "verified")
        for key in ("title", "description_html", "single_usd", "status"):
            self.assertEqual(self.entry[key], before[key])

    def test_complete_reviewed_gallery_is_noop_without_converter_or_upload(self):
        self.state["media"] = [self.fixture.media(i) for i in range(len(self.fixture.manifest["assets"]))]
        before = copy.deepcopy(self.state["media"])
        with patch.object(daily, "prepare_images") as prepare, \
             patch.object(daily, "localized_images") as localize:
            out = daily.backfill_draft_images(self.shop, self.registry)[0]
        self.assertEqual(out["status"], "complete")
        self.assertTrue(out["gallery_complete"])
        self.assertEqual(out["add_asset_sha256s"], [])
        self.assertEqual(self.state["media"], before)
        self.assertEqual(out["preserve_media_ids"], [m["id"] for m in before])
        prepare.assert_not_called()
        localize.assert_not_called()
        self.shop.upload_product_image.assert_not_called()
        self.shop.upload_jpeg.assert_not_called()
        self.shop.gql.assert_not_called()
        self.assertEqual(self.entry["status"], "DRAFT")

    def test_existing_safe_zero_image_path_is_retained_without_claiming_complete(self):
        self.state["media"] = []
        self.new_hashes = ["a" * 64, "b" * 64]
        self.entry["images"] = 0
        with patch.object(daily, "daiso_lookup", return_value={"pdNo": "123"}), \
                patch.object(daily, "prepare_images", return_value={"resource_urls": ["r1", "r2"], "alts": ["a1", "a2"], "output_sha256s": self.new_hashes}) as prepare:
            out = daily.backfill_draft_images(self.shop, self.registry)[0]
        prepare.assert_called_once()
        self.shop.gql.assert_called_once()
        self.assertEqual(out["status"], "attached")
        self.assertEqual(self.entry["images"], 2)
        self.assertFalse(out["gallery_complete"])
        self.assertFalse(self.entry["gallery_complete"])
        self.assertEqual(self.entry["status"], "DRAFT")

    def test_active_before_repair_performs_no_upload_or_mutation(self):
        self.state["status"] = "ACTIVE"
        with patch.object(daily, "prepare_images") as prepare:
            out = daily.backfill_draft_images(self.shop, self.registry)[0]
        prepare.assert_not_called()
        self.shop.upload_product_image.assert_not_called()
        self.shop.gql.assert_not_called()
        self.assertFalse(out["gallery_complete"])

    def test_zero_image_status_change_after_staging_prevents_attachment(self):
        self.state["media"] = []
        def prepare(*args, **kwargs):
            self.state["status"] = "ACTIVE"
            return {"resource_urls": ["r1"], "alts": []}
        with patch.object(daily, "daiso_lookup", return_value={"pdNo": "123"}), \
                patch.object(daily, "prepare_images", side_effect=prepare):
            out = daily.backfill_draft_images(self.shop, self.registry)[0]
        self.shop.gql.assert_not_called()
        self.assertEqual(out["reasons"], ["gallery_changed_before_append"])
        self.assertNotIn("image_backfill", self.entry)

    def test_partial_state_change_before_upload_aborts_all_writes(self):
        calls = 0
        def observe(pid):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.state["status"] = "ACTIVE"
            return self.observe(pid)
        self.shop.read_gallery.side_effect = observe
        out = daily.backfill_draft_images(self.shop, self.registry)[0]
        self.shop.upload_product_image.assert_not_called()
        self.shop.gql.assert_not_called()
        self.assertEqual(out["status"], "review_required")

    def test_source_revocation_during_staging_prevents_product_mutation(self):
        def upload(*args):
            (self.fixture.root / self.fixture.manifest["assets"][0]["source_file"]).unlink(missing_ok=True)
            return "staged"
        self.shop.upload_product_image.side_effect = upload
        out = daily.backfill_draft_images(self.shop, self.registry)[0]
        self.shop.gql.assert_not_called()
        self.assertFalse(out["gallery_complete"])
        self.assertEqual(out["reasons"], ["gallery_evidence_changed_before_append"])

    def test_post_write_active_or_changed_media_remains_uncertain_and_never_retries(self):
        def append(query, variables):
            result = self.append(query, variables)
            self.state["status"] = "ACTIVE"
            return result
        self.shop.gql.side_effect = append
        out = daily.backfill_draft_images(self.shop, self.registry)[0]
        self.assertEqual(out["status"], "verification_pending")
        self.assertEqual(self.entry["image_backfill"]["state"], "append_reserved")
        self.assertEqual(self.entry["images"], 2)
        self.state["status"] = "DRAFT"
        self.shop.gql.reset_mock()
        self.shop.upload_product_image.reset_mock()
        again = daily.backfill_draft_images(self.shop, self.registry)[0]
        self.shop.gql.assert_not_called()
        self.shop.upload_product_image.assert_not_called()
        self.assertEqual(again["status"], "reconciled")
        self.assertEqual(self.entry["image_backfill"]["state"], "verified")

    def test_uncertain_mutation_durably_holds_retry(self):
        self.shop.gql.side_effect = RuntimeError("private network error")
        out = daily.backfill_draft_images(self.shop, self.registry)[0]
        self.assertEqual(self.entry["image_backfill"]["state"], "append_reserved")
        self.assertFalse(out["gallery_complete"])
        self.shop.gql.reset_mock()
        daily.backfill_draft_images(self.shop, self.registry)
        self.shop.gql.assert_not_called()

    def test_uncertain_gallery_write_stops_later_gallery_items(self):
        self.registry["items"].append({**self.entry, "shopify_id": "gid://shopify/Product/456", "pd_no": "456"})
        self.shop.gql.side_effect = RuntimeError("uncertain")
        out = daily.backfill_draft_images(self.shop, self.registry)
        self.assertEqual(len(out), 2)
        self.assertTrue(out[0]["stop_further_writes"])
        self.assertTrue(out[1]["stop_further_writes"])
        self.assertNotIn("gid://shopify/Product/456", [call.args[0] for call in self.shop.read_gallery.call_args_list])
        self.assertEqual(self.shop.gql.call_count, 1)

    def test_post_write_missing_original_media_cannot_be_reconciled(self):
        def append(query, variables):
            result = self.append(query, variables)
            self.state["media"] = self.state["media"][1:]
            return result
        self.shop.gql.side_effect = append
        out = daily.backfill_draft_images(self.shop, self.registry)[0]
        self.assertEqual(out["status"], "verification_pending")
        self.assertTrue(out["stop_further_writes"])
        self.assertEqual(self.entry["images"], 2)
        self.shop.gql.reset_mock()
        again = daily.backfill_draft_images(self.shop, self.registry)[0]
        self.assertEqual(again["status"], "verification_pending")
        self.shop.gql.assert_not_called()

    def test_revocation_during_final_read_prevents_the_mutation(self):
        calls = 0
        def observe(pid):
            nonlocal calls
            calls += 1
            if calls == 4:
                (self.fixture.root / self.fixture.manifest["assets"][0]["source_file"]).unlink()
            return self.observe(pid)
        self.shop.read_gallery.side_effect = observe
        out = daily.backfill_draft_images(self.shop, self.registry)[0]
        self.shop.gql.assert_not_called()
        self.assertTrue(out["stop_further_writes"])
        self.assertEqual(out["reasons"], ["gallery_evidence_changed_before_append"])

    def test_revocation_during_reservation_save_prevents_the_mutation(self):
        def save(reg):
            (self.fixture.root / self.fixture.manifest["assets"][0]["source_file"]).unlink(missing_ok=True)
        with patch.object(daily, "save_registry", side_effect=save):
            out = daily.backfill_draft_images(self.shop, self.registry)[0]
        self.shop.gql.assert_not_called()
        self.assertTrue(out["stop_further_writes"])
        self.assertEqual(self.entry["image_backfill"]["state"], "cancelled_before_append")

    def test_post_append_evidence_revocation_stops_later_writes(self):
        def append(query, variables):
            result = self.append(query, variables)
            (self.fixture.root / self.fixture.manifest["assets"][0]["source_file"]).unlink()
            return result
        self.shop.gql.side_effect = append
        out = daily.backfill_draft_images(self.shop, self.registry)[0]
        self.assertEqual(out["status"], "attached_review_required")
        self.assertFalse(out["gallery_complete"])
        self.assertTrue(out["stop_further_writes"])
        self.assertEqual(out["assessment"]["status"], "partial")

    def test_reservation_blocks_even_outside_budget_or_with_cached_active_status(self):
        self.entry["status"] = "ACTIVE"
        self.entry["image_backfill"] = {"state": "append_reserved"}
        with patch.object(daily, "BACKFILL_DRAFT_IMAGES_LIMIT", 0):
            out = daily.backfill_draft_images(self.shop, self.registry)[0]
        self.shop.read_gallery.assert_not_called()
        self.shop.gql.assert_not_called()
        self.assertTrue(out["stop_further_writes"])
        self.assertEqual(out["status"], "verification_pending")

    def test_unknown_existing_hash_or_missing_rights_blocks_partial_repair(self):
        self.state["media"][0]["content_sha256"] = "f" * 64
        out = daily.backfill_draft_images(self.shop, self.registry)[0]
        self.shop.upload_product_image.assert_not_called()
        self.shop.gql.assert_not_called()
        self.assertEqual(out["add_asset_sha256s"], [])
        self.state["media"][0] = self.fixture.media(0)
        self.fixture.manifest["review_evidence"].pop("rights")
        out = daily.backfill_draft_images(self.shop, self.registry)[0]
        self.shop.gql.assert_not_called()
        self.assertFalse(out["gallery_complete"])

    def test_cdn_hash_reads_real_bytes_and_refuses_non_shopify_destinations(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"actual media bytes"
        with patch.object(daily.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value = response
            digest = daily.gallery_media_hash("https://cdn.shopify.com/s/files/1/photo.png?v=1")
            self.assertEqual(digest, daily.hashlib.sha256(b"actual media bytes").hexdigest())
            for url in ("https://attacker.test/a", "http://cdn.shopify.com/s/files/a", "https://cdn.shopify.com@localhost/s/files/a"):
                self.assertIsNone(daily.gallery_media_hash(url))
            self.assertEqual(opener.call_count, 1)



if __name__ == "__main__":
    unittest.main()
