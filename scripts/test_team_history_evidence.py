"""팀 자기개선 git 이력 근거 테스트 (2026-10-17)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import team_history_evidence as th  # noqa: E402


def pt(date, value, den=None, clock="2026-10-01T00:00:00+00:00", commit="c"):
    return {"date": date, "value": value, "denominator": den, "source_clock": clock, "commit": commit}


class VerdictTest(unittest.TestCase):
    def test_same_source_clock_is_not_refreshed_not_no_change(self):
        v = th.verdict("increase", pt("2026-10-17", 4), pt("2026-10-10", 4))
        self.assertEqual(v["verdict"], "source_not_refreshed")

    def test_direction_aware(self):
        self.assertEqual(th.verdict("increase", pt("b", 5, clock="2"), pt("a", 3, clock="1"))["verdict"], "improved")
        self.assertEqual(th.verdict("decrease", pt("b", 5, clock="2"), pt("a", 3, clock="1"))["verdict"], "worse")

    def test_changed_denominator_uses_ratio(self):
        # 실측: 가격팀 10/10 → 3/7 (대상 S 목록 축소). 개수가 아니라 비율로 판정한다.
        v = th.verdict("increase", pt("b", 3, 7, clock="2"), pt("a", 10, 10, clock="1"))
        self.assertTrue(v["denominator_changed"])
        self.assertEqual(v["verdict"], "worse")
        self.assertEqual(th.verdict("increase", pt("b", 7, 7, clock="2"), pt("a", 9, 10, clock="1"))["verdict"], "improved")

    def test_missing_denominator_is_not_comparable(self):
        v = th.verdict("increase", pt("b", 0, None, clock="2"), pt("a", 9, 9, clock="1"))
        self.assertEqual(v["verdict"], "not_comparable")

    def test_missing_history_is_reported(self):
        self.assertEqual(th.verdict("increase", pt("b", 1), None)["verdict"], "insufficient_history")


class ShallowGuardTest(unittest.TestCase):
    def test_shallow_clone_keeps_existing_file(self):
        with mock.patch.object(th, "git", side_effect=lambda *a: "true\n" if a[0] == "rev-parse" else
                               "2099-01-01T00:00:00+09:00\n"), \
                mock.patch.object(th, "build") as build:
            self.assertEqual(th.main(["--keep-if-shallow", "--output", "/nonexistent/x.json"]), 0)
        build.assert_not_called()


class RealHistoryTest(unittest.TestCase):
    def test_measures_with_same_rules_as_baselines(self):
        doc = th.build(1, "HEAD")
        self.assertEqual(doc["schema_version"], 1)
        for team in doc["teams"].values():
            for p in team["series"]:
                self.assertRegex(p["commit"], r"^[0-9a-f]{40}$")
                self.assertTrue(p["commit_url"].endswith(p["commit"]))


if __name__ == "__main__":
    unittest.main()
