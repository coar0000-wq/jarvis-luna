"""Exact shortlist observer history and narrowly bound diagnostic replacement.

Source identities/captures, request reservations and budgets are never exempted.
Only latest-attempt/derived ID lists may move once their exact prior bytes and
capture/attempt histories are retained. No network, bootstrap or clock refresh.
"""
from __future__ import annotations
from copy import deepcopy
import json
import os
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


def validate_transition(base, current, policy):
    before, after = json.loads(base), json.loads(current)
    if after.get('schema_version') != 2 or after.get('scope') != 'active_shopify_shortlist_only' or after.get('operating_catalog_mutated') is not False:
        raise ValueError('shortlist_scope_or_schema_changed')
    if before.get('expected_ids') != after.get('expected_ids'):
        raise ValueError('shortlist_identity_scope_changed_requires_owned_input_reconciliation')
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
    for key in DIAGNOSTICS:
        permitted.extend(removed_identities(left.get(key), right.get(key), contract))
        left.pop(key, None); right.pop(key, None)
    unexpected = removed_identities(left, right, contract)
    if unexpected: raise ValueError('shortlist_non_diagnostic_removal')
    return sorted(set(permitted))


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
        ids = validate_transition(base, output, policy)
        if previous_output is not None: validate_transition(previous_output, output, policy)
        for raw in (base,base_ledger,previous_output,previous_ledger,output,ledger):
            if raw is not None: atomic_write(root, HISTORY + '/' + sha(raw) + '.json', raw, immutable=True)
        path = safe_path(root, MANIFEST)
        original = path.read_bytes() if path.exists() else None
        manifest = json.loads(original) if original else {'schema_version':1,'deletions':[]}
        if manifest.get('schema_version') != 1 or not isinstance(manifest.get('deletions'),list):
            raise ValueError('shortlist_publication_manifest_invalid')
        result = deepcopy(manifest)
        result['deletions'] = [r for r in result['deletions'] if not (r.get('path') == OUTPUT and r.get('policy_ref') == POLICY_REF)]
        if ids:
            result['deletions'].append({'path':OUTPUT,'base_sha256':sha(base),'replacement_sha256':sha(output),
                'ids':ids,'policy_ref':POLICY_REF,'delete_file':False,
                'reason':'Latest shortlist observation diagnostics replaced; exact bytes, source captures and reservation history retained.'})
            if not deletion_authorized(OUTPUT,base,ids,result,replacement=output):
                raise ValueError('shortlist_replacement_not_bound')
        if safe_path(root, OUTPUT).read_bytes() != output or safe_path(root, LEDGER).read_bytes() != ledger or exact_head(root, OUTPUT) != base or exact_head(root, LEDGER) != base_ledger:
            raise ValueError('shortlist_concurrent_publication_changed')
        if (path.read_bytes() if path.exists() else None) != original:
            raise ValueError('shortlist_concurrent_manifest_changed')
        atomic_write(root, MANIFEST, (json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode())
        return {'current_sha256':sha(output),'removed_ids':ids}
    finally:
        os.close(fd); lock.unlink(); sync_dir(lock.parent)
