#!/usr/bin/env python3
"""고시 alt 라벨 파서 회귀 테스트. 외부 호출 없음."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "daiso" / "collect_gosi_alt.py"
spec = importlib.util.spec_from_file_location("collect_gosi_alt", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

sample = """화장품법에 따라 기재·표시하여야 하는 모든 성분(전성분):
정제수, 글리세린, 세라마이드엔피

심사 필 유무(기능성화장품): 해당사항 없음
용량 또는 중량: 23 ml / 0.78 fl. oz.
제조업자 및 책임(제조) 판매업자: (주)메가코스 / 유니레버코리아(주)
제조국: 대한민국
"""
parsed = module.parse_alt(sample)
assert parsed["ingredients"] == "정제수, 글리세린, 세라마이드엔피", parsed
assert parsed["volume"] == "23 ml / 0.78 fl. oz.", parsed
assert parsed["maker"] == "(주)메가코스 / 유니레버코리아(주)", parsed
assert parsed["origin"] == "대한민국", parsed
# 2026-10-17 1072800 실측 형태: "화장품제조업자 및 책임판매업자:" 라벨이 통째로 와야 한다.
cushion = module.parse_alt("화장품제조업자 및 책임판매업자: (주)코스메카코리아 / (주)정샘물뷰티\n제조국: 대한민국")
assert cushion["maker"] == "(주)코스메카코리아 / (주)정샘물뷰티", cushion
class SoapNoticeTests(unittest.TestCase):
    def test_retained_source_hash_and_fields(self):
        fixture = SCRIPT.parents[1].parent / "tests/fixtures/daiso_1033789_supplier_alt.txt"
        metadata = json.loads(fixture.with_suffix(".json").read_text())
        raw = fixture.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), metadata["fixture_sha256"])
        self.assertFalse(metadata["physical_label_verified"])
        self.assertFalse(metadata["safety_approved"])
        fields = module.parse_alt(raw.decode("utf-8"))
        self.assertEqual(fields["maker"], "(주)엘지생활건강")
        self.assertEqual(fields["volume"], "90g (수분포함), 72g (건조시)")
        self.assertEqual(fields["expiry"], "제조일로부터 36개월")
        self.assertNotIn("origin", fields)  # address is not an origin declaration
        self.assertIn("세롤라타벚나무꽃추출물", fields["ingredients"])
        self.assertNotIn("0.1ppm", fields["ingredients"])
        self.assertNotIn("공장", fields["maker"])
        sys.path.insert(0, str(SCRIPT.parents[1]))
        from sync_gosi_to_us_labels import split_ingredients, to_inci
        from inci_resolver import InciResolver
        parts = split_ingredients(fields["ingredients"])
        self.assertEqual(len(parts), 37)
        self.assertIn("1,2-헥산다이올", parts)
        dictionary = json.loads((SCRIPT.parents[1].parent / "data/inci_dictionary.json").read_text())
        inci, missing, fixed, review = to_inci(fields["ingredients"], InciResolver(dictionary["kr_to_inci"]))
        self.assertTrue(inci)
        self.assertEqual(missing, [])
        self.assertEqual(len(fixed), 1)  # existing spelling correction, not source fact
        self.assertIn("세롤라타벚나무꽃추출물", str(fixed))
        self.assertEqual(review, [])
        unresolved, missing, _, _ = to_inci(fields["ingredients"] + ", 미등록시험성분XYZ", InciResolver(dictionary["kr_to_inci"]))
        self.assertEqual(unresolved, "")
        self.assertIn("미등록시험성분XYZ", missing)

    def test_compound_heading_inline_and_multiline_addresses(self):
        for marker in ("공장:", "본사：", "주소:", "소재지:", "(공장)", "(본사):"):
            for separator in (" ", "\n"):
                with self.subTest(marker=marker, separator=separator):
                    fields = module.parse_alt("제조원 및 책임판매원:\n(주)엘지생활건강" + separator + marker + " 울산광역시\n제조국: 대한민국")
                    self.assertEqual(fields["maker"], "(주)엘지생활건강")
                    self.assertEqual(fields["origin"], "대한민국")
        self.assertEqual(module.parse_alt("제조원 및 책임판매원: (주)엘지생활건강")["maker"], "(주)엘지생활건강")

    def test_role_only_missing_and_later_real_maker(self):
        for value in ("및 책임판매원", "제조원 및 책임판매원", "책임판매원", "제조업자 / 책임판매업자", "공장: 서울시"):
            with self.subTest(value=value):
                self.assertEqual(module.clean_maker(value), "")
        fields = module.parse_alt("제조원: 및 책임판매원\n제조원: (주)실제회사")
        self.assertEqual(fields["maker"], "(주)실제회사")
        for raw in ("제조원 및 책임판매원\n\n제조국: 대한민국", "제조원 및 책임판매원"):
            self.assertNotIn("maker", module.parse_alt(raw))

    def test_company_name_and_multiple_companies_not_truncated(self):
        self.assertEqual(module.parse_alt("제조원: (주)공장장코스메틱")["maker"], "(주)공장장코스메틱")
        self.assertEqual(module.parse_alt("제조원 및 책임판매원\n(주)첫회사\n(주)두회사\n본사: 서울시")["maker"], "(주)첫회사 (주)두회사")

    def test_ingredient_alias_only_matches_heading(self):
        for raw in ("성분명: 정제수, 글리세린", "성분명\n정제수, 글리세린"):
            self.assertEqual(module.parse_alt(raw)["ingredients"], "정제수, 글리세린")
        for raw in ("성분명은 원문을 확인하세요", "이 성분명 목록은 예시입니다"):
            self.assertNotIn("ingredients", module.parse_alt(raw))
        fields = module.parse_alt("성분명\n정제수, 글리세린\n제조원 및 책임판매원: (주)엘지생활건강")
        self.assertEqual(fields["ingredients"], "정제수, 글리세린")


if __name__ == "__main__":
    unittest.main()
