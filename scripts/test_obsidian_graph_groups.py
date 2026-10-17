"""옵시디언 그래프 색 그룹 회귀 테스트 (2026-10-17).

전: 흰 점 5 + 회색 그룹 247 (Personal 105, Personal/Claude 142), 최대 그룹 257 (Concepts).
후: 흰 점 0, 회색·파스텔 0, 최대 그룹 59.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import obsidian_graph_groups as g  # noqa: E402


class ParserTest(unittest.TestCase):
    def note(self, path, text=""):
        return {"path": path.lower(), "rel": path, "name": Path(path).stem.lower(),
                "text": text.lower(), "tags": set()}

    def test_and_or_not_and_quotes(self):
        e = g.parse('path:Personal (file:"AI Models" OR "다이소") -path:Personal/templates')
        self.assertTrue(g.match(e, self.note("Personal/AI Models.md")))
        self.assertTrue(g.match(e, self.note("Personal/x.md", "다이소 상품")))
        self.assertFalse(g.match(e, self.note("Personal/templates/AI Models.md")))
        self.assertFalse(g.match(e, self.note("Concepts/AI Models.md")))

    def test_pale_colors_are_flagged(self):
        self.assertTrue(g.low_contrast(0x757575))   # 이전 path:Personal 회색
        self.assertTrue(g.low_contrast(0x90A4AE))   # 이전 path:Personal/Claude
        self.assertFalse(g.low_contrast(0xFF4081))


class VaultTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = g.measure()

    def test_no_white_nodes(self):
        self.assertEqual(self.r["white"], 0, self.r["white_notes"])

    def test_no_pale_or_empty_groups(self):
        self.assertEqual(self.r["pale_groups"], [])
        self.assertEqual(self.r["empty_groups"], [])

    def test_groups_are_balanced(self):
        # 전에는 Concepts 하나가 257개였다.
        self.assertLessEqual(self.r["largest_group"], 80, self.r["groups"])

    def test_saved_graph_json_leaves_no_white_nodes(self):
        # 정확히 같을 필요는 없다 (개념 노트가 늘면 목록이 바뀐다). 그러나 실제로
        # 옵시디언이 읽는 graph.json 으로 칠했을 때 흰 점·흐린 색이 없어야 한다.
        saved = json.loads(g.GRAPH.read_text(encoding="utf-8"))
        self.assertEqual(saved["search"], g.SEARCH)
        groups = [(c["query"][:40], c["query"], c["color"]["rgb"]) for c in saved["colorGroups"]]
        r = g.measure(groups=groups)
        self.assertEqual(r["white"], 0,
                         f"{r['white_notes']} — python scripts/obsidian_graph_groups.py --write")
        self.assertEqual(r["pale_groups"], [])


if __name__ == "__main__":
    unittest.main()
