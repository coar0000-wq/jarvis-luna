#!/usr/bin/env python3
"""Offline, non-authoritative product/copy evidence checks.

A source registry binds an exact retailer product to an official product URL and
ID. A separately recorded capture must match that binding, its bytes, and clock.
This verifies recorded evidence consistency, not website ownership, clinical
truth, legal clearance, or permission to publish. Missing/invalid evidence keeps
an honest neutral draft available. No network, model, approval, or writes here.
"""
from __future__ import annotations

import copy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

REGISTRY = "data/manual/product_accuracy_sources.json"
EVIDENCE = "data/manual/product_accuracy_evidence.private.json"
CAPTURE_DIR = "data/manual/product_accuracy"
MAX_AGE_SECONDS = 30 * 86400
MAX_BYTES = 2 * 1024 * 1024
HOLD_REASON = "product_accuracy_owner_review_required"
FIELDS = ("title", "description_html", "seo_title", "seo_description", "tags", "product_type")
FACT_FIELDS = ("brand", "product_name", "net_contents", "product_type", "ingredients", "directions", "warnings")


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _normal(value):
    return " ".join(value.split()) if isinstance(value, str) else ""


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _copy_digest(value):
    try:
        return _digest(value)
    except (TypeError, ValueError, OverflowError):
        return None


def identity(product):
    """Do not merge different retailer IDs, editions, shades, or source names."""
    pd_no = product.get("pd_no", product.get("pdNo"))
    name = product.get("name", product.get("pdNm"))
    return {"pd_no": str(pd_no) if isinstance(pd_no, (str, int)) and not isinstance(pd_no, bool) else "",
            "retailer_name": _normal(name)}


def _read(path):
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("evidence_too_large")
    raw = path.read_bytes()
    doc = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(doc, dict):
        raise ValueError("invalid_evidence_document")
    return raw, doc


def _entry(doc, pd_no):
    if type(doc.get("schema_version")) is not int or doc["schema_version"] != 1:
        raise ValueError("invalid_evidence_schema")
    rows = doc.get("products")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("invalid_evidence_products")
    rows = [row for row in rows if row.get("pd_no") == pd_no]
    if len(rows) != 1:
        raise ValueError("product_evidence_missing_or_duplicate")
    return rows[0]


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("invalid_capture_time")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("capture_time_requires_timezone")
    return stamp.astimezone(timezone.utc)


def source_evidence(product, root, *, now=None):
    """Return only exact source-bound statements; fail closed on all bad inputs.

    Source documents are inert data. Their own 'verified', 'approved', or
    'official' flags confer no authority. Fixed policy freshness cannot be
    extended by a record. The report exposes no private capture path/content.
    """
    result = {"status": "UNVERIFIED", "reasons": [], "facts": {}, "statements": []}
    root = Path(root).resolve()
    current = identity(product)
    if not current["pd_no"] or not current["retailer_name"]:
        result["reasons"] = ["product_identity_missing"]
        return result
    try:
        if not (root / REGISTRY).is_file() or not (root / EVIDENCE).is_file():
            raise ValueError("official_product_evidence_missing")
        for relative in (REGISTRY, EVIDENCE):
            if not (root / relative).resolve().is_relative_to(root / "data/manual"):
                raise ValueError("invalid_capture_path")
        _, registry = _read(root / REGISTRY)
        _, ledger = _read(root / EVIDENCE)
        binding, record = _entry(registry, current["pd_no"]), _entry(ledger, current["pd_no"])
        if binding.get("retailer_name") != current["retailer_name"]:
            raise ValueError("retailer_product_identity_changed")
        url, official_id = binding.get("official_url"), binding.get("official_product_id")
        parsed = urlsplit(url if isinstance(url, str) else "")
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or not parsed.path.strip("/") or not _text(official_id)):
            raise ValueError("invalid_official_product_binding")
        for key in ("pd_no", "retailer_name", "official_url", "official_product_id"):
            if record.get(key) != binding.get(key):
                raise ValueError("official_product_binding_mismatch")
        filename = record.get("capture_file")
        if not isinstance(filename, str) or "\\" in filename or ":" in filename:
            raise ValueError("invalid_capture_path")
        relative = Path(filename)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("invalid_capture_path")
        target = (root / relative).resolve()
        if not target.is_relative_to(root / CAPTURE_DIR) or not target.is_relative_to(root):
            raise ValueError("invalid_capture_path")
        raw, captured = _read(target)
        actual = hashlib.sha256(raw).hexdigest()
        if record.get("capture_sha256") != actual:
            raise ValueError("capture_hash_mismatch")
        if captured.get("source_url") != url or captured.get("official_product_id") != official_id:
            raise ValueError("capture_product_identity_mismatch")
        stamp = _timestamp(captured.get("captured_at"))
        clock = now or datetime.now(timezone.utc)
        if clock.tzinfo is None:
            raise ValueError("review_time_requires_timezone")
        age = (clock - stamp).total_seconds()
        if age < 0 or age > MAX_AGE_SECONDS:
            raise ValueError("capture_future_or_stale")
        content = captured.get("text")
        if not _text(content):
            raise ValueError("capture_content_missing")
        # Whole recorded lines, not loose substring matches: 'organic' must not
        # be extracted from 'not organic', nor a percentage from another claim.
        lines = {_normal(line) for line in content.splitlines() if _normal(line)}
        facts = record.get("facts")
        statements = record.get("statements", [])
        if (not isinstance(facts, dict) or not facts or set(facts) - set(FACT_FIELDS)
                or not isinstance(statements, list)):
            raise ValueError("invalid_fact_evidence")
        selected = {}
        for field, item in facts.items():
            if (not isinstance(item, dict) or not _text(item.get("value"))
                    or item.get("value") != item.get("quote") or _normal(item["quote"]) not in lines):
                raise ValueError("fact_not_an_exact_source_quote")
            selected[field] = _normal(item["value"])
        if any(not _text(text) or _normal(text) not in lines for text in statements):
            raise ValueError("statement_not_an_exact_source_quote")
        if not selected.get("product_name"):
            raise ValueError("official_product_name_missing")
        result.update(status="RECORDED_SOURCE_BOUND", facts=selected,
                      statements=[_normal(text) for text in statements],
                      evidence_digest=_digest({"binding": binding, "record": record, "capture_sha256": actual}),
                      captured_at=stamp.isoformat())
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError) as exc:
        # Fixed reasons only: never leak a private filename or arbitrary content.
        allowed = {"official_product_evidence_missing", "invalid_evidence_schema", "invalid_evidence_products",
                   "product_evidence_missing_or_duplicate", "retailer_product_identity_changed",
                   "invalid_official_product_binding", "official_product_binding_mismatch", "invalid_capture_path",
                   "capture_hash_mismatch", "capture_product_identity_mismatch", "capture_time_requires_timezone",
                   "review_time_requires_timezone", "capture_future_or_stale", "capture_content_missing",
                   "invalid_fact_evidence", "fact_not_an_exact_source_quote", "statement_not_an_exact_source_quote",
                   "official_product_name_missing", "evidence_too_large", "invalid_evidence_document", "invalid_capture_time"}
        result["reasons"] = [str(exc) if str(exc) in allowed else "product_evidence_unreadable"]
    return result


class _Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.current, self.invalid = [], [], False

    def flush(self):
        value = _normal("".join(self.current))
        if value:
            self.parts.append(value)
        self.current = []

    def handle_starttag(self, tag, attrs):
        if tag not in ("p", "br", "strong", "em") or attrs:
            self.invalid = True
        if tag in ("p", "br"):
            self.flush()

    def handle_endtag(self, tag):
        if tag not in ("p", "br", "strong", "em"):
            self.invalid = True
        if tag in ("p", "br"):
            self.flush()

    def handle_data(self, data):
        self.current.append(data)

    def handle_comment(self, data):
        self.invalid = True

    def handle_decl(self, decl):
        self.invalid = True


def _paragraphs(value):
    parser = _Paragraphs()
    parser.feed(value)
    parser.close()
    parser.flush()
    return parser.parts, parser.invalid


def review_copy(product, candidate, fallback, root, *, now=None):
    """Conservative exact-support screen, not a semantic truth/approval model.

    Free paraphrases are intentionally held. They can use the deterministic
    neutral draft until someone supplies the correct product-bound evidence.
    Recompute each time; saved review JSON is never a reusable approval token.
    """
    source = source_evidence(product, root, now=now)
    unsupported, discrepancies = [], []
    facts = source["facts"]
    for key, source_key in (("brand_english", "brand"), ("net_contents", "net_contents")):
        if _text(product.get(key)) and source_key in facts:
            normal = lambda value: re.sub(r"\s+", "", value).casefold()
            if normal(product[key]) != normal(facts[source_key]):
                discrepancies.append(source_key)
    if not isinstance(candidate, dict) or not isinstance(fallback, dict):
        unsupported = ["copy_schema"]
    else:
        titles = {facts[key] for key in ("product_name", "brand", "net_contents", "product_type") if key in facts}
        if facts.get("product_name") and facts.get("net_contents"):
            titles.add(facts["product_name"] + " " + facts["net_contents"])
        if facts.get("brand") and facts.get("product_name"):
            titles.add(facts["brand"] + " " + facts["product_name"])
        for field in FIELDS:
            if field not in candidate:
                if field in ("title", "description_html") or field in fallback:
                    unsupported.append(field)
                continue
            value, neutral = candidate[field], fallback.get(field)
            if field == "tags":
                allowed = set(neutral or []) | {re.sub(r"[^a-z0-9]+", "-", t.casefold()).strip("-") for t in titles}
                if not isinstance(value, list) or any(not _text(t) or t not in allowed for t in value):
                    unsupported.append(field)
                continue
            if not _text(value):
                unsupported.append(field)
                continue
            if field == "description_html":
                parts, invalid = _paragraphs(value)
                safe_parts, _ = _paragraphs(neutral or "")
                if invalid or not parts or any(p not in set(safe_parts + source["statements"]) for p in parts):
                    unsupported.append(field)
            elif field == "seo_description":
                if _normal(value) not in {_normal(neutral), *source["statements"]}:
                    unsupported.append(field)
            elif _normal(value) not in {_normal(neutral), *titles}:
                unsupported.append(field)
    copy_digest = _copy_digest(candidate)
    if copy_digest is None:
        unsupported.append("copy_schema")
    supported = source["status"] == "RECORDED_SOURCE_BOUND" and not unsupported and not discrepancies
    report = {"schema_version": 1, "product_id": identity(product)["pd_no"],
              "source_identity_sha256": _digest(identity(product)), "copy_sha256": copy_digest,
              "status": "SOURCE_BOUND_DRAFT_REVIEW_REQUIRED" if supported else "UNVERIFIED_DRAFT",
              "evidence_status": source["status"], "unsupported_fields": sorted(set(unsupported)),
              "source_conflicts": sorted(discrepancies), "reasons": source["reasons"],
              "human_review_required": True, "publication_allowed": False,
              "safety_approval": False, "overall_legal_clearance": False,
              "scope": "recorded_source_consistency_and_exact_copy_support_only"}
    if source.get("evidence_digest"):
        report["evidence_digest"] = source["evidence_digest"]
    return report


def select_copy(product, candidate, fallback, root, *, now=None):
    """Unsupported model text is replaced, never promoted by a 'verified' flag."""
    report = review_copy(product, candidate, fallback, root, now=now)
    replace = bool(report["unsupported_fields"] or report["source_conflicts"])
    selected = fallback if replace else candidate
    report["fallback_used"] = replace
    report["selected_copy_sha256"] = _digest(selected)
    return copy.deepcopy(selected), report
