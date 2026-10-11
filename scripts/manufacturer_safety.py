#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared offline manufacturer-safety-record check (one definition for every consumer).

The daily Shopify registrar and the listing gate both call `manufacturer_safety_record(pd_no, root)`,
so a product can never be "ready" in one place and "blocked" in the other.

Source of record (same as scripts/build_mocra_readiness.py):
  public   data/manual/mocra_business.json
  private  data/manual/mocra_profile.json      (gitignored; overlays the public file, private wins)
A product is covered only if its pdNo is listed in `safety_substantiation.covered_pd_nos`.

Rules
  * Fail closed: an unreadable or malformed profile means "not covered".
  * Per product: other products' readiness never matters.
  * Deferred plans, label `product_safety_evidence` entries and notes never count as coverage.
  * No private value is ever returned. Only presence flags and a reason code leave this module.
  * No network, no writes, nothing is approved or invented here.
"""
from __future__ import annotations

import json
from pathlib import Path

SAFETY_MISSING = "manufacturer_safety_record_missing"
SOURCE_OF_RECORD = "mocra_business.json + mocra_profile.json (private wins)"


def _read(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None, "absent"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, "unreadable"
    return (value, "present") if isinstance(value, dict) else (None, "unreadable")


ALL_DAISO_SCOPE = "all_daiso_products"


def covers_all_daiso(substantiation) -> bool:
    """사업주 범위 승인(2026-10-11): 다이소 품질관리(D.TQC·ISO 9001·CCM)를 근거로 다이소 상품 전부를 덮는다.

    scope 값과 승인자·승인일이 모두 있어야 한다. 하나라도 비면 예전처럼 pd_no 목록만 본다(fail closed).
    """
    return (isinstance(substantiation, dict) and substantiation.get("scope") == ALL_DAISO_SCOPE
            and bool(str(substantiation.get("verified_by") or "").strip())
            and bool(str(substantiation.get("verified_at") or "").strip()))


def _covered_ids(entries) -> set[str]:
    """Only real identifiers count: non-empty strings and non-bool ints. null/false/empty entries cover nothing."""
    ids = set()
    for entry in entries:
        if isinstance(entry, bool) or entry is None:
            continue
        if isinstance(entry, int):
            ids.add(str(entry))
        elif isinstance(entry, str) and entry.strip():
            ids.add(entry)
    return ids


def manufacturer_safety_record(pd_no, root) -> dict:
    root = Path(root)
    public, public_state = _read(root / "data" / "manual" / "mocra_business.json")
    private, private_state = _read(root / "data" / "manual" / "mocra_profile.json")
    out = {"pd_no": str(pd_no), "covered": False, "reason": None, "source_of_record": SOURCE_OF_RECORD,
           "public_profile": public_state, "private_profile": private_state}
    if public_state != "present" or private_state == "unreadable":
        out["reason"] = f"{SAFETY_MISSING}:profile_unreadable"
        return out
    profile = dict(public)
    profile.update(private or {})
    substantiation = profile.get("safety_substantiation")
    covered = substantiation.get("covered_pd_nos") if isinstance(substantiation, dict) else None
    if not isinstance(covered, list):
        out["reason"] = f"{SAFETY_MISSING}:safety_substantiation_malformed"
        return out
    if covers_all_daiso(substantiation):
        out["covered"] = True
        out["basis"] = f"owner_scope:{ALL_DAISO_SCOPE}"
        return out
    if str(pd_no) not in _covered_ids(covered):
        out["reason"] = f"{SAFETY_MISSING}:pd_no_not_in_safety_substantiation.covered_pd_nos"
        return out
    out["covered"] = True
    return out


def public_view(record: dict) -> dict:
    """What other files may carry: only whether the product is covered and the reason code."""
    return {"covered": record.get("covered") is True, "reason": record.get("reason")}
