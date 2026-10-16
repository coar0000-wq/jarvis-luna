"""Owner business decisions for non-public drafts, never safety/FDA clearance."""
import json
from pathlib import Path

PATH = 'data/manual/owner_draft_approvals.json'


def approved(pd_no, root):
    if isinstance(pd_no, bool) or not isinstance(pd_no, (str, int)):
        return False
    product = str(pd_no)
    try:
        doc = json.loads((Path(root) / PATH).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, UnicodeError):
        return False
    if not isinstance(doc, dict):
        return False
    if (type(doc.get('schema_version')) is not int or doc['schema_version'] != 1
            or doc.get('scope') != 'nonpublic_draft_only'
            or doc.get('source') != 'owner_conversation'
            or doc.get('public_sale_authorized') is not False
            or doc.get('safety_evidence_verified') is not False
            or doc.get('fda_approval') is not False):
        return False
    items = doc.get('items')
    row = items.get(product) if isinstance(items, dict) else None
    return (isinstance(row, dict) and row.get('status') == 'OWNER_APPROVED'
            and row.get('decision_type') == 'business_decision'
            and row.get('draft_only') is True)
