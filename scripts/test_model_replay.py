"""Synthetic unit fixtures only; these do not demonstrate provider performance."""
import copy
import unittest
from evaluate_model_replay import evaluate


def fixture():
    return [{"id": str(i), "source": "unit-test-only", "holdout": True,
             "expected": True, "baseline": True, "candidate": True,
             "baseline_ms": 20, "candidate_ms": 10,
             "baseline_cost": 0, "candidate_cost": 0} for i in range(30)]


class ReplayTests(unittest.TestCase):
    def test_valid_and_zero_cost(self):
        r = evaluate(fixture())
        self.assertTrue(r["eligible_for_review"])
        self.assertIsNone(r["cost_reduction_fraction"])
        self.assertFalse(r["routing_changed"])

    def test_insufficient_and_duplicate(self):
        self.assertFalse(evaluate(fixture()[:29])["eligible_for_review"])
        rows = fixture(); rows[1]["id"] = rows[0]["id"]
        self.assertTrue(evaluate(rows)["errors"])

    def test_missing_and_invalid(self):
        for key, value in [("candidate", None), ("candidate_ms", float("nan")),
                           ("candidate_cost", -1), ("holdout", False), ("source", "")]:
            rows = fixture(); rows[0][key] = value
            self.assertFalse(evaluate(rows)["eligible_for_review"])

    def test_wrong_consensus_and_regression(self):
        rows = fixture(); rows[0]["expected"] = False
        self.assertFalse(evaluate(rows)["eligible_for_review"])
        rows = fixture(); rows[0]["candidate"] = False
        self.assertEqual(evaluate(rows)["regressions"], ["0"])

    def test_order_does_not_change_results(self):
        rows = fixture()
        self.assertEqual(evaluate(rows), evaluate(list(reversed(copy.deepcopy(rows)))))

    def test_boolean_is_not_numeric_label(self):
        rows = fixture(); rows[0]["candidate"] = 1
        self.assertFalse(evaluate(rows)["eligible_for_review"])


if __name__ == "__main__":
    unittest.main()
