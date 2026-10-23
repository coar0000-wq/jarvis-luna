#!/usr/bin/env python3
"""Offline bounded response capture, checkpoint and process cleanup regressions."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.daiso import collect_gosi_alt as collector
from scripts import gosi_observation_history as history


class FakeResponse:
    def __init__(self, raw=b'country', *, mime='text/plain', resource='xhr', status=200,
                 length=None, body=None, url='https://www.daisomall.co.kr/fixture'):
        self.url, self.status = url, status
        self.request = SimpleNamespace(url=url, resource_type=resource)
        # Request identity must be hashable like a real Playwright Request.
        self.request = type('Request', (), dict(url=url, resource_type=resource))()
        self.headers = {'content-type': mime}
        if length is not None:
            self.headers['content-length'] = str(length)
        self.raw, self.body_effect, self.body_calls = raw, body, 0
    def body(self):
        self.body_calls += 1
        return self.body_effect() if self.body_effect else self.raw


class ResponseCaptureTests(unittest.TestCase):
    def make(self, **kwargs):
        self.stops = []
        return collector.ResponseCapture((1, '1234567'), self.stops.append,
                     max_body_bytes=1024, max_total_bytes=4096,
                     max_text_bytes=8192, **kwargs)
    def send(self, capture, response):
        capture.request_started(response.request)
        capture.received(response)
    def test_binary_body_is_not_read_or_decoded(self):
        cap=self.make(); response=FakeResponse(b'\xff'*16384,mime='image/png',resource='image')
        with patch.object(collector,'response_text',side_effect=AssertionError('no decode')):
            self.send(cap,response)
        self.assertEqual(response.body_calls,0);self.assertEqual(cap.responses,[])
        self.assertEqual(cap.binary_skipped,1);self.assertEqual(cap.issues,[])
    def test_denials_precede_binary_size_count_and_existing_limits(self):
        for code in (401,403,429):
            cap=self.make(max_responses=1);cap.issue('already_full')
            response=FakeResponse(mime='image/png',resource='image',status=code,length=1000000)
            self.send(cap,response)
            self.assertEqual(response.body_calls,0);self.assertEqual(self.stops[0].code,code)
            later=FakeResponse();self.send(cap,later);self.assertEqual(later.body_calls,0)
    def test_known_oversized_body_is_not_read(self):
        cap=self.make();response=FakeResponse(length=1025)
        self.send(cap,response)
        self.assertEqual(response.body_calls,0);self.assertIn('response_body_limit',cap.issues)
    def test_unknown_length_actual_oversize_never_decodes_or_mints_receipt(self):
        cap=self.make();response=FakeResponse(b'x'*1025)
        with patch.object(collector,'response_text',side_effect=AssertionError('no decode')), \
             patch.object(collector,'receipt',side_effect=AssertionError('no receipt')):
            self.send(cap,response)
        self.assertEqual(response.body_calls,1);self.assertIn('response_body_limit',cap.issues)
    def test_count_is_reserved_before_nested_body_callback(self):
        cap=self.make(max_responses=1)
        nested=FakeResponse()
        outer=FakeResponse(body=lambda:(self.send(cap,nested),b'country')[1])
        self.send(cap,outer)
        self.assertEqual(outer.body_calls,1);self.assertEqual(nested.body_calls,0)
        self.assertEqual(cap.responses,[]);self.assertIn('response_count_limit',cap.issues)
        self.assertEqual((cap.inflight,cap.reserved),(0,0))
    def test_inflight_slot_reserved_before_nested_body_callback(self):
        cap=self.make(max_inflight=1)
        nested=FakeResponse();outer=FakeResponse(body=lambda:(self.send(cap,nested),b'country')[1])
        self.send(cap,outer)
        self.assertEqual(nested.body_calls,0);self.assertIn('response_inflight_limit',cap.issues)
    def test_denial_during_body_prevents_outer_capture(self):
        cap=self.make();denial=FakeResponse(status=403)
        outer=FakeResponse(body=lambda:(self.send(cap,denial),b'country')[1])
        self.send(cap,outer)
        self.assertEqual(self.stops[0].code,403);self.assertEqual(cap.responses,[])
    def test_request_generation_is_bound_before_response_arrival(self):
        old=self.make();new=self.make();new.generation=(2,'1234568')
        response=FakeResponse();old.request_started(response.request)
        new.received(response)
        self.assertEqual(response.body_calls,0)
        self.assertIn('response_without_current_request_identity',new.issues)
    def test_text_receipt_uses_complete_exact_original_bytes(self):
        cap=self.make();raw=b'{"notice":"\\uc81c\\uc870\\uad6d: country"}'
        response=FakeResponse(raw,mime='application/json');self.send(cap,response)
        row={};collector.apply_alt(row,'제조국: country',cap.responses,'1234567','rendered_alt_partial_page')
        obs=row['field_observations']['origin']
        self.assertEqual(obs['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(obs['byte_count'],len(raw))
        self.assertFalse(obs['verified']);self.assertFalse(obs['product_identity_verified'])
        self.assertFalse(obs['human_verified'])
    def test_unbound_text_does_not_invent_field(self):
        cap=self.make();self.send(cap,FakeResponse(b'other source'))
        row={};collector.apply_alt(row,'제조국: country',cap.responses,'1234567','rendered_alt_partial_page')
        self.assertNotIn('origin',row);self.assertEqual(row['observation_attempts'][0]['status'],'unbound_field')
    def test_text_retention_limit_is_truthful_not_truncation(self):
        cap=self.make();cap.max_text_bytes=10
        self.send(cap,FakeResponse(b'country'))
        self.assertEqual(cap.responses,[]);self.assertIn('response_text_limit',cap.issues)
        with self.assertRaises(collector.CaptureLimit):cap.check()
    def test_cumulative_budget_admission_precedes_body(self):
        cap=self.make();cap.max_total_bytes=1024
        first=FakeResponse(b'x'*512);second=FakeResponse(b'y'*512)
        self.send(cap,first);self.send(cap,second)
        self.assertEqual(first.body_calls,1);self.assertEqual(second.body_calls,0)
        self.assertIn('response_total_limit',cap.issues)
    def test_json_capture_does_not_retain_recursive_visitor_cycles(self):
        import gc
        import tracemalloc
        cap=collector.ResponseCapture((1,'fixture'),lambda stop:None,
            max_body_bytes=512*1024,max_total_bytes=4*1024*1024,max_text_bytes=8*1024*1024)
        raw=b'{"value":"'+b'x'*(256*1024)+b'"}'
        enabled=gc.isenabled()
        gc.collect();gc.disable();tracemalloc.start()
        try:
            for _ in range(6):
                self.send(cap,FakeResponse(raw,mime='application/json'))
            current,_=tracemalloc.get_traced_memory()
            self.assertEqual(len(cap.responses),6)
            self.assertLess(current,cap.text_bytes+200000)
        finally:
            tracemalloc.stop()
            if enabled:gc.enable()
            gc.collect()

    def test_hostname_allowlist_rejects_substring_spoof(self):
        cap=self.make();response=FakeResponse(url='https://daisomall.co.kr.attacker.invalid/fixture')
        self.send(cap,response);self.assertEqual(response.body_calls,0)
    def test_finished_request_binding_is_released(self):
        cap=self.make();response=FakeResponse();cap.request_started(response.request)
        self.assertEqual(len(cap.requests),1);cap.request_finished(response.request)
        self.assertEqual(cap.requests,{})


class ParentCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'data').mkdir();(self.root/'config').mkdir()
        self.original={'items':{'1234567':{'product_id':'1234567','maker':'retained source fact','captured_at':'original'}}}
        self.raw=(json.dumps(self.original)+'\n').encode()
        (self.root/'data/gosi.json').write_bytes(self.raw)
        (self.root/'config/publish_policy.json').write_text(json.dumps({'identity_fields':['pd_no','product_id']}))
    def run_fixture(self, events, outcome):
        from scripts.daiso import gosi_collection_runtime as runtime
        def supervised(*args,**kwargs):
            Path(kwargs['journal_dir']).mkdir()
            for i,(kind,payload) in enumerate(events,1):
                kwargs['on_event']({'kind':kind,'payload':payload,'sequence':i})
            return outcome
        with patch.object(collector,'ROOT',self.root),patch.object(collector,'GOSI',self.root/'data/gosi.json'), \
             patch.object(history,'exact_head',return_value=self.raw),patch.object(runtime,'run_supervised',side_effect=supervised), \
             patch('scripts.gosi_safety_checkpoint.collection_admission',return_value=True), \
             patch.object(collector,'_publish_checkpoint',side_effect=lambda root,doc,**kw: history.publish_observation(root,doc)), \
             patch.dict(os.environ,{'RUNNER_TEMP':str(self.root),'DAISO_GOSI_BUDGET_SECONDS':'10','DAISO_GOSI_CLEANUP_SECONDS':'1'}):
            return collector.run_collection_supervisor(copy.deepcopy(self.original),['1234567'])
    def test_observed_stop_published_before_timeout_cleanup(self):
        now='2026-10-22T00:00:00+00:00'
        events=[('start_product',{'product_id':'1234567','attempted_at':now}),
                ('stop',{'product_id':'1234567','code':403,'category':'auth','observed_at':now})]
        code=self.run_fixture(events,dict(exit_code=2,reason='provider_stop',timed_out=True,cleanup_confirmed=True,error=None))
        self.assertEqual(code,2)
        doc=json.loads((self.root/'data/gosi.json').read_text())
        self.assertEqual(doc['provider_stops'][0]['code'],403)
        self.assertEqual(doc['provider_stops'][0]['stopped_at'],now)
        self.assertEqual(doc['items']['1234567']['maker'],'retained source fact')
        self.assertFalse((self.root/'.gosi-collection.pending').exists())
        archive=self.root/history.HISTORY_PATH/(history.sha(self.raw)+'.json')
        self.assertEqual(archive.read_bytes(),self.raw)
    def test_unknown_worker_failure_leaves_pending_marker(self):
        code=self.run_fixture([],dict(exit_code=1,reason='missing_complete',timed_out=False,cleanup_confirmed=True,error=None))
        self.assertEqual(code,1);self.assertTrue((self.root/'.gosi-collection.pending').exists())
        self.assertEqual((self.root/'data/gosi.json').read_bytes(),self.raw)
    def test_reconciled_timeout_is_failed_and_preserves_attempt(self):
        events=[('start_product',{'product_id':'1234567','attempted_at':history.utcnow()})]
        code=self.run_fixture(events,dict(exit_code=124,reason='worker_deadline',timed_out=True,cleanup_confirmed=True,error=None))
        self.assertEqual(code,124);self.assertFalse((self.root/'.gosi-collection.pending').exists())
        row=json.loads((self.root/'data/gosi.json').read_text())['items']['1234567']
        self.assertEqual([x['status'] for x in row['observation_attempts']],['started','interrupted'])
        self.assertEqual(row['maker'],'retained source fact')
    def test_unconfirmed_cleanup_cannot_clear_pending_marker(self):
        code=self.run_fixture([],dict(exit_code=125,reason='descendant_cleanup_unconfirmed',timed_out=True,cleanup_confirmed=False,error=None))
        self.assertEqual(code,125);self.assertTrue((self.root/'.gosi-collection.pending').exists())


import subprocess
from scripts.daiso import gosi_collection_runtime as runtime
ROOT = Path(__file__).resolve().parents[1]

PREFIX = '''
import json, os, signal, sys, time
from pathlib import Path
from scripts.daiso.gosi_collection_runtime import JournalWriter
j = JournalWriter.from_env()
'''


@unittest.skipUnless(sys.platform == 'linux', 'Linux subreaper containment is required')
class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gosi-runtime-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.baseline = b'{"items":{"fixture":{"origin":"retained"}}}\n'
        self.events = []
        self.serial = 0

    def run_worker(self, code, callback=None, duration=1.6, cleanup=.7):
        self.serial += 1
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT))
        started = time.monotonic()
        result = runtime.run_supervised([sys.executable, '-B', '-c', PREFIX + code],
            journal_dir=self.root / f'journal-{self.serial}', baseline_bytes=self.baseline,
            deadline=started + duration, cleanup_seconds=cleanup,
            on_event=callback or self.events.append, env=environment, cwd=ROOT)
        self.assertLess(time.monotonic() - started, duration + 1.0, result)
        self.assertTrue(result['cleanup_confirmed'], result)
        self.assertEqual((Path(result['journal_dir']) / 'baseline.json').read_bytes(), self.baseline)
        return result

    def test_success_requires_checkpoint_ack_exit_and_complete_after_teardown(self):
        code = '''
j.emit('start_product', {'product_id':'fixture','attempted_at':'fixture'})
j.emit('product_result', {'product_id':'fixture','observations':[], 'attempts':[],
                        'stale':False,'state':{'completed':['fixture']}}, wait_for_ack=True)
Path(os.environ['GOSI_WORKER_JOURNAL'], 'worker-after-ack').write_text('ack observed')
j.emit('complete', {'exit_code':0, 'state':{'phase':'complete'}})
'''
        result = self.run_worker(code)
        self.assertEqual(result['exit_code'], 0, result)
        self.assertEqual([e['kind'] for e in self.events], ['start_product', 'product_result', 'complete'])
        self.assertEqual(result['state'], {'phase': 'complete'})
        self.assertTrue((Path(result['journal_dir']) / 'worker-after-ack').exists())
        self.assertEqual(len(list(Path(result['journal_dir']).glob('*.ack'))), 3)

    def test_admission_refusal_is_truthful_failure_before_product_dispatch(self):
        def admission(event):
            self.events.append(event)
            return False if event['kind'] == 'start_product' else None
        result = self.run_worker('''
admission=j.emit('start_product', {'product_id':'fixture'}, wait_for_ack=True)
if admission.get('admitted') is False:
    j.emit('complete', {'exit_code':1, 'state':{'phase':'resource_limit','unattempted':['fixture']}}, wait_for_ack=True)
    sys.exit(1)
(j.directory/'unexpected-product-dispatch').write_text('bad')
j.emit('complete', {'exit_code':0})
''', callback=admission)
        self.assertEqual(result['exit_code'], 1, result)
        self.assertEqual(result['reason'], 'worker_reported_failure')
        self.assertIsNone(result['error'])
        self.assertFalse((Path(result['journal_dir'])/'unexpected-product-dispatch').exists())
        self.assertEqual([event['kind'] for event in self.events], ['start_product', 'complete'])
        self.assertFalse(json.loads((Path(result['journal_dir'])/'000001.ack').read_text())['admitted'])

    def test_body_rpc_and_shutdown_hangs_are_bounded(self):
        for phase in ('response_body', 'renderer_rpc', 'shutdown'):
            with self.subTest(phase=phase):
                result = self.run_worker(f'''
j.emit('start_product', {{'product_id':'fixture', 'state':{{'phase':{phase!r}}}}})
signal.signal(signal.SIGTERM, signal.SIG_IGN)
while True: time.sleep(1)
''')
                self.assertEqual(result['exit_code'], 124, result)
                self.assertTrue(result['timed_out'])
                self.assertEqual(result['state']['phase'], phase)

    def test_durable_stop_is_published_before_stuck_teardown_is_killed(self):
        published = self.root / 'published-stop-fixture.json'
        callback_times = []
        def publish(event):
            self.events.append(event)
            if event['kind'] == 'stop':
                # Substitute only a temporary fixture for canonical publication.
                with published.open('w') as stream:
                    json.dump(event['payload'], stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                callback_times.append(time.monotonic())
        result = self.run_worker('''
j.emit('stop', {'product_id':'fixture','code':403,'category':'auth','observed_at':'fixture'})
signal.signal(signal.SIGTERM, signal.SIG_IGN)
while True: time.sleep(1)
''', callback=publish)
        self.assertEqual(result['exit_code'], 2, result)
        self.assertTrue(result['stop_seen'])
        self.assertEqual(json.loads(published.read_text())['code'], 403)
        self.assertEqual(len(callback_times), 1)
        self.assertGreater(time.monotonic() - callback_times[0], .5)
        stop_event = Path(result['journal_dir']) / '000001.json'
        self.assertEqual(json.loads(stop_event.read_text())['payload']['code'], 403)

    def test_callback_failure_gets_no_ack_and_never_advances_worker(self):
        def reject(event):
            raise ValueError('fixture_publication_failure')
        result = self.run_worker('''
j.emit('product_result', {'product_id':'fixture'}, wait_for_ack=True)
Path(os.environ['GOSI_WORKER_JOURNAL'], 'after-rejected-event').write_text('bad')
j.emit('complete', {'exit_code':0})
''', callback=reject)
        self.assertNotEqual(result['exit_code'], 0)
        self.assertIn('fixture_publication_failure', result['error'])
        directory = Path(result['journal_dir'])
        self.assertFalse((directory / '000001.ack').exists())
        self.assertFalse((directory / 'after-rejected-event').exists())

    def test_exit_without_complete_is_failure(self):
        result = self.run_worker('pass')
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(result['reason'], 'missing_complete')

    def test_nonzero_complete_and_process_failure_are_not_success(self):
        result = self.run_worker("j.emit('complete', {'exit_code':7}); sys.exit(7)")
        self.assertEqual(result['exit_code'], 7)
        self.assertEqual(result['reason'], 'worker_reported_failure')
        result = self.run_worker("j.emit('complete', {'exit_code':0}); sys.exit(9)")
        self.assertEqual(result['exit_code'], 9)
        self.assertEqual(result['reason'], 'worker_exit_mismatch')
        result = self.run_worker("j.emit('complete', {'exit_code':7})")
        self.assertNotEqual(result['exit_code'], 0)
        self.assertEqual(result['reason'], 'worker_exit_mismatch')

    def test_cross_run_identity_partial_and_sequence_gaps_fail_closed(self):
        variants = {
            'nonce': "event['nonce']='0'*32",
            'run_id': "event['run_id']='another-run'",
            'baseline': "event['baseline_sha256']='0'*64",
            'sequence': "event['sequence']=2",
            'partial': "raw=b'{broken'",
        }
        for name, mutation in variants.items():
            with self.subTest(name=name):
                self.events.clear()
                result = self.run_worker('''
header=json.loads((j.directory/'header.json').read_text())
event={key:header[key] for key in ('schema_version','run_id','nonce','baseline_sha256')}
event.update(sequence=1,kind='complete',payload={'exit_code':0})
''' + (mutation + '\n' if name != 'partial' else '') + '''
raw=json.dumps(event).encode()
''' + (mutation + '\n' if name == 'partial' else '') + '''
(j.directory/'000001.json').write_bytes(raw)
while True: time.sleep(1)
''')
                self.assertEqual(result['exit_code'], 1, result)
                self.assertEqual(self.events, [])
        result = self.run_worker('''
(j.directory/'000002.json').write_text('{}')
while True: time.sleep(1)
''')
        self.assertEqual(result['exit_code'], 1)
        self.assertIn('sequence_gap', result['error'])

    def test_detached_double_fork_descendant_is_killed_and_reaped(self):
        result = self.run_worker('''
pid=os.fork()
if pid == 0:
    os.setsid()
    grandchild=os.fork()
    if grandchild:
        os._exit(0)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    (j.directory/'detached.pid').write_text(str(os.getpid()))
    while True: time.sleep(1)
os.waitpid(pid,0)
while not (j.directory/'detached.pid').exists(): time.sleep(.01)
j.emit('complete', {'exit_code':0})
''')
        self.assertEqual(result['exit_code'], 1, result)
        self.assertEqual(result['reason'], 'unexpected_descendants_after_complete')
        pid = int((Path(result['journal_dir']) / 'detached.pid').read_text())
        self.assertIn(pid, result['tracked_pids'])
        self.assertIn(pid, result['signalled_pids'])
        self.assertFalse(Path(f'/proc/{pid}').exists(), 'Detached descendant survived or remained zombie')

    def test_existing_sibling_and_supervisor_are_not_signalled(self):
        sibling = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            result = self.run_worker('while True: time.sleep(1)')
            self.assertEqual(result['exit_code'], 1)
            self.assertIn('requires_no_existing_children', result['error'])
            self.assertIsNone(result['worker_exit_code'])
            self.assertIsNone(sibling.poll())
            self.assertNotIn(sibling.pid, result['tracked_pids'])
            self.assertNotIn(os.getpid(), result['signalled_pids'])
        finally:
            sibling.terminate()
            sibling.wait(timeout=3)

    def test_timeout_budget_already_exhausted_never_spawns(self):
        with patch.object(runtime.subprocess, 'Popen') as spawn:
            result = runtime.run_supervised(['must-not-run'], journal_dir=self.root/'none',
                baseline_bytes=self.baseline, deadline=time.monotonic()+.1,
                cleanup_seconds=.2, on_event=self.events.append)
        spawn.assert_not_called()
        self.assertEqual(result['exit_code'], 124)
        self.assertFalse((self.root/'none').exists())


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gosi-journal-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.baseline = b'{"items":{}}'
        self.header = dict(schema_version=1, run_id='fixture:1', nonce='a'*32,
                           baseline_sha256=hashlib.sha256(self.baseline).hexdigest(),
                           deadline=time.monotonic()+.3)
        runtime._immutable(self.root/'baseline.json', self.baseline)
        runtime._immutable(self.root/'header.json', runtime._json_bytes(self.header))

    def test_stop_is_fsynced_before_return_and_events_are_exclusive(self):
        writer = runtime.JournalWriter(self.root)
        real_fsync = os.fsync
        with patch.object(runtime.os, 'fsync', wraps=real_fsync) as fsync:
            event = writer.emit('stop', {'code':429})
            self.assertGreaterEqual(fsync.call_count, 2)
        self.assertEqual(event['sequence'], 1)
        before = (self.root/'000001.json').read_bytes()
        with self.assertRaises(FileExistsError):
            runtime._immutable(self.root/'000001.json', b'overwrite')
        self.assertEqual((self.root/'000001.json').read_bytes(), before)

    def test_event_byte_count_and_total_bounds(self):
        writer = runtime.JournalWriter(self.root)
        with patch.object(runtime, 'MAX_EVENT_BYTES', 300):
            with self.assertRaises(runtime.JournalError):
                writer.emit('stop', {'padding':'x'*400})
        self.assertFalse((self.root/'000001.json').exists())
        with patch.object(runtime, 'MAX_EVENTS', 1):
            writer.emit('start_product', {})
            with self.assertRaises(runtime.JournalError):
                writer.emit('stop', {})

    def test_total_byte_budget_and_complete_order_are_enforced(self):
        writer = runtime.JournalWriter(self.root)
        with patch.object(runtime, 'MAX_TOTAL_BYTES', 10):
            with self.assertRaisesRegex(runtime.JournalError, 'total_size_bound'):
                writer.emit('start_product', {})
        writer.emit('complete', {'exit_code':0})
        with self.assertRaisesRegex(runtime.JournalError, 'kind_or_order'):
            writer.emit('stop', {'code':403})

    def test_missing_ack_is_bounded(self):
        writer = runtime.JournalWriter(self.root)
        started = time.monotonic()
        with self.assertRaisesRegex(runtime.JournalError, 'ack_deadline'):
            writer.emit('product_result', {}, wait_for_ack=True)
        self.assertLess(time.monotonic()-started, .6)

    def test_forged_ack_is_rejected(self):
        writer = runtime.JournalWriter(self.root)
        runtime._immutable(self.root/'000001.ack', b'{"accepted":true}')
        with self.assertRaisesRegex(runtime.JournalError, 'invalid_ack'):
            writer.emit('product_result', {}, wait_for_ack=True)

    def test_changed_accepted_event_is_rejected(self):
        writer = runtime.JournalWriter(self.root)
        writer.emit('stop', {'code':403})
        reader = runtime._Reader(self.root, self.header)
        reader.drain(lambda event: None)
        (self.root/'000001.json').chmod(0o600)
        (self.root/'000001.json').write_text('{}')
        with self.assertRaisesRegex(runtime.JournalError, 'accepted_event_changed'):
            reader.verify_retained()

    def test_partial_pending_event_is_not_accepted_or_discarded(self):
        reader = runtime._Reader(self.root, self.header)
        (self.root/'.pending-interrupted').write_bytes(b'{partial')
        reader.drain(lambda event: self.fail('A partial event was accepted'))
        with self.assertRaisesRegex(runtime.JournalError, 'partial_event_retained'):
            reader.verify_retained()
        self.assertEqual((self.root/'.pending-interrupted').read_bytes(), b'{partial')

    def test_baseline_mismatch_is_rejected(self):
        (self.root/'baseline.json').chmod(0o600)
        (self.root/'baseline.json').write_text('different')
        with self.assertRaisesRegex(runtime.JournalError, 'baseline_mismatch'):
            runtime.JournalWriter(self.root)

    def test_symlink_event_is_not_followed(self):
        unrelated = self.root/'retained'
        unrelated.write_text('retained')
        (self.root/'000001.json').symlink_to(unrelated)
        reader = runtime._Reader(self.root, self.header)
        with self.assertRaises(OSError):
            reader.drain(lambda event: self.fail('A symlink was accepted'))
        self.assertEqual(unrelated.read_text(), 'retained')

    def test_duplicate_keys_and_nonfinite_numbers_are_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}'):
            with self.assertRaises(ValueError):
                runtime._parse_json(raw)


@unittest.skipUnless(sys.platform == 'linux', 'Linux process containment is required')
class OuterGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gosi-outer-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def guard(self, code, duration=1.7, cleanup=.6):
        started = time.monotonic()
        outcome = runtime.run_guarded([sys.executable, '-B', '-c', code],
            deadline=started+duration, cleanup_seconds=cleanup, cwd=self.root,
            env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1'))
        self.assertLess(time.monotonic()-started, duration+.8, outcome)
        self.assertTrue(outcome['cleanup_confirmed'], outcome)
        return outcome

    def test_outer_guard_does_not_write_journal_or_fsync(self):
        with (patch.object(runtime, '_immutable', side_effect=AssertionError('outer journal')),
              patch.object(runtime.os, 'fsync', side_effect=AssertionError('outer fsync'))):
            result = self.guard('from scripts.daiso.gosi_collection_runtime import emit_guard_result; emit_guard_result(0)')
        self.assertEqual(result['exit_code'], 0, result)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_mismatched_oversized_and_forged_completion_fail(self):
        variants = (
            ('pass', 'missing_complete'),
            ('from scripts.daiso.gosi_collection_runtime import emit_guard_result; emit_guard_result(0); raise SystemExit(7)',
             'worker_exit_mismatch'),
            ("import os; os.write(int(os.environ['GOSI_GUARD_RESULT_FD']), b'x'*4097)", 'supervisor_error'),
            ("import os; os.write(int(os.environ['GOSI_GUARD_RESULT_FD']), b'{\"schema_version\":1,\"nonce\":\"wrong\",\"exit_code\":0}\\n')",
             'supervisor_error'),
            ("from scripts.daiso.gosi_collection_runtime import emit_guard_result; emit_guard_result(2); raise SystemExit(2)",
             'worker_reported_failure'),
        )
        for code, reason in variants:
            with self.subTest(reason=reason):
                result = self.guard(code)
                self.assertNotEqual(result['exit_code'], 0, result)
                self.assertEqual(result['reason'], reason, result)

    def test_inner_input_and_fsync_stalls_are_contained_without_extending_deadline(self):
        for phase in ('input', 'fsync'):
            with self.subTest(phase=phase):
                code = '''
import os, signal, time
from pathlib import Path
from scripts.daiso import gosi_collection_runtime as rt
signal.signal(signal.SIGTERM, signal.SIG_IGN)
def hang(*args, **kwargs):
    while True: time.sleep(1)
''' + ("rt._immutable=hang\n" if phase == 'input' else "rt.os.fsync=hang\n") + '''
rt.run_supervised(['must-not-start'], journal_dir=Path('journal-'''+phase+''''),
    baseline_bytes=b'{}', deadline=float(os.environ['GOSI_GUARD_DEADLINE_MONOTONIC']),
    cleanup_seconds=.4, on_event=lambda event: None)
rt.emit_guard_result(0)
'''
                result = self.guard(code)
                self.assertEqual(result['exit_code'], 124, result)
                self.assertTrue(result['timed_out'])

    def test_inner_ack_stall_preserves_stop_and_kills_nested_detached_children(self):
        worker = PREFIX + '''
pid=os.fork()
if pid == 0:
    os.setsid()
    child=os.fork()
    if child: os._exit(0)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    Path('nested-detached.pid').write_text(str(os.getpid()))
    while True: time.sleep(1)
os.waitpid(pid,0)
while not Path('nested-detached.pid').exists(): time.sleep(.01)
j.emit('stop', {'code':403, 'product_id':'fixture'}, wait_for_ack=True)
'''
        code = '''
import json, os, signal, sys, time
from pathlib import Path
from scripts.daiso import gosi_collection_runtime as rt
original=rt._immutable
def write(path, raw, **kwargs):
    if path.suffix == '.ack':
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        while True: time.sleep(1)
    return original(path, raw, **kwargs)
rt._immutable=write
def published(event):
    if event['kind']=='stop':
        with Path('durable-stop.json').open('w') as stream:
            json.dump(event,stream); stream.flush(); os.fsync(stream.fileno())
outcome=rt.run_supervised([sys.executable, '-B', '-c', '''+repr(worker)+'''],
    journal_dir=Path('inner-journal'), baseline_bytes=b'{"items":{}}',
    deadline=float(os.environ['GOSI_GUARD_DEADLINE_MONOTONIC']), cleanup_seconds=.4,
    on_event=published)
rt.emit_guard_result(outcome['exit_code'])
raise SystemExit(outcome['exit_code'])
'''
        result = self.guard(code, duration=2.0, cleanup=.7)
        self.assertEqual(result['exit_code'], 124, result)
        self.assertEqual(json.loads((self.root/'durable-stop.json').read_text())['payload']['code'], 403)
        self.assertTrue((self.root/'inner-journal/000001.json').is_file())
        self.assertFalse((self.root/'inner-journal/000001.ack').exists())
        pid = int((self.root/'nested-detached.pid').read_text())
        self.assertIn(pid, result['tracked_pids'])
        self.assertFalse(Path(f'/proc/{pid}').exists())

    def test_preexisting_child_is_rejected_before_subreaper_adoption(self):
        sibling = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            result = self.guard('raise RuntimeError("must never start")')
            self.assertEqual(result['exit_code'], 1)
            self.assertIn('requires_no_existing_children', result['error'])
            self.assertIsNone(result['worker_exit_code'])
            self.assertIsNone(sibling.poll())
            self.assertEqual(result['signalled_pids'], [])
        finally:
            sibling.terminate(); sibling.wait(timeout=3)

    def test_rejected_preexisting_child_can_fork_and_exit_without_orphan_signal(self):
        unrelated = '''
import os, signal, time
from pathlib import Path
while not Path('allow-fork').exists(): time.sleep(.01)
pid=os.fork()
if pid:
    os._exit(0)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path('unrelated-orphan.pid').write_text(str(os.getpid()))
while True: time.sleep(1)
'''
        code = '''
import os, signal, subprocess, sys, time
from pathlib import Path
from scripts.daiso import gosi_collection_runtime as rt
# The fixture itself adopts its unrelated orphan so it can safely reap it.
adopter=rt._ProcessTree()
parent=subprocess.Popen([sys.executable, '-B', '-c', '''+repr(unrelated)+'''])
outcome=rt.run_guarded(['must-not-start'], deadline=time.monotonic()+1,
                       cleanup_seconds=.2)
assert outcome['exit_code']==1 and not outcome['signalled_pids'], outcome
assert 'requires_no_existing_children' in outcome['error'], outcome
Path('allow-fork').write_text('go')
parent.wait(timeout=1)
until=time.monotonic()+1
while not Path('unrelated-orphan.pid').exists():
    assert time.monotonic()<until
    time.sleep(.01)
pid=int(Path('unrelated-orphan.pid').read_text())
os.kill(pid,0)
os.kill(pid,signal.SIGKILL)
os.waitpid(pid,0)
adopter.restore()
rt.emit_guard_result(0)
'''
        result = self.guard(code, duration=3, cleanup=.6)
        self.assertEqual(result['exit_code'], 0, result)
        self.assertEqual(result['signalled_pids'], [])


FAKE_PLAYWRIGHT_SOURCE = r'''
import json,os,sys,time
from pathlib import Path
from types import SimpleNamespace
MODE=os.environ['SYNTHETIC_GOSI_MODE']
EVENTS=Path(os.environ['SYNTHETIC_GOSI_EVENTS'])
def log(value):
    with EVENTS.open('a') as f:f.write(value+'\n')
class Request:
    url='https://www.daisomall.co.kr/fixture' + ('?'+'x'*1200000 if MODE=='metadata_growth' else '')
    resource_type='xhr'
class Response:
    url=Request.url
    status=200
    headers={'content-type':'application/json'}
    def __init__(self,status=200):self.status=status;self.request=Request()
    def body(self):
        log('body')
        if MODE=='body_hang':time.sleep(60)
        if MODE in ('unicode_growth','growth_and_stop'):return json.dumps({'notice':'제조국: '+'가'*400000},ensure_ascii=False).encode()
        return b'{"notice":"\\uc81c\\uc870\\uad6d: country"}'
class Button:
    @property
    def first(self):return self
    def wait_for(self,**kwargs):pass
    def count(self):return 0
class Page:
    def __init__(self):self.handlers={};self.mouse=SimpleNamespace(wheel=lambda *a:log('wheel'))
    def on(self,event,callback):self.handlers[event]=callback
    def response(self,status):
        response=Response(status)
        self.handlers['request'](response.request)
        self.handlers['response'](response)
        self.handlers['requestfinished'](response.request)
    def goto(self,*args,**kwargs):
        log('goto');self.response(403 if MODE=='close_hang_after403' else 200)
    def locator(self,*args):return Button()
    def wait_for_timeout(self,*args):pass
    def evaluate(self,js):
        log('evaluate')
        if 'querySelectorAll' not in js:return [100,100]
        return '제조국: '+('가'*400000 if MODE in ('unicode_growth','growth_and_stop') else 'country')
    def close(self):
        log('page_close')
        if MODE=='close_hang_after403':time.sleep(60)
        if MODE=='growth_and_stop':self.response(403)
class Context:
    def new_page(self):
        log('new_page');page=Page()
        if MODE=='delay_denial':
            actual_time=time
            def delayed(seconds):
                log('delay');page.response(403)
            sys.modules['__main__'].time=SimpleNamespace(monotonic=actual_time.monotonic,sleep=delayed)
        return page
    def close(self):log('context_close')
class Browser:
    def new_context(self,**kwargs):return Context()
    def close(self):log('browser_close')
class Playwright:
    chromium=SimpleNamespace(launch=lambda **kwargs:Browser())
    def __enter__(self):return self
    def __exit__(self,*args):
        log('playwright_exit')
        if MODE=='exit_hang':time.sleep(60)
sync_playwright=Playwright
'''


class WorkerIntegrationTests(unittest.TestCase):
    def setUp(self):
        import subprocess
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'data').mkdir();(self.root/'config').mkdir()
        self.original={'items':{'1234567':{'product_id':'1234567','maker':'retained fact','captured_at':'original'}}}
        self.raw=(json.dumps(self.original)+'\n').encode()
        (self.root/'data/gosi.json').write_bytes(self.raw)
        (self.root/'config/publish_policy.json').write_text(json.dumps({'identity_fields':['pd_no','product_id']}))
        for command in (['git','init','-q',str(self.root)],['git','-C',str(self.root),'add','data/gosi.json','config/publish_policy.json'],
                        ['git','-C',str(self.root),'-c','user.name=Offline Fixture','-c','user.email=fixture@example.invalid','commit','-qm','synthetic baseline']):
            subprocess.run(command,check=True,capture_output=True)
        fake=self.root/'fake';package=fake/'playwright';package.mkdir(parents=True)
        (package/'__init__.py').write_text('')
        (package/'sync_api.py').write_text(FAKE_PLAYWRIGHT_SOURCE)
        self.events=self.root/'browser-events'
        self.report=self.root/'collection-report.json'
        self.env=dict(RUNNER_TEMP=str(self.root),PYTHONPATH=str(fake),
                      SYNTHETIC_GOSI_EVENTS=str(self.events),GOSI_COLLECTION_REPORT=str(self.report),
                      DAISO_GOSI_BUDGET_SECONDS='2.5',DAISO_GOSI_CLEANUP_SECONDS='0.8',
                      GITHUB_ACTIONS='false')
    def run_mode(self,mode,targets=None,budget=None):
        env=dict(self.env,SYNTHETIC_GOSI_MODE=mode)
        if budget:env['DAISO_GOSI_BUDGET_SECONDS']=str(budget)
        with patch.dict(os.environ,env),patch.object(collector,'ROOT',self.root), \
             patch.object(collector,'GOSI',self.root/'data/gosi.json'):
            return collector.run_collection_supervisor(copy.deepcopy(self.original), targets or ['1234567'])
    def assert_preserved(self):
        doc=json.loads((self.root/'data/gosi.json').read_text())
        for key,value in self.original['items']['1234567'].items():
            actual=doc['items']['1234567'][key]
            self.assertEqual(actual[:len(value)] if isinstance(value,list) else actual,value)
        archive=self.root/history.HISTORY_PATH/(history.sha(self.raw)+'.json')
        self.assertEqual(archive.read_bytes(),self.raw)
        return doc
    def test_real_worker_parent_and_publisher_complete_offline(self):
        self.assertEqual(self.run_mode('normal'),0)
        doc=self.assert_preserved();obs=doc['items']['1234567']['field_observations']['origin']
        raw=b'{"notice":"\\uc81c\\uc870\\uad6d: country"}'
        self.assertEqual(obs['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertFalse(obs['human_verified']);self.assertFalse(obs['product_identity_verified'])
        self.assertFalse((self.root/'.gosi-collection.pending').exists())
        report=json.loads(self.report.read_text());self.assertEqual(report['completed'],['1234567'])
        events=self.events.read_text().splitlines()
        self.assertEqual(events.count('page_close'),1);self.assertEqual(events.count('context_close'),1)
    def test_body_rpc_hang_is_failed_and_started_attempt_survives(self):
        started=time.monotonic();self.assertEqual(self.run_mode('body_hang'),124)
        self.assertLess(time.monotonic()-started,3.5)
        doc=self.assert_preserved();row=doc['items']['1234567']
        self.assertNotIn('origin',row)
        self.assertEqual([x['status'] for x in row['observation_attempts']],['started','interrupted'])
        self.assertFalse((self.root/'.gosi-collection.pending').exists())
    def test_403_checkpoint_survives_hung_page_teardown(self):
        self.assertEqual(self.run_mode('close_hang_after403'),2)
        doc=self.assert_preserved();self.assertEqual(doc['provider_stops'][0]['code'],403)
        events=self.events.read_text().splitlines()
        self.assertEqual(events.count('goto'),1)
        self.assertNotIn('body',events);self.assertNotIn('wheel',events);self.assertNotIn('evaluate',events)
    def test_source_checkpoint_survives_hung_playwright_exit(self):
        self.assertEqual(self.run_mode('exit_hang'),124)
        doc=self.assert_preserved();self.assertEqual(doc['items']['1234567']['origin'],'country')
        self.assertFalse(doc['items']['1234567']['field_observations']['origin']['verified'])
        self.assertTrue(json.loads(self.report.read_text())['timed_out'])
    def test_denial_during_delay_prevents_next_page_and_goto(self):
        # Long synthetic budget permits the existing required 30-second delay;
        # fake sleep injects denial immediately without a real wait or request.
        self.assertEqual(self.run_mode('delay_denial',['1234567','1234568'],budget=60),2)
        events=self.events.read_text().splitlines()
        self.assertEqual(events.count('new_page'),1);self.assertEqual(events.count('goto'),1)
        self.assertIn('delay',events)
        doc=self.assert_preserved();self.assertEqual(doc['provider_stops'][0]['code'],403)
        report=json.loads(self.report.read_text());self.assertEqual(report['unattempted'],['1234568'])
    def run_guarded_mode(self, mode, *, stall_parent=False):
        real_popen=subprocess.Popen
        code=("import sys,time; from pathlib import Path; "
              f"sys.path.insert(0,{str(ROOT)!r}); "
              "from scripts.daiso import collect_gosi_alt as c; "
              f"c.ROOT=Path({str(self.root)!r}); c.GOSI=c.ROOT/'data/gosi.json'; "
              "c.targets=lambda arguments=None:['1234567']; ")
        if stall_parent:
            code+="c._publish_checkpoint=lambda *a,**k:time.sleep(60); "
        code+="raise SystemExit(c.guarded_collection_worker())"
        def worker(command,*args,**kwargs):
            if '--guarded-collection' in command:
                command=[sys.executable,'-B','-c',code]
            return real_popen(command,*args,**kwargs)
        with patch.dict(os.environ,dict(self.env,SYNTHETIC_GOSI_MODE=mode)), \
             patch.object(subprocess,'Popen',side_effect=worker):
            return collector.run_guarded_collection([])

    def test_actual_guarded_entrypoint_completes_with_shared_budget(self):
        self.assertEqual(self.run_guarded_mode('normal'),0)
        doc=self.assert_preserved()
        self.assertEqual(doc['items']['1234567']['origin'],'country')
        self.assertFalse((self.root/'.gosi-collection.pending').exists())

    def test_guarded_parent_publication_stall_keeps_pending_evidence(self):
        started=time.monotonic()
        self.assertEqual(self.run_guarded_mode('normal',stall_parent=True),124)
        self.assertLess(time.monotonic()-started,3.5)
        self.assertTrue((self.root/'.gosi-collection.pending').exists())
        self.assertEqual((self.root/'data/gosi.json').read_bytes(),self.raw)
        self.assertFalse(self.events.exists())
        marker=json.loads((self.root/'.gosi-collection.pending').read_bytes())
        self.assertTrue((Path(marker['journal_dir'])/'000001.json').exists())
        self.assertFalse((Path(marker['journal_dir'])/'000001.ack').exists())

    def test_capacity_refusal_precedes_browser_and_remains_unattempted(self):
        with patch('scripts.gosi_safety_checkpoint.collection_admission',return_value=False):
            self.assertEqual(self.run_mode('normal'),1)
        self.assertFalse(self.events.exists())
        self.assertEqual((self.root/'data/gosi.json').read_bytes(),self.raw)
        self.assertFalse((self.root/'.gosi-collection.pending').exists())
        report=json.loads(self.report.read_text())
        self.assertEqual(report['attempted'],[])
        self.assertEqual(report['unattempted'],['1234567'])
        self.assertEqual(report['admission_refused'],['1234567'])
        self.assertEqual(report['state']['reason'],'checkpoint_capacity')

    def test_serialized_unicode_and_metadata_growth_publish_no_new_fields(self):
        for mode in ('unicode_growth','metadata_growth'):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_mode(mode,budget=5),1)
                doc=self.assert_preserved();row=doc['items']['1234567']
                self.assertNotIn('origin',row)
                self.assertIn('product_document_growth_limit',
                    [a.get('reason') for a in row['observation_attempts']])
                self.assertFalse((self.root/'.gosi-collection.pending').exists())
                report=json.loads(self.report.read_text())
                self.assertEqual(report['completed'],[])
                self.assertTrue(report['reconciled'])
                # Each follow-up fixture starts from the entire retained document.
                self.original=doc

    def test_stop_survives_oversized_result_without_fields(self):
        self.assertEqual(self.run_mode('growth_and_stop',budget=5),2)
        doc=self.assert_preserved()
        self.assertNotIn('origin',doc['items']['1234567'])
        self.assertEqual(doc['provider_stops'][0]['code'],403)
        self.assertIn('product_document_growth_limit',
            [a.get('reason') for a in doc['items']['1234567']['observation_attempts']])
        self.assertFalse((self.root/'.gosi-collection.pending').exists())

    def test_hanging_publisher_is_bounded_without_commit_claim(self):
        import subprocess
        real_popen=subprocess.Popen
        def hanging(command,*args,**kwargs):
            if '--publish-checkpoint' in command:
                command=[sys.executable,'-c','import time; time.sleep(60)']
            return real_popen(command,*args,**kwargs)
        started=time.monotonic()
        with patch.object(subprocess,'Popen',side_effect=hanging):
            self.assertEqual(self.run_mode('normal'),1)
        self.assertLess(time.monotonic()-started,3.5)
        self.assertTrue((self.root/'.gosi-collection.pending').exists())
        self.assertEqual((self.root/'data/gosi.json').read_bytes(),self.raw)
        report=json.loads(self.report.read_text());self.assertFalse(report['reconciled'])


class ActualCliTests(unittest.TestCase):
    assert_preserved = WorkerIntegrationTests.assert_preserved

    def setUp(self):
        WorkerIntegrationTests.setUp(self)
        script=self.root/'scripts/daiso/collect_gosi_alt.py'
        script.parent.mkdir(parents=True)
        script.write_bytes(Path(collector.__file__).read_bytes())
        self.script=script
        self.score=self.root/'data/daiso_real/shopify_demand_score.json'
        self.score.parent.mkdir()
        self.score.write_text(json.dumps({'all_scored':[{'pd_no':'1234567','grade':'S'},
                                                     {'pd_no':'1234568','grade':'A'}]}))
        self.registry=self.root/'data/shopify_daily_registry.json'
        self.registry.write_text(json.dumps({'items':[]}))
        self.env['PYTHONPATH']=self.env['PYTHONPATH']+os.pathsep+str(ROOT)

    def cli(self,arguments=(),mode='normal'):
        # Same CLI spelling/cwd/env shape as Deep; no target or entrypoint mocks.
        budget=float(self.env['DAISO_GOSI_BUDGET_SECONDS'])
        environment=dict(os.environ,**self.env,SYNTHETIC_GOSI_MODE=mode,
            DAISO_GOSI_DEADLINE_MONOTONIC=str(time.monotonic()+budget))
        return subprocess.run([sys.executable,'-u','scripts/daiso/collect_gosi_alt.py',*arguments],
            cwd=self.root,env=environment,text=True,capture_output=True,timeout=budget+2)

    def test_cli_default_discovery_enters_real_worker(self):
        result=self.cli()
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(self.report.read_text())
        self.assertEqual(report['selected'],['1234567'])
        self.assertEqual(report['completed'],['1234567'])
        self.assertIn('goto',self.events.read_text().splitlines())
        self.assertNotIn('collection_no_op',result.stdout)
        self.assertEqual(self.assert_preserved()['items']['1234567']['origin'],'country')

    def test_cli_explicit_scope_does_not_expand_to_default_targets(self):
        result=self.cli(['1234568'])
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(self.report.read_text())
        self.assertEqual(report['selected'],['1234568'])
        self.assertEqual(report['completed'],['1234568'])
        doc=self.assert_preserved()
        self.assertNotIn('origin',doc['items']['1234567'])
        self.assertEqual(doc['items']['1234568']['origin'],'country')

    def test_cli_explicit_order_and_unattempted_survive_body_hang(self):
        result=self.cli(['001234568','1234567'],mode='body_hang')
        self.assertEqual(result.returncode,124,result.stderr)
        report=json.loads(self.report.read_text())
        self.assertEqual(report['selected'],['001234568','1234567'])
        self.assertEqual(report['attempted'],['001234568'])
        self.assertEqual(report['unattempted'],['1234567'])
        self.assertEqual(self.events.read_text().splitlines().count('goto'),1)
        self.assertNotIn('collection_no_op',result.stdout)

    def test_cli_unknown_mixed_reserved_and_duplicate_arguments_fail(self):
        for arguments in (['--unknown'],['--check-access-only','1234567'],
                          ['1234567','--unknown'],['--guarded-collection'],
                          ['--collection-worker'],['--publish-checkpoint'],
                          ['1234567','1234567'],['123/456'],['123abc']):
            with self.subTest(arguments=arguments):
                result=self.cli(arguments)
                self.assertNotEqual(result.returncode,0)
                self.assertNotIn('collection_no_op',result.stdout)
                self.assertFalse(self.events.exists())
                self.assertFalse(self.report.exists())
                self.assertEqual((self.root/'data/gosi.json').read_bytes(),self.raw)

    def test_cli_no_op_requires_valid_empty_discovery_inputs(self):
        self.score.write_text(json.dumps({'all_scored':[]}))
        result=self.cli()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('collection_no_op',result.stdout)
        self.assertIn('no_eligible_targets',result.stdout)
        self.assertIn(hashlib.sha256(self.score.read_bytes()).hexdigest(),result.stdout)
        self.assertFalse(self.events.exists())
        self.assertEqual((self.root/'data/gosi.json').read_bytes(),self.raw)

    def test_cli_discovery_parse_missing_and_shape_errors_are_failures(self):
        for payload in ('{', '{}', '{"all_scored":"wrong"}', None):
            with self.subTest(payload=payload):
                if payload is None:self.score.unlink()
                else:self.score.write_text(payload)
                result=self.cli()
                self.assertNotEqual(result.returncode,0)
                self.assertNotIn('collection_no_op',result.stdout)
                self.assertFalse(self.events.exists())
                self.assertEqual((self.root/'data/gosi.json').read_bytes(),self.raw)

    def test_api_argument_boundary_rejects_ambiguous_and_internal_scope(self):
        for value in ('1234567', ['--guarded-collection'], ['--check-access-only'],
                      ['1234567','--force'], [1234567], ['1234567','1234567']):
            with self.subTest(value=value), self.assertRaises(ValueError):
                collector.targets(value)
        self.assertEqual(collector.targets(['001234568','1234567']),['001234568','1234567'])

    def test_cli_invalid_target_limit_cannot_manufacture_no_op(self):
        for value in ('0','-1'):
            with self.subTest(value=value):
                self.env['DAISO_GOSI_MAX']=value
                result=self.cli()
                self.assertNotEqual(result.returncode,0)
                self.assertNotIn('collection_no_op',result.stdout)
                self.assertFalse(self.events.exists())

    def test_cli_five_mib_published_canonical_can_run_twice(self):
        self.original['fixture_padding']='x'*(5*1024*1024)
        self.raw=(json.dumps(self.original)+'\n').encode()
        (self.root/'data/gosi.json').write_bytes(self.raw)
        self.env['DAISO_GOSI_BUDGET_SECONDS']='10'
        for execution in range(2):
            # Simulate the ordinary immutable Git publication boundary before
            # each clean run. All prior source/history bytes remain committed.
            for command in (['git','-C',str(self.root),'add','data'],
                            ['git','-C',str(self.root),'-c','user.name=Offline Fixture',
                             '-c','user.email=fixture@example.invalid','commit','-qm',f'large baseline {execution}']):
                subprocess.run(command,check=True,capture_output=True)
            baseline=(self.root/'data/gosi.json').read_bytes()
            self.assertGreater(len(baseline),runtime.MAX_EVENT_BYTES)
            self.assertLess(len(baseline),runtime.MAX_BASELINE_BYTES)
            result=self.cli()
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(self.report.read_text())
            self.assertEqual(report['completed'],['1234567'])
            self.assertEqual((Path(report['journal_dir'])/'baseline.json').read_bytes(),baseline)
            self.assertEqual(self.assert_preserved()['fixture_padding'],self.original['fixture_padding'])

    def test_baseline_limit_is_separate_and_oversize_rejected_before_spawn(self):
        self.assertEqual(runtime.MAX_BASELINE_BYTES,collector.MAX_CHECKPOINT_DOCUMENT_BYTES)
        self.assertEqual(runtime.MAX_EVENT_BYTES,4*1024*1024)
        directory=self.root/'oversize-journal'
        with patch.object(runtime.subprocess,'Popen',side_effect=AssertionError('must not spawn')):
            with self.assertRaisesRegex(ValueError,'invalid_supervisor_bounds'):
                runtime.run_supervised(['unused'],journal_dir=directory,
                    baseline_bytes=b'x'*(runtime.MAX_BASELINE_BYTES+1),
                    deadline=time.monotonic()+1,cleanup_seconds=.2,on_event=lambda e:None)
        self.assertFalse(directory.exists())
        with self.assertRaisesRegex(runtime.JournalError,'journal_event_too_large'):
            runtime._immutable(self.root/'000001.json',b'x'*(runtime.MAX_EVENT_BYTES+1))
        self.assertFalse((self.root/'000001.json').exists())

    def test_cli_access_only_is_read_only_and_does_not_discover_targets(self):
        self.score.unlink()
        result=self.cli(['--check-access-only'])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(self.events.exists())
        self.assertNotIn('collection_no_op',result.stdout)
        self.assertEqual((self.root/'data/gosi.json').read_bytes(),self.raw)


if __name__ == '__main__':
    unittest.main(verbosity=2)
