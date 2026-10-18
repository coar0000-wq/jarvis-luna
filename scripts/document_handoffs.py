"""Bounded document handoffs; file integrity is not execution or approval evidence."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'data/manual/document_adoption.json'
RECIPIENTS = {'sourcing', 'institutions', 'market', 'listing', 'pricing', 'legal',
              'robotics', 'design', 'channels', 'knowledge', 'graph', 'rea'}


def packets(root=ROOT):
    root = Path(root).resolve()
    manifest = root / MANIFEST
    if not manifest.exists():
        return []
    doc = json.loads(manifest.read_text(encoding='utf-8'))
    if not doc.get('sources') or set(doc.get('recipients', {})) - RECIPIENTS:
        raise ValueError('missing sources or unknown recipients')
    reviewed_at = doc.get('reviewed_at')
    try:
        if date.fromisoformat(reviewed_at).isoformat() != reviewed_at:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError('document review date must be YYYY-MM-DD') from exc
    evidence = []
    allowed = (root / 'docs/learning/materials').resolve()
    for source in doc['sources']:
        path = (root / source['path']).resolve()
        if not path.is_relative_to(allowed) or not path.is_file():
            raise ValueError('document source outside archived materials or missing')
        raw = path.read_bytes()
        if len(raw) > 1_000_000 or hashlib.sha256(raw).hexdigest() != source['sha256']:
            raise ValueError('document source size/hash mismatch')
        evidence.append({'path': source['path'], 'sha256': source['sha256']})
    out = []
    for recipient, action in doc['recipients'].items():
        if len(action) > 1600:
            raise ValueError('handoff summary too long')
        out.append({'id': doc['id'] + ':' + recipient, 'recipient': recipient,
                    'date': reviewed_at, 'title': doc['title'],
                    'summary': action, 'url': doc['review_path'],
                    'status': 'shared_to_repository_not_acknowledged',
                    'verification': {'kind': 'local_document_integrity_only', 'sources': evidence},
                    'authority': False, 'execution_verified': False,
                    'next_step': 'Review assigned summary and return evidence-linked findings; use existing execution gates.'})
    return out


def feed_rows(root=ROOT):
    return [{'title': p['title'], 'url': p['url'], 'date': p['date'],
             'pool': 'document_handoff', 'teams': [p['recipient']],
             'summary': p['summary'], 'text': p['summary'], 'status': p['status'],
             'evidence': p['verification'], 'date_basis': 'document_review_date'}
            for p in packets(root) if p['recipient'] != 'rea']


def write_specialist_handoff(root=ROOT):
    root = Path(root)
    selected = [p for p in packets(root) if p['recipient'] == 'rea']
    target = root / 'data/agents/rea_document_handoff.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'specialist': 'rea', 'parent_teams': ['robotics', 'knowledge'],
                                 'packets': selected, 'receipt_scope': 'repository_delivery_only'},
                                ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    write_specialist_handoff()
    print(f'{len(packets())} document handoffs validated; no engine execution or approval claimed')
