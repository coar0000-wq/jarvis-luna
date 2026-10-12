"""Archive/read back filtered structured datasets into a LOCAL-ONLY BrainRuntime.

This preprocessing step does not establish that all downstream programs consume
vault bytes. Private/auth/manual/TypeSafe/state paths are outside its coverage.
No API, provider, upload, publication, Git changes or original-source edits.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import tempfile

import obsidian_brain as brain

LABELS = {'task': 'dataset_ingest', 'team': 'ingestion', 'operation': 'local-analysis'}
INDEX = brain.DATASET_INDEX


def _atomic_index(root, value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                     allow_nan=False).encode('utf-8') + b'\n'
    if len(raw) > brain.MAX_BYTES:
        raise brain.BrainError('dataset_index_byte_limit_exceeded')
    target = brain._safe(root, INDEX)
    if target.exists():
        info = target.lstat()
        if info.st_nlink != 1 or not target.is_file():
            raise brain.PathExcluded('excluded_nonregular_or_hardlinked_file')
    target.parent.mkdir(parents=True, exist_ok=True)
    brain._safe(root, INDEX)
    fd, temporary = tempfile.mkstemp(prefix='.brain-dataset-', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        staged, _ = brain._read(Path(temporary))
        if staged != raw or hashlib.sha256(staged).digest() != hashlib.sha256(raw).digest():
            raise brain.IntegrityError('dataset_index_writeback_mismatch')
        # No final index is published until all archived input payloads verify.
        brain.verify_consumed(root)
        brain.require_git_root(root)
        brain._safe(root, INDEX)
        os.replace(temporary, target)
        returned, _ = brain._read(target)
        if returned != raw:
            raise brain.IntegrityError('dataset_index_writeback_mismatch')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def ingest(root, *, limit=brain.MAX_SCAN_FILES):
    """Return safe counts and proof; parsed business values never enter reports.

    Path/content exclusions and oversized/malformed sources are counted with
    safe codes. Integrity, I/O and exclusion-verification failures abort, without
    substituting defaults. A scan cap prevents an all-datasets coverage claim.
    """
    root = brain.require_git_root(root)
    scan = brain.scan_public_data(root, limit=limit)
    rejected = Counter()
    entries = []
    with brain.execution(root, **LABELS) as run:
        for candidate in sorted(scan['entries'], key=lambda item: item['source_path']):
            try:
                loaded = brain.load_artifact(candidate['source_path'], root)
            except brain.IntegrityError:
                raise
            except brain.PathExcluded as error:
                rejected[str(error)] += 1
                continue
            except brain.ArtifactParseError as error:
                rejected[str(error)] += 1
                continue
            except brain.BrainError as error:
                if str(error) != 'byte_limit_exceeded':
                    raise
                rejected['byte_limit_exceeded'] += 1
                continue
            # All fields below reflect genuine source/vault readback, not scan
            # metadata or a synthetic observation clock. Do not retain value.
            entries.append({key: loaded[key] for key in (
                'source_path', 'source_sha256', 'source_workspace_id', 'payload_id', 'artifact_id',
                'parser', 'count', 'count_unit', 'size_bytes', 'source_mtime_ns',
                'source_timestamps', 'input_read_from_vault')})
        if not entries:
            return {'blocked': 'no_genuine_dataset_inputs', 'archived_file_count': 0,
                    'path_excluded_count': scan['excluded_count'],
                    'path_excluded_count_unit': scan['excluded_count_unit'],
                    'path_excluded_codes': scan['excluded_codes'],
                    'source_rejected_count': sum(rejected.values()),
                    'source_rejected_codes': dict(sorted(rejected.items())),
                    'scan_truncated': scan['truncated'],
                    'private_coverage_claimed': False, 'human_approval_claimed': False,
                    'downstream_direct_vault_consumption_verified': False, **run.proof()}
        brain.verify_consumed(root)
        index = {
            'schema': 'brain_dataset_index_v1', 'write_at': brain._now(),
            'local_only': True, 'business_approval': False,
            'coverage': 'filtered structured dataset archive/readback preprocessor',
            'downstream_direct_vault_consumption_verified': False,
            'private_coverage_claimed': False, 'human_approval_claimed': False,
            'input_read_from_vault': True, 'archived_file_count': len(entries),
            'scan_limit': limit, 'scan_truncated': scan['truncated'],
            'path_excluded_count': scan['excluded_count'],
            'path_excluded_count_unit': scan['excluded_count_unit'],
            'path_excluded_codes': scan['excluded_codes'],
            'source_rejected_count': sum(rejected.values()),
            'source_rejected_codes': dict(sorted(rejected.items())),
            'entries': entries,
        }
        _atomic_index(root, index)
        proof = brain.record_output(INDEX, root, **LABELS)
        return {
            'archived_file_count': len(entries),
            'parser_counts': dict(sorted(Counter(item['parser'] for item in entries).items())),
            'path_excluded_count': scan['excluded_count'],
            'path_excluded_count_unit': scan['excluded_count_unit'],
            'path_excluded_codes': scan['excluded_codes'],
            'source_rejected_count': sum(rejected.values()),
            'source_rejected_codes': dict(sorted(rejected.items())),
            'scan_truncated': scan['truncated'], 'index_path': INDEX,
            'downstream_direct_vault_consumption_verified': False,
            'private_coverage_claimed': False, 'human_approval_claimed': False,
            **proof,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--limit', type=int, default=brain.MAX_SCAN_FILES)
    args = parser.parse_args(argv)
    try:
        result = ingest(args.root, limit=args.limit)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2 if result.get('blocked') else 0
    except brain.BrainError as error:
        print(json.dumps({'blocked': str(error), 'local_only': True,
                          'business_approval': False}))
        return 2
    except OSError:
        print(json.dumps({'blocked': 'local_io_failure', 'local_only': True,
                          'business_approval': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
