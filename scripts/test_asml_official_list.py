"""Offline tests for the reconstructed ASML official dated-list adapter."""
import copy
import importlib.util
from datetime import date
from pathlib import Path
import unittest
import urllib.error
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('asml_candidate', HERE / 'collect_institutions.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
FIXTURE = (HERE / 'fixtures/asml_press_list.html').read_text()
TODAY = date(2026, 10, 23)
ALLOW = 'User-agent: *\nDisallow: /admin/\n'
OLD, NEW = '2026-10-01T00:00:00+00:00', '2026-10-23T00:00:00+00:00'


class AsmlTests(unittest.TestCase):
    def setUp(self):
        guard = patch('urllib.request.urlopen', side_effect=AssertionError('NETWORK FORBIDDEN'))
        guard.start()
        self.addCleanup(guard.stop)

    def test_fixture_title_date_url_provenance(self):
        rows = m.parse_asml_list(FIXTURE, today=TODAY)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r['date'] for r in rows], ['2026-10-14', '2026-09-08'])
        self.assertIn('€11.7 billion', rows[0]['title'])
        self.assertTrue(rows[0]['url'].startswith('https://investor.asml.com/news-releases/news-release-details/'))
        self.assertEqual(rows[0]['feed'], m.ASML_LIST)
        self.assertEqual(rows[0]['source'], 'official_list')
        self.assertEqual(rows[0]['date_source'], 'publication_date')
        self.assertNotIn('collected_at', rows[0])

    def test_duplicate_future_and_future_only_rows(self):
        self.assertEqual(len(m.parse_asml_list(FIXTURE * 2, today=TODAY)), 2)
        rows = m.parse_asml_list(FIXTURE.replace('October 14, 2026', 'October 24, 2026'), today=TODAY)
        self.assertEqual([r['date'] for r in rows], ['2026-09-08'])
        with self.assertRaises(ValueError):
            m.parse_asml_list(FIXTURE, today=date(2026, 1, 1))

    def test_parse_failures_are_not_partial_success(self):
        cases = ['', '<html>Challenge</html>', FIXTURE.rsplit('</article>', 1)[0],
                 FIXTURE.replace('October 14, 2026', 'February 30, 2026'),
                 FIXTURE.replace('October 14, 2026', 'unknown'),
                 FIXTURE.replace('search-results__date-posted', 'changed-layout'),
                 FIXTURE.replace('href="/news-releases/', 'href="https://other.example/news-releases/'),
                 FIXTURE.replace('href="/news-releases/', 'href="javascript:/news-releases/')]
        for text in cases:
            with self.subTest(text=text[:60]), self.assertRaises(ValueError):
                m.parse_asml_list(text, today=TODAY)

    def test_robots_denied_unavailable_or_invalid_stops_before_list(self):
        cases = ['User-agent: *\nDisallow: /\n', '<html>Denied</html>', '', TimeoutError(),
                 urllib.error.HTTPError(m.ASML_ROBOTS, 403, 'Forbidden', {}, None)]
        for response in cases:
            with self.subTest(response=response), patch.object(m, 'fetch', side_effect=[response]) as fetch:
                rows, errors = m.collect_official_lists()
                self.assertEqual(rows, [])
                self.assertEqual(len(errors), 1)
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(errors[0]['url'], m.ASML_LIST)

    def test_allowed_collection_and_list_403_no_retry(self):
        with patch.object(m, 'fetch', side_effect=[ALLOW, FIXTURE]) as fetch:
            rows, errors = m.collect_official_lists()
            self.assertEqual(len(rows), 2)
            self.assertEqual(errors, [])
            self.assertEqual([c.args[0] for c in fetch.call_args_list], [m.ASML_ROBOTS, m.ASML_LIST])
        exc = urllib.error.HTTPError(m.ASML_LIST, 403, 'Forbidden', {}, None)
        with patch.object(m, 'fetch', side_effect=[ALLOW, exc]) as fetch:
            rows, errors = m.collect_official_lists()
            self.assertEqual(rows, [])
            self.assertEqual(errors[0]['http_status'], 403)
            self.assertEqual(fetch.call_count, 2)

    def test_failed_parse_retains_prior_rows_and_clocks(self):
        old = {**m.parse_asml_list(FIXTURE, today=TODAY)[0], 'collected_at': OLD}
        previous = {'items': [old], 'sources': {'official_list': {'status': 'ok', 'collected_at': OLD}}}
        untouched = copy.deepcopy(previous)
        with patch.object(m, 'fetch', side_effect=[ALLOW, FIXTURE.replace('October 14, 2026', 'bad-date')]):
            batch = m.collect_official_lists()
        result = m.merge_attempt(previous, {'official_list': batch}, NEW)
        self.assertEqual(previous, untouched)
        self.assertEqual(result['retained_count'], 1)
        self.assertEqual(result['fresh_count'], 0)
        self.assertEqual(result['items'][0]['collected_at'], OLD)
        self.assertTrue(result['items'][0]['retained'])
        self.assertEqual(result['sources']['official_list']['status'], 'failed')

    def test_legacy_and_other_org_provenance_is_preserved(self):
        old = {**m.parse_asml_list(FIXTURE, today=TODAY)[0], 'collected_at': OLD,
               'source': 'sitemap', 'feed': 'https://www.asml.com/sitemap.xml'}
        other = {**old, 'org': 'Broadcom', 'source': 'rss',
                 'feed': 'https://investors.broadcom.com/rss/news-releases.xml'}
        result = m.merge_attempt({'items': [old, other]},
                                 {'official_list': (m.parse_asml_list(FIXTURE, today=TODAY), [])}, NEW)
        self.assertEqual(result['retained_count'], 2)
        self.assertEqual(result['fresh_count'], 2)
        self.assertEqual(result['sources']['official_list']['status'], 'ok')


if __name__ == '__main__':
    unittest.main()
