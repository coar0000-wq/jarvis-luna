#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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
        # Never inherit live credentials, billing evidence or a shared ledger.
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("TYPESAFE_")}
        environment = patch.dict(os.environ, env, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.proof_path = self.root / "proof.json"
        self.ledger_path = self.root / "ledger.json"

    def enable_free_credits(self):
        """Dummy evidence and mocked transport only; never a real credit call."""
        now = datetime.now(timezone.utc)
        proof = {
            "key_sha256": hashlib.sha256(b"dummy-offline").hexdigest(),
            "org_id": "dummy-org", "available_free_usd": 5,
            "auto_recharge": False, "payment_method_on_file": False,
            "verified_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        }
        self.proof_path.write_text(json.dumps(proof), encoding="utf-8")
        os.environ.update(
            TYPESAFE_ENABLED="1", TYPESAFE_FREE_CREDITS_ONLY="1",
            TYPESAFE_API_KEY="dummy-offline", TYPESAFE_ORG_ID="dummy-org",
            TYPESAFE_BILLING_PROOF_PATH=str(self.proof_path),
            TYPESAFE_SHARED_LEDGER_PATH=str(self.ledger_path),
        )

    @staticmethod
    def response():
        return {
            "model": ts.MODEL,
            "answers": {
                "grade_advisory": {"choice": "review", "confidence": 0.8},
                "legal_gate_advisory": {"choice": "review", "confidence": 0.7},
                "risk_level": {"score": 2.0, "confidence": 0.9},
                "team_route": {"choice": "legal", "confidence": 0.85},
                "model_route": {"choice": "human", "confidence": 0.95},
            },
            "usage": {"input_tokens": 100, "output_tokens": 10},
        }

    def test_default_never_calls_network(self):
        with patch.object(ts, "_request", side_effect=AssertionError("network called")) as request:
            result = ts.evaluate(dict(BASE))
        request.assert_not_called()
        self.assertEqual(result["mode"], "disabled_local_advisory")
        self.assertFalse(result["paid_api_called"])
        self.assertEqual(result["grade_advisory"], "keep_s")
        self.assertIn("legal", result["team_routes"])
        self.assertEqual(result["model_route"], "human")

    def test_enabled_without_free_only_guard_stays_local(self):
        os.environ["TYPESAFE_ENABLED"] = "1"
        os.environ["TYPESAFE_API_KEY"] = "dummy-must-not-be-used"
        with patch.object(ts, "_request", side_effect=AssertionError("network called")) as request:
            result = ts.evaluate(dict(BASE))
        request.assert_not_called()
        self.assertEqual(result["mode"], "free_only_required")
        self.assertFalse(result["paid_api_called"])

    def test_paid_override_is_rejected_without_transport(self):
        self.enable_free_credits()
        os.environ["TYPESAFE_ALLOW_PAID"] = "1"
        with patch.object(ts, "_request", side_effect=AssertionError("network called")) as request:
            result = ts.evaluate(dict(BASE))
        request.assert_not_called()
        self.assertEqual(result["mode"], "paid_override_rejected")
        self.assertFalse(result["paid_api_called"])

    def test_missing_billing_proof_stays_local(self):
        self.enable_free_credits()
        self.proof_path.unlink()
        with patch.object(ts, "_request", side_effect=AssertionError("network called")) as request:
            result = ts.evaluate(dict(BASE))
        request.assert_not_called()
        self.assertEqual(result["mode"], "proof_missing_or_invalid")
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
        self.assertEqual(result["model_route"], "human")

    def test_free_credit_mock_is_observational_by_default(self):
        self.enable_free_credits()
        with patch.object(ts, "_request", return_value=self.response()) as request:
            result = ts.evaluate(dict(BASE))
        request.assert_called_once()
        self.assertEqual(result["source"], "typesafe")
        self.assertEqual(result["mode"], "typesafe_observational_free_credits")
        self.assertFalse(result["paid_api_called"])
        self.assertFalse(result["enforced"])
        self.assertEqual(result["risk_level"], "high")
        self.assertEqual(result["model_route"], "human")
        self.assertEqual(result["model_route_confidence"], 0.95)

    def test_incomplete_typed_response_falls_back_locally(self):
        self.enable_free_credits()
        response = self.response()
        del response["answers"]["model_route"]
        with patch.object(ts, "_request", return_value=response) as request:
            result = ts.evaluate(dict(BASE))
        request.assert_called_once()
        self.assertEqual(result["source"], "deterministic_local")
        self.assertEqual(result["mode"], "answer_ids_mismatch")
        self.assertFalse(result["paid_api_called"])
        self.assertEqual(result["model_route"], "human")


if __name__ == "__main__":
    unittest.main()
