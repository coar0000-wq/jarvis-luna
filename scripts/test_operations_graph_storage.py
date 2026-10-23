"""Offline lossless graph storage tests. No production writes or network calls."""
import copy
import hashlib
import json
import unittest
from unittest.mock import Mock, patch

import operations_graph_storage as storage


def raw(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'),
                       allow_nan=False) + '\n').encode('utf-8')


def graph():
    # Deliberately nonalphabetical object fields and non-sorted record IDs.
    return {'revision': {'z': 4, 'a': None},
            'edges': [{'target': 'a', 'id': 'e2', 'source': 'z', 'unknown': [False, 1.25]},
                      {'id': 'e1', 'source': 'a', 'target': 'z'}],
            'annotations': ['한글  \t\n', {'nested': [1, 'é', True]}],
            'nodes': [{'payload': {'z': '한글  \t\n', 'a': 2}, 'id': 'z'},
                      {'id': 'a', 'complete_original': 'x' * 400}],
            'last': 'unchanged'}


class GraphStorageTests(unittest.TestCase):
    def bundle(self, value=None):
        with patch.object(storage, 'GRAPH_SEGMENT_TARGET_BYTES', 64):
            return storage.prepare_operations_graph(graph() if value is None else value, force=True)

    def manifest(self, files):
        return json.loads(files[storage.GRAPH_PATH])

    def mutate(self, files, mutate):
        files = dict(files)
        manifest = self.manifest(files)
        mutate(manifest[storage.STORAGE_KEY])
        files[storage.GRAPH_PATH] = raw(manifest)
        return files

    def rebind(self, files, index, value):
        manifest = self.manifest(files)
        item = manifest[storage.STORAGE_KEY]['segments'][index]
        body = raw(value)
        digest = hashlib.sha256(body).hexdigest()
        path = storage.GRAPH_DIRECTORY + '/segment-' + digest + '.json'
        item.update(path=path, sha256=digest, bytes=len(body))
        files[path] = body
        files[storage.GRAPH_PATH] = raw(manifest)

    def test_constants_reuse_bounds_without_increasing_any_file_limit(self):
        self.assertEqual(storage.GRAPH_MAX_BYTES, 32 * 1024 * 1024)
        self.assertEqual(storage.GRAPH_MEMBER_MAX_BYTES, 8 * 1024 * 1024)
        self.assertEqual(storage.GRAPH_SEGMENT_TARGET_BYTES, 1024 * 1024)
        self.assertEqual(storage.GRAPH_LOGICAL_MAX_BYTES, storage.OPS_LOGICAL_MAX_BYTES)
        self.assertEqual(storage.GRAPH_AGGREGATE_MAX_BYTES, 120 * 1024 * 1024)

    def test_legacy_preserves_every_field_order_literal_and_input(self):
        value = graph()
        before = copy.deepcopy(value)
        files = storage.prepare_operations_graph(value)
        self.assertEqual(list(files), [storage.GRAPH_PATH])
        self.assertEqual(files[storage.GRAPH_PATH], raw(value))
        loaded = storage.load_operations_graph(files[storage.GRAPH_PATH])
        self.assertEqual(raw(loaded), raw(before))
        self.assertEqual(value, before)
        self.assertEqual(storage.graph_members(files[storage.GRAPH_PATH]), ())
        self.assertFalse(storage.is_graph_manifest(files[storage.GRAPH_PATH]))

    def test_legacy_loose_shapes_remain_compatible(self):
        for value in ({'nodes': [{'literal': 'old graph'}], 'edges': []},
                      {'nodes': ['old graph']}, {},
                      {'nodes': [{'id': 'n'}, {'id': 'n'}], 'edges': []}):
            with self.subTest(value=value):
                body = storage.prepare_operations_graph(value)[storage.GRAPH_PATH]
                self.assertEqual(storage.load_operations_graph(body), value)
                self.assertEqual(storage.load_operations_graph(json.dumps(value, indent=2).encode()), value)
                with self.assertRaises(ValueError):
                    storage.prepare_operations_graph(value, force=True)

    def test_segment_roundtrip_preserves_metadata_and_all_order(self):
        value = graph()
        before = raw(value)
        files = self.bundle(value)
        manifest = self.manifest(files)[storage.STORAGE_KEY]
        loaded = storage.load_operations_graph(files[storage.GRAPH_PATH], files.__getitem__)
        self.assertEqual(raw(loaded), before)
        self.assertEqual(raw(value), before)
        self.assertTrue(storage.is_graph_manifest(files[storage.GRAPH_PATH]))
        self.assertEqual(storage.graph_members(files[storage.GRAPH_PATH]), tuple(list(files)[:-1]))
        self.assertEqual(manifest['counts'], {'nodes': 2, 'edges': 2})
        self.assertEqual(manifest['logical_bytes'], len(before))
        self.assertEqual(manifest['logical_sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(files, self.bundle(value))
        for name, body in files.items():
            if name != storage.GRAPH_PATH:
                self.assertEqual(storage.validate_graph_member(name, body), json.loads(body))

    def test_empty_graph_manifest_retains_metadata_without_reader(self):
        value = {'a': {'original': [1, 2]}, 'nodes': [], 'edges': []}
        files = self.bundle(value)
        self.assertEqual(storage.graph_members(files[storage.GRAPH_PATH]), ())
        self.assertEqual(storage.load_operations_graph(files[storage.GRAPH_PATH]), value)

    def test_real_larger_than_32mib_roundtrip_is_lossless(self):
        # Distinct IDs, full repeated literals, two collections, and metadata.
        # One string is shared in memory; serialized bytes really exceed 32 MiB.
        text = '한글0123456789  \t\n' * 2500
        value = {'nodes': [{'id': 'n' + str(i), 'payload': text, 'ordinal': i}
                           for i in range(710)],
                 'edges': [{'id': 'e' + str(i), 'source': 'n' + str(i),
                            'target': 'n0', 'full_evidence': [i, text[:31]]}
                           for i in range(710)],
                 'meta': {'all': True, 'unknown': None}}
        logical = raw(value)
        self.assertGreater(len(logical), storage.GRAPH_MAX_BYTES)
        files = storage.prepare_operations_graph(value)
        self.assertGreater(len(files), 2)
        self.assertLessEqual(len(files[storage.GRAPH_PATH]), storage.GRAPH_MAX_BYTES)
        self.assertTrue(all(len(body) <= storage.GRAPH_MEMBER_MAX_BYTES
                            for name, body in files.items() if name != storage.GRAPH_PATH))
        self.assertEqual(raw(storage.load_operations_graph(files[storage.GRAPH_PATH], files.__getitem__)), logical)

    def test_missing_member_and_missing_reader_rejected(self):
        files = self.bundle()
        body = files[storage.GRAPH_PATH]
        with self.assertRaisesRegex(ValueError, 'reader required'):
            storage.load_operations_graph(body)
        for error in (KeyError('missing'), FileNotFoundError('missing')):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, 'member missing'):
                storage.load_operations_graph(body, Mock(side_effect=error))

    def test_hash_corrupt_and_wrong_declared_size_rejected(self):
        files = self.bundle()
        member = storage.graph_members(files[storage.GRAPH_PATH])[0]
        files[member] = files[member].replace(b'payload', b'Payload', 1)
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            storage.load_operations_graph(files[storage.GRAPH_PATH], files.__getitem__)
        files[member] += b' '
        with self.assertRaisesRegex(ValueError, 'size/reference mismatch'):
            storage.load_operations_graph(files[storage.GRAPH_PATH], files.__getitem__)

    def test_manifest_missing_extra_and_boolean_fields_rejected(self):
        cases = [lambda m: m.pop('counts'), lambda m: m.update(extra=True),
                 lambda m: m.update(schema_version=True),
                 lambda m: m.update(logical_bytes=True),
                 lambda m: m['counts'].update(nodes=True),
                 lambda m: m.update(field_order=['nodes', 'nodes', 'edges']),
                 lambda m: m['metadata'].update(nodes=[]),
                 lambda m: m['segments'][0].update(extra=True),
                 lambda m: m['segments'][0].update(bytes=True),
                 lambda m: m['segments'][0].update(start=True),
                 lambda m: m['segments'][0].update(records=True),
                 lambda m: m['segments'][0].update(sha256='A' * 64)]
        for index, change in enumerate(cases):
            files = self.mutate(self.bundle(), change)
            reader = Mock(side_effect=AssertionError('must validate before read'))
            with self.subTest(case=index), self.assertRaises(ValueError):
                storage.load_operations_graph(files[storage.GRAPH_PATH], reader)
            reader.assert_not_called()
        files = self.bundle()
        manifest = self.manifest(files)
        manifest['extra'] = True
        with self.assertRaisesRegex(ValueError, 'manifest schema'):
            storage.graph_members(raw(manifest))

    def test_missing_extra_reordered_and_repeated_references_rejected(self):
        changes = [lambda m: m['segments'].pop(),
                   lambda m: m['segments'].reverse(),
                   lambda m: m['segments'].append(copy.deepcopy(m['segments'][0]))]
        for change in changes:
            files = self.mutate(self.bundle(), change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                storage.graph_members(files[storage.GRAPH_PATH])

    def test_rebinding_order_indices_still_fails_logical_order_binding(self):
        files = self.bundle()
        manifest = self.manifest(files)
        meta = manifest[storage.STORAGE_KEY]
        self.assertEqual(meta['segments'][0]['scope'], meta['segments'][1]['scope'])
        first, second = meta['segments'][0], meta['segments'][1]
        meta['segments'][0], meta['segments'][1] = second, first
        files[storage.GRAPH_PATH] = raw(manifest)
        with self.assertRaisesRegex(ValueError, 'logical digest/size'):
            storage.load_operations_graph(files[storage.GRAPH_PATH], files.__getitem__)

    def test_member_unknown_missing_wrong_type_and_noncanonical_rejected(self):
        files = self.bundle()
        name = storage.graph_members(files[storage.GRAPH_PATH])[0]
        original = json.loads(files[name])
        for change in (lambda s: s.update(extra=True), lambda s: s.pop('scope'),
                       lambda s: s.update(schema_version=True),
                       lambda s: s.update(start=0), lambda s: s.update(records=[]),
                       lambda s: s.update(scope='metadata'), lambda s: s.update(records=[{}])):
            segment = copy.deepcopy(original)
            change(segment)
            body = raw(segment)
            path = storage.GRAPH_DIRECTORY + '/segment-' + hashlib.sha256(body).hexdigest() + '.json'
            with self.subTest(change=change), self.assertRaises(ValueError):
                storage.validate_graph_member(path, body)
        body = json.dumps(original, indent=2).encode()
        path = storage.GRAPH_DIRECTORY + '/segment-' + hashlib.sha256(body).hexdigest() + '.json'
        with self.assertRaisesRegex(ValueError, 'canonical'):
            storage.validate_graph_member(path, body)

    def test_duplicate_ids_are_rejected_within_and_across_segments(self):
        for scope in storage.SCOPES:
            value = graph()
            value[scope].append(copy.deepcopy(value[scope][0]))
            with self.subTest(scope=scope), self.assertRaisesRegex(ValueError, 'duplicate record ID'):
                self.bundle(value)
        files = self.bundle()
        refs = self.manifest(files)[storage.STORAGE_KEY]['segments']
        segment = json.loads(files[refs[1]['path']])
        segment['records'][0]['id'] = 'z'
        self.rebind(files, 1, segment)
        with self.assertRaisesRegex(ValueError, 'duplicate record ID'):
            storage.load_operations_graph(files[storage.GRAPH_PATH], files.__getitem__)

    def test_same_id_in_different_scopes_is_not_a_duplicate(self):
        value = {'nodes': [{'id': 'shared'}], 'edges': [{'id': 'shared'}]}
        files = self.bundle(value)
        self.assertEqual(storage.load_operations_graph(files[storage.GRAPH_PATH], files.__getitem__), value)

    def test_logical_digest_size_metadata_and_order_bound(self):
        for change in (lambda m: m.update(logical_sha256='0' * 64),
                       lambda m: m.update(logical_bytes=m['logical_bytes'] + 1),
                       lambda m: m['metadata']['revision'].update(a=9),
                       lambda m: m['field_order'].remove('nodes') or m['field_order'].append('nodes')):
            files = self.mutate(self.bundle(), change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'logical digest/size'):
                storage.load_operations_graph(files[storage.GRAPH_PATH], files.__getitem__)

    def test_json_duplicate_keys_nonfinite_and_invalid_utf8_rejected(self):
        bad = [b'{"nodes":[],"nodes":[],"edges":[]}',
               b'{"nodes":[],"extra":{"a":1,"a":2}}',
               b'{"nodes":[NaN]}', b'{"nodes":[Infinity]}',
               b'{"nodes":[-Infinity]}', b'{"nodes":[1e999]}',
               b'{"nodes":["\xff"]}', b'[]']
        for body in bad:
            with self.subTest(body=body), self.assertRaises(ValueError):
                storage.load_operations_graph(body)
        for body in (b'{"schema_version":1,"schema_version":1}', b'{"value":NaN}', b'{"value":1e999}'):
            path = storage.GRAPH_DIRECTORY + '/segment-' + hashlib.sha256(body).hexdigest() + '.json'
            with self.subTest(body=body), self.assertRaises(ValueError):
                storage.validate_graph_member(path, body)

    def test_prepare_rejects_non_json_lossy_types_and_cycles(self):
        circular = []; circular.append(circular)
        for value in ({1: 'integer key'}, {'x': (1, 2)}, {'x': float('nan')},
                      {'x': float('inf')}, {'x': set()}, {'x': circular},
                      {'x': '\ud800'}, {storage.STORAGE_KEY: {}}):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                storage.prepare_operations_graph(value)

    def test_path_checks_are_exact_before_reader(self):
        files = self.bundle()
        name = storage.graph_members(files[storage.GRAPH_PATH])[0]
        for path in ('../' + name, '/' + name, name.replace('/', '\\'),
                     name.replace('/segment-', '/../segment-'), name.upper(), name + '/',
                     name.replace('knowledge_graph/', 'other/'), None, []):
            with self.subTest(path=path):
                self.assertFalse(storage.is_graph_member(path))
                with self.assertRaisesRegex(ValueError, 'path invalid'):
                    storage.validate_graph_member(path, b'{}')
                reader = Mock()
                altered = self.mutate(files, lambda m: m['segments'][0].update(path=path))
                with self.assertRaises(ValueError):
                    storage.load_operations_graph(altered[storage.GRAPH_PATH], reader)
                reader.assert_not_called()

    def test_actual_and_declared_oversized_member_rejected_before_parse(self):
        files = self.bundle()
        name = storage.graph_members(files[storage.GRAPH_PATH])[0]
        with patch.object(storage, '_json', side_effect=AssertionError('no decode')):
            with self.assertRaisesRegex(ValueError, 'size invalid'):
                storage.validate_graph_member(name, b'x' * (storage.GRAPH_MEMBER_MAX_BYTES + 1))
        altered = self.mutate(files, lambda m: m['segments'][0].update(bytes=storage.GRAPH_MEMBER_MAX_BYTES + 1))
        reader = Mock()
        with self.assertRaisesRegex(ValueError, 'reference/order'):
            storage.load_operations_graph(altered[storage.GRAPH_PATH], reader)
        reader.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'serialized capacity'):
            self.bundle({'nodes': [{'id': 'n', 'payload': 'x' * storage.GRAPH_MEMBER_MAX_BYTES}], 'edges': []})

    def test_oversized_manifest_and_legacy_rejected_before_json_decode(self):
        with patch.object(storage.json, 'loads', side_effect=AssertionError('no decode')):
            for body in (b'x' * (storage.GRAPH_MAX_BYTES + 1), '', bytearray(b'{}')):
                with self.subTest(type=type(body)), self.assertRaisesRegex(ValueError, 'scope/size'):
                    storage.load_operations_graph(body)

    def test_declared_logical_aggregate_and_member_count_bounds_before_io(self):
        files = self.bundle()
        changes = [lambda m: m.update(logical_bytes=storage.GRAPH_LOGICAL_MAX_BYTES + 1),
                   lambda m: m.update(segments=m['segments'] * (storage.GRAPH_MAX_MEMBERS + 1))]
        for change in changes:
            altered = self.mutate(files, change)
            reader = Mock()
            with self.assertRaises(ValueError):
                storage.load_operations_graph(altered[storage.GRAPH_PATH], reader)
            reader.assert_not_called()
        def huge_manifest(meta):
            meta['segments'] = []
            for index in range(16):
                digest = format(index, '064x')
                meta['segments'].append({'path': storage.GRAPH_DIRECTORY + '/segment-' + digest + '.json',
                                         'sha256': digest, 'bytes': storage.GRAPH_MEMBER_MAX_BYTES,
                                         'scope': 'nodes', 'records': 1})
            meta['counts'] = {'nodes': 16, 'edges': 0}
        altered = self.mutate(files, huge_manifest)
        reader = Mock()
        with self.assertRaisesRegex(ValueError, 'aggregate capacity'):
            storage.load_operations_graph(altered[storage.GRAPH_PATH], reader)
        reader.assert_not_called()

    def test_prepare_capacity_bound_and_wrapper_overhead_fail_closed(self):
        with patch.object(storage, 'GRAPH_LOGICAL_MAX_BYTES', 200):
            with self.assertRaisesRegex(ValueError, 'serialized capacity'):
                storage.prepare_operations_graph(graph())
        with patch.object(storage, 'GRAPH_AGGREGATE_MAX_BYTES', 1000):
            with self.assertRaisesRegex(ValueError, 'aggregate capacity'):
                self.bundle()
        with patch.object(storage, 'GRAPH_MAX_MEMBERS', 1):
            with self.assertRaisesRegex(ValueError, 'aggregate capacity'):
                self.bundle()

    def test_record_references_reuse_every_unchanged_record_after_scattered_insertions(self):
        value = {'nodes': [{'id': str(i), 'value': 'x' * 90} for i in range(300)], 'edges': []}
        with patch.object(storage, 'GRAPH_SEGMENT_TARGET_BYTES', 500):
            old = storage.prepare_operations_graph(value, force=True)
            unchanged = storage.prepare_operations_graph(copy.deepcopy(value), old[storage.GRAPH_PATH], old.__getitem__)
            self.assertEqual(unchanged, {storage.GRAPH_PATH: old[storage.GRAPH_PATH]})
            retained = dict(old)
            changed = copy.deepcopy(value)
            old_members = set(storage.graph_members(old[storage.GRAPH_PATH]))
            # Insert into many existing chunks each run. No old record is copied.
            for run in range(20):
                for index in range(12):
                    changed['nodes'].insert(index * 20, {'id': 'new-' + str(run) + '-' + str(index), 'value': 'new record'})
                batch = storage.prepare_operations_graph(changed, retained[storage.GRAPH_PATH], retained.__getitem__)
                new_records = [record for name, body in batch.items() if name != storage.GRAPH_PATH
                               for record in json.loads(body)['records']]
                self.assertEqual(len(new_records), 12)
                self.assertTrue(all(record['id'].startswith('new-' + str(run) + '-') for record in new_records))
                self.assertTrue(old_members <= set(storage.graph_members(batch[storage.GRAPH_PATH])))
                for name, body in batch.items():
                    if name != storage.GRAPH_PATH and name in retained:
                        self.assertEqual(retained[name], body)
                    retained[name] = body
                self.assertEqual(storage.load_operations_graph(retained[storage.GRAPH_PATH], retained.__getitem__), changed)
            self.assertLess(sum(map(len, retained.values())), 2 * sum(map(len, old.values())))
            self.assertEqual(storage.load_operations_graph(old[storage.GRAPH_PATH], old.__getitem__), value)

    def test_partial_update_reorder_and_deletion_preserve_old_physical_records(self):
        initial = {'nodes': [{'id': 'a', 'value': 1}, {'id': 'b', 'value': 2}, {'id': 'c', 'value': 3}],
                   'edges': [{'id': 'edge', 'source': 'a', 'target': 'b'}], 'metadata': {'original': True}}
        old = storage.prepare_operations_graph(initial, force=True)
        changed = copy.deepcopy(initial)
        changed['nodes'] = [{'id': 'c', 'value': 3}, {'id': 'a', 'value': 99}]
        batch = storage.prepare_operations_graph(changed, old[storage.GRAPH_PATH], old.__getitem__)
        new_records = [record for name, body in batch.items() if name != storage.GRAPH_PATH
                       for record in json.loads(body)['records']]
        self.assertEqual(new_records, [{'id': 'a', 'value': 99}])
        retained = {**old, **batch}
        self.assertEqual(storage.load_operations_graph(batch[storage.GRAPH_PATH], retained.__getitem__), changed)
        self.assertEqual(storage.load_operations_graph(old[storage.GRAPH_PATH], old.__getitem__), initial)
        self.assertTrue(set(old) <= set(retained))
        # The old a/b versions remain in an immutable chunk still used for c.
        old_node = next(body for name, body in old.items() if name != storage.GRAPH_PATH and json.loads(body)['scope'] == 'nodes')
        self.assertEqual(json.loads(old_node)['records'], initial['nodes'])
        # Reordering with no content changes emits no new immutable bytes.
        reordered = copy.deepcopy(changed); reordered['nodes'].reverse()
        reorder_batch = storage.prepare_operations_graph(reordered, batch[storage.GRAPH_PATH], retained.__getitem__)
        self.assertEqual(set(reorder_batch), {storage.GRAPH_PATH})
        self.assertEqual(storage.load_operations_graph(reorder_batch[storage.GRAPH_PATH], retained.__getitem__), reordered)

    def test_same_id_changed_field_order_requires_new_record(self):
        initial = {'nodes': [{'id': 'a', 'x': 1, 'y': 2}], 'edges': []}
        old = storage.prepare_operations_graph(initial, force=True)
        changed = {'nodes': [{'y': 2, 'x': 1, 'id': 'a'}], 'edges': []}
        batch = storage.prepare_operations_graph(changed, old[storage.GRAPH_PATH], old.__getitem__)
        self.assertGreater(len(batch), 1)
        retained = {**old, **batch}
        self.assertEqual(raw(storage.load_operations_graph(batch[storage.GRAPH_PATH], retained.__getitem__)), raw(changed))

    def test_previous_snapshot_is_validated_before_reuse_and_cannot_downgrade(self):
        old = self.bundle()
        with self.assertRaisesRegex(ValueError, 'reader required'):
            storage.prepare_operations_graph(graph(), old[storage.GRAPH_PATH])
        name = storage.graph_members(old[storage.GRAPH_PATH])[0]
        corrupted = dict(old); corrupted[name] = corrupted[name].replace(b'payload', b'Payload', 1)
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            storage.prepare_operations_graph(graph(), old[storage.GRAPH_PATH], corrupted.__getitem__)
        missing = dict(old); del missing[name]
        with self.assertRaisesRegex(ValueError, 'member missing'):
            storage.prepare_operations_graph(graph(), old[storage.GRAPH_PATH], missing.__getitem__)
        empty = storage.prepare_operations_graph({'nodes': [], 'edges': []}, old[storage.GRAPH_PATH], old.__getitem__)
        self.assertTrue(storage.is_graph_manifest(empty[storage.GRAPH_PATH]))
        self.assertEqual(storage.graph_members(empty[storage.GRAPH_PATH]), ())

    def test_legacy_previous_migrates_without_changing_logical_bytes(self):
        value = graph(); original = raw(value)
        old = storage.prepare_operations_graph(value)
        batch = storage.prepare_operations_graph(value, old[storage.GRAPH_PATH], force=True)
        self.assertGreater(len(batch), 1)
        self.assertEqual(raw(storage.load_operations_graph(batch[storage.GRAPH_PATH], batch.__getitem__)), original)

    def test_record_reference_schema_scope_bounds_duplicates_and_unused_segments(self):
        changes = [lambda m: m.pop('order'), lambda m: m['order'].update(extra=[]),
                   lambda m: m['order'].update(nodes={}),
                   lambda m: m['order']['nodes'].__setitem__(0, [False, 0]),
                   lambda m: m['order']['nodes'].__setitem__(0, [0, True]),
                   lambda m: m['order']['nodes'].__setitem__(0, [-1, 0]),
                   lambda m: m['order']['nodes'].__setitem__(0, [0, -1]),
                   lambda m: m['order']['nodes'].__setitem__(0, [999, 0]),
                   lambda m: m['order']['nodes'].__setitem__(0, [0, 999]),
                   lambda m: m['order']['nodes'].__setitem__(0, [0]),
                   lambda m: m['order']['nodes'].__setitem__(0, [0, 0, 0]),
                   lambda m: m['order']['nodes'].__setitem__(0, {'segment': 0, 'index': 0}),
                   lambda m: m['order']['nodes'].__setitem__(0, m['order']['edges'][0]),
                   lambda m: m['order']['nodes'].__setitem__(1, m['order']['nodes'][0]),
                   lambda m: m['order']['nodes'].pop(),
                   lambda m: (m['order']['nodes'].pop(), m['counts'].update(nodes=1))]
        for index, change in enumerate(changes):
            files = self.mutate(self.bundle(), change)
            reader = Mock(side_effect=AssertionError('must fail before member IO'))
            with self.subTest(index=index), self.assertRaises(ValueError):
                storage.load_operations_graph(files[storage.GRAPH_PATH], reader)
            reader.assert_not_called()

    def test_reordered_records_inside_same_chunk_fail_logical_digest(self):
        files = storage.prepare_operations_graph({'nodes': [{'id': 'a'}, {'id': 'b'}], 'edges': []}, force=True)
        files = self.mutate(files, lambda m: m['order']['nodes'].reverse())
        with self.assertRaisesRegex(ValueError, 'logical digest/size'):
            storage.load_operations_graph(files[storage.GRAPH_PATH], files.__getitem__)

    def test_large_target_still_respects_member_hard_limit(self):
        value = {'nodes': [{'id': str(i), 'value': 'x' * 150} for i in range(15)], 'edges': []}
        with patch.object(storage, 'GRAPH_MEMBER_MAX_BYTES', 500), \
                patch.object(storage, 'GRAPH_SEGMENT_TARGET_BYTES', 10 ** 30):
            files = storage.prepare_operations_graph(value, force=True)
            self.assertGreater(len(files), 2)
            for path, body in files.items():
                if path != storage.GRAPH_PATH:
                    self.assertLessEqual(len(body), 500)
            self.assertEqual(storage.load_operations_graph(files[storage.GRAPH_PATH], files.__getitem__), value)

    def test_valid_old_orphan_can_be_verified_without_current_manifest(self):
        old = self.bundle()
        newer_value = graph()
        newer_value['nodes'][1]['complete_original'] += 'new revision'
        newer = self.bundle(newer_value)
        self.assertTrue(set(old) - set(newer))
        # Storage never touches the caller's old byte mapping or authorizes its
        # deletion. Publication/runner must retain and verify these old bytes.
        for path, body in old.items():
            if path != storage.GRAPH_PATH:
                storage.validate_graph_member(path, body)
        self.assertEqual(storage.load_operations_graph(old[storage.GRAPH_PATH], old.__getitem__), graph())


if __name__ == '__main__':
    unittest.main()
