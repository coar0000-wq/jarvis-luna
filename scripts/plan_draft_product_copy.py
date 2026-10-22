#!/usr/bin/env python3
"""Offline, exact-ID DRAFT copy planner. No credentials, network or write executor.

Source-image hashes prove which bytes were reviewed, not rights, actual-stock
label verification, INCI accuracy or legal/safety approval. Only exact text
substitutions are permitted; unknown copy is held instead of overwritten.
"""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path

from apply_reviewed_product_gallery import (Hold, require, validate_snapshot,
    read_json, atomic_json, json_bytes, utcnow)

POLICY = Path(__file__).resolve().parents[1] / 'data/manual/draft_copy/verified_fields.json'
ALLOWED = {'1073406': 'gid://shopify/Product/9705391259905',
           '1033789': 'gid://shopify/Product/9705431761153',
           '1076498': 'gid://shopify/Product/9708428820737'}
FLAGS = ('rights_verified', 'physical_label_verified', 'inci_verified', 'safety_approved')
BODY_ONLY_PD = '1076498'
BODY_ONLY_TITLE = '블리스텍스 센시티브 립밤'
BODY_ONLY_BEFORE_SHA = 'c866ef5c3d490032b90375370cb65757ebbfaeaa5606f43fc96049d69cf66913'
BODY_ONLY_AFTER_SHA = 'e4ef775529f657c0558770d7517d0cbb56c09860ffcb3d5803c212c2f5e3614c'
BODY_ONLY_REPLACEMENT = {
    'old': '<strong>Net contents:</strong> 의 스틱형',
    'new': '<strong>Net contents:</strong> Source verification pending.',
}


def sha(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def text_sha(value):
    require(isinstance(value, str), 'description_string_required')
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def allowed_fields(pd_no):
    require(pd_no in ALLOWED, 'product_not_allowlisted')
    return ['descriptionHtml'] if pd_no == BODY_ONLY_PD else ['title', 'descriptionHtml']


def body_only_rule(policy=None):
    policy = read_json(POLICY) if policy is None else policy
    require(policy.get('schema_version') == 1 and
            all(policy.get(k) is False for k in FLAGS), 'review_flags_must_remain_false')
    matches = [p for p in policy['products'] if p.get('pd_no') == BODY_ONLY_PD]
    require(len(matches) == 1, 'policy_product_missing_or_duplicate')
    rule = matches[0]
    require(rule.get('product_id') == ALLOWED[BODY_ONLY_PD] and
            rule.get('mode') == 'exact_body_only_missing_quantity' and
            rule.get('expected_title') == BODY_ONLY_TITLE and
            rule.get('before_body_sha256') == BODY_ONLY_BEFORE_SHA and
            rule.get('after_body_sha256') == BODY_ONLY_AFTER_SHA and
            rule.get('replacements') == [BODY_ONLY_REPLACEMENT], 'body_only_policy_mismatch')
    return rule


def validate_changes(pd_no, changes):
    require(isinstance(changes, dict) and set(changes) <= set(allowed_fields(pd_no)),
            'unapproved_field')
    if pd_no == BODY_ONLY_PD and changes:
        body_only_rule()
        require(text_sha(changes['descriptionHtml']) == BODY_ONLY_AFTER_SHA,
                'body_only_target_hash_mismatch')


def protected(snapshot):
    result = deepcopy(snapshot)
    result.pop('observed_at', None)
    fields = ('descriptionHtml', 'updatedAt')
    if result['product']['id'] != ALLOWED[BODY_ONLY_PD]:
        fields += ('title',)
    for field in fields:
        result['product'].pop(field, None)
    return result


def replacement(body, old, new):
    # Never append a fallback or silently discard an unfamiliar existing section.
    old_count, new_count = body.count(old), body.count(new)
    require((old_count, new_count) in {(1, 0), (0, 1)}, 'copy_missing_duplicate_or_conflicting')
    return body.replace(old, new, 1) if old_count else body


def build_plan(snapshot, pd_no, evidence_root, *, now=None):
    validate_snapshot(snapshot, now=now)
    require(pd_no in ALLOWED, 'product_not_allowlisted')
    policy = read_json(POLICY)
    require(policy['schema_version'] == 1 and all(policy.get(k) is False for k in FLAGS),
            'review_flags_must_remain_false')
    require(snapshot['shop']['id'] == policy['shop_id'] == 'gid://shopify/Shop/82748997889',
            'wrong_shop')
    matches = [p for p in policy['products'] if p['pd_no'] == pd_no]
    require(len(matches) == 1, 'policy_product_missing_or_duplicate')
    rule, product = matches[0], snapshot['product']
    require(product['id'] == rule['product_id'] == ALLOWED[pd_no], 'wrong_product')
    require(product['status'] == 'DRAFT', 'draft_only')
    require([t for t in product['tags'] if t.startswith('daiso-pd-')] == ['daiso-pd-' + pd_no],
            'supplier_identity_mismatch')
    require(sorted((v['id'], v['sku']) for v in product['variants']) ==
            sorted((v['id'], v['sku']) for v in rule['variant_identity']), 'variant_identity_changed')
    if pd_no == BODY_ONLY_PD:
        body_only_rule(policy)
        require(product['title'] == BODY_ONLY_TITLE, 'unreviewed_title')
    else:
        require(product['title'] in {rule['old_title'], rule['title_en']}, 'unreviewed_title')
    body = product.get('descriptionHtml')
    require(isinstance(body, str) and 0 < len(body) <= 100000, 'complete_body_required')
    if pd_no == BODY_ONLY_PD:
        require(text_sha(body) in {BODY_ONLY_BEFORE_SHA, BODY_ONLY_AFTER_SHA},
                'body_only_source_hash_mismatch')
    root = Path(evidence_root).resolve()
    for source in rule['sources']:
        path = root / source['local_file']
        require(path.resolve().is_relative_to(root) and path.is_file() and not path.is_symlink(),
                'source_missing_or_unsafe')
        require(hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256'], 'source_hash_mismatch')
    after_body = body
    for change in rule['replacements']:
        after_body = replacement(after_body, change['old'], change['new'])
    changes = {}
    if pd_no != BODY_ONLY_PD and product['title'] != rule['title_en']:
        changes['title'] = rule['title_en']
    if body != after_body:
        changes['descriptionHtml'] = after_body
    validate_changes(pd_no, changes)
    result = {'schema_version': 1, 'kind': 'draft_copy_offline_plan', 'pd_no': pd_no,
              'product_id': product['id'], 'before': deepcopy(snapshot),
              'changes': changes, 'state': 'review_required' if changes else 'no_op',
              'policy_sha256': sha(policy), 'evidence': deepcopy(rule['sources']),
              'protected_sha256': sha(protected(snapshot)),
              'apply_allowed': False, 'publication_allowed': False, 'upload_allowed': False,
              **dict.fromkeys(FLAGS, False)}
    result['plan_sha256'] = sha(result)
    return result


def validate_body_only_plan(plan):
    """Do not let a caller rehash a broader or unrelated description edit."""
    if plan.get('pd_no') != BODY_ONLY_PD:
        return
    policy = read_json(POLICY)
    body_only_rule(policy)
    product = plan['before']['product']
    require(plan.get('product_id') == product.get('id') == ALLOWED[BODY_ONLY_PD] and
            product.get('status') == 'DRAFT' and product.get('title') == BODY_ONLY_TITLE,
            'body_only_identity_mismatch')
    body = product.get('descriptionHtml')
    require(text_sha(body) in {BODY_ONLY_BEFORE_SHA, BODY_ONLY_AFTER_SHA},
            'body_only_source_hash_mismatch')
    after = replacement(body, **BODY_ONLY_REPLACEMENT)
    require(text_sha(after) == BODY_ONLY_AFTER_SHA, 'body_only_target_hash_mismatch')
    expected = {'descriptionHtml': after} if after != body else {}
    require(plan.get('changes') == expected and plan.get('policy_sha256') == sha(policy) and
            plan.get('protected_sha256') == sha(protected(plan['before'])), 'body_only_plan_mismatch')
    require(all(plan.get(k) is False for k in (*FLAGS, 'apply_allowed', 'publication_allowed', 'upload_allowed')),
            'review_flags_must_remain_false')


def verify_readback(plan, snapshot, *, now=None):
    """Pure checker for a future separately authorized executor's full readback."""
    unsigned = {k: v for k, v in plan.items() if k != 'plan_sha256'}
    require(sha(unsigned) == plan.get('plan_sha256'), 'plan_digest_mismatch')
    validate_changes(plan['pd_no'], plan['changes'])
    validate_body_only_plan(plan)
    validate_snapshot(snapshot, now=now)
    require(protected(snapshot) == protected(plan['before']), 'protected_fields_changed')
    expected = deepcopy(plan['before']['product'])
    expected.update(plan['changes'])
    require(all(snapshot['product'].get(k) == expected[k] for k in ('title', 'descriptionHtml')),
            'copy_readback_mismatch')
    return {'state': 'copy_readback_verified', 'publication_allowed': False,
            'upload_allowed': False, **dict.fromkeys(FLAGS, False)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, help='Complete fresh gallery-schema snapshot plus descriptionHtml')
    parser.add_argument('--pd-no', required=True, choices=sorted(ALLOWED))
    parser.add_argument('--evidence-root', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        plan = build_plan(read_json(args.snapshot), args.pd_no, args.evidence_root)
        atomic_json(args.output, plan)
    except (Hold, KeyError, TypeError, OSError, ValueError) as exc:
        parser.exit(2, 'HELD: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
