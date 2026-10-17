"""Offline category-order/completeness tests. No network or inventory writes."""
import contextlib
import copy
import importlib.util
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "collect_desk_catalog_order_under_test", ROOT / "scripts/daiso/collect_desk_catalog.py")
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)

CODE = "CTGR_01113"
URL = "https://www.daisomall.co.kr/ds/exhCtgr/C208/CTGR_01050/CTGR_01061/CTGR_01113"
CATEGORY = {"code": CODE, "middle": "CTGR_01061", "name": "샤워/입욕", "url": URL}
CFG = {"body": {"name": "바디 전담팀", "source": "offline fixture", "categories": [CATEGORY]}}


def product(number, orders=0, reviews=0, **extra):
    return {"pdNo": str(number), "pdNm": "original " + str(number), "pdPrc": "3,000",
            "avgStscVal": "4.25", "revwCnt": str(reviews), "totOrQy": str(orders),
            "exhSmallCtgrNm": "source category", "exhSmallCtgrNo": "SOURCE_CHILD",
            "soldOutYn": "N", "pdImgUrl": "/original.jpg", **extra}


def payload(total, docs):
    return {"resultSet": {"result": [{"totalSize": total, "resultDocuments": docs}]}}


def ids(rows):
    return [r["pd_no"] for r in rows]


class CategoryOrderTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(collector.urllib.request, "urlopen",
                             side_effect=AssertionError("network forbidden"))
        guard.start()
        self.addCleanup(guard.stop)
        sleeper = patch.object(collector.time, "sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def collect(self, responses, cfg=None, max_pages=3, per_page=2):
        with patch.object(collector, "fetch", side_effect=responses) as fetcher, \
                patch.object(collector, "MAX_PAGES", max_pages), \
                patch.object(collector, "PER_PAGE", per_page):
            result = collector.collect(copy.deepcopy(CFG if cfg is None else cfg))
        return result, fetcher

    def category(self, result):
        return result["desks"]["body"]["categories"][0]

    def assert_incomplete(self, result):
        category = self.category(result)
        self.assertIs(category["complete"], False)
        self.assertNotEqual(category["fetch_status"], "ok")

    def test_api_order_is_not_sales_sort_and_original_row_fields_survive(self):
        docs = [product(31, 1), product(12, 50)]
        before = datetime.now(timezone.utc)
        result, fetcher = self.collect([payload(2, docs)])
        after = datetime.now(timezone.utc)
        category = self.category(result)
        self.assertEqual(ids(category["listing_products"]), ["31", "12"])
        self.assertEqual(ids(result["desks"]["body"]["products"]), ["12", "31"])
        self.assertEqual(category["listing_products"], [collector.row(d) for d in docs])
        for source, row in zip(docs, category["listing_products"]):
            self.assertEqual(row["url"], collector.PRODUCT.format(source["pdNo"]))
            self.assertEqual(row["small_category_code"], "SOURCE_CHILD")
            self.assertEqual(row["price_krw"], 3000)
        self.assertEqual(category["code"], CODE)
        self.assertEqual(category["url"], URL)
        self.assertEqual(category["site_total"], 2)
        self.assertEqual(category["collected"], 2)
        self.assertEqual(category["fetch_status"], "ok")
        self.assertIs(category["complete"], True)
        stamp = datetime.fromisoformat(category["fetched_at"])
        self.assertEqual(stamp.utcoffset().total_seconds(), 0)
        self.assertLessEqual(before, stamp)
        self.assertLessEqual(stamp, after)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["calls"], 1)
        fetcher.assert_called_once_with(CODE, 1)

    def test_mixed_ids_survive_in_original_listing_snapshot(self):
        docs = [product("PD20261016001"), product(1049276), product("P100002"), product(1049277)]
        original = copy.deepcopy(docs)
        result, _ = self.collect([payload(4, docs)], per_page=100)
        self.assertEqual(ids(self.category(result)["listing_products"]),
                         ["PD20261016001", "1049276", "P100002", "1049277"])
        self.assertEqual(self.category(result)["listing_products"], [collector.row(d) for d in docs])
        self.assertIs(self.category(result)["complete"], True)
        self.assertEqual(docs, original)

    def test_multiple_pages_and_completion_timestamp_after_last_fetch(self):
        events = []
        completed = datetime(2026, 10, 10, 10, 0, 1, tzinfo=timezone.utc)
        replies = [payload(3, [product(3, 1), product(2, 10)]), payload(3, [product(1, 5)])]

        def fetch(code, page):
            events.append((code, page))
            return replies[page - 1]

        clock = Mock()
        clock.now.side_effect = lambda tz: (events.append("timestamp") or completed)
        with patch.object(collector, "datetime", clock):
            result, fetcher = self.collect(fetch)
        category = self.category(result)
        self.assertEqual(events, [(CODE, 1), (CODE, 2), "timestamp"])
        self.assertEqual(category["fetched_at"], completed.isoformat())
        self.assertEqual(ids(category["listing_products"]), ["3", "2", "1"])
        self.assertEqual(ids(result["desks"]["body"]["products"]), ["2", "1", "3"])
        self.assertIs(category["complete"], True)
        self.assertEqual(fetcher.call_args_list, [call(CODE, 1), call(CODE, 2)])
        self.assertEqual(result["calls"], 2)
        self.sleep.assert_called_once_with(collector.DELAY)

    def test_duplicate_ids_keep_first_row_across_pages(self):
        first = product(3, 1)
        changed = product(3, 900, pdNm="must not replace first")
        result, _ = self.collect([payload(3, [first, product(1, 8)]),
                                  payload(3, [changed, product(2, 4)])])
        category = self.category(result)
        self.assertEqual(ids(category["listing_products"]), ["3", "1", "2"])
        self.assertEqual(category["listing_products"][0], collector.row(first))
        self.assertEqual(category["collected"], 3)
        self.assertIs(category["complete"], True)
        self.assertEqual(ids(result["desks"]["body"]["products"]), ["1", "2", "3"])

    def test_category_membership_is_independent_of_desk_dedup(self):
        other = {**CATEGORY, "code": "OTHER", "url": "https://example.invalid/other"}
        cfg = copy.deepcopy(CFG)
        cfg["body"]["categories"].append(other)
        shared = product(1, 5)
        other_shared = product(1, 80, pdNm="other category original row")
        result, fetcher = self.collect([payload(2, [shared, product(2)]),
                                       payload(2, [product(3), other_shared])], cfg)
        a, b = result["desks"]["body"]["categories"]
        self.assertEqual(ids(a["listing_products"]), ["1", "2"])
        self.assertEqual(ids(b["listing_products"]), ["3", "1"])
        self.assertEqual(b["listing_products"][1], collector.row(other_shared))
        self.assertEqual([a["collected"], b["collected"]], [2, 1])
        self.assertEqual(result["desks"]["body"]["product_count"], 3)
        self.assertTrue(a["complete"] and b["complete"])
        self.assertEqual(fetcher.call_args_list, [call(CODE, 1), call("OTHER", 1)])

    def test_sales_sort_ties_remain_reviews_then_id(self):
        result, _ = self.collect([payload(4, [product(3, 5, 2), product(2, 5, 9),
                                              product(1, 5, 9), product(4, 7)])], per_page=100)
        self.assertEqual(ids(result["desks"]["body"]["products"]), ["4", "1", "2", "3"])
        self.assertEqual(ids(self.category(result)["listing_products"]), ["3", "2", "1", "4"])

    def test_error_keeps_partial_products_and_original_error_shape(self):
        result, _ = self.collect([payload(3, [product(2), product(1)]), OSError("offline failure")])
        self.assert_incomplete(result)
        self.assertEqual(self.category(result)["fetch_status"], "error")
        self.assertEqual(ids(self.category(result)["listing_products"]), ["2", "1"])
        self.assertEqual(result["errors"], [{"desk": "body", "category": "샤워/입욕",
                         "code": CODE, "page": 2, "error": "OSError: offline failure"}])
        self.assertEqual(result["calls"], 2)
        self.assertEqual(self.category(result)["site_total"], 3)

    def test_first_page_error_has_no_complete_listing(self):
        result, _ = self.collect([TimeoutError("offline")])
        self.assert_incomplete(result)
        self.assertEqual(self.category(result)["listing_products"], [])
        self.assertEqual(result["errors"][0]["page"], 1)

    def test_page_bound_is_not_complete_and_does_not_request_extra_page(self):
        result, fetcher = self.collect([payload(5, [product(4), product(3)]),
                                       payload(5, [product(2), product(1)])], max_pages=2)
        self.assert_incomplete(result)
        self.assertEqual(self.category(result)["fetch_status"], "truncated")
        self.assertEqual(ids(self.category(result)["listing_products"]), ["4", "3", "2", "1"])
        self.assertEqual(fetcher.call_count, 2)
        self.assertEqual(result["errors"], [])

    def test_exact_page_bound_can_be_complete(self):
        result, fetcher = self.collect([payload(4, [product(4), product(3)]),
                                       payload(4, [product(2), product(1)])], max_pages=2)
        self.assertIs(self.category(result)["complete"], True)
        self.assertEqual(fetcher.call_count, 2)

    def test_explicit_empty_category_is_valid(self):
        for total in (0, "0"):
            with self.subTest(total=total):
                result, _ = self.collect([payload(total, [])])
                category = self.category(result)
                self.assertIs(category["complete"], True)
                self.assertEqual(category["fetch_status"], "ok")
                self.assertEqual(category["listing_products"], [])
                self.assertEqual(result["errors"], [])

    def test_malformed_or_inconsistent_responses_are_not_complete(self):
        cases = [None, {}, {"resultSet": {}}, {"resultSet": {"result": []}},
                 payload(1, []), payload(0, [product(1)]), payload(-1, []),
                 payload("unknown", []), payload(True, []),
                 payload(0, None), payload(0, {}), payload(1, ["not a document"]),
                 payload(1, [{}]), payload(2, [product(1), {}]),
                 payload(2, [product(1)]), payload(2, [product(1), product(1)]),
                 {"resultSet": {"result": [{"resultDocuments": []}]}}]
        for response in cases:
            with self.subTest(response=response):
                result, _ = self.collect([response])
                self.assert_incomplete(result)

    def test_empty_later_page_and_changing_totals_are_not_complete(self):
        for second in (payload(3, []), payload(2, [product(3)])):
            with self.subTest(second=second):
                result, _ = self.collect([payload(3, [product(1), product(2)]), second])
                self.assert_incomplete(result)
                self.assertEqual(ids(self.category(result)["listing_products"])[:2], ["1", "2"])

    def test_partial_malformed_page_keeps_legacy_usable_products(self):
        result, _ = self.collect([payload(2, [product(1), "bad row"])])
        self.assert_incomplete(result)
        self.assertEqual(ids(result["desks"]["body"]["products"]), ["1"])
        self.assertEqual(result["errors"], [])

    def test_main_reuses_previous_categories_without_refreshing_metadata(self):
        previous_category = {**CATEGORY, "site_total": 1, "collected": 1,
                             "fetched_at": "2020-01-01T00:00:00+00:00", "fetch_status": "ok",
                             "complete": True, "listing_products": [collector.row(product(9))]}
        previous = {"name": "old body", "source": "old source", "product_count": 1,
                    "products": [collector.row(product(9))], "categories": [previous_category]}
        old = {"desks": {"body": previous}}
        config_file = Mock()
        config_file.read_text.return_value = json.dumps({"category_desks": CFG})
        output_file = Mock()
        output_file.exists.return_value = True
        output_file.read_text.return_value = json.dumps(old)
        with patch.object(collector, "CONFIG", config_file), \
                patch.object(collector, "OUT", output_file), \
                patch.object(collector, "fetch", side_effect=OSError("offline")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(collector.main(), 0)
        saved = json.loads(output_file.write_text.call_args.args[0])
        self.assertEqual(saved["kept_previous"], ["body"])
        self.assertEqual(saved["desks"]["body"]["categories"], previous["categories"])
        self.assertEqual(saved["desks"]["body"]["products"], previous["products"])
        self.assertEqual(saved["desks"]["body"]["kept_previous_because"], "이번 수집 0건")
        self.assertEqual(old["desks"]["body"], previous)
        self.assertEqual(len(saved["errors"]), 1)


class CollectorCliTests(unittest.TestCase):
    def test_body_only_collection_uses_separate_repository_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'config.json'
            config.write_text(json.dumps({'category_desks': {**CFG, 'skincare': CFG['body']}}), encoding='utf-8')
            got = {'desks': {'body': {'products': [collector.row(product(1))],
                                      'product_count': 1, 'categories': []}},
                   'errors': [], 'calls': 1}
            default = Mock()
            with patch.object(collector, 'ROOT', root), patch.object(collector, 'CONFIG', config), \
                    patch.object(collector, 'OUT', default), \
                    patch.object(collector, 'collect', return_value=got) as collect_mock, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(collector.main(['--desk', 'body', '--output', 'out/body.json']), 0)
            self.assertEqual(list(collect_mock.call_args.args[0]), ['body'])
            saved = json.loads((root / 'out/body.json').read_text(encoding='utf-8'))
            self.assertEqual(list(saved['desks']), ['body'])
            default.exists.assert_not_called()
            default.write_text.assert_not_called()

    def test_output_escape_or_absolute_path_fails_before_collection(self):
        for output in ('../escape.json', str(ROOT / 'absolute.json')):
            with self.subTest(output=output), patch.object(collector, 'collect') as collect_mock, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(collector.main(['--desk', 'body', '--output', output]), 2)
                collect_mock.assert_not_called()


class RegistrarWorkflowIsolationTests(unittest.TestCase):
    def test_runtime_secrets_and_catalog_override_do_not_reach_unit_tests(self):
        workflow = (ROOT / '.github/workflows/daiso-daily-beauty-shopify.yml').read_text(encoding='utf-8')
        job_header = workflow.split('    steps:', 1)[0]
        self.assertNotIn('SHOPIFY_CLIENT_SECRET:', job_header)
        self.assertNotIn('GEMINI_API_KEY:', job_header)
        self.assertNotIn('BODY_FALLBACK_CATALOG_PATH:', job_header)
        tests = workflow.split('- name: 일일 등록 안전성 단위 테스트', 1)[1].split('# Owner-approved', 1)[0]
        self.assertIn('tempfile.TemporaryDirectory', tests)
        self.assertIn('shutil.copytree', tests)
        self.assertIn('socket.socket.connect = blocked', tests)
        self.assertNotIn('secrets.', tests)
        live = workflow.split('- name: 다이소 추천 선택 후 Shopify 등록', 1)[1].split('- name: 바디 원래 목록', 1)[0]
        self.assertIn("BODY_FALLBACK_CATALOG_PATH: 'out/body_shower_catalog.json'", live)
        self.assertIn('SHOPIFY_CLIENT_SECRET:', live)


if __name__ == "__main__":
    unittest.main()
