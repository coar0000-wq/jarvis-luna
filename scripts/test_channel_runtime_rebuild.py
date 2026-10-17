"""채널 상태가 이전 런타임에 묶이지 않고 원본 수집 파일을 따라가는지 (2026-10-17).

회귀 대상
  1. publish 재생성 경로에서 채널 상태가 10-03 에 멈췄다. 원본은 매일 갱신됐다.
  2. Sephora 보강분(09-15)에 파일 시각(10-16)이 붙어 '오늘 수집 · ok' 로 보일 뻔했다.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load_sync(data_dir: Path):
    spec = importlib.util.spec_from_file_location("_sync_channels_test", ROOT / "sync_channels.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DATA = data_dir
    return mod


class StoreTimeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        (self.data / "manual").mkdir()
        (self.data / "manual" / "us_retail_assist.json").write_text(json.dumps(
            {"captured_at": "2026-09-15T11:19:23.782Z", "sites": {"sephora": {}, "walmart": {}}}),
            encoding="utf-8")
        self.sc = load_sync(self.data)

    def tearDown(self):
        self.tmp.cleanup()

    def test_assisted_store_keeps_assist_time_not_file_time(self):
        doc = {"collected_at": "2026-10-16T23:00:55+00:00", "by_store": {
            "Sephora": {"count": 14, "reason": "차단 · 보강 파일로 채움 (사람, 2026-09-15)"}}}
        self.assertEqual(self.sc._store_at(doc, "Sephora", doc["collected_at"]),
                         "2026-09-15T11:19:23.782Z")

    def test_explicit_store_time_wins(self):
        doc = {"by_store": {"Ulta": {"collected_at": "2026-10-16T23:00:55+00:00"}}}
        self.assertEqual(self.sc._store_at(doc, "Ulta", "x"), "2026-10-16T23:00:55+00:00")

    def test_assisted_without_known_time_is_blank_not_today(self):
        (self.data / "manual" / "us_retail_assist.json").unlink()
        doc = {"by_store": {"Sephora": {"assisted": True}}}
        self.assertEqual(self.sc._store_at(doc, "Sephora", "2026-10-16T23:00:55+00:00"), "")

    def test_directly_collected_store_uses_file_time(self):
        doc = {"by_store": {"Ulta": {"count": 60, "reason": ""}}}
        self.assertEqual(self.sc._store_at(doc, "Ulta", "T"), "T")


class RuntimeRebuildTest(unittest.TestCase):
    def test_runtime_rebuild_reads_sources_not_previous_runtime(self):
        import generate_dashboard_runtime as g
        gl, st = g.rebuild_channels_from_sources()
        self.assertIsInstance(gl, dict)
        self.assertEqual(set(gl), set(st))
        src = json.loads((ROOT / "data" / "amazon_products.json").read_text(encoding="utf-8-sig"))
        src_at = src.get("updated_at") or src.get("collected_at") or src.get("last_updated") or ""
        if src.get("products") or src.get("items"):
            self.assertEqual(st["amazon_best_sellers"]["collected_at"], src_at)
        for v in st.values():
            self.assertNotIn("items", v)

    def test_rebuild_failure_falls_back_to_previous(self):
        import generate_dashboard_runtime as g
        old = g.ROOT
        with tempfile.TemporaryDirectory() as d:
            g.ROOT = Path(d)
            try:
                self.assertEqual(g.rebuild_channels_from_sources(), (None, None))
            finally:
                g.ROOT = old


if __name__ == "__main__":
    unittest.main()
