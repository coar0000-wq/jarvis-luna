"""Offline quote/total regression fixtures. No checkout or API is contacted."""
from copy import deepcopy
from datetime import timedelta
import json
import unittest

import build_beauty_price_strategy as strategy
from test_beauty_price_strategy import NOW, ago, base_docs, build, checkout_quote, oy_item, product


class CheckoutTotalTests(unittest.TestCase):
    def docs(self, market_price=20, own_price=10):
        return base_docs([oy_item("Acme Glow Serum 30ml", market_price, ship=0)], own_price=own_price)

    def pos(self, docs):
        return product(build(docs, own_shipping_usd=3), "100")["price_position"]

    def test_legacy_shipping_only_is_provisional_not_full_total(self):
        docs = self.docs()
        del docs["oliveyoung_us"]["products"][0]["checkout_quote"]
        del docs["registry"]["items"][0]["checkout_quote"]
        result = product(build(docs, own_shipping_usd=3), "100")
        self.assertFalse(result["price_position"]["verified"])
        self.assertEqual(result["priority"]["components"]["verified_price_points"], 0)
        market = result["market"]["provisional_lowest"]
        self.assertIsNone(market["delivered_price_usd"])
        self.assertEqual(market["item_shipping_subtotal_usd"], 20)
        self.assertIn("own_checkout_quote_missing", result["price_position"]["reasons"])

    def test_missing_invalid_tax_or_fees_never_becomes_zero(self):
        for side in ("own", "market"):
            for field in ("tax_usd", "mandatory_fees_usd"):
                for value in (None, True, False, -1, "NaN", "Infinity", "unknown", [], {}):
                    with self.subTest(side=side, field=field, value=value):
                        docs = self.docs()
                        row = docs["registry"]["items"][0] if side == "own" else docs["oliveyoung_us"]["products"][0]
                        row["checkout_quote"][field] = value
                        self.assertFalse(self.pos(docs)["verified"])
        docs = self.docs()
        del docs["registry"]["items"][0]["checkout_quote"]["tax_usd"]
        self.assertFalse(self.pos(docs)["verified"])

    def test_extreme_or_fractional_cent_quote_is_unknown_without_crashing(self):
        for value in ("1e100", "1e1000000", "1e-1000", "0.001", "1000000.01"):
            with self.subTest(value=value):
                docs = self.docs()
                docs["registry"]["items"][0]["checkout_quote"]["tax_usd"] = value
                self.assertFalse(self.pos(docs)["verified"])
                report = strategy.build_strategy(docs, [], NOW, own_shipping_usd=3)
                self.assertFalse(product(report, "100")["own_price"]["checkout_evidence"]["known"])

    def test_known_zero_is_valid_and_tax_fee_changes_total_ranking(self):
        docs = self.docs()
        self.assertTrue(self.pos(docs)["verified"])
        own = docs["registry"]["items"][0]["checkout_quote"]
        own.update(tax_usd=5, mandatory_fees_usd=4)
        # Item 10 + shipping 3 + tax 5 + mandatory fees 4 = 22 > market 20.
        pos = self.pos(docs)
        self.assertEqual(pos["status"], "verified_not_below")
        self.assertAlmostEqual(pos["own_unit_price"] * 30, 22, places=3)

    def test_market_ranks_by_full_total_not_item_subtotal(self):
        docs = self.docs()
        first = docs["oliveyoung_us"]["products"][0]
        first["checkout_quote"]["tax_usd"] = 10
        second = oy_item("Acme Glow Serum 30ml", 22, ship=0, product_id="second")
        docs["oliveyoung_us"]["products"].append(second)
        pos = self.pos(docs)
        self.assertEqual(pos["comparator"]["item_id"], "second")
        self.assertAlmostEqual(pos["comparator_unit_price"] * 30, 22, places=3)

    def test_mismatched_destination_is_provisional(self):
        docs = self.docs()
        docs["oliveyoung_us"]["products"][0]["checkout_quote"]["destination_key"] = "us_other_fixture"
        pos = self.pos(docs)
        self.assertFalse(pos["verified"])
        self.assertIn("comparison_destination_mismatch", pos["reasons"])

    def test_cheaper_incomplete_total_prevents_lowest_claim(self):
        docs = self.docs()
        unknown = oy_item("Acme Glow Serum 30ml", 11, ship=0, product_id="unknown")
        unknown["checkout_quote"].pop("tax_usd")
        docs["oliveyoung_us"]["products"].append(unknown)
        pos = self.pos(docs)
        self.assertFalse(pos["verified"])
        self.assertIn("cheaper_item_price_with_incomplete_checkout", pos["reasons"])

    def test_invalid_quote_identity_price_shipping_scope_or_freshness(self):
        bad = {
            "item_id": ["different", None],
            "item_price_usd": [11, None],
            "shipping_usd": [4, None, True],
            "currency": ["AUD", ""],
            "market": ["AU", "CA"],
            "quantity": [2, True, "1"],
            "shipping_method": ["express", ""],
            "destination_key": ["", "customer@example.com", "123 Main Street"],
            "source_url": ["", "http://example.com", "https://name:secret@example.com"],
            "observed_at": [None, "2026-10-11", "2026-10-11T01:00:00", ago(25),
                            (NOW + timedelta(minutes=1)).isoformat()],
        }
        for field, values in bad.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    docs = self.docs()
                    docs["registry"]["items"][0]["checkout_quote"][field] = value
                    self.assertFalse(self.pos(docs)["verified"])

    def test_quote_boundary_and_evidence_not_reflected_arbitrarily(self):
        quote = checkout_quote("100", 10, 3, observed_at=ago(24),
                               private_customer={"email": "do-not-output@example.com"},
                               status="approved", execution_verified=True)
        evidence = strategy.checkout_total_evidence(quote, "100", 10, 3, NOW)
        self.assertTrue(evidence["known"])
        self.assertNotIn("private_customer", evidence)
        self.assertNotIn("approved", json.dumps(evidence))
        docs = self.docs()
        docs["registry"]["items"][0]["checkout_quote"] = quote
        original = deepcopy(docs)
        result = build(docs, own_shipping_usd=3)
        self.assertNotIn("do-not-output@example.com", json.dumps(result))
        self.assertNotIn("_checkout_quote", json.dumps(result))
        self.assertEqual(docs, original)

    def test_exact_pack_quantity_required_and_g_ml_never_mixed(self):
        for title in ("Acme Glow Serum 5ml x 6", "Acme Glow Serum 31ml", "Acme Glow Serum 30g",
                      "Acme Glow Serum 30ml (2pcs)", "Acme Glow Serum 30ml (2 EA)",
                      "Acme Glow Serum 30ml x 2 (3pcs)"):
            docs = base_docs([oy_item(title, 20, ship=0)])
            self.assertFalse(self.pos(docs)["verified"])
        qty = strategy.parse_quantity([("title", "Acme Glow Serum 30ml (2pcs)")])
        self.assertEqual(qty["status"], "ambiguous")
        self.assertFalse(strategy.quantity_usable(qty))
        self.assertIn("secondary_count_pack_ambiguous", qty["flags"])

    def test_no_price_status_gate_or_fee_policy_mutation(self):
        docs = self.docs()
        before = deepcopy(docs)
        p = product(build(docs, own_shipping_usd=3), "100")
        docs["oliveyoung_us"]["products"][0]["checkout_quote"]["tax_usd"] = None
        p_unknown = product(build(docs, own_shipping_usd=3), "100")
        for key in ("margin_advisory", "grade", "grade_original", "s_gate_audit", "live_selection_preview"):
            self.assertEqual(p[key], p_unknown[key])
        self.assertEqual(docs["registry"], before["registry"])
        self.assertEqual(docs["pricing_model"], before["pricing_model"])

    def test_production_ingress_never_trusts_self_declared_quote_verification(self):
        docs = self.docs()
        for quote in (docs["registry"]["items"][0]["checkout_quote"],
                      docs["oliveyoung_us"]["products"][0]["checkout_quote"]):
            quote.update(source_verified=True, known=True, verified=True, reviewed=True,
                         status="approved", source_url="https://unrelated.invalid/no-evidence",
                         evidence_sha256="a" * 64)
        # Deliberately bypass the legacy algorithm's explicit synthetic trust
        # fixture and exercise the real production input normalization.
        result = strategy.build_strategy(docs, [], NOW, own_shipping_usd=3)
        item = product(result, "100")
        self.assertFalse(item["own_price"]["checkout_evidence"]["source_verified"])
        self.assertFalse(item["price_position"]["verified"])
        self.assertEqual(item["market"]["tier_counts"]["qualified"], 0)
        self.assertEqual(item["market"]["tier_counts"]["provisional"], 1)
        self.assertEqual(item["priority"]["components"]["verified_price_points"], 0)
        self.assertIn("own_checkout_source_provenance_unverified", item["price_position"]["reasons"])
        self.assertIn("market_checkout_source_provenance_unverified", item["price_position"]["reasons"])

    def test_equal_nonterminating_unit_prices_are_not_below(self):
        docs = self.docs(market_price=20, own_price=17)  # 20/30 has no finite decimal expansion.
        pos = self.pos(docs)
        self.assertEqual(pos["status"], "verified_not_below")
        self.assertFalse(pos["below_lowest"])
        self.assertEqual(pos["gap_pct"], 0)

    def test_equal_incomplete_item_lower_bound_blocks_verified_claim(self):
        docs = self.docs(market_price=30, own_price=17)
        other = oy_item("Acme Glow Serum 30ml", 20, ship=0, product_id="incomplete")
        other["checkout_quote"].pop("tax_usd")
        docs["oliveyoung_us"]["products"].append(other)
        pos = self.pos(docs)
        self.assertFalse(pos["verified"])
        self.assertIn("cheaper_item_price_with_incomplete_checkout", pos["reasons"])


if __name__ == "__main__":
    unittest.main()
