"""Exact shortlist observer history and narrowly bound diagnostic replacement.

Source identities/captures, request reservations and budgets are never exempted.
Only latest-attempt/derived ID lists may move once their exact prior bytes and
capture/attempt histories are retained. No network, bootstrap or clock refresh.
"""
from __future__ import annotations
from copy import deepcopy
import json
import os
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from scripts.moe_evaluation_history import LOCK_PATH, safe_path, sync_dir, atomic_write, exact_head, sha
from scripts.publish_transaction import removed_identities, deletion_authorized

OUTPUT = 'data/daiso_real/shortlist_observations.json'
LEDGER = 'data/daiso_real/.shortlist_observation_claim.json'
HISTORY = 'data/agents/source_procedures/observer_history'
MANIFEST = 'data/publish_deletions.json'
POLICY_REF = 'scripts/shortlist_observation_history.py'
DIAGNOSTICS = {'attempts','new_success_ids','failed_ids','missing_ids','retained_original_capture_ids'}


def parse(raw):
    from scripts.daiso.observe_shortlist import _unique_object
    def nonfinite(value):
        raise ValueError('shortlist_nonfinite_json')
    return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=nonfinite)


def scope_changed(base, current):
    return parse(base).get('expected_ids') != parse(current).get('expected_ids')


def owned_inputs(root):
    """Read only the observer's fixed public inputs, never manifest-selected paths."""
    from scripts.daiso.observe_shortlist import INPUTS
    from scripts.immutable_snapshot_store import _read
    result = {}
    for name in INPUTS:
        path = safe_path(root, name)
        raw = path.read_bytes() if path.exists() else None
        result[name] = None if raw is None else _read(root, name, sha(raw))
    return result


def input_hashes(inputs):
    return {name: sha(raw) if raw is not None else 'missing' for name, raw in inputs.items()}


def verify_owned_scope(base, current, inputs, base_ledger, current_ledger):
    from scripts.daiso import observe_shortlist as observer
    from scripts.source_safety_checkpoint import _validate, _nonregression
    before, after = parse(base), parse(current)
    if not isinstance(inputs, dict) or set(inputs) != set(observer.INPUTS):
        raise ValueError('shortlist_owned_input_evidence_required')
    if any(raw is not None and not isinstance(raw, bytes) for raw in inputs.values()):
        raise ValueError('shortlist_owned_input_bytes_required')
    hashes = input_hashes(inputs)
    if after.get('inputs_byte_identical') is not True or after.get('input_hashes_before') != hashes or after.get('input_hashes_after') != hashes:
        raise ValueError('shortlist_owned_input_hash_mismatch')
    names = ('data/shopify_shortlist.json', 'data/product_master.json', 'data/daiso_real/products.json')
    if any(inputs[name] is None for name in names):
        raise ValueError('shortlist_owned_membership_inputs_missing')
    shortlist, master, catalog = (parse(inputs[name]) for name in names)
    pairs = observer._members_from_documents(shortlist, master, catalog)
    expected = [cp for _, cp in pairs]
    if after.get('expected_ids') != expected:
        raise ValueError('shortlist_owned_membership_mismatch')
    old_ids = before.get('expected_ids')
    registry = master['pd_no_to_cp']
    if not isinstance(old_ids, list) or not old_ids or len(old_ids) != len(set(old_ids)) or not set(old_ids) <= set(registry.values()):
        raise ValueError('shortlist_previous_scope_not_canonical')
    for doc in (before, after):
        for key in ('products', 'retained_previous_products', 'capture_history'):
            if any(registry.get(r.get('pd_no')) != r.get('canonical_product_id') for r in doc.get(key, [])):
                raise ValueError('shortlist_historical_identity_remapped')
    if any((r.get('pd_no'), r.get('canonical_product_id')) not in pairs for r in after.get('products', [])):
        raise ValueError('shortlist_capture_outside_owned_scope')
    if not isinstance(base_ledger, bytes) or not isinstance(current_ledger, bytes):
        raise ValueError('shortlist_scope_ledger_evidence_required')
    old = {OUTPUT: base, LEDGER: base_ledger}
    new = {OUTPUT: current, LEDGER: current_ledger}
    _validate(old); _validate(new); _nonregression(old, new)
    old_claim, new_claim = parse(base_ledger), parse(current_ledger)
    # The ledger's identities are lifetime reservations, not current membership.
    if not set(old_claim.get('expected_ids', [])) <= set(new_claim.get('expected_ids', [])):
        raise ValueError('shortlist_reserved_identity_loss')
    checkpoint = after['budget_checkpoint']
    if any(checkpoint.get(k) != new_claim.get(k) for k in ('total_http_attempts', 'last_run_attempt_at', 'last_request_at', 'last_checked_at')) or checkpoint['request_history_sha256'] != observer._history_digest(new_claim['request_history']):
        raise ValueError('shortlist_current_ledger_checkpoint_mismatch')
    return expected


def validate_transition(base, current, policy, *, inputs=None, base_ledger=None, current_ledger=None):
    before, after = parse(base), parse(current)
    if after.get('schema_version') != 2 or after.get('scope') != 'active_shopify_shortlist_only' or after.get('operating_catalog_mutated') is not False:
        raise ValueError('shortlist_scope_or_schema_changed')
    changed = before.get('expected_ids') != after.get('expected_ids')
    if changed:
        verify_owned_scope(base, current, inputs, base_ledger, current_ledger)
    if after.get('inputs_byte_identical') is not True or after.get('input_hashes_before') != after.get('input_hashes_after'):
        raise ValueError('shortlist_operating_inputs_mutated')
    retained = after.get('capture_history') or []
    for row in before.get('products', []) + before.get('retained_previous_products', []) + before.get('capture_history', []):
        if row not in retained: raise ValueError('shortlist_capture_history_lost')
    previous_attempts = before.get('attempts') or []
    if previous_attempts and not any(e.get('attempts') == previous_attempts and e.get('budget_checkpoint') == before.get('budget_checkpoint') and e.get('status') == before.get('status') for e in after.get('observation_history', [])):
        raise ValueError('shortlist_attempt_history_lost')
    for event in before.get('observation_history', []):
        if not any(event == e or ('legacy_budget_proof' not in event and event == {k:v for k,v in e.items() if k != 'legacy_budget_proof'}) for e in after.get('observation_history', [])):
            raise ValueError('shortlist_observation_history_lost')
    old = before.get('budget_checkpoint') or {}
    new = after.get('budget_checkpoint') or {}
    if new.get('total_http_attempts', -1) < old.get('total_http_attempts', before.get('http_attempt_count',0)):
        raise ValueError('shortlist_lifetime_request_counter_regression')
    # Actual products/capture histories and all invariant fields remain checked.
    left, right = deepcopy(before), deepcopy(after)
    permitted = []
    contract = {'identity_fields':policy['identity_fields']}
    # A current active view can contract only after exact input/capture/ledger
    # replay. Its old IDs and complete source bytes remain immutable below.
    for key in DIAGNOSTICS | ({'expected_ids', 'products'} if changed else set()):
        permitted.extend(removed_identities(left.get(key), right.get(key), contract))
        left.pop(key, None); right.pop(key, None)
    unexpected = removed_identities(left, right, contract)
    if unexpected: raise ValueError('shortlist_non_diagnostic_removal')
    return sorted(set(permitted))


def scope_record(base, current, policy, inputs, base_ledger, current_ledger):
    ids = validate_transition(base, current, policy, inputs=inputs,
                              base_ledger=base_ledger, current_ledger=current_ledger)
    return {'schema_version': 1, 'kind': 'owned_shortlist_scope_reconciliation',
            'base_output_sha256': sha(base), 'replacement_output_sha256': sha(current),
            'base_ledger_sha256': sha(base_ledger), 'replacement_ledger_sha256': sha(current_ledger),
            'input_hashes': input_hashes(inputs), 'expected_ids_before': parse(base)['expected_ids'],
            'expected_ids_after': parse(current)['expected_ids'], 'removed_ids': ids}


def verify_scope_evidence(base, current, policy, evidence):
    if not isinstance(evidence, dict):
        raise ValueError('shortlist_scope_evidence_missing')
    expected = scope_record(base, current, policy, evidence['inputs'],
                            evidence['base_ledger'], evidence['current_ledger'])
    if evidence['record'] != expected:
        raise ValueError('shortlist_scope_receipt_mismatch')
    for raw in (base, current, evidence['base_ledger'], evidence['current_ledger'],
                *[v for v in evidence['inputs'].values() if v is not None]):
        if evidence['archives'].get(sha(raw)) != raw:
            raise ValueError('shortlist_exact_scope_archive_missing')
    return expected['removed_ids']


def load_scope_evidence(root, base, current, policy, manifest):
    """Publisher independently replays the proof, then binds it to live inputs."""
    from scripts.immutable_snapshot_store import _read
    from scripts.daiso.observe_shortlist import INPUTS
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 1 or not isinstance(manifest.get('deletions'), list) or any(not isinstance(r, dict) for r in manifest['deletions']):
        raise ValueError('shortlist_scope_manifest_invalid')
    entries = [r for r in manifest['deletions'] if r.get('path') == OUTPUT
               and r.get('base_sha256') == sha(base) and r.get('replacement_sha256') == sha(current)
               and r.get('policy_ref') == POLICY_REF]
    if len(entries) != 1:
        raise ValueError('shortlist_scope_manifest_missing_or_ambiguous')
    archives = {}
    def read(digest):
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('shortlist_scope_archive_digest_invalid')
        raw = _read(root, HISTORY + '/' + digest + '.json', digest)
        archives[digest] = raw
        return raw
    record = parse(read(entries[0].get('scope_evidence_sha256')))
    hashes = record.get('input_hashes', {})
    if set(hashes) != set(INPUTS):
        raise ValueError('shortlist_scope_input_inventory_mismatch')
    inputs = {n: None if hashes[n] == 'missing' else read(hashes[n]) for n in INPUTS}
    read(sha(base)); read(sha(current))
    evidence = {'inputs': inputs, 'base_ledger': read(record.get('base_ledger_sha256')),
                'current_ledger': read(record.get('replacement_ledger_sha256')),
                'record': record, 'archives': archives, 'manifest_entry': entries[0]}
    ids = verify_scope_evidence(base, current, policy, evidence)
    if entries[0].get('ids') != ids or entries[0].get('delete_file') is not False:
        raise ValueError('shortlist_scope_manifest_ids_mismatch')
    if owned_inputs(root) != inputs or safe_path(root, LEDGER).read_bytes() != evidence['current_ledger']:
        raise ValueError('shortlist_scope_live_inputs_changed')
    return evidence


def verify_final_scope(root, evidence):
    """Derived clocks may advance; product identity mappings must not change."""
    from scripts.daiso.observe_shortlist import _members, _members_from_documents, _read
    inputs = evidence['inputs']
    names = ('data/shopify_shortlist.json', 'data/product_master.json', 'data/daiso_real/products.json')
    documents = [parse(inputs[name]) for name in names]
    if _members(root) != _members_from_documents(*documents) or _read(root, names[1])['pd_no_to_cp'] != documents[1]['pd_no_to_cp']:
        raise ValueError('final regenerated shortlist identities changed after observation')
    manifest = parse(safe_path(root, MANIFEST).read_bytes())
    entries = [r for r in manifest.get('deletions', []) if isinstance(r, dict)
               and r.get('path') == OUTPUT and r.get('policy_ref') == POLICY_REF]
    if entries != [evidence['manifest_entry']]:
        raise ValueError('shortlist_final_scope_manifest_changed')
    from scripts.immutable_snapshot_store import _read as read_exact
    for digest, raw in evidence['archives'].items():
        if read_exact(root, HISTORY + '/' + digest + '.json', digest) != raw:
            raise ValueError('shortlist_final_scope_archive_changed')


def preserve(root, *, previous_output=None, previous_ledger=None):
    root = Path(root).absolute()
    lock = safe_path(root, LOCK_PATH)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.fsync(fd)
        output = safe_path(root, OUTPUT).read_bytes()
        ledger = safe_path(root, LEDGER).read_bytes()
        base = exact_head(root, OUTPUT)
        base_ledger = exact_head(root, LEDGER)
        policy = json.loads(safe_path(root, 'config/publish_policy.json').read_bytes())
        inputs = owned_inputs(root) if scope_changed(base, output) or (previous_output is not None and scope_changed(previous_output, output)) else None
        ids = validate_transition(base, output, policy, inputs=inputs, base_ledger=base_ledger, current_ledger=ledger)
        if previous_output is not None:
            validate_transition(previous_output, output, policy, inputs=inputs,
                                base_ledger=previous_ledger, current_ledger=ledger)
        for raw in (base,base_ledger,previous_output,previous_ledger,output,ledger):
            if raw is not None: atomic_write(root, HISTORY + '/' + sha(raw) + '.json', raw, immutable=True)
        evidence = None
        if scope_changed(base, output):
            record = scope_record(base, output, policy, inputs, base_ledger, ledger)
            raw = (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode()
            for value in [raw, *[v for v in inputs.values() if v is not None]]:
                atomic_write(root, HISTORY + '/' + sha(value) + '.json', value, immutable=True)
            evidence = sha(raw)
        path = safe_path(root, MANIFEST)
        original = path.read_bytes() if path.exists() else None
        manifest = json.loads(original) if original else {'schema_version':1,'deletions':[]}
        if manifest.get('schema_version') != 1 or not isinstance(manifest.get('deletions'),list):
            raise ValueError('shortlist_publication_manifest_invalid')
        result = deepcopy(manifest)
        result['deletions'] = [r for r in result['deletions'] if not (r.get('path') == OUTPUT and r.get('policy_ref') == POLICY_REF)]
        if ids or evidence:
            result['deletions'].append({'path':OUTPUT,'base_sha256':sha(base),'replacement_sha256':sha(output),
                'ids':ids,'policy_ref':POLICY_REF,'delete_file':False,
                'reason':'Latest shortlist observation diagnostics replaced; exact bytes, source captures and reservation history retained.'})
            if evidence:
                result['deletions'][-1]['scope_evidence_sha256'] = evidence
            proof = load_scope_evidence(root, base, output, policy, result) if evidence else None
            if not deletion_authorized(OUTPUT,base,ids,result,replacement=output, observer_evidence=proof, observer_policy=policy):
                raise ValueError('shortlist_replacement_not_bound')
        if safe_path(root, OUTPUT).read_bytes() != output or safe_path(root, LEDGER).read_bytes() != ledger or exact_head(root, OUTPUT) != base or exact_head(root, LEDGER) != base_ledger:
            raise ValueError('shortlist_concurrent_publication_changed')
        if (path.read_bytes() if path.exists() else None) != original:
            raise ValueError('shortlist_concurrent_manifest_changed')
        if inputs is not None and owned_inputs(root) != inputs:
            raise ValueError('shortlist_concurrent_owned_inputs_changed')
        atomic_write(root, MANIFEST, (json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode())
        return {'current_sha256':sha(output),'removed_ids':ids}
    finally:
        os.close(fd); lock.unlink(); sync_dir(lock.parent)
