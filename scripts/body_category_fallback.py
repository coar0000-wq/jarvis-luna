"""Bounded offline draft-only fallback. Grants no S, public or safety approval.

Caller retains owner approval, S-first and live detail/price/image/label gates.
Only a fully validated source can replace the single queue key in registry.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

CATEGORY_CODE = "CTGR_01113"
SOURCE_URL = "https://www.daisomall.co.kr/ds/exhCtgr/C208/CTGR_01050/CTGR_01061/CTGR_01113"
SELECTION_SOURCE = "owner_body_shower_category_fallback"
QUEUE_KEY = "body_shower_fallback_queue"
SCHEMA_VERSION = 1
MAX_QUEUE_IDS = 10000
MAX_SOURCE_ROWS = 10000
_SETTLED = {"DRAFT", "ACTIVE", "deleted_by_owner", "deleted_verified", "verified_deleted"}


class _Blocked(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise _Blocked(reason)


def _pd_no(value):
    _require(type(value) in (str, int), "invalid_product_id")
    text = str(value)
    _require(len(text) <= 32 and re.fullmatch(r"[1-9][0-9]*", text), "invalid_product_id")
    return text


def _utc(value):
    _require(isinstance(value, str) and len(value) <= 64, "invalid_fetched_at")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise _Blocked("invalid_fetched_at") from None
    _require(stamp.tzinfo is not None and stamp.utcoffset().total_seconds() == 0,
             "fetched_at_must_be_utc")
    return stamp


def _listing_id(value):
    # Only bounded ASCII alphanumeric IDs are recognized as unsupported.
    # Malformed IDs still invalidate the entire snapshot. Never coerce them.
    if (isinstance(value, str) and len(value) <= 32
            and re.fullmatch(r"[A-Za-z0-9]+", value) and re.search(r"[A-Za-z]", value)):
        return value
    return _pd_no(value)


def _row_id(row):
    _require(isinstance(row, dict), "malformed_listing_row")
    pd_no = _listing_id(row.get("pd_no"))
    _require(isinstance(row.get("name"), str) and row["name"].strip(), "malformed_listing_row")
    _require(row.get("small_category_code") in (None, "", CATEGORY_CODE), "wrong_row_category")
    url = row.get("url")
    _require(isinstance(url, str) and len(url) <= 2048, "invalid_product_url")
    try:
        parsed = urlsplit(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        valid = (parsed.scheme == "https" and parsed.netloc == "www.daisomall.co.kr"
                 and parsed.path == "/pd/pdr/SCR_PDR_0001" and not parsed.fragment
                 and params.get("pdNo") == [pd_no])
    except ValueError:
        valid = False
    _require(valid, "product_url_id_mismatch")
    for key in ("price_krw", "review_count", "total_orders"):
        if key in row:
            _require(type(row[key]) is int and row[key] >= 0, "malformed_listing_row")
    if row.get("rating") is not None:
        value = row["rating"]
        _require(type(value) in (int, float) and (type(value) is int or math.isfinite(value)) and value >= 0,
                 "malformed_listing_row")
    if "sold_out" in row:
        _require(type(row["sold_out"]) is bool, "malformed_listing_row")
    return pd_no


def _source(catalog, now, max_age_hours):
    _require(isinstance(catalog, dict), "invalid_catalog")
    previous = catalog.get("kept_previous", [])
    _require(isinstance(previous, list), "invalid_kept_previous")
    _require("body" not in previous, "body_kept_previous")
    errors = catalog.get("errors", [])
    _require(isinstance(errors, list), "invalid_catalog_errors")
    for error in errors:
        _require(isinstance(error, (dict, str)), "invalid_catalog_errors")
        if isinstance(error, dict):
            affected = (error.get("desk") == "body" or error.get("code") == CATEGORY_CODE
                        or error.get("category_code") == CATEGORY_CODE
                        or error.get("url") == SOURCE_URL or error.get("source_url") == SOURCE_URL)
        else:
            affected = "body" in error.lower() or CATEGORY_CODE in error or SOURCE_URL in error
        _require(not affected, "body_category_fetch_error")
    desks = catalog.get("desks")
    _require(isinstance(desks, dict) and isinstance(desks.get("body"), dict), "missing_body_desk")
    body = desks["body"]
    _require(not body.get("kept_previous_because"), "body_kept_previous")
    categories = body.get("categories")
    _require(isinstance(categories, list) and len(categories) <= 1000, "invalid_categories")
    _require(all(isinstance(cat, dict) for cat in categories), "invalid_categories")
    matches = [cat for cat in categories if cat.get("code") == CATEGORY_CODE or cat.get("url") == SOURCE_URL]
    _require(len(matches) == 1, "missing_or_duplicate_category")
    cat = matches[0]
    _require(cat.get("code") == CATEGORY_CODE and cat.get("url") == SOURCE_URL, "category_source_mismatch")
    _require(cat.get("fetch_status") == "ok" and cat.get("complete") is True, "incomplete_category_source")
    stamp = _utc(cat.get("fetched_at"))
    age = (now - stamp).total_seconds()
    _require(age >= 0, "future_category_source")
    _require(age <= max_age_hours * 3600, "stale_category_source")
    rows = cat.get("listing_products")
    _require(isinstance(rows, list) and len(rows) <= MAX_SOURCE_ROWS, "invalid_listing_products")
    current, source_indices, skipped, seen = {}, {}, [], set()
    for index, row in enumerate(rows):
        pd_no = _row_id(row)
        _require(pd_no not in seen, "duplicate_listing_product_id")
        seen.add(pd_no)
        if not re.fullmatch(r"[1-9][0-9]*", pd_no):
            skipped.append({"pd_no": pd_no, "source_index": index, "url": row["url"],
                            "reason": "unsupported_alphanumeric_product_id",
                            "category_code": CATEGORY_CODE, "source_url": SOURCE_URL,
                            "fetched_at": stamp.isoformat()})
            continue
        current[pd_no] = row
        source_indices[pd_no] = index
    return current, stamp, source_indices, skipped


def _history(registry):
    _require(isinstance(registry, dict) and isinstance(registry.get("items"), list), "invalid_registry")
    excluded = set()
    for item in registry["items"]:
        _require(isinstance(item, dict), "invalid_registry_item")
        excluded.add(_pd_no(item.get("pd_no")))
        if item.get("source") == SELECTION_SOURCE or item.get("selection_source") == SELECTION_SOURCE:
            _require(isinstance(item.get("status"), str) and item["status"] in _SETTLED,
                     "uncertain_fallback_outcome")
    if QUEUE_KEY not in registry:
        return [], excluded
    queue = registry[QUEUE_KEY]
    _require(isinstance(queue, dict), "malformed_existing_queue")
    _require(type(queue.get("schema_version")) is int and queue["schema_version"] == SCHEMA_VERSION
             and queue.get("category_code") == CATEGORY_CODE and queue.get("source_url") == SOURCE_URL
             and queue.get("selection_source") == SELECTION_SOURCE, "existing_queue_binding_mismatch")
    order = queue.get("ordered_pd_nos")
    _require(isinstance(order, list) and len(order) <= MAX_QUEUE_IDS, "malformed_existing_queue")
    validated = [_pd_no(value) for value in order]
    _require(all(type(value) is str for value in order) and len(set(validated)) == len(validated),
             "malformed_existing_queue")
    return validated, excluded


def prepare_queue(catalog, registry, now=None, max_age_hours=24):
    """Return (candidate_rows, blocked_reason), changing only the queue on success.

    Full ID history is append-only, bounded at 10,000 IDs, and never a source
    of stale row data. Exhaustion returns ([], None). Invalid or uncertain input
    returns ([], reason), leaving registry unchanged. No I/O or network calls.
    """
    try:
        _require(type(max_age_hours) in (int, float) and max_age_hours > 0
                 and (type(max_age_hours) is int or math.isfinite(max_age_hours)),
                 "invalid_max_age_hours")
        now = datetime.now(timezone.utc) if now is None else now
        _require(isinstance(now, datetime) and now.tzinfo is not None
                 and now.utcoffset() is not None, "invalid_now")
        current, stamp, source_indices, skipped = _source(catalog, now, max_age_hours)
        order, excluded = _history(registry)
        known = set(order)
        order = order + [pd_no for pd_no in current if pd_no not in known]
        _require(len(order) <= MAX_QUEUE_IDS, "queue_capacity_exceeded")
        candidates = []
        for index, pd_no in enumerate(order):
            if pd_no in excluded or pd_no not in current:
                continue
            # Construct explicitly: never trust grades, scores or approval
            # claims supplied by a listing row.
            fresh = {key: current[pd_no][key] for key in
                     ("name", "price_krw", "rating", "review_count", "total_orders", "small_category",
                      "small_category_code", "sold_out", "url", "image_url") if key in current[pd_no]}
            candidates.append({**fresh, "pd_no": pd_no, "grade": "-", "selection_source": SELECTION_SOURCE,
                               "_priority": {"source": SELECTION_SOURCE, "category_code": CATEGORY_CODE,
                                             "source_url": SOURCE_URL, "fetched_at": stamp.isoformat(),
                                             "status": "draft_only_category_source_order",
                                             "queue_index": index, "source_index": source_indices[pd_no],
                                             "score": None, "name": current[pd_no]["name"],
                                             "unsupported_listing_products": skipped}})
        registry[QUEUE_KEY] = {"schema_version": SCHEMA_VERSION, "category_code": CATEGORY_CODE,
                               "source_url": SOURCE_URL, "selection_source": SELECTION_SOURCE,
                               "ordered_pd_nos": order, "unsupported_listing_products": skipped}
        return candidates, None
    except _Blocked as exc:
        return [], str(exc)
