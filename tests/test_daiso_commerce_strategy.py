"""Offline tests for config/daiso_commerce_strategy.json and its two consumers outside the daily script.

Covers scripts/pricing_model.py (evidence/advisory, offers) and scripts/build_listing_gate.py (price gate).
No network, no Shopify, no writes to the repository's data/ (everything runs in a temp dir).
"""
import contextlib
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_listing_gate as gate  # noqa: E402
import gate_signature  # noqa: E402
import pricing_model as pm  # noqa: E402


SYNTHETIC_COVERAGE = object()


def synthetic_safety_profile(root, base=None):
    """Real temporary files and SHA bindings; explicitly fictional, not production approval."""
    manual = Path(root) / "data/manual"
    manual.mkdir(parents=True, exist_ok=True)
    dossier = b"SYNTHETIC TEST ONLY: exact SKU 1/formula dossier, not production substantiation."
    adequacy = b"SYNTHETIC TEST ONLY: completed qualified adequacy review, not production approval."
    dossier_path = "data/manual/private-synthetic-dossier.txt"
    adequacy_path = "data/manual/private-synthetic-adequacy.txt"
    (Path(root) / dossier_path).write_bytes(dossier)
    (Path(root) / adequacy_path).write_bytes(adequacy)
    document_sha = hashlib.sha256(dossier).hexdigest()
    scope = {"scope_type": "exact_product_formula", "pd_nos": ["1"],
             "formula_id": "PRIVATE-SYNTHETIC-FORMULA-NOT-PRODUCTION"}
    record = {"document_type": "qualified_safety_dossier", "scope": scope,
              "file": dossier_path, "sha256": document_sha,
              "manual_review": {"method": "manual", "disposition": "adequate",
                  "reviewer_qualified": True, "reviewed_by": "PRIVATE-SYNTHETIC-REVIEWER",
                  "reviewed_at": "2026-01-01", "document_sha256": document_sha,
                  "scope": copy.deepcopy(scope), "adequacy_type": "product_safety_substantiation",
                  "adequacy_file": adequacy_path, "adequacy_sha256": hashlib.sha256(adequacy).hexdigest()}}
    profile = copy.deepcopy(base) if base is not None else {"safety_substantiation": {"covered_pd_nos": ["1"]}}
    profile["safety_substantiation"]["evidence_records"] = [record]
    return profile


def iso(days_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class PricingModelPolicyTests(unittest.TestCase):
    def test_strategy_file_is_valid_and_hash_is_recorded(self):
        doc = pm.load_commerce_strategy()
        self.assertEqual([c["tag"] for c in doc["categories"]], ["skincare", "makeup", "body"])
        self.assertEqual(len(doc["_sha256"]), 64)
        for pd_no, entries in doc["image_policy"]["reviewed_product_only_allowlist"].items():
            self.assertTrue(pd_no.isdigit())
            self.assertTrue(entries)
            for entry in entries:
                self.assertRegex(entry["path"], r"^/[A-Za-z0-9_\-./]+$")
                self.assertNotIn("..", entry["path"])
                self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(entry["reviewed_by"].strip())
                datetime.fromisoformat(entry["reviewed_at"])

    def test_assess_price_evidence_requires_product_level_fresh_sampled_volume_matched_evidence(self):
        base = {"source": "serpapi_google_shopping", "median_usd": 20.0, "sample_n": 10,
                "query": "Serum 50 ml", "collected_at": iso(1)}
        names = ["테스트 세럼 50 ml"]
        self.assertTrue(pm.assess_price_evidence(base, names)["ok"])
        cases = {
            "missing": (None, "price_evidence_missing"),
            "benchmark": ({**base, "source": "oliveyoung_us_benchmark"}, "price_evidence_source_not_allowed"),
            "unknown source": ({**base, "source": "guess"}, "price_evidence_source_not_allowed"),
            "price zero": ({**base, "median_usd": 0}, "price_evidence_price_invalid"),
            "price bool": ({**base, "median_usd": True}, "price_evidence_price_invalid"),
            "small sample": ({**base, "sample_n": 4}, "price_evidence_sample_too_small"),
            "no date": ({**base, "collected_at": None}, "price_evidence_collected_at_missing"),
            "bad date": ({**base, "collected_at": "yesterday"}, "price_evidence_collected_at_missing"),
            "stale": ({**base, "collected_at": iso(31)}, "price_evidence_stale"),
            "future": ({**base, "collected_at": iso(-5)}, "price_evidence_dated_in_future"),
            "volume mismatch": ({**base, "query": "Serum 100 ml"}, "price_evidence_volume_mismatch"),
            "comparison volume unknown": ({**base, "query": "Serum"}, "price_evidence_volume_unverified_comparison"),
        }
        for label, (evidence, reason) in cases.items():
            with self.subTest(case=label):
                verdict = pm.assess_price_evidence(evidence, names)
                self.assertFalse(verdict["ok"])
                self.assertTrue(any(r.startswith(reason) for r in verdict["reasons"]), verdict["reasons"])
        unknown = pm.assess_price_evidence(base, ["테스트 세럼"])
        self.assertFalse(unknown["ok"])
        self.assertIn("price_evidence_volume_unverified_product", unknown["reasons"])
        # 총량 비교: 개당 용량 x 입수
        packed = pm.assess_price_evidence({**base, "query": "Ampoule 2ml x 6"}, ["앰플 2 ml*6개입"])
        self.assertTrue(packed["ok"])
        self.assertEqual(packed["volume_status"], "match")

    def test_advisory_never_blocks_even_below_breakeven(self):
        loss = pm.profitability_advisory(5.0, 8.0, weight_estimated=True)
        self.assertEqual(loss["status"], "loss")
        self.assertIn("price_at_or_below_breakeven", loss["warnings"])
        self.assertFalse(loss["blocks_registration"])
        self.assertEqual(pm.profitability_advisory(100.0, 10.0)["status"], "ok")
        # 추정 무게는 최소 마진을 5%p 올려 경고한다 (경고일 뿐)
        thin = pm.profitability_advisory(100.0, 100 * (1 - pm.PAY_RATE - 0.33), weight_estimated=False)
        thin_est = pm.profitability_advisory(100.0, 100 * (1 - pm.PAY_RATE - 0.33), weight_estimated=True)
        self.assertFalse(any(w.startswith("margin_below_minimum") for w in thin["warnings"]))
        self.assertTrue(any(w.startswith("margin_below_minimum") for w in thin_est["warnings"]))

    def _run_model(self, serp, collected_at, price_krw=5000):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            product = {"pd_no": "1", "name": "테스트 세럼 50 ml", "bucket": "스킨케어", "shopify_score": 90, "price_krw": price_krw}
            write(tmp / "score.json", {"all_scored": [{**product, "grade": "S"}]})
            write(tmp / "srec.json", {"recommendations": [product]})
            write(tmp / "status.json", {"fx": {"usd_to_krw": 1400.0, "as_of": "2026-10-11", "source": "test"}})
            write(tmp / "oy.json", {"price_stats": {"n": 10, "min": 10.0, "p25": 12.0, "median": 15.0, "max": 30.0},
                                    "collected_at": iso(0)})
            out = tmp / "pricing.json"
            with patch.object(pm, "SCORE", tmp / "score.json"), patch.object(pm, "SREC", tmp / "srec.json"), \
                 patch.object(pm, "STATUS", tmp / "status.json"), patch.object(pm, "OLIVEYOUNG", tmp / "oy.json"), \
                 patch.object(pm, "OUT", out), patch.object(pm, "MEASURED", {}), patch.object(pm, "GOSI_VOL", {}), \
                 patch.object(pm, "SERP", serp), patch.object(pm, "SERP_COLLECTED_AT", collected_at), \
                 patch.object(pm, "ROOT", tmp), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pm.main(), 0)
            return json.loads(out.read_text(encoding="utf-8"))

    def test_offers_below_breakeven_are_not_blocked_but_carry_warnings_and_evidence(self):
        serp = {"1": {"median": 3.0, "n": 12, "query": "Test Serum 50 ml"}}
        doc = self._run_model(serp, iso(2))
        self.assertFalse(doc["pricing_policy"]["margin_hard_block"])
        for kind in ("single", "bundle"):
            offer = doc["offers_by_product"][kind][0]
            # 2026-10-18 사업주: 근거가가 적자여도 원가+배송+카드수수료 기준 최소 마진 30% 하한가로 올린다.
            self.assertGreater(offer["net_profit_usd"], 0, kind)
            self.assertGreaterEqual(offer["margin_pct"], 30, kind)
            self.assertTrue(offer["margin_floor_applied"], kind)
            self.assertEqual(offer["pricing_basis"], "margin_floor_above_evidence", kind)
            self.assertFalse(offer["register_blocked"], kind)
            self.assertEqual(offer["block_reason"], "")
            self.assertNotIn("price_at_or_below_breakeven", offer["profit_warnings"])
            self.assertEqual(offer["price_evidence"]["source"], "serpapi_google_shopping")
            self.assertEqual(offer["price_evidence"]["collected_at"], doc["pricing_policy"]["serp_collected_at"])
            self.assertTrue(offer["price_evidence"]["assessment_at_generation"]["ok"])
        single = doc["offers_by_product"]["single"][0]
        landed = single["landed_cost_total_usd"]
        self.assertIn(single["price_usd"], {pm.margin_floor_price(landed, False), pm.margin_floor_price(landed, True)})
        self.assertGreater(single["price_usd"], 2.99)  # 근거가(중앙값 3.0 x 0.95)보다 높은 하한가

    def test_margin_floor_price_meets_minimum_margin_and_estimated_buffer(self):
        for landed in (0.5, 3.21, 8.0, 14.0, 27.4):
            for estimated, minimum in ((False, 30.0), (True, 35.0)):
                price = pm.margin_floor_price(landed, estimated)
                self.assertTrue(f"{price:.2f}".endswith(".99"))
                adv = pm.profitability_advisory(price, landed, estimated)
                self.assertGreaterEqual(adv["margin_pct"], minimum, (landed, estimated))
                if price >= 2:  # the next lower .99 price would miss the floor
                    self.assertLess(pm.profitability_advisory(price - 1, landed, estimated)["margin_pct"], minimum)
        self.assertEqual(pm.apply_margin_floor(99.99, 8.0), (99.99, False))
        self.assertIsNone(pm.margin_floor_price(0))

    def test_offers_without_valid_evidence_are_cost_based_drafts(self):
        stale = self._run_model({"1": {"median": 30.0, "n": 12, "query": "Test Serum 50 ml"}}, iso(90))
        self.assertFalse(stale["offers_by_product"]["single"][0]["register_blocked"])
        self.assertTrue(stale["offers_by_product"]["single"][0]["draft_only"])
        undated = self._run_model({"1": {"median": 30.0, "n": 12, "query": "Test Serum 50 ml"}}, None)
        self.assertTrue(undated["offers_by_product"]["single"][0]["draft_only"])
        mismatch = self._run_model({"1": {"median": 30.0, "n": 12, "query": "Test Serum 100 ml"}}, iso(1))
        self.assertTrue(mismatch["offers_by_product"]["single"][0]["draft_only"])
        benchmark = self._run_model({}, iso(1))  # 상품별 근거 없음 -> 올리브영 카테고리 벤치마크만 남는다
        row = benchmark["offers_by_product"]["single"][0]
        self.assertEqual(row["market_price_source"], "oliveyoung_us_benchmark")
        self.assertFalse(row["register_blocked"])
        self.assertTrue(row["draft_only"])
        self.assertTrue(pm.is_cost_based_draft(row["price_usd"], row["landed_cost_total_usd"]))
        self.assertFalse(row["price_evidence"]["assessment_at_generation"]["ok"])


class ListingGatePriceTests(unittest.TestCase):
    # Materialize actual synthetic files/receipts in each temporary root, not owner declarations.
    COVERED = SYNTHETIC_COVERAGE

    def _gate(self, price, legal=None, safety=COVERED, private=None, verified_private=False, candidate=None):
        legal = {"status": "ok", "hard_block": False} if legal is None else legal
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            data = tmp / "data"
            files = {
                "recs": data / "daiso_real/shopify_s_recommendations.json",
                "copy": data / "shopify_listing_copy.json",
                "pricing": data / "pricing_model.json",
                "legal": data / "legal_products.json",
                "legal_full": data / "legal_full.json",
                "labels": data / "daiso_real/daiso_us_labels.json",
                "gosi": data / "gosi.json",
                "master": data / "product_master.json",
                "output": data / "listing_gate.json",
                "typesafe": data / "typesafe_advisory.json",
            }
            write(files["recs"], {"recommendations": [{"pd_no": "1", "grade": "S", "rank": 1, "name": "테스트 세럼 50 ml",
                                                       "bucket": "스킨케어", "price_krw": 5000, "shopify_score": 90,
                                                       "canonical_product_id": "CP000001"}]})
            write(files["master"], {"pd_no_to_cp": {"1": "CP000001"}})
            write(files["copy"], {"items": [{"pd_no": "1", "copy_status": "ok",
                                             "copy": candidate if candidate is not None else
                                             gate.local_copy_builder.local_copy("테스트 세럼 50 ml", {"us_label": {"net_contents": "50 ml"}})}]})
            write(files["pricing"], {"offers_by_product": {"single": [price] if price else []}})
            write(files["legal"], {"items": {"1": legal}})
            write(files["legal_full"], {"items": {"1": {"complete": True}}})
            write(files["labels"], {"1": {"gosi_ok": True, "net_contents": "50 ml", "ingredients_inci": "Water",
                                          "manufacturer": "Maker Co", "country_of_origin": "Korea"}})
            write(files["gosi"], {"items": {"1": {"ingredients": "정제수", "volume": "50 ml", "maker": "메이커", "origin": "한국"}}})
            manual = data / "manual"
            manual.mkdir(parents=True, exist_ok=True)
            if safety is SYNTHETIC_COVERAGE:
                safety = synthetic_safety_profile(tmp)
            if verified_private:
                private = synthetic_safety_profile(tmp, private)
            if safety is not None:
                (manual / "mocra_business.json").write_text(
                    safety if isinstance(safety, str) else json.dumps(safety), encoding="utf-8")
            if private is not None:
                (manual / "mocra_profile.json").write_text(
                    private if isinstance(private, str) else json.dumps(private), encoding="utf-8")
            patches = [
                patch.object(gate, "ROOT", tmp), patch.object(gate, "DATA", data),
                patch.object(gate, "RECOMMENDATIONS", files["recs"]), patch.object(gate, "COPY", files["copy"]),
                patch.object(gate, "PRICING", files["pricing"]), patch.object(gate, "LEGAL", files["legal"]),
                patch.object(gate, "LEGAL_FULL", files["legal_full"]), patch.object(gate, "LABELS", files["labels"]),
                patch.object(gate, "GOSI", files["gosi"]), patch.object(gate, "PRODUCT_MASTER", files["master"]),
                patch.object(gate, "OUTPUT", files["output"]), patch.object(gate, "TYPESAFE_STORE", files["typesafe"]),
                patch.object(gate_signature, "DATA", data), patch.object(gate_signature, "RECOMMENDATIONS", files["recs"]),
                patch.object(gate_signature, "PRICING", files["pricing"]), patch.object(gate_signature, "LEGAL", files["legal"]),
                patch.object(gate_signature, "LABELS", files["labels"]), patch.object(gate_signature, "GOSI", files["gosi"]),
                patch.object(gate_signature, "PRODUCT_MASTER", files["master"]),
                patch.object(gate.typesafe_decision_support, "evaluate", return_value={"source": "local", "mode": "local"}),
                patch.object(gate.typesafe_decision_support, "ledger", return_value={}),
            ]
            with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()):
                for p in patches:
                    stack.enter_context(p)
                self.assertEqual(gate.main(), 0)
            doc = json.loads(files["output"].read_text(encoding="utf-8"))
        return doc, doc["items"][0]

    def _offer(self, **over):
        row = {"pd_no": "1", "name": "테스트 세럼 50 ml", "qty": 1, "price_usd": 2.99, "margin_pct": -120.0,
               "net_profit_usd": -6.0, "register_blocked": False, "market_price_source": "serpapi_google_shopping",
               "price_evidence": {"source": "serpapi_google_shopping", "median_usd": 3.0, "sample_n": 12,
                                  "query": "Test Serum 50 ml", "collected_at": iso(2)}}
        row.update(over)
        return row

    def test_loss_making_but_evidenced_price_does_not_block_the_gate(self):
        doc, item = self._gate(self._offer(profit_warnings=["price_at_or_below_breakeven"]))
        self.assertNotIn("price", item["blocked_by"])
        self.assertTrue(item["ready"])
        self._assert_verified_public_record(item["manufacturer_safety_record"])
        self.assertTrue(item["price"]["price_evidence_ok"])
        self.assertEqual(item["price"]["profit_warnings"], ["price_at_or_below_breakeven"])
        self.assertFalse(item["price"]["blocks_registration"])
        self.assertFalse(doc["price_policy"]["margin_hard_block"])
        self.assertEqual(doc["price_policy"]["products_with_profit_warnings"], 1)
        self.assertFalse(item["public_ready"])
        self.assertIn(gate.product_accuracy.HOLD_REASON, item["public_blocked_by"])

    def test_saved_ok_cannot_bypass_current_copy_accuracy_review(self):
        candidate = gate.local_copy_builder.local_copy("테스트 세럼 50 ml", {"us_label": {"net_contents": "50 ml"}})
        candidate["description_html"] = "<p>Contains 5% niacinamide and guarantees results.</p>"
        _, item = self._gate(self._offer(), candidate=candidate)
        self.assertEqual(item["copy"], candidate)
        self.assertEqual(item["copy_status"], "review_required")
        self.assertIn("copy", item["blocked_by"])
        self.assertFalse(item["ready"])
        self.assertFalse(item["public_ready"])

    def test_margin_warnings_are_derived_when_the_model_did_not_provide_them(self):
        _, item = self._gate(self._offer(margin_pct=12.0, net_profit_usd=1.0))
        self._assert_verified_public_record(item["manufacturer_safety_record"])
        self.assertNotIn("price", item["blocked_by"])
        self.assertTrue(any(w.startswith("margin_below_minimum") for w in item["price"]["profit_warnings"]))
        self.assertTrue(any(w.startswith("margin_below_target") for w in item["price"]["profit_warnings"]))

    def test_real_price_problems_still_block(self):
        evidence = self._offer()["price_evidence"]
        bad_rows = {
            "no price row": None,
            "price zero": self._offer(price_usd=0),
            "register_blocked evidence flag": self._offer(register_blocked=True),
            "legacy row without evidence": {k: v for k, v in self._offer().items() if k != "price_evidence"},
            "stale evidence": self._offer(price_evidence={**evidence, "collected_at": iso(60)}),
            "undated evidence": self._offer(price_evidence={**evidence, "collected_at": None}),
            "thin sample": self._offer(price_evidence={**evidence, "sample_n": 1}),
            "volume mismatch": self._offer(price_evidence={**evidence, "query": "Test Serum 100 ml"}),
            "category benchmark": self._offer(price_evidence={**evidence, "source": "oliveyoung_us_benchmark"}),
        }
        for label, row in bad_rows.items():
            with self.subTest(case=label):
                _, item = self._gate(row)
                self.assertIn("price", item["blocked_by"])
                self.assertFalse(item["ready"])

    def test_cost_based_price_allows_draft_but_never_publication(self):
        offer = self._offer(price_usd=pm.cost_based_draft_price(10),
                            landed_cost_total_usd=10, draft_only=True, price_evidence=None)
        _, item = self._gate(offer)
        self.assertTrue(item["ready"])
        self.assertFalse(item["public_ready"])
        self.assertIn("market_price_review", item["public_blocked_by"])
        _, invalid = self._gate({**offer, "price_usd": 0.01})
        self.assertIn("price", invalid["blocked_by"])

    def test_legal_hard_block_still_blocks_when_price_is_fine(self):
        _, item = self._gate(self._offer(), legal={"status": "blocked", "hard_block": True, "hard_block_reason": "x"})
        self.assertNotIn("price", item["blocked_by"])
        self.assertIn("legal", item["blocked_by"])
        self.assertFalse(item["ready"])


    # ------------------------------------------------------------------
    # 제조사 안전성 기록: listing gate 가 daily 등록기와 같은 함수를 상품마다 부른다
    # ------------------------------------------------------------------
    def _assert_verified_public_record(self, record):
        self.assertTrue(record["covered"])
        self.assertIsNone(record["reason"])
        self.assertEqual(set(record), {"covered", "reason", "evidence_digest"})
        self.assertRegex(record["evidence_digest"], r"^[0-9a-f]{64}$")
        public = json.dumps(record)
        for secret in ("PRIVATE-SYNTHETIC-REVIEWER", "PRIVATE-SYNTHETIC-FORMULA",
                       "private-synthetic-dossier.txt", "private-synthetic-adequacy.txt"):
            self.assertNotIn(secret, public)

    def _assert_safety_blocked(self, item):
        reason = "manufacturer_safety_record_missing"
        self.assertIn(reason, item["blocked_by"])
        self.assertIn(reason, item["agent_blocked_by"])
        self.assertIn(reason, item["public_blocked_by"])
        self.assertFalse(item["ready"])
        self.assertFalse(item["agent_ready"])
        self.assertFalse(item["public_ready"])
        self.assertFalse(item["manufacturer_safety_record"]["covered"])
        self.assertTrue(item["manufacturer_safety_record"]["reason"].startswith(reason + ":"))

    def test_confirmed_coverage_passes_this_check_and_margin_alone_never_blocks(self):
        doc, item = self._gate(self._offer())
        reason = "manufacturer_safety_record_missing"
        self.assertNotIn(reason, item["blocked_by"] + item["agent_blocked_by"] + item["public_blocked_by"])
        self._assert_verified_public_record(item["manufacturer_safety_record"])
        self.assertEqual(doc["counts"]["manufacturer_safety_record"], 1)
        self.assertNotIn("manufacturer_safety_record", doc["blockers"])

    def test_missing_wrong_product_unreadable_or_false_coverage_cannot_pass(self):
        cases = {
            "no profile at all": dict(safety=None),
            "empty covered list": dict(safety={"safety_substantiation": {"covered_pd_nos": []}}),
            "another product only": dict(safety={"safety_substantiation": {"covered_pd_nos": ["2", "10"]}}),
            "deferred plan note only": dict(safety={"safety_substantiation": {"covered_pd_nos": [],
                                                                             "note": "obtain documents after first sale"}}),
            "unreadable public profile": dict(safety="{broken"),
            "profile not an object": dict(safety="[1]"),
            "unreadable private profile": dict(safety=self.COVERED, private="{broken"),
            "substantiation false": dict(safety={"safety_substantiation": False}),
            "covered list false": dict(safety={"safety_substantiation": {"covered_pd_nos": False}}),
            "covered list string": dict(safety={"safety_substantiation": {"covered_pd_nos": "1"}}),
            "false-like entries": dict(safety={"safety_substantiation": {"covered_pd_nos": [False, None, "", "  ", 0]}}),
            "private overlay replaces coverage": dict(safety=self.COVERED, private={"safety_substantiation": {"covered_pd_nos": []}}),
        }
        for label, kwargs in cases.items():
            with self.subTest(case=label):
                doc, item = self._gate(self._offer(), **kwargs)
                self._assert_safety_blocked(item)
                self.assertEqual((doc["public_ready"], doc["ready"], doc["agent_ready"]), (0, 0, 0))
                self.assertEqual(doc["blockers"]["manufacturer_safety_record"], 1)

    def test_private_overlay_can_cover_and_its_values_never_reach_the_gate_file(self):
        secret = "PRIVATE-VALUE-DO-NOT-LEAK"
        private = {"owner_contact": secret, "safety_substantiation": {"covered_pd_nos": ["1"], "note": secret}}
        doc, item = self._gate(self._offer(), safety={"safety_substantiation": {"covered_pd_nos": []}},
                               private=private, verified_private=True)
        self._assert_verified_public_record(item["manufacturer_safety_record"])
        public_doc = json.dumps(doc, ensure_ascii=False)
        for private_value in (secret, "PRIVATE-SYNTHETIC-REVIEWER", "PRIVATE-SYNTHETIC-FORMULA",
                              "data/manual/private-synthetic-dossier.txt", "data/manual/private-synthetic-adequacy.txt"):
            self.assertNotIn(private_value, public_doc)
        blocked_doc, blocked = self._gate(self._offer(), safety=None, private={"owner_contact": secret})
        self.assertEqual(sorted(blocked["manufacturer_safety_record"]), ["covered", "reason"])  # 여부와 사유 코드뿐
        self.assertNotIn(secret, json.dumps(blocked_doc, ensure_ascii=False))

    def test_owner_declared_verified_lists_and_future_promises_are_not_evidence(self):
        declaration = {"safety_substantiation": {"covered_pd_nos": ["1"], "status": "검증완료",
            "verified_by": "사업주", "basis": "판매 발생 시 사업주가 실제 자료를 확보해 보관한다"}}
        for kwargs in ({"safety": declaration},
                       {"safety": {"safety_substantiation": {"covered_pd_nos": []}}, "private": declaration}):
            with self.subTest(source="private" if "private" in kwargs else "public"):
                doc, item = self._gate(self._offer(), **kwargs)
                self._assert_safety_blocked(item)
                self.assertIn("scoped_evidence_missing", item["manufacturer_safety_record"]["reason"])
                self.assertEqual(doc["counts"]["manufacturer_safety_record"], 0)

    def test_gate_and_daily_use_the_same_helper_with_the_same_answer(self):
        import importlib.util
        import manufacturer_safety
        spec = importlib.util.spec_from_file_location("daily_for_safety", ROOT / "scripts/daiso_daily_beauty_to_shopify.py")
        daily = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(daily)
        self.assertIs(daily.manufacturer_safety, manufacturer_safety)
        self.assertIs(gate.manufacturer_safety, manufacturer_safety)
        profiles = {"covered": self.COVERED, "other product": {"safety_substantiation": {"covered_pd_nos": ["2"]}},
                    "unreadable": "{broken", "malformed": {"safety_substantiation": {"covered_pd_nos": False}}, "absent": None}
        for label, profile in profiles.items():
            with self.subTest(profile=label), tempfile.TemporaryDirectory() as folder:
                manual = Path(folder) / "data/manual"
                manual.mkdir(parents=True)
                local_profile = synthetic_safety_profile(folder) if profile is SYNTHETIC_COVERAGE else profile
                if local_profile is not None:
                    (manual / "mocra_business.json").write_text(
                        local_profile if isinstance(local_profile, str) else json.dumps(local_profile), encoding="utf-8")
                shared = manufacturer_safety.public_view(manufacturer_safety.manufacturer_safety_record("1", folder))
                with patch.object(daily, "ROOT", Path(folder)):
                    wrapper = manufacturer_safety.public_view(daily.manufacturer_safety_record("1"))
                self.assertEqual(wrapper, shared)
                _, item = self._gate(self._offer(), safety=profile)
                self.assertEqual(item["manufacturer_safety_record"], shared)


if __name__ == "__main__":
    unittest.main()
