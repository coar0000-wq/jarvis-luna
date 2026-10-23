#!/usr/bin/env python3
"""Fail-closed, read-only continuity reconciliation for one approved gap.

GitHub metadata authentication is deliberately separate from pure analysis. This
module never imports a producer, initializes a ledger, or dispatches an action.
A restricted review is not an operations/source/AI checkpoint.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = 'coar0000-wq/jarvis-luna'
DECISION_PATH = 'data/manual/continuity_reconciliation/deep-39893237129-attempt-1.json'
REPORT_PATH = 'data/agents/continuity_review.json'
HISTORY_DIR = 'data/agents/continuity_review_history/'
MODE = 'restricted_gap'
GAP = {'run_id': 39893237129, 'run_attempt': 1,
       'head_sha': '52113c37396fcae41e3ac6e25af26c23b6d9c8b2',
       'workflow': '.github/workflows/JARVIS-Deep-Analysis.yml'}
BASELINE = {'run_id': 39887036572, 'run_attempt': 1, 'artifact_id': 12475331670,
            'artifact_sha256': 'f384b0ba5c93cabe8124663d5a236c233d2465dd8a860ec88bea1989e66cf912',
            'verified_receipts': 2007, 'verified_claims': 2007,
            'original_publication_commit': '52113c37396fcae41e3ac6e25af26c23b6d9c8b2',
            'protected_baseline_commit': 'c5eda8151c9287f592cb08cf873723b87e1cf2f1'}
KNOWN_INPUT_RUNS = [{'run_id': 39893706651, 'run_attempt': 1,
                     'head_sha': '52113c37396fcae41e3ac6e25af26c23b6d9c8b2',
                     'workflow': '.github/workflows/gosi-vision.yml',
                     'published_commit': 'c5eda8151c9287f592cb08cf873723b87e1cf2f1'}]
# One exact independently completed publication; never a future Shopify allowance.
PRESERVED_PUBLICATIONS = [{'run_id': 39906965295,
  'run_attempt': 1,
  'workflow': '.github/workflows/daiso-daily-beauty-shopify.yml',
  'head_sha': '760529597a68ccec95a9fcbf69ca1732e22b7cb8',
  'job_id': 120261030072,
  'job_name': 'register',
  'publication_step': '등록 이력 저장 (중복 방지)',
  'publication_commit': '435b51cf4addf749c71b86ebf8818229f5c784c8',
  'parent_commit': '760529597a68ccec95a9fcbf69ca1732e22b7cb8',
  'tree_sha': '5cd341178112ba3d4ed8ea14ce40372cbfbae58e',
  'code_contract_digest': 'ccb9c6ac1f11da9e4b9a706d21bc1a6861139ac5e5805c4d7dc159650f1d3542',
  'scope': 'preserve_exact_already_published_bytes_only',
  'files': {'data/image_localization/1025282.json': {'before': None,
                                                     'after': {'mode': '100644',
                                                               'git_blob': '7b85b4a2f0853155a2f16f36308cc4291525811e'}},
            'data/image_localization/1060124.json': {'before': None,
                                                     'after': {'mode': '100644',
                                                               'git_blob': '1a8e88d1454b1e6a8499df8a8ca61118ebe06e9a'}},
            'data/shop_com_categories.json': {'before': {'mode': '100644',
                                                         'git_blob': '7b1bb1c92163365ed2a02ae351d7d6e7b8b4cb95'},
                                              'after': {'mode': '100644',
                                                        'git_blob': '9062e866cae316326b13d067e3c1f7d0f364eb4d'}},
            'data/shopify_daily_registry.json': {'before': {'mode': '100644',
                                                            'git_blob': '5df99e6cc5db6f37c6ca2a5e233788e450656f1b'},
                                                 'after': {'mode': '100644',
                                                           'git_blob': '6386bee050eca099ab46d0b306eb451c857c2cf1'}}},
  'audit': {'job_log_sha256': '90f71030fdb79a4405e9565d8333c0bac5b65242dcbd2bbbebc84d317bfd21bf',
            'result_sha256': 'ad247f05c7e57dcb7429ea8e3db47f66132d71d46a9e83276d7ac8b7b6cdc1ab',
            'registry_preservation_sha256': 'e7b3d3d193bb38246d07d164a52cc28edbf24096b45ab5c66e41bcd2100c6247',
            'independent_admin_readback_sha256': '067364d9cfc43bd223278b79981b188fde06177ea332091e28c113a2e530ad9e'}}]
# Audited completed run only; local commerce derivatives were discarded.
RECONCILED_BLOCKED_RUNS = [{'run_id': 39911582752,
  'run_attempt': 1,
  'head_sha': '3603173e75488f6aa2d17dd216daf79508927967',
  'workflow': '.github/workflows/JARVIS-Core-Automation.yml',
  'created_at': '2026-10-23T06:27:25Z',
  'updated_at': '2026-10-23T06:28:48Z',
  'event': 'workflow_dispatch',
  'actor': {'login': 'github-actions[bot]', 'id': 41898282},
  'triggering_actor': {'login': 'github-actions[bot]', 'id': 41898282},
  'job_id': 120275586332,
  'job_name': 'core-automation',
  'code_contract_digest': 'ea5fab6715701097e4f0e522d121eb76cfdf248eb08f0a888656a66c1f9ed7ce',
  'job_projection_digest': '03556fbffdd18dfcdb7dbd0ca1ec41ef57c93db2b689778fe9ef25070529747c',
  'canonical_job_log_sha256': 'dafae585df196de7cd8a80efd075663459a321484cbddb4f5d7b8b05c4e3b405',
 'job_log_normalization': 'utf8_strict_remove_one_leading_bom_crlf_to_lf_one_trailing_lf',
  'scope': 'exact_completed_blocked_run_no_remote_publication_or_provider_actuation',
  'runner_local_changes': 'discarded_not_restored',
  'artifact_count': 0}]
PURE_WORKFLOWS = frozenset(('.github/workflows/preflight.yml', '.github/workflows/pages-verified.yml',
                           '.github/workflows/dependency-profiles.yml', '.github/workflows/image-ocr-tests.yml',
                           '.github/workflows/latest-code-revalidation.yml'))
PLAN_DIGEST = 'df670a379701044cbb22ab4857552d71a48f846dab8fd7f9beb10807241b18e9'
APPROVAL_REFERENCE = 'Sentinel_b1b2e3d15eb481919a7127db98b36508'
APPROVAL_AT = '2026-10-23T05:06:23Z'
APPROVAL_DIGEST = '453a5a9369a622a6e3a9fd98a59b163599e2672a3fa52c410cf1f9038b6f647c'
ALLOWED_EFFECTS = ['local_analysis', 'review_publication']
FORBIDDEN_EFFECTS = ['provider_requests', 'ai_requests', 'operations_actions', 'shopify_mutations']
CAPABILITIES = ['source_collection', 'gosi_vision_alt', 'source_procedures', 'shortlist_observer',
                'ai_setup', 'jev', 'gemini', 'automatic_recovery', 'safe_autofix',
                'operations_execution', 'commerce_regeneration', 'shopify_mutation']
RESTRICTED_WORKFLOWS = {'.github/workflows/JARVIS-Core-Automation.yml': 'core-automation',
                        GAP['workflow']: 'Collect, normalize, graph, train and publish runtime state'}
RESTRICTED_PUBLICATION_STEP = 'Publish only the validated restricted review'
RESTRICTED_PROOF_STEPS = ('Select authenticated continuity mode before provider setup',
                          'Analyze saved inputs under the approved unresolved gap',
                          'Aggregate the distinct restricted review contract',
                          'Validate restricted review and complete protected inventory')
REQUIRED_STAGES = ['reconciliation_decision', 'exact_input_validation', 'pure_review',
                   'protected_state_equality', 'restricted_publication_validation']
INPUT_PATHS = ('data/gosi.json', 'data/daiso_real/products.json', 'data/daiso_real/daiso_gosi.json',
               'data/daiso_real/collection_status.json', 'data/product_master.json',
               'data/pricing_model.json', 'data/listing_gate.json', 'data/legal_products.json',
               'data/mocra_readiness.json', 'data/team_improvement.json')
FROZEN_PREFIXES = ('data/operations/', 'data/agents/source_procedures/', 'data/manual/', 'data/typesafe')
FROZEN_FILES = frozenset(('data/daiso_real/shortlist_observations.json',
                         'data/daiso_real/.shortlist_observation_claim.json', 'data/shopify_daily_registry.json'))
IMMUTABLE_PREFIXES = ('data/agents/workflow_status_history/', 'data/agents/gemini_escalation_history/',
                      'data/knowledge/moe_evaluation_history/', 'data/knowledge/gosi_observation_history/',
                      'data/agents/daiso_pipeline_history/', 'data/agents/source_procedures/observer_history/',
                      'data/daiso_real/candidate_pool_history/', 'data/legal_export_history/',
                      'data/typesafe_team_advisory_history/')
STATE_NAME = re.compile(r'(?:^|[._/-])(?:ledger|nonces?|claims?|receipts?|checkpoint|budget|stops?|registry|state)(?:$|[._/-])')
GUARDED_INPUTS = frozenset(('data/gosi.json', 'data/daiso_real/daiso_gosi.json'))
GUARDED_FIELD = re.compile(r'(?:stop|budget|nonce|claim|charged|reserved|call_log|account_limit)', re.I)
INPUT_PROFILE = {'workflow': '.github/workflows/jarvis-real-knowledge.yml',
                 'job_name': 'collect-and-sync', 'publication_step': '산출물 발행 (원격 최신 위에 이번 변경만)',
                 'publication_profile': 'non_operations'}
KNOWLEDGE_OUTPUTS = frozenset((
    'data/agents/beauty_category_teams.json', 'data/agents/brain_execution_agents.json',
    'data/agents/brain_execution_runtime.json', 'data/agents/collector_audit.json',
    'data/agents/last_run.json', 'data/agents/listing_notes.json', 'data/agents/ops_plan.json',
    'data/agents/score_explain.json', 'data/agents/signal_audit.json', 'data/dashboard_runtime.json',
    'data/health_check.json', 'data/knowledge/cumulative_history.json',
    'data/knowledge/moe_tuning_report.json', 'data/knowledge/organic_skincare_products.json',
    'data/knowledge/real_knowledge_moe.npz', 'data/knowledge/real_knowledge_moe_tuned.npz',
    'data/knowledge/real_knowledge_router.npz', 'data/knowledge/real_sources.json',
    'data/knowledge/training_corpus.jsonl', 'data/knowledge/training_status.json',
    'data/obsidian_record_names.json', 'data/publish_deletions.json',
    'data/self_improve/team_history_evidence.json', 'data/team_improvement.json'))


def _profile_data_output(path):
    return path in KNOWLEDGE_OUTPUTS or bool(re.fullmatch(r'data/knowledge/moe_evaluation_history/[0-9a-f]{64}\.json', path))

INPUT_RUNTIME_COMMANDS = [['scripts/ingest_obsidian_data.py', '--root', '.'], ['scripts/health_check_v2.py'],
                          ['scripts/generate_dashboard_runtime.py'], ['scripts/run_jarvis_agents.py', '--force'],
                          ['scripts/build_team_improvement.py']]
PRODUCERS = frozenset(('.github/workflows/JARVIS-Core-Automation.yml', GAP['workflow'],
                     '.github/workflows/daiso-real-collection.yml', '.github/workflows/fx-refresh.yml',
                     '.github/workflows/daiso-candidate-recovery.yml'))
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_FILES = 30000
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_RUN_PAGES = 100
MAX_METADATA_REQUESTS = 256
MAX_DISCOVERY_SECONDS = 240
EVIDENCE_TTL = timedelta(minutes=10)
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
HEX40 = re.compile(r'[0-9a-f]{40}\Z')
EXECUTION = re.compile(r'[1-9][0-9]*:[1-9][0-9]*\Z')
_SEAL = object()


class ContinuityError(ValueError):
    pass


def _fail(condition, message):
    if not condition:
        raise ContinuityError(message)


def _time(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except (ValueError, TypeError):
            raise ContinuityError('invalid_timestamp') from None
    _fail(result.tzinfo is not None, 'timestamp_timezone_required')
    return result.astimezone(timezone.utc)


def canonical_digest(value):
    try:
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                         allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError):
        raise ContinuityError('noncanonical_value') from None
    return hashlib.sha256(raw).hexdigest()


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _fail(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    try:
        result = json.loads(raw, object_pairs_hook=pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ContinuityError('nonfinite_json')))
    except (ValueError, UnicodeError, RecursionError):
        raise ContinuityError('malformed_json') from None
    canonical_digest(result)
    return result


def _safe(root, relative):
    root = Path(root).resolve()
    _fail(isinstance(relative, str) and relative and not relative.startswith('/') and
          '\\' not in relative and all(p not in ('', '.', '..') for p in relative.split('/')), 'unsafe_path')
    result = root.joinpath(*relative.split('/'))
    current = root
    for part in relative.split('/'):
        current = current / part
        _fail(not current.is_symlink(), 'symlink_forbidden')
    _fail(result.resolve().is_relative_to(root), 'path_escape')
    return result


def _read(root, relative, cap=MAX_FILE_BYTES):
    path = _safe(root, relative)
    _fail(path.is_file() and path.stat().st_size <= cap, 'file_missing_or_oversize:' + relative)
    with path.open('rb') as stream:
        raw = stream.read(cap + 1)
    _fail(len(raw) <= cap, 'file_oversize:' + relative)
    return raw


def _git(root, *args, cap=MAX_JSON_BYTES):
    try:
        result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(root), *args],
                                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    except (subprocess.SubprocessError, OSError):
        raise ContinuityError('git_evidence_unavailable') from None
    _fail(len(result.stdout) <= cap, 'git_evidence_oversize')
    return result.stdout


def _blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def _tree(root, ref):
    _fail(bool(HEX40.fullmatch(ref)), 'exact_commit_required')
    raw = _git(root, 'ls-tree', '-r', '-z', ref, cap=32 * 1024 * 1024)
    entries = {}
    for row in raw.split(b'\0'):
        if not row:
            continue
        meta, path = row.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        path = path.decode('utf-8')
        if not (_data(path) or _code(path) or _is_review(path)):
            continue
        _fail(kind == 'blob' and mode in ('100644', '100755'), 'nonregular_git_member')
        entries[path] = {'mode': mode, 'git_blob': oid}
    _fail(len(entries) <= MAX_FILES, 'tree_file_limit')
    return entries


def _is_review(path):
    return path == REPORT_PATH or bool(re.fullmatch(re.escape(HISTORY_DIR) + r'[0-9a-f]{64}\.json', path))


CODE_DIRECTORIES = ('scripts', 'config', '.github', 'requirements', 'automation', 'tools')


def _code(path):
    return '/' not in path or path.startswith(tuple(p + '/' for p in CODE_DIRECTORIES))


def _local_paths(root, predicate):
    paths = set()
    tracked = _git(root, 'ls-files', '-z', cap=32 * 1024 * 1024).decode().split('\0')
    for path in tracked:
        if path and predicate(path):
            paths.add(path)
    # Include ignored files too: an untracked ledger is still effect-bearing state.
    prefixes = ('data',) if predicate is _data else CODE_DIRECTORIES
    for prefix in prefixes:
        base = _safe(root, prefix)
        if base.exists():
            _fail(base.is_dir(), 'inventory_root_not_directory')
            for path in base.rglob('*'):
                relative = path.relative_to(Path(root).resolve()).as_posix()
                _fail(not path.is_symlink(), 'symlink_forbidden')
                _fail(path.is_file() or path.is_dir(), 'nonregular_file_forbidden')
                if path.is_file() and predicate(relative) and (predicate is not _code or
                        ('__pycache__/' not in relative and not relative.endswith('.pyc'))):
                    paths.add(relative)
    if predicate is _code:
        for path in Path(root).iterdir():
            if not path.name.startswith('.git'):
                _fail(not path.is_symlink(), 'symlink_forbidden')
                _fail(path.is_file() or path.is_dir(), 'nonregular_file_forbidden')
                if path.is_file():
                    paths.add(path.name)
    _fail(len(paths) <= MAX_FILES, 'inventory_file_limit')
    return sorted(paths)


def _data(path):
    return path.startswith('data/') and not _is_review(path)


def _protected_fields(raw):
    value, fields = _json(raw), {}
    def walk(node, path=''):
        if isinstance(node, dict):
            for key, item in node.items():
                location = path + '/' + key
                if GUARDED_FIELD.search(key):
                    fields[location] = item
                else:
                    walk(item, location)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, path + '/' + str(index))
    walk(value)
    return canonical_digest(fields)


def _effect_state(path):
    # Default-deny, not a naming heuristic. Only the reviewed exact independent
    # input profile can advance these enumerated non-effect output files.
    if path == DECISION_PATH or _is_review(path):
        return False
    return _data(path) and not _profile_data_output(path)


def _immutable(path):
    return path.startswith(IMMUTABLE_PREFIXES) or bool(re.search(r'/[0-9a-f]{64}\.(?:json|bin)$', path))


def _inventory(root, paths):
    output, total = {}, 0
    for path in paths:
        raw = _read(root, path)
        total += len(raw)
        _fail(total <= MAX_TOTAL_BYTES, 'inventory_total_limit')
        mode = '100755' if _safe(root, path).stat().st_mode & stat.S_IXUSR else '100644'
        output[path] = {'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw),
                        'mode': mode, 'git_blob': _blob(raw)}
        if path in GUARDED_INPUTS:
            output[path]['protected_fields_digest'] = _protected_fields(raw)
    return output


def protected_inventory(root):
    """Hash every canonical data byte, including ignored/untracked data and nonces."""
    root = Path(root).resolve()
    return _inventory(root, _local_paths(root, _data))


def protected_inventory_digest(inventory):
    return canonical_digest(inventory)


def assert_protected_unchanged(before, after):
    _fail(isinstance(before, dict) and before == after, 'protected_bytes_changed')


def _tree_projection(inventory):
    return {p: {'mode': v['mode'], 'git_blob': v['git_blob']} for p, v in sorted(inventory.items())}


def frozen_inventory_digest(inventory):
    frozen = {p: v for p, v in _tree_projection(inventory).items() if _effect_state(p)}
    # Preserve exact independently published current bytes, then compare the
    # original baseline projection. No counter reset or generic path exemption.
    for publication in PRESERVED_PUBLICATIONS:
        for path, identities in publication['files'].items():
            _fail(frozen.get(path) == identities['after'], 'preserved_publication_bytes_changed:' + path)
            if identities['before'] is None:
                frozen.pop(path)
            else:
                frozen[path] = identities['before']
    guards = {p: v['protected_fields_digest'] for p, v in inventory.items() if p in GUARDED_INPUTS}
    return canonical_digest({'effect_state': frozen, 'embedded_source_safety': guards})


def baseline_frozen_digest(root, ref=None):
    ref = ref or BASELINE['protected_baseline_commit']
    tree = _tree(root, ref)
    for publication in PRESERVED_PUBLICATIONS:
        for path, identities in publication['files'].items():
            _fail(tree.get(path) == identities['before'], 'preserved_baseline_before_mismatch')
    frozen = {p: v for p, v in tree.items() if _data(p) and _effect_state(p)}
    guards = {p: _protected_fields(_git(root, 'show', ref + ':' + p, cap=MAX_FILE_BYTES))
              for p in GUARDED_INPUTS if p in tree}
    return canonical_digest({'effect_state': frozen, 'embedded_source_safety': guards})


def validate_original_history(root, inventory):
    baseline = _tree(root, BASELINE['protected_baseline_commit'])
    actual = _tree_projection(inventory)
    for path, identity in baseline.items():
        if _data(path) and _immutable(path):
            _fail(actual.get(path) == identity, 'original_history_member_changed:' + path)



def code_contract_digest(root, ref=None):
    if ref is not None:
        return canonical_digest({p: v for p, v in _tree(root, ref).items() if _code(p)})
    return canonical_digest(_tree_projection(_inventory(root, _local_paths(root, _code))))


def load_decision(root):
    decision = _json(_read(root, DECISION_PATH, MAX_JSON_BYTES))
    _fail(isinstance(decision, dict), 'decision_object_required')
    return decision


def _decision_shape(decision, now=None):
    keys = {'schema_version', 'mode', 'repository', 'gap_inventory', 'baseline', 'plan_digest',
            'approval', 'expires_at', 'allowed_effects', 'forbidden_effects', 'input_paths',
            'report_path', 'history_directory', 'code_contract_digest', 'frozen_inventory_digest',
            'analysis_kind', 'provenance', 'known_verified_input_runs', 'approved_history_inventory_digest', 'independent_input_profiles', 'approved_prior_code_contracts', 'preserved_publications', 'reconciled_blocked_runs'}
    _fail(isinstance(decision, dict) and set(decision) == keys, 'decision_schema_mismatch')
    _fail(type(decision['schema_version']) is int and decision['schema_version'] == 1 and decision['mode'] == MODE, 'decision_mode_mismatch')
    _fail(decision['repository'] == REPOSITORY and canonical_digest(decision['gap_inventory']) == canonical_digest([GAP]), 'gap_inventory_mismatch')
    prior_contracts = decision['approved_prior_code_contracts']
    _fail(isinstance(prior_contracts, list) and len(prior_contracts) <= 16, 'prior_code_contract_list_invalid')
    for entry in prior_contracts:
        _fail(isinstance(entry, dict) and set(entry) == {'commit', 'code_contract_digest', 'scope'} and
              isinstance(entry['commit'], str) and HEX40.fullmatch(entry['commit']) and
              isinstance(entry['code_contract_digest'], str) and HEX64.fullmatch(entry['code_contract_digest']) and
              entry['scope'] == 'verification_and_existing_input_profile', 'prior_code_contract_invalid')
    _fail(canonical_digest(decision['reconciled_blocked_runs']) == canonical_digest(RECONCILED_BLOCKED_RUNS), 'blocked_run_scope_changed')
    _fail(canonical_digest(decision['preserved_publications']) == canonical_digest(PRESERVED_PUBLICATIONS), 'preserved_publication_scope_changed')
    _fail(decision['independent_input_profiles'] == [INPUT_PROFILE], 'independent_input_profile_changed')
    _fail(canonical_digest(decision['known_verified_input_runs']) == canonical_digest(KNOWN_INPUT_RUNS), 'known_input_run_scope_mismatch')
    _fail(canonical_digest(decision['baseline']) == canonical_digest(BASELINE) and decision['plan_digest'] == PLAN_DIGEST, 'baseline_or_plan_mismatch')
    _fail(decision['approval'] == {'reference': APPROVAL_REFERENCE, 'approved_at': APPROVAL_AT,
                                 'sha256': APPROVAL_DIGEST}, 'approval_reference_mismatch')
    _fail(decision['provenance'] == 'owner_scope_reference_bound_to_authenticated_main_policy', 'approval_provenance_mismatch')
    _fail(decision['allowed_effects'] == ALLOWED_EFFECTS and decision['forbidden_effects'] == FORBIDDEN_EFFECTS,
          'effect_scope_mismatch')
    _fail(decision['input_paths'] == list(INPUT_PATHS) and decision['report_path'] == REPORT_PATH and
          decision['history_directory'] == HISTORY_DIR and decision['analysis_kind'] == 'cached_review_v1', 'analysis_scope_mismatch')
    for key in ('code_contract_digest', 'frozen_inventory_digest', 'approved_history_inventory_digest'):
        _fail(isinstance(decision[key], str) and bool(HEX64.fullmatch(decision[key])), 'unbound_' + key)
    instant = _time(now)
    _fail(_time(APPROVAL_AT) <= instant < _time(decision['expires_at']) <= _time(APPROVAL_AT) + timedelta(days=7),
          'decision_expired_or_future')
    return decision


@dataclass(frozen=True)
class VerifiedEvidence:
    main_commit: str
    run: dict
    gap_inventory: list
    observed_at: str
    data_tree: dict
    code_digest: str
    decision_blob: str
    publication_executions: tuple
    inventory_digest: str
    inventory_count: int
    request_count: int
    rate_remaining: int | None
    rate_limit: int | None
    rate_reset: int | None
    reserved_requests: int
    production_transport: bool
    seal: object


_API_ACCOUNTING = {'requests': 0, 'remaining': None, 'limit': None, 'reset': None}


def _record_rate_headers(headers):
    """Only actual GitHub HTTP headers establish available request capacity."""
    try:
        remaining, limit, reset = (int(headers[name]) for name in
                                   ('X-RateLimit-Remaining', 'X-RateLimit-Limit', 'X-RateLimit-Reset'))
    except (KeyError, ValueError, TypeError):
        raise ContinuityError('github_rate_budget_unavailable') from None
    _fail(0 <= remaining <= limit and limit > 0 and reset > 0, 'github_rate_budget_invalid')
    _API_ACCOUNTING.update(remaining=remaining, limit=limit, reset=reset)


def _require_rate_reserve(reserve, *, production):
    if production:
        available = _API_ACCOUNTING['remaining']
        _fail(type(available) is int and available >= reserve, 'github_rate_budget_insufficient')


def _inventory_snapshot(rows):
    fields = ('id', 'run_attempt', 'head_sha', 'path', 'head_branch', 'created_at', 'updated_at', 'status', 'conclusion')
    return sorted(({key: row.get(key) for key in fields} for row in rows), key=lambda row: row['id'])


def _discover_runs(get, *, first_page=None):
    runs, expected_total, seen_ids, covered = [], None, set(), False
    for page in range(1, MAX_RUN_PAGES + 1):
        listing = get('actions/runs?per_page=100&page=' + str(page))
        rows, total = listing.get('workflow_runs'), listing.get('total_count')
        _fail(isinstance(rows, list) and len(rows) <= 100 and type(total) is int and
              0 <= total <= MAX_RUN_PAGES * 100, 'run_inventory_malformed_or_oversize')
        if expected_total is None:
            expected_total = total
            if first_page:
                first_page(max(1, (total + 99) // 100))
        _fail(total == expected_total, 'run_inventory_changed_during_discovery')
        for row in rows:
            _fail(isinstance(row, dict) and type(row.get('id')) is int and row['id'] not in seen_ids,
                  'run_inventory_duplicate_or_race')
            seen_ids.add(row['id'])
        runs.extend(rows)
        if len(runs) == expected_total:
            covered = True
            break
        _fail(len(rows) == 100 and len(runs) < expected_total, 'run_inventory_incomplete')
    _fail(covered, 'gap_discovery_bound_exhausted')
    return runs


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _github_json(endpoint):
    _fail(endpoint == 'git/ref/heads/main' or
          bool(re.fullmatch(r'actions/runs(?:/[1-9][0-9]*(?:/attempts/[1-9][0-9]*)?)?(?:\?per_page=100&page=(?:[1-9][0-9]?|100))?', endpoint)) or
          bool(re.fullmatch(r'actions/runs/[1-9][0-9]*/attempts/[1-9][0-9]*/jobs\?per_page=100', endpoint)) or
          bool(re.fullmatch(r'actions/runs/[1-9][0-9]*/artifacts\?per_page=100', endpoint)),
          'github_read_scope_denied')
    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    _fail(bool(token), 'authenticated_github_read_required')
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'JARVIS-restricted-continuity/1'}
    request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + '/' + endpoint, headers=headers)
    try:
        opener = urllib.request.build_opener(_NoRedirect())
        _API_ACCOUNTING['requests'] += 1
        with opener.open(request, timeout=20) as response:
            _record_rate_headers(response.headers)
            _fail(response.status == 200, 'github_read_unsuccessful')
            declared = response.headers.get('Content-Length')
            _fail(not declared or 0 <= int(declared) <= MAX_JSON_BYTES, 'github_response_size_limit')
            chunks, received, deadline = [], 0, time.monotonic() + 20
            while True:
                _fail(time.monotonic() < deadline, 'github_response_time_limit')
                chunk = response.read1(min(65536, MAX_JSON_BYTES + 1 - received))
                if not chunk:
                    break
                chunks.append(chunk)
                received += len(chunk)
                _fail(received <= MAX_JSON_BYTES, 'github_response_size_limit')
            _fail(not declared or received == int(declared), 'github_response_truncated')
            return _json(b''.join(chunks))
    except (urllib.error.URLError, OSError, ValueError):
        raise ContinuityError('authenticated_github_read_failed') from None


def _github_job_log(endpoint):
    """Read one authenticated job log; never forward Authorization on redirect."""
    _fail(bool(re.fullmatch(r'actions/jobs/[1-9][0-9]*/logs', endpoint)), 'log_read_scope_denied')
    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    _fail(bool(token), 'authenticated_github_read_required')
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'JARVIS-restricted-continuity/1'}
    request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + '/' + endpoint, headers=headers)
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        try:
            _API_ACCOUNTING['requests'] += 1
            with opener.open(request, timeout=20) as response:
                _record_rate_headers(response.headers)
                return _bounded_job_log_response(response)
        except urllib.error.HTTPError as error:
            _record_rate_headers(error.headers)
            _fail(error.code in (301, 302, 303, 307, 308), 'attempt_logs_unavailable')
            location = error.headers.get('Location'); error.close()
        parsed = urllib.parse.urlsplit(location or '')
        _fail(parsed.scheme == 'https' and parsed.hostname and
              any(parsed.hostname.endswith(suffix) for suffix in ('.blob.core.windows.net', '.githubusercontent.com', '.actions.githubusercontent.com')) and
              not parsed.username and not parsed.password and parsed.port in (None, 443) and not parsed.fragment,
              'untrusted_log_redirect')
        redirected = urllib.request.Request(location, headers={'User-Agent': 'JARVIS-restricted-continuity/1'})
        with opener.open(redirected, timeout=20) as response:
            return _bounded_job_log_response(response)
    except (urllib.error.URLError, OSError, ValueError):
        raise ContinuityError('authenticated_attempt_logs_unavailable') from None


def _bounded_job_log_response(response):
    _fail(response.status == 200, 'log_response_unsuccessful')
    cap, total, chunks, deadline = 16 * 1024 * 1024, 0, [], time.monotonic() + 20
    declared = response.headers.get('Content-Length')
    _fail(not declared or 0 <= int(declared) <= cap, 'log_response_size_limit')
    while True:
        _fail(time.monotonic() < deadline, 'log_response_time_limit')
        chunk = response.read1(min(65536, cap + 1 - total))
        _fail(time.monotonic() < deadline, 'log_response_time_limit')
        if not chunk:
            _fail(not declared or total == int(declared), 'job_log_response_truncated')
            return b''.join(chunks)
        chunks.append(chunk); total += len(chunk)
        _fail(total <= cap, 'log_response_size_limit')


def _job_log_record(raw, step, expression):
    """Unique whole-job record, then exact authenticated publication-step time."""
    _fail(isinstance(raw, bytes) and 0 < len(raw) <= 16 * 1024 * 1024, 'job_log_size_limit')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeError:
        raise ContinuityError('job_log_encoding_invalid') from None
    _fail(isinstance(step, dict) and all(isinstance(step.get(key), str) and
          re.fullmatch(r'\d{4}-\d\d-\d\dT[0-9:.]+Z', step[key]) for key in ('started_at', 'completed_at')),
          'publication_step_timestamps_missing')
    started, completed = _time(step['started_at']), _time(step['completed_at'])
    _fail(started <= completed and completed - started <= timedelta(minutes=90), 'publication_step_timestamps_invalid')
    matches = re.findall(r'^(\d{4}-\d\d-\d\dT[0-9:.]+Z) ' + expression + r'\r?$', text, re.M)
    _fail(len(matches) == 1, 'unique_job_publication_record_required')
    observed, payload = matches[0]
    _fail(started <= _time(observed) < completed + timedelta(seconds=1), 'publication_record_outside_step')
    _fail(len(payload.encode('utf-8')) <= MAX_JSON_BYTES, 'publication_record_size_limit')
    return payload


def _publication_from_job(raw, step):
    return _json(_job_log_record(raw, step, r'PUBLISH_TRANSACTION_OK (.*)'))


def _verify_preserved_publication(root, run, main, publication, get, get_logs):
    """Authenticate one completed external producer; never run or authorize it."""
    identity = str(publication['run_id']) + ':' + str(publication['run_attempt'])
    endpoint = 'actions/runs/' + identity.replace(':', '/attempts/')
    exact = get(endpoint)
    for value in (run, exact):
        _validate_run(value, identity)
        _fail(value.get('path') == publication['workflow'] and value.get('head_sha') == publication['head_sha'] and
              value.get('status') == 'completed' and value.get('conclusion') == 'success', 'preserved_run_changed')
    _fail(code_contract_digest(root, publication['head_sha']) == publication['code_contract_digest'], 'preserved_producer_code_changed')
    jobs = get(endpoint + '/jobs?per_page=100')
    _fail(jobs.get('total_count') == 1 and isinstance(jobs.get('jobs'), list) and len(jobs['jobs']) == 1, 'preserved_jobs_incomplete')
    job = jobs['jobs'][0]
    _fail(job.get('id') == publication['job_id'] and job.get('run_id') == publication['run_id'] and
          job.get('head_sha') == publication['head_sha'] and job.get('name') == publication['job_name'] and
          job.get('status') == 'completed' and job.get('conclusion') == 'success', 'preserved_job_changed')
    steps = job.get('steps')
    _fail(isinstance(steps, list) and all(s.get('conclusion') in ('success', 'skipped') for s in steps), 'preserved_step_failed')
    matches = [step for step in steps if step.get('name') == publication['publication_step']]
    _fail(len(matches) == 1 and matches[0].get('conclusion') == 'success', 'preserved_publication_step_missing')
    _fail(type(job.get('id')) is int and job['id'] > 0, 'authenticated_job_id_required')
    summary = _job_log_record(get_logs('actions/jobs/' + str(job['id']) + '/logs'), matches[0],
                              r'\[main ([0-9a-f]{7,40})\] chore\(shopify\): 일일 등록 이력 2026-10-23')
    commit = publication['publication_commit']
    _fail(commit.startswith(summary), 'preserved_publication_log_binding')
    base = publication['parent_commit']
    _fail(_git(root, 'rev-list', '--parents', '-n', '1', commit).decode().strip().split() == [commit, base], 'preserved_publication_parent_changed')
    _fail(_git(root, 'rev-parse', commit + '^{tree}').decode().strip() == publication['tree_sha'], 'preserved_publication_tree_changed')
    _git(root, 'merge-base', '--is-ancestor', BASELINE['protected_baseline_commit'], base)
    _git(root, 'merge-base', '--is-ancestor', commit, main)
    before, after = _tree(root, base), _tree(root, commit)
    changed = sorted(filter(None, _git(root, 'diff', '--name-only', '-z', base, commit).decode().split('\0')))
    _fail(changed == sorted(publication['files']), 'preserved_publication_paths_changed')
    for path, values in publication['files'].items():
        _fail(not _immutable(path) and before.get(path) == values['before'] and after.get(path) == values['after'], 'preserved_publication_blob_changed')
    return {'execution_id': identity, 'commit': commit, 'base': base, 'profile': 'exact_preservation', 'paths': changed}


def _job_projection(job):
    fields = ('id', 'run_id', 'run_attempt', 'head_sha', 'head_branch', 'name', 'status', 'conclusion')
    _fail(isinstance(job, dict) and isinstance(job.get('steps'), list), 'blocked_job_schema_invalid')
    return {**{key: job.get(key) for key in fields}, 'steps': [
        {key: step.get(key) for key in ('number', 'name', 'status', 'conclusion', 'started_at', 'completed_at')}
        for step in job['steps']]}


def _canonical_job_log(raw):
    """Only transport-equivalent UTF-8 BOM/CRLF/trailing-LF normalization."""
    _fail(isinstance(raw, bytes) and 0 < len(raw) <= 16*1024*1024, 'job_log_size_limit')
    try:
        text = raw.decode('utf-8')
    except UnicodeError:
        raise ContinuityError('job_log_encoding_invalid') from None
    if text.startswith('\ufeff'):
        text = text[1:]
    # Preserve lone CR, spaces, all body bytes and any second BOM.
    return (text.replace('\r\n', '\n').rstrip('\n') + '\n').encode('utf-8')


def _verify_reconciled_blocked_run(root, run, proof, get, get_logs):
    """One reviewed failed run; no restored local state or new execution grant."""
    identity = str(proof['run_id']) + ':' + str(proof['run_attempt'])
    endpoint = 'actions/runs/' + identity.replace(':', '/attempts/')
    exact = get(endpoint)
    for value in (run, exact):
        _validate_run(value, identity)
        _fail(value.get('path') == proof['workflow'] and value.get('head_sha') == proof['head_sha'] and
              value.get('status') == 'completed' and value.get('conclusion') == 'failure' and
              all(value.get(key) == proof[key] for key in ('created_at', 'updated_at', 'event')) and
              _actor(value.get('actor')) == proof['actor'] and
              _actor(value.get('triggering_actor')) == proof['triggering_actor'], 'blocked_run_binding_changed')
    _fail(code_contract_digest(root, proof['head_sha']) == proof['code_contract_digest'], 'blocked_run_code_changed')
    jobs = get(endpoint + '/jobs?per_page=100')
    _fail(jobs.get('total_count') == 1 and isinstance(jobs.get('jobs'), list) and len(jobs['jobs']) == 1,
          'blocked_run_jobs_incomplete')
    job = jobs['jobs'][0]
    _fail(type(job.get('id')) is int and job['id'] == proof['job_id'] and
          job.get('name') == proof['job_name'] and
          canonical_digest(_job_projection(job)) == proof['job_projection_digest'], 'blocked_job_binding_changed')
    raw = _canonical_job_log(get_logs('actions/jobs/' + str(proof['job_id']) + '/logs'))
    _fail(hashlib.sha256(raw).hexdigest() == proof['canonical_job_log_sha256'], 'blocked_complete_log_changed')
    markers = {
        6: ('SOURCE_SAFETY_BLOCKED (.*)', 'authenticated_history_or_checkpoint_reconciliation_required'),
        7: ('OPERATIONS_SAFETY_BLOCKED (.*)', 'authenticated_history_or_reconciliation_required code=artifactless_run_actuation_unproved'),
        13: ('COMMERCE_PIPELINE_OK (.*)', 'offline policy chain complete; authority=false')}
    for number, (expression, expected) in markers.items():
        steps = [step for step in job['steps'] if step.get('number') == number]
        _fail(len(steps) == 1 and _job_log_record(raw, steps[0], expression) == expected, 'blocked_run_effect_proof_missing')
    artifacts = get('actions/runs/' + str(proof['run_id']) + '/artifacts?per_page=100')
    _fail(artifacts.get('total_count') == 0 and artifacts.get('artifacts') == [], 'blocked_run_artifacts_changed')
    return True


def _verify_independent_input(root, run, main, approved_codes, get, get_logs):
    """Authenticate a fixed existing producer, without executing that producer."""
    rid = _run_identity(run)
    _fail(run['path'] == INPUT_PROFILE['workflow'] and run['head_branch'] == 'main' and
          run.get('status') == 'completed' and run.get('conclusion') == 'success', 'independent_input_run_not_complete')
    _fail(code_contract_digest(root, run['head_sha']) in approved_codes, 'independent_input_code_not_approved')
    endpoint = 'actions/runs/' + rid.replace(':', '/attempts/')
    exact = get(endpoint)
    _validate_run(exact, rid)
    _fail(all(exact.get(k) == run.get(k) for k in ('head_sha', 'status', 'conclusion', 'path')), 'independent_input_attempt_changed')
    jobs_doc = get(endpoint + '/jobs?per_page=100')
    jobs = jobs_doc.get('jobs')
    _fail(jobs_doc.get('total_count') == 1 and isinstance(jobs, list) and len(jobs) == 1, 'independent_input_jobs_incomplete')
    job = jobs[0]
    _fail(job.get('name') == INPUT_PROFILE['job_name'] and job.get('run_id') == run['id'] and
          job.get('head_sha') == run['head_sha'] and job.get('status') == 'completed' and job.get('conclusion') == 'success', 'independent_input_job_binding')
    steps = job.get('steps')
    _fail(isinstance(steps, list) and all(s.get('conclusion') in ('success', 'skipped') for s in steps), 'independent_input_step_failed')
    publication_steps = [s for s in steps if s.get('name') == INPUT_PROFILE['publication_step']]
    _fail(len(publication_steps) == 1 and publication_steps[0].get('conclusion') == 'success', 'independent_publication_step_missing')
    _fail(type(job.get('id')) is int and job['id'] > 0, 'authenticated_job_id_required')
    result = _publication_from_job(get_logs('actions/jobs/' + str(job['id']) + '/logs'), publication_steps[0])
    _fail(result.get('status') == 'published' and result.get('publication_profile') == 'non_operations' and
          result.get('operations_producer_status') == 'excluded_by_profile' and
          result.get('declared_runtime_commands') == INPUT_RUNTIME_COMMANDS, 'independent_publication_profile_invalid')
    commands = result.get('executed_commands')
    _fail(isinstance(commands, list) and len(commands) == 8 and commands[:5] == INPUT_RUNTIME_COMMANDS and
          commands[5][:3] == ['scripts/check_release_quality.py', '--phase', 'candidate'] and
          commands[6][:3] == ['scripts/check_release_quality.py', '--phase', 'final'] and
          commands[7] == ['scripts/audit_team_reports.py'], 'independent_publication_command_changed')
    attempts = result.get('attempts')
    _fail(isinstance(attempts, list) and 1 <= len(attempts) <= 3 and
          all(a.get('validated') is True and a.get('publication_profile') == 'non_operations' for a in attempts), 'independent_publication_validation_missing')
    for index, attempt in enumerate(attempts, 1):
        _fail(type(attempt.get('attempt')) is int and attempt['attempt'] == index and
              isinstance(attempt.get('remote_sha'), str) and HEX40.fullmatch(attempt['remote_sha']) and
              (attempt.get('push_rejected') is True if index < len(attempts) else not attempt.get('push_rejected', False)),
              'independent_publication_attempt_sequence_invalid')
        if index > 1:
            _git(root, 'merge-base', '--is-ancestor', attempts[index-2]['remote_sha'], attempt['remote_sha'])
    commit, original_base = result.get('commit_sha'), result.get('base_sha')
    base = attempts[-1]['remote_sha']
    _fail(isinstance(commit, str) and HEX40.fullmatch(commit) and isinstance(original_base, str) and HEX40.fullmatch(original_base), 'independent_commit_missing')
    _git(root, 'merge-base', '--is-ancestor', original_base, base)
    _fail(code_contract_digest(root, base) in approved_codes, 'independent_publication_parent_code_not_approved')
    parents = _git(root, 'rev-list', '--parents', '-n', '1', commit).decode().strip().split()
    _fail(parents == [commit, base], 'independent_publication_parent_mismatch')
    _git(root, 'merge-base', '--is-ancestor', BASELINE['protected_baseline_commit'], base)
    _git(root, 'merge-base', '--is-ancestor', commit, main)
    before, after = _tree(root, base), _tree(root, commit)
    _fail({p:v for p,v in before.items() if _code(p)} == {p:v for p,v in after.items() if _code(p)}, 'independent_publication_code_changed')
    _fail({p:v for p,v in before.items() if _data(p) and _effect_state(p)} ==
          {p:v for p,v in after.items() if _data(p) and _effect_state(p)}, 'independent_publication_effect_state_changed')
    for path, identity in before.items():
        if _data(path) and _immutable(path):
            _fail(after.get(path) == identity, 'independent_publication_history_changed')
    policy = _json(_git(root, 'show', run['head_sha'] + ':config/publish_policy.json'))
    _fail(policy.get('non_operations_runtime_commands') == INPUT_RUNTIME_COMMANDS, 'independent_policy_commands_changed')
    derived = policy.get('derived_paths')
    _fail(isinstance(derived, list) and all(isinstance(p, str) for p in derived), 'independent_policy_scope_invalid')
    changed = _git(root, 'diff-tree', '--no-commit-id', '--name-only', '-r', '-z', commit).decode().split('\0')
    for path in filter(None, changed):
        allowed = path.startswith('obsidian/') or _profile_data_output(path)
        _fail(allowed and not _effect_state(path), 'independent_publication_path_denied:' + path)
    for path in GUARDED_INPUTS:
        if path in before or path in after:
            _fail(path in before and path in after and
                  _protected_fields(_git(root, 'show', base + ':' + path, cap=MAX_FILE_BYTES)) ==
                  _protected_fields(_git(root, 'show', commit + ':' + path, cap=MAX_FILE_BYTES)), 'independent_source_safety_changed')
    return {'execution_id': rid, 'commit': commit, 'base': base, 'profile': 'non_operations',
            'paths': sorted(p for p in changed if p.startswith('data/'))}



def _verify_prior_restricted(root, identity, main, code_digest, decision_blob, get, get_logs, *, now, listed=None):
    """A report annotation is a lookup hint, never publication authority."""
    endpoint = 'actions/runs/' + identity.replace(':', '/attempts/')
    run = get(endpoint)
    _validate_run(run, identity)
    _fail(run.get('path') in RESTRICTED_WORKFLOWS, 'prior_workflow_not_restricted')
    if listed is not None:
        _fail(_inventory_snapshot([run]) == _inventory_snapshot([listed]), 'prior_attempt_changed_during_discovery')
    _fail(run.get('status') == 'completed' and run.get('conclusion') in ('success', 'failure', 'cancelled'),
          'prior_restricted_run_not_complete')
    _fail(code_contract_digest(root, run['head_sha']) == code_digest and
          _tree(root, run['head_sha']).get(DECISION_PATH, {}).get('git_blob') == decision_blob,
          'prior_restricted_run_binding_changed')
    jobs = get(endpoint + '/jobs?per_page=100')
    _fail(jobs.get('total_count') == 1 and isinstance(jobs.get('jobs'), list) and len(jobs['jobs']) == 1,
          'prior_restricted_jobs_incomplete')
    job = jobs['jobs'][0]
    _fail(job.get('run_id') == run['id'] and job.get('head_sha') == run['head_sha'] and
          job.get('name') == RESTRICTED_WORKFLOWS[run['path']] and job.get('status') == 'completed', 'prior_restricted_job_binding')
    steps = job.get('steps')
    _fail(isinstance(steps, list), 'prior_restricted_steps_missing')
    for name in RESTRICTED_PROOF_STEPS:
        found = [step for step in steps if step.get('name') == name]
        _fail(len(found) == 1 and found[0].get('conclusion') == 'success', 'prior_restricted_stage_unproven')
    found = [step for step in steps if step.get('name') == RESTRICTED_PUBLICATION_STEP]
    _fail(len(found) == 1 and found[0].get('conclusion') in ('success', 'failure', 'cancelled'), 'prior_publication_step_missing')
    _fail(type(job.get('id')) is int and job['id'] > 0, 'authenticated_job_id_required')
    result = _json(_job_log_record(get_logs('actions/jobs/' + str(job['id']) + '/logs'), found[0],
                                   r'RESTRICTED_ANALYSIS_PUBLISHED (.*)'))
    _fail(result.get('status') == 'restricted_analysis_published' and result.get('publication_profile') == MODE and
          result.get('mode') == MODE and result.get('continuity') == 'unresolved_gap' and
          result.get('production_recovered') is False and result.get('operations_execution_verified') is False and
          result.get('old_run_provider_calls') is None and result.get('old_run_provider_cost') is None and
          result.get('declared_runtime_commands') == [] and result.get('executed_commands') == [] and
          result.get('operations_producer_status') == 'quarantined_not_attempted' and
          result.get('execution_id') == identity and result.get('run_id') == run['id'] and
          result.get('run_attempt') == run['run_attempt'] and result.get('actor') == _actor(run.get('actor')) and
          result.get('triggering_actor') == _actor(run.get('triggering_actor')), 'prior_publication_authority_changed')
    commit, base = result.get('commit_sha'), result.get('input_commit')
    _fail(isinstance(commit, str) and HEX40.fullmatch(commit) and isinstance(base, str) and HEX40.fullmatch(base),
          'prior_publication_commit_missing')
    _fail(_git(root, 'rev-list', '--parents', '-n', '1', commit).decode().strip().split() == [commit, base],
          'prior_publication_parent_mismatch')
    _git(root, 'merge-base', '--is-ancestor', commit, main)
    published = _json(_git(root, 'show', commit + ':' + REPORT_PATH))
    validate_published_review(root, published, now=now, check_inputs=False, require_history=False)
    for key in ('execution_id', 'run_id', 'run_attempt', 'actor', 'triggering_actor', 'analysis_id', 'decision_digest',
                'input_commit', 'input_digests', 'code_contract_digest', 'protected_inventory_digest', 'gap_ids'):
        _fail(result.get(key) == published.get(key), 'prior_publication_report_binding')
    allowed = set(restricted_output_paths(published))
    changed = set(filter(None, _git(root, 'diff', '--name-only', '-z', base, commit).decode().split('\0')))
    _fail(REPORT_PATH in changed, 'prior_publication_delta_not_restricted')
    base_tree = _tree(root, base)
    _fail(all(path == REPORT_PATH or path not in base_tree for path in changed), 'prior_publication_history_not_append_only')
    extra = changed - allowed
    if extra:
        captured_commit = result.get('base_sha')
        _fail(len(extra) == 1, 'prior_publication_delta_not_restricted')
        captured_path = next(iter(extra))
        _fail(bool(re.fullmatch(re.escape(HISTORY_DIR) + r'[0-9a-f]{64}\.json', captured_path)) and
              isinstance(captured_commit, str) and HEX40.fullmatch(captured_commit), 'prior_publication_delta_not_restricted')
        captured_id = captured_path[len(HISTORY_DIR):-5]
        _git(root, 'merge-base', '--is-ancestor', captured_commit, base)
        _fail(code_contract_digest(root, captured_commit) == code_digest and
              _tree(root, captured_commit).get(DECISION_PATH, {}).get('git_blob') == decision_blob,
              'captured_history_code_decision_changed')
        captured = _json(_git(root, 'show', commit + ':' + HISTORY_DIR + captured_id + '.json'))
        _fail(isinstance(captured, dict) and set(captured) == set(_immutable_payload(published)), 'captured_history_schema_invalid')
        captured_report = dict(published)
        captured_report.update(captured)
        captured_report['input_commit'] = captured_commit
        validate_published_review(root, captured_report, now=now, check_inputs=False, require_history=False)
        _fail(captured_report['analysis_id'] == captured_id, 'captured_history_identity_changed')
        findings, captures = _pure_findings(root, captured['input_digests'], ref=captured_commit)
        _fail(findings == captured['review_findings'] and captures == captured['original_capture_times'],
              'captured_history_findings_unproven')
    _fail(_json(_git(root, 'show', commit + ':' + HISTORY_DIR + published['analysis_id'] + '.json')) == _immutable_payload(published),
          'prior_publication_history_binding')
    return run


def validate_input_commit_attribution(root, main, publications):
    """Every canonical data delta since c5 must belong to an authenticated proof."""
    commits = _git(root, 'rev-list', '--first-parent', '--reverse', '--max-count=257',
                   BASELINE['protected_baseline_commit'] + '..' + main).decode().split()
    _fail(len(commits) <= 256, 'input_commit_history_bound_exhausted')
    approved = {p['commit']: p for p in publications}
    for commit in commits:
        parents = _git(root, 'rev-list', '--parents', '-n', '1', commit).decode().strip().split()
        _fail(len(parents) >= 2, 'input_commit_parent_missing')
        changed = list(filter(None, _git(root, 'diff', '--name-only', '-z', parents[1], commit).decode().split('\0')))
        canonical = [p for p in changed if p.startswith('data/') and p != DECISION_PATH and not _is_review(p)]
        if canonical:
            _fail(commit in approved and sorted(canonical) == approved[commit]['paths'],
                  'unattributed_canonical_input_change:' + commit)
    return True


def execution_identity(value=None):
    value = value or os.environ.get('RELEASE_EXECUTION_ID') or ':'.join(
        (os.environ.get('GITHUB_RUN_ID', ''), os.environ.get('GITHUB_RUN_ATTEMPT', '')))
    _fail(isinstance(value, str) and bool(EXECUTION.fullmatch(value)), 'exact_run_attempt_required')
    return value


def _run_identity(run):
    _fail(isinstance(run, dict) and type(run.get('id')) is int and run['id'] > 0 and
          type(run.get('run_attempt')) is int and run['run_attempt'] > 0,
          'run_identity_malformed')
    return str(run['id']) + ':' + str(run['run_attempt'])


def _actor(value):
    _fail(isinstance(value, dict) and isinstance(value.get('login'), str) and
          re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,99}(?:\[bot\])?', value['login']) and
          type(value.get('id')) is int and value['id'] > 0, 'authenticated_actor_required')
    return {'login': value['login'], 'id': value['id']}


def _validate_run(run, identity, *, main_only=True):
    _fail(_run_identity(run) == identity and (not main_only or run.get('head_branch') == 'main') and
          isinstance(run.get('path'), str) and bool(HEX40.fullmatch(str(run.get('head_sha', '')))), 'run_binding_mismatch')
    repository = run.get('repository', {})
    _fail(repository.get('full_name') == REPOSITORY, 'run_repository_mismatch')


def approved_history_inventory_digest(runs):
    """Stable approved pre-cutoff identities detect erased runs and old-ID retries."""
    fields = ('id', 'run_attempt', 'head_sha', 'path', 'head_branch')
    selected = [{key: run[key] for key in fields} for run in runs if _time(run['created_at']) < _time(APPROVAL_AT)]
    _fail(len({r['id'] for r in selected}) == len(selected), 'approved_history_duplicate')
    return canonical_digest(sorted(selected, key=lambda row: row['id']))


def authenticate_evidence(root, *, execution_id=None, now=None, transport=None, log_transport=None, purpose='analysis'):
    """Bounded read-only GitHub metadata + content-addressed local Git objects.

    Transport injection is for fixture tests; persisted JSON cannot instantiate
    authenticated evidence. Missing local authenticated Git objects fail closed.
    """
    root = Path(root).resolve()
    identity, instant = execution_identity(execution_id), _time(now)
    if transport is None:
        _fail(os.environ.get('GITHUB_ACTIONS') == 'true' and identity == ':'.join(
            (os.environ.get('GITHUB_RUN_ID', ''), os.environ.get('GITHUB_RUN_ATTEMPT', ''))), 'current_actions_execution_required')
    _fail(purpose in ('analysis', 'publication'), 'authentication_purpose_invalid')
    production = transport is None
    reserve = 0
    read = transport or _github_json
    read_logs = log_transport or _github_job_log
    request_count = 0
    deadline = time.monotonic() + MAX_DISCOVERY_SECONDS
    def get(endpoint):
        nonlocal request_count
        if request_count:
            _require_rate_reserve(reserve + 1, production=production)
        request_count += 1
        _fail(request_count <= MAX_METADATA_REQUESTS and time.monotonic() < deadline, 'metadata_request_budget_exhausted')
        value = read(endpoint)
        _fail(time.monotonic() < deadline, 'metadata_request_budget_exhausted')
        return value
    def get_logs(endpoint):
        nonlocal request_count
        if request_count:
            _require_rate_reserve(reserve + 1, production=production)
        request_count += 1
        _fail(request_count <= MAX_METADATA_REQUESTS and time.monotonic() < deadline, 'metadata_request_budget_exhausted')
        value = read_logs(endpoint)
        _fail(time.monotonic() < deadline, 'metadata_request_budget_exhausted')
        return value
    ref = get('git/ref/heads/main')
    main = ref.get('object', {}).get('sha')
    _fail(isinstance(main, str) and bool(HEX40.fullmatch(main)) and ref.get('ref') == 'refs/heads/main', 'main_ref_invalid')
    tree = _tree(root, main)
    _git(root, 'merge-base', '--is-ancestor', BASELINE['protected_baseline_commit'], main)
    _fail(DECISION_PATH in tree, 'main_approval_missing')
    decision = load_decision(root)
    _decision_shape(decision, instant)
    _fail(_blob(_read(root, DECISION_PATH)) == tree[DECISION_PATH]['git_blob'], 'decision_not_authenticated_main')
    code_digest = code_contract_digest(root, main)
    _fail(code_digest == decision['code_contract_digest'] == code_contract_digest(root), 'code_contract_changed')
    current = get('actions/runs/' + identity.replace(':', '/attempts/'))
    _validate_run(current, identity)
    _fail(current.get('path') in RESTRICTED_WORKFLOWS, 'current_workflow_not_restricted')
    _fail(current.get('status') == 'in_progress', 'current_execution_not_running')
    _actor(current.get('actor'))
    _actor(current.get('triggering_actor'))
    _fail(code_contract_digest(root, current['head_sha']) == code_digest, 'current_run_code_mismatch')
    _fail(_tree(root, current['head_sha']).get(DECISION_PATH) == tree[DECISION_PATH], 'current_run_decision_mismatch')
    gap = get('actions/runs/39893237129/attempts/1')
    _validate_run(gap, '39893237129:1')
    _fail(gap['head_sha'] == GAP['head_sha'] and gap['path'] == GAP['workflow'] and
          gap.get('status') == 'completed' and gap.get('conclusion') == 'failure', 'original_gap_metadata_changed')
    prior_ids = ()
    if REPORT_PATH in tree:
        raw = _git(root, 'show', main + ':' + REPORT_PATH)
        prior = _json(raw)
        # Offline validity, plus exact Git-authenticated bytes, authorizes only
        # already published restricted annotations. It never certifies old calls.
        validate_published_review(root, prior, now=instant, check_inputs=False)
        prior_ids = tuple(prior['publication_executions'])
    verified_prior = set()
    def verify_prior(identity, listed=None):
        _fail(identity in prior_ids, 'prior_restricted_attempt_unreconciled')
        if identity not in verified_prior:
            _verify_prior_restricted(root, identity, main, code_digest, tree[DECISION_PATH]['git_blob'],
                                     get, get_logs, now=instant, listed=listed)
            verified_prior.add(identity)
    _fail(current['run_attempt'] <= 5, 'current_attempt_bound_exhausted')
    for attempt in range(1, current['run_attempt']):
        earlier_id = str(current['id']) + ':' + str(attempt)
        _fail(earlier_id in prior_ids, 'earlier_current_attempt_unreconciled')
        verify_prior(earlier_id)
    cutoff = _time(gap['created_at'])
    def reserve_capacity(pages):
        nonlocal reserve
        # Analysis leaves room for the later publisher's two scans and final
        # scan; publication leaves one complete pre-push scan plus ref/run reads.
        reserve = (3 * pages + 16) if purpose == 'analysis' else pages + 4
        _require_rate_reserve(2 * pages - 1 + reserve + 16, production=production)
    runs = _discover_runs(get, first_page=reserve_capacity)
    repeated = _discover_runs(get)
    _fail(_inventory_snapshot(runs) == _inventory_snapshot(repeated), 'run_inventory_changed_between_scans')
    _fail(approved_history_inventory_digest(runs) == decision['approved_history_inventory_digest'], 'approved_history_inventory_changed')
    seen_gap, seen_current = False, False
    known_inputs_seen = set()
    preserved_seen = set()
    blocked_seen = set()
    blocked_map = {str(p['run_id']) + ':' + str(p['run_attempt']): p for p in RECONCILED_BLOCKED_RUNS}
    preserved_map = {str(p['run_id']) + ':' + str(p['run_attempt']): p for p in PRESERVED_PUBLICATIONS}
    verified_publications = []
    baseline_code = code_contract_digest(root, BASELINE['protected_baseline_commit'])
    approved_codes = {code_digest, baseline_code}
    for contract in decision['approved_prior_code_contracts']:
        _fail(code_contract_digest(root, contract['commit']) == contract['code_contract_digest'], 'prior_code_contract_binding_mismatch')
        approved_codes.add(contract['code_contract_digest'])
    known_input_map = {str(r['run_id']) + ':' + str(r['run_attempt']): r for r in KNOWN_INPUT_RUNS}
    for run in runs:
        rid = _run_identity(run)
        _validate_run(run, rid, main_only=False)
        if rid == '39893237129:1':
            seen_gap = True
            continue
        if rid == identity:
            seen_current = True
            continue
        if rid in blocked_map:
            _verify_reconciled_blocked_run(root, run, blocked_map[rid], get, get_logs)
            blocked_seen.add(rid)
            continue
        if rid in preserved_map:
            verified_publications.append(_verify_preserved_publication(root, run, main, preserved_map[rid], get, get_logs))
            preserved_seen.add(rid)
            continue
        if rid in known_input_map:
            known = known_input_map[rid]
            exact = get('actions/runs/' + rid.replace(':', '/attempts/'))
            _validate_run(exact, rid)
            _fail(exact.get('head_sha') == known['head_sha'] and exact.get('path') == known['workflow'] and
                  exact.get('status') == 'completed' and exact.get('conclusion') == 'success', 'known_input_run_changed')
            known_inputs_seen.add(rid)
            continue
        is_new = _time(run.get('created_at')) >= cutoff or _time(run.get('updated_at')) >= cutoff
        if not is_new:
            continue
        if run['path'] == INPUT_PROFILE['workflow']:
            _fail(run['run_attempt'] <= 5, 'independent_attempt_bound_exhausted')
            for attempt in range(1, run['run_attempt']):
                earlier = get('actions/runs/' + str(run['id']) + '/attempts/' + str(attempt))
                verified_publications.append(_verify_independent_input(root, earlier, main, approved_codes, get, get_logs))
            verified_publications.append(_verify_independent_input(root, run, main, approved_codes, get, get_logs))
            continue
        if run['path'] in PURE_WORKFLOWS:
            _fail(code_contract_digest(root, run['head_sha']) in approved_codes, 'pure_workflow_code_not_approved')
            continue
        _fail(run['path'] in RESTRICTED_WORKFLOWS, 'additional_unapproved_run_or_attempt:' + rid)
        _fail(run['run_attempt'] <= 5 and all(str(run['id']) + ':' + str(a) in prior_ids for a in range(1, run['run_attempt'] + 1)),
              'prior_restricted_attempt_unreconciled')
        for attempt in range(1, run['run_attempt'] + 1):
            verify_prior(str(run['id']) + ':' + str(attempt), run if attempt == run['run_attempt'] else None)
    for prior_id in prior_ids:
        if prior_id != identity:
            verify_prior(prior_id)
    _fail(seen_gap and seen_current, 'exact_gap_or_current_run_missing')
    _fail(known_inputs_seen == set(known_input_map), 'known_input_run_missing')
    _fail(preserved_seen == set(preserved_map), 'preserved_publication_run_missing')
    _fail(blocked_seen == set(blocked_map), 'reconciled_blocked_run_missing')
    validate_input_commit_attribution(root, main, verified_publications)
    _fail(get('git/ref/heads/main') == ref, 'main_changed_during_discovery')
    _fail(len(prior_ids) < 100, 'publication_annotation_limit')
    return VerifiedEvidence(main, current, [dict(GAP)], instant.isoformat(),
                            {p: v for p, v in tree.items() if _data(p)}, code_digest,
                            tree[DECISION_PATH]['git_blob'], prior_ids, canonical_digest(_inventory_snapshot(runs)), len(runs),
                            request_count, _API_ACCOUNTING['remaining'] if production else None,
                            _API_ACCOUNTING['limit'] if production else None, _API_ACCOUNTING['reset'] if production else None,
                            reserve, production, _SEAL)


def validate_decision(decision, *, root, evidence=None, now=None, execution_id=None):
    instant = _time(now)
    _decision_shape(decision, instant)
    if evidence is None:
        evidence = authenticate_evidence(root, execution_id=execution_id, now=instant)
    _fail(type(evidence) is VerifiedEvidence and evidence.seal is _SEAL, 'authenticated_evidence_required')
    _fail(timedelta(0) <= instant - _time(evidence.observed_at) <= EVIDENCE_TTL, 'evidence_expired_or_future')
    _fail(evidence.gap_inventory == decision['gap_inventory'], 'gap_inventory_mismatch')
    _fail(evidence.code_digest == decision['code_contract_digest'] == code_contract_digest(root), 'code_contract_changed')
    _fail(_blob(_read(root, DECISION_PATH)) == evidence.decision_blob and load_decision(root) == decision,
          'decision_binding_changed')
    if execution_id is not None:
        _fail(_run_identity(evidence.run) == execution_identity(execution_id), 'execution_binding_changed')
    inventory = protected_inventory(root)
    _fail(_tree_projection(inventory) == evidence.data_tree, 'inputs_not_exact_authenticated_main')
    _fail(frozen_inventory_digest(inventory) == decision['frozen_inventory_digest'], 'frozen_baseline_changed')
    _fail(baseline_frozen_digest(root) == decision['frozen_inventory_digest'], 'original_baseline_binding_changed')
    validate_original_history(root, inventory)
    return {'mode': MODE, 'decision_digest': canonical_digest(decision), 'evidence': evidence,
            'inventory': inventory, 'protected_inventory_digest': canonical_digest(inventory)}


def validate_pending_decision(root, *, now=None):
    """Offline scope/binding check only: no report, no resumed-analysis claim."""
    decision = load_decision(root)
    _decision_shape(decision, now)
    _fail(code_contract_digest(root) == decision['code_contract_digest'], 'code_contract_changed')
    _fail(frozen_inventory_digest(protected_inventory(root)) == decision['frozen_inventory_digest'] == baseline_frozen_digest(root), 'frozen_baseline_changed')
    validate_original_history(root, protected_inventory(root))
    return {'mode': MODE, 'continuity': 'unresolved_gap', 'status': 'RESTRICTED_ANALYSIS_PENDING',
            'production_recovered': False, 'operations_execution_verified': False,
            'analyzed_at': None, 'decision_digest': canonical_digest(decision)}


def _rows(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ('products', 'all_scored', 'items', 'rows', 'offers', 'offers_by_product', 'teams', 'checks'):
            if isinstance(value.get(key), list):
                return value[key]
            if isinstance(value.get(key), dict):
                return list(value[key].values())
    return []


def _pure_findings(root, input_digests, *, ref=None):
    """Fixed comparisons only; never interpret commands, URLs or instructions."""
    findings, captures = {}, {}
    for path in INPUT_PATHS:
        raw = _read(root, path) if ref is None else _git(root, 'show', ref + ':' + path, cap=MAX_FILE_BYTES)
        _fail(hashlib.sha256(raw).hexdigest() == input_digests[path], 'analysis_input_bytes_changed')
        value = _json(raw)
        baseline_raw = _git(root, 'show', BASELINE['protected_baseline_commit'] + ':' + path, cap=MAX_FILE_BYTES)
        baseline = _json(baseline_raw)
        rows, old_rows = _rows(value), _rows(baseline)
        captures[path] = {key: value[key] for key in ('captured_at', 'collected_at', 'generated_at', 'updated_at', 'vision_at')
                          if isinstance(value, dict) and isinstance(value.get(key), str)}
        row_captures = sorted({r[key] for r in rows if isinstance(r, dict)
                               for key in ('captured_at', 'collected_at', 'updated_at') if isinstance(r.get(key), str)})
        if row_captures:
            captures[path]['oldest_row_capture'] = row_captures[0]
            captures[path]['newest_row_capture'] = row_captures[-1]
        blocked = sum(1 for row in rows if isinstance(row, dict) and
                      (row.get('blocked') is True or row.get('status') in ('blocked', 'hold', 'needs_review')))
        numeric = {}
        for key in ('price', 'quantity', 'stock', 'sale_price', 'price_krw', 'price_usd', 'retail_usd'):
            numbers = [r[key] for r in rows if isinstance(r, dict) and type(r.get(key)) in (int, float)]
            prior_numbers = [r[key] for r in old_rows if isinstance(r, dict) and type(r.get(key)) in (int, float)]
            if numbers:
                numeric[key] = {'observations': len(numbers), 'minimum': min(numbers), 'maximum': max(numbers),
                                'baseline_minimum': min(prior_numbers) if prior_numbers else None,
                                'baseline_maximum': max(prior_numbers) if prior_numbers else None}
        def index(items):
            indexed = {}
            for row in items:
                if not isinstance(row, dict):
                    continue
                identity = next((str(row[key]) for key in ('pd_no', 'canonical_product_id', 'pdNo', 'id', 'team')
                                 if isinstance(row.get(key), (str, int))), None)
                if identity is not None:
                    # Repeated IDs remain an explicit review issue, never deduplicated as an action.
                    indexed.setdefault(identity, []).append(canonical_digest(row))
            return indexed
        current_index, prior_index = index(rows), index(old_rows)
        keys, prior_keys = set(current_index), set(prior_index)
        changes = {'baseline_commit': BASELINE['protected_baseline_commit'],
                   'baseline_sha256': hashlib.sha256(baseline_raw).hexdigest(),
                   'bytes_changed': input_digests[path] != hashlib.sha256(baseline_raw).hexdigest(),
                   'added_cached_ids': len(keys - prior_keys), 'removed_cached_ids': len(prior_keys - keys),
                   'changed_cached_ids': sum(current_index[k] != prior_index[k] for k in keys & prior_keys),
                   'duplicate_cached_ids': sum(len(v) > 1 for v in current_index.values())}
        blockers = {key: len(value[key]) for key in ('blockers', 'blocking', 'checks', '오래_막힌_팀')
                    if isinstance(value, dict) and isinstance(value.get(key), (dict, list))}
        findings[path] = {'sha256': input_digests[path], 'cached_rows': len(rows),
                          'explicit_blocked_rows': blocked, 'cached_numeric_ranges': numeric,
                          'input_changes': changes, 'remaining_review_counts': blockers,
                          'freshness_basis': 'original_capture_timestamps_unchanged',
                          'interpretation': 'saved_evidence_only_no_approval_or_gate_change'}
    return findings, captures


def _analysis_identity(decision_digest, code_digest, input_digests):
    return canonical_digest({'kind': 'cached_review_v1', 'decision_digest': decision_digest,
                             'code_contract_digest': code_digest, 'input_digests': input_digests})


def _immutable_payload(report):
    fields = ('schema_version', 'mode', 'continuity', 'result', 'production_recovered',
              'operations_execution_verified', 'old_run_provider_calls', 'old_run_provider_cost',
              'effective_new_request_allowance', 'allowed_effects', 'forbidden_effects',
              'decision_digest', 'gap_ids', 'code_contract_digest', 'input_digests', 'analysis_id',
              'analyzed_at', 'original_capture_times', 'blocked_capabilities', 'review_findings')
    return {key: report[key] for key in fields}


def build_review(root, *, decision=None, evidence=None, now=None, execution_id=None):
    instant = _time(now)
    decision = load_decision(root) if decision is None else decision
    context = validate_decision(decision, root=root, evidence=evidence, now=instant, execution_id=execution_id)
    evidence = context['evidence']
    digests = {p: context['inventory'][p]['sha256'] for p in INPUT_PATHS}
    analysis_id = _analysis_identity(context['decision_digest'], decision['code_contract_digest'], digests)
    findings, captures = _pure_findings(root, digests)
    report = {'schema_version': 1, 'mode': MODE, 'continuity': 'unresolved_gap',
              'result': 'restricted_analysis_complete', 'status': 'RESTRICTED_ANALYSIS_COMPLETE',
              'production_recovered': False, 'operations_execution_verified': False,
              'old_run_provider_calls': None, 'old_run_provider_cost': None, 'effective_new_request_allowance': 0,
              'allowed_effects': list(ALLOWED_EFFECTS), 'forbidden_effects': list(FORBIDDEN_EFFECTS),
              'decision_digest': context['decision_digest'], 'gap_ids': ['39893237129:1'],
              'code_contract_digest': decision['code_contract_digest'], 'input_commit': evidence.main_commit,
              'input_digests': digests, 'protected_inventory_digest': context['protected_inventory_digest'],
              'analysis_id': analysis_id, 'analyzed_at': instant.isoformat(),
              'original_capture_times': captures, 'blocked_capabilities': {k: 'quarantined/not_attempted' for k in CAPABILITIES},
              'review_findings': findings, 'execution_id': _run_identity(evidence.run),
              'run_id': evidence.run['id'], 'run_attempt': evidence.run['run_attempt'],
              'actor': _actor(evidence.run['actor']), 'triggering_actor': _actor(evidence.run['triggering_actor']),
              'publication_executions': sorted(set(evidence.publication_executions + (_run_identity(evidence.run),))),
              'gap_observed_at': evidence.observed_at, 'main_authentication': 'github_authenticated_ref_and_exact_git_bytes'}
    history = HISTORY_DIR + analysis_id + '.json'
    if _safe(root, history).exists():
        old = _json(_read(root, history, MAX_JSON_BYTES))
        _fail(isinstance(old, dict) and set(old) == set(_immutable_payload(report)), 'immutable_review_schema_mismatch')
        report['analyzed_at'] = old.get('analyzed_at')
        _fail(old == _immutable_payload(report), 'immutable_review_collision')
    assert_protected_unchanged(context['inventory'], protected_inventory(root))
    validate_restricted_report(report, root=root, decision=decision, evidence=evidence, now=instant, require_history=False)
    return report


def validate_published_review(root, report, *, now=None, check_inputs=True, require_history=True):
    """Offline publication integrity; does NOT assert live gap discovery freshness."""
    decision = load_decision(root)
    _decision_shape(decision, now)
    _fail(isinstance(report, dict), 'restricted_report_object_required')
    expected = {'schema_version', 'mode', 'continuity', 'result', 'status', 'production_recovered',
                'operations_execution_verified', 'old_run_provider_calls', 'old_run_provider_cost',
                'effective_new_request_allowance', 'allowed_effects', 'forbidden_effects', 'decision_digest',
                'gap_ids', 'code_contract_digest', 'input_commit', 'input_digests', 'protected_inventory_digest',
                'analysis_id', 'analyzed_at', 'original_capture_times', 'blocked_capabilities', 'review_findings',
                'execution_id', 'run_id', 'run_attempt', 'actor', 'triggering_actor', 'publication_executions', 'gap_observed_at', 'main_authentication'}
    _fail(set(report) == expected, 'restricted_report_schema_mismatch')
    _fail(type(report['schema_version']) is int and report['schema_version'] == 1 and report['mode'] == MODE and report['continuity'] == 'unresolved_gap' and
          report['result'] == 'restricted_analysis_complete' and report['status'] == 'RESTRICTED_ANALYSIS_COMPLETE', 'restricted_status_mismatch')
    _fail(report['production_recovered'] is False and report['operations_execution_verified'] is False and
          report['old_run_provider_calls'] is None and report['old_run_provider_cost'] is None and
          type(report['effective_new_request_allowance']) is int and report['effective_new_request_allowance'] == 0, 'restricted_authority_mismatch')
    _fail(report['allowed_effects'] == ALLOWED_EFFECTS and report['forbidden_effects'] == FORBIDDEN_EFFECTS and
          report['blocked_capabilities'] == {k: 'quarantined/not_attempted' for k in CAPABILITIES}, 'restricted_scope_mismatch')
    _fail(report['gap_ids'] == ['39893237129:1'] and report['decision_digest'] == canonical_digest(decision), 'report_decision_gap_mismatch')
    _fail(report['code_contract_digest'] == decision['code_contract_digest'] == code_contract_digest(root), 'report_code_binding_mismatch')
    _fail(isinstance(report['input_digests'], dict) and set(report['input_digests']) == set(INPUT_PATHS) and
          all(isinstance(v, str) and HEX64.fullmatch(v) for v in report['input_digests'].values()), 'report_input_digest_invalid')
    _fail(report['analysis_id'] == _analysis_identity(report['decision_digest'], report['code_contract_digest'], report['input_digests']),
          'analysis_identity_mismatch')
    _fail(isinstance(report['input_commit'], str) and HEX40.fullmatch(report['input_commit']) and
          isinstance(report['protected_inventory_digest'], str) and HEX64.fullmatch(report['protected_inventory_digest']), 'report_binding_invalid')
    execution_identity(report['execution_id'])
    _fail(type(report['run_id']) is int and type(report['run_attempt']) is int and
          report['execution_id'] == str(report['run_id']) + ':' + str(report['run_attempt']), 'report_run_identity_mismatch')
    _fail(report['actor'] == _actor(report['actor']) and report['triggering_actor'] == _actor(report['triggering_actor']), 'report_actor_invalid')
    executions = report['publication_executions']
    _fail(isinstance(executions, list) and 1 <= len(executions) <= 100 and
          all(isinstance(v, str) and EXECUTION.fullmatch(v) for v in executions) and
          executions == sorted(set(executions)) and report['execution_id'] in executions, 'publication_identity_invalid')
    _fail(report['main_authentication'] == 'github_authenticated_ref_and_exact_git_bytes', 'input_provenance_invalid')
    _fail(all(_time(APPROVAL_AT) <= _time(report[key]) <= _time(now) for key in ('analyzed_at', 'gap_observed_at')), 'report_time_invalid')
    if check_inputs:
        inventory = protected_inventory(root)
        _fail(canonical_digest(inventory) == report['protected_inventory_digest'] and
              frozen_inventory_digest(inventory) == decision['frozen_inventory_digest'], 'report_protected_binding_mismatch')
        validate_original_history(root, inventory)
        _fail({p: inventory[p]['sha256'] for p in INPUT_PATHS} == report['input_digests'], 'report_input_binding_mismatch')
        findings, captures = _pure_findings(root, report['input_digests'])
        _fail(findings == report['review_findings'] and captures == report['original_capture_times'], 'report_findings_changed')
    history = HISTORY_DIR + report['analysis_id'] + '.json'
    if require_history:
        _fail(_json(_read(root, history, MAX_JSON_BYTES)) == _immutable_payload(report), 'immutable_review_binding_mismatch')
    return {'mode': MODE, 'analysis_id': report['analysis_id'], 'decision_digest': report['decision_digest'],
            'live_gap_validated': False}


def validate_restricted_report(report, *, root, decision=None, evidence=None, before_inventory=None, now=None, require_history=True):
    instant = _time(now)
    validate_published_review(root, report, now=instant, require_history=require_history)
    context = validate_decision(load_decision(root) if decision is None else decision, root=root, evidence=evidence,
                                execution_id=report['execution_id'], now=instant)
    findings, captures = _pure_findings(root, report['input_digests'])
    _fail(findings == report['review_findings'] and captures == report['original_capture_times'], 'live_baseline_findings_changed')
    verified = context['evidence']
    _fail(report['actor'] == _actor(verified.run['actor']) and
          report['triggering_actor'] == _actor(verified.run['triggering_actor']), 'report_authenticated_actor_mismatch')
    _fail(report['input_commit'] == verified.main_commit and report['gap_observed_at'] == verified.observed_at,
          'report_live_evidence_changed')
    _fail(report['publication_executions'] == sorted(set(verified.publication_executions + (report['execution_id'],))),
          'publication_annotation_changed')
    _fail(report['protected_inventory_digest'] == context['protected_inventory_digest'], 'protected_inventory_mismatch')
    if before_inventory is not None:
        assert_protected_unchanged(before_inventory, context['inventory'])
    return context


def _check_execution_environment(identity):
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        _fail(identity == ':'.join((os.environ.get('GITHUB_RUN_ID', ''), os.environ.get('GITHUB_RUN_ATTEMPT', ''))),
              'current_actions_execution_required')


def validate_review_bindings(root, report, *, execution_id, before_inventory=None, now=None):
    """Independent strict offline candidate check; does not authorize a push."""
    identity = execution_identity(execution_id)
    _check_execution_environment(identity)
    _fail(isinstance(report, dict) and report.get('execution_id') == identity, 'publication_execution_mismatch')
    result = validate_published_review(root, report, now=now)
    _fail(baseline_frozen_digest(root) == load_decision(root)['frozen_inventory_digest'], 'original_baseline_binding_changed')
    if before_inventory is not None:
        assert_protected_unchanged(before_inventory, protected_inventory(root))
    return result


def validate_publication_report(root, report, *, execution_id, before_inventory=None, now=None, evidence=None):
    validate_review_bindings(root, report, execution_id=execution_id, before_inventory=before_inventory, now=now)
    instant = _time(now)
    if evidence is None:
        evidence = authenticate_evidence(root, execution_id=execution_id, now=instant, purpose='publication')
        _fail(timedelta(0) <= instant - _time(report['gap_observed_at']) <= EVIDENCE_TTL, 'report_gap_evidence_expired')
        # Reuse report observation only after a fresh authenticated re-check.
        evidence = replace(evidence, observed_at=report['gap_observed_at'])
    return validate_restricted_report(report, root=root, evidence=evidence, before_inventory=before_inventory, now=instant)


def validate_publication_freshness(root, report, *, evidence, execution_id, now=None, transport=None):
    """One complete scan immediately before push; JSON cannot replace evidence."""
    _fail(type(evidence) is VerifiedEvidence and evidence.seal is _SEAL, 'authenticated_evidence_required')
    identity, instant = execution_identity(execution_id), _time(now)
    validate_publication_report(root, report, execution_id=identity, evidence=evidence, now=instant)
    _fail(not evidence.production_transport or transport is None, 'production_transport_substitution_denied')
    production, read = evidence.production_transport, transport or _github_json
    if production:
        _fail(os.environ.get('GITHUB_ACTIONS') == 'true', 'current_actions_execution_required')
    pages = max(1, (evidence.inventory_count + 99) // 100)
    _require_rate_reserve(pages + 3, production=production)
    count, deadline = 0, time.monotonic() + MAX_DISCOVERY_SECONDS
    def get(endpoint):
        nonlocal count
        _require_rate_reserve(1, production=production)
        count += 1
        _fail(count <= MAX_RUN_PAGES + 3 and time.monotonic() < deadline, 'freshness_request_budget_exhausted')
        value = read(endpoint)
        _fail(time.monotonic() < deadline, 'freshness_request_budget_exhausted')
        return value
    ref = get('git/ref/heads/main')
    _fail(ref == {'ref': 'refs/heads/main', 'object': {'sha': evidence.main_commit}} or
          (ref.get('ref') == 'refs/heads/main' and ref.get('object', {}).get('sha') == evidence.main_commit),
          'latest_main_changed_before_push')
    def reserve_scan(actual_pages):
        _require_rate_reserve(actual_pages - 1 + 2, production=production)
    rows = _discover_runs(get, first_page=reserve_scan)
    _fail(len(rows) == evidence.inventory_count and canonical_digest(_inventory_snapshot(rows)) == evidence.inventory_digest,
          'run_inventory_changed_before_push')
    current = get('actions/runs/' + identity.replace(':', '/attempts/'))
    _validate_run(current, identity)
    _fail(current.get('status') == 'in_progress' and all(current.get(k) == evidence.run.get(k) for k in
          ('head_sha', 'path', 'actor', 'triggering_actor', 'run_attempt', 'head_branch')), 'current_run_changed_before_push')
    _fail(get('git/ref/heads/main') == ref, 'main_changed_during_final_scan')
    completed = _time(now)
    _decision_shape(load_decision(root), completed)
    _fail(timedelta(0) <= completed - _time(evidence.observed_at) <= EVIDENCE_TTL, 'evidence_expired_before_push')
    return {'live_gap_validated': True, 'inventory_count': len(rows), 'inventory_digest': evidence.inventory_digest,
            'authentication_requests': evidence.request_count, 'freshness_requests': count,
            'attempt_total_requests': evidence.request_count + count,
            'process_github_requests': _API_ACCOUNTING['requests'] if production else None,
            'rate_remaining': _API_ACCOUNTING['remaining'] if production else None,
            'rate_limit': _API_ACCOUNTING['limit'] if production else None,
            'rate_reset': _API_ACCOUNTING['reset'] if production else None,
            'reserved_requests': evidence.reserved_requests, 'checked_at': completed.isoformat()}


def restricted_output_paths(report):
    _fail(isinstance(report, dict) and isinstance(report.get('analysis_id'), str) and
          HEX64.fullmatch(report['analysis_id']), 'analysis_identity_invalid')
    return (REPORT_PATH, HISTORY_DIR + report['analysis_id'] + '.json')


def validate_history_member(root, path):
    _fail(isinstance(path, str) and bool(re.fullmatch(re.escape(HISTORY_DIR) + r'[0-9a-f]{64}\.json', path)), 'history_path_invalid')
    value = _json(_read(root, path, MAX_JSON_BYTES))
    required = set(_immutable_payload({k: None for k in (
        'schema_version', 'mode', 'continuity', 'result', 'production_recovered',
        'operations_execution_verified', 'old_run_provider_calls', 'old_run_provider_cost',
        'effective_new_request_allowance', 'allowed_effects', 'forbidden_effects', 'decision_digest',
        'gap_ids', 'code_contract_digest', 'input_digests', 'analysis_id', 'analyzed_at',
        'original_capture_times', 'blocked_capabilities', 'review_findings')}))
    _fail(isinstance(value, dict) and set(value) == required, 'history_schema_invalid')
    _fail(value['mode'] == MODE and value['continuity'] == 'unresolved_gap' and
          value['result'] == 'restricted_analysis_complete' and type(value['schema_version']) is int and value['schema_version'] == 1 and
          value['production_recovered'] is False and value['operations_execution_verified'] is False and
          value['old_run_provider_calls'] is None and value['old_run_provider_cost'] is None and
          type(value['effective_new_request_allowance']) is int and value['effective_new_request_allowance'] == 0 and
          value['allowed_effects'] == ALLOWED_EFFECTS and value['forbidden_effects'] == FORBIDDEN_EFFECTS and
          value['gap_ids'] == ['39893237129:1'] and value['blocked_capabilities'] == {k: 'quarantined/not_attempted' for k in CAPABILITIES},
          'history_restrictions_invalid')
    _fail(all(isinstance(value[k], str) and HEX64.fullmatch(value[k]) for k in ('decision_digest', 'code_contract_digest', 'analysis_id')) and
          isinstance(value['input_digests'], dict) and set(value['input_digests']) == set(INPUT_PATHS) and
          all(isinstance(v, str) and HEX64.fullmatch(v) for v in value['input_digests'].values()), 'history_digests_invalid')
    _fail(isinstance(value['review_findings'], dict) and set(value['review_findings']) == set(INPUT_PATHS) and
          all(isinstance(value['review_findings'][p], dict) and value['review_findings'][p].get('sha256') == value['input_digests'][p] for p in INPUT_PATHS) and
          isinstance(value['original_capture_times'], dict) and set(value['original_capture_times']) == set(INPUT_PATHS), 'history_findings_invalid')
    _fail(value['analysis_id'] == _analysis_identity(value['decision_digest'], value['code_contract_digest'], value['input_digests']) and
          path == HISTORY_DIR + value['analysis_id'] + '.json', 'history_identity_invalid')
    _time(value['analyzed_at'])
    return value


def write_review(root, report, *, now=None):
    validate_published_review(root, report, now=now, require_history=False)
    before = protected_inventory(root)
    latest, history = restricted_output_paths(report)
    payload = _immutable_payload(report)
    history_path = _safe(root, history)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    if history_path.exists():
        _fail(_read(root, history) == encoded, 'immutable_review_bytes_changed')
    else:
        with history_path.open('xb') as stream:
            stream.write(encoded)
    target = _safe(root, latest)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    assert_protected_unchanged(before, protected_inventory(root))
    return restricted_output_paths(report)


def reanalyze_for_publication(root, prior_report, *, input_commit, execution_id, evidence=None):
    # Scope/code/approval may never be silently renewed by a data refresh.
    decision = load_decision(root)
    _fail(prior_report.get('decision_digest') == canonical_digest(decision), 'decision_changed_during_publication')
    if evidence is None:
        evidence = authenticate_evidence(root, execution_id=execution_id, purpose='publication')
    _fail(type(evidence) is VerifiedEvidence and evidence.seal is _SEAL, 'authenticated_evidence_required')
    _fail(evidence.main_commit == input_commit, 'latest_main_changed_during_publication')
    return build_review(root, decision=decision, evidence=evidence, execution_id=execution_id)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('decide', 'analyze', 'validate'))
    parser.add_argument('--root', default='.')
    parser.add_argument('--report', default=REPORT_PATH)
    parser.add_argument('--execution-id')
    parser.add_argument('--output')
    parser.add_argument('--github-output')
    args = parser.parse_args(argv)
    root, result, code = Path(args.root).resolve(), {}, 0
    try:
        if args.command == 'decide':
            context = validate_pending_decision(root)
            result = {'mode': MODE, 'continuity': 'unresolved_gap', 'decision_digest': context['decision_digest']}
        elif args.command == 'analyze':
            _fail(args.report == REPORT_PATH, 'report_output_scope_denied')
            evidence = authenticate_evidence(root, execution_id=args.execution_id)
            report = build_review(root, execution_id=args.execution_id, evidence=evidence)
            write_review(root, report)
            result = {'mode': MODE, 'continuity': 'unresolved_gap', 'analysis_id': report['analysis_id'],
                      'report': REPORT_PATH, 'status': report['status'], 'authentication_requests': evidence.request_count,
                      'rate_remaining': evidence.rate_remaining, 'rate_limit': evidence.rate_limit,
                      'reserved_requests': evidence.reserved_requests}
        else:
            report = _json(_read(root, args.report, MAX_JSON_BYTES))
            validate_review_bindings(root, report, execution_id=execution_identity(args.execution_id))
            result = {'mode': MODE, 'continuity': 'unresolved_gap', 'valid': True, 'analysis_id': report['analysis_id']}
    except (ContinuityError, KeyError, TypeError, OSError) as error:
        result, code = {'mode': 'blocked', 'continuity': 'unresolved_gap', 'reason': str(error)}, 1
    raw = json.dumps(result, ensure_ascii=False, sort_keys=True) + '\n'
    if args.output:
        path = Path(args.output).resolve()
        _fail(not path.is_relative_to(root), 'decision_status_must_be_outside_repository')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding='utf-8')
    if args.github_output:
        _fail(os.environ.get('GITHUB_OUTPUT') == args.github_output and not Path(args.github_output).resolve().is_relative_to(root), 'github_output_scope_denied')
        with open(args.github_output, 'a', encoding='utf-8') as stream:
            stream.write('mode=' + result['mode'] + '\n')
    sys.stdout.write(raw)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
