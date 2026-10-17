"""shopify_set_media_alt 오프라인 테스트 (2026-10-17). 네트워크·인증 없이 가짜 클라이언트로 본다."""
import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import shopify_set_media_alt as m  # noqa: E402

MANIFEST = json.loads((HERE.parent / "data/manual/image_localization/1084687.json").read_text(encoding="utf-8"))


class FakeShop:
    def __init__(self, manifest, alts=None, fail_write=False, drop_on_write=False):
        p = m.plan(manifest)
        self.shop = p["shop_id"]
        self.pid = p["product_id"]
        self.nodes = [{"id": t["id"], "mediaContentType": "IMAGE", "status": "READY",
                       "alt": (alts or {}).get(t["file"], ""),
                       "image": {"url": f"https://cdn.shopify.com/s/files/x/{t['file'][:-4]}_800x800.png?v=1"}}
                      for t in p["targets"]]
        self.writes = []
        self.fail_write, self.drop_on_write = fail_write, drop_on_write

    def gql(self, query, variables):
        if "productUpdateMedia" in query:
            self.writes.append(variables)
            if self.fail_write:
                return {"productUpdateMedia": {"mediaUserErrors": [{"message": "x"}]}}
            if not self.drop_on_write:
                by = {x["id"]: x["alt"] for x in variables["media"]}
                for n in self.nodes:
                    n["alt"] = by.get(n["id"], n["alt"])
            return {"productUpdateMedia": {"mediaUserErrors": []}}
        return {"shop": {"id": self.shop},
                "product": {"id": self.pid, "media": {"nodes": copy.deepcopy(self.nodes),
                                                      "pageInfo": {"hasNextPage": False}}}}


class MediaAltTest(unittest.TestCase):
    def test_alt_is_built_from_owner_file_names(self):
        p = m.plan(MANIFEST)
        self.assertEqual(len(p["targets"]), 11)
        self.assertEqual(p["targets"][2]["alt"],
                         "Dr.CPU+ Lacto Exosome Glutathione Capsule Cream — Customize your routine")

    def test_dry_run_reads_only(self):
        shop = FakeShop(MANIFEST)
        r = m.run(shop, MANIFEST, dry_run=True)
        self.assertEqual((r["status"], r["empty_before"], len(r["to_write"])), ("dry_run", 11, 11))
        self.assertEqual(shop.writes, [])

    def test_apply_writes_then_verifies(self):
        shop = FakeShop(MANIFEST)
        self.assertEqual(m.run(shop, MANIFEST, dry_run=False)["status"], "verified")
        self.assertEqual(len(shop.writes), 1)
        self.assertEqual(m.run(shop, MANIFEST, dry_run=False)["status"], "already_set")

    def test_existing_human_alt_is_not_overwritten(self):
        shop = FakeShop(MANIFEST, alts={"01-glutathione-main-en.png": "owner wrote this"})
        r = m.run(shop, MANIFEST, dry_run=False)
        self.assertEqual(r["reason"], "existing_alt_not_overwritten")
        self.assertEqual(shop.writes, [])

    def test_readback_mismatch_and_user_errors_block(self):
        with self.assertRaises(m.Blocked):
            m.run(FakeShop(MANIFEST, drop_on_write=True), MANIFEST, dry_run=False)
        with self.assertRaises(m.Blocked):
            m.run(FakeShop(MANIFEST, fail_write=True), MANIFEST, dry_run=False)

    def test_changed_media_order_blocks_before_write(self):
        shop = FakeShop(MANIFEST)
        shop.nodes.reverse()
        with self.assertRaises(m.Blocked):
            m.run(shop, MANIFEST, dry_run=False)
        self.assertEqual(shop.writes, [])


if __name__ == "__main__":
    unittest.main()
