"""Pure evidence-bound shopping copy. No I/O, providers, or approval changes.

Optional field_evidence records bind a verified verbatim English quotation to
one product/field and a label/manufacturer source reference. Current gate rows
lack this authority, so directions and warnings remain omitted by default.
"""
from __future__ import annotations

from copy import deepcopy
from html import escape, unescape
import re

_START = '<!-- ai-shopping-copy:start -->'
_END = '<!-- ai-shopping-copy:end -->'


def text_values(value):
    """Visit all nested text values AND keys, including extension fields."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from text_values(key)
            yield from text_values(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from text_values(child)


def banned_expressions(value, terms):
    blob = ' '.join(unescape(text) for text in text_values(value)).casefold()
    return sorted({term for term in terms if term.casefold() in blob})


def _text(value):
    return ' '.join(value.split()) if isinstance(value, str) else ''


def _verified(field, evidence, pd_no):
    record = evidence.get(field) if isinstance(evidence, dict) else None
    if not isinstance(record, dict):
        return ''
    if (not pd_no or record.get('pd_no') != str(pd_no)
            or record.get('field') != field or record.get('verified') is not True
            or record.get('source_type') not in ('product_label', 'manufacturer_document')
            or record.get('language') != 'en'
            or not _text(record.get('source_ref'))
            or _text(record.get('text')) != _text(record.get('source_quote'))):
        return ''
    text = _text(record.get('text'))
    # A language tag cannot turn Korean (including decomposed/entity-encoded
    # Hangul) into verified English. Do not translate the source quotation.
    if re.search(r'[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7ff]', unescape(text)):
        return ''
    if re.search(r'placeholder|\bTODO\b|\bTBD\b', text, re.I):
        return ''
    return text


def build_shopping_copy(name, product_type='', size='', *, pd_no='', field_evidence=None):
    """Caller supplies accepted English display identity and canonical type/size.

    Display identity is not field authority; pd_no still binds source records.

    Target describes shopping preference, not inferred skin suitability. The
    three semantic slots need not contain three claims. Missing slots are empty.
    """
    name, product_type, size = map(_text, (name, product_type, size))
    evidence = field_evidence or {}
    target = ('For shoppers looking for ' + product_type.lower() + '.') if product_type and product_type != 'Cosmetic' else ''
    directions = _verified('directions', evidence, pd_no)
    warnings = _verified('warnings', evidence, pd_no)
    omissions = {}
    if not target:
        omissions['recommendation_target'] = 'No specific canonical product type available.'
    if not directions:
        omissions['usage_scenario'] = 'No verified sourced English directions for this product.'
    if not warnings:
        omissions['not_recommended_conditions'] = 'No verified sourced English warnings for this product.'
    faqs = []
    english_identity = bool(name) and not re.search(
        r'[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7ff]', unescape(name))
    if english_identity:
        faqs.append({'question': 'Which product is listed as ' + name + '?', 'answer': name})
    elif name:
        omissions['faq_identity'] = 'No verified English display identity; no translation invented.'
    if product_type and product_type != 'Cosmetic':
        question = 'What type is ' + name + '?' if english_identity else 'What product type is listed?'
        faqs.append({'question': question, 'answer': product_type})
    if size and re.search(r'[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7ff]', unescape(size)):
        omissions['faq_size'] = 'No admitted English size text; no translation invented.'
    elif size:
        question = 'What size is ' + name + '?' if english_identity else 'What size is listed?'
        faqs.append({'question': question, 'answer': size})
    if directions:
        faqs.append({'question': 'What directions does the source provide?', 'answer': directions})
    if warnings:
        faqs.append({'question': 'What warnings does the source provide?', 'answer': warnings})
    return {'recommendation_target': target, 'usage_scenario': directions,
            'not_recommended_conditions': warnings, 'faq': faqs,
            'omission_reasons': omissions}


def render_shopping_copy(shopping):
    """Render only the p/strong subset admitted by the accuracy reviewer."""
    if not isinstance(shopping, dict):
        return ''
    sections = []
    for key, label in (('recommendation_target', 'Shopping preference:'),
                       ('usage_scenario', 'Usage scenario'),
                       ('not_recommended_conditions', 'Not recommended conditions')):
        value = shopping.get(key)
        if isinstance(value, str) and value:
            sections.append('<p><strong>' + label + '</strong> ' + escape(value) + '</p>')
    faqs = shopping.get('faq')
    if isinstance(faqs, list) and faqs:
        sections.append('<p><strong>Product FAQ</strong></p>')
        for faq in faqs:
            if (isinstance(faq, dict) and isinstance(faq.get('question'), str)
                    and isinstance(faq.get('answer'), str)):
                sections.append('<p><strong>' + escape(faq['question']) + '</strong> '
                                + escape(faq['answer']) + '</p>')
    return ''.join(sections)


def append_shopping_copy(copy, name, product_type='', size='', **authority):
    """Return independent enriched copy with an escaped, idempotent HTML suffix."""
    result = deepcopy(copy)
    html = result.get('description_html') or ''
    # Remove only our exact prior suffix, not human-authored content. Keep
    # compatibility with the former marker format without emitting comments.
    previous = render_shopping_copy(result.get('ai_shopping_copy'))
    if previous and html.endswith(previous):
        html = html[:-len(previous)]
    html = re.sub(re.escape(_START) + r'.*?' + re.escape(_END) + r'$', '', html, flags=re.S)
    shopping = build_shopping_copy(name, product_type, size, **authority)
    result['ai_shopping_copy'] = shopping
    result['description_html'] = html + render_shopping_copy(shopping)
    return result
