#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline fixture-only regressions; never read or rewrite repository data."""
from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import build_listing_copy_local as listing
import check_slop

FIXTURES = (
    ("VT PDRN 크림 50 ml", "50 ml", "VT PDRN Face Cream 50 ml"),
    ("본셉 레티놀 세럼 30 ml", "30 ml", "VONSEP Retinol Face Serum 30 ml"),
    ("메디필 콜라겐 랩핑 마스크 10 g", "10 g", "MEDI-PEEL Collagen Wrapping Mask 10 g"),
    ("셀더마데일리 히알론 미스트 80 ml", "80 ml", "CELDERMA Daily Hyaluron Face Mist 80 ml"),
)


def product(index=0):
    return {"pd_no": str(index + 1), "name": FIXTURES[index][0], "bucket": "fixture"}


def gate(index=0, ready=True):
    return {"pd_no": str(index + 1), "canonical_product_id": "fixture",
            "agent_ready": ready, "us_label": {"net_contents": FIXTURES[index][1]}}


class ListingCopyLocalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.src, self.gate, self.out = (root / n for n in ("source.json", "gate.json", "copy.json"))
        for attr, value in (("SRC", self.src), ("GATE", self.gate), ("OUT", self.out)):
            p = patch.object(listing, attr, value)
            p.start()
            self.addCleanup(p.stop)

    def run_fixture(self, products=None, gates=None, old=None):
        products = [product()] if products is None else products
        gates = [gate()] if gates is None else gates
        self.src.write_text(json.dumps({"recommendations": products}), encoding="utf-8")
        self.gate.write_text(json.dumps({"items": gates}), encoding="utf-8")
        if old is not None:
            self.out.write_text(json.dumps({"items": old}), encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(listing.main(), 0)
        return json.loads(self.out.read_text(encoding="utf-8"))

    def test_four_distinct_titlefacts_pass_unmodified_slop_gate(self):
        result = self.run_fixture([product(i) for i in range(4)], [gate(i) for i in range(4)])
        # Use production field selection, HTML stripping and tokenization unchanged.
        spec = dict(check_slop.SOURCES[0], path=str(self.out))
        docs = check_slop.collect(spec)
        self.assertEqual(len(docs), 4)
        metrics = check_slop.measure(docs)
        fails, warns = check_slop.judge(metrics)
        self.assertEqual(fails, [], metrics)
        self.assertEqual(metrics["max_dup_docs"], 0, metrics)
        self.assertEqual([r["copy"]["title"] for r in result["items"]], [f[2] for f in FIXTURES])
        print("FIXTURE_SLOP docs=4 avg_overlap=%.4f max_dup_docs=%d warns=%s" %
              (metrics["avg_overlap"], metrics["max_dup_docs"], warns))

    def test_local_copy_is_deterministic_and_does_not_mutate_facts(self):
        facts = gate()
        original = copy.deepcopy(facts)
        a = listing.local_copy(FIXTURES[0][0], facts)
        self.assertEqual(a, listing.local_copy(FIXTURES[0][0], facts))
        self.assertEqual(facts, original)

    def test_repeat_run_preserves_v2_items(self):
        first = self.run_fixture()
        second = self.run_fixture()
        self.assertEqual(first["items"], second["items"])
        self.assertEqual(first["generated_local"], 1)
        self.assertEqual(second["generated_local"], 0)
        self.assertEqual(second["carried_forward"], 1)
        self.assertEqual(second["items"][0]["generation_mode"], listing.LOCAL_MODE)

    def test_only_v1_ok_copy_is_migrated(self):
        old_copy = {"title": "old", "description_html": "old repeated boilerplate"}
        result = self.run_fixture(old=[{"pd_no": "1", "copy_status": "ok", "copy": old_copy,
                                      "generation_mode": listing.LEGACY_LOCAL_MODE}])
        row = result["items"][0]
        self.assertNotEqual(row["copy"], old_copy)
        self.assertEqual(row["copy"], listing.local_copy(FIXTURES[0][0], gate()))
        self.assertEqual(row["generation_mode"], listing.LOCAL_MODE)
        self.assertEqual(result["generated_local"], 1)

    def test_external_manual_and_unmarked_ok_copies_are_preserved(self):
        verified = {"title": "Externally reviewed", "description_html": "<p>Manual copy.</p>",
                    "custom_review_metadata": {"reviewed": True}}
        for mode in ("gemini", "manual_verified", "carried_verified_copy", listing.LOCAL_MODE,
                     "future_external_mode", None):
            with self.subTest(mode=mode):
                old = {"pd_no": "1", "copy_status": "ok", "copy": verified}
                if mode is not None:
                    old["generation_mode"] = mode
                result = self.run_fixture(old=[old])
                self.assertEqual(result["items"][0]["copy"], verified)
                self.assertEqual(result["generated_local"], 0)
                self.assertEqual(result["items"][0]["generation_mode"], mode or "carried_verified_copy")

    def test_skipped_prerequisite_recovers_when_agent_ready(self):
        old = {"pd_no": "1", "copy_status": "skipped_prerequisite", "generation_mode": "none",
               "copy": None, "agent_blocked_by": ["us_label"]}
        result = self.run_fixture(old=[old])
        self.assertEqual(result["items"][0]["copy_status"], "ok")
        self.assertEqual(result["items"][0]["generation_mode"], listing.LOCAL_MODE)
        self.assertEqual(result["items"][0]["agent_blocked_by"], [])

    def test_not_agent_ready_blocks_even_verified_or_v1_copy(self):
        for mode in (listing.LEGACY_LOCAL_MODE, listing.LOCAL_MODE, "manual_verified"):
            with self.subTest(mode=mode):
                blocked = gate(ready=False)
                blocked["agent_blocked_by"] = ["us_label", "legal"]
                old = {"pd_no": "1", "copy_status": "ok", "copy": {"title": "old"},
                       "generation_mode": mode}
                with patch.object(listing, "local_copy", side_effect=AssertionError("blocked generation")):
                    result = self.run_fixture(gates=[blocked], old=[old])
                row = result["items"][0]
                self.assertIsNone(row["copy"])
                self.assertEqual(row["copy_status"], "skipped_prerequisite")
                self.assertEqual(row["generation_mode"], "none")
                self.assertEqual(row["agent_blocked_by"], ["us_label", "legal"])
                self.assertEqual(result["generated_local"], 0)
                self.assertEqual(result["carried_forward"], 0)
                self.assertEqual(result["skipped_prerequisite"], 1)

    def test_missing_gate_is_fail_closed(self):
        with patch.object(listing, "local_copy", side_effect=AssertionError("missing gate")):
            result = self.run_fixture(gates=[])
        row = result["items"][0]
        self.assertEqual(row["agent_blocked_by"], ["ontology_gate_missing"])
        self.assertIsNone(row["copy"])
        self.assertEqual(result["eligible"], 0)

    def test_missing_agent_ready_is_fail_closed(self):
        facts = gate()
        del facts["agent_ready"]
        result = self.run_fixture(gates=[facts])
        self.assertEqual(result["items"][0]["copy_status"], "skipped_prerequisite")
        self.assertIsNone(result["items"][0]["copy"])

    def test_safety_notice_is_product_bound_and_no_new_claims(self):
        for name, volume, title in FIXTURES:
            with self.subTest(name=name):
                value = listing.local_copy(name, {"us_label": {"net_contents": volume}})
                self.assertIn("review " + title, value["description_html"])
                self.assertIn("ingredient list, directions, and final US label", value["description_html"])
                self.assertIn("before publication", value["seo_description"])
                text = json.dumps(value).lower()
                for unsupported in ("korean", "made in", "certified", "clinically", "brightening", "anti-aging"):
                    self.assertNotIn(unsupported, text)

    def test_volume_precedence_and_no_invented_size(self):
        name = "VT PDRN 크림 50 ml"
        self.assertEqual(listing.volume_of({"us_label": {"net_contents": "25 ml"},
                                          "gosi": {"volume": "40 ml"}}, name), "25 ml")
        self.assertEqual(listing.volume_of({"gosi": {"volume": "40 ml"}}, name), "40 ml")
        self.assertEqual(listing.volume_of({}, name), "50 ml")
        no_size = listing.local_copy("VT PDRN 크림", {})
        self.assertNotIn("net contents", no_size["description_html"])
        self.assertNotIn("net contents", no_size["seo_description"])
        self.assertFalse(any(c.isdigit() for c in json.dumps(no_size)))

    def test_unknown_brand_preserves_source_name_without_origin_inference(self):
        value = listing.local_copy("Example Unknown 세럼", {})
        self.assertEqual(value["title"], "Example Unknown 세럼")
        self.assertNotIn("K-Beauty", value["title"])
        self.assertNotIn("korean", json.dumps(value).lower())

    def test_fact_text_is_html_escaped(self):
        value = listing.local_copy("Unknown <b>Name</b> 세럼", {"gosi": {"volume": "10 ml & 2 packs"}})
        self.assertNotIn("<b>", value["description_html"])
        self.assertIn("&lt;b&gt;", value["description_html"])
        self.assertIn("&amp;", value["description_html"])

    def test_identical_facts_are_not_disguised_to_evade_gate(self):
        value = listing.local_copy(FIXTURES[0][0], gate())
        text = check_slop.strip_html(" ".join(value[f] for f in check_slop.SOURCES[0]["fields"]))
        docs = [{"id": str(i), "name": value["title"], "text": text,
                 "w": check_slop.words(text)} for i in range(4)]
        self.assertTrue(check_slop.judge(check_slop.measure(docs))[0])


if __name__ == "__main__":
    unittest.main()
