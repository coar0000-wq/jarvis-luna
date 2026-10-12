#!/usr/bin/env python3
"""Offline fee regression tests: python -B -m unittest discover -s scripts -p test_payment_fees.py -v."""
from decimal import Decimal
from pathlib import Path
import unittest

import payment_fees as fees
import pricing_model as pm
import build_beauty_price_strategy as bps
from test_beauty_price_strategy import base_docs, build, product


class PaymentFeeTests(unittest.TestCase):
    def test_explicit_component_source_rate_and_fixed(self):
        basis = fees.payment_cost_basis()
        self.assertEqual((pm.PAY_RATE, pm.PAY_FIXED), (0.02, 0.0))
        self.assertEqual(pm.PAY_NOTE, fees.PAYMENT_FEE_NOTE)
        self.assertEqual(basis["payment_fee_source"], "user instruction2026-10-11")
        self.assertEqual(basis["payment_fee_rate"], 0.02)
        self.assertEqual(basis["payment_fee_fixed_usd"], 0.0)
        self.assertNotIn("observed_at", basis)

    def test_direct_fee_cases(self):
        for sale, expected in [(0, "0.00"), (1, "0.02"), (10, "0.20"), (100, "2.00"), (23.99, "0.48")]:
            with self.subTest(sale=sale):
                self.assertEqual(fees.payment_fee_usd(sale), Decimal(expected))
        for invalid in [-1, float("nan"), float("inf")]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                fees.payment_fee_usd(invalid)

    def test_unknown_supplemental_fees_not_counted(self):
        basis = fees.payment_cost_basis()
        components = basis["payment_fee_components"]
        included = [c for c in components if c["included"]]
        self.assertEqual(len(included), 1)
        self.assertEqual(sum(c["rate"] for c in included), 0.02)
        unknown = [c for c in components if c["status"] == "UNKNOWN"]
        self.assertEqual({c["name"] for c in unknown}, set(fees.UNKNOWN_SUPPLEMENTAL_FEES))
        self.assertTrue(all(c["rate"] is None and c["fixed_usd"] is None and c["source"] is None for c in unknown))
        self.assertTrue(basis["has_unknown_fees"])
        self.assertFalse(basis["full_profit_verified"])
        self.assertEqual(set(basis["unknown_fees"]), set(fees.UNKNOWN_SUPPLEMENTAL_FEES))
        basis["unknown_fees"].clear()
        self.assertTrue(fees.payment_cost_basis()["unknown_fees"])

    def test_numeric_rate_preferred_without_double_count(self):
        basis = fees.payment_cost_basis()
        basis["payment_fee"] = "legacy 3.9% + 3.5% = 7.4%"
        model = {"cost_basis": basis}
        rate = bps._fee_rate(model)
        self.assertEqual(rate, Decimal("0.02"))
        margin = bps.margin_scenario(10, 8, rate)
        self.assertEqual(margin["fee_usd"], 0.20)
        self.assertEqual(margin["net_profit_usd"], 1.80)
        self.assertEqual(margin["margin_pct"], 18.0)
        self.assertFalse(margin["full_profit_verified"])

    def test_legacy_equals_percent_parser_compatible(self):
        for note, expected in [("Shopify 3.9% + 3.5% = 7.4%", Decimal("0.074")),
                               ("card = 2%", Decimal("0.02")), ("card = 0%", Decimal("0"))]:
            self.assertEqual(bps._fee_rate({"cost_basis": {"payment_fee": note}}), expected)
        self.assertIsNone(bps._fee_rate({"cost_basis": {"payment_fee": "UNKNOWN"}}))
        self.assertIsNone(bps._fee_rate({}))

    def test_invalid_numeric_does_not_revive_stale_legacy_rate(self):
        for value in [None, True, -0.02, 1, float("nan"), float("inf"), "0.02"]:
            with self.subTest(value=value):
                self.assertIsNone(bps._fee_rate({"cost_basis": {"payment_fee_rate": value, "payment_fee": "old = 7.4%"}}))
        self.assertEqual(bps._fee_rate({"cost_basis": {"payment_fee_rate": 0}}), Decimal("0"))

    def test_pricing_advisory_charges_card_once_and_never_blocks(self):
        policy = {"price_policy": {"margin_advisory": {"target_margin": 0.40, "minimum_margin": 0.30,
                                                          "estimated_weight_extra_margin": 0.05}}}
        advisory = pm.profitability_advisory(10, 8, strategy=policy)
        self.assertEqual(advisory["net_profit_usd"], 1.8)
        self.assertEqual(advisory["margin_pct"], 18.0)
        self.assertFalse(advisory["blocks_registration"])
        self.assertTrue(advisory["has_unknown_fees"])
        self.assertFalse(advisory["full_profit_verified"])
        loss = pm.profitability_advisory(10, 11, strategy=policy)
        self.assertEqual(loss["status"], "loss")
        self.assertFalse(loss["blocks_registration"])

    def test_strategy_report_keeps_unknowns_and_nonblocking_margin(self):
        docs = base_docs(own_price=10)
        docs["pricing_model"]["cost_basis"] = fees.payment_cost_basis()
        report = build(docs)
        self.assertEqual(report["parameters"]["payment_fee_rate"], 0.02)
        self.assertEqual(report["parameters"]["payment_fee_components"], fees.payment_cost_basis()["payment_fee_components"])
        self.assertTrue(report["parameters"]["has_unknown_fees"])
        self.assertFalse(report["parameters"]["full_profit_verified"])
        self.assertTrue(any("Supplemental Shopify" in u and "UNKNOWN" in u for u in report["unknowns"]))
        advisory = product(report, "100")["margin_advisory"]
        self.assertFalse(advisory["blocking"])
        self.assertEqual(advisory["scenarios"]["ship_1_unit_order"]["fee_usd"], 0.20)
        self.assertFalse(advisory["full_profit_verified"])

    def test_daily_uses_shared_pricing_advisory_no_duplicate_fee(self):
        daily = (Path(__file__).parent / "daiso_daily_beauty_to_shopify.py").read_text(encoding="utf-8")
        self.assertIn("import pricing_model as pm", daily)
        self.assertIn("pm.profitability_advisory(single, landed1", daily)
        self.assertIn("pm.profitability_advisory(pack, landed2", daily)
        self.assertNotIn("0.074", daily)
        model = (Path(__file__).parent / "pricing_model.py").read_text(encoding="utf-8")
        self.assertIn('"cost_basis": {', model)
        self.assertIn("**payment_cost_basis(),", model)


if __name__ == "__main__":
    unittest.main()
