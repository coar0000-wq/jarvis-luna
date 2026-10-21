#!/usr/bin/env python3
"""Deterministic offline tests. Run:
python -B -m unittest discover -s scripts -p test_beauty_price_strategy.py -v
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_beauty_price_strategy as bps

NOW = datetime(2026, 10, 11, 2, 0, tzinfo=timezone.utc)


def ago(hours):
    return (NOW - timedelta(hours=hours)).isoformat()


def score_row(pd, name, bucket="스킨케어", grade="A", score=80, **extra):
    row = {"pd_no": pd, "name": name, "bucket": bucket, "grade": grade, "shopify_score": score, "price_krw": 5000,
           "s_rule": "strong_form" if grade == "S" else "score_below_82",
           "best_global_match": {"channel": "x", "similarity": 0.7, "matched_tokens": ["serum"]},
           "score_breakdown": {"penalty": 0}, "canonical_product_id": "CP" + pd}
    row.update(extra)
    return row


def oy_doc(products, hours=1.0):
    return {"collected_at": ago(hours), "is_stale": False, "products": products}


def checkout_quote(item_id, price, ship, **extra):
    """Synthetic complete zero-tax/zero-fee evidence, never real checkout data."""
    value = {"item_id": item_id, "item_price_usd": price, "shipping_usd": ship,
             "tax_usd": 0, "mandatory_fees_usd": 0, "currency": "USD", "market": "US",
             "quantity": 1, "shipping_method": "standard", "destination_key": "us_fixture",
             "observed_at": ago(1), "source_url": "https://example.com/synthetic-quote"}
    value.update(extra)
    return value


def oy_item(title, price, ship=None, brand="Acme", **extra):
    row = {"product_id": "id-" + title[:6], "product": title, "brand": brand, "price_usd": price, "currency": "USD", "is_soldout": False}
    if ship is not None:
        row["shipping_usd"] = ship
    row.update(extra)
    if ship is not None:
        row.setdefault("checkout_quote", checkout_quote(row["product_id"], price, ship))
    return row


def base_docs(market_items=None, own_price=10.0, market_hours=1.0, verified=True, extra_rows=()):
    rows = [score_row("100", "테스트 글로우 세럼 30 ml", grade="A", score=80),
            score_row("200", "테스트 S 앰플 30 ml", grade="S", score=95, s_rank=1)] + list(extra_rows)
    docs = {
        "score": {"generated_at": ago(0), "s_slot_limit": 10, "s_slot_open": 8, "all_scored": rows},
        "registry": {"items": [
            {"pd_no": "100", "status": "ACTIVE", "title": "Acme Glow Serum 30 ml", "single_usd": own_price, "date": "2026-10-10",
             "price_observed_at": ago(2)},
            {"pd_no": "200", "status": "ACTIVE", "title": "Acme Ampoule 30 ml", "single_usd": 12.0, "date": "2026-10-10",
             "price_observed_at": ago(2)}]},
        "candidate_comparison": {"excluded_market_sources": {} if verified else {"oliveyoung_us": "unverified_or_stale_source"}},
        "pricing_model": {"exchange_rate": {"usd_to_krw": 1341.69}, "cost_basis": {"payment_fee": "Shopify 3.9% + 3.5% = 7.4%"},
                          "scenarios": {"1개_묶음배송": [{"pd_no": "100", "landed_cost_ddu_usd": 8.84, "landed_cost_ddp_usd": 8.5}],
                                       "2개_묶음배송": []}},
        "profitability": {"min_margin_pct": 15.0, "min_net_profit_usd": 1.5},
    }
    if market_items is not None:
        docs["oliveyoung_us"] = oy_doc(market_items, market_hours)
    for row in docs["registry"]["items"]:
        row["checkout_quote"] = checkout_quote(row["pd_no"], row["single_usd"], 3.0)
    return docs


def build(docs, **kw):
    # Explicit internal trust-boundary fixture for the comparison algorithm.
    # Production normalization has no trusted quote producer and always keeps
    # source_verified=False. Ingress safety is tested without this fixture in
    # test_checkout_price_evidence.py; no JSON value enables trust in production.
    original = bps.checkout_total_evidence

    def trusted_synthetic_record(*args, **kwargs):
        result = original(*args, **kwargs)
        result["source_verified"] = result["known"]
        result["source_reasons"] = [] if result["known"] else ["checkout_source_provenance_unverified"]
        return result

    with patch.object(bps, "checkout_total_evidence", side_effect=trusted_synthetic_record):
        return bps.build_strategy(docs, [], NOW, kw.pop("max_age_hours", 168.0),
                                  kw.pop("own_shipping_usd", None), kw.pop("analytics_status", None))


def product(report, pd):
    return next(p for p in report["products"] if p["pd_no"] == pd)


class UnitTests(unittest.TestCase):
    def test_fl_oz_to_ml_is_exact(self):
        q = bps.parse_quantity([("t", "Serum 1 fl. oz.")])
        self.assertEqual(q["primary_dim"], "ml")
        self.assertEqual(q["total"], 29.573530)  # 29.5735295625 rounded to 6 dp
        self.assertEqual(bps.ML_PER_FL_OZ, Decimal("29.5735295625"))
        self.assertIn("converted_from_fl_oz", q["flags"])

    def test_metric_value_preferred_when_both_given_and_consistent(self):
        q = bps.parse_quantity([("t", "Serum 1.01 fl. oz.(30ml)")])
        self.assertEqual((q["status"], q["total"], q["base_unit"]), ("ok", 30.0, "ml"))

    def test_litre_kg_lb_conversions(self):
        self.assertEqual(bps.parse_quantity([("t", "Wash 1.5 L")])["total"], 1500.0)
        self.assertEqual(bps.parse_quantity([("t", "Bar 0.09 kg")])["total"], 90.0)
        self.assertEqual(bps.parse_quantity([("t", "Salt 1 lb")])["total"], 453.59237)
        self.assertEqual(bps.parse_quantity([("t", "Mask 28 g")])["base_unit"], "g")

    def test_grams_never_compared_with_ml(self):
        own = bps.parse_quantity([("t", "Cream 50 ml")])
        comp = bps.parse_quantity([("t", "Cream 50 g")])
        self.assertIsNone(bps.comparable_dim(own, comp))
        self.assertIsNone(bps.comparable_dim(comp, own))

    def test_plain_oz_is_ambiguous_and_matches_only_itself(self):
        oz = bps.parse_quantity([("t", "Body Wash 30.6 oz")])
        self.assertEqual(oz["primary_dim"], "oz_ambiguous")
        self.assertIsNone(bps.comparable_dim(bps.parse_quantity([("t", "x 900 ml")]), oz))
        self.assertIsNone(bps.comparable_dim(bps.parse_quantity([("t", "x 900 g")]), oz))
        self.assertEqual(bps.comparable_dim(oz, deepcopy(oz)), "oz_ambiguous")

    def test_oz_corroborating_g_is_not_ambiguous(self):
        q = bps.parse_quantity([("t", "Cushion 0.49 oz.(14g)")])
        self.assertEqual((q["primary_dim"], q["total"]), ("g", 14.0))
        self.assertIn("oz_corroborates_g", q["flags"])

    def test_pack_total_kept_separate(self):
        for text in ("VT 리들샷 2 ml*6개입", "VT Reedle 2ml x 6", "앰플 2 ml 6개입", "Ampoule 2ml X 6ea"):
            q = bps.parse_quantity([("t", text)])
            self.assertEqual((q["unit_amount"], q["pack_count"], q["total"], q["base_unit"]), (2.0, 6, 12.0, "ml"), text)

    def test_pack_with_fl_oz_restatement(self):
        q = bps.parse_quantity([("g", "4 ml / 0.13 fl. oz. 4 ml x 4 EA")])
        self.assertEqual((q["unit_amount"], q["pack_count"], q["total"]), (4.0, 4, 16.0))

    def test_name_and_gosi_agreement_and_conflict(self):
        ok = bps.parse_quantity([("name", "세럼 30 ml"), ("gosi", "30ml (1.01 fl.oz)")])
        self.assertEqual(ok["status"], "ok")
        bad = bps.parse_quantity([("name", "세럼 30 ml"), ("gosi", "50ml")])
        self.assertEqual(bad["status"], "conflict")
        self.assertIsNone(bad["total"])
        self.assertFalse(bps.quantity_usable(bad))

    def test_count_is_secondary_to_mass_and_volume(self):
        q = bps.parse_quantity([("name", "마스크팩 30매"), ("gosi", "30매 (내용량 110g)")])
        self.assertEqual((q["primary_dim"], q["total"]), ("g", 110.0))
        self.assertEqual(q["alternates"]["count"]["total"], 30.0)
        q2 = bps.parse_quantity([("name", "마스크팩 1매"), ("gosi", "18g")])
        self.assertEqual((q2["primary_dim"], q2["total"]), ("g", 18.0))
        self.assertEqual(q2["alternates"]["count"]["total"], 1.0)

    def test_plus_bundle_is_ambiguous(self):
        q = bps.parse_quantity([("t", "Essence 1.69 fl. oz.(50ml) Set (+Reedle Shot 2ml)")])
        self.assertEqual(q["status"], "ambiguous")
        self.assertFalse(bps.quantity_usable(q))
        self.assertEqual(bps.parse_quantity([("t", "Sun SPF50+ 50ml")])["status"], "ok")

    def test_unknown_quantity_is_unknown_not_zero(self):
        q = bps.parse_quantity([("t", "립밤 03 멜로우")])
        self.assertEqual(q["status"], "unknown")
        self.assertIsNone(q["total"])

    def test_unit_price_exact(self):
        self.assertEqual(bps.unit_price("24", "12"), Decimal(2))
        self.assertIsNone(bps.unit_price("24", 0))
        self.assertIsNone(bps.unit_price(None, 12))


class IdentityTests(unittest.TestCase):
    def tok(self, title, brand=None):
        return bps.identity_tokens(title, brand)["tokens"]

    def test_different_strength_variant_is_not_same_product(self):
        own = self.tok("VT Reedle Shot 300 Facial Boosting First Ampoule 2ml x 6")
        self.assertFalse(bps.identity_match(own, self.tok("VT Reedle Shot 100 Ampoule 2ml x 6")))
        self.assertTrue(bps.identity_match(own, self.tok("Reedle Shot 300 Ampoule 2 ml x 6", "VT COSMETICS")))
        self.assertTrue(bps.identity_match(own, self.tok("Reedle Shot 300", "VT")))  # missing type word on one side only

    def test_different_formulation_model_set_kit_not_matched(self):
        own = self.tok("VT Reedle Shot 300 Ampoule")
        for other in ("VT Collagen Reedle Shot 300", "VT Reedle Shot Starter Kit (8ct)", "VT PDRN Reedle Shot Hair Ampoule 300",
                      "VT Reti-A Reedle Shot 300"):
            self.assertFalse(bps.identity_match(own, self.tok(other)), other)

    def test_type_word_conflict_rejected(self):
        self.assertFalse(bps.identity_match(self.tok("Acme Retinol Serum 30ml"), self.tok("Acme Retinol Cream 30ml")))

    def test_multi_option_listing_flagged(self):
        self.assertTrue(bps.identity_tokens("[2options] Acme Glow Serum 30ml")["multi_option"])
        self.assertTrue(bps.identity_tokens("[30shades] Acme Cushion 14g")["multi_option"])
        self.assertFalse(bps.identity_tokens("Acme Glow Serum 30ml")["multi_option"])

    def test_pack_tail_not_part_of_identity(self):
        self.assertEqual(self.tok("Acme Serum 2ml x 6"), self.tok("Acme Serum 2 ml*6개입"))
        self.assertNotIn("6", self.tok("Acme Serum 2ml x 6ea"))

    def test_trivial_one_token_never_matches(self):
        self.assertFalse(bps.identity_match(["serum"], ["serum"]))


class FreshnessTests(unittest.TestCase):
    def test_fresh_stale_invalid(self):
        self.assertEqual(bps.assess_freshness(ago(2), NOW, 168)["state"], "fresh")
        self.assertEqual(bps.assess_freshness(ago(200), NOW, 168)["state"], "stale")
        self.assertEqual(bps.assess_freshness("2026-10-11", NOW, 168)["state"], "invalid")  # date only
        self.assertEqual(bps.assess_freshness("garbage", NOW, 168)["state"], "invalid")
        self.assertEqual(bps.assess_freshness(None, NOW, 168)["state"], "invalid")
        self.assertEqual(bps.assess_freshness((NOW + timedelta(hours=3)).isoformat(), NOW, 168)["state"], "invalid")
        self.assertEqual(bps.assess_freshness("2026-10-11T01:00:00", NOW, 168)["state"], "fresh")  # naive = UTC


class ComparatorTests(unittest.TestCase):
    def test_stale_source_is_reference_only_and_never_scored(self):
        docs = base_docs([oy_item("Acme Glow Serum 1.01 fl. oz.(30ml)", 20.0, ship=4.0)], market_hours=400)
        r = build(docs, own_shipping_usd=3.0)
        p = product(r, "100")
        self.assertEqual(p["market"]["tier_counts"], {"qualified": 0, "provisional": 0, "reference_only": 1})
        self.assertIn("stale_by_age", p["market"]["reference_only"][0]["not_used_because"])
        self.assertEqual(p["price_position"]["status"], "unknown")
        self.assertEqual(p["priority"]["components"]["verified_price_points"], 0.0)
        self.assertEqual(p["priority"]["score"], 48.0)

    def test_unverified_source_flagged_by_candidate_comparison(self):
        docs = base_docs([oy_item("Acme Glow Serum 30ml", 20.0, ship=4.0)], verified=False)
        p = product(build(docs, own_shipping_usd=3.0), "100")
        self.assertEqual(p["market"]["tier_counts"]["qualified"], 0)
        self.assertEqual(p["market"]["tier_counts"]["reference_only"], 1)
        self.assertEqual(p["price_position"]["status"], "unknown")

    def test_missing_verification_evidence_means_unverified(self):
        docs = base_docs([oy_item("Acme Glow Serum 30ml", 20.0, ship=4.0)])
        del docs["candidate_comparison"]
        p = product(build(docs, own_shipping_usd=3.0), "100")
        self.assertEqual(p["market"]["tier_counts"]["reference_only"], 1)
        self.assertFalse(p["price_position"]["verified"])

    def test_verified_advantage_with_known_shipping_both_sides(self):
        docs = base_docs([oy_item("Acme Glow Serum 1.01 fl. oz.(30ml)", 20.0, ship=4.0),
                          oy_item("Acme Glow Serum 30ml", 30.0, ship=0.0)])
        r = build(docs, own_shipping_usd=3.0)
        p = product(r, "100")
        pos = p["price_position"]
        self.assertEqual(pos["status"], "verified_below")
        self.assertTrue(pos["verified"])
        self.assertEqual(pos["basis"], "delivered_exact_pack_total")
        self.assertAlmostEqual(pos["gap_pct"], (24 - 13) / 24 * 100, places=2)
        self.assertAlmostEqual(pos["own_unit_price"] * 30, 13.0, places=3)
        self.assertGreater(p["priority"]["components"]["verified_price_points"], 20)

    def test_market_shipping_unknown_is_provisional_without_points(self):
        docs = base_docs([oy_item("Acme Glow Serum 30ml", 20.0)])
        p = product(build(docs, own_shipping_usd=3.0), "100")
        self.assertEqual(p["price_position"]["status"], "provisional_below")
        self.assertFalse(p["price_position"]["verified"])
        self.assertIn("market_shipping_unknown", p["price_position"]["reasons"])
        self.assertEqual(p["priority"]["evidence_status"], "provisional_not_counted")
        self.assertEqual(p["priority"]["components"]["verified_price_points"], 0.0)
        self.assertGreater(p["priority"]["components"]["provisional_price_points_not_counted"], 0)
        self.assertEqual(p["priority"]["score"], 48.0)

    def test_own_shipping_unknown_is_provisional(self):
        docs = base_docs([oy_item("Acme Glow Serum 30ml", 20.0, ship=4.0)])
        p = product(build(docs), "100")
        self.assertEqual(p["price_position"]["status"], "provisional_below")
        self.assertIn("own_customer_shipping_unknown", p["price_position"]["reasons"])

    def test_cheaper_item_with_unknown_shipping_blocks_verified_claim(self):
        docs = base_docs([oy_item("Acme Glow Serum 30ml", 30.0, ship=0.0), oy_item("Acme Glow Serum 30ml", 11.0, brand="Acme")])
        docs["oliveyoung_us"]["products"][1]["product_id"] = "other"
        p = product(build(docs, own_shipping_usd=3.0), "100")  # own delivered 13 vs cheaper item price 11 (ship unknown)
        self.assertFalse(p["price_position"]["verified"])
        self.assertIn("cheaper_item_price_with_unknown_shipping", p["price_position"]["reasons"])
        self.assertEqual(p["price_position"]["status"], "provisional_below")  # item price 10 vs 11, not delivered
        self.assertEqual(p["priority"]["components"]["verified_price_points"], 0.0)

    def test_draft_only_price_is_not_verified(self):
        docs = base_docs([oy_item("Acme Glow Serum 30ml", 20.0, ship=4.0)])
        docs["registry"]["items"][0]["status"] = "DRAFT"
        docs["queue"] = {"generated_at": ago(1), "draft_actions": [{"immutablePayload": {"products": [
            {"pd_no": "100", "Title": "Acme Glow Serum 30 ml", "Variant Price": "10.00", "Status": "draft"}]}}]}
        p = product(build(docs, own_shipping_usd=3.0), "100")
        self.assertEqual(p["own_price"]["status"], "draft_payload")
        self.assertEqual(p["price_position"]["status"], "provisional_below")
        self.assertIn("own_price_not_live_listing", p["price_position"]["reasons"])

    def test_not_below_gets_no_points(self):
        docs = base_docs([oy_item("Acme Glow Serum 30ml", 8.0, ship=0.0)])
        p = product(build(docs, own_shipping_usd=3.0), "100")
        self.assertEqual(p["price_position"]["status"], "verified_not_below")
        self.assertEqual(p["priority"]["components"]["verified_price_points"], 0.0)

    def test_equal_price_is_not_below(self):
        docs = base_docs([oy_item("Acme Glow Serum 30ml", 13.0, ship=0.0)])
        p = product(build(docs, own_shipping_usd=3.0), "100")
        self.assertEqual(p["price_position"]["status"], "verified_not_below")

    def test_different_variant_item_is_not_used_even_if_cheaper(self):
        docs = base_docs([oy_item("Acme Glow Serum Collagen 30ml", 1.0, ship=0.0),
                          oy_item("Acme Glow Serum 2 30ml", 1.0, ship=0.0, product_id="v2"),
                          oy_item("Acme Glow Serum Set 30ml", 1.0, ship=0.0, product_id="set")])
        p = product(build(docs, own_shipping_usd=3.0), "100")
        self.assertEqual(p["market"]["tier_counts"], {"qualified": 0, "provisional": 0, "reference_only": 0})
        self.assertEqual(p["price_position"]["status"], "unknown")
        self.assertEqual(len(p["market"]["near_misses"]), 3)
        self.assertEqual(p["market"]["rejected_counts"], {"identity_mismatch": 3})

    def test_different_size_same_product_uses_per_unit_like_basis(self):
        docs = base_docs([oy_item("Acme Glow Serum 60ml", 30.0, ship=0.0)])
        pos = product(build(docs, own_shipping_usd=3.0), "100")["price_position"]
        # 60 ml vs 30 ml is outside the 5% volume tolerance: like-basis only, never verified
        self.assertEqual(pos["basis"], "item_price_per_unit_like_basis")
        self.assertEqual(pos["status"], "provisional_below")
        self.assertFalse(pos["verified"])
        self.assertIn("comparator_size_outside_volume_tolerance", pos["reasons"])
        self.assertEqual(pos["base_unit"], "ml")
        self.assertAlmostEqual(pos["comparator_unit_price"], 0.5, places=6)

    def test_ml_comparator_does_not_match_gram_product(self):
        docs = base_docs([oy_item("Acme Glow Serum 30g", 30.0, ship=0.0)])
        p = product(build(docs, own_shipping_usd=3.0), "100")
        self.assertEqual(p["market"]["rejected_counts"].get("quantity_unknown_or_dimension_mismatch"), 1)
        self.assertEqual(p["price_position"]["status"], "unknown")

    def test_pack_total_difference_is_not_exact(self):
        docs = base_docs([oy_item("Acme Glow Serum 5ml x 6", 20.0, ship=0.0)])
        docs["registry"]["items"][0]["title"] = "Acme Glow Serum 30 ml"
        pos = product(build(docs, own_shipping_usd=3.0), "100")["price_position"]
        # same 30 ml total but 6 packs of 5 ml vs a single 30 ml: pack structure differs, so not "exact"
        self.assertEqual(pos["basis"], "item_price_total_volume_within_tolerance")
        self.assertFalse(pos["verified"])
        self.assertIn("comparator_exact_pack_required", pos["reasons"])
        self.assertAlmostEqual(pos["comparator_unit_price"], 20 / 30, places=6)

    def test_rejections_multi_option_currency_soldout_market(self):
        docs = base_docs([oy_item("[2options] Acme Glow Serum 30ml", 5.0, ship=0.0),
                          oy_item("Acme Glow Serum 30ml", 5.0, ship=0.0, currency="KRW", product_id="a"),
                          oy_item("Acme Glow Serum 30ml", 5.0, ship=0.0, is_soldout=True, product_id="b"),
                          oy_item("Acme Glow Serum 30ml", 5.0, ship=0.0, market="KR", product_id="c"),
                          oy_item("Acme Glow Serum 30ml", None, ship=0.0, product_id="d"),
                          oy_item("Acme Glow Serum 30ml", -3.0, ship=0.0, product_id="e")])
        rc = product(build(docs, own_shipping_usd=3.0), "100")["market"]["rejected_counts"]
        for key in ("multi_option_listing_price_unspecified", "currency_not_usd", "sold_out", "market_mismatch", "price_missing_or_invalid"):
            self.assertIn(key, rc)
        self.assertEqual(rc["price_missing_or_invalid"], 2)

    def test_no_english_identity_means_no_comparison(self):
        docs = base_docs([oy_item("Acme Glow Serum 30ml", 20.0, ship=0.0)], extra_rows=[score_row("300", "이름만 한글 세럼 30 ml")])
        p = product(build(docs, own_shipping_usd=3.0), "300")
        self.assertFalse(p["market"]["english_identity_available"])
        self.assertEqual(p["price_position"]["status"], "unknown")
        self.assertIn("own_price_missing", p["price_position"]["reasons"])

    def test_aggregate_serpapi_is_reference_never_comparator(self):
        docs = base_docs([])
        docs["serpapi"] = {"generated_at": ago(1), "prices": {"items": [{"pd_no": "100", "query": "q", "n": 20, "min_usd": 1.0,
                                                                          "median_usd": 9.0, "max_usd": 50.0}]}}
        p = product(build(docs, own_shipping_usd=3.0), "100")
        self.assertFalse(p["market"]["aggregate_reference"]["qualified"])
        self.assertEqual(p["price_position"]["status"], "unknown")


class MissingDataTests(unittest.TestCase):
    def test_missing_prices_units_shipping_do_not_fabricate_victory(self):
        docs = base_docs([oy_item("Acme Glow Serum", 20.0)])  # no size, no shipping
        r = build(docs)
        for p in r["products"]:
            self.assertFalse(p["price_position"]["verified"])
            self.assertEqual(p["priority"]["components"]["verified_price_points"] if p["included_in_priority"] else 0.0, 0.0)
        self.assertEqual(r["input_coverage"]["price_position"], {"unknown": 2})

    def test_missing_own_price(self):
        docs = base_docs([oy_item("Acme Glow Serum 30ml", 20.0, ship=0.0)])
        docs["registry"] = {"items": []}
        p = product(build(docs, own_shipping_usd=3.0), "100")
        self.assertEqual(p["own_price"]["status"], "missing")
        self.assertIsNone(p["own_price"]["price_usd"])
        self.assertEqual(p["profitability_risk"], "unknown")

    def test_missing_pricing_model_margin_unknown(self):
        docs = base_docs([])
        del docs["pricing_model"]
        r = build(docs)
        p = product(r, "100")
        self.assertEqual(p["profitability_risk"], "unknown")
        self.assertEqual(p["margin_advisory"]["risk_basis"], "price_or_cost_missing")

    def test_analytics_missing_is_unknown_not_zero(self):
        r = build(base_docs([]))
        plan = r["review_24h"]
        self.assertFalse(plan["analytics_input"]["provided"])
        self.assertTrue(plan["products"])
        for e in plan["products"]:
            for v in e["metrics"].values():
                self.assertEqual(v, "UNKNOWN")
        self.assertEqual(plan["store_level_context"], "UNKNOWN")

    def test_store_monthly_nulls_are_unknown(self):
        docs = base_docs([])
        docs["monthly_revenue"] = {"last_month": {"label": "2026-08", "orders": None, "revenue_usd": None}}
        ctx = build(docs)["review_24h"]["store_level_context"]
        self.assertEqual((ctx["orders"], ctx["revenue_usd"], ctx["level"]), ("UNKNOWN", "UNKNOWN", "store_monthly_not_product_level"))

    def test_analytics_real_zero_vs_missing_metric(self):
        start = NOW - timedelta(hours=24)
        analytics = {"observations": [
            {"pd_no": "100", "window_start": start.isoformat(), "window_end": NOW.isoformat(), "sessions": 12, "orders": 0,
             "units": None, "revenue_usd": "bad", "source": "shopify_analytics_export"}]}
        docs = base_docs([])
        docs["analytics"] = analytics
        r = build(docs, analytics_status={"path": "a.json", "loaded": True})
        e = next(x for x in r["review_24h"]["products"] if x["pd_no"] == "100")
        self.assertEqual(e["metrics"]["sessions"], 12)
        self.assertEqual(e["metrics"]["orders"], 0)  # an explicit observed zero stays 0
        self.assertEqual(e["metrics"]["units"], "UNKNOWN")
        self.assertEqual(e["metrics"]["revenue_usd"], "UNKNOWN")
        self.assertEqual(e["metrics"]["product_views"], "UNKNOWN")
        self.assertEqual(r["review_24h"]["analytics_input"]["product_level_observations_used"], 1)

    def test_analytics_wrong_window_or_other_product_not_used(self):
        start = NOW - timedelta(hours=72)
        docs = base_docs([])
        docs["analytics"] = {"observations": [
            {"pd_no": "100", "window_start": start.isoformat(), "window_end": NOW.isoformat(), "sessions": 99},
            {"pd_no": "999", "window_start": (NOW - timedelta(hours=24)).isoformat(), "window_end": NOW.isoformat(), "sessions": 5}]}
        r = build(docs)
        e = next(x for x in r["review_24h"]["products"] if x["pd_no"] == "100")
        self.assertEqual(e["metrics"]["sessions"], "UNKNOWN")

    def test_review_plan_promises_no_causality_and_draft_not_applicable(self):
        docs = base_docs([])
        docs["registry"]["items"][0]["status"] = "DRAFT"
        docs["queue"] = {"generated_at": ago(1), "draft_actions": [{"immutablePayload": {"products": [
            {"pd_no": "100", "Title": "Acme Glow Serum 30 ml", "Variant Price": "10.00"}]}}]}
        plan = build(docs)["review_24h"]
        self.assertIn("cannot show", plan["causality_policy"])
        e = next(x for x in plan["products"] if x["pd_no"] == "100")
        self.assertFalse(e["review_applicable"])
        self.assertEqual(e["price_change_anchor_at"], "UNKNOWN")


class SPreservationTests(unittest.TestCase):
    def advantaged_docs(self):
        docs = base_docs([oy_item("Acme Glow Serum 1.01 fl. oz.(30ml)", 40.0, ship=0.0),
                          oy_item("Acme Ampoule 30ml", 90.0, ship=0.0, product_id="amp")], own_price=5.0)
        return docs

    def test_a_with_verified_advantage_is_not_upgraded(self):
        r = build(self.advantaged_docs(), own_shipping_usd=3.0)
        a = product(r, "100")
        self.assertEqual(a["price_position"]["status"], "verified_below")
        self.assertEqual((a["grade"], a["grade_original"], a["grade_changed_by_this_report"]), ("A", "A", False))
        self.assertEqual(r["s_preservation"]["a_products_with_verified_price_advantage_not_upgraded"], ["100"])
        self.assertEqual(r["s_preservation"]["grade_changes"], [])
        self.assertFalse(r["policy"]["a_auto_upgrade_allowed"])

    def test_s_ranks_before_a_even_if_a_priority_score_is_higher(self):
        r = build(self.advantaged_docs(), own_shipping_usd=3.0)
        a, s = product(r, "100"), product(r, "200")
        self.assertLess(s["priority_rank"], a["priority_rank"])
        self.assertEqual(r["priority_order"][0], "200")

    def test_a_score_can_exceed_s_but_grade_tier_still_orders(self):
        docs = self.advantaged_docs()
        docs["score"]["all_scored"][1]["shopify_score"] = 82  # S just at threshold
        r = build(docs, own_shipping_usd=3.0)
        a, s = product(r, "100"), product(r, "200")
        self.assertGreater(a["priority"]["score"], s["priority"]["score"])
        self.assertEqual(r["priority_order"], ["200", "100"])

    def test_s_audit_reports_but_never_changes_grade(self):
        docs = base_docs([])
        docs["score"]["all_scored"][1]["s_rule"] = "score_below_82"
        docs["score"]["all_scored"][1]["shopify_score"] = 70
        r = build(docs)
        s = product(r, "200")
        self.assertEqual(s["grade"], "S")
        self.assertFalse(s["s_gate_audit"]["constraints_met"])
        self.assertEqual(set(s["s_gate_audit"]["failed_constraints"]), {"score_below_82", "s_rule_not_qualifying"})
        self.assertEqual(r["s_preservation"]["s_gate_constraints_failed"], ["200"])
        self.assertEqual(r["s_preservation"]["grade_changes"], [])

    def test_s_audit_passes_for_valid_s_and_does_not_apply_to_others(self):
        r = build(base_docs([]))
        self.assertTrue(product(r, "200")["s_gate_audit"]["constraints_met"])
        self.assertFalse(product(r, "100")["s_gate_audit"]["applies"])

    def test_grades_unchanged_for_every_product(self):
        docs = base_docs([oy_item("Acme Glow Serum 30ml", 40.0, ship=0.0)], own_price=1.0,
                         extra_rows=[score_row("300", "X B", grade="B", score=65), score_row("400", "X C", grade="C", score=20)])
        r = build(docs, own_shipping_usd=0.0)
        src = {x["pd_no"]: x["grade"] for x in docs["score"]["all_scored"]}
        for p in r["products"]:
            self.assertEqual(p["grade"], src[p["pd_no"]])

    def test_other_buckets_not_covered_and_misfit_excluded(self):
        docs = base_docs([], extra_rows=[score_row("500", "향수 미스트 50 ml", bucket="향수"),
                                          score_row("600", "NITEX 그립 코팅장갑", bucket="메이크업", grade="C", score=30),
                                          score_row("700", "일반 립 틴트 3 g", bucket="메이크업", grade="B", score=62)])
        r = build(docs)
        self.assertEqual(r["input_coverage"]["score_file"]["other_buckets_not_covered"], 1)
        misfit = product(r, "600")
        self.assertFalse(misfit["included_in_priority"])
        self.assertIsNone(misfit["priority"]["score"])
        self.assertIsNone(misfit["priority_rank"])
        self.assertNotIn("600", r["priority_order"])
        self.assertIn("700", r["priority_order"])
        self.assertEqual(product(r, "700")["category"], "makeup")


class MarginTests(unittest.TestCase):
    def test_negative_margin_is_advisory_and_visible(self):
        docs = base_docs([], own_price=4.92)
        r = build(docs)
        p = product(r, "100")
        self.assertEqual(p["profitability_risk"], "negative_margin")
        self.assertFalse(p["margin_advisory"]["blocking"])
        self.assertEqual(p["margin_advisory"]["waiver"], "user_waived_margin_block")
        sc = p["margin_advisory"]["scenarios"]["ship_1_unit_order"]
        self.assertLess(sc["net_profit_usd"], 0)
        self.assertLess(sc["margin_pct"], 0)
        self.assertTrue(p["included_in_priority"])
        self.assertIn("100", r["priority_order"])
        self.assertEqual(p["priority"]["score"], 48.0)  # margin never reduces the score

    def test_negative_margin_does_not_demote_or_remove_s(self):
        docs = base_docs([], own_price=1.0)
        docs["registry"]["items"][1]["single_usd"] = 1.0
        docs["pricing_model"]["scenarios"]["1개_묶음배송"].append({"pd_no": "200", "landed_cost_ddu_usd": 9.0})
        r = build(docs)
        s = product(r, "200")
        self.assertEqual(s["profitability_risk"], "negative_margin")
        self.assertEqual(s["grade"], "S")
        self.assertIsNotNone(s["priority_rank"])

    def test_margin_matches_pricing_model_numbers(self):
        sc = bps.margin_scenario(23.99, 8.84, Decimal("0.074"), 15.0, 1.5)
        self.assertEqual((sc["fee_usd"], sc["net_profit_usd"], sc["margin_pct"], sc["risk"]), (1.78, 13.37, 55.7, "ok"))

    def test_below_floor_and_bound_risk(self):
        low = bps.margin_scenario(11.0, 8.84, Decimal("0.074"), 15.0, 1.5)
        self.assertEqual(low["risk"], "below_advisory_floor")
        m = bps.margin_advisory(2.0, "x", 2.24, {}, Decimal("0.074"), {"min_margin_pct": 15.0, "min_net_profit_usd": 1.5})
        self.assertEqual((m["risk"], m["risk_basis"], m["blocking"]), ("negative_margin", "upper_bound_certain", False))
        m2 = bps.margin_advisory(20.0, "x", 2.24, {}, Decimal("0.074"), {"min_margin_pct": 15.0, "min_net_profit_usd": 1.5})
        self.assertEqual((m2["risk"], m2["risk_basis"]), ("unknown", "landed_cost_missing"))
        self.assertIn("upper_bound_margin_pct_excluding_shipping_and_tariff", m2)

    def test_missing_inputs_margin_unknown(self):
        self.assertEqual(bps.margin_scenario(None, 8.0, Decimal("0.07"))["risk"], "unknown")
        self.assertEqual(bps.margin_scenario(10, None, Decimal("0.07"))["status"], "unknown_missing_inputs")
        self.assertEqual(bps.margin_scenario(0, 8, Decimal("0.07"))["risk"], "unknown")


class ConfigAlignmentTests(unittest.TestCase):
    CONFIG = {
        "policy_id": "t", "grade_policy": {"allowed_grades": ["S"], "lower_grade_fallback": False},
        "categories": [
            {"tag": "skincare", "daiso_name": "스킨케어", "score_buckets": ["스킨케어", "마스크팩", "클렌징", "선케어"], "allowed_grades": ["S"]},
            {"tag": "makeup", "daiso_name": "메이크업", "score_buckets": ["메이크업"], "allowed_grades": ["S"]},
            {"tag": "body", "daiso_name": "바디케어", "score_buckets": ["바디케어"], "allowed_grades": ["S"]}],
        "price_policy": {"margin_advisory": {"target_margin": 0.40, "minimum_margin": 0.30, "estimated_weight_extra_margin": 0.05},
                         "volume_comparison": {"tolerance": 0.05},
                         "price_evidence": {"sources": {"serpapi_google_shopping": {"min_sample": 5, "max_age_days": 30, "price_factor": 0.95}}}}}

    def docs(self, **kw):
        d = base_docs(**kw)
        d["commerce_config"] = deepcopy(self.CONFIG)
        return d

    def test_config_buckets_map_to_tags(self):
        cfg = bps.parse_category_config(self.CONFIG)
        self.assertEqual(cfg["order"], ["skincare", "makeup", "body"])
        for b in ("스킨케어", "마스크팩", "클렌징", "선케어"):
            self.assertEqual(cfg["bucket_to_tag"][b], "skincare")
        self.assertEqual(cfg["bucket_to_tag"]["바디케어"], "body")
        self.assertTrue(bps.parse_category_config(None)["used_fallback"])
        self.assertEqual(bps.parse_category_config({"categories": []})["order"], ["skincare", "makeup", "body"])

    def test_skin_mask_s_is_reclassified_into_skincare_and_stays_s(self):
        docs = self.docs(extra_rows=[score_row("900", "테스트 콜라겐 마스크 28 g", bucket="마스크팩", grade="S", score=90, s_rule="ingredient+form"),
                                     score_row("901", "테스트 클렌징 폼 100 ml", bucket="클렌징", grade="A", score=84)])
        r = build(docs)
        m = product(r, "900")
        self.assertEqual((m["category"], m["bucket_ko"], m["grade"]), ("skincare", "마스크팩", "S"))
        self.assertEqual(m["reclassified_into_category_from_bucket"], "마스크팩")
        self.assertTrue(m["s_gate_audit"]["constraints_met"])
        self.assertIn("900", r["config_alignment"]["reclassified_s"])
        self.assertIn("900", r["s_preservation"]["s_by_category"]["skincare"])
        self.assertEqual(r["s_preservation"]["s_outside_config_categories"], [])
        self.assertEqual(product(r, "901")["category"], "skincare")
        self.assertEqual(r["categories"]["skincare"]["s_by_score_bucket"], {"마스크팩": 1, "스킨케어": 1})
        self.assertEqual(r["s_preservation"]["grade_changes"], [])

    def test_unmapped_bucket_s_is_reported_as_outside(self):
        docs = self.docs(extra_rows=[score_row("910", "헤어 에센스 100 ml", bucket="헤어케어", grade="S", score=90)])
        r = build(docs)
        self.assertEqual(r["s_preservation"]["s_outside_config_categories"], ["910"])
        self.assertNotIn("910", [p["pd_no"] for p in r["products"]])

    def test_non_beauty_in_mask_bucket_excluded(self):
        docs = self.docs(extra_rows=[
            score_row("920", "참조은 덴탈 마스크 컬러 대형 10매입", bucket="마스크팩", grade="C", score=10, score_breakdown={"penalty": 40}),
            score_row("921", "이불용 밸브 압축팩 90x110cm", bucket="마스크팩", grade="C", score=10, score_breakdown={"penalty": 40}),
            score_row("922", "NITEX 그립 코팅장갑 L", bucket="메이크업", grade="C", score=10),
            score_row("923", "삼각 모서리 집게 클립 4개입", bucket="메이크업", grade="C", score=10),
            score_row("924", "스팀베이스 데일리 아이워머 카모마일 향", bucket="마스크팩", grade="B", score=62)])
        r = build(docs)
        for pd in ("920", "921", "922", "923", "924"):
            p = product(r, pd)
            self.assertFalse(p["included_in_priority"], pd)
            self.assertNotIn(pd, r["priority_order"])
            self.assertIn("non_beauty_misfit", p["live_selection_preview"]["all_blockers"])

    def test_sunscreen_stays_gated_even_when_bucket_is_skincare(self):
        docs = self.docs(extra_rows=[
            score_row("930", "테스트 선크림 SPF50+ 50 ml", bucket="선케어", grade="A", score=85),
            score_row("931", "테스트 선세럼 50 ml", bucket="스킨케어", grade="S", score=90, s_rule="strong_form")])
        r = build(docs)
        a = product(r, "930")
        self.assertEqual((a["category"], a["grade"], a["us_legal_gate"]), ("skincare", "A", "otc_drug"))
        self.assertIn("suncare_otc_review_not_s_eligible", a["flags"])
        s = product(r, "931")
        self.assertEqual(s["grade"], "S")  # grade is never rewritten here
        self.assertFalse(s["s_gate_audit"]["constraints_met"])
        self.assertIn("us_legal_gate_otc_drug", s["s_gate_audit"]["failed_constraints"])
        self.assertFalse(s["live_selection_preview"]["eligible_by_grade_and_gates"])
        self.assertIn("931", r["s_preservation"]["s_gate_constraints_failed"])

    def test_claim_risk_s_is_audited(self):
        docs = self.docs(extra_rows=[score_row("940", "테스트 아크네 앰플 30 ml", grade="S", score=90, s_rule="strong_form",
                                               score_breakdown={"penalty": 0, "us_block_kind": "claim_risk"})])
        s = product(build(docs), "940")
        self.assertIn("us_legal_gate_claim_risk", s["s_gate_audit"]["failed_constraints"])

    def test_live_selection_preview_follows_config_grade_policy_not_margin(self):
        r = build(self.docs(own_price=0.5))  # hugely negative margin
        a, s = product(r, "100"), product(r, "200")
        self.assertIn("grade_not_allowed_by_config", a["live_selection_preview"]["all_blockers"])
        self.assertTrue(s["live_selection_preview"]["eligible_by_grade_and_gates"])
        for p in (a, s):
            self.assertFalse([b for b in p["live_selection_preview"]["all_blockers"] if "margin" in b and "manufacturer" not in b])
        self.assertEqual(a["profitability_risk"], "negative_margin")
        self.assertIn("manufacturer_safety_record_missing", s["live_selection_preview"]["all_blockers"])
        view = r["config_alignment"]["live_selection_preview"]["skincare"]
        self.assertEqual([x["pd_no"] for x in view], ["200"])

    def test_manufacturer_safety_coverage_is_per_product(self):
        from test_manufacturer_safety import synthetic_receipt
        docs = self.docs()
        docs["mocra_business"] = {"safety_substantiation": {"covered_pd_nos": ["200"],
            "scope": "all_daiso_products", "verified_by": "SYNTHETIC OWNER", "verified_at": "2026-01-01"}}
        self.assertFalse(product(build(docs), "200")["manufacturer_safety_record_covered"])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            receipt = synthetic_receipt(root, "200")
            (root / "data/manual/mocra_business.json").write_text(
                json.dumps(docs["mocra_business"]), encoding="utf-8")
            (root / "data/manual/manufacturer_safety_evidence.private.json").write_text(
                json.dumps({"schema_version": 1, "records": [receipt]}), encoding="utf-8")
            self.assertTrue(bps.manufacturer_safety_record("200", root)["covered"])
            docs["manufacturer_safety_record_views"] = {
                "200": bps.safety_public_view(bps.manufacturer_safety_record("200", root)),
                "100": bps.safety_public_view(bps.manufacturer_safety_record("100", root))}
            r = build(docs)
            self.assertTrue(product(r, "200")["manufacturer_safety_record_covered"])
            self.assertFalse(product(r, "100")["manufacturer_safety_record_covered"])
            self.assertNotIn("manufacturer_safety_record_missing", product(r, "200")["live_selection_preview"]["all_blockers"])
            (root / receipt["file"]).unlink()
            docs["manufacturer_safety_record_views"]["200"] = bps.safety_public_view(
                bps.manufacturer_safety_record("200", root))
            self.assertFalse(product(build(docs), "200")["manufacturer_safety_record_covered"])

    def test_volume_tolerance_from_config(self):
        near = self.docs(market_items=[oy_item("Acme Glow Serum 31ml", 40.0, ship=0.0)], own_price=5.0)  # 3.2% off
        near_product = product(build(near, own_shipping_usd=3.0), "100")
        self.assertEqual(near_product["price_position"]["status"], "provisional_below")
        self.assertTrue(near_product["market"]["qualified_lowest"]["volume_within_tolerance"])
        far = self.docs(market_items=[oy_item("Acme Glow Serum 33ml", 40.0, ship=0.0)], own_price=5.0)  # 10% off
        pos = product(build(far, own_shipping_usd=3.0), "100")["price_position"]
        self.assertEqual(pos["status"], "provisional_below")
        self.assertFalse(pos["verified"])
        tight = self.docs(market_items=[oy_item("Acme Glow Serum 31ml", 40.0, ship=0.0)], own_price=5.0)
        tight["commerce_config"]["price_policy"]["volume_comparison"]["tolerance"] = 0.01
        self.assertFalse(product(build(tight, own_shipping_usd=3.0), "100")["price_position"]["verified"])

    def test_margin_target_tier_with_estimated_weight_extra(self):
        docs = self.docs(own_price=17.0)  # landed 8.84 -> about 43.7% margin
        m = product(build(docs), "100")["margin_advisory"]
        self.assertTrue(m["weight_estimated"])
        self.assertEqual(m["effective_target_margin_pct"], 45.0)
        self.assertEqual(m["advisory_floor"]["min_margin_pct"], 30.0)
        self.assertEqual(m["risk"], "below_target_margin")  # 43.7% < 40% + 5% estimated-weight extra
        self.assertFalse(m["blocking"])
        rich = product(build(self.docs(own_price=23.99)), "100")["margin_advisory"]
        self.assertEqual(rich["risk"], "ok")

    def test_serp_reference_basis_is_reference_only(self):
        docs = self.docs()
        docs["serpapi"] = {"generated_at": ago(24), "prices": {"items": [
            {"pd_no": "100", "query": "Acme Glow Serum 30ml", "n": 20, "min_usd": 1.0, "median_usd": 20.0, "max_usd": 50.0}]}}
        r = build(docs, own_shipping_usd=3.0)
        p = product(r, "100")
        ref = p["market"]["aggregate_reference"]["reference_basis"]
        self.assertTrue(ref["eligible"])
        self.assertEqual(ref["reference_basis_price_usd"], 19.0)
        self.assertEqual(ref["claim"], "reference_price_basis_only")
        self.assertFalse(ref["used_for_priority_score"])
        self.assertFalse(p["market"]["aggregate_reference"]["qualified"])
        self.assertEqual(p["price_position"]["status"], "unknown")
        self.assertEqual(p["priority"]["components"]["verified_price_points"], 0.0)

    def test_serp_reference_basis_rejections(self):
        rule = {"min_sample": 5, "max_age_days": 30, "price_factor": 0.95}
        qty30 = bps.parse_quantity([("t", "Serum 30 ml")])
        ok = {"n": 20, "query": "Serum 30ml", "median_usd": 20.0}
        self.assertTrue(bps.serp_reference_basis(ok, qty30, 10, rule)["eligible"])
        self.assertIn("sample_below_minimum", bps.serp_reference_basis(dict(ok, n=4), qty30, 10, rule)["reasons"])
        self.assertIn("older_than_max_age_days", bps.serp_reference_basis(ok, qty30, 24 * 31, rule)["reasons"])
        self.assertIn("older_than_max_age_days", bps.serp_reference_basis(ok, qty30, None, rule)["reasons"])
        self.assertIn("comparison_volume_unknown", bps.serp_reference_basis(dict(ok, query="Serum"), qty30, 10, rule)["reasons"])
        self.assertIn("product_volume_unknown", bps.serp_reference_basis(ok, bps.parse_quantity([("t", "Serum")]), 10, rule)["reasons"])
        self.assertIn("volume_dimension_mismatch", bps.serp_reference_basis(dict(ok, query="Serum 30g"), qty30, 10, rule)["reasons"])
        self.assertIn("volume_outside_tolerance", bps.serp_reference_basis(dict(ok, query="Serum 50ml"), qty30, 10, rule)["reasons"])
        self.assertIsNone(bps.serp_reference_basis(dict(ok, n=1), qty30, 10, rule)["reference_basis_price_usd"])


class OwnLiveFreshnessTests(unittest.TestCase):
    """A live own price needs a parseable observation timestamp <= 24h old (config shop_com live freshness)."""

    def docs(self, ts_item=None, drop_ts=True, **top):
        d = base_docs([oy_item("Acme Glow Serum 30ml", 40.0, ship=0.0)], own_price=5.0)
        item = d["registry"]["items"][0]
        if drop_ts:
            item.pop("price_observed_at", None)
        if ts_item is not None:
            item["price_observed_at"] = ts_item
        d["registry"].update(top)
        return d

    def pos(self, docs, **kw):
        p = product(build(docs, own_shipping_usd=3.0, **kw), "100")
        return p, p["price_position"]

    def assert_not_verified(self, p, pos, state):
        self.assertFalse(pos["verified"])
        self.assertEqual(pos["status"], "provisional_below")
        self.assertIn("own_live_price_observation_" + state, pos["reasons"])
        self.assertEqual(p["priority"]["components"]["verified_price_points"], 0.0)
        self.assertGreater(p["priority"]["components"]["provisional_price_points_not_counted"], 0)
        self.assertEqual(p["priority"]["score"], 48.0)
        self.assertEqual(p["own_price"]["live_freshness"]["state"], state)
        self.assertFalse(p["own_price"]["live_fresh"])

    def test_fresh_timestamp_is_verified(self):
        p, pos = self.pos(self.docs(ago(2)))
        self.assertEqual(pos["status"], "verified_below")
        self.assertEqual(p["own_price"]["live_freshness"]["state"], "fresh")
        self.assertEqual(p["own_price"]["observed_at_source"], "item:price_observed_at")

    def test_date_only_registry_date_never_counts(self):
        p, pos = self.pos(self.docs())  # only the registry `date` field exists
        self.assert_not_verified(p, pos, "missing")
        p2, pos2 = self.pos(self.docs("2026-10-11"))
        self.assert_not_verified(p2, pos2, "invalid")

    def test_unparseable_timestamp(self):
        p, pos = self.pos(self.docs("yesterday-ish"))
        self.assert_not_verified(p, pos, "invalid")
        p, pos = self.pos(self.docs("   ", drop_ts=True))
        self.assert_not_verified(p, pos, "missing")

    def test_stale_timestamp(self):
        p, pos = self.pos(self.docs(ago(30)))
        self.assert_not_verified(p, pos, "stale")
        self.assertEqual(p["own_price"]["live_freshness"]["age_hours"], 30.0)

    def test_future_timestamp(self):
        p, pos = self.pos(self.docs((NOW + timedelta(hours=1)).isoformat()))
        self.assert_not_verified(p, pos, "future")

    def test_boundary_and_clock_skew(self):
        self.assertEqual(bps.live_price_freshness(ago(24), NOW)["state"], "fresh")  # exactly 24h is fresh
        self.assertEqual(bps.live_price_freshness(ago(24.01), NOW)["state"], "stale")
        self.assertEqual(bps.live_price_freshness((NOW + timedelta(minutes=4)).isoformat(), NOW)["state"], "fresh")  # <=5 min skew
        self.assertEqual(bps.live_price_freshness((NOW + timedelta(minutes=6)).isoformat(), NOW)["state"], "future")
        self.assertEqual(bps.live_price_freshness("2026-10-11T01:00:00", NOW)["state"], "fresh")  # naive = UTC
        self.assertEqual(bps.live_price_freshness(None, NOW)["state"], "missing")
        self.assertEqual(bps.live_price_freshness("2026-10-11", NOW)["state"], "invalid")

    def test_registry_snapshot_fallback_and_item_precedence(self):
        p, pos = self.pos(self.docs(snapshot_at=ago(3)))
        self.assertEqual(pos["status"], "verified_below")
        self.assertEqual(p["own_price"]["observed_at_source"], "registry_snapshot:snapshot_at")
        p, pos = self.pos(self.docs(ago(40), snapshot_at=ago(1)))  # item-level stale wins over a fresh snapshot
        self.assert_not_verified(p, pos, "stale")
        p, pos = self.pos(self.docs(snapshot_at=ago(50)))
        self.assert_not_verified(p, pos, "stale")

    def test_config_live_freshness_days_is_used(self):
        docs = self.docs(ago(30))
        docs["commerce_config"] = deepcopy(ConfigAlignmentTests.CONFIG)
        docs["commerce_config"]["price_policy"]["price_evidence"]["sources"]["shop_com_live_comparable"] = {"max_age_days": 2}
        r = build(docs, own_shipping_usd=3.0)
        self.assertEqual(product(r, "100")["price_position"]["status"], "verified_below")
        self.assertEqual(r["parameters"]["own_live_max_age_hours"], 48.0)
        docs["commerce_config"]["price_policy"]["price_evidence"]["sources"]["shop_com_live_comparable"] = {"max_age_days": 1}
        self.assertFalse(product(build(docs, own_shipping_usd=3.0), "100")["price_position"]["verified"])
        self.assertEqual(build(base_docs([]))["parameters"]["own_live_max_age_hours"], 24.0)

    def test_draft_and_model_prices_never_verified_even_with_fresh_timestamps(self):
        docs = self.docs(ago(1))
        docs["registry"]["items"][0]["status"] = "DRAFT"
        docs["queue"] = {"generated_at": ago(0), "draft_actions": [{"immutablePayload": {"products": [
            {"pd_no": "100", "Title": "Acme Glow Serum 30 ml", "Variant Price": "5.00", "Status": "draft"}]}}]}
        p, pos = self.pos(docs)
        self.assertEqual(p["own_price"]["kind"], "draft_payload")
        self.assertFalse(pos["verified"])
        self.assertIn("own_price_not_live_listing", pos["reasons"])
        self.assertIsNone(p["own_price"]["live_freshness"])
        model_only = self.docs(ago(1))
        model_only["registry"]["items"][0]["status"] = "DELETED"
        model_only["pricing_model"]["offers_by_product"] = {"single": [{"pd_no": "100", "qty": 1, "price_usd": 5.0}]}
        p, pos = self.pos(model_only)
        self.assertEqual(p["own_price"]["kind"], "model_recommended")
        self.assertFalse(pos["verified"])
        self.assertEqual(p["priority"]["components"]["verified_price_points"], 0.0)

    def test_price_position_without_freshness_flag_is_never_verified(self):
        own = {"kind": "live", "price_usd": 5.0}  # direct caller that skipped the freshness step
        qty = bps.parse_quantity([("t", "Serum 30ml")])
        comp = {"unit_price_item": 1.0, "unit_price_delivered": 1.0, "basis": "exact_pack_total", "volume_within_tolerance": True,
                "base_unit": "ml", "source_id": "s", "item_id": "i", "title": "t", "price_usd": 30.0,
                "shipping_usd": 0.0, "comparator_total": 30}
        pos = bps.price_position(own, qty, {"qualified": [comp], "provisional": [], "reference_only": []}, 3.0)
        self.assertFalse(pos["verified"])

    def test_unverified_live_price_is_flagged_for_pricing_team(self):
        r = build(self.docs())
        pricing = next(t for t in r["team_work_plan"]["teams"] if t["team"] == "pricing")
        self.assertIn("own_live_price_observation_not_fresh_for_1_products", pricing["tasks"][0]["blocked_on"])
        # margin stays advisory regardless of freshness
        self.assertFalse(product(r, "100")["margin_advisory"]["blocking"])


class PlanAndOutputTests(unittest.TestCase):
    def test_team_plan_states_and_no_receipts(self):
        plan = build(base_docs([]))["team_work_plan"]
        names = [t["team"] for t in plan["teams"]]
        self.assertEqual(names, ["sourcing", "market", "pricing", "listing", "legal", "design", "channels", "knowledge", "graph"])
        for t in plan["teams"]:
            self.assertIn(t["state"], ("proposed", "input_required"))
            for task in t["tasks"]:
                self.assertIn(task["state"], ("proposed", "input_required"))
                self.assertTrue(task["evidence_required"])
        self.assertEqual(plan["receipts"], {"handoff": None, "approval": None, "completion": None})
        text = json.dumps(plan).lower()
        for banned in ("handed_off", "approved_by", "completed_at", "\"done\"", "\"completed\""):
            self.assertNotIn(banned, text)
        market = next(t for t in plan["teams"] if t["team"] == "market")
        self.assertEqual(market["state"], "input_required")

    def test_channels_not_blocked_once_a_verified_position_exists(self):
        docs = base_docs([oy_item("Acme Glow Serum 30ml", 40.0, ship=0.0)], own_price=5.0)
        plan = build(docs, own_shipping_usd=3.0)["team_work_plan"]
        ch = next(t for t in plan["teams"] if t["team"] == "channels")
        self.assertEqual(ch["state"], "proposed")

    def test_output_is_deterministic_finite_json(self):
        docs = base_docs([oy_item("Acme Glow Serum 30ml", 20.0, ship=2.0)])
        a = json.dumps(build(docs, own_shipping_usd=3.0), ensure_ascii=False, allow_nan=False, sort_keys=False)
        b = json.dumps(build(deepcopy(docs), own_shipping_usd=3.0), ensure_ascii=False, allow_nan=False, sort_keys=False)
        self.assertEqual(a, b)
        self.assertNotIn("NaN", a)
        self.assertNotIn("Infinity", a)

    def test_assert_finite_rejects_nan(self):
        with self.assertRaises(ValueError):
            bps.assert_finite({"a": [1.0, float("nan")]})
        with self.assertRaises(ValueError):
            bps.assert_finite({"a": float("inf")})
        bps.assert_finite({"a": [1.0, 2]})

    def test_non_finite_inputs_are_ignored(self):
        self.assertIsNone(bps._dec(float("nan")))
        self.assertIsNone(bps._dec(float("inf")))
        self.assertIsNone(bps._positive("abc"))
        docs = base_docs([oy_item("Acme Glow Serum 30ml", float("nan"), ship=0.0)])
        p = product(build(docs, own_shipping_usd=3.0), "100")
        self.assertEqual(p["market"]["rejected_counts"].get("price_missing_or_invalid"), 1)

    def test_no_network_or_paid_modules_imported(self):
        src = Path(bps.__file__).read_text(encoding="utf-8")
        for banned in ("import requests", "import urllib", "import http", "import socket", "import ftplib", "import smtplib", "subprocess"):
            self.assertNotIn(banned, src)

    def test_policy_flags(self):
        pol = build(base_docs([]))["policy"]
        self.assertFalse(pol["network_calls"])
        self.assertFalse(pol["paid_api_called"])
        self.assertTrue(pol["margin_block_waived_by_user"])
        self.assertFalse(pol["receipts_asserted"])


def quiet_main(argv):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return bps.main(argv)


class CliTests(unittest.TestCase):
    def make_data_dir(self, root):
        data = Path(root) / "data"
        (data / "daiso_real").mkdir(parents=True)
        docs = base_docs([oy_item("Acme Glow Serum 30ml", 20.0, ship=2.0)])
        (data / "daiso_real" / "shopify_demand_score.json").write_text(json.dumps(docs["score"], ensure_ascii=False), encoding="utf-8")
        (data / "shopify_daily_registry.json").write_text(json.dumps(docs["registry"], ensure_ascii=False), encoding="utf-8")
        (data / "oliveyoung_us_products.json").write_text(json.dumps(docs["oliveyoung_us"], ensure_ascii=False), encoding="utf-8")
        (data / "pricing_model.json").write_text(json.dumps(docs["pricing_model"], ensure_ascii=False), encoding="utf-8")
        return data

    def test_output_flag_is_required(self):
        with self.assertRaises(SystemExit) as cm:
            quiet_main([])
        self.assertEqual(cm.exception.code, 2)

    def test_writes_only_explicit_output_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            data = self.make_data_dir(root)
            out = Path(root) / "out.json"
            before = sorted(p.name for p in data.rglob("*"))
            self.assertEqual(quiet_main(["--output", str(out), "--data-dir", str(data)]), 0)
            doc = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(doc["as_of"], bps.iso(bps.parse_ts(ago(0))))
            self.assertEqual(sorted(p.name for p in data.rglob("*")), before)
            first = out.read_bytes()
            self.assertEqual(quiet_main(["--output", str(out), "--data-dir", str(data)]), 2)
            self.assertEqual(out.read_bytes(), first)
            self.assertEqual(quiet_main(["--output", str(out), "--data-dir", str(data), "--overwrite"]), 0)
            self.assertEqual(out.read_bytes(), first)  # deterministic

    def test_missing_required_input_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / "o.json"
            self.assertEqual(quiet_main(["--output", str(out), "--data-dir", str(Path(root) / "nope")]), 2)
            self.assertFalse(out.exists())

    def test_bad_numeric_args_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(SystemExit):
                quiet_main(["--output", str(Path(root) / "o.json"), "--max-age-hours", "nan"])
            with self.assertRaises(SystemExit):
                quiet_main(["--output", str(Path(root) / "o.json"), "--own-shipping-usd", "-1"])


if __name__ == "__main__":
    unittest.main()
