#!/usr/bin/env python3
"""Offline gallery evidence consistency and additive planning; never an uploader.

Roles/counts alone are not evidence. Exact SKU, original and output bytes, bound
review receipts and current media must agree. This is a recorded consistency
check, not an authentication of a reviewer, copyright opinion or sales approval.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re
from urllib.parse import urlsplit

ROLES = ('representative', 'composition_texture', 'usage', 'product_information', 'cautions')
MANIFEST_DIR = 'data/manual/gallery_review'
MAX_AGE_SECONDS = 30 * 86400
MAX_BYTES = 32 * 1024 * 1024
HASH = re.compile(r'^[0-9a-f]{64}$')
QA_CHECKS = ('face_check', 'claim_check', 'residual_text_check', 'sku_check')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _bytes(root, relative, expected):
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise ValueError('unsafe_evidence_path')
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('unsafe_evidence_path')
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError('evidence_file_missing_or_outside_root')
    size = target.stat().st_size
    if not 0 < size <= MAX_BYTES or not isinstance(expected, str) or not HASH.fullmatch(expected):
        raise ValueError('evidence_bytes_or_hash_invalid')
    raw = target.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('evidence_hash_mismatch')
    return raw


def _receipt(root, ref, pd_no, kind, clock):
    if not isinstance(ref, dict):
        raise ValueError('review_receipt_missing')
    doc = json.loads(_bytes(root, ref.get('file'), ref.get('sha256')))
    if not isinstance(doc, dict) or doc.get('pd_no') != pd_no or doc.get('kind') != kind:
        raise ValueError('review_receipt_scope_mismatch')
    if not isinstance(doc.get('reviewed_at'), str):
        raise ValueError('review_timestamp_missing')
    stamp = datetime.fromisoformat(doc['reviewed_at'].replace('Z', '+00:00'))
    if stamp.tzinfo is None or not 0 <= (clock - stamp).total_seconds() <= MAX_AGE_SECONDS:
        raise ValueError('review_receipt_future_or_stale')
    if not isinstance(doc.get('reviewer'), str) or not doc['reviewer'].strip():
        raise ValueError('reviewer_record_missing')
    return doc


def assess_gallery(pd_no, manifest, root, *, now=None):
    """Evaluate prepared assets, keeping live-gallery completeness separate.

    Requires all five evidence-backed roles, not eleven files. Role receipts
    must bind original/output bytes and QA. Rights/label receipts additionally
    bind actual supporting document bytes. Self-declared success is ignored.
    """
    root = Path(root).resolve()
    pd_no = str(pd_no)
    clock = now or datetime.now(timezone.utc)
    result = {'schema_version': 1, 'pd_no': pd_no, 'status': 'review_required',
              'preparation_complete': False, 'gallery_complete': False,
              'required_roles': list(ROLES), 'covered_roles': [], 'missing_roles': list(ROLES),
              'accepted_assets': [], 'rejected_assets': [], 'reasons': [],
              'rights_review': 'unverified', 'label_review': 'unverified',
              'publication_allowed': False, 'legal_or_safety_approval': False,
              'scope': 'recorded_gallery_evidence_consistency_only'}
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
            or manifest.get('schema_version') != 1 or manifest.get('pd_no') != pd_no
            or not isinstance(manifest.get('assets'), list)
            or not isinstance(clock, datetime) or clock.tzinfo is None):
        result['reasons'] = ['gallery_manifest_missing_or_invalid']
        return result
    refs = manifest.get('review_evidence')
    refs = refs if isinstance(refs, dict) else {}
    seen = set()
    for index, asset in enumerate(manifest['assets']):
        try:
            if not isinstance(asset, dict) or asset.get('pd_no') != pd_no:
                raise ValueError('asset_product_mismatch')
            digest = asset.get('asset_sha256')
            _bytes(root, asset.get('asset_file'), digest)
            _bytes(root, asset.get('source_file'), asset.get('source_sha256'))
            source_url = asset.get('source_url')
            url = urlsplit(source_url if isinstance(source_url, str) else '')
            if url.scheme != 'https' or not url.hostname or url.username or url.password:
                raise ValueError('source_url_missing_or_invalid')
            if digest in seen:
                raise ValueError('duplicate_asset_bytes')
            review = _receipt(root, asset.get('review_receipt'), pd_no, 'gallery_asset_review', clock)
            if (review.get('asset_sha256') != digest or review.get('source_sha256') != asset.get('source_sha256')
                    or review.get('source_url') != source_url):
                raise ValueError('asset_review_binding_mismatch')
            roles = review.get('roles')
            if (not isinstance(roles, list) or not roles or any(r not in ROLES for r in roles)
                    or len(set(roles)) != len(roles)):
                raise ValueError('asset_role_evidence_missing')
            # Per-role rationale/quote is required; labels alone never establish coverage.
            evidence = review.get('role_evidence')
            if not isinstance(evidence, dict) or any(not isinstance(evidence.get(r), str)
                    or not evidence[r].strip() for r in roles):
                raise ValueError('asset_role_evidence_missing')
            qa = review.get('qa')
            if not isinstance(qa, dict) or any(qa.get(k) != 'pass' for k in QA_CHECKS):
                raise ValueError('asset_qa_incomplete')
            seen.add(digest)
            result['accepted_assets'].append({'asset_sha256': digest, 'source_sha256': asset['source_sha256'],
                                              'roles': roles, 'review_sha256': asset['review_receipt']['sha256']})
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            result['rejected_assets'].append({'index': index, 'reason': 'asset_evidence_unverified'})
    covered = {role for asset in result['accepted_assets'] for role in asset['roles']}
    result['covered_roles'] = [r for r in ROLES if r in covered]
    result['missing_roles'] = [r for r in ROLES if r not in covered]
    for kind in ('rights', 'label'):
        try:
            ref = refs.get(kind)
            review = _receipt(root, ref, pd_no, 'gallery_' + kind + '_review', clock)
            if review.get('disposition') != 'confirmed' or set(review.get('asset_sha256s') or []) != seen or not seen:
                raise ValueError('document_review_scope_mismatch')
            if kind == 'label' and review.get('verification_basis') != 'actual_package_label':
                raise ValueError('actual_label_verification_missing')
            if kind == 'rights' and (set(review.get('source_sha256s') or []) !=
                    {a['source_sha256'] for a in result['accepted_assets']}
                    or not {'reproduce', 'adapt', 'store_product_gallery'}.issubset(
                        set(review.get('permission_scope') or []))):
                raise ValueError('source_permission_scope_missing')
            _bytes(root, review.get('evidence_file'), review.get('evidence_sha256'))
            result[kind + '_review'] = 'recorded_bound'
        except (OSError, ValueError, TypeError, KeyError, OverflowError, AttributeError):
            result['reasons'].append(kind + '_review_evidence_missing_or_invalid')
    if result['missing_roles']:
        result['reasons'].append('gallery_roles_incomplete')
    if result['rejected_assets']:
        result['reasons'].append('gallery_assets_require_review')
    result['preparation_complete'] = not result['reasons']
    result['status'] = 'prepared' if result['preparation_complete'] else ('partial' if covered else 'review_required')
    result['evidence_digest'] = _digest({'pd_no': pd_no, 'accepted_assets': result['accepted_assets'],
                                         'document_reviews': {k: refs[k].get('sha256') for k in ('rights', 'label')
                                                             if result[k + '_review'] == 'recorded_bound'},
                                         'status': result['status']})
    return result


def load_manifest(root, pd_no):
    """Only safe product IDs locate private manifests; never read arbitrary paths."""
    if not re.fullmatch(r'[A-Za-z0-9_-]+', str(pd_no)):
        return {}
    path = Path(root) / MANIFEST_DIR / (str(pd_no) + '.json')
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()) or path.stat().st_size > MAX_BYTES:
            return {}
        doc = json.loads(path.read_text(encoding='utf-8-sig'))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def observation_error(entry, observation, *, now=None):
    """Validate a fresh exact DRAFT inventory; unknown existing bytes hold changes."""
    clock = now or datetime.now(timezone.utc)
    try:
        stamp = datetime.fromisoformat(observation.get('observed_at', '').replace('Z', '+00:00'))
        current = stamp.tzinfo is not None and 0 <= (clock - stamp).total_seconds() <= 300
    except (ValueError, TypeError, AttributeError, OverflowError):
        current = False
    if (not isinstance(entry, dict) or not isinstance(observation, dict)
            or not str(entry.get('pd_no') or '') or not isinstance(entry.get('shopify_id'), str)
            or not re.fullmatch(r'gid://shopify/Product/[0-9]+', entry['shopify_id'])
            or observation.get('id') != entry['shopify_id'] or not current
            or observation.get('status') != 'DRAFT' or observation.get('complete') is not True
            or observation.get('pd_no') != str(entry['pd_no'])):
        return 'current_exact_draft_observation_required'
    media = observation.get('media')
    if not isinstance(media, list) or any(not isinstance(m, dict) or not isinstance(m.get('id'), str)
                                        or not m['id'] for m in media):
        return 'current_media_inventory_invalid'
    if (len({m['id'] for m in media}) != len(media) or any(m.get('status') != 'READY'
            or m.get('mediaContentType') != 'IMAGE' or not isinstance(m.get('content_sha256'), str)
            or not HASH.fullmatch(m['content_sha256']) for m in media)):
        return 'existing_media_identity_or_bytes_unverified'
    return None


def same_inventory(entry, first, second, *, now=None):
    if observation_error(entry, first, now=now) or observation_error(entry, second, now=now):
        return False
    def snapshot(obs):
        return sorted((m['id'], m['content_sha256']) for m in obs['media'])
    return snapshot(first) == snapshot(second)


def plan_additions(entry, manifest, root, observation, *, now=None):
    """Recompute evidence and plan only missing assets, never delete or replace.

    Existing bytes must match prepared asset bytes. A transformed CDN image or
    unknown mapping holds the plan; never re-upload it merely to align hashes.
    """
    entry = entry if isinstance(entry, dict) else {}
    pd_no = str(entry.get('pd_no') or '')
    assessment = assess_gallery(pd_no, manifest, root, now=now)
    plan = {'pd_no': pd_no, 'shopify_id': entry.get('shopify_id'),
            'status': 'review_required', 'gallery_complete': False, 'add_asset_sha256s': [],
            'preserve_media_ids': [], 'reasons': [], 'publication_allowed': False,
            'assessment': assessment}
    if isinstance(observation, dict) and isinstance(observation.get('media'), list):
        plan['preserve_media_ids'] = [m['id'] for m in observation['media']
                                     if isinstance(m, dict) and isinstance(m.get('id'), str) and m['id']]
    error = observation_error(entry, observation, now=now)
    if error:
        plan['reasons'] = [error]
        return plan
    if not assessment['preparation_complete']:
        plan['reasons'] = ['gallery_preparation_requires_review']
        return plan
    existing = {m['content_sha256'] for m in observation['media']}
    desired = {a['asset_sha256'] for a in assessment['accepted_assets']}
    if not desired or not existing.issubset(desired):
        plan['reasons'] = ['existing_media_asset_binding_unverified']
        return plan
    plan['add_asset_sha256s'] = sorted(desired - existing)
    plan['gallery_complete'] = not plan['add_asset_sha256s']
    plan['status'] = 'complete' if plan['gallery_complete'] else 'additions_prepared'
    return plan


def prepared_payloads(pd_no, manifest, root, hashes, *, now=None):
    """Read exact reviewed bytes; generation/conversion cannot silently replace them."""
    if not assess_gallery(pd_no, manifest, root, now=now)['preparation_complete']:
        raise ValueError('gallery_preparation_requires_review')
    assets = {a['asset_sha256']: a for a in manifest['assets']}
    if not hashes or any(h not in assets for h in hashes):
        raise ValueError('gallery_payload_missing')
    return [(h, _bytes(Path(root).resolve(), assets[h]['asset_file'], h)) for h in hashes]
