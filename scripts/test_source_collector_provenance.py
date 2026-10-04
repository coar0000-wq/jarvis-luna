"""Offline source capture regression tests. Network is forbidden."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent

def load_module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

rb = load_module('collect_robotics')
ds = load_module('collect_design_sources')
bt = load_module('build_design_team')
ch = load_module('discover_channels')
OLD = '2026-01-01T00:00:00+00:00'
NEW = '2026-10-03T00:00:00+00:00'
RSS = b'<rss><channel><title>Feed</title><item><title>Design</title><link>https://example.com/a</link><pubDate>1999-01-01</pubDate></item></channel></rss>'

class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        guard = patch('urllib.request.urlopen', side_effect=AssertionError('NETWORK FORBIDDEN'))
        guard.start()
        self.addCleanup(guard.stop)
        delay = patch('time.sleep')
        delay.start()
        self.addCleanup(delay.stop)

    def old_item(self, feed='B', key=None):
        return {'title': 'retained', 'url': 'https://example.com/old', 'feed': feed,
                'captured_at': OLD, 'observed_at': OLD, 'collected_at': OLD,
                'provenance': {'source_key': key or feed}}

    def test_robotics_rss_partial_retains_old_capture(self):
        previous = {'items': [self.old_item()], 'source_results': {'B': {'captured_at': OLD}}}
        with patch.object(rb, 'RSS_FEEDS', [('A', 'https://a'), ('B', 'https://b')]), patch.object(rb, 'get', side_effect=[(RSS, ''), (None, 'HTTP 503')]), patch.object(rb, 'observation_time', return_value=NEW):
            result = rb.collect_rss(previous)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['captured_at'], OLD)
        self.assertEqual([r['captured_at'] for r in result['items']], [NEW, OLD])
        failed = result['source_results']['B']
        self.assertEqual(failed['captured_at'], OLD)
        self.assertEqual(failed['last_attempt']['http_status'], 503)
        self.assertEqual(failed['last_attempt']['attempted_at'], NEW)

    def test_robotics_empty_and_malformed_have_no_capture(self):
        for body in (b'', b'<html/>', b'<broken'):
            with patch.object(rb, 'RSS_FEEDS', [('A', 'https://a')]), patch.object(rb, 'get', return_value=(body, '')):
                result = rb.collect_rss()
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('captured_at', result)
            self.assertNotIn('captured_at', result['source_results']['A'])

    def test_openalex_partial_topic_preserved(self):
        previous = {'items': [self.old_item(key='T2')], 'source_results': {'T2': {'captured_at': OLD}}}
        doc = json.dumps({'results': [{'title': 'Robot', 'publication_date': '1990-01-01', 'doi': 'https://doi/a'}]}).encode()
        with patch.object(rb, 'OPENALEX_TOPICS', [('T1', 'one'), ('T2', 'two')]), patch.object(rb, 'get', side_effect=[(doc, ''), (b'{"error":"quota"}', '')]), patch.object(rb, 'observation_time', return_value=NEW):
            result = rb.collect_arxiv(previous)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual([r['captured_at'] for r in result['items']], [NEW, OLD])
        self.assertEqual(result['source_results']['T2']['last_attempt']['code'], 'parse_error')

    def test_capture_clock_follows_parse_not_fetch(self):
        events = []
        loads = rb.json.loads
        def fake_get(*args):
            events.append('http')
            return b'{"results":[{"title":"Robot"}]}', ''
        def fake_parse(*args):
            result = loads(*args)
            events.append('parse')
            return result
        def clock():
            self.assertEqual(events[:2], ['http', 'parse'])
            return NEW
        with patch.object(rb, 'OPENALEX_TOPICS', [('T', 'topic')]), patch.object(rb, 'get', side_effect=fake_get), patch.object(rb.json, 'loads', side_effect=fake_parse), patch.object(rb, 'observation_time', side_effect=clock):
            result = rb.collect_arxiv()
        self.assertEqual(result['items'][0]['observed_at'], NEW)

    def test_design_fonts_and_colors_capture(self):
        font = json.dumps({'familyMetadataList': [{'family': 'Example', 'popularity': 1, 'dateAdded': '1990', 'fonts': {'400': {}}}]})
        with patch.object(ds, 'fetch', return_value=font), patch.object(ds, 'observation_time', return_value=NEW):
            result = ds.collect_fonts()
        self.assertEqual(result['captured_at'], NEW)
        self.assertEqual(result['top_popular'][0]['collected_at'], NEW)
        with patch.object(ds, 'fetch', return_value='{"blue":["#000"]}'), patch.object(ds, 'observation_time', return_value=NEW):
            result = ds.collect_colors()
        self.assertEqual(result['captured_at'], NEW)
        self.assertEqual(result['provenance']['source_key'], 'colors')

    def test_design_articles_partial(self):
        previous = {'items': [self.old_item()], 'source_results': {'B': {'captured_at': OLD}}}
        with patch.object(ds, 'FEEDS', [('A', 'https://a', 'ux'), ('B', 'https://b', 'ux')]), patch.object(ds, 'fetch', side_effect=[RSS.decode(), OSError('offline')]), patch.object(ds, 'observation_time', return_value=NEW):
            result = ds.collect_articles(previous)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['items'][1]['captured_at'], OLD)
        self.assertEqual(result['source_results']['B']['last_attempt']['status'], 'failed')

    def test_design_main_failed_block_retains_clock(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'design.json'
            out.write_text(json.dumps({'fonts': {'status': 'ok', 'captured_at': OLD, 'total': 1}}))
            with patch.object(ds, 'OUT', out), patch.object(ds, 'collect_fonts', side_effect=OSError('offline')), patch.object(ds, 'collect_colors', return_value={'status': 'ok'}), patch.object(ds, 'collect_articles', return_value={'status': 'failed', 'items': []}), patch.object(ds, 'observation_time', return_value=NEW):
                self.assertEqual(ds.main(), 1)
            result = json.loads(out.read_text())
        self.assertEqual(result['fonts']['captured_at'], OLD)
        self.assertEqual(result['fonts']['status'], 'failed')
        self.assertEqual(result['fonts']['last_attempt']['attempted_at'], NEW)

    def test_team_reference_uses_own_feed_and_retains_partial(self):
        previous = {'items': [self.old_item()], 'source_results': {'B': {'captured_at': OLD}}}
        sources = {}
        with patch.object(bt, 'FEEDS', [('A', 'https://team-a'), ('B', 'https://team-b')]), patch.object(bt, 'fetch', side_effect=[RSS.decode(), '<malformed']), patch.object(bt, 'observation_time', return_value=NEW):
            items, fails = bt.collect_references(previous, sources)
        self.assertEqual(items[0]['provenance']['source_url'], 'https://team-a')
        self.assertEqual([r['captured_at'] for r in items], [NEW, OLD])
        self.assertEqual(sources['B']['last_attempt']['parse_status'], 'failed')
        self.assertEqual(len(fails), 1)

    def candidate(self):
        return {'key': 'k', 'label': 'public', 'why': 'test', 'url': 'https://example.com/api', 'kind': 'json', 'path': ['items'], 'name_keys': ['name']}

    def test_channels_success_is_probe_not_registration(self):
        body = json.dumps({'items': [{'name': name} for name in ('one', 'two', 'three')]}).encode()
        with patch.object(ch, 'robots_allows', return_value=(True, 'allowed')), patch.object(ch, 'get', return_value=(body, '')), patch.object(ch, 'observation_time', return_value=NEW):
            result = ch.probe(self.candidate())
        self.assertEqual(result['captured_at'], NEW)
        self.assertEqual(result['collected_at'], NEW)
        self.assertEqual(result['last_attempt']['parse_status'], 'ok')
        self.assertEqual(result['evidence_scope'], 'candidate_probe')
        self.assertFalse(result['connector_registered'])

    def test_channels_failure_preserves_capture(self):
        previous = {'captured_at': OLD, 'observed_at': OLD, 'collected_at': OLD, 'items': 3, 'samples': ['old']}
        with patch.object(ch, 'robots_allows', return_value=(True, 'allowed')), patch.object(ch, 'get', return_value=(None, 'HTTP 429')), patch.object(ch, 'observation_time', return_value=NEW):
            result = ch.probe(self.candidate(), previous)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['captured_at'], OLD)
        self.assertEqual(result['last_attempt']['http_status'], 429)
        self.assertEqual(result['last_attempt']['attempted_at'], NEW)

    def test_channels_ambiguous_response_not_healthy(self):
        for body in (b'{}', b'{"items":[]}', b'<html/>'):
            with patch.object(ch, 'robots_allows', return_value=(True, 'allowed')), patch.object(ch, 'get', return_value=(body, '')):
                result = ch.probe(self.candidate())
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('captured_at', result)

    def test_unknown_robots_blocked_before_source_request(self):
        for response in ((None, 'HTTP 503'), (b'', ''), (b'<html>oops</html>', '')):
            with patch.object(ch, 'get', return_value=response) as get:
                result = ch.probe(self.candidate())
            self.assertEqual(result['last_attempt']['code'], 'robots_unknown')
            self.assertEqual(get.call_count, 1)
            self.assertNotIn('captured_at', result)

    def test_robots_disallow_and_valid_allow(self):
        for body, allowed in ((b'User-agent: *\nDisallow: /', False), (b'User-agent: *\nAllow: /', True)):
            with patch.object(ch, 'get', return_value=(body, '')):
                self.assertEqual(ch.robots_allows('https://example.com/api')[0], allowed)

    def reviewed_candidates(self):
        return [dict(c) for c in ch.CANDIDATES if c['key'] in ch.PUBLIC_API_DOCUMENTATION]

    def api_body(self, candidate):
        name = candidate['name_keys'][0]
        return json.dumps({candidate['path'][0]: [{name: x} for x in ('one', 'two', 'three')]}).encode()

    def test_reviewed_exact_apis_use_documentation_for_unknown_robots(self):
        for candidate in self.reviewed_candidates():
            with self.subTest(key=candidate['key']), patch.object(ch, 'get', side_effect=[(None, 'HTTP 404'), (self.api_body(candidate), '')]) as get, patch.object(ch, 'observation_time', return_value=NEW):
                result = ch.probe(candidate)
            self.assertEqual(get.call_count, 2)  # One robots GET, exactly one API GET.
            self.assertEqual(get.call_args_list[1].args, (candidate['url'],))
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['verdict'], '가능')
            self.assertEqual(result['provenance']['access_basis'], 'reviewed_public_api_read')
            self.assertEqual(result['provenance']['public_api_documentation'], ch.PUBLIC_API_DOCUMENTATION[candidate['key']][2])
            self.assertEqual(result['last_attempt']['max_source_reads'], 1)
            self.assertEqual(result['captured_at'], NEW)
            self.assertFalse(result['connector_registered'])

    def test_reviewed_url_path_or_key_mismatch_stays_blocked(self):
        candidate = self.reviewed_candidates()[0]
        variants = [dict(candidate, key='unreviewed'),
                    dict(candidate, url=candidate['url'].replace('https:', 'http:')),
                    dict(candidate, url=candidate['url'].replace('wikimedia.org', 'wikimedia.org.evil.example')),
                    dict(candidate, url=candidate['url'] + '/different'),
                    dict(candidate, url=candidate['url'] + '?api_key=not-a-real-key'),
                    dict(candidate, url=candidate['url'] + '#fragment')]
        for fda in self.reviewed_candidates()[1:]:
            variants.append(dict(fda, url=fda['url'].replace('.json', '.json/different')))
            variants.append(dict(fda, key='wikipedia_pageviews'))
        for variant in variants:
            with self.subTest(url=variant['url']), patch.object(ch, 'get', return_value=(None, 'HTTP 404')) as get:
                result = ch.probe(variant)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['last_attempt']['code'], 'robots_unknown')
            self.assertEqual(get.call_count, 1)
            self.assertNotIn('captured_at', result)

    def test_explicit_denial_never_uses_api_documentation(self):
        for candidate in self.reviewed_candidates():
            with patch.object(ch, 'get', return_value=(b'User-agent: *\nDisallow: /', '')) as get:
                result = ch.probe(candidate)
            self.assertEqual(result['last_attempt']['code'], 'robots_denied')
            self.assertEqual(get.call_count, 1)
            self.assertNotIn('public_api_documentation', result)

    def test_reviewed_api_auth_quota_and_no_records_fail_without_retry(self):
        candidate = self.reviewed_candidates()[1]
        previous = {'captured_at': OLD, 'observed_at': OLD, 'collected_at': OLD}
        for code in (401, 403, 404, 429):
            with self.subTest(code=code), patch.object(ch, 'get', side_effect=[(None, 'HTTP 404'), (None, f'HTTP {code}')]) as get, patch.object(ch, 'observation_time', return_value=NEW):
                result = ch.probe(candidate, previous)
            self.assertEqual(get.call_count, 2)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['last_attempt']['http_status'], code)
            self.assertEqual(result['last_attempt']['code'], 'http_error')
            self.assertEqual(result['captured_at'], OLD)
            self.assertEqual(result['last_attempt']['public_api_documentation'], ch.PUBLIC_API_DOCUMENTATION[candidate['key']][2])

    def test_robots_auth_quota_errors_are_not_retried_or_overridden(self):
        for candidate in self.reviewed_candidates():
            for code in (401, 403, 429):
                with patch.object(ch, 'get', return_value=(None, f'HTTP {code}')) as get:
                    result = ch.probe(candidate)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(get.call_count, 1)

    def test_source_requests_use_identifying_user_agent(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{}'
        with patch('urllib.request.urlopen', return_value=response) as request:
            ch.get('https://example.com/public')
        self.assertEqual(request.call_args.args[0].get_header('User-agent'), 'JarvisLunaSourceProbe/1.0 (+https://github.com/coar0000-wq/jarvis-luna)')

if __name__ == '__main__':
    unittest.main()
