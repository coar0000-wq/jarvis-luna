"""Offline assignment preservation; generated feed rows are never work receipts."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_team_feeds as feeds


def briefing(**updates):
    value = {
        "id": "shop-benchmark-design",
        "title": "Shop product image review",
        "date": "2026-10-20",
        "source_url": "https://example.com/product",
        "source_urls": ["https://example.com/product", "https://example.com/policy"],
        "review_path": "docs/learning/benchmark.md",
        "teams": ["design", "listing"],
        "summary": "Review exact SKU images; no publication.",
        "team_actions": {"design": "Check image rights.", "listing": "Check product size.",
                         "pricing": "This team is not assigned."},
        "scope_limits": {"may_publish": False},
    }
    value.update(updates)
    return value


class BriefingFeedTests(unittest.TestCase):
    def test_preflight_runs_all_sales_regressions(self):
        path = Path(__file__).resolve().parents[1] / ".github/workflows/preflight.yml"
        workflow = path.read_text(encoding="utf-8")
        for filename in ("test_beauty_price_strategy.py", "test_checkout_price_evidence.py",
                         "test_team_briefing_feeds.py"):
            command = f'python -B -m unittest discover -s scripts -p "{filename}"'
            self.assertEqual(workflow.count(command), 1)

    def test_source_id_recipient_action_and_evidence_are_preserved(self):
        source = briefing()
        before = deepcopy(source)
        pool = feeds.briefing_rows({"items": [source]})[0]
        design = feeds.team_feed_row(pool, "design")
        listing = feeds.team_feed_row(pool, "listing")
        for row in (design, listing):
            self.assertEqual(row["briefing_id"], source["id"])
            self.assertEqual(row["teams"], source["teams"])
            self.assertEqual(row["scope_limits"], source["scope_limits"])
            self.assertEqual(row["source_urls"], source["source_urls"])
            self.assertEqual(row["review_path"], source["review_path"])
            self.assertEqual(row["url"], source["source_url"])
            self.assertEqual(row["date"], source["date"])
            self.assertTrue(row["by_hand"])
            self.assertNotIn("team_actions", row)
            self.assertNotIn("_team_actions", row)
        self.assertEqual(design["team_action"], "Check image rights.")
        self.assertEqual(listing["team_action"], "Check product size.")
        self.assertEqual(source, before)

    def test_optional_fields_absent_keep_legacy_shape_fields(self):
        source = {"title": "Legacy briefing", "teams": ["knowledge"], "summary": "Review"}
        row = feeds.team_feed_row(feeds.briefing_rows({"items": [source]})[0], "knowledge")
        for key, expected in {"title": source["title"], "teams": source["teams"], "summary": "Review",
                              "url": "", "date": "", "pool": "team_briefing", "by_hand": True}.items():
            self.assertEqual(row[key], expected)
        self.assertNotIn("briefing_id", row)
        self.assertNotIn("team_action", row)
        self.assertEqual(feeds.briefing_rows(None), [])

    def test_claimed_completion_approval_and_permissions_are_not_authority(self):
        source = briefing(status="completed", execution_verified=True, business_approval=True,
                          acknowledged_at="2026-10-20", completed_at="2026-10-20",
                          scope_limits={"may_publish": True, "may_pay": True})
        row = feeds.team_feed_row(feeds.briefing_rows({"items": [source]})[0], "design")
        self.assertEqual(row["status"], "generated_for_review_not_acknowledged")
        self.assertEqual(row["receipt_scope"], "feed_generation_only")
        self.assertFalse(row["execution_verified"])
        self.assertFalse(row["business_approval"])
        self.assertEqual(row["scope_limits_authority"], "source_declaration_only")
        self.assertNotIn("completed_at", row)
        self.assertNotIn("acknowledged_at", row)

    def test_duplicate_ids_fail_and_no_id_legacy_rows_are_allowed(self):
        for second in (briefing(), briefing(title="Conflicting instruction")):
            with self.assertRaisesRegex(ValueError, "duplicate team briefing id"):
                feeds.briefing_rows({"items": [briefing(), second]})
        self.assertEqual(len(feeds.briefing_rows({"items": [
            {"title": "one", "teams": ["design"]}, {"title": "two", "teams": ["design"]}]})), 2)

    def test_team_keys_not_renamed_and_duplicate_recipients_removed(self):
        teams = ["sourcing", "pricing", "design", "listing", "market", "channels", "legal",
                 "robotics", "knowledge", "institutions", "graph", "rea"]
        row = feeds.briefing_rows({"items": [briefing(teams=teams + ["design"])]})[0]
        self.assertEqual(row["teams"], teams)
        self.assertEqual(feeds.briefing_rows({"items": [None, briefing(teams="design")]}), [])

    def test_existing_non_briefing_fields_unchanged(self):
        source = {"title": "News", "url": "https://example.com", "pool": "news",
                  "summary": "News summary", "date": "20 Oct 2026", "status": "original"}
        row = feeds.team_feed_row(source, "market")
        self.assertEqual(row, {**source, "date": "2026-10-20", "by_hand": False})

    def run_pipeline(self, items, output):
        def load(path):
            return {"items": items} if str(path).endswith("manual/team_briefings.json") else {}
        with patch.object(feeds, "load", side_effect=load), \
             patch.object(feeds, "feed_rows", return_value=[]), \
             patch.object(feeds, "collect_fda", return_value=([], [])), \
             patch.object(feeds, "OUT", output), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(feeds.main(), 0)
        return json.loads(output.read_text())

    def test_pipeline_idempotent_assignment_and_legacy_deduplication(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "feed.json"
            items = [briefing(), {"title": "legacy", "teams": ["channels"]},
                     {"title": "legacy", "teams": ["channels"]}]
            first = self.run_pipeline(items, output)
            second = self.run_pipeline(items, output)
            self.assertEqual(first["teams"], second["teams"])
            self.assertEqual(len(first["teams"]["design"]), 1)
            self.assertEqual(len(first["teams"]["listing"]), 1)
            self.assertEqual(len(first["teams"]["channels"]), 1)
            self.assertEqual(first["teams"]["pricing"], [])
            before = output.read_bytes()
            with self.assertRaises(ValueError):
                self.run_pipeline([briefing(), briefing()], output)
            self.assertEqual(output.read_bytes(), before)

    def test_distinct_briefing_ids_with_same_title_url_keep_both_actions(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "feed.json"
            items = [briefing(id="first", teams=["design"], team_actions={"design": "First action"}),
                     briefing(id="second", teams=["design"], team_actions={"design": "Second action"})]
            result = self.run_pipeline(items, output)
            rows = result["teams"]["design"]
            self.assertEqual([r["briefing_id"] for r in rows], ["first", "second"])
            self.assertEqual([r["team_action"] for r in rows], ["First action", "Second action"])

    def test_briefing_id_namespace_cannot_collide_with_legacy_title_url(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "feed.json"
            items = [{"title": "team_briefing", "source_url": "first", "teams": ["design"]},
                     briefing(id="first", teams=["design"], team_actions={"design": "Retain this action"})]
            rows = self.run_pipeline(items, output)["teams"]["design"]
            self.assertEqual(len(rows), 2)
            assigned = [r for r in rows if r.get("briefing_id") == "first"]
            self.assertEqual(len(assigned), 1)
            self.assertEqual(assigned[0]["team_action"], "Retain this action")


if __name__ == "__main__":
    unittest.main()
