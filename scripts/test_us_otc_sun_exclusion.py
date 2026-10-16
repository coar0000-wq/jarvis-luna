#!/usr/bin/env python3
"""선케어 제외: 이름에 SPF 가 없어도 고시 기능성·사용자 확인 목록으로 걸러야 한다 (2026-10-16 회귀)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from daiso import score_shopify_demand as s  # noqa: E402


class SunExclusionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.cfg, self.gosi = root / "ex.json", root / "gosi.json"
        self.cfg.write_text(json.dumps({"items": [{"pd_no": "1068733", "kind": "otc_drug", "reason": "SPF50+"}]}), encoding="utf-8")
        self.gosi.write_text(json.dumps({"items": {
            "900": {"functional": "미백 / 자외선차단(SPF50+, PA++++)"},
            "901": {"functional": "해당 없음", "usage": "사용 후 자외선 차단제를 함께 바르세요"},
        }}), encoding="utf-8")
        self.saved = (s.US_OTC_EXCLUSIONS, s.GOSI_PATH, s._SUN_EVIDENCE)
        s.US_OTC_EXCLUSIONS, s.GOSI_PATH, s._SUN_EVIDENCE = self.cfg, self.gosi, None

    def tearDown(self):
        s.US_OTC_EXCLUSIONS, s.GOSI_PATH, s._SUN_EVIDENCE = self.saved
        self.tmp.cleanup()

    def test_confirmed_list_blocks_pact_without_spf_in_name(self):
        self.assertEqual(s.us_blockers("[21호]클리덤 리포좀 비타민C 기미 앰플 밤 팩트 10 g", "1068733")[0], "otc_drug")

    def test_gosi_functional_blocks(self):
        self.assertEqual(s.us_blockers("어떤 톤업 크림", "900")[0], "otc_drug")

    def test_usage_mentioning_sunscreen_does_not_block(self):
        self.assertEqual(s.us_blockers("레티놀 세럼", "901")[0], "")

    def test_name_rule_still_works_without_pd_no(self):
        self.assertEqual(s.us_blockers("선쿠션 SPF50")[0], "otc_drug")
        self.assertEqual(s.us_blockers("수분 크림")[0], "")

    def test_s_gate_rejects(self):
        ok, rule = s.qualify_s("앰플 밤 팩트", "스킨케어", 95, [], False, "1068733")
        self.assertEqual((ok, rule), (False, "otc_drug"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
