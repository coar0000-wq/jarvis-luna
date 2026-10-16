"""Owner business decisions for non-public drafts, never safety/FDA clearance."""
import json
from pathlib import Path

PATH = 'data/manual/owner_draft_approvals.json'
BODY_CATEGORY_CODE = 'CTGR_01113'
BODY_SOURCE_URL = 'https://www.daisomall.co.kr/ds/exhCtgr/C208/CTGR_01050/CTGR_01061/CTGR_01113'


def _document(root):
    try:
        doc = json.loads((Path(root) / PATH).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, UnicodeError):
        return None
    if not isinstance(doc, dict):
        return None
    if (type(doc.get('schema_version')) is not int or doc['schema_version'] != 1
            or doc.get('scope') != 'nonpublic_draft_only'
            or doc.get('source') != 'owner_conversation'
            or doc.get('public_sale_authorized') is not False
            or doc.get('safety_evidence_verified') is not False
            or doc.get('fda_approval') is not False):
        return None
    return doc


def approved(pd_no, root):
    if isinstance(pd_no, bool) or not isinstance(pd_no, (str, int)):
        return False
    product = str(pd_no)
    doc = _document(root)
    if doc is None:
        return False
    items = doc.get('items')
    row = items.get(product) if isinstance(items, dict) else None
    return (isinstance(row, dict) and row.get('status') == 'OWNER_APPROVED'
            and row.get('decision_type') == 'business_decision'
            and row.get('draft_only') is True)


def category_approved(category_code, source_url, root):
    """Exact shower/bath draft exception, not blanket product/safety approval."""
    if category_code != BODY_CATEGORY_CODE or source_url != BODY_SOURCE_URL:
        return False
    doc = _document(root)
    if doc is None:
        return False
    scopes = doc.get('category_scopes')
    if (not isinstance(scopes, list) or len(scopes) > 1000
            or any(not isinstance(row, dict) for row in scopes)):
        return False
    matches = [row for row in scopes
               if row.get('category_code') == category_code or row.get('source_url') == source_url]
    if len(matches) != 1:
        return False
    row = matches[0]
    return (row.get('category') == 'body'
            and row.get('category_code') == BODY_CATEGORY_CODE
            and row.get('source_url') == BODY_SOURCE_URL
            and row.get('status') == 'OWNER_APPROVED'
            and row.get('decision_type') == 'business_decision'
            and row.get('draft_only') is True
            and row.get('selection_condition') == 'no_eligible_canonical_s'
            and type(row.get('daily_limit')) is int and row['daily_limit'] == 1
            and row.get('ordering') == 'source_category_list_order'
            and row.get('promote_to_s') is False
            and row.get('public_sale_authorized') is False
            and row.get('safety_evidence_verified') is False
            and row.get('fda_approval') is False)
