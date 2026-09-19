#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import typesafe_decision_support as ts


BASE = {
    "canonical_product_id": "CP000001",
    "pd_no": "1000001",
    "name": "테스트 상품",
    "grade": "S",
    "shopify_score": 95,
    "blocked_by": [],
    "public_blocked_by": ["legal_full"],
    "gosi": {"gosi_ok": True},
    "us_label": {"us_label_ok": True},
    "price": {"price_usd": 19.99, "register_blocked": False},
    "legal": {"status": "auto_checked", "hard_block": False},
    "legal_full_complete": False,
}


class TypeSafeDecisionSupportTest(unittest.TestCase):
    def setUp(self):
        for key in (
            "TYPESAFE_ENABLED", "TYPESAFE_ALLOW_PAID", "TYPESAFE_API_KEY",
        ):
            os.environ.pop(key, None)

    def tearDown(self):
        self.setUp()

    def test_default_never_calls_network(self):
        with patch.object(ts, "_request", side_effect=AssertionError("network called")):
            result = ts.evaluate(dict(BASE))
        self.assertEqual(result["mode"], "disabled_local_advisory")
        self.assertFalse(result["paid_api_called"])
        self.assertEqual(result["grade_advisory"], "keep_s")
        self.assertIn("legal", result["team_routes"])

    def test_enabled_without_paid_approval_stays_local(self):
        os.environ["TYPESAFE_ENABLED"] = "1"
        os.environ["TYPESAFE_API_KEY"] = "must-not-be-used"
        with patch.object(ts, "_request", side_effect=AssertionError("network called")):
            result = ts.evaluate(dict(BASE))
        self.assertEqual(result["mode"], "blocked_no_paid_approval")
        self.assertFalse(result["paid_api_called"])

    def test_hard_legal_block_routes_legal_and_holds(self):
        context = dict(BASE)
        context["blocked_by"] = ["legal"]
        context["public_blocked_by"] = ["legal", "legal_full"]
        context["legal"] = {"status": "fail", "hard_block": True}
        result = ts.local_advisory(context)
        self.assertEqual(result["grade_advisory"], "hold")
        self.assertEqual(result["legal_gate_advisory"], "block")
        self.assertEqual(result["risk_level"], "critical")
        self.assertEqual(result["team_routes"][0], "legal")

    def test_paid_path_can_be_mocked_but_is_observational_by_default(self):
        os.environ["TYPESAFE_ENABLED"] = "1"
        os.environ["TYPESAFE_ALLOW_PAID"] = "1"
        os.environ["TYPESAFE_API_KEY"] = "test-key"
        response = {
            "model": "jev-test",
            "answers": {
                "grade_advisory": {"choice": "review", "confidence": 0.8},
                "legal_gate_advisory": {"choice": "review", "confidence": 0.7},
                "risk_level": {"score": 2.0, "confidence": 0.9},
                "team_route": {"choice": "legal", "confidence": 0.85},
            },
            "usage": {"input_tokens": 100, "output_tokens": 10},
        }
        with patch.object(ts, "_request", return_value=response):
            result = ts.evaluate(dict(BASE))
        self.assertEqual(result["source"], "typesafe")
        self.assertEqual(result["mode"], "typesafe_observational")
        self.assertTrue(result["paid_api_called"])
        self.assertFalse(result["enforced"])
        self.assertEqual(result["risk_level"], "high")


if __name__ == "__main__":
    unittest.main()
