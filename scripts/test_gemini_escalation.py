#!/usr/bin/env python3
from __future__ import annotations

import unittest
from unittest.mock import patch

import gemini_escalation as ge


class GeminiEscalationTest(unittest.TestCase):
    def docs(self, parse_other: bool = False, repeated: bool = False):
        return {
            "ops_plan.json": {"risk": "low", "tasks": []},
            "collector_audit.json": {
                "failure_types": ([{"type": "parse_other", "pd_no": "x"}]
                                  if parse_other else [])
            },
            "signal_audit.json": {"empty_or_failed": []},
            "remediation_state.json": {
                "issues": {
                    "human": {
                        "classification": "human_approval_required",
                        "detected_runs": 5,
                        "resolved_at": None,
                    },
                    **({
                        "auto": {
                            "classification": "revalidate_only",
                            "detected_runs": 3,
                            "resolved_at": None,
                            "key": "auto",
                        }
                    } if repeated else {}),
                }
            },
            "typesafe_advisory.json": {"items": {}},
        }

    def reasons(self, docs):
        def fake_load(path, default):
            return docs.get(path.name, default)
        with patch.object(ge, "load", side_effect=fake_load):
            return ge.insufficiency_reasons()[0]

    def test_human_only_does_not_call_gemini(self):
        self.assertEqual(self.reasons(self.docs()), [])

    def test_unclassified_parser_failure_escalates(self):
        self.assertIn("unclassified_parse_failures=1",
                      self.reasons(self.docs(parse_other=True)))

    def test_repeated_revalidation_escalates(self):
        self.assertIn("repeated_unresolved_auto_issues=1",
                      self.reasons(self.docs(repeated=True)))


if __name__ == "__main__":
    unittest.main()
