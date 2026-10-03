#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
import youtube_dropshipping_analysis as y
from unittest.mock import patch
import collector_result as c

ROOT = Path(__file__).resolve().parents[1]


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT.parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.result = self.root/'results'/'stage.json'
        self.artifact = self.root/'input.json'
        self.artifact.write_text('{"generated_at":"old","items":[]}', encoding='utf-8')
        self.env = patch.dict(os.environ, {'RELEASE_EXECUTION_ID': 'fixture:1'})
        self.env.start(); self.addCleanup(self.env.stop)

    def run(self, result=None):
        # unittest itself calls run(result); retain its protocol.
        return super().run(result)

    def stage(self, command=None, required=True, skip=None):
        return c.run_stage('stage', required, [str(self.artifact)],
                           command or [sys.executable, '-c', 'pass'], self.result,
                           skip_reason=skip)

    def test_success_process_is_not_successful_source_fetch(self):
        self.assertEqual(self.stage(), 0)
        d = json.loads(self.result.read_text())
        self.assertEqual(d['status'], 'success')
        self.assertIsNone(d['last_successful_fetch_at'])
        self.assertEqual(d['fetch_verification'], 'not_instrumented')
        self.assertEqual(d['new_count'], 0)
        self.assertTrue(d['using_cached_data'])

    def test_semantic_hash_ignores_timestamp_only_changes(self):
        before = c.artifact(self.artifact)
        self.artifact.write_text('{"generated_at":"new","items":[]}', encoding='utf-8')
        after = c.artifact(self.artifact)
        self.assertNotEqual(before['sha256'], after['sha256'])
        self.assertEqual(before['content_sha256'], after['content_sha256'])

    def test_html_block_page_not_valid_zero_result(self):
        self.artifact.write_text('<html>Access denied</html>', encoding='utf-8')
        self.assertEqual(self.stage(), 1)
        d = json.loads(self.result.read_text())
        self.assertEqual(d['error_code'], 'artifact_missing_or_invalid')
        self.assertEqual(d['status'], 'failed')

    def test_missing_artifact_blocks(self):
        self.artifact.unlink()
        self.assertEqual(self.stage(), 1)

    def test_required_failure_propagates_and_publication_blocked(self):
        self.assertEqual(self.stage([sys.executable, '-c', 'raise SystemExit(7)']), 7)
        code = c.aggregate(self.result.parent, [('stage', True)], self.root/'report.json')
        self.assertEqual(code, 1)
        self.assertFalse(json.loads((self.root/'report.json').read_text())['publish_allowed'])

    def test_optional_failure_degraded_and_reflected_runtime(self):
        self.stage([sys.executable, '-c', 'raise SystemExit(2)'], required=False)
        rt = self.root/'runtime.json'; rt.write_text('{"generated_at":"original"}')
        self.assertEqual(c.aggregate(self.result.parent, [('stage', False)], self.root/'report.json', rt), 0)
        d = json.loads(rt.read_text())
        self.assertEqual(d['pipeline_health']['status'], 'degraded')
        self.assertEqual(d['pipeline_health']['optional_failure_count'], 1)
        self.assertEqual(d['generated_at'], 'original')

    def test_synthetic_skip_does_not_rewrite_source_bytes(self):
        before = self.artifact.read_bytes()
        self.stage(required=False, skip='synthetic collector disabled')
        d = json.loads(self.result.read_text())
        self.assertEqual(d['status'], 'skipped')
        self.assertIsNone(d['last_successful_fetch_at'])
        self.assertEqual(before, self.artifact.read_bytes())
        self.assertEqual(c.aggregate(self.result.parent, [('stage', False)], self.root/'report.json'), 0)
        self.assertEqual(json.loads((self.root/'report.json').read_text())['status'], 'degraded')

    def test_missing_or_stale_optional_evidence_never_assumed_success(self):
        self.assertEqual(c.aggregate(self.result.parent, [('stage', False)], self.root/'report.json'), 1)
        self.stage(required=False)
        with patch.dict(os.environ, {'RELEASE_EXECUTION_ID': 'fixture:2'}):
            self.assertEqual(c.aggregate(self.result.parent, [('stage', False)], self.root/'report.json'), 1)

    def test_local_known_identity_counts_observed_without_fake_fetch(self):
        self.artifact.write_text('{"products":[{"pd_no":"1","name":"old"}]}')
        def local_process(*args, **kwargs):
            self.artifact.write_text('{"products":[{"pd_no":"1","name":"changed"},{"pd_no":"2","name":"new"}]}')
            return SimpleNamespace(returncode=0)
        with patch.object(c.subprocess, 'run', side_effect=local_process): self.stage()
        d=json.loads(self.result.read_text())
        self.assertEqual((d['new_count'],d['updated_count']), (1,1))
        self.assertIsNone(d['last_successful_fetch_at'])

    def run_youtube_fixture(self, channels=None):
        evidence=self.root/'youtube-evidence.json'
        self.artifact=self.root/'youtube_real_videos.json'
        self.artifact.write_text('{"videos":[]}',encoding='utf-8')
        def child(*args, **kwargs):
            with patch.dict(os.environ,kwargs['env']): return SimpleNamespace(returncode=y.main())
        with patch.object(y,'DATA',self.root), patch.object(c.subprocess,'run',side_effect=child):
            if channels is None:
                with patch.object(y,'ROBOTS_BLOCKED',True), patch.object(y,'fetch',side_effect=AssertionError('no network')):
                    rc=c.run_stage('stage',False,[str(self.artifact)],['fixture'],self.result,fetch_evidence=evidence)
            else:
                ids=['good','bad'] if len(channels)==2 else ['good']
                with patch.object(y,'ROBOTS_BLOCKED',False),patch.object(y,'channel_ids',return_value=ids),patch.object(y,'collect_channel',side_effect=channels):
                    rc=c.run_stage('stage',False,[str(self.artifact)],['fixture'],self.result,fetch_evidence=evidence)
        return rc,json.loads(self.result.read_text()),json.loads(evidence.read_text())

    def test_robots_blocked_source_is_not_successful_zero_fetch(self):
        rc,result,evidence=self.run_youtube_fixture()
        self.assertEqual(rc,0)
        self.assertEqual(result['status'],'skipped')
        self.assertEqual(result['fetch_verification'],'not_attempted')
        self.assertIsNone(result['last_successful_fetch_at'])
        self.assertEqual(evidence['query_count'],0)

    def test_validated_feed_provides_actual_new_count_and_partial_failure(self):
        good={'channel_id':'good','channel_title':'Fixture','rss_url':'https://example.invalid/rss','count':1,
              'videos':[{'video_id':'v1','title':'Fixture','url':'https://example.invalid/v1'}]}
        for channels,status in (([good],'success'),([good,ValueError('blocked')],'degraded')):
            rc,result,evidence=self.run_youtube_fixture(channels)
            self.assertEqual(rc,0)
            self.assertEqual(result['status'],status)
            self.assertEqual(result['fetch_verification'],'verified_http_parse')
            self.assertIsNotNone(result['last_successful_fetch_at'])
            self.assertEqual((result['new_count'],result['updated_count']),(1,0))
            self.assertEqual(result['query_count'],len(channels))
            self.assertEqual(evidence['parsed_count'],1)

    def test_no_valid_feed_fails_and_html_not_atom(self):
        rc,result,evidence=self.run_youtube_fixture([ValueError('blocked')])
        self.assertEqual(rc,1)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(evidence['succeeded_count'],0)
        with patch.object(y,'fetch',return_value=b'<html>Access denied</html>'),self.assertRaises(ValueError):
            y.collect_channel('fixture')

    def test_attach_runtime_rejects_stale_report(self):
        with self.assertRaises(ValueError):
            c.attach_runtime({'schema_version':1, 'execution_id':'old', 'status':'success'}, self.root/'rt.json')


if __name__ == '__main__': unittest.main(verbosity=2)
