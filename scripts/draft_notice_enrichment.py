"""Rotating, in-place DRAFT notice enrichment. No creation or publication APIs."""
import copy
import hashlib
from html import escape
import json
import re


# Explicitly inspected supplier artwork, never a generic brand translator.
TITLE_SCOPE = {
    '1060646': ('gid://shopify/Product/9652410122497', 'THE LAB by BLANC DOUX Clear Hyal Dewy Glow Tinted Cover Cream 40 mL'),
    '1069430': ('gid://shopify/Product/9652673216769', '46cm Body Wash Refreshing Herbal 225 mL'),
    '1069429': ('gid://shopify/Product/9597411655937', '46cm Body Wash Sparkling Citrus 225 mL'),
}


def source_titles(root, registry):
    path = root / 'data/manual/gosi_source_recovery/2026-10-20/source_recovery.json'
    try:
        raw = path.read_bytes()
        doc = json.loads(raw)
    except (OSError, ValueError):
        return {}
    if doc.get('schema_version') != 1 or doc.get('source') != 'assistant_visual_transcription_from_expanded_daiso_detail':
        return {}
    out = {}
    for fact in doc.get('items', []):
        pd = str(fact.get('pd_no', ''))
        if pd not in TITLE_SCOPE:
            continue
        gid, title = TITLE_SCOPE[pd]
        matches = [r for r in registry.get('items', []) if str(r.get('pd_no')) == pd]
        if (len(matches) != 1 or matches[0].get('shopify_id') != gid
                or matches[0].get('name_kr') != fact.get('name') or fact.get('english_title') != title
                or not str(fact.get('source_image', '')).startswith('https://cdn.daisomall.co.kr/file/resize/PD/')):
            continue
        out[pd] = {'title': title, 'shopify_id': gid, 'source_sha256': hashlib.sha256(raw).hexdigest(),
                   'source_path': path.relative_to(root).as_posix(), 'source_image': fact['source_image'],
                   'scope': 'draft_source_name_only_not_safety_or_sale_approval'}
    return out


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def candidates(registry):
    rows = [r for r in registry.get('items', []) if r.get('status', '').upper() in {'DRAFT', 'CREATED_DRAFT'}
            and re.fullmatch(r'[0-9]+', str(r.get('pd_no', '')))
            and re.fullmatch(r'gid://shopify/Product/[0-9]+', str(r.get('shopify_id', '')))]
    cursor = registry.get('notice_enrichment_cursor')
    for i, row in enumerate(rows):
        if row['shopify_id'] == cursor:
            rows = rows[i + 1:] + rows[:i + 1]
            break
    return sorted(rows, key=lambda r: r.get('notice_enrichment', {}).get('state') != 'reserved')


def record_verified(entry, product):
    # Diagnostic refresh only. Owner/safety/pricing/publication holds remain intact.
    entry['title'] = product.get('title', entry.get('title'))
    info = entry.get('notice_collection') or {}
    holds = list(entry.get('draft_reasons') or [])
    if info.get('source_complete'):
        holds = [h for h in holds if not h.startswith('gosi_missing:') and h != 'ingredients_missing' and not h.startswith('inci_unresolved:')]
        holds += info.get('label_reasons') or []
    if (entry.get('notice_enrichment') or {}).get('expected_title'):
        holds = [h for h in holds if h != 'english_title_missing' and not h.startswith('brand_english_unverified:')]
    updated = list(dict.fromkeys(holds))
    if updated != entry.get('draft_reasons', []):
        entry.setdefault('draft_reason_history', []).append({'before': list(entry.get('draft_reasons') or []),
            'after': updated, 'reason': 'fresh_draft_notice_or_title_readback_only'})
    entry['draft_reasons'] = updated


def cleanup_superseded_generated(entry, state, body, title):
    """Replace the exact legacy generated block on initial repair or migration.

    Never parse/rewrite arbitrary HTML or adopt a changed remote body as evidence.
    Only the legacy generated information block and exact source-name intro move.
    """
    pd = str(entry.get('pd_no', ''))
    if pd not in TITLE_SCOPE or (entry.get('shopify_id'), title) != TITLE_SCOPE[pd]:
        return body, None
    section = state.get('section') or ''
    if not state:
        # First repair: caller still performs durable backup and fresh-body/title
        # compare immediately before mutation. Only exact generated fragments go.
        if 'data-jarvis-notice=' in body:
            return body, None
        original = body
    else:
        if (state.get('state') != 'verified' or not section or body.count(section) != 1
                or body.count('data-jarvis-notice=') != 1):
            return body, None
        prior_body = state.get('before_description_html')
        if not isinstance(prior_body, str) or not (
                body == prior_body + section or digest(body) == state.get('after_sha256')):
            return body, None
        original = body.replace(section, '', 1)
    footer = '<p><small>Source: Daiso Mall item ' + pd + '.</small></p>'
    intro = '<p>' + escape(entry.get('name_kr', '')) + " from Daiso Korea's daily beauty picks.</p>"
    if original.count(footer) != 1 or original.count(intro) != 1:
        return body, None
    # This is the exact escaped HTML grammar emitted by build_us_label, not a
    # general <ul> matcher. A second block or manual nested markup fails closed.
    blocks = list(re.finditer(r'<h4>Product information</h4>\s*<ul>\s*(?:<li>\s*<strong>[^<>]+:</strong>\s+[^<>]*</li>\s*)+</ul>', original))
    if len(blocks) != 1 or original.count('<h4>Product information</h4>') != 1:
        return body, None
    old = blocks[0].group()
    new_intro = '<p>' + escape(title) + " from Daiso Korea's daily beauty picks.</p>"
    # Replace exact old substrings in the full body; all remaining bytes survive.
    chunks = body.split(section) if section else [body]
    cleaned_chunks = [chunk.replace(old, '', 1).replace(intro, new_intro, 1) for chunk in chunks]
    cleaned = section.join(cleaned_chunks) if section else cleaned_chunks[0]
    return cleaned, {'version': 1, 'legacy_block_sha256': digest(old),
                     'before_sha256': digest(body), 'after_sha256': digest(cleaned),
                     'intro_before': intro, 'intro_after': new_intro}


def safe_product(product, entry):
    return (isinstance(product, dict) and product.get('id') == entry['shopify_id']
            and product.get('status') == 'DRAFT'
            and {t for t in product.get('tags', []) if t.startswith('daiso-pd-')} == {'daiso-pd-' + str(entry['pd_no'])})


def enrich(shop, registry, collect, label, save, limit=2, pd_nos=None, title_overrides=None):
    out = []
    selected = candidates(registry)
    if pd_nos:
        selected = [r for r in selected if str(r['pd_no']) in pd_nos or (r.get('notice_enrichment') or {}).get('state') == 'reserved']
    for entry in selected[:max(0, min(6, limit))]:
        state = entry.get('notice_enrichment') or {}
        row = {'pd_no': entry['pd_no'], 'shopify_id': entry['shopify_id']}
        try:
            before = shop.read_product(entry['shopify_id'])
            if not safe_product(before, entry):
                row['status'] = 'identity_or_draft_changed'
                out.append(row)
                continue
            body = before.get('descriptionHtml') or ''
            if state.get('state') == 'reserved':
                # Never repeat an uncertain mutation. Readback is the only reconciliation.
                if digest(body) == state['after_sha256'] and (not state.get('expected_title') or before.get('title') == state['expected_title']):
                    state['state'] = 'verified'
                    entry['notice_enrichment'] = state
                    record_verified(entry, before)
                    save(registry)
                    row['status'] = 'reconciled'
                    out.append(row)
                    continue
                row['status'] = 'prior_write_requires_reconciliation'
                row['stop_further_writes'] = True
                out.append(row)
                break
            gosi = collect(entry['pd_no'], allow_ai=False)
            entry['notice_collection'] = {'missing': gosi.get('missing', []), 'source_complete': bool(gosi.get('gosi_ok')), 'evidence': gosi.get('_notice_evidence', {})}
            prepared = label(entry['pd_no'], entry.get('name_kr', ''), gosi)
            # OCR candidates never enter gosi fields. No partial/empty English label is written.
            override = (title_overrides or {}).get(entry['pd_no']) or {}
            title = override.get('title') if override.get('shopify_id') == entry['shopify_id'] else None
            label_ready = bool(gosi.get('gosi_ok') and not [r for r in prepared.get('reasons', [])
                if r != 'us_regulatory_review_functional_or_drug_like'])
            entry['notice_collection']['label_reasons'] = prepared.get('reasons', [])
            if not label_ready and not title:
                row['status'] = 'source_or_label_review_required'
            else:
                section = ('<div data-jarvis-notice="' + entry['pd_no'] + '">' + prepared['html'] + '</div>') if label_ready else state.get('section')
                old = state.get('section')
                if not old and 'data-jarvis-notice=' in body:
                    raise ValueError('unowned_managed_section')
                cleaned, migration = cleanup_superseded_generated(entry, state, body, title) if label_ready else (body, None)
                outside = body.replace(old, '', 1) if old else body
                exact_scope = (entry['pd_no'] in TITLE_SCOPE and
                               (entry['shopify_id'], title) == TITLE_SCOPE[entry['pd_no']])
                if exact_scope and label_ready and '<h4>Product information</h4>' in outside and not migration:
                    # Do not add a second conflicting table if cleanup evidence
                    # is missing or an owner changed the previously verified HTML.
                    row.update(status='legacy_cleanup_review_required', stop_further_writes=True)
                elif not migration and ((section == old and section and body.count(section) == 1) or not label_ready) and (not title or title == before.get('title')):
                    row['status'] = 'unchanged'
                elif old and body.count(old) != 1:
                    row['status'] = 'managed_section_changed_review_required'
                else:
                    after = (cleaned.replace(old, section, 1) if old else cleaned + section) if label_ready else cleaned
                    fresh = shop.read_product(entry['shopify_id'])
                    if not safe_product(fresh, entry) or fresh.get('descriptionHtml', '') != body or fresh.get('title') != before.get('title'):
                        raise ValueError('description_changed')
                    if state:
                        entry.setdefault('notice_enrichment_history', []).append(copy.deepcopy(state))
                    entry['notice_enrichment'] = {'state': 'reserved', 'before_description_html': body, 'before_sha256': digest(body),
                        'after_sha256': digest(after), 'section': section, 'before_title': before.get('title'),
                        'expected_title': title, 'title_provenance': override if title else {},
                        'cleanup_migration': migration}
                    save(registry)  # Durable reservation before any remote write.
                    if title:
                        shop.update_draft_content(entry['shopify_id'], after, title)
                    else:
                        shop.update_description(entry['shopify_id'], after)
                    verified = shop.read_product(entry['shopify_id'])
                    if not safe_product(verified, entry) or verified.get('descriptionHtml') != after or (title and verified.get('title') != title):
                        raise ValueError('write_unverified')
                    entry['notice_enrichment']['state'] = 'verified'
                    record_verified(entry, verified)
                    row['status'] = 'enriched_draft' if label_ready else 'title_enriched_label_review_required'
            registry['notice_enrichment_cursor'] = entry['shopify_id']
            save(registry)
        except Exception as exc:
            row.update(status='notice_enrichment_failed_or_unverified', stop_further_writes=True,
                       error_type=type(exc).__name__)
            # Network/provider messages may contain credentials or private URLs.
            if isinstance(exc, ValueError) and str(exc) in {'unowned_managed_section', 'description_changed', 'write_unverified'}:
                row['error_reason'] = str(exc)
        out.append(row)
        if row.get('stop_further_writes'):
            break
    return out
