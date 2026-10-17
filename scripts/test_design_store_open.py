"""디자인팀 '스토어 개설' 단계를 등록 장부의 실제 Shopify 상품 ID 로 판정한다 (2026-10-17).

전: check None 이라 스토어가 열려 있어도 '대기 · 다음 단계: Shopify 스토어 개설'.
후: 장부에 gid://shopify/Product/ 가 ACTIVE/DRAFT 로 있으면 완료, 없으면 대기.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_design_team as b  # noqa: E402


class StoreOpenTest(unittest.TestCase):
    def run_with(self, items):
        old = b.DATA
        with tempfile.TemporaryDirectory() as d:
            b.DATA = Path(d)
            try:
                if items is not None:
                    (Path(d) / "shopify_daily_registry.json").write_text(
                        json.dumps({"items": items}), encoding="utf-8")
                return b.store_open_evidence()
            finally:
                b.DATA = old

    def test_real_product_ids_prove_store_open(self):
        ev = self.run_with([
            {"status": "ACTIVE", "shopify_id": "gid://shopify/Product/1"},
            {"status": "DRAFT", "shopify_id": "gid://shopify/Product/2"},
            {"status": "deleted_by_owner", "shopify_id": "gid://shopify/Product/3"},
        ])
        self.assertIn("2건", ev)
        self.assertIn("ACTIVE 1", ev)

    def test_no_registry_or_no_ids_is_not_done(self):
        self.assertIsNone(self.run_with(None))
        self.assertIsNone(self.run_with([{"status": "DRAFT", "shopify_id": ""}]))
        self.assertIsNone(self.run_with([{"status": "deleted_by_owner",
                                          "shopify_id": "gid://shopify/Product/9"}]))

    def test_settings_step_stays_pending_without_evidence(self):
        steps, _ = b.build_steps({})
        by = {s["id"]: s for s in steps}
        self.assertIn("store-settings", by)
        self.assertEqual(by["store-settings"]["status"], "대기")


if __name__ == "__main__":
    unittest.main()
