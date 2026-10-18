#!/usr/bin/env python3
"""Fixture-only visibility/provenance tests. No network or real data writes."""
from __future__ import annotations
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_team_learning as learning
import build_team_feeds as feeds
import sync_jarvis_brain as brain
import build_public_site as public_site


def insight(identifier="new", reviewed_at="2026-10-10T12:30:00Z", **extra):
    return {"id": identifier, "reviewed_at": reviewed_at, "confidence": "high",
            "tactic": "FDA Shopify review", "action": "Review one local fixture before any approval.",
            "teams": ["knowledge"], "prerequisites": ["source verification"],
            "evidence": {"video_id": "AAAAAAAAAAA", "url": "https://www.youtube.com/watch?v=AAAAAAAAAAA&t=120",
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
            with patch.object(feeds, "DATA", data), patch.object(feeds, "OUT", out), patch.object(feeds, "load", fixture_load), patch.object(feeds, "collect_fda", return_value=([], [])), patch.object(feeds, "feed_rows", return_value=[]), contextlib.redirect_stdout(io.StringIO()):
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


class PublicVideoLearningVisibilityTests(unittest.TestCase):
    def fixture(self):
        item = insight()
        item.update(status="shared-review-directive", business_approval=True,
                    execution_authority={"may_execute": True}, captured_at="2099-01-01",
                    manual_source={"raw": "PRIVATE_MANUAL"},
                    notebook_url="https://notebooklm.google.com/notebook/PRIVATE")
        return {"status": "reviewed", "insights": 2, "videos_available": 4,
                "this_week_action": item, "raw_source": {"private": True}}

    def render(self, value):
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        function = "function renderTeamVideoReview(" + html.split("function renderTeamVideoReview(", 1)[1].split("function renderTeams(", 1)[0]
        node = shutil.which("node") or shutil.which("node.cmd")
        self.assertIsNotNone(node, "Node is required for fixture renderer tests")
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "review.cjs"
            script.write_text(function + '\nconst input=JSON.parse(require("fs").readFileSync(0,"utf8"));process.stdout.write(renderTeamVideoReview(input));', encoding="utf-8")
            return subprocess.run([node, str(script)], input=json.dumps(value), text=True,
                                  encoding="utf-8", capture_output=True, check=True, timeout=15).stdout

    def test_public_schema_drops_private_sources_and_authority(self):
        fixture = {"teams": [{"id": "knowledge", "youtube_learning": self.fixture()}]}
        doc = public_site.project(fixture, public_site.SCHEMAS["data/dashboard_runtime.json"])
        view = doc["teams"][0]["youtube_learning"]
        self.assertEqual(set(view), {"status", "insights", "videos_available", "this_week_action"})
        item = view["this_week_action"]
        self.assertEqual(set(item), {"id", "tactic", "action", "reviewed_at", "status", "evidence"})
        self.assertEqual(set(item["evidence"]), {"url", "timestamp", "timestamp_status", "timestamp_basis"})
        self.assertIsNone(item["evidence"]["timestamp"])
        self.assertEqual(item["evidence"]["timestamp_status"], "not_provided_by_notebooklm")
        self.assertEqual(item["reviewed_at"], "2026-10-10T12:30:00Z")
        for private in ("PRIVATE", '"business_approval"', '"execution_authority"', "chapter_hint", "source_type", "mapping_verified"):
            self.assertNotIn(private, json.dumps(doc))
        item["action"] = "x" * 900
        self.assertEqual(len(public_site.project(view, public_site.YOUTUBE_LEARNING)["this_week_action"]["action"]), 600)

    def test_public_schema_rejects_nested_values_and_private_text(self):
        value = self.fixture()
        value.update(status={"raw": "private"}, insights=[1], videos_available=-1)
        value["this_week_action"].update(action={"raw": "private"}, tactic="https://notebooklm.google.com/notebook/PRIVATE")
        result = public_site.project(value, public_site.YOUTUBE_LEARNING)
        for field in ("status", "insights", "videos_available"):
            self.assertIsNone(result[field])
        self.assertIsNone(result["this_week_action"]["action"])
        self.assertIsNone(result["this_week_action"]["tactic"])

    def test_renderer_escapes_html_uses_review_date_and_unknown_timestamp(self):
        value = self.fixture()
        value["this_week_action"].update(tactic='<script>alert("x")</script>', action='<img src=x onerror="evil()">' + "x" * 900)
        html = self.render(value)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;img", html)
        self.assertNotIn("<script", html)
        self.assertNotIn("<img", html)
        self.assertNotIn("x" * 601, html)
        self.assertIn("검토일: 2026-10-10T12:30:00Z", html)
        self.assertIn("타임스탬프: 미확인 (UNKNOWN)", html)
        self.assertIn("공유된 검토 과제, 실행 완료·성과·승인 증명 아님", html)
        self.assertIn("https://www.youtube.com/watch?v=AAAAAAAAAAA", html)
        for private in ("02:00", "2099-01-01", "PRIVATE", "notebooklm.google.com", "chapter_hint"):
            self.assertNotIn(private, html)

    def test_projection_and_renderer_reject_unsafe_source_urls(self):
        for url in ("javascript:alert(1)", "http://youtube.com/watch?v=x", "https://youtube.com.evil.test/x",
                    "https://evilyoutube.com/x", "https://user:secret@youtube.com/x", "https://@youtube.com/x",
                    "https://youtube.com:444/x", "https://notebooklm.google.com/x", "https://%79outube.com/x",
                    "https://youtube.com\\@evil.test/x", "https://youtube.com/\nunsafe", "https://youtube.com/redirect?q=https://example.test",
                    "https://youtube.com/watch?v=short", "https://youtube.com/watch?v=AAAAAAAAAAA&v=BBBBBBBBBBB",
                    "https://youtu.be/AAAAAAAAAAA/extra", "https://youtube.com/@channel"):
            with self.subTest(url=url):
                self.assertIsNone(public_site.public_youtube_url(url))
                value = self.fixture()
                value["this_week_action"]["evidence"]["url"] = url
                self.assertNotIn("href=", self.render(value))
        for url in ("https://youtube.com/watch?v=AAAAAAAAAAA&t=120&token=PRIVATE",
                    "https://www.youtube.com/watch?v=AAAAAAAAAAA", "https://youtu.be/AAAAAAAAAAA?si=PRIVATE",
                    "https://www.youtube.com/shorts/AAAAAAAAAAA#PRIVATE"):
            with self.subTest(url=url):
                self.assertEqual(public_site.public_youtube_url(url), "https://www.youtube.com/watch?v=AAAAAAAAAAA")
                value = self.fixture()
                value["this_week_action"]["evidence"]["url"] = url
                self.assertIn('href="https://www.youtube.com/watch?v=AAAAAAAAAAA"', self.render(value))
                self.assertNotIn('PRIVATE', self.render(value))

    def test_nested_source_is_not_a_fallback_and_unreviewed_is_hidden(self):
        value = self.fixture()
        item = value["this_week_action"]
        item["evidence"] = {"timestamp": None, "chapter_hint": "02:00", "source": {"url": "https://youtu.be/private"}}
        item["source"] = {"url": "https://youtu.be/private"}
        html = self.render(value)
        self.assertNotIn("href=", html)
        self.assertNotIn("private", html)
        self.assertNotIn("02:00", html)
        self.assertIn("UNKNOWN", html)
        item["status"] = "executed"
        self.assertEqual(self.render(value), "")
        self.assertEqual(self.render(None), "")


if __name__ == "__main__":
    unittest.main()
