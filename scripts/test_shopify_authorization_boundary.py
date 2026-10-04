#!/usr/bin/env python3
"""Offline authorization boundary tests. Synthetic data only."""
import copy
import csv
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_signature as gs
import build_shopify_action_queue as q
import export_shopify_operational as exp
import validate_commerce_architecture as val


def write(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value), encoding='utf-8')


def blocked(fn):
    try:
        fn()
    except (RuntimeError, AssertionError):
        return
    raise AssertionError('unsafe input accepted')


with tempfile.TemporaryDirectory() as td:
    d = Path(td) / 'data'; d.mkdir()
    gs.DATA = q.D = exp.D = d
    q.OUT = d / 'shopify_action_queue.json'
    q.APPROVALS = d / 'manual/shopify_action_approvals.json'
    exp.OUT = d / 'shopify_exports'
    for name, rel in {'PRODUCT_MASTER': 'product_master.json', 'GOSI': 'gosi.json',
        'LABELS': 'daiso_real/daiso_us_labels.json', 'PRICING': 'pricing_model.json',
        'LEGAL': 'legal_products.json', 'RECOMMENDATIONS': 'daiso_real/shopify_s_recommendations.json',
        'GATE': 'listing_gate.json'}.items():
        setattr(gs, name, d / rel)
    write(gs.RECOMMENDATIONS, {'recommendations': [{'pd_no': '1', 'grade': 'S'}]})
    write(gs.PRODUCT_MASTER, {'pd_no_to_cp': {'1': 'CP-1'}, 'products': [{'pd_no': '1',
        'canonical_product_id': 'CP-1', 'variant': {'group_id': 'VG-1'}}], 'variant_groups': []})
    write(d / 'shopify_shortlist.json', {'status': 'proposed', 'active_pd_nos': ['1']})
    for rel in ['shopify_listing_copy.json', 'legal_full.json', 'mocra_readiness.json']:
        write(d / rel, {'generated_at': 'clock', 'items': {'1': {'evidence': 'original'}}})
    gate = {'items': [{'pd_no': '1', 'ready': True, 'copy': {'title': 'Draft'}}],
            'agent_input_signature': gs.agent_input_signature(gs.current_recommendations())}
    write(gs.GATE, gate)
    assert not gs.stale_reason(gate)
    for rel in ['shopify_listing_copy.json', 'mocra_readiness.json', 'legal_full.json',
                'product_master.json', 'shopify_shortlist.json']:
        p = d / rel; original = json.loads(p.read_text(encoding="utf-8"))
        changed = copy.deepcopy(original); changed['policy_or_evidence'] = 'changed'
        write(p, changed); assert rel in gs.stale_reason(gate)
        write(p, original)
    p = d / 'shopify_listing_copy.json'; original = json.loads(p.read_text(encoding="utf-8"))
    changed = copy.deepcopy(original); changed['generated_at'] = 'new-clock'
    write(p, changed); assert not gs.stale_reason(gate)
    changed['captured_at'] = 'actual-source-capture'
    write(p, changed); assert gs.stale_reason(gate)
    exp.OUT.mkdir(); (exp.OUT / 'products.csv').write_text('do-not-overwrite')
    before = {p.relative_to(d).as_posix(): p.read_bytes() for p in d.rglob('*') if p.is_file()}
    blocked(exp.main)
    after = {p.relative_to(d).as_posix(): p.read_bytes() for p in d.rglob('*') if p.is_file()}
    assert before == after
    write(d / 'shopify_listing_copy.json', original)
    product = {'Canonical Product ID': 'CP-1', 'Handle': 'draft', 'Status': 'draft',
               'Published': 'FALSE', 'Variant Inventory Qty': '0', 'Variant Inventory Policy': 'deny'}
    inv = {'Canonical Product ID': 'CP-1', 'Available': '0', 'Inventory Policy': 'deny'}
    for name, rows in [('products.csv', [product]), ('inventory.csv', [inv]),
                       ('images.csv', []), ('collections.csv', [])]:
        with (exp.OUT / name).open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['Handle'])
            w.writeheader(); w.writerows(rows)
    assert q.main() == 0
    action = json.loads(q.OUT.read_text(encoding="utf-8"))['draft_actions'][0]
    assert action['target_configuration'] == 'unconfigured_blocked'
    write(q.APPROVALS, {'drafts': {'CP-1': {'approved': True,
          'approved_payload_hash': action['payload_hash'], 'approved_by': 'Synthetic Approver',
          'approved_at': 'synthetic-time'}}})
    assert q.main() == 0
    action = json.loads(q.OUT.read_text(encoding="utf-8"))['draft_actions'][0]
    assert action['authorization']['planning_acknowledged'] is True
    assert not q.approval_valid({'approved': True}, action['payload_hash'])
    assert 'Synthetic Approver' not in q.OUT.read_text(encoding="utf-8")
    expected = copy.deepcopy(action['immutablePayload'])
    val.validate_action_boundary(action, expected)
    for key, value in [('target_shop', 'other-shop'), ('remote_preconditions', {'version': 'wrong'}),
                       ('api_version', 'wrong'), ('operation', 'PUBLISH')]:
        forged = copy.deepcopy(action); forged['immutablePayload']['context'][key] = value
        forged['payload_hash'] = q.digest(forged['immutablePayload'])
        blocked(lambda: val.validate_action_boundary(forged, expected))
    for mutation in [{'state': 'READY_TO_EXECUTE'}, {'authenticated_authorization': True},
                     {'execution': {'enabled': True}}, {'approved_by': 'Synthetic Approver'}]:
        forged = copy.deepcopy(action); forged.update(mutation)
        blocked(lambda: val.validate_action_boundary(forged, expected))
print('SHOPIFY_AUTHORIZATION_BOUNDARY_OK')
