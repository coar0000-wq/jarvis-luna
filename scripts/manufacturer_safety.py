#!/usr/bin/env python3
"""Verify recorded local evidence bindings, never create approvals or certifications.

Private schema_version=1 ledger records[] overrides profile evidence_records.
Each record binds real dossier+adequacy files, exact pd_nos/formula scope, and a
qualified manual review. Lists/status/notes/future promises do not prove possession.
No network/writes. Only fixed reasons/states and opaque evidence digests leave here.
"""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

SAFETY_MISSING = "manufacturer_safety_record_missing"
SOURCE_OF_RECORD = "private safety evidence ledger or mocra profile evidence records"
DOCUMENT_TYPES = {"manufacturer_safety_assessment", "qualified_safety_dossier", "safety_substantiation_dossier"}


def _read(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None, "absent"
    except (OSError, UnicodeDecodeError, ValueError):
        return None, "unreadable"
    return (value, "present") if isinstance(value, dict) else (None, "unreadable")


def _id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return str(value)
    if isinstance(value, str) and value and value == value.strip():
        return value
    return None


def _covered_ids(entries):
    return {v for item in entries if (v := _id(item)) is not None}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _scope(value):
    if not isinstance(value, dict) or value.get("scope_type") != "exact_product_formula":
        return None
    ids = value.get("pd_nos")
    if not isinstance(ids, list) or not ids or any(_id(x) is None for x in ids):
        return None
    if not _text(value.get("formula_id")):
        return None
    return sorted(_covered_ids(ids)), value["formula_id"]


def _hash_file(root, filename, expected):
    if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        return "file_binding_invalid", None
    if not isinstance(filename, str) or "\\" in filename or ":" in filename:
        return "file_binding_invalid", None
    rel = Path(filename)
    if rel.is_absolute() or ".." in rel.parts or rel.parts[:2] != ("data", "manual"):
        return "file_binding_invalid", None
    try:
        target = (root / rel).resolve()
        target.relative_to((root / "data/manual").resolve())
        target.relative_to(root.resolve())
        if not target.is_file():
            return "file_missing", None
        size = target.stat().st_size
        if size <= 0 or size > 32 * 1024 * 1024:
            return "file_binding_invalid", None
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
    except (OSError, ValueError, RuntimeError):
        return "file_missing", None
    return (None if actual == expected else "file_hash_mismatch"), actual


def _review_date(value):
    if not isinstance(value, str):
        return False
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return date <= datetime.now(timezone.utc)
    except (ValueError, OverflowError):
        return False


def _check(record, pd_no, root):
    if not isinstance(record, dict):
        return "evidence_record_malformed", {"state": "malformed"}
    scope = _scope(record.get("scope"))
    if scope is None or pd_no not in scope[0]:
        return "evidence_scope_mismatch", {"state": "scope_mismatch"}
    binding = {"scope": scope, "document_type": record.get("document_type")}
    # Use membership tuple: malformed lists/dicts must fail closed, never throw.
    if record.get("document_type") not in tuple(DOCUMENT_TYPES):
        return "dossier_type_invalid", {"state": "dossier_type_invalid"}
    error, actual = _hash_file(root, record.get("file"), record.get("sha256"))
    binding.update(document_sha256=record.get("sha256"), actual_document_sha256=actual)
    if error:
        return error, binding
    review = record.get("manual_review")
    if not isinstance(review, dict):
        return "manual_adequacy_review_missing", binding
    review_scope = _scope(review.get("scope"))
    fields = ("method", "disposition", "reviewer_qualified", "reviewed_at", "document_sha256", "adequacy_type", "adequacy_sha256")
    binding["review"] = {key: review.get(key) for key in fields}
    binding["review"]["scope"] = review_scope
    binding["review"]["reviewer_present"] = _text(review.get("reviewed_by"))
    if (review.get("method") != "manual" or review.get("disposition") != "adequate"
            or review.get("reviewer_qualified") is not True or not _text(review.get("reviewed_by"))
            or not _review_date(review.get("reviewed_at"))
            or review.get("adequacy_type") != "product_safety_substantiation"
            or review.get("document_sha256") != actual or review_scope != scope):
        return "manual_adequacy_review_invalid", binding
    error, review_actual = _hash_file(root, review.get("adequacy_file"), review.get("adequacy_sha256"))
    binding["review"]["actual_adequacy_sha256"] = review_actual
    if error:
        return "adequacy_" + error, binding
    # A qualified assessment may contain both dossier and adequacy review;
    # no separate signed report or duplicated review document is mandatory.
    return None, binding


def manufacturer_safety_record(pd_no, root) -> dict:
    root = Path(root)
    public, public_state = _read(root / "data/manual/mocra_business.json")
    private, private_state = _read(root / "data/manual/mocra_profile.json")
    ledger, ledger_state = _read(root / "data/manual/manufacturer_safety_evidence.private.json")
    product = _id(pd_no)
    out = {"pd_no": product if product is not None else "", "covered": False, "reason": None,
           "source_of_record": SOURCE_OF_RECORD, "public_profile": public_state,
           "private_profile": private_state, "evidence_ledger": ledger_state}
    def fail(reason):
        out["reason"] = SAFETY_MISSING + ":" + reason
        return out
    if product is None:
        return fail("pd_no_invalid")
    if public_state != "present" or private_state == "unreadable":
        return fail("profile_unreadable")
    if ledger_state == "unreadable":
        return fail("evidence_ledger_unreadable")
    profile = dict(public)
    profile.update(private or {})
    substantiation = profile.get("safety_substantiation")
    if ledger_state == "present":
        if type(ledger.get("schema_version")) is not int or ledger["schema_version"] != 1:
            return fail("evidence_ledger_malformed")
        records = ledger.get("records")
    else:
        if not isinstance(substantiation, dict) or not isinstance(substantiation.get("covered_pd_nos"), list):
            return fail("safety_substantiation_malformed")
        records = substantiation.get("evidence_records", [])
    if not isinstance(records, list):
        return fail("evidence_records_malformed")
    checks = [_check(record, product, root) for record in records]
    if checks:
        out["evidence_digest"] = hashlib.sha256(json.dumps(
            [binding for _, binding in checks], sort_keys=True, ensure_ascii=False,
            separators=(",", ":")).encode("utf-8")).hexdigest()
    if any(error is None for error, _ in checks):
        out["covered"] = True
        return out
    errors = [error for error, _ in checks if error != "evidence_scope_mismatch"]
    if errors:
        return fail(errors[0])
    declared = substantiation.get("covered_pd_nos", []) if isinstance(substantiation, dict) else []
    if not records and isinstance(declared, list) and product not in _covered_ids(declared):
        return fail("pd_no_not_in_safety_substantiation.covered_pd_nos")
    return fail("scoped_evidence_missing")


def public_view(record: dict) -> dict:
    out = {"covered": record.get("covered") is True, "reason": record.get("reason")}
    digest = record.get("evidence_digest")
    if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
        out["evidence_digest"] = digest
    return out
