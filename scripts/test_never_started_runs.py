#!/usr/bin/env python3
"""Only runs GitHub cancelled before creating any job are skipped for safety continuity."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from scripts import restore_source_safety as src  # noqa: E402
from scripts import restore_operations_safety as ops  # noqa: E402

RUN = {"id": 7, "run_attempt": 1, "status": "completed", "conclusion": "cancelled"}


def jobs(payload):
    seen = []

    def fetch(url):
        seen.append(url)
        return payload
    return fetch, seen


class NeverStartedTests(unittest.TestCase):
    def test_zero_job_cancelled_run_is_skipped(self):
        for module in (src, ops):
            fetch, seen = jobs({"total_count": 0, "jobs": []})
            self.assertTrue(module.never_started(RUN, fetch, module.BASE))
            self.assertEqual(seen, [module.BASE + "runs/7/attempts/1/jobs?per_page=100"])

    def test_cancelled_run_with_any_job_is_kept(self):
        for module in (src, ops):
            fetch, _ = jobs({"total_count": 1, "jobs": [{"id": 1}]})
            self.assertFalse(module.never_started(RUN, fetch, module.BASE))

    def test_failed_or_successful_runs_never_query_and_are_kept(self):
        for module in (src, ops):
            for conclusion in ("failure", "success", "skipped", None):
                fetch, seen = jobs({"total_count": 0, "jobs": []})
                self.assertFalse(module.never_started(dict(RUN, conclusion=conclusion), fetch, module.BASE))
                self.assertEqual(seen, [])

    def test_malformed_jobs_response_is_kept(self):
        for module in (src, ops):
            for payload in (None, [], {"total_count": 0}, {"jobs": []}, {"total_count": "0", "jobs": []}):
                fetch, _ = jobs(payload)
                self.assertFalse(module.never_started(RUN, fetch, module.BASE))


if __name__ == "__main__":
    unittest.main(verbosity=1)
