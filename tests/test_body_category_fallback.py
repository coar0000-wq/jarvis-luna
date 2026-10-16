"""Pure offline queue tests. No collector, Brain runtime or live commerce calls."""
import copy
import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/body_category_fallback.py"
spec = importlib.util.spec_from_file_location("body_fallback", SCRIPT)
fallback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fallback)
NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def product(identity, **changes):
    pd_no = identity
    return {"pd_no": str(pd_no), "name": "Body wash " + str(pd_no), "price_krw": 3000,
            "rating": 4.5, "review_count": 1, "total_orders": 1, "sold_out": False,
            "small_category": "Body/shower", "small_category_code": fallback.CATEGORY_CODE,
            "url": "https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo=" + str(pd_no),
            "image_url": "https://cdn.daisomall.co.kr/body.jpg", **changes}


def catalog(rows=None, **changes):
    category = {"code": fallback.CATEGORY_CODE, "url": fallback.SOURCE_URL,
                "fetch_status": "ok", "complete": True, "fetched_at": NOW.isoformat(),
                "listing_products": rows if rows is not None else [product(1), product(2)], **changes}
    return {"desks": {"body": {"categories": [category], "products": []}},
            "errors": [], "kept_previous": []}


def category(doc):
    return doc["desks"]["body"]["categories"][0]


class BodyCategoryFallbackTests(unittest.TestCase):
    def setUp(self):
        self.registry = {"items": [], "unrelated": {"preserve": [1, 2, 3]}}

    def run_queue(self, source=None, now=NOW):
        return fallback.prepare_queue(source if source is not None else catalog(), self.registry, now)

    def assert_blocked(self, source=None, **kwargs):
        before = copy.deepcopy(self.registry)
        rows, reason = fallback.prepare_queue(source if source is not None else catalog(),
                                              self.registry, kwargs.pop("now", NOW), **kwargs)
        self.assertEqual(rows, [])
        self.assertIsInstance(reason, str)
        self.assertTrue(reason)
        self.assertEqual(self.registry, before)

    def test_exact_constants_and_source_order_not_sales_sort(self):
        self.assertEqual(fallback.CATEGORY_CODE, "CTGR_01113")
        self.assertEqual(fallback.SOURCE_URL,
                         "https://www.daisomall.co.kr/ds/exhCtgr/C208/CTGR_01050/CTGR_01061/CTGR_01113")
        source = catalog([product(3, total_orders=1, grade="S", shopify_score=100),
                          product(1, total_orders=1000), product(2, total_orders=500)])
        category(source)["products"] = [product(99)]
        source["desks"]["body"]["products"] = [product(1), product(2), product(3)]
        original = copy.deepcopy(source)
        rows, reason = self.run_queue(source)
        self.assertIsNone(reason)
        self.assertEqual([row["pd_no"] for row in rows], ["3", "1", "2"])
        self.assertEqual([row["grade"] for row in rows], ["-"] * 3)
        self.assertEqual([row["_priority"]["source_index"] for row in rows], [0, 1, 2])
        self.assertTrue(all(row["selection_source"] == fallback.SELECTION_SOURCE for row in rows))
        self.assertTrue(all(row["_priority"]["score"] is None for row in rows))
        self.assertNotIn("shopify_score", rows[0])
        self.assertEqual(source, original)
        self.assertEqual(self.registry["unrelated"], {"preserve": [1, 2, 3]})
        self.assertEqual(self.registry["items"], [])

    def test_realistic_mixed_catalog_preserves_snapshot_order_and_audits_skips(self):
        identities = ["PD20261016001" if i == 0 else ("P" + str(1000000 + i) if i % 6 == 0 else str(1000000 + i))
                      for i in range(136)]
        # 21 unsupported IDs, matching the observed catalog mix.
        identities[126] = "1000126"
        identities[132] = "1000132"
        source = catalog([product(identity) for identity in identities])
        original = copy.deepcopy(source)
        rows, reason = self.run_queue(source)
        self.assertIsNone(reason)
        numeric = [identity for identity in identities if identity.isdecimal()]
        self.assertEqual(len(numeric), 115)
        self.assertEqual([r["pd_no"] for r in rows], numeric)
        self.assertEqual([r["_priority"]["source_index"] for r in rows],
                         [i for i, identity in enumerate(identities) if identity.isdecimal()])
        audit = self.registry[fallback.QUEUE_KEY]["unsupported_listing_products"]
        self.assertEqual(len(audit), 21)
        for skipped in audit:
            self.assertEqual(skipped["reason"], "unsupported_alphanumeric_product_id")
            self.assertEqual(identities[skipped["source_index"]], skipped["pd_no"])
            self.assertEqual(skipped["source_url"], fallback.SOURCE_URL)
        self.assertEqual(rows[0]["_priority"]["unsupported_listing_products"], audit)
        self.assertEqual(source, original)
        self.registry["items"] = [{"pd_no": numeric[0], "source": fallback.SELECTION_SOURCE, "status": "DRAFT"}]
        later, reason = self.run_queue(catalog([product("NEW20261016"), product(numeric[1]), product("2000000")]))
        self.assertIsNone(reason)
        self.assertEqual([r["pd_no"] for r in later], [numeric[1], "2000000"])
        self.assertEqual(self.registry[fallback.QUEUE_KEY]["ordered_pd_nos"], numeric + ["2000000"])
        self.registry["items"][0]["status"] = "create_reserved"
        self.assert_blocked(source)

    def test_unsupported_rows_still_require_valid_bindings_and_unique_ids(self):
        self.assert_blocked(catalog([product("P1000001"), product("P1000001")]))
        self.assert_blocked(catalog([product(1), product("P1000001", sold_out="N")]))
        self.assert_blocked(catalog([product("P1000001", url="https://evil.example/?pdNo=P1000001")]))
        for identity in ("P/123", "P 123", "P" * 33, "１２３"):
            self.assert_blocked(catalog([product(identity)]))

    def test_later_reorder_append_refresh_and_absent_rows(self):
        self.run_queue(catalog([product(3), product(1), product(2)]))
        rows, reason = self.run_queue(catalog([product(2, price_krw=2000, name="Fresh"), product(4), product(3)]))
        self.assertIsNone(reason)
        self.assertEqual([row["pd_no"] for row in rows], ["3", "2", "4"])
        self.assertEqual(rows[1]["name"], "Fresh")
        self.assertEqual(rows[1]["price_krw"], 2000)
        self.assertEqual([row["_priority"]["source_index"] for row in rows], [2, 0, 1])
        self.assertEqual(self.registry[fallback.QUEUE_KEY]["ordered_pd_nos"], ["3", "1", "2", "4"])
        rows, _ = self.run_queue(catalog([product(1), product(4), product(3)]))
        self.assertEqual([row["pd_no"] for row in rows], ["3", "1", "4"])

    def test_next_day_progress_registered_deleted_and_reserved_excluded(self):
        self.run_queue(catalog([product(1049275), product(1), product(2), product(3)]))
        self.registry["items"] = [{"pd_no": "1049275", "status": "deleted_by_owner"},
                                  {"pd_no": "1", "source": fallback.SELECTION_SOURCE, "status": "DRAFT"},
                                  {"pd_no": 2, "source": "other", "status": "create_reserved"}]
        before = copy.deepcopy(self.registry["items"])
        tomorrow = NOW + timedelta(days=1)
        source = catalog([product(3), product(2), product(1), product(1049275)], fetched_at=tomorrow.isoformat())
        rows, reason = self.run_queue(source, tomorrow)
        self.assertIsNone(reason)
        self.assertEqual([row["pd_no"] for row in rows], ["3"])
        self.assertEqual(self.registry["items"], before)
        self.assertEqual(self.registry[fallback.QUEUE_KEY]["ordered_pd_nos"], ["1049275", "1", "2", "3"])

    def test_uncertain_own_outcomes_block_without_advancing(self):
        self.run_queue()
        for field in ("source", "selection_source"):
            for status in ("create_reserved", "created_unverified", "quarantine_unverified", "deleted_unverified",
                           "deleted", "unknown", "", None, {}, "draft"):
                with self.subTest(field=field, status=status):
                    self.registry["items"] = [{"pd_no": "1", field: fallback.SELECTION_SOURCE, "status": status}]
                    self.assert_blocked(catalog([product(3)]))

    def test_settled_own_outcomes_consumed(self):
        for status in ("DRAFT", "ACTIVE", "deleted_by_owner", "deleted_verified", "verified_deleted"):
            with self.subTest(status=status):
                self.registry["items"] = [{"pd_no": "1", "source": fallback.SELECTION_SOURCE, "status": status}]
                rows, reason = self.run_queue()
                self.assertIsNone(reason)
                self.assertEqual([row["pd_no"] for row in rows], ["2"])

    def test_stale_future_invalid_or_non_utc_time(self):
        for stamp in ((NOW - timedelta(hours=24, seconds=1)).isoformat(),
                      (NOW + timedelta(microseconds=1)).isoformat(), "bad", None,
                      NOW.replace(tzinfo=None).isoformat(), "2026-10-16T12:00:00+09:00"):
            with self.subTest(stamp=stamp):
                self.assert_blocked(catalog(fetched_at=stamp))
        for stamp in ((NOW - timedelta(hours=24)).isoformat(), NOW.isoformat().replace("+00:00", "Z")):
            self.assertIsNone(self.run_queue(catalog(fetched_at=stamp))[1])

    def test_wrong_category_partial_failed_or_missing_source(self):
        for change in ({"code": "CTGR_99999"}, {"url": fallback.SOURCE_URL + "/"},
                       {"complete": False}, {"complete": 1}, {"fetch_status": "error"},
                       {"listing_products": None}):
            with self.subTest(change=change):
                self.assert_blocked(catalog(**change))
        for key in ("fetched_at", "complete", "fetch_status", "listing_products"):
            source = catalog()
            del category(source)[key]
            self.assert_blocked(source)
        source = catalog()
        source["desks"]["body"]["categories"].append(copy.deepcopy(category(source)))
        self.assert_blocked(source)
        self.assert_blocked({"desks": {}})

    def test_kept_previous_and_relevant_errors_block(self):
        for key, value in (("kept_previous", ["body"]), ("errors", [{"desk": "body"}]),
                           ("errors", [{"code": fallback.CATEGORY_CODE}]),
                           ("errors", [{"url": fallback.SOURCE_URL}]),
                           ("errors", ["body/category failure"])):
            source = catalog()
            source[key] = value
            self.assert_blocked(source)
        source = catalog()
        source["desks"]["body"]["kept_previous_because"] = "failed"
        self.assert_blocked(source)
        source = catalog()
        source["kept_previous"] = ["skincare"]
        source["errors"] = [{"desk": "makeup", "code": "CTGR_OTHER", "error": "failure"}]
        self.assertIsNone(self.run_queue(source)[1])

    def test_malformed_and_duplicate_rows_block_whole_snapshot(self):
        for row in (None, [], {}, product(1, name=""), product(1, pd_no=True),
                    product(1, pd_no=1.0), product(1, pd_no="abc"), product(1, pd_no="01"),
                    product(1, small_category_code="CTGR_OTHER"), product(1, total_orders=True),
                    product(1, sold_out="N"), product(1, rating=float("nan"))):
            with self.subTest(row=row):
                self.assert_blocked(catalog([product(2), row]))
        self.assert_blocked(catalog([product(1), product(1)]))
        self.assert_blocked(catalog([product(1), product(1, pd_no=1)]))

    def test_product_url_must_bind_exact_id_and_host(self):
        for url in ("https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo=2",
                    "https://evil.example/pd/pdr/SCR_PDR_0001?pdNo=1",
                    "http://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo=1",
                    "https://www.daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo=1&pdNo=2", None):
            with self.subTest(url=url):
                self.assert_blocked(catalog([product(1, url=url)]))

    def test_existing_queue_malformed_binding_and_duplicates_do_not_reset(self):
        self.run_queue()
        good = copy.deepcopy(self.registry[fallback.QUEUE_KEY])
        for queue in (None, [], {}, {**good, "schema_version": True},
                      {**good, "category_code": "OTHER"}, {**good, "source_url": "https://evil.example"},
                      {**good, "selection_source": "other"}, {**good, "ordered_pd_nos": ["1", "1"]},
                      {**good, "ordered_pd_nos": [True]}, {**good, "ordered_pd_nos": [1]},
                      {**good, "ordered_pd_nos": "1"}):
            with self.subTest(queue=queue):
                self.registry[fallback.QUEUE_KEY] = queue
                self.assert_blocked(catalog([product(3)]))

    def test_bounded_capacity_fails_without_truncation(self):
        self.run_queue()
        with patch.object(fallback, "MAX_QUEUE_IDS", 2):
            self.assert_blocked(catalog([product(3)]))
        with patch.object(fallback, "MAX_SOURCE_ROWS", 1):
            self.assert_blocked()
        self.assertEqual(self.registry[fallback.QUEUE_KEY]["ordered_pd_nos"], ["1", "2"])

    def test_exhaustion_and_empty_current_snapshot_preserve_history(self):
        self.run_queue()
        self.assertEqual(self.run_queue(catalog([])), ([], None))
        self.assertEqual(self.registry[fallback.QUEUE_KEY]["ordered_pd_nos"], ["1", "2"])
        self.registry["items"] = [{"pd_no": "1"}, {"pd_no": "2"}]
        self.assertEqual(self.run_queue(), ([], None))

    def test_invalid_arguments_and_registry_fail_closed(self):
        for age in (True, 0, -1, float("nan"), float("inf"), "24"):
            self.assert_blocked(max_age_hours=age)
        self.assert_blocked(now=NOW.replace(tzinfo=None))
        for items in (None, {}, [None], [{}], [{"pd_no": False}]):
            self.registry["items"] = items
            self.assert_blocked()


if __name__ == "__main__":
    unittest.main()
