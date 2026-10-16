#!/usr/bin/env python3
"""메이크업 실시간 랭킹 대체: 메이크업 전용·하루 1개·비공개 초안·선케어 차단 (2026-10-16)."""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import daiso_daily_beauty_to_shopify as d  # noqa: E402
import pricing_model  # noqa: E402

MAKEUP = next(c for c in d.CATEGORIES if c[0] == "makeup")
SKIN = next(c for c in d.CATEGORIES if c[0] == "skincare")


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.doc = copy.deepcopy(pricing_model.load_commerce_strategy())
        self.doc.pop("_sha256", None)

    def bad(self, **change):
        doc = copy.deepcopy(self.doc)
        doc["makeup_ranking_fallback"].update(change)
        with self.assertRaises(ValueError):
            pricing_model.validate_strategy(doc)

    def test_current_policy_is_valid_and_s_only_stays(self):
        pricing_model.validate_strategy(self.doc)
        self.assertEqual(self.doc["grade_policy"]["allowed_grades"], ["S"])
        self.assertIs(self.doc["grade_policy"]["lower_grade_fallback"], False)

    def test_unsafe_values_rejected(self):
        self.bad(category="skincare")
        self.bad(status="ACTIVE")
        self.bad(public_sale_authorized=True)
        self.bad(max_per_day=2)
        self.bad(trigger="always")
        self.bad(api_url="https://example.com/ranking")

    def test_only_makeup(self):
        self.assertTrue(d.ranking_enabled(MAKEUP))
        self.assertFalse(d.ranking_enabled(SKIN))


class SafetyTests(unittest.TestCase):
    def test_base_makeup_without_ingredients_blocked(self):
        self.assertEqual(d._ranking_regulated("후시덤 베리어 리페어 비비크림 40 ml", "999001", {}),
                         "spf_unverified_base_makeup")
        self.assertEqual(d._ranking_regulated("밀착 쿠션 21호", "999002", {"ingredients": ""}),
                         "spf_unverified_base_makeup")

    def test_uv_filter_ingredient_blocked(self):
        g = {"ingredients": "정제수, 에칠헥실메톡시신나메이트, 글리세린"}
        self.assertTrue(d._ranking_regulated("톤업 크림", "999003", g).startswith("uv_filter_in_ingredients"))

    def test_functional_sun_blocked(self):
        g = {"ingredients": "정제수", "functional": "자외선차단(SPF50+, PA++++)"}
        self.assertEqual(d._ranking_regulated("컨실러", "999004", g), "regulated_functional_or_name")

    def test_plain_makeup_allowed(self):
        self.assertIsNone(d._ranking_regulated("드롭비 컬러즈 커버픽 컨실러 클리어 베이지", "999005",
                                               {"ingredients": "정제수, 사이클로펜타실록세인, 티타늄디옥사이드"}))

    def test_base_makeup_with_clean_ingredients_allowed(self):
        self.assertIsNone(d._ranking_regulated("세범 다운 쿠션", "999006",
                                               {"ingredients": "정제수, 다이메티콘, 실리카", "functional": "해당 없음"}))

    def test_draft_allowed_only_for_ranking_source(self):
        self.assertTrue(d.draft_allowed({"pdNo": "999007", "_source": d.RANKING_SOURCE}))
        self.assertFalse(d.draft_allowed({"pdNo": "999007", "_source": "jarvis_s_list"}))


if __name__ == "__main__":
    unittest.main(verbosity=1)
