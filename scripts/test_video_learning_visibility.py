#!/usr/bin/env python3
"""Fixture-only visibility/provenance tests. No network or real data writes."""
from __future__ import annotations
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_team_learning as learning
import build_team_feeds as feeds
import sync_jarvis_brain as brain


def insight(identifier="new", reviewed_at="2026-10-10T12:30:00Z", **extra):
    return {"id": identifier, "reviewed_at": reviewed_at, "confidence": "high",
            "tactic": "FDA Shopify review", "action": "Review one local fixture before any approval.",
            "teams": ["knowledge"], "prerequisites": ["source verification"],
            "evidence": {"video_id": "fixture-video", "url": "https://www.youtube.com/watch?v=fixture-video&t=120",
                         "timestamp": None, "timestamp_basis": "notebooklm_transcript",
                         "timestamp_status": "not_provided_by_notebooklm", "mapping_verified": True,
                         "chapter_hint": "02:00 uploader chapter", "source_type": "notebooklm_transcript_review",
                         "summary": "Fixture transcript review"}, **extra}


class VideoLearningVisibilityTests(unittest.TestCase):
    def test_newer_review_beats_older_id_at_equal_confidence(self):
        old, new = insight("aaa", "2026-09-28"), insight("zzz", "2026-10-10")
        self.assertEqual(sorted([old, new], key=learning.insight_sort_key), [new, old])
        low = insight("low", "2026-10-11", confidence="low")
        self.assertEqual(sorted([low, old], key=learning.insight_sort_key)[0], old)

    def test_invalid_missing_dates_follow_valid_and_ties_are_stable(self):
        valid = insight("zzz", "2026-01-01")
        items = [insight("a", "9999-99-99"), insight("b", None), insight("c", "2026-02-30"), valid]
        self.assertIs(sorted(items, key=learning.insight_sort_key)[0], valid)
        for bad in (None, "", "zzz", "2026-02-30", 99999):
            self.assertIsNone(learning.reviewed_datetime(bad))
        a, b = insight("a"), insight("b")
        self.assertEqual(sorted([b, a], key=learning.insight_sort_key), [a, b])
        earlier = insight("a", "2026-10-10T12:00:00+09:00")
        later = insight("z", "2026-10-10T04:00:00Z")
        self.assertEqual(sorted([earlier, later], key=learning.insight_sort_key), [later, earlier])

    def test_learning_generator_preserves_item_dates_and_evidence(self):
        new, old, missing = insight("zzz"), insight("aaa", "2026-09-28"), insight("missing", None)
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "manual").mkdir()
            (data / "manual" / "team_youtube_insights.json").write_text(json.dumps({
                "updated_at": "2099-01-01", "videos": [], "insights": [old, missing, new]}), encoding="utf-8")
            out = data / "team_learning.json"
            with patch.object(learning, "DATA", data), patch.object(learning, "OUT", out), contextlib.redirect_stdout(io.StringIO()):
                learning.main()
            doc = json.loads(out.read_text(encoding="utf-8"))
        team = doc["teams"]["knowledge"]
        self.assertEqual(team["this_week_action"]["id"], "zzz")
        self.assertEqual(team["last_review"], new["reviewed_at"])
        item = team["this_week_action"]
        self.assertEqual(item["reviewed_at"], new["reviewed_at"])
        self.assertEqual(item["evidence"], new["evidence"])
        self.assertEqual(item["teams"], ["knowledge"])
        self.assertNotIn("captured_at", item)
        self.assertEqual(item["status"], "shared-review-directive")
        self.assertIsNone(team["items"][-1]["reviewed_at"])

    def test_feed_item_date_timestamp_url_and_declared_routing(self):
        source = {"updated_at": "2099-01-01", "insights": [insight(), insight("missing", None), insight("bad", "2026-02-30")]}
        rows = feeds.insight_rows(source)
        self.assertEqual([r["date"] for r in rows], ["2026-10-10", "", ""])
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            out = data / "feeds.json"
            fixture_load = lambda p: source if p.name == "team_youtube_insights.json" else {}
            with patch.object(feeds, "DATA", data), patch.object(feeds, "OUT", out), patch.object(feeds, "load", fixture_load), patch.object(feeds, "collect_fda", return_value=([], [])), contextlib.redirect_stdout(io.StringIO()):
                feeds.main()
            doc = json.loads(out.read_text(encoding="utf-8"))
        row = doc["teams"]["knowledge"][0]
        self.assertEqual(row["url"], source["insights"][0]["evidence"]["url"])
        self.assertEqual(row["evidence"], source["insights"][0]["evidence"])
        self.assertEqual(row["date"], "2026-10-10")
        self.assertEqual(row["date_basis"], "reviewed_at")
        self.assertEqual(row["teams"], ["knowledge"])
        self.assertEqual(doc["teams"]["legal"], [])
        self.assertEqual(doc["teams"]["design"], [])
        self.assertNotIn("captured_at", row)

    def test_brain_reads_derived_actions_and_source_without_execution_claim(self):
        item = learning.brief(insight(), {})
        item["action"] += " [[Inferred relation]]"
        fixture = {"data/dashboard_runtime.json": {"teams": [
            {"id": "knowledge", "name": "Fixture knowledge", "status": "waiting"},
            {"id": "legal", "name": "Fixture legal", "status": "waiting"}]},
            "data/team_learning.json": {"generated_at": "2099-01-01", "teams": {
                "knowledge": {"items": [item]}, "legal": {"items": [item]}}}}
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            with patch.object(brain, "load", side_effect=lambda rel, default: fixture.get(rel, default)), patch.object(brain, "BRAIN", vault):
                doc = brain.build()
                brain.write_vault(doc)
            note = (vault / "Teams" / "Fixture knowledge.md").read_text(encoding="utf-8")
            legal = (vault / "Teams" / "Fixture legal.md").read_text(encoding="utf-8")
        team = doc["teams"][0]
        self.assertFalse(team["external_team_execution_verified"])
        self.assertFalse(team["video_learning"][0]["business_approval"])
        self.assertEqual(doc["teams"][1]["video_learning"], [])
        self.assertIn("Review one local fixture", note)
        self.assertIn(item["evidence"]["url"], note)
        self.assertIn("타임스탬프: UNKNOWN", note)
        self.assertIn("notebooklm_transcript", note)
        self.assertIn("shared-review-directive", note)
        self.assertIn("외부 도구 실행·검증된 성과·사업 승인 아님", note)
        self.assertNotIn("[[Inferred relation]]", note)
        self.assertNotIn("영상 학습 공유 검토 지시", legal)
        self.assertNotIn("2099-01-01", note)
        self.assertNotIn("captured_at", team["video_learning"][0])

    def test_brain_list_is_bounded_and_requires_declared_membership(self):
        item = learning.brief(insight(), {})
        doc = {"teams": {"knowledge": {"items": [item] * 30 + [{"action": "undeclared"}]}}}
        self.assertEqual(len(brain.team_video_reviews(doc, "knowledge")), 10)
        self.assertEqual(brain.team_video_reviews(doc, "legal"), [])


if __name__ == "__main__":
    unittest.main()
